"""
Gestor de risco para o bot de scalping alavancado.
Controla tamanho de posicao, circuit breaker e calculo de TP/SL.
"""

from datetime import date, datetime
from typing import Optional

import pandas as pd
from loguru import logger

from config import (
    ALAVANCAGEM,
    PERDA_MAXIMA_DIARIA,
    RISCO_POR_TRADE,
    RR_ALVO,
    TAXA_MAKER,
    TAXA_TAKER,
)
from database import (
    get_connection,
    update_trade_resultado,
)


class RiskManager:
    """Gerencia risco de cada trade e limites diarios."""

    def __init__(self, binance_client, db_module=None):
        """
        Args:
            binance_client: Instancia de BinanceClient.
            db_module: Modulo database (para testes/injecao). Se None, usa o modulo global.
        """
        self.client = binance_client
        self.db = db_module

        self.risco_por_trade = RISCO_POR_TRADE
        self.perda_maxima_diaria = PERDA_MAXIMA_DIARIA
        self.taxa_maker = TAXA_MAKER
        self.taxa_taker = TAXA_TAKER
        self.rr_alvo = RR_ALVO
        self.alavancagem = ALAVANCAGEM

        logger.info(
            "RiskManager inicializado | risco_trade={}% | perda_max_dia={}% | RR={}",
            self.risco_por_trade * 100,
            self.perda_maxima_diaria * 100,
            self.rr_alvo,
        )

    # ------------------------------------------------------------------ #
    #  Calculo de posicao
    # ------------------------------------------------------------------ #

    def calcular_posicao(
        self,
        par: str,
        preco_entrada: float,
        preco_sl: float,
        saldo_disponivel: float,
    ) -> dict:
        """Calcula quantidade ideal baseada no risco por trade.

        Args:
            par: Par de negociacao (ex: BTC/USDT).
            preco_entrada: Preco de entrada planejado.
            preco_sl: Preco de stop loss.
            saldo_disponivel: Saldo livre em USDT.

        Returns:
            Dict com quantidade, margem_necessaria, risco_usd, notional.
        """
        alavancagem = self.alavancagem.get(par, 10)
        risco_usd = saldo_disponivel * self.risco_por_trade
        distancia_sl = abs(preco_entrada - preco_sl)

        if distancia_sl <= 0:
            logger.error("Distancia SL invalida para {}: entrada={} sl={}", par, preco_entrada, preco_sl)
            return {"quantidade": 0, "margem_necessaria": 0, "risco_usd": 0, "notional": 0}

        quantidade = risco_usd / distancia_sl
        notional = quantidade * preco_entrada
        margem_necessaria = notional / alavancagem

        if margem_necessaria > saldo_disponivel:
            quantidade = (saldo_disponivel * alavancagem) / preco_entrada
            notional = quantidade * preco_entrada
            margem_necessaria = notional / alavancagem
            logger.warning(
                "Posicao ajustada por margem insuficiente em {} | qty={:.6f}",
                par, quantidade,
            )

        logger.info(
            "Posicao calculada {} | qty={:.6f} | margem={:.2f} | risco={:.2f} | notional={:.2f}",
            par, quantidade, margem_necessaria, risco_usd, notional,
        )

        return {
            "quantidade": quantidade,
            "margem_necessaria": margem_necessaria,
            "risco_usd": risco_usd,
            "notional": notional,
        }

    # ------------------------------------------------------------------ #
    #  Calculo de TP (2:1 liquido de taxas)
    # ------------------------------------------------------------------ #

    def calcular_tp(
        self,
        preco_entrada: float,
        preco_sl: float,
        direcao: str,
        notional: float,
    ) -> float:
        """Calcula preco de TP para entregar RR_ALVO liquido de taxas.

        Args:
            preco_entrada: Preco de entrada.
            preco_sl: Preco de stop loss.
            direcao: 'LONG' ou 'SHORT'.
            notional: Valor nocional da posicao.

        Returns:
            Preco de take profit.
        """
        quantidade = notional / preco_entrada

        # Taxas no cenario de perda: entrada limit (maker) + SL market (taker)
        taxas_perda = notional * (self.taxa_maker + self.taxa_taker)
        # Taxas no cenario de ganho: entrada limit (maker) + TP limit (maker)
        taxas_ganho = notional * (self.taxa_maker + self.taxa_maker)

        perda_bruta = abs(preco_entrada - preco_sl) * quantidade
        perda_liquida = perda_bruta + taxas_perda

        lucro_liquido_alvo = perda_liquida * self.rr_alvo
        lucro_bruto_necessario = lucro_liquido_alvo + taxas_ganho

        distancia_tp = lucro_bruto_necessario / quantidade

        if direcao.upper() == "LONG":
            tp = preco_entrada + distancia_tp
        else:
            tp = preco_entrada - distancia_tp

        logger.info(
            "TP calculado {} {} | entrada={} | sl={} | tp={:.4f} | RR_liquido={}",
            direcao, "+" if direcao.upper() == "LONG" else "-",
            preco_entrada, preco_sl, tp, self.rr_alvo,
        )

        return tp

    # ------------------------------------------------------------------ #
    #  Circuit breaker
    # ------------------------------------------------------------------ #

    def verificar_circuit_breaker(self) -> bool:
        """Verifica se a perda diaria atingiu o limite.

        Returns:
            True se o circuit breaker foi acionado (deve parar de operar).
        """
        hoje = date.today()
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT lucro_total FROM performance_diaria WHERE data = %s;",
                    (hoje,),
                )
                row = cur.fetchone()
        except Exception as e:
            logger.error("Erro ao verificar circuit breaker: {}", e)
            return False
        finally:
            conn.close()

        if not row:
            return False

        lucro_total_pct = row[0]  # ja em percentual

        saldo = self.client.get_balance()
        if not saldo or saldo["total"] <= 0:
            logger.warning("Nao foi possivel obter saldo para circuit breaker")
            return False

        perda_pct = abs(lucro_total_pct) / saldo["total"] if lucro_total_pct < 0 else 0

        if perda_pct >= self.perda_maxima_diaria:
            logger.warning(
                "CIRCUIT BREAKER ACIONADO | Perda diaria: {:.2f}% >= {:.2f}%",
                perda_pct * 100, self.perda_maxima_diaria * 100,
            )
            return True

        if perda_pct >= 0.04:
            logger.warning(
                "Atencao: Perda diaria proxima do limite | {:.2f}% de {:.2f}%",
                perda_pct * 100, self.perda_maxima_diaria * 100,
            )

        return False

    # ------------------------------------------------------------------ #
    #  Verificacao geral para operar
    # ------------------------------------------------------------------ #

    def pode_operar(self, par: str = None) -> dict:
        """Verifica se o bot pode abrir uma nova posicao.

        Args:
            par: Par a verificar (opcional, para checar posicao duplicada).

        Returns:
            Dict com { pode: bool, motivo: str }.
        """
        # Circuit breaker
        if self.verificar_circuit_breaker():
            return {"pode": False, "motivo": "Circuit breaker acionado - perda diaria maxima atingida"}

        # Posicao aberta no par
        if par:
            posicoes = self.client.get_open_positions()
            for pos in posicoes:
                symbol = pos.get("symbol", "")
                contracts = float(pos.get("contracts", 0))
                if symbol == par and contracts > 0:
                    return {"pode": False, "motivo": f"Ja existe posicao aberta em {par}"}

        # Saldo minimo
        saldo = self.client.get_balance()
        if not saldo:
            return {"pode": False, "motivo": "Nao foi possivel consultar saldo"}

        if saldo["free"] < 10:
            return {"pode": False, "motivo": f"Saldo insuficiente: {saldo['free']:.2f} USDT"}

        return {"pode": True, "motivo": "OK"}

    # ------------------------------------------------------------------ #
    #  SL baseado na EMA100
    # ------------------------------------------------------------------ #

    def calcular_sl_por_ema100(self, df_candles: pd.DataFrame, direcao: str) -> float:
        """Calcula stop loss baseado na EMA100 com margem de seguranca.

        Args:
            df_candles: DataFrame com coluna 'ema100'.
            direcao: 'LONG' ou 'SHORT'.

        Returns:
            Preco de stop loss.
        """
        ema100 = df_candles["ema100"].iloc[-1]
        margem = ema100 * 0.001  # 0.1%

        if direcao.upper() == "LONG":
            sl = ema100 - margem
        else:
            sl = ema100 + margem

        logger.info(
            "SL por EMA100 | direcao={} | ema100={:.4f} | sl={:.4f}",
            direcao, ema100, sl,
        )
        return sl

    # ------------------------------------------------------------------ #
    #  Registro de resultado
    # ------------------------------------------------------------------ #

    def registrar_resultado_trade(
        self,
        trade_id: int,
        preco_saida: float,
        resultado: str,
        preco_entrada: float,
        quantidade: float,
        direcao: str,
    ) -> None:
        """Atualiza trade no banco e recalcula performance diaria.

        Args:
            trade_id: ID do trade no banco.
            preco_saida: Preco de saida efetivo.
            resultado: 'WIN' ou 'LOSS'.
            preco_entrada: Preco de entrada do trade.
            quantidade: Quantidade negociada.
            direcao: 'LONG' ou 'SHORT'.
        """
        notional = quantidade * preco_entrada

        if direcao.upper() == "LONG":
            lucro_bruto = (preco_saida - preco_entrada) * quantidade
        else:
            lucro_bruto = (preco_entrada - preco_saida) * quantidade

        # Taxas: entrada maker + saida (maker se TP, taker se SL/market)
        if resultado == "WIN":
            taxas = notional * (self.taxa_maker + self.taxa_maker)
        else:
            taxas = notional * (self.taxa_maker + self.taxa_taker)

        lucro_usd = lucro_bruto - taxas

        saldo = self.client.get_balance()
        saldo_total = saldo["total"] if saldo and saldo["total"] > 0 else 1
        lucro_pct = lucro_usd / saldo_total

        update_trade_resultado(
            trade_id=trade_id,
            preco_saida=preco_saida,
            resultado=resultado,
            lucro_usd=lucro_usd,
            lucro_pct=lucro_pct,
            taxas_pagas=taxas,
        )

        self._atualizar_performance_diaria()

        logger.info(
            "Resultado registrado trade #{} | {} | lucro={:.2f} USD ({:.2f}%) | taxas={:.2f}",
            trade_id, resultado, lucro_usd, lucro_pct * 100, taxas,
        )

    def _atualizar_performance_diaria(self) -> None:
        """Recalcula e salva performance do dia atual."""
        hoje = date.today()
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        COUNT(*) as total,
                        COALESCE(SUM(CASE WHEN resultado = 'WIN' THEN 1 ELSE 0 END), 0) as wins,
                        COALESCE(SUM(CASE WHEN resultado = 'LOSS' THEN 1 ELSE 0 END), 0) as losses,
                        COALESCE(SUM(lucro_usd), 0) as lucro_total,
                        COALESCE(MIN(lucro_usd), 0) as maior_perda
                    FROM trades
                    WHERE DATE(timestamp_entrada) = %s
                      AND resultado IN ('WIN', 'LOSS');
                    """,
                    (hoje,),
                )
                row = cur.fetchone()

                total, wins, losses, lucro_total, maior_perda = row
                win_rate = (wins / total * 100) if total > 0 else 0

                cur.execute(
                    """
                    INSERT INTO performance_diaria (data, total_trades, wins, losses, win_rate, lucro_total, maior_perda)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (data) DO UPDATE SET
                        total_trades = EXCLUDED.total_trades,
                        wins = EXCLUDED.wins,
                        losses = EXCLUDED.losses,
                        win_rate = EXCLUDED.win_rate,
                        lucro_total = EXCLUDED.lucro_total,
                        maior_perda = EXCLUDED.maior_perda;
                    """,
                    (hoje, total, wins, losses, win_rate, lucro_total, maior_perda),
                )
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error("Erro ao atualizar performance diaria: {}", e)
        finally:
            conn.close()

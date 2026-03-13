"""
Executor de ordens para o bot de scalping alavancado.
Gerencia abertura, monitoramento e fechamento de posicoes.
"""

import time
from datetime import date, datetime
from typing import Optional

import pandas as pd
from loguru import logger

from config import ALAVANCAGEM, TIMEFRAME
from database import get_connection, insert_trade


class Trader:
    """Executa sinais de trading e gerencia posicoes abertas."""

    def __init__(self, binance_client, risk_manager, db_module=None):
        """
        Args:
            binance_client: Instancia de BinanceClient.
            risk_manager: Instancia de RiskManager.
            db_module: Modulo database (para testes/injecao).
        """
        self.client = binance_client
        self.risk = risk_manager
        self.db = db_module
        self.posicoes_abertas: dict = {}

        logger.info("Trader inicializado")

    # ------------------------------------------------------------------ #
    #  Execucao de sinais
    # ------------------------------------------------------------------ #

    def executar_sinal(
        self,
        sinal: str,
        par: str,
        df_candles: pd.DataFrame,
    ) -> dict:
        """Executa um sinal de trading.

        Args:
            sinal: 'LONG', 'SHORT' ou 'NEUTRO'.
            par: Par de negociacao.
            df_candles: DataFrame com indicadores calculados (inclui ema100).

        Returns:
            Dict com resultado da operacao.
        """
        if sinal.upper() == "NEUTRO":
            return {"sucesso": False, "motivo": "Sinal neutro, sem operacao"}

        # Verificar se pode operar
        verificacao = self.risk.pode_operar(par)
        if not verificacao["pode"]:
            logger.warning("Nao pode operar {}: {}", par, verificacao["motivo"])
            return {"sucesso": False, "motivo": verificacao["motivo"]}

        direcao = sinal.upper()

        # Calcular SL via EMA100
        try:
            preco_sl = self.risk.calcular_sl_por_ema100(df_candles, direcao)
        except Exception as e:
            logger.error("Erro ao calcular SL para {}: {}", par, e)
            return {"sucesso": False, "motivo": f"Erro ao calcular SL: {e}"}

        # Obter preco atual como referencia para entrada
        candles = self.client.get_candles(par, TIMEFRAME, limite=1)
        if not candles:
            return {"sucesso": False, "motivo": "Nao foi possivel obter preco atual"}

        preco_entrada = candles[-1][4]  # close do ultimo candle

        # Validar SL faz sentido para a direcao
        if direcao == "LONG" and preco_sl >= preco_entrada:
            return {"sucesso": False, "motivo": f"SL ({preco_sl}) >= entrada ({preco_entrada}) para LONG"}
        if direcao == "SHORT" and preco_sl <= preco_entrada:
            return {"sucesso": False, "motivo": f"SL ({preco_sl}) <= entrada ({preco_entrada}) para SHORT"}

        # Obter saldo
        saldo = self.client.get_balance()
        if not saldo:
            return {"sucesso": False, "motivo": "Nao foi possivel obter saldo"}

        # Calcular posicao
        posicao = self.risk.calcular_posicao(par, preco_entrada, preco_sl, saldo["free"])
        if posicao["quantidade"] <= 0:
            return {"sucesso": False, "motivo": "Quantidade calculada invalida"}

        quantidade = posicao["quantidade"]
        notional = posicao["notional"]

        # Calcular TP
        preco_tp = self.risk.calcular_tp(preco_entrada, preco_sl, direcao, notional)

        # Definir alavancagem
        alavancagem = ALAVANCAGEM.get(par, 10)
        if not self.client.set_leverage(par, alavancagem):
            return {"sucesso": False, "motivo": "Falha ao definir alavancagem"}

        # Colocar ordem LIMIT de entrada
        side_entrada = "buy" if direcao == "LONG" else "sell"
        ordem_entrada = self.client.create_limit_order(par, side_entrada, quantidade, preco_entrada)
        if not ordem_entrada:
            return {"sucesso": False, "motivo": "Falha ao criar ordem de entrada"}

        order_id_entrada = ordem_entrada.get("id")

        # Aguardar preenchimento (polling ate 30s)
        preenchida = self._aguardar_preenchimento(par, order_id_entrada, timeout=30)

        if not preenchida:
            self.client.cancel_order(par, order_id_entrada)
            logger.info("Ordem de entrada cancelada por timeout: {} {}", par, order_id_entrada)
            return {"sucesso": False, "motivo": "Ordem de entrada nao preenchida em 30s"}

        # Obter preco efetivo de entrada
        try:
            ordem_info = self.client.exchange.fetch_order(order_id_entrada, par)
            preco_entrada_efetivo = ordem_info.get("average", preco_entrada)
        except Exception:
            preco_entrada_efetivo = preco_entrada

        # Colocar TP (LIMIT) e SL (STOP MARKET)
        side_saida = "sell" if direcao == "LONG" else "buy"

        # TP como ordem LIMIT
        ordem_tp = self.client.create_limit_order(par, side_saida, quantidade, preco_tp)

        # SL como STOP MARKET
        ordem_sl = self._criar_stop_market(par, side_saida, quantidade, preco_sl)

        # Salvar trade no banco
        try:
            trade_id = insert_trade(
                par=par,
                direcao=direcao,
                alavancagem=alavancagem,
                preco_entrada=preco_entrada_efetivo,
                sl=preco_sl,
                tp=preco_tp,
                quantidade=quantidade,
                motivo_entrada=f"Sinal {direcao}",
            )
        except Exception as e:
            logger.error("Erro ao salvar trade no banco: {}", e)
            trade_id = None

        # Registrar posicao aberta
        self.posicoes_abertas[par] = {
            "trade_id": trade_id,
            "direcao": direcao,
            "preco_entrada": preco_entrada_efetivo,
            "sl": preco_sl,
            "tp": preco_tp,
            "quantidade": quantidade,
            "order_id_tp": ordem_tp.get("id") if ordem_tp else None,
            "order_id_sl": ordem_sl.get("id") if ordem_sl else None,
            "timestamp": datetime.utcnow(),
        }

        logger.info(
            "Trade aberto #{} | {} {} | entrada={} | sl={} | tp={} | qty={:.6f}",
            trade_id, direcao, par, preco_entrada_efetivo, preco_sl, preco_tp, quantidade,
        )

        return {
            "sucesso": True,
            "trade_id": trade_id,
            "preco_entrada": preco_entrada_efetivo,
            "sl": preco_sl,
            "tp": preco_tp,
            "quantidade": quantidade,
        }

    # ------------------------------------------------------------------ #
    #  Monitoramento de posicoes
    # ------------------------------------------------------------------ #

    def monitorar_posicoes(self, candles_atuais: dict[str, pd.DataFrame] = None) -> None:
        """Verifica posicoes abertas e aplica saida antecipada por cruzamento EMA25.

        Args:
            candles_atuais: Dict par -> DataFrame com indicadores (ema9, ema25).
        """
        if not self.posicoes_abertas:
            return

        for par, pos in list(self.posicoes_abertas.items()):
            # Verificar se posicao ainda existe na exchange
            posicoes_exchange = self.client.get_open_positions()
            pos_ativa = False
            for p in posicoes_exchange:
                if p.get("symbol") == par and float(p.get("contracts", 0)) > 0:
                    pos_ativa = True
                    break

            if not pos_ativa:
                # Posicao foi fechada (TP ou SL atingido)
                logger.info("Posicao em {} fechada externamente (TP/SL)", par)
                self._finalizar_posicao_externa(par, pos)
                continue

            # Verificar cruzamento EMA25 contra a posicao
            if candles_atuais and par in candles_atuais:
                df = candles_atuais[par]
                if len(df) >= 2 and "ema9" in df.columns and "ema25" in df.columns:
                    ema9_atual = df["ema9"].iloc[-1]
                    ema9_anterior = df["ema9"].iloc[-2]
                    ema25_atual = df["ema25"].iloc[-1]
                    ema25_anterior = df["ema25"].iloc[-2]

                    cruzou_contra = False
                    if pos["direcao"] == "LONG":
                        # EMA9 cruzou abaixo da EMA25
                        if ema9_anterior >= ema25_anterior and ema9_atual < ema25_atual:
                            cruzou_contra = True
                    else:
                        # EMA9 cruzou acima da EMA25
                        if ema9_anterior <= ema25_anterior and ema9_atual > ema25_atual:
                            cruzou_contra = True

                    if cruzou_contra:
                        logger.warning(
                            "Cruzamento EMA25 contra posicao {} {} - saida antecipada",
                            pos["direcao"], par,
                        )
                        self.fechar_posicao(par, motivo="Cruzamento EMA25 contra")

    def _finalizar_posicao_externa(self, par: str, pos: dict) -> None:
        """Trata posicao fechada externamente (TP ou SL atingido na exchange)."""
        trade_id = pos.get("trade_id")
        if not trade_id:
            del self.posicoes_abertas[par]
            return

        # Buscar preco de saida do trade no banco ou via ultima ordem
        try:
            conn = get_connection()
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT preco_saida, resultado FROM trades WHERE id = %s;",
                    (trade_id,),
                )
                row = cur.fetchone()
            conn.close()

            if row and row[0] is not None:
                # Ja foi atualizado
                del self.posicoes_abertas[par]
                return
        except Exception as e:
            logger.error("Erro ao consultar trade #{}: {}", trade_id, e)

        # Obter preco atual como aproximacao
        candles = self.client.get_candles(par, TIMEFRAME, limite=1)
        preco_saida = candles[-1][4] if candles else pos["preco_entrada"]

        if pos["direcao"] == "LONG":
            resultado = "WIN" if preco_saida >= pos["tp"] else "LOSS"
        else:
            resultado = "WIN" if preco_saida <= pos["tp"] else "LOSS"

        self.risk.registrar_resultado_trade(
            trade_id=trade_id,
            preco_saida=preco_saida,
            resultado=resultado,
            preco_entrada=pos["preco_entrada"],
            quantidade=pos["quantidade"],
            direcao=pos["direcao"],
        )

        del self.posicoes_abertas[par]

    # ------------------------------------------------------------------ #
    #  Fechar posicao
    # ------------------------------------------------------------------ #

    def fechar_posicao(self, par: str, motivo: str = "Manual") -> None:
        """Fecha posicao a mercado e cancela ordens pendentes.

        Args:
            par: Par de negociacao.
            motivo: Motivo do fechamento.
        """
        pos = self.posicoes_abertas.get(par)
        if not pos:
            logger.warning("Nenhuma posicao aberta em {} para fechar", par)
            return

        # Fechar posicao a mercado
        ordem_close = self.client.close_position(par)

        # Cancelar ordens pendentes (TP e SL)
        if pos.get("order_id_tp"):
            self.client.cancel_order(par, pos["order_id_tp"])
        if pos.get("order_id_sl"):
            self.client.cancel_order(par, pos["order_id_sl"])

        # Obter preco de saida
        preco_saida = None
        if ordem_close:
            preco_saida = ordem_close.get("average") or ordem_close.get("price")

        if not preco_saida:
            candles = self.client.get_candles(par, TIMEFRAME, limite=1)
            preco_saida = candles[-1][4] if candles else pos["preco_entrada"]

        # Determinar resultado
        if pos["direcao"] == "LONG":
            resultado = "WIN" if preco_saida > pos["preco_entrada"] else "LOSS"
        else:
            resultado = "WIN" if preco_saida < pos["preco_entrada"] else "LOSS"

        # Registrar resultado
        trade_id = pos.get("trade_id")
        if trade_id:
            self.risk.registrar_resultado_trade(
                trade_id=trade_id,
                preco_saida=preco_saida,
                resultado=resultado,
                preco_entrada=pos["preco_entrada"],
                quantidade=pos["quantidade"],
                direcao=pos["direcao"],
            )

        logger.info(
            "Posicao fechada {} {} | motivo={} | resultado={} | saida={}",
            pos["direcao"], par, motivo, resultado, preco_saida,
        )

        del self.posicoes_abertas[par]

    # ------------------------------------------------------------------ #
    #  Consultas
    # ------------------------------------------------------------------ #

    def get_posicoes_abertas(self) -> list[dict]:
        """Retorna lista de posicoes abertas com P&L atual."""
        resultado = []
        for par, pos in self.posicoes_abertas.items():
            candles = self.client.get_candles(par, TIMEFRAME, limite=1)
            preco_atual = candles[-1][4] if candles else pos["preco_entrada"]

            if pos["direcao"] == "LONG":
                pnl = (preco_atual - pos["preco_entrada"]) * pos["quantidade"]
            else:
                pnl = (pos["preco_entrada"] - preco_atual) * pos["quantidade"]

            resultado.append({
                "par": par,
                "trade_id": pos.get("trade_id"),
                "direcao": pos["direcao"],
                "preco_entrada": pos["preco_entrada"],
                "preco_atual": preco_atual,
                "sl": pos["sl"],
                "tp": pos["tp"],
                "quantidade": pos["quantidade"],
                "pnl_usd": pnl,
                "timestamp": pos.get("timestamp"),
            })

        return resultado

    def get_estatisticas_dia(self) -> dict:
        """Retorna estatisticas do dia atual.

        Returns:
            Dict com total_trades, wins, losses, win_rate, lucro_total,
            maior_ganho, maior_perda.
        """
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
                        COALESCE(MAX(lucro_usd), 0) as maior_ganho,
                        COALESCE(MIN(lucro_usd), 0) as maior_perda
                    FROM trades
                    WHERE DATE(timestamp_entrada) = %s
                      AND resultado IN ('WIN', 'LOSS');
                    """,
                    (hoje,),
                )
                row = cur.fetchone()
        except Exception as e:
            logger.error("Erro ao consultar estatisticas do dia: {}", e)
            return {
                "total_trades": 0, "wins": 0, "losses": 0,
                "win_rate": 0, "lucro_total": 0,
                "maior_ganho": 0, "maior_perda": 0,
            }
        finally:
            conn.close()

        total, wins, losses, lucro_total, maior_ganho, maior_perda = row
        win_rate = (wins / total * 100) if total > 0 else 0

        return {
            "total_trades": total,
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
            "lucro_total": lucro_total,
            "maior_ganho": maior_ganho,
            "maior_perda": maior_perda,
        }

    # ------------------------------------------------------------------ #
    #  Helpers internos
    # ------------------------------------------------------------------ #

    def _aguardar_preenchimento(
        self, par: str, order_id: str, timeout: int = 30
    ) -> bool:
        """Aguarda ordem ser preenchida via polling.

        Args:
            par: Par de negociacao.
            order_id: ID da ordem.
            timeout: Tempo maximo em segundos.

        Returns:
            True se a ordem foi preenchida.
        """
        inicio = time.time()
        while time.time() - inicio < timeout:
            try:
                ordem = self.client.exchange.fetch_order(order_id, par)
                status = ordem.get("status", "")
                if status == "closed":
                    logger.info("Ordem {} preenchida em {}", order_id, par)
                    return True
                if status == "canceled" or status == "expired":
                    logger.info("Ordem {} cancelada/expirada em {}", order_id, par)
                    return False
            except Exception as e:
                logger.error("Erro ao verificar ordem {}: {}", order_id, e)

            time.sleep(1)

        return False

    def _criar_stop_market(
        self, par: str, side: str, quantidade: float, preco_stop: float
    ) -> Optional[dict]:
        """Cria ordem STOP MARKET.

        Args:
            par: Par de negociacao.
            side: 'buy' ou 'sell'.
            quantidade: Quantidade.
            preco_stop: Preco de ativacao do stop.

        Returns:
            Dict da ordem ou None em caso de erro.
        """
        try:
            order = self.client.exchange.create_order(
                symbol=par,
                type="STOP_MARKET",
                side=side,
                amount=quantidade,
                params={
                    "stopPrice": preco_stop,
                    "reduceOnly": True,
                },
            )
            logger.info(
                "Stop market criado: {} {} {} @ stop={}",
                side, quantidade, par, preco_stop,
            )
            return order
        except Exception as e:
            logger.error("Erro ao criar stop market: {}", e)
            return None

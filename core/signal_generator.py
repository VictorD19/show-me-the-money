"""
Gerador de sinais de scalping.

Combina indicadores tecnicos, modelo ML, sentimento de noticias e
Fear & Greed Index para gerar sinais LONG/SHORT/NEUTRO.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pandas as pd
from loguru import logger

from core.model import ScalpingModel
from core.news_collector import NewsCollector

try:
    from config import CONFIANCA_MINIMA
except ImportError:
    CONFIANCA_MINIMA = 0.65


class SignalGenerator:
    """Gera sinais de entrada combinando analise tecnica, ML e sentimento."""

    # Distancia percentual para considerar "toque" na EMA
    _EMA_TOUCH_PCT = 0.001  # 0.1%

    # Limites de RSI por direcao
    _RSI_LONG = (40, 65)
    _RSI_SHORT = (35, 60)

    # Volume relativo minimo
    _VOL_REL_MIN = 1.2

    # Fear & Greed extremo
    _FG_EXTREME_LOW = 20
    _FG_EXTREME_HIGH = 80

    def __init__(
        self, model: ScalpingModel, news_collector: NewsCollector
    ) -> None:
        """Inicializa o gerador de sinais.

        Args:
            model: Instancia do ScalpingModel.
            news_collector: Instancia do NewsCollector.
        """
        self._model = model
        self._news = news_collector
        self._signal_history: List[Dict[str, Any]] = []
        self._stats = {"total": 0, "long": 0, "short": 0, "neutro": 0}

    # ------------------------------------------------------------------
    # Verificacoes individuais
    # ------------------------------------------------------------------

    def _check_regime(self, features: Dict[str, Any]) -> Optional[str]:
        """Verifica regime de mercado. Retorna regime ou None se LATERAL."""
        regime_code = features.get("regime_encoded", 0)
        regime_map = {0: "LATERAL", 1: "TREND_UP", 2: "TREND_DOWN"}
        regime = regime_map.get(regime_code, "LATERAL")
        if regime == "LATERAL":
            return None
        return regime

    def _check_ema_alignment(
        self, features: Dict[str, Any], direcao: str
    ) -> bool:
        """Verifica alinhamento das EMAs.

        LONG: EMA25 > EMA50 > EMA100
        SHORT: EMA25 < EMA50 < EMA100
        """
        ema25 = features.get("ema25", 0)
        ema50 = features.get("ema50", 0)
        ema100 = features.get("ema100", 0)

        if direcao == "LONG":
            return ema25 > ema50 > ema100
        elif direcao == "SHORT":
            return ema25 < ema50 < ema100
        return False

    def _check_ema_touch(self, features: Dict[str, Any]) -> Optional[str]:
        """Verifica se preco tocou EMA25 ou EMA50 (dentro de 0.1%).

        Returns:
            "EMA25", "EMA50" ou None.
        """
        dist_ema25 = abs(features.get("preco_vs_ema25", 999))
        dist_ema50 = abs(features.get("preco_vs_ema50", 999))

        # preco_vs_ema ja esta em percentual (ex: 0.05 = 0.05%)
        threshold = self._EMA_TOUCH_PCT * 100  # 0.1

        if dist_ema25 <= threshold:
            return "EMA25"
        if dist_ema50 <= threshold:
            return "EMA50"
        return None

    def _check_candle_confirmation(
        self, features: Dict[str, Any], df_candles: pd.DataFrame, direcao: str
    ) -> bool:
        """Verifica se o ultimo candle confirma a direcao.

        LONG: fechou acima da EMA25
        SHORT: fechou abaixo da EMA25
        """
        if df_candles.empty:
            return False

        last_close = df_candles.iloc[-1].get("close", 0)
        ema25 = features.get("ema25", 0)

        if direcao == "LONG":
            return last_close > ema25
        elif direcao == "SHORT":
            return last_close < ema25
        return False

    def _check_rsi(self, features: Dict[str, Any], direcao: str) -> bool:
        """Verifica se RSI esta na faixa adequada."""
        rsi = features.get("rsi", 50)
        if direcao == "LONG":
            return self._RSI_LONG[0] <= rsi <= self._RSI_LONG[1]
        elif direcao == "SHORT":
            return self._RSI_SHORT[0] <= rsi <= self._RSI_SHORT[1]
        return False

    def _check_volume(self, features: Dict[str, Any]) -> bool:
        """Verifica se volume relativo e suficiente (> 1.2x media)."""
        return features.get("volume_relativo", 0) >= self._VOL_REL_MIN

    def _check_model_confidence(
        self, features: Dict[str, Any], direcao: str
    ) -> float:
        """Consulta o modelo ML e retorna confianca.

        Para LONG a confianca e a probabilidade de WIN.
        Para SHORT a confianca e (1 - probabilidade), pois o modelo
        preve probabilidade de um trade vencedor dado as features.
        """
        proba = self._model.predict(features)
        if direcao == "LONG":
            return proba
        elif direcao == "SHORT":
            return 1.0 - proba
        return 0.5

    def _adjust_for_fear_greed(
        self, confianca: float, fear_greed: int
    ) -> float:
        """Ajusta confianca com base no Fear & Greed extremo.

        Extremos (< 20 ou > 80) reduzem a confianca em 15%.
        """
        if fear_greed < self._FG_EXTREME_LOW or fear_greed > self._FG_EXTREME_HIGH:
            logger.debug(
                f"Fear & Greed extremo ({fear_greed}) — reduzindo confianca"
            )
            return confianca * 0.85
        return confianca

    def _adjust_for_sentiment(
        self, confianca: float, sentimento: float, direcao: str
    ) -> float:
        """Ajusta confianca com base no sentimento de noticias.

        Sentimento contrario a direcao reduz confianca.
        Sentimento favoravel aumenta levemente.
        """
        if direcao == "LONG" and sentimento < -0.3:
            return confianca * 0.90
        elif direcao == "SHORT" and sentimento > 0.3:
            return confianca * 0.90
        elif direcao == "LONG" and sentimento > 0.3:
            return min(confianca * 1.05, 1.0)
        elif direcao == "SHORT" and sentimento < -0.3:
            return min(confianca * 1.05, 1.0)
        return confianca

    # ------------------------------------------------------------------
    # Analise principal
    # ------------------------------------------------------------------

    def analyze(
        self,
        par: str,
        df_candles: pd.DataFrame,
        features_dict: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Analise completa e geracao de sinal.

        Args:
            par: Par de trading (ex: "BTC/USDT").
            df_candles: DataFrame com candles OHLCV.
            features_dict: Dict com todas as features calculadas.

        Returns:
            Dict com sinal, confianca, motivo e detalhes.
        """
        resultado = {
            "sinal": "NEUTRO",
            "confianca": 0.0,
            "motivo": "",
            "ema_alinhada": False,
            "toque_ema": None,
            "regime": "LATERAL",
            "fear_greed": 50,
            "sentimento": 0.0,
            "funding_rate": features_dict.get("funding_rate", 0.0),
            "timestamp": datetime.now(timezone.utc),
        }

        motivos_rejeicao: List[str] = []

        # 1. Verificar regime
        regime = self._check_regime(features_dict)
        if regime is None:
            resultado["motivo"] = "Mercado LATERAL — sem operacao"
            self._record_signal(resultado)
            return resultado
        resultado["regime"] = regime

        # Determinar direcao baseada no regime
        direcao = "LONG" if regime == "TREND_UP" else "SHORT"

        # 2. Verificar alinhamento das EMAs
        ema_alinhada = self._check_ema_alignment(features_dict, direcao)
        resultado["ema_alinhada"] = ema_alinhada
        if not ema_alinhada:
            motivos_rejeicao.append("EMAs desalinhadas")

        # 3. Verificar toque na EMA
        toque_ema = self._check_ema_touch(features_dict)
        resultado["toque_ema"] = toque_ema
        if toque_ema is None:
            motivos_rejeicao.append("Preco longe das EMAs")

        # 4. Verificar candle de confirmacao
        candle_ok = self._check_candle_confirmation(
            features_dict, df_candles, direcao
        )
        if not candle_ok:
            motivos_rejeicao.append("Sem confirmacao de candle")

        # 5. Verificar RSI
        rsi_ok = self._check_rsi(features_dict, direcao)
        if not rsi_ok:
            motivos_rejeicao.append(
                f"RSI fora da faixa ({features_dict.get('rsi', 'N/A')})"
            )

        # 6. Verificar volume
        vol_ok = self._check_volume(features_dict)
        if not vol_ok:
            motivos_rejeicao.append(
                f"Volume baixo ({features_dict.get('volume_relativo', 0):.2f}x)"
            )

        # 7. Consultar modelo ML
        ml_confianca = self._check_model_confidence(features_dict, direcao)

        # 8. Fear & Greed
        fg = self._news.get_fear_greed_index()
        fear_greed = fg.get("valor", 50)
        resultado["fear_greed"] = fear_greed
        ml_confianca = self._adjust_for_fear_greed(ml_confianca, fear_greed)

        # 9. Sentimento de noticias
        simbolo = par.split("/")[0] if "/" in par else par
        sentimento = self._news.get_news_sentiment_score(simbolo)
        resultado["sentimento"] = sentimento
        ml_confianca = self._adjust_for_sentiment(ml_confianca, sentimento, direcao)

        resultado["confianca"] = round(ml_confianca, 4)

        # Decisao final
        if motivos_rejeicao:
            resultado["motivo"] = f"Rejeitado: {'; '.join(motivos_rejeicao)}"
            resultado["sinal"] = "NEUTRO"
        elif ml_confianca < CONFIANCA_MINIMA:
            resultado["motivo"] = (
                f"Confianca ML insuficiente ({ml_confianca:.2%} < {CONFIANCA_MINIMA:.0%})"
            )
            resultado["sinal"] = "NEUTRO"
        else:
            resultado["sinal"] = direcao
            resultado["motivo"] = (
                f"{direcao} confirmado — regime {regime}, "
                f"toque {toque_ema}, confianca {ml_confianca:.2%}, "
                f"F&G {fear_greed}, sent {sentimento:.2f}"
            )

        self._record_signal(resultado)
        logger.info(
            f"[{par}] Sinal: {resultado['sinal']} | "
            f"Confianca: {resultado['confianca']:.2%} | "
            f"{resultado['motivo']}"
        )

        return resultado

    # ------------------------------------------------------------------
    # Historico e estatisticas
    # ------------------------------------------------------------------

    def _record_signal(self, sinal: Dict[str, Any]) -> None:
        """Registra sinal no historico."""
        self._signal_history.append(sinal.copy())
        self._stats["total"] += 1
        tipo = sinal["sinal"].lower()
        if tipo in self._stats:
            self._stats[tipo] += 1

        # Manter apenas os ultimos 500 sinais em memoria
        if len(self._signal_history) > 500:
            self._signal_history = self._signal_history[-500:]

    def get_signal_history(self, n: int = 50) -> List[Dict[str, Any]]:
        """Retorna os ultimos N sinais gerados.

        Args:
            n: Quantidade de sinais a retornar.

        Returns:
            Lista dos sinais mais recentes.
        """
        return self._signal_history[-n:]

    def get_stats(self) -> Dict[str, Any]:
        """Retorna estatisticas dos sinais gerados.

        Returns:
            Dict com total, contagem por tipo e win rate (se disponivel).
        """
        total = self._stats["total"]
        operacoes = self._stats["long"] + self._stats["short"]
        return {
            "total_sinais": total,
            "long": self._stats["long"],
            "short": self._stats["short"],
            "neutro": self._stats["neutro"],
            "taxa_operacao": round(operacoes / max(total, 1), 4),
        }

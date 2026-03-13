"""
Modulo de treinamento e retreino do modelo de scalping.

Gerencia:
- Treino inicial com dados historicos
- Retreino semanal automatico
- Avaliacao de performance entre versoes
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd
from loguru import logger

from core.model import ScalpingModel, FEATURE_COLUMNS, TARGET_COLUMN
from core.data_collector import DataCollector

try:
    from config import MODELS_DIR, PARES
except ImportError:
    MODELS_DIR = Path(__file__).resolve().parent.parent / "models"
    PARES = ["BTC/USDT", "ETH/USDT", "XRP/USDT"]

try:
    from database import get_connection
except ImportError:
    get_connection = None
    logger.warning("database.get_connection nao disponivel")

try:
    from sklearn.metrics import (
        accuracy_score,
        precision_score,
        recall_score,
        roc_auc_score,
    )
    _SKLEARN_AVAILABLE = True
except ImportError:
    _SKLEARN_AVAILABLE = False


class ModelTrainer:
    """Gerencia treino e retreino do modelo de scalping."""

    def __init__(
        self,
        model: ScalpingModel,
        data_collector: DataCollector,
        database=None,
    ) -> None:
        """Inicializa o trainer.

        Args:
            model: Instancia do ScalpingModel.
            data_collector: Instancia do DataCollector para baixar dados.
            database: Modulo de banco de dados (nao usado diretamente, apenas para registro).
        """
        self._model = model
        self._data_collector = data_collector
        self._db = database
        MODELS_DIR.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Treino inicial
    # ------------------------------------------------------------------

    def treinar_inicial(self) -> None:
        """Executa treino inicial se nao existe modelo treinado.

        - Verifica se ja existe modelo em MODELS_DIR
        - Se nao: baixa historico de 3 anos, constroi dataset, treina
        - Se sim: carrega e verifica se precisa retreino
        """
        modelos_existentes = list(MODELS_DIR.glob("scalping_model_v*.pkl"))

        if modelos_existentes:
            logger.info(
                "Modelo existente encontrado: {}. Verificando data...",
                modelos_existentes[-1].name,
            )
            if not self._model.retrain_if_needed():
                logger.info("Modelo esta atualizado. Treino inicial nao necessario.")
                return
            logger.info("Modelo desatualizado. Retreinando...")

        logger.info("Iniciando treino inicial — baixando historico de 3 anos...")

        # Baixar dados e treinar para cada par
        all_dfs = []
        for par in PARES:
            logger.info("Baixando dados historicos para {}...", par)
            try:
                candles_df = self._data_collector.download_historical_candles(
                    par=par, anos=3, timeframe="5m"
                )
                if candles_df.empty:
                    logger.warning("Nenhum candle baixado para {}", par)
                    continue

                # Baixar dados complementares
                funding_df = self._data_collector.download_funding_rate_history(par)
                fear_greed_df = self._data_collector.download_fear_greed_history()

                # Construir dataset de treino
                df = self._data_collector.build_training_dataset(
                    par=par,
                    candles_df=candles_df,
                    funding_df=funding_df,
                    fear_greed_df=fear_greed_df,
                )

                if not df.empty:
                    all_dfs.append(df)
                    logger.info("[{}] {} amostras de treino geradas", par, len(df))

            except Exception as e:
                logger.error("Erro ao preparar dados de {} para treino: {}", par, e)
                continue

        if not all_dfs:
            logger.error("Nenhum dado disponivel para treino. Abortando.")
            return

        # Concatenar todos os pares
        df_completo = pd.concat(all_dfs, ignore_index=True)
        logger.info("Dataset total: {} amostras de {} pares", len(df_completo), len(all_dfs))

        # Preparar features para o modelo (mapear nomes de colunas)
        df_treino = self._preparar_features(df_completo)

        # Treinar
        metricas = self._model.train(df_treino)
        logger.info("Treino inicial concluido. Metricas: {}", metricas)

        # Registrar no banco
        self._registrar_treino(metricas)

    # ------------------------------------------------------------------
    # Retreino
    # ------------------------------------------------------------------

    def retreinar_se_necessario(self) -> bool:
        """Verifica se modelo precisa de retreino (>7 dias) e retreina.

        Returns:
            True se retreinou, False caso contrario.
        """
        if not self._model.retrain_if_needed():
            return False

        logger.info("Retreinando modelo...")

        all_dfs = []
        for par in PARES:
            try:
                # Baixar dados mais recentes (ultimos 3 meses)
                candles_df = self._data_collector.download_historical_candles(
                    par=par, anos=0.25, timeframe="5m"
                )
                if candles_df.empty:
                    continue

                df = self._data_collector.build_training_dataset(
                    par=par,
                    candles_df=candles_df,
                )
                if not df.empty:
                    all_dfs.append(df)

            except Exception as e:
                logger.error("Erro ao preparar dados de {} para retreino: {}", par, e)

        if not all_dfs:
            logger.warning("Nenhum dado novo disponivel para retreino")
            return False

        df_completo = pd.concat(all_dfs, ignore_index=True)
        df_treino = self._preparar_features(df_completo)

        # Guardar metricas anteriores para comparacao
        metricas_anteriores = self._model.get_model_info().get("metrics", {})

        metricas = self._model.train(df_treino)

        # Comparar com versao anterior
        avaliacao = self.avaliar_performance_modelo(metricas, metricas_anteriores)
        if avaliacao.get("melhorou"):
            logger.info("Novo modelo e melhor que o anterior!")
        else:
            logger.warning("Novo modelo NAO melhorou. Mantendo mesmo assim (dados mais recentes).")

        self._registrar_treino(metricas)
        return True

    # ------------------------------------------------------------------
    # Avaliacao
    # ------------------------------------------------------------------

    def avaliar_performance_modelo(
        self,
        metricas_novas: Dict[str, Any],
        metricas_anteriores: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Compara metricas do novo modelo com o anterior.

        Args:
            metricas_novas: Metricas do modelo recem-treinado.
            metricas_anteriores: Metricas do modelo anterior (para comparacao).

        Returns:
            Dict com 'melhorou' (bool) e 'metricas' (dict com deltas).
        """
        resultado = {
            "melhorou": True,
            "metricas": metricas_novas,
            "deltas": {},
        }

        if not metricas_anteriores:
            return resultado

        # Comparar AUC como metrica principal
        auc_novo = metricas_novas.get("auc_roc", 0)
        auc_antigo = metricas_anteriores.get("auc_roc", 0)

        for metrica in ("accuracy", "precision", "recall", "auc_roc"):
            novo = metricas_novas.get(metrica, 0)
            antigo = metricas_anteriores.get(metrica, 0)
            resultado["deltas"][metrica] = round(novo - antigo, 4)

        resultado["melhorou"] = auc_novo >= auc_antigo

        logger.info(
            "Comparacao: AUC {:.4f} -> {:.4f} (delta: {:+.4f}) | {}",
            auc_antigo, auc_novo, auc_novo - auc_antigo,
            "MELHOROU" if resultado["melhorou"] else "PIOROU",
        )

        return resultado

    # ------------------------------------------------------------------
    # Utilitarios
    # ------------------------------------------------------------------

    @staticmethod
    def _preparar_features(df: pd.DataFrame) -> pd.DataFrame:
        """Mapeia colunas do DataCollector para as esperadas pelo ScalpingModel.

        O DataCollector gera nomes como 'ema_9', 'rsi_7', etc.
        O ScalpingModel espera 'ema9', 'rsi', etc.
        """
        rename_map = {
            "ema_9": "ema9",
            "ema_25": "ema25",
            "ema_50": "ema50",
            "ema_100": "ema100",
            "rsi_7": "rsi",
            "atr_14": "atr",
            "relative_volume": "volume_relativo",
            "close_position": "candle_position",
            "upper_shadow_ratio": "sombra_superior",
            "lower_shadow_ratio": "sombra_inferior",
            "body_ratio": "corpo_candle",
            "candle_sequence": "sequencia_candles",
            "fear_greed_value": "fear_greed",
            "order_book_imbalance": "ob_imbalance",
            "taker_buy_ratio": "taker_ratio",
        }

        df = df.rename(columns=rename_map)

        # Regime encoded
        if "regime" in df.columns:
            regime_map = {"LATERAL": 0, "TREND_UP": 1, "TREND_DOWN": 2}
            df["regime_encoded"] = df["regime"].map(regime_map).fillna(0).astype(int)

        # Relacoes preco vs EMAs
        for ema in ("ema25", "ema50", "ema100"):
            col = f"preco_vs_{ema}"
            if col not in df.columns and ema in df.columns and "close" in df.columns:
                df[col] = ((df["close"] - df[ema]) / df["close"]) * 100

        # Preencher colunas faltantes com zeros
        for col in FEATURE_COLUMNS:
            if col not in df.columns:
                df[col] = 0.0
                logger.debug("Coluna {} ausente — preenchida com 0.0", col)

        # Garantir que label existe
        if TARGET_COLUMN not in df.columns:
            logger.warning("Coluna '{}' ausente no dataset", TARGET_COLUMN)

        return df

    def _registrar_treino(self, metricas: Dict[str, Any]) -> None:
        """Registra informacoes do treino no banco de dados."""
        if get_connection is None:
            return

        try:
            conn = get_connection()
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO model_versions
                        (versao, acuracia, precisao, recall, caminho_arquivo)
                    VALUES (%s, %s, %s, %s, %s);
                """, (
                    f"v{self._model._version}",
                    metricas.get("accuracy", 0),
                    metricas.get("precision", 0),
                    metricas.get("recall", 0),
                    str(self._model._modelo_path or ""),
                ))
            conn.commit()
            conn.close()
            logger.info("Treino v{} registrado no banco", self._model._version)
        except Exception as e:
            logger.warning("Falha ao registrar treino no banco: {}", e)

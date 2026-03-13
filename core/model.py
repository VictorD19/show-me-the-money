"""
Modelo LightGBM especialista em scalping cripto.

Treina um classificador binario (WIN/LOSS) usando features tecnicas,
de microestrutura, regime de mercado e dados externos (sentimento, funding).
"""

import pickle
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from loguru import logger

try:
    import lightgbm as lgb
    _LGB_AVAILABLE = True
except ImportError:
    _LGB_AVAILABLE = False
    logger.warning("lightgbm nao instalado — modelo ML desabilitado")

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
    logger.warning("scikit-learn nao instalado — metricas indisponiveis")

try:
    from config import MODELS_DIR, CONFIANCA_MINIMA
except ImportError:
    MODELS_DIR = Path(__file__).resolve().parent.parent / "models"
    CONFIANCA_MINIMA = 0.65


# Features esperadas pelo modelo
FEATURE_COLUMNS: List[str] = [
    # Tecnicas
    "ema9", "ema25", "ema50", "ema100",
    "rsi", "atr", "vwap", "volume_relativo",
    # Microestrutura
    "cvd", "ob_imbalance", "taker_ratio",
    "candle_position", "sombra_superior", "sombra_inferior", "corpo_candle",
    # Sequencia
    "sequencia_candles",
    # Regime
    "regime_encoded",
    # Externas
    "fear_greed", "sentimento_noticias", "funding_rate", "open_interest_change",
    # Relacoes
    "preco_vs_ema25", "preco_vs_ema50", "preco_vs_ema100",
]

TARGET_COLUMN = "label"
MIN_TRAINING_SAMPLES = 1000


class ScalpingModel:
    """Modelo LightGBM para classificacao binaria de scalping (WIN/LOSS)."""

    def __init__(self, modelo_path: Optional[str] = None) -> None:
        """Inicializa o modelo.

        Args:
            modelo_path: Caminho para modelo .pkl existente. Se None, tenta
                         carregar a versao mais recente de MODELS_DIR.
        """
        self._model: Optional[lgb.Booster] = None
        self._version: int = 0
        self._train_date: Optional[datetime] = None
        self._metrics: Dict[str, float] = {}
        self._feature_importance: Dict[str, float] = {}
        self._modelo_path: Optional[Path] = None

        MODELS_DIR.mkdir(parents=True, exist_ok=True)

        if modelo_path:
            self._load(Path(modelo_path))
        else:
            self._load_latest()

    # ------------------------------------------------------------------
    # Carregar / Salvar
    # ------------------------------------------------------------------

    def _load(self, path: Path) -> bool:
        """Carrega modelo de um arquivo .pkl."""
        if not path.exists():
            logger.warning(f"Arquivo de modelo nao encontrado: {path}")
            return False
        try:
            with open(path, "rb") as f:
                data = pickle.load(f)
            self._model = data["model"]
            self._version = data.get("version", 0)
            self._train_date = data.get("train_date")
            self._metrics = data.get("metrics", {})
            self._feature_importance = data.get("feature_importance", {})
            self._modelo_path = path
            logger.info(
                f"Modelo v{self._version} carregado de {path} "
                f"(AUC: {self._metrics.get('auc_roc', 'N/A')})"
            )
            return True
        except Exception as exc:
            logger.error(f"Erro ao carregar modelo: {exc}")
            return False

    def _load_latest(self) -> bool:
        """Carrega a versao mais recente do modelo em MODELS_DIR."""
        modelos = sorted(MODELS_DIR.glob("scalping_model_v*.pkl"))
        if not modelos:
            logger.info("Nenhum modelo encontrado — necessario treinar")
            return False
        return self._load(modelos[-1])

    def _save(self) -> Path:
        """Salva o modelo atual em disco."""
        path = MODELS_DIR / f"scalping_model_v{self._version}.pkl"
        data = {
            "model": self._model,
            "version": self._version,
            "train_date": self._train_date,
            "metrics": self._metrics,
            "feature_importance": self._feature_importance,
        }
        with open(path, "wb") as f:
            pickle.dump(data, f)
        self._modelo_path = path
        logger.info(f"Modelo v{self._version} salvo em {path}")
        return path

    # ------------------------------------------------------------------
    # Treino
    # ------------------------------------------------------------------

    def train(self, df_features: pd.DataFrame) -> Dict[str, Any]:
        """Treina o modelo com split temporal.

        Args:
            df_features: DataFrame com FEATURE_COLUMNS + TARGET_COLUMN.

        Returns:
            Dict com metricas de validacao.
        """
        if not _LGB_AVAILABLE:
            raise RuntimeError("lightgbm nao instalado")

        # Validar colunas
        missing = [c for c in FEATURE_COLUMNS if c not in df_features.columns]
        if missing:
            raise ValueError(f"Colunas ausentes no DataFrame: {missing}")

        if TARGET_COLUMN not in df_features.columns:
            raise ValueError(f"Coluna target '{TARGET_COLUMN}' ausente")

        if len(df_features) < MIN_TRAINING_SAMPLES:
            logger.warning(
                f"Apenas {len(df_features)} amostras (minimo {MIN_TRAINING_SAMPLES}). "
                "Modelo nao sera treinado."
            )
            return {"status": "insuficiente", "amostras": len(df_features)}

        # Split temporal (80/20) — sem lookahead bias
        split_idx = int(len(df_features) * 0.8)
        train_df = df_features.iloc[:split_idx]
        val_df = df_features.iloc[split_idx:]

        X_train = train_df[FEATURE_COLUMNS]
        y_train = train_df[TARGET_COLUMN]
        X_val = val_df[FEATURE_COLUMNS]
        y_val = val_df[TARGET_COLUMN]

        logger.info(
            f"Treinando modelo — Train: {len(X_train)}, Val: {len(X_val)}"
        )

        # Class weight balanceado
        n_pos = y_train.sum()
        n_neg = len(y_train) - n_pos
        scale_pos_weight = n_neg / max(n_pos, 1)

        params = {
            "objective": "binary",
            "metric": "auc",
            "learning_rate": 0.05,
            "num_leaves": 31,
            "max_depth": 6,
            "min_child_samples": 50,
            "feature_fraction": 0.8,
            "bagging_fraction": 0.8,
            "bagging_freq": 5,
            "scale_pos_weight": scale_pos_weight,
            "verbose": -1,
        }

        train_data = lgb.Dataset(X_train, label=y_train)
        val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)

        self._model = lgb.train(
            params,
            train_data,
            num_boost_round=500,
            valid_sets=[val_data],
            callbacks=[
                lgb.early_stopping(stopping_rounds=50),
                lgb.log_evaluation(period=100),
            ],
        )

        # Metricas de validacao
        y_pred_proba = self._model.predict(X_val)
        y_pred = (y_pred_proba >= 0.5).astype(int)

        self._metrics = {
            "accuracy": round(accuracy_score(y_val, y_pred), 4),
            "precision": round(precision_score(y_val, y_pred, zero_division=0), 4),
            "recall": round(recall_score(y_val, y_pred, zero_division=0), 4),
            "auc_roc": round(roc_auc_score(y_val, y_pred_proba), 4),
            "train_size": len(X_train),
            "val_size": len(X_val),
        }

        # Feature importance
        importances = self._model.feature_importance(importance_type="gain")
        self._feature_importance = {
            name: round(float(imp), 2)
            for name, imp in sorted(
                zip(FEATURE_COLUMNS, importances), key=lambda x: -x[1]
            )
        }

        # Versionamento
        self._version += 1
        self._train_date = datetime.now(timezone.utc)
        self._save()

        logger.info(
            f"Treino concluido v{self._version}: "
            f"AUC={self._metrics['auc_roc']}, "
            f"Acc={self._metrics['accuracy']}, "
            f"Prec={self._metrics['precision']}, "
            f"Rec={self._metrics['recall']}"
        )

        return self._metrics

    # ------------------------------------------------------------------
    # Predicao
    # ------------------------------------------------------------------

    def predict(self, features_dict: Dict[str, float]) -> float:
        """Retorna probabilidade de WIN (0 a 1).

        Args:
            features_dict: Dict com os valores das features.

        Returns:
            Probabilidade de WIN. Retorna 0.5 se modelo nao treinado.
        """
        if self._model is None:
            logger.warning("Modelo nao carregado — retornando confianca neutra 0.5")
            return 0.5

        try:
            values = [features_dict.get(col, 0.0) for col in FEATURE_COLUMNS]
            X = np.array([values])
            proba = self._model.predict(X)[0]
            return round(float(proba), 4)
        except Exception as exc:
            logger.error(f"Erro na predicao: {exc}")
            return 0.5

    def predict_batch(self, df: pd.DataFrame) -> np.ndarray:
        """Retorna array de probabilidades de WIN para cada linha.

        Args:
            df: DataFrame com FEATURE_COLUMNS.

        Returns:
            Array numpy com probabilidades. Retorna 0.5 para todos se sem modelo.
        """
        if self._model is None:
            logger.warning("Modelo nao carregado — retornando 0.5 para todos")
            return np.full(len(df), 0.5)

        try:
            X = df[FEATURE_COLUMNS].values
            return self._model.predict(X)
        except Exception as exc:
            logger.error(f"Erro na predicao batch: {exc}")
            return np.full(len(df), 0.5)

    # ------------------------------------------------------------------
    # Retrain automatico
    # ------------------------------------------------------------------

    def retrain_if_needed(self) -> bool:
        """Verifica se o modelo precisa ser retreinado (>7 dias desde ultimo treino).

        Returns:
            True se retreino e necessario (chamador deve fornecer dados e chamar train).
        """
        if self._train_date is None:
            logger.info("Nenhum modelo treinado — retreino necessario")
            return True

        dias = (datetime.now(timezone.utc) - self._train_date).days
        if dias >= 7:
            logger.info(
                f"Modelo tem {dias} dias — retreino recomendado (limite: 7 dias)"
            )
            return True

        logger.debug(f"Modelo com {dias} dias — retreino nao necessario")
        return False

    # ------------------------------------------------------------------
    # Informacoes
    # ------------------------------------------------------------------

    def get_model_info(self) -> Dict[str, Any]:
        """Retorna informacoes sobre o modelo atual."""
        return {
            "version": self._version,
            "train_date": self._train_date.isoformat() if self._train_date else None,
            "metrics": self._metrics,
            "modelo_path": str(self._modelo_path) if self._modelo_path else None,
            "carregado": self._model is not None,
        }

    def get_feature_importance(self) -> Dict[str, float]:
        """Retorna features mais importantes ordenadas por importancia (gain)."""
        return self._feature_importance

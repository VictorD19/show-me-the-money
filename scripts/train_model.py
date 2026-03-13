#!/usr/bin/env python3
"""
Script para treinar o modelo de scalping.

Uso:
    python scripts/train_model.py --pares BTC ETH XRP
    python scripts/train_model.py --pares BTC
    python scripts/train_model.py  # usa padroes (BTC ETH XRP)

Carrega dados historicos do banco ou CSVs e treina o modelo LightGBM.
"""

import argparse
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from loguru import logger

from config import BINANCE_TESTNET, HISTORICAL_DIR, MODELS_DIR, validar_config
from core.binance_client import BinanceClient
from core.data_collector import DataCollector
from core.model import ScalpingModel
from core.trainer import ModelTrainer


def parse_args() -> argparse.Namespace:
    """Parse argumentos de linha de comando."""
    parser = argparse.ArgumentParser(
        description="Treinar modelo LightGBM para scalping."
    )
    parser.add_argument(
        "--pares", nargs="+", default=["BTC", "ETH", "XRP"],
        help="Pares para treinar (default: BTC ETH XRP). Sera adicionado /USDT automaticamente."
    )
    parser.add_argument(
        "--from-csv", action="store_true",
        help="Carregar dados de CSVs ao inves do banco"
    )
    parser.add_argument(
        "--anos", type=float, default=3,
        help="Anos de historico para usar no treino (se baixar novos dados)"
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Forcar retreino mesmo se modelo existente esta atualizado"
    )
    return parser.parse_args()


def main() -> None:
    """Executa o treino do modelo."""
    args = parse_args()

    validar_config()

    # Formatar pares
    pares = [
        f"{p.upper()}/USDT" if "/" not in p else p.upper()
        for p in args.pares
    ]

    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    logger.info("=" * 60)
    logger.info("Treinamento do Modelo de Scalping")
    logger.info("Pares: {}", ", ".join(pares))
    logger.info("Fonte: {}", "CSV" if args.from_csv else "Banco de dados / Download")
    logger.info("=" * 60)

    # Inicializar componentes
    client = BinanceClient(testnet=BINANCE_TESTNET)
    collector = DataCollector(client)
    model = ScalpingModel()
    trainer = ModelTrainer(model, collector)

    # Verificar se precisa treinar
    if not args.force and not model.retrain_if_needed():
        model_info = model.get_model_info()
        logger.info("Modelo existente esta atualizado:")
        logger.info("  Versao: v{}", model_info["version"])
        logger.info("  Treinado em: {}", model_info["train_date"])
        logger.info("  AUC: {}", model_info["metrics"].get("auc_roc", "N/A"))
        logger.info("Use --force para forcar retreino.")
        return

    # Executar treino
    import pandas as pd

    all_dfs = []
    for par in pares:
        logger.info("-" * 40)
        logger.info("Preparando dados de {}...", par)

        candles_df = None
        funding_df = None
        fear_greed_df = None

        if args.from_csv:
            # Carregar de CSVs
            csv_path = HISTORICAL_DIR / f"candles_{par.replace('/', '_').lower()}_5m.csv"
            if csv_path.exists():
                candles_df = pd.read_csv(str(csv_path))
                logger.info("Carregados {} candles de {}", len(candles_df), csv_path.name)
            else:
                logger.error("CSV nao encontrado: {}", csv_path)
                continue

            # Tentar carregar funding rate
            symbol = par.replace("/", "").lower()
            funding_csv = HISTORICAL_DIR / f"funding_rate_{symbol}.csv"
            if funding_csv.exists():
                funding_df = pd.read_csv(str(funding_csv))

            # Tentar carregar Fear & Greed
            fg_csv = HISTORICAL_DIR / "fear_greed.csv"
            if fg_csv.exists():
                fear_greed_df = pd.read_csv(str(fg_csv))
        else:
            # Baixar dados frescos
            try:
                candles_df = collector.download_historical_candles(
                    par=par, anos=args.anos, timeframe="5m"
                )
                funding_df = collector.download_funding_rate_history(par)
                fear_greed_df = collector.download_fear_greed_history()
            except Exception as e:
                logger.error("Erro ao baixar dados de {}: {}", par, e)
                continue

        if candles_df is None or candles_df.empty:
            logger.warning("Sem dados para {}. Pulando.", par)
            continue

        # Construir dataset
        df = collector.build_training_dataset(
            par=par,
            candles_df=candles_df,
            funding_df=funding_df,
            fear_greed_df=fear_greed_df,
        )

        if not df.empty:
            all_dfs.append(df)
            logger.info("[{}] {} amostras de treino", par, len(df))

    if not all_dfs:
        logger.error("Nenhum dado disponivel para treino. Abortando.")
        sys.exit(1)

    # Concatenar e preparar features
    df_completo = pd.concat(all_dfs, ignore_index=True)
    logger.info("Dataset total: {} amostras", len(df_completo))

    df_treino = trainer._preparar_features(df_completo)

    # Treinar
    logger.info("Iniciando treino...")
    metricas = model.train(df_treino)

    # Exibir resultados
    logger.info("=" * 60)
    logger.info("RESULTADOS DO TREINO")
    logger.info("=" * 60)

    if isinstance(metricas, dict):
        for k, v in metricas.items():
            if isinstance(v, float):
                logger.info("  {:20s} {:.4f}", k, v)
            else:
                logger.info("  {:20s} {}", k, v)

    # Feature importance
    fi = model.get_feature_importance()
    if fi:
        logger.info("-" * 40)
        logger.info("Top 10 Features mais importantes:")
        for i, (feat, imp) in enumerate(list(fi.items())[:10], 1):
            logger.info("  {:2d}. {:30s} {:.2f}", i, feat, imp)

    logger.info("=" * 60)
    model_info = model.get_model_info()
    logger.info("Modelo salvo: {}", model_info.get("modelo_path", "N/A"))
    logger.info("Treino concluido!")


if __name__ == "__main__":
    main()

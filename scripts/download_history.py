#!/usr/bin/env python3
"""
Script para download de dados historicos da Binance.

Uso:
    python scripts/download_history.py --anos 3 --pares BTC ETH XRP
    python scripts/download_history.py --anos 1 --pares BTC
    python scripts/download_history.py  # usa padroes (3 anos, BTC ETH XRP)

Deve ser executado antes de rodar o bot pela primeira vez para
popular o banco de dados e/ou gerar CSVs de backup.
"""

import argparse
import sys
from pathlib import Path

# Adicionar raiz do projeto ao path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from loguru import logger

from config import BINANCE_TESTNET, HISTORICAL_DIR, validar_config
from core.binance_client import BinanceClient
from core.data_collector import DataCollector


def parse_args() -> argparse.Namespace:
    """Parse argumentos de linha de comando."""
    parser = argparse.ArgumentParser(
        description="Download de dados historicos da Binance para treino do modelo."
    )
    parser.add_argument(
        "--anos", type=float, default=3,
        help="Quantidade de anos de historico para baixar (default: 3)"
    )
    parser.add_argument(
        "--pares", nargs="+", default=["BTC", "ETH", "XRP"],
        help="Pares para baixar (default: BTC ETH XRP). Sera adicionado /USDT automaticamente."
    )
    parser.add_argument(
        "--timeframe", type=str, default="5m",
        help="Timeframe dos candles (default: 5m)"
    )
    parser.add_argument(
        "--skip-funding", action="store_true",
        help="Pular download de funding rate"
    )
    parser.add_argument(
        "--skip-fear-greed", action="store_true",
        help="Pular download de Fear & Greed Index"
    )
    parser.add_argument(
        "--skip-oi", action="store_true",
        help="Pular download de Open Interest"
    )
    return parser.parse_args()


def main() -> None:
    """Executa o download de dados historicos."""
    args = parse_args()

    # Validar config
    if not validar_config():
        logger.warning("Configuracao incompleta. Continuando com valores disponiveis...")

    # Garantir que diretorio existe
    HISTORICAL_DIR.mkdir(parents=True, exist_ok=True)

    # Formatar pares (BTC -> BTC/USDT)
    pares = [
        f"{p.upper()}/USDT" if "/" not in p else p.upper()
        for p in args.pares
    ]

    modo = "TESTNET" if BINANCE_TESTNET else "PRODUCAO"
    logger.info("=" * 60)
    logger.info("Download de Dados Historicos")
    logger.info("Modo: {}", modo)
    logger.info("Pares: {}", ", ".join(pares))
    logger.info("Anos: {}", args.anos)
    logger.info("Timeframe: {}", args.timeframe)
    logger.info("=" * 60)

    # Inicializar cliente e coletor
    client = BinanceClient(testnet=BINANCE_TESTNET)
    collector = DataCollector(client)

    resumo = {}

    # Download de candles para cada par
    for par in pares:
        logger.info("-" * 40)
        logger.info("Baixando candles de {}...", par)

        try:
            df = collector.download_historical_candles(
                par=par, anos=args.anos, timeframe=args.timeframe
            )
            resumo[f"{par} candles"] = len(df)

            # Salvar CSV de backup
            csv_path = HISTORICAL_DIR / f"candles_{par.replace('/', '_').lower()}_{args.timeframe}.csv"
            df.to_csv(csv_path, index=False)
            logger.info("Backup CSV salvo: {}", csv_path)

        except Exception as e:
            logger.error("Erro ao baixar candles de {}: {}", par, e)
            resumo[f"{par} candles"] = "ERRO"

    # Download de funding rate
    if not args.skip_funding:
        for par in pares:
            logger.info("Baixando funding rate de {}...", par)
            try:
                df = collector.download_funding_rate_history(par)
                resumo[f"{par} funding"] = len(df)
            except Exception as e:
                logger.error("Erro ao baixar funding rate de {}: {}", par, e)
                resumo[f"{par} funding"] = "ERRO"

    # Download de Fear & Greed
    if not args.skip_fear_greed:
        logger.info("Baixando historico Fear & Greed Index...")
        try:
            df = collector.download_fear_greed_history()
            resumo["Fear & Greed"] = len(df)
        except Exception as e:
            logger.error("Erro ao baixar Fear & Greed: {}", e)
            resumo["Fear & Greed"] = "ERRO"

    # Download de Open Interest
    if not args.skip_oi:
        for par in pares:
            logger.info("Baixando open interest de {}...", par)
            try:
                df = collector.download_open_interest_history(par)
                resumo[f"{par} OI"] = len(df)
            except Exception as e:
                logger.error("Erro ao baixar OI de {}: {}", par, e)
                resumo[f"{par} OI"] = "ERRO"

    # Resumo final
    logger.info("=" * 60)
    logger.info("RESUMO DO DOWNLOAD")
    logger.info("=" * 60)
    for item, contagem in resumo.items():
        if isinstance(contagem, int):
            logger.info("  {:30s} {:>10,} registros", item, contagem)
        else:
            logger.info("  {:30s} {:>10s}", item, str(contagem))
    logger.info("=" * 60)
    logger.info("Download concluido!")


if __name__ == "__main__":
    main()

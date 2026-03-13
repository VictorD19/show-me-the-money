"""
Coletor de dados historicos para treino do modelo de scalping.
"""

import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np
import pandas as pd
import requests
from loguru import logger
from tqdm import tqdm

from core.binance_client import BinanceClient
from core.indicators import calculate_all, calculate_order_book_imbalance

try:
    from config import Config
except ImportError:
    class Config:
        TRADING_PAIR = "BTC/USDT"
        CANDLE_TIMEFRAME = "5m"
        TP_RATIO = 2.18
        LABEL_LOOKAHEAD = 6
        DB_HOST = "localhost"
        DB_PORT = 5432
        DB_NAME = "scalping_bot"
        DB_USER = "postgres"
        DB_PASSWORD = "postgres"


def _get_db_connection():
    """Tenta conectar ao TimescaleDB. Retorna None se nao disponivel."""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=Config.DB_HOST,
            port=Config.DB_PORT,
            dbname=Config.DB_NAME,
            user=Config.DB_USER,
            password=Config.DB_PASSWORD,
        )
        return conn
    except Exception as e:
        logger.warning("TimescaleDB nao disponivel: {}. Usando CSV como fallback.", e)
        return None


def _save_to_db(conn, table: str, df: pd.DataFrame):
    """Salva DataFrame no TimescaleDB."""
    from io import StringIO
    import psycopg2.extras

    cursor = conn.cursor()

    # Cria tabela se nao existe
    cols_sql = ", ".join(
        f'"{c}" DOUBLE PRECISION' if df[c].dtype in ["float64", "float32"]
        else f'"{c}" BIGINT' if df[c].dtype in ["int64", "int32"]
        else f'"{c}" TEXT'
        for c in df.columns
    )
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS {table} (
            {cols_sql}
        )
    """)

    # Insere dados usando COPY
    buffer = StringIO()
    df.to_csv(buffer, index=False, header=False)
    buffer.seek(0)
    columns = ", ".join(f'"{c}"' for c in df.columns)
    cursor.copy_expert(
        f"COPY {table} ({columns}) FROM STDIN WITH CSV", buffer
    )
    conn.commit()
    cursor.close()
    logger.info("{} linhas salvas na tabela {}", len(df), table)


def _save_to_csv(filepath: str, df: pd.DataFrame):
    """Fallback: salva DataFrame em CSV."""
    df.to_csv(filepath, index=False)
    logger.info("{} linhas salvas em {}", len(df), filepath)


class DataCollector:
    """Coleta e prepara dados historicos para treino."""

    def __init__(self, client: BinanceClient = None):
        self.client = client or BinanceClient()
        self.conn = _get_db_connection()

    def download_historical_candles(
        self,
        par: str = None,
        anos: int = 2,
        timeframe: str = None,
    ) -> pd.DataFrame:
        """Baixa X anos de candles da Binance em lotes de 1000."""
        par = par or Config.TRADING_PAIR
        timeframe = timeframe or Config.CANDLE_TIMEFRAME

        fim = datetime.now(timezone.utc)
        inicio = fim - timedelta(days=anos * 365)

        logger.info(
            "Baixando candles de {} ({}) de {} ate {}",
            par, timeframe, inicio.date(), fim.date(),
        )

        # Estima numero total de candles para progress bar
        timeframe_minutes = {
            "1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30,
            "1h": 60, "2h": 120, "4h": 240, "1d": 1440,
        }
        minutes = timeframe_minutes.get(timeframe, 5)
        total_candles_estimate = int((fim - inicio).total_seconds() / 60 / minutes)
        total_batches = total_candles_estimate // 1000 + 1

        all_candles = []
        since_ms = int(inicio.timestamp() * 1000)
        fim_ms = int(fim.timestamp() * 1000)

        with tqdm(total=total_batches, desc=f"Baixando {par} {timeframe}") as pbar:
            while since_ms < fim_ms:
                try:
                    candles = self.client.exchange.fetch_ohlcv(
                        par, timeframe, since=since_ms, limit=1000
                    )
                except Exception as e:
                    logger.warning("Erro ao baixar candles: {}. Retentando...", e)
                    time.sleep(10)
                    continue

                if not candles:
                    break

                all_candles.extend(candles)
                since_ms = candles[-1][0] + 1
                pbar.update(1)
                time.sleep(self.client.exchange.rateLimit / 1000)

        # Filtra e converte para DataFrame
        all_candles = [c for c in all_candles if c[0] <= fim_ms]
        df = pd.DataFrame(
            all_candles,
            columns=["timestamp", "open", "high", "low", "close", "volume"],
        )
        df = df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)

        logger.info("Total de {} candles baixados para {}", len(df), par)

        # Salva
        if self.conn:
            _save_to_db(self.conn, f"candles_{par.replace('/', '_').lower()}", df)
        else:
            filepath = f"/home/ixcsoft/Documentos/show-me-the-money/data/historical/candles_{par.replace('/', '_').lower()}_{timeframe}.csv"
            _save_to_csv(filepath, df)

        return df

    def download_fear_greed_history(self) -> pd.DataFrame:
        """Baixa historico do Fear & Greed Index."""
        url = "https://api.alternative.me/fng/?limit=0&format=json"
        logger.info("Baixando historico Fear & Greed Index...")

        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            data = response.json().get("data", [])
        except Exception as e:
            logger.error("Erro ao baixar Fear & Greed: {}", e)
            return pd.DataFrame()

        df = pd.DataFrame(data)
        df["value"] = df["value"].astype(int)
        df["timestamp"] = df["timestamp"].astype(int) * 1000  # converter para ms
        df = df[["timestamp", "value", "value_classification"]].rename(
            columns={"value": "fear_greed_value", "value_classification": "fear_greed_class"}
        )
        df = df.sort_values("timestamp").reset_index(drop=True)

        logger.info("{} registros de Fear & Greed baixados", len(df))

        if self.conn:
            _save_to_db(self.conn, "fear_greed", df)
        else:
            _save_to_csv(
                "/home/ixcsoft/Documentos/show-me-the-money/data/historical/fear_greed.csv", df
            )

        return df

    def download_funding_rate_history(self, par: str = None) -> pd.DataFrame:
        """Baixa historico de funding rate."""
        par = par or Config.TRADING_PAIR
        symbol = par.replace("/", "")
        logger.info("Baixando historico de funding rate para {}...", par)

        all_data = []
        start_time = int((datetime.now(timezone.utc) - timedelta(days=365 * 2)).timestamp() * 1000)

        with tqdm(desc=f"Funding Rate {par}") as pbar:
            while True:
                try:
                    data = self.client.exchange.fapiPublicGetFundingRate({
                        "symbol": symbol,
                        "startTime": start_time,
                        "limit": 1000,
                    })
                except Exception as e:
                    logger.warning("Erro ao baixar funding rate: {}. Retentando...", e)
                    time.sleep(5)
                    continue

                if not data:
                    break

                all_data.extend(data)
                start_time = int(data[-1]["fundingTime"]) + 1
                pbar.update(len(data))
                time.sleep(0.5)

                if len(data) < 1000:
                    break

        if not all_data:
            return pd.DataFrame()

        df = pd.DataFrame(all_data)
        df["timestamp"] = df["fundingTime"].astype(int)
        df["funding_rate"] = df["fundingRate"].astype(float)
        df = df[["timestamp", "funding_rate"]].sort_values("timestamp").reset_index(drop=True)

        logger.info("{} registros de funding rate baixados", len(df))

        if self.conn:
            _save_to_db(self.conn, f"funding_rate_{symbol.lower()}", df)
        else:
            _save_to_csv(
                f"/home/ixcsoft/Documentos/show-me-the-money/data/historical/funding_rate_{symbol.lower()}.csv",
                df,
            )

        return df

    def download_open_interest_history(self, par: str = None) -> pd.DataFrame:
        """Baixa historico de open interest."""
        par = par or Config.TRADING_PAIR
        symbol = par.replace("/", "")
        logger.info("Baixando historico de open interest para {}...", par)

        all_data = []
        start_time = int((datetime.now(timezone.utc) - timedelta(days=30)).timestamp() * 1000)

        with tqdm(desc=f"Open Interest {par}") as pbar:
            while True:
                try:
                    data = self.client.exchange.fapiDataGetOpenInterestHist({
                        "symbol": symbol,
                        "period": "5m",
                        "startTime": start_time,
                        "limit": 500,
                    })
                except Exception as e:
                    logger.warning("Erro ao baixar OI: {}. Retentando...", e)
                    time.sleep(5)
                    continue

                if not data:
                    break

                all_data.extend(data)
                start_time = int(data[-1]["timestamp"]) + 1
                pbar.update(len(data))
                time.sleep(0.5)

                if len(data) < 500:
                    break

        if not all_data:
            return pd.DataFrame()

        df = pd.DataFrame(all_data)
        df["timestamp"] = df["timestamp"].astype(int)
        df["open_interest"] = df["sumOpenInterest"].astype(float)
        df["open_interest_value"] = df["sumOpenInterestValue"].astype(float)
        df = df[["timestamp", "open_interest", "open_interest_value"]]
        df = df.sort_values("timestamp").reset_index(drop=True)

        logger.info("{} registros de OI baixados", len(df))

        if self.conn:
            _save_to_db(self.conn, f"open_interest_{symbol.lower()}", df)
        else:
            _save_to_csv(
                f"/home/ixcsoft/Documentos/show-me-the-money/data/historical/open_interest_{symbol.lower()}.csv",
                df,
            )

        return df

    def build_training_dataset(
        self,
        par: str = None,
        candles_df: pd.DataFrame = None,
        funding_df: pd.DataFrame = None,
        fear_greed_df: pd.DataFrame = None,
    ) -> pd.DataFrame:
        """Monta dataset completo para treino do modelo.

        Gera labels:
        - WIN: preco atingiu TP antes do SL nas proximas 6 velas
        - LOSS: caso contrario
        - TP = entrada + (distancia_sl * TP_RATIO) [para 2:1 liquido de taxas]
        - SL = EMA100 no momento da entrada
        """
        par = par or Config.TRADING_PAIR
        logger.info("Construindo dataset de treino para {}...", par)

        # Carrega candles se nao fornecido
        if candles_df is None:
            csv_path = f"/home/ixcsoft/Documentos/show-me-the-money/data/historical/candles_{par.replace('/', '_').lower()}_5m.csv"
            try:
                candles_df = pd.read_csv(csv_path)
            except FileNotFoundError:
                logger.error("Arquivo de candles nao encontrado: {}", csv_path)
                return pd.DataFrame()

        # Calcula indicadores
        df = calculate_all(candles_df)

        # Merge funding rate (forward fill para alinhar timestamps)
        if funding_df is not None and not funding_df.empty:
            funding_df = funding_df.sort_values("timestamp")
            df = pd.merge_asof(
                df.sort_values("timestamp"),
                funding_df[["timestamp", "funding_rate"]],
                on="timestamp",
                direction="backward",
            )
        else:
            df["funding_rate"] = 0.0

        # Merge Fear & Greed (forward fill diario)
        if fear_greed_df is not None and not fear_greed_df.empty:
            fear_greed_df = fear_greed_df.sort_values("timestamp")
            df = pd.merge_asof(
                df.sort_values("timestamp"),
                fear_greed_df[["timestamp", "fear_greed_value"]],
                on="timestamp",
                direction="backward",
            )
        else:
            df["fear_greed_value"] = 50

        # Gera labels
        lookahead = Config.LABEL_LOOKAHEAD
        tp_ratio = Config.TP_RATIO
        labels = []

        close_arr = df["close"].values
        high_arr = df["high"].values
        low_arr = df["low"].values
        ema100_arr = df["ema_100"].values

        for i in range(len(df)):
            if i >= len(df) - lookahead or pd.isna(ema100_arr[i]):
                labels.append(np.nan)
                continue

            entry = close_arr[i]
            sl_long = ema100_arr[i]
            sl_dist = abs(entry - sl_long)

            if sl_dist == 0:
                labels.append(np.nan)
                continue

            # Avalia setup LONG
            tp_long = entry + sl_dist * tp_ratio

            won = False
            lost = False
            for j in range(1, lookahead + 1):
                idx = i + j
                if idx >= len(df):
                    break
                # Verifica SL primeiro (mais conservador)
                if low_arr[idx] <= sl_long:
                    lost = True
                    break
                if high_arr[idx] >= tp_long:
                    won = True
                    break

            if won:
                labels.append(1)  # WIN
            else:
                labels.append(0)  # LOSS

        df["label"] = labels

        # Remove linhas sem label
        df = df.dropna(subset=["label"]).reset_index(drop=True)
        df["label"] = df["label"].astype(int)

        win_count = (df["label"] == 1).sum()
        total = len(df)
        logger.info(
            "Dataset de treino: {} amostras | WIN: {} ({:.1f}%) | LOSS: {} ({:.1f}%)",
            total,
            win_count,
            win_count / total * 100 if total > 0 else 0,
            total - win_count,
            (total - win_count) / total * 100 if total > 0 else 0,
        )

        return df

    def get_realtime_snapshot(self, par: str = None) -> Optional[dict]:
        """Retorna snapshot atual de todas as features para predicao em tempo real."""
        par = par or Config.TRADING_PAIR

        try:
            # Busca candles recentes (200 para calcular indicadores com warmup)
            candles = self.client.get_candles(par, "5m", 200)
            if not candles:
                logger.error("Nao foi possivel obter candles recentes")
                return None

            df = pd.DataFrame(
                candles,
                columns=["timestamp", "open", "high", "low", "close", "volume"],
            )

            # Calcula indicadores
            df = calculate_all(df)

            # Pega ultima linha (candle mais recente)
            latest = df.iloc[-1].to_dict()

            # Adiciona dados em tempo real
            order_book = self.client.get_order_book(par, 20)
            if order_book["bids"] and order_book["asks"]:
                bid_qty = sum(b[1] for b in order_book["bids"])
                ask_qty = sum(a[1] for a in order_book["asks"])
                latest["order_book_imbalance"] = calculate_order_book_imbalance(
                    bid_qty, ask_qty
                )
            else:
                latest["order_book_imbalance"] = 0.0

            # Funding rate
            funding = self.client.get_funding_rate(par)
            latest["funding_rate"] = (
                funding["funding_rate"] if funding else 0.0
            )

            # Open interest
            oi = self.client.get_open_interest(par)
            latest["open_interest"] = (
                oi["open_interest"] if oi else 0.0
            )

            # Taker ratio
            taker = self.client.get_taker_ratio(par)
            latest["long_short_ratio"] = (
                taker["long_short_ratio"] if taker else 1.0
            )

            logger.debug("Snapshot realtime gerado para {}", par)
            return latest

        except Exception as e:
            logger.error("Erro ao gerar snapshot realtime: {}", e)
            return None

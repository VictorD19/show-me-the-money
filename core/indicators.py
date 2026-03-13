"""
Indicadores tecnicos especializados para scalping.
"""

import numpy as np
import pandas as pd
import pandas_ta as ta
from loguru import logger


def calculate_emas(df: pd.DataFrame) -> pd.DataFrame:
    """EMA 9, 25, 50, 100."""
    df["ema_9"] = ta.ema(df["close"], length=9)
    df["ema_25"] = ta.ema(df["close"], length=25)
    df["ema_50"] = ta.ema(df["close"], length=50)
    df["ema_100"] = ta.ema(df["close"], length=100)
    return df


def calculate_rsi(df: pd.DataFrame) -> pd.DataFrame:
    """RSI periodo 7."""
    df["rsi_7"] = ta.rsi(df["close"], length=7)
    return df


def calculate_atr(df: pd.DataFrame) -> pd.DataFrame:
    """ATR periodo 14."""
    df["atr_14"] = ta.atr(df["high"], df["low"], df["close"], length=14)
    return df


def calculate_adx(df: pd.DataFrame) -> pd.DataFrame:
    """ADX periodo 14."""
    adx_df = ta.adx(df["high"], df["low"], df["close"], length=14)
    if adx_df is not None:
        df["adx_14"] = adx_df[f"ADX_14"]
        df["dmp_14"] = adx_df[f"DMP_14"]
        df["dmn_14"] = adx_df[f"DMN_14"]
    return df


def calculate_vwap(df: pd.DataFrame) -> pd.DataFrame:
    """VWAP intraday acumulado desde abertura do dia."""
    df = df.copy()
    if "timestamp" in df.columns:
        ts = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    elif isinstance(df.index, pd.DatetimeIndex):
        ts = df.index
    else:
        df["vwap"] = np.nan
        return df

    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    tp_vol = typical_price * df["volume"]

    # Agrupa por dia e acumula
    day = ts.dt.date if hasattr(ts, "dt") else pd.Series(ts).dt.date
    day = day.values

    vwap = np.full(len(df), np.nan)
    cum_tp_vol = 0.0
    cum_vol = 0.0
    current_day = None

    for i in range(len(df)):
        if day[i] != current_day:
            cum_tp_vol = 0.0
            cum_vol = 0.0
            current_day = day[i]
        cum_tp_vol += tp_vol.iloc[i]
        cum_vol += df["volume"].iloc[i]
        if cum_vol > 0:
            vwap[i] = cum_tp_vol / cum_vol

    df["vwap"] = vwap
    return df


def calculate_cvd(df: pd.DataFrame) -> pd.DataFrame:
    """CVD (Cumulative Volume Delta).
    Se taker_buy_vol estiver disponivel, usa diretamente.
    Caso contrario, estima usando posicao do close no candle.
    """
    if "taker_buy_vol" in df.columns:
        taker_sell = df["volume"] - df["taker_buy_vol"]
        delta = df["taker_buy_vol"] - taker_sell
    else:
        # Estimativa: proporcionalmente pela posicao do close no candle
        candle_range = df["high"] - df["low"]
        close_position = np.where(
            candle_range > 0,
            (df["close"] - df["low"]) / candle_range,
            0.5,
        )
        delta = df["volume"] * (2 * close_position - 1)

    df["cvd"] = delta.cumsum()
    df["cvd_delta"] = delta
    return df


def calculate_order_book_imbalance(
    bid_qty: float, ask_qty: float
) -> float:
    """Order Book Imbalance: (bid - ask) / (bid + ask). Retorna valor entre -1 e 1."""
    total = bid_qty + ask_qty
    if total == 0:
        return 0.0
    return (bid_qty - ask_qty) / total


def calculate_taker_ratio(df: pd.DataFrame) -> pd.DataFrame:
    """Taker Buy/Sell Ratio: taker_buy_vol / total_vol."""
    if "taker_buy_vol" in df.columns:
        df["taker_buy_ratio"] = np.where(
            df["volume"] > 0,
            df["taker_buy_vol"] / df["volume"],
            0.5,
        )
    else:
        df["taker_buy_ratio"] = 0.5
    return df


def calculate_relative_volume(df: pd.DataFrame, periods: int = 20) -> pd.DataFrame:
    """Volume relativo: volume_atual / media_volume_N_periodos."""
    vol_mean = df["volume"].rolling(window=periods).mean()
    df["relative_volume"] = np.where(vol_mean > 0, df["volume"] / vol_mean, 1.0)
    return df


def calculate_candle_anatomy(df: pd.DataFrame) -> pd.DataFrame:
    """Anatomia do candle: posicao do close, sombras, corpo."""
    candle_range = df["high"] - df["low"]
    safe_range = np.where(candle_range > 0, candle_range, np.nan)

    # Posicao do fechamento no candle (0 a 1)
    df["close_position"] = (df["close"] - df["low"]) / safe_range

    # Sombra superior
    upper_wick = df["high"] - np.maximum(df["open"], df["close"])
    df["upper_shadow_ratio"] = upper_wick / safe_range

    # Sombra inferior
    lower_wick = np.minimum(df["open"], df["close"]) - df["low"]
    df["lower_shadow_ratio"] = lower_wick / safe_range

    # Corpo do candle
    body = np.abs(df["close"] - df["open"])
    df["body_ratio"] = body / safe_range

    return df


def calculate_candle_sequence(df: pd.DataFrame) -> pd.DataFrame:
    """Sequencia de candles consecutivos de alta/baixa.
    Positivo = sequencia de alta, negativo = de baixa.
    """
    direction = np.sign(df["close"] - df["open"])
    sequence = np.zeros(len(df))
    for i in range(len(df)):
        if i == 0:
            sequence[i] = direction.iloc[i]
        elif direction.iloc[i] == direction.iloc[i - 1] and direction.iloc[i] != 0:
            sequence[i] = sequence[i - 1] + direction.iloc[i]
        else:
            sequence[i] = direction.iloc[i]
    df["candle_sequence"] = sequence
    return df


def detect_regime(df: pd.DataFrame) -> pd.Series:
    """Detecta regime de mercado para cada linha.
    TREND_UP: ADX > 25 AND EMA25 > EMA50 > EMA100
    TREND_DOWN: ADX > 25 AND EMA25 < EMA50 < EMA100
    LATERAL: qualquer outro caso
    """
    conditions = []
    for col in ["adx_14", "ema_25", "ema_50", "ema_100"]:
        if col not in df.columns:
            return pd.Series("LATERAL", index=df.index)

    regime = pd.Series("LATERAL", index=df.index)

    trend_up = (
        (df["adx_14"] > 25)
        & (df["ema_25"] > df["ema_50"])
        & (df["ema_50"] > df["ema_100"])
    )
    trend_down = (
        (df["adx_14"] > 25)
        & (df["ema_25"] < df["ema_50"])
        & (df["ema_50"] < df["ema_100"])
    )

    regime[trend_up] = "TREND_UP"
    regime[trend_down] = "TREND_DOWN"

    return regime


def calculate_all(df: pd.DataFrame) -> pd.DataFrame:
    """Calcula todos os indicadores e retorna DataFrame completo."""
    df = df.copy()
    logger.debug("Calculando indicadores para {} candles", len(df))

    df = calculate_emas(df)
    df = calculate_rsi(df)
    df = calculate_atr(df)
    df = calculate_adx(df)
    df = calculate_vwap(df)
    df = calculate_cvd(df)
    df = calculate_taker_ratio(df)
    df = calculate_relative_volume(df)
    df = calculate_candle_anatomy(df)
    df = calculate_candle_sequence(df)
    df["regime"] = detect_regime(df)

    logger.debug("Indicadores calculados: {} colunas", len(df.columns))
    return df

"""
Conexao com TimescaleDB e operacoes de banco de dados.
Gerencia todas as tabelas do bot de scalping.
"""

from datetime import datetime, date
from typing import Optional

import psycopg2
import psycopg2.extras
from loguru import logger

from config import DATABASE_URL, DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD


def get_connection():
    """Retorna uma conexao com o TimescaleDB."""
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
        )
        conn.autocommit = False
        return conn
    except psycopg2.OperationalError as e:
        logger.error(f"Falha ao conectar no banco de dados: {e}")
        raise
    except Exception as e:
        logger.error(f"Erro inesperado na conexao: {e}")
        raise


def create_tables():
    """Cria todas as tabelas e converte series temporais em hypertables."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            # Habilitar extensao TimescaleDB
            cur.execute("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;")

            # --- candles ---
            cur.execute("""
                CREATE TABLE IF NOT EXISTS candles (
                    timestamp   TIMESTAMPTZ NOT NULL,
                    par         VARCHAR(20) NOT NULL,
                    open        DOUBLE PRECISION NOT NULL,
                    high        DOUBLE PRECISION NOT NULL,
                    low         DOUBLE PRECISION NOT NULL,
                    close       DOUBLE PRECISION NOT NULL,
                    volume      DOUBLE PRECISION NOT NULL,
                    timeframe   VARCHAR(10) NOT NULL,
                    UNIQUE (timestamp, par, timeframe)
                );
            """)

            # --- order_book_snapshots ---
            cur.execute("""
                CREATE TABLE IF NOT EXISTS order_book_snapshots (
                    timestamp       TIMESTAMPTZ NOT NULL,
                    par             VARCHAR(20) NOT NULL,
                    bids_imbalance  DOUBLE PRECISION,
                    asks_imbalance  DOUBLE PRECISION,
                    UNIQUE (timestamp, par)
                );
            """)

            # --- funding_rate ---
            cur.execute("""
                CREATE TABLE IF NOT EXISTS funding_rate (
                    timestamp       TIMESTAMPTZ NOT NULL,
                    par             VARCHAR(20) NOT NULL,
                    funding_rate    DOUBLE PRECISION,
                    open_interest   DOUBLE PRECISION,
                    UNIQUE (timestamp, par)
                );
            """)

            # --- trades ---
            cur.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id                  SERIAL PRIMARY KEY,
                    par                 VARCHAR(20) NOT NULL,
                    direcao             VARCHAR(5) NOT NULL,
                    alavancagem         INTEGER NOT NULL,
                    preco_entrada       DOUBLE PRECISION NOT NULL,
                    preco_saida         DOUBLE PRECISION,
                    sl                  DOUBLE PRECISION NOT NULL,
                    tp                  DOUBLE PRECISION NOT NULL,
                    quantidade          DOUBLE PRECISION NOT NULL,
                    resultado           VARCHAR(10) DEFAULT 'OPEN',
                    lucro_usd           DOUBLE PRECISION DEFAULT 0,
                    lucro_pct           DOUBLE PRECISION DEFAULT 0,
                    motivo_entrada      TEXT,
                    timestamp_entrada   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    timestamp_saida     TIMESTAMPTZ,
                    taxas_pagas         DOUBLE PRECISION DEFAULT 0
                );
            """)

            # --- features ---
            cur.execute("""
                CREATE TABLE IF NOT EXISTS features (
                    timestamp           TIMESTAMPTZ NOT NULL,
                    par                 VARCHAR(20) NOT NULL,
                    ema9                DOUBLE PRECISION,
                    ema25               DOUBLE PRECISION,
                    ema50               DOUBLE PRECISION,
                    ema100              DOUBLE PRECISION,
                    rsi                 DOUBLE PRECISION,
                    atr                 DOUBLE PRECISION,
                    vwap                DOUBLE PRECISION,
                    cvd                 DOUBLE PRECISION,
                    ob_imbalance        DOUBLE PRECISION,
                    taker_ratio         DOUBLE PRECISION,
                    vol_relativo        DOUBLE PRECISION,
                    regime              VARCHAR(20),
                    fear_greed          DOUBLE PRECISION,
                    sentimento_noticias DOUBLE PRECISION,
                    funding_rate        DOUBLE PRECISION,
                    open_interest       DOUBLE PRECISION,
                    UNIQUE (timestamp, par)
                );
            """)

            # --- performance_diaria ---
            cur.execute("""
                CREATE TABLE IF NOT EXISTS performance_diaria (
                    data            DATE NOT NULL,
                    total_trades    INTEGER DEFAULT 0,
                    wins            INTEGER DEFAULT 0,
                    losses          INTEGER DEFAULT 0,
                    win_rate        DOUBLE PRECISION DEFAULT 0,
                    lucro_total     DOUBLE PRECISION DEFAULT 0,
                    maior_perda     DOUBLE PRECISION DEFAULT 0,
                    drawdown_max    DOUBLE PRECISION DEFAULT 0,
                    sharpe          DOUBLE PRECISION DEFAULT 0,
                    UNIQUE (data)
                );
            """)

            # --- noticias ---
            cur.execute("""
                CREATE TABLE IF NOT EXISTS noticias (
                    id                  SERIAL PRIMARY KEY,
                    timestamp           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    titulo              TEXT NOT NULL,
                    url                 TEXT,
                    sentimento_score    DOUBLE PRECISION,
                    fonte               VARCHAR(100),
                    par_relacionado     VARCHAR(20)
                );
            """)

            # --- model_versions ---
            cur.execute("""
                CREATE TABLE IF NOT EXISTS model_versions (
                    id                  SERIAL PRIMARY KEY,
                    versao              VARCHAR(50) NOT NULL,
                    timestamp_treino    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    acuracia            DOUBLE PRECISION,
                    precisao            DOUBLE PRECISION,
                    recall              DOUBLE PRECISION,
                    caminho_arquivo     TEXT NOT NULL
                );
            """)

            # Converter tabelas de series temporais em hypertables
            _hypertables = [
                ("candles", "timestamp"),
                ("order_book_snapshots", "timestamp"),
                ("funding_rate", "timestamp"),
                ("features", "timestamp"),
            ]
            for tabela, coluna in _hypertables:
                cur.execute(f"""
                    SELECT EXISTS (
                        SELECT 1 FROM timescaledb_information.hypertables
                        WHERE hypertable_name = '{tabela}'
                    );
                """)
                is_hypertable = cur.fetchone()[0]
                if not is_hypertable:
                    cur.execute(
                        f"SELECT create_hypertable('{tabela}', '{coluna}', "
                        f"if_not_exists => TRUE, migrate_data => TRUE);"
                    )
                    logger.info(f"Hypertable criada: {tabela}")

        conn.commit()
        logger.info("Todas as tabelas criadas com sucesso.")
    except Exception as e:
        conn.rollback()
        logger.error(f"Erro ao criar tabelas: {e}")
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Insercoes
# ---------------------------------------------------------------------------

def insert_candle(par: str, timestamp, open_: float, high: float, low: float,
                  close: float, volume: float, timeframe: str):
    """Insere um candle (upsert por timestamp+par+timeframe)."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO candles (timestamp, par, open, high, low, close, volume, timeframe)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (timestamp, par, timeframe) DO UPDATE SET
                    open = EXCLUDED.open, high = EXCLUDED.high,
                    low = EXCLUDED.low, close = EXCLUDED.close,
                    volume = EXCLUDED.volume;
            """, (timestamp, par, open_, high, low, close, volume, timeframe))
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"Erro ao inserir candle: {e}")
        raise
    finally:
        conn.close()


def insert_trade(par: str, direcao: str, alavancagem: int, preco_entrada: float,
                 sl: float, tp: float, quantidade: float, motivo_entrada: str) -> int:
    """Insere um novo trade e retorna o id."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO trades (par, direcao, alavancagem, preco_entrada, sl, tp,
                                    quantidade, motivo_entrada)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id;
            """, (par, direcao, alavancagem, preco_entrada, sl, tp,
                  quantidade, motivo_entrada))
            trade_id = cur.fetchone()[0]
        conn.commit()
        logger.info(f"Trade #{trade_id} aberto: {direcao} {par} @ {preco_entrada}")
        return trade_id
    except Exception as e:
        conn.rollback()
        logger.error(f"Erro ao inserir trade: {e}")
        raise
    finally:
        conn.close()


def insert_features(par: str, timestamp, **kwargs):
    """Insere um registro de features (upsert por timestamp+par)."""
    colunas = ["timestamp", "par"] + list(kwargs.keys())
    valores = [timestamp, par] + list(kwargs.values())
    placeholders = ", ".join(["%s"] * len(valores))
    col_names = ", ".join(colunas)

    update_set = ", ".join(
        f"{c} = EXCLUDED.{c}" for c in kwargs.keys()
    )

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                INSERT INTO features ({col_names})
                VALUES ({placeholders})
                ON CONFLICT (timestamp, par) DO UPDATE SET {update_set};
            """, valores)
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"Erro ao inserir features: {e}")
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Atualizacoes
# ---------------------------------------------------------------------------

def update_trade_resultado(trade_id: int, preco_saida: float, resultado: str,
                           lucro_usd: float, lucro_pct: float, taxas_pagas: float):
    """Atualiza o resultado de um trade fechado."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE trades
                SET preco_saida = %s, resultado = %s, lucro_usd = %s,
                    lucro_pct = %s, taxas_pagas = %s, timestamp_saida = NOW()
                WHERE id = %s;
            """, (preco_saida, resultado, lucro_usd, lucro_pct, taxas_pagas, trade_id))
        conn.commit()
        logger.info(f"Trade #{trade_id} fechado: {resultado} | {lucro_usd:.2f} USD")
    except Exception as e:
        conn.rollback()
        logger.error(f"Erro ao atualizar trade #{trade_id}: {e}")
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Consultas
# ---------------------------------------------------------------------------

def get_historical_features(par: str, inicio: datetime, fim: datetime) -> list[dict]:
    """Retorna features historicas para um par em um intervalo de tempo."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT * FROM features
                WHERE par = %s AND timestamp >= %s AND timestamp <= %s
                ORDER BY timestamp ASC;
            """, (par, inicio, fim))
            return cur.fetchall()
    except Exception as e:
        logger.error(f"Erro ao consultar features: {e}")
        raise
    finally:
        conn.close()


def get_performance_diaria(data_inicio: Optional[date] = None,
                           data_fim: Optional[date] = None) -> list[dict]:
    """Retorna registros de performance diaria."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            query = "SELECT * FROM performance_diaria"
            params = []
            conditions = []

            if data_inicio:
                conditions.append("data >= %s")
                params.append(data_inicio)
            if data_fim:
                conditions.append("data <= %s")
                params.append(data_fim)

            if conditions:
                query += " WHERE " + " AND ".join(conditions)

            query += " ORDER BY data DESC;"
            cur.execute(query, params)
            return cur.fetchall()
    except Exception as e:
        logger.error(f"Erro ao consultar performance diaria: {e}")
        raise
    finally:
        conn.close()


def get_trades_recentes(limite: int = 50) -> list[dict]:
    """Retorna os trades mais recentes."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT * FROM trades
                ORDER BY timestamp_entrada DESC
                LIMIT %s;
            """, (limite,))
            return cur.fetchall()
    except Exception as e:
        logger.error(f"Erro ao consultar trades recentes: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    logger.info("Inicializando banco de dados...")
    create_tables()
    logger.info("Banco de dados inicializado.")

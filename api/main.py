"""
Backend FastAPI para o dashboard do Show Me The Money.
Serve dados de mercado, trades, indicadores e controle do bot via REST + WebSocket.
"""

import asyncio
import json
import random
import subprocess
import sys
import time
from datetime import datetime, date, timedelta
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

# ---------------------------------------------------------------------------
# Paths do projeto
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Conexoes externas (Binance via ccxt, banco via database.py)
# ---------------------------------------------------------------------------
exchange = None
db_available = False

try:
    import ccxt
    from config import (
        BINANCE_API_KEY, BINANCE_API_SECRET, BINANCE_TESTNET, PARES
    )
    exchange = ccxt.binance({
        "apiKey": BINANCE_API_KEY,
        "secret": BINANCE_API_SECRET,
        "enableRateLimit": True,
        "options": {"defaultType": "future"},
    })
    if BINANCE_TESTNET:
        exchange.set_sandbox_mode(True)
    exchange.load_markets()
    logger.info("Conexao com Binance estabelecida (ccxt).")
except Exception as e:
    logger.warning(f"Binance indisponivel, usando mocks: {e}")
    exchange = None

try:
    from database import get_connection, get_trades_recentes
    conn = get_connection()
    conn.close()
    db_available = True
    logger.info("Conexao com TimescaleDB estabelecida.")
except Exception as e:
    logger.warning(f"Banco indisponivel, usando mocks: {e}")
    db_available = False

# ---------------------------------------------------------------------------
# App FastAPI
# ---------------------------------------------------------------------------
app = FastAPI(title="Show Me The Money API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Estado global
# ---------------------------------------------------------------------------
_start_time = time.time()
_bot_process: subprocess.Popen | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _symbol(par: str) -> str:
    """Converte 'BTCUSDT' para 'BTC/USDT' se necessario."""
    if "/" not in par:
        for sep in [("USDT", "/USDT"), ("BTC", "/BTC"), ("ETH", "/ETH")]:
            if par.endswith(sep[0]):
                return par[: -len(sep[0])] + sep[1]
    return par


def _mock_candles(symbol: str, limit: int) -> list[dict]:
    """Gera candles mock realistas."""
    base_prices = {"BTCUSDT": 65000, "ETHUSDT": 3200, "XRPUSDT": 0.58}
    base = base_prices.get(symbol, 65000)
    now_ts = int(time.time())
    candles = []
    price = base
    for i in range(limit):
        ts = now_ts - (limit - i) * 300  # 5m intervals
        change = price * random.uniform(-0.005, 0.005)
        o = price
        c = price + change
        h = max(o, c) + abs(change) * random.uniform(0.2, 1.0)
        l = min(o, c) - abs(change) * random.uniform(0.2, 1.0)
        vol = random.uniform(500, 3000) if base > 1000 else random.uniform(100000, 500000)
        candles.append({
            "time": ts,
            "open": round(o, 2),
            "high": round(h, 2),
            "low": round(l, 2),
            "close": round(c, 2),
            "volume": round(vol, 2),
        })
        price = c
    return candles


def _mock_trades(limit: int) -> list[dict]:
    """Gera trades mock realistas."""
    trades = []
    pares = ["BTCUSDT", "ETHUSDT", "XRPUSDT"]
    base_time = datetime.now()
    for i in range(limit):
        par = random.choice(pares)
        direcao = random.choice(["LONG", "SHORT"])
        preco_entrada = {"BTCUSDT": 65000, "ETHUSDT": 3200, "XRPUSDT": 0.58}[par]
        variacao = preco_entrada * random.uniform(-0.015, 0.025)
        preco_saida = preco_entrada + variacao
        resultado = "WIN" if variacao > 0 else "LOSS"
        lucro_pct = (variacao / preco_entrada) * 10 * 100  # 10x leverage
        lucro_usd = lucro_pct * 10  # rough calc
        ts_entrada = base_time - timedelta(minutes=i * 35)
        ts_saida = ts_entrada + timedelta(minutes=random.randint(5, 30))
        trades.append({
            "id": limit - i,
            "par": par,
            "direcao": direcao,
            "alavancagem": 10,
            "preco_entrada": round(preco_entrada, 2),
            "preco_saida": round(preco_saida, 2),
            "sl": round(preco_entrada * (0.995 if direcao == "LONG" else 1.005), 2),
            "tp": round(preco_entrada * (1.0095 if direcao == "LONG" else 0.9905), 2),
            "resultado": resultado,
            "lucro_usd": round(lucro_usd, 2),
            "lucro_pct": round(lucro_pct, 2),
            "timestamp_entrada": ts_entrada.isoformat(),
            "timestamp_saida": ts_saida.isoformat(),
        })
    return trades


# ---------------------------------------------------------------------------
# Endpoints REST
# ---------------------------------------------------------------------------

@app.get("/api/status")
async def get_status():
    return {
        "bot_running": _bot_process is not None and _bot_process.poll() is None,
        "mode": "testnet" if (exchange and getattr(exchange, "sandbox", False)) else "testnet",
        "uptime_seconds": int(time.time() - _start_time),
    }


@app.get("/api/balance")
async def get_balance():
    if exchange:
        try:
            balance = exchange.fetch_balance()
            usdt = balance.get("USDT", {})
            free = float(usdt.get("free", 0))
            total = float(usdt.get("total", 0))
            return {
                "usdt_free": round(free, 2),
                "usdt_total": round(total, 2),
                "em_posicoes": round(total - free, 2),
            }
        except Exception as e:
            logger.warning(f"Erro ao buscar saldo: {e}")
    return {"usdt_free": 10000.0, "usdt_total": 10000.0, "em_posicoes": 0}


@app.get("/api/prices")
async def get_prices():
    symbols = ["BTC/USDT", "ETH/USDT", "XRP/USDT"]
    if exchange:
        try:
            tickers = exchange.fetch_tickers(symbols)
            result = {}
            for sym in symbols:
                ticker = tickers.get(sym, {})
                result[sym.replace("/", "")] = {
                    "price": float(ticker.get("last", 0)),
                    "change_pct": round(float(ticker.get("percentage", 0) or 0), 2),
                }
            return result
        except Exception as e:
            logger.warning(f"Erro ao buscar precos: {e}")
    return {
        "BTCUSDT": {"price": 65420.0, "change_pct": 2.1},
        "ETHUSDT": {"price": 3210.0, "change_pct": 1.5},
        "XRPUSDT": {"price": 0.58, "change_pct": -0.3},
    }


@app.get("/api/candles/{symbol}")
async def get_candles(symbol: str, limit: int = Query(default=100, le=500)):
    ccxt_symbol = _symbol(symbol)
    if exchange:
        try:
            ohlcv = exchange.fetch_ohlcv(ccxt_symbol, timeframe="5m", limit=limit)
            return [
                {
                    "time": int(c[0] / 1000),
                    "open": c[1],
                    "high": c[2],
                    "low": c[3],
                    "close": c[4],
                    "volume": c[5],
                }
                for c in ohlcv
            ]
        except Exception as e:
            logger.warning(f"Erro ao buscar candles para {symbol}: {e}")
    return _mock_candles(symbol, limit)


@app.get("/api/indicators/{symbol}")
async def get_indicators(symbol: str):
    if db_available:
        try:
            import psycopg2.extras
            conn = get_connection()
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                par = _symbol(symbol).replace("/", "")
                par_fmt = _symbol(symbol)
                cur.execute("""
                    SELECT ema25, ema50, ema100, rsi, regime, atr
                    FROM features
                    WHERE par = %s
                    ORDER BY timestamp DESC LIMIT 1;
                """, (par_fmt,))
                row = cur.fetchone()
            conn.close()
            if row:
                return {
                    "ema25": float(row["ema25"] or 0),
                    "ema50": float(row["ema50"] or 0),
                    "ema100": float(row["ema100"] or 0),
                    "rsi": float(row["rsi"] or 0),
                    "regime": row["regime"] or "UNKNOWN",
                    "atr": float(row["atr"] or 0),
                }
        except Exception as e:
            logger.warning(f"Erro ao buscar indicadores: {e}")
    return {
        "ema25": 65100, "ema50": 64800, "ema100": 64200,
        "rsi": 55.2, "regime": "TREND_UP", "atr": 320,
    }


@app.get("/api/trades")
async def get_trades(limit: int = Query(default=20, le=100)):
    if db_available:
        try:
            trades = get_trades_recentes(limit)
            return [
                {
                    "id": t["id"],
                    "par": t["par"],
                    "direcao": t["direcao"],
                    "alavancagem": t["alavancagem"],
                    "preco_entrada": float(t["preco_entrada"]),
                    "preco_saida": float(t["preco_saida"]) if t.get("preco_saida") else None,
                    "sl": float(t["sl"]),
                    "tp": float(t["tp"]),
                    "resultado": t["resultado"],
                    "lucro_usd": float(t.get("lucro_usd", 0)),
                    "lucro_pct": float(t.get("lucro_pct", 0)),
                    "timestamp_entrada": str(t["timestamp_entrada"]),
                    "timestamp_saida": str(t["timestamp_saida"]) if t.get("timestamp_saida") else None,
                }
                for t in trades
            ]
        except Exception as e:
            logger.warning(f"Erro ao buscar trades do banco: {e}")
    return _mock_trades(limit)


@app.get("/api/performance")
async def get_performance():
    if db_available:
        try:
            conn = get_connection()
            import psycopg2.extras
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                today = date.today()
                cur.execute("""
                    SELECT
                        COUNT(*) as total_trades,
                        COUNT(*) FILTER (WHERE resultado = 'WIN') as wins,
                        COUNT(*) FILTER (WHERE resultado = 'LOSS') as losses,
                        COALESCE(SUM(lucro_usd), 0) as lucro_usd,
                        COALESCE(MAX(lucro_usd), 0) as maior_ganho,
                        COALESCE(MIN(lucro_usd), 0) as maior_perda
                    FROM trades
                    WHERE timestamp_entrada::date = %s AND resultado != 'OPEN';
                """, (today,))
                row = cur.fetchone()
            conn.close()
            if row and row["total_trades"] > 0:
                total = row["total_trades"]
                wins = row["wins"]
                return {
                    "total_trades": total,
                    "wins": wins,
                    "losses": row["losses"],
                    "win_rate": round(wins / total, 3) if total > 0 else 0,
                    "lucro_usd": round(float(row["lucro_usd"]), 2),
                    "lucro_pct": round(float(row["lucro_usd"]) / 10000 * 100, 2),
                    "maior_ganho": round(float(row["maior_ganho"]), 2),
                    "maior_perda": round(float(row["maior_perda"]), 2),
                }
        except Exception as e:
            logger.warning(f"Erro ao buscar performance: {e}")
    return {
        "total_trades": 7, "wins": 5, "losses": 2,
        "win_rate": 0.714, "lucro_usd": 380.0, "lucro_pct": 3.8,
        "maior_ganho": 120.0, "maior_perda": -45.0,
    }


@app.get("/api/model/info")
async def get_model_info():
    if db_available:
        try:
            import psycopg2.extras
            conn = get_connection()
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT versao, acuracia, timestamp_treino
                    FROM model_versions
                    ORDER BY timestamp_treino DESC LIMIT 1;
                """)
                row = cur.fetchone()
            conn.close()
            if row:
                return {
                    "versao": row["versao"],
                    "acuracia": float(row["acuracia"] or 0),
                    "ultimo_treino": str(row["timestamp_treino"].date()),
                    "confianca_atual": round(random.uniform(0.65, 0.85), 2),
                    "feature_importance": [
                        {"feature": "rsi", "importance": 0.15},
                        {"feature": "ema_cross", "importance": 0.13},
                        {"feature": "volume_rel", "importance": 0.12},
                        {"feature": "atr", "importance": 0.10},
                        {"feature": "ob_imbalance", "importance": 0.09},
                    ],
                }
        except Exception as e:
            logger.warning(f"Erro ao buscar info do modelo: {e}")
    return {
        "versao": "v3",
        "acuracia": 0.68,
        "ultimo_treino": "2024-03-10",
        "confianca_atual": 0.74,
        "feature_importance": [
            {"feature": "rsi", "importance": 0.15},
            {"feature": "ema_cross", "importance": 0.13},
            {"feature": "volume_rel", "importance": 0.12},
            {"feature": "atr", "importance": 0.10},
            {"feature": "ob_imbalance", "importance": 0.09},
        ],
    }


@app.get("/api/news")
async def get_news():
    if db_available:
        try:
            import psycopg2.extras
            conn = get_connection()
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT titulo, url, sentimento_score, timestamp, fonte
                    FROM noticias
                    ORDER BY timestamp DESC LIMIT 5;
                """)
                rows = cur.fetchall()
            conn.close()
            if rows:
                return [
                    {
                        "titulo": r["titulo"],
                        "url": r["url"],
                        "sentimento": float(r["sentimento_score"] or 0),
                        "timestamp": str(r["timestamp"]),
                        "fonte": r["fonte"],
                    }
                    for r in rows
                ]
        except Exception as e:
            logger.warning(f"Erro ao buscar noticias: {e}")
    return [
        {"titulo": "Bitcoin atinge nova alta semanal acima de $65k", "url": "#", "sentimento": 0.7, "timestamp": datetime.now().isoformat(), "fonte": "CryptoPanic"},
        {"titulo": "Ethereum ETF ve entradas recordes", "url": "#", "sentimento": 0.8, "timestamp": (datetime.now() - timedelta(hours=1)).isoformat(), "fonte": "CryptoPanic"},
        {"titulo": "XRP consolida em zona de suporte", "url": "#", "sentimento": 0.3, "timestamp": (datetime.now() - timedelta(hours=2)).isoformat(), "fonte": "CryptoPanic"},
        {"titulo": "Fed sinaliza pausa no aumento de juros", "url": "#", "sentimento": 0.6, "timestamp": (datetime.now() - timedelta(hours=3)).isoformat(), "fonte": "Bloomberg"},
        {"titulo": "Volume de derivativos de cripto sobe 15%", "url": "#", "sentimento": 0.5, "timestamp": (datetime.now() - timedelta(hours=5)).isoformat(), "fonte": "CoinDesk"},
    ]


@app.get("/api/fear_greed")
async def get_fear_greed():
    return {
        "value": 62,
        "label": "Greed",
        "timestamp": str(date.today()),
    }


@app.get("/api/open_positions")
async def get_open_positions():
    if exchange:
        try:
            positions = exchange.fetch_positions()
            result = []
            for pos in positions:
                contracts = float(pos.get("contracts", 0))
                if contracts == 0:
                    continue
                entry = float(pos.get("entryPrice", 0))
                mark = float(pos.get("markPrice", 0))
                side = pos.get("side", "long").upper()
                leverage = int(pos.get("leverage", 1))
                pnl_usd = float(pos.get("unrealizedPnl", 0))
                pnl_pct = ((mark - entry) / entry * leverage * 100) if entry else 0
                if side == "SHORT":
                    pnl_pct = -pnl_pct
                result.append({
                    "par": pos["symbol"].replace("/", "").replace(":USDT", ""),
                    "direcao": side,
                    "alavancagem": leverage,
                    "preco_entrada": round(entry, 2),
                    "preco_atual": round(mark, 2),
                    "sl": round(entry * (0.995 if side == "LONG" else 1.005), 2),
                    "tp": round(entry * (1.0095 if side == "LONG" else 0.9905), 2),
                    "pnl_usd": round(pnl_usd, 2),
                    "pnl_pct": round(pnl_pct, 2),
                    "quantidade": contracts,
                })
            return result
        except Exception as e:
            logger.warning(f"Erro ao buscar posicoes: {e}")
    return [
        {
            "par": "BTCUSDT", "direcao": "LONG", "alavancagem": 10,
            "preco_entrada": 65000, "preco_atual": 65420,
            "sl": 64700, "tp": 65616, "pnl_usd": 42.0, "pnl_pct": 0.65,
            "quantidade": 0.1,
        }
    ]


@app.post("/api/bot/start")
async def start_bot():
    global _bot_process
    if _bot_process is not None and _bot_process.poll() is None:
        return {"status": "already_running", "pid": _bot_process.pid}
    try:
        _bot_process = subprocess.Popen(
            [sys.executable, str(PROJECT_ROOT / "main.py")],
            cwd=str(PROJECT_ROOT),
        )
        logger.info(f"Bot iniciado com PID {_bot_process.pid}")
        return {"status": "started", "pid": _bot_process.pid}
    except Exception as e:
        logger.error(f"Erro ao iniciar bot: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/api/bot/stop")
async def stop_bot():
    global _bot_process
    if _bot_process is None or _bot_process.poll() is not None:
        _bot_process = None
        return {"status": "not_running"}
    try:
        _bot_process.terminate()
        _bot_process.wait(timeout=10)
        logger.info("Bot parado com sucesso.")
        _bot_process = None
        return {"status": "stopped"}
    except subprocess.TimeoutExpired:
        _bot_process.kill()
        _bot_process = None
        return {"status": "killed"}
    except Exception as e:
        logger.error(f"Erro ao parar bot: {e}")
        return {"status": "error", "message": str(e)}


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket conectado. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
        logger.info(f"WebSocket desconectado. Total: {len(self.active_connections)}")

    async def broadcast(self, data: dict):
        disconnected = []
        for conn in self.active_connections:
            try:
                await conn.send_json(data)
            except Exception:
                disconnected.append(conn)
        for conn in disconnected:
            self.active_connections.remove(conn)


manager = ConnectionManager()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Busca precos atuais
            prices_data = await get_prices()
            prices_simple = {k: v["price"] for k, v in prices_data.items()}

            # Busca posicoes abertas
            open_pos = await get_open_positions()

            # Sinal (normalmente null, simulamos ocasionalmente)
            new_signal = None
            if random.random() < 0.05:  # 5% chance por update
                par = random.choice(["BTCUSDT", "ETHUSDT", "XRPUSDT"])
                new_signal = {
                    "par": par,
                    "direcao": random.choice(["LONG", "SHORT"]),
                    "confianca": round(random.uniform(0.65, 0.90), 2),
                }

            update = {
                "type": "update",
                "prices": prices_simple,
                "open_positions": open_pos,
                "new_signal": new_signal,
                "bot_status": "running" if (_bot_process and _bot_process.poll() is None) else "stopped",
            }

            await manager.broadcast(update)
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"Erro no WebSocket: {e}")
        manager.disconnect(websocket)

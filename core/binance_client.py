"""
Cliente Binance Futures usando ccxt (REST) e websockets (async streams).
"""

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Callable, Optional

import ccxt
import websockets
from loguru import logger

try:
    from config import Config
except ImportError:
    class Config:
        BINANCE_API_KEY = ""
        BINANCE_API_SECRET = ""
        BINANCE_TESTNET = True
        DEFAULT_LEVERAGE = 10
        TRADING_PAIR = "BTC/USDT"


class BinanceClient:
    """Cliente REST + WebSocket para Binance Futures."""

    TESTNET_WS_URL = "wss://stream.binancefuture.com/ws"
    PRODUCTION_WS_URL = "wss://fstream.binance.com/ws"

    def __init__(
        self,
        api_key: str = None,
        api_secret: str = None,
        testnet: bool = None,
    ):
        api_key = api_key or Config.BINANCE_API_KEY
        api_secret = api_secret or Config.BINANCE_API_SECRET
        testnet = testnet if testnet is not None else Config.BINANCE_TESTNET

        self.exchange = ccxt.binanceusdm({
            "apiKey": api_key,
            "secret": api_secret,
            "enableRateLimit": True,
            "options": {
                "defaultType": "future",
                "adjustForTimeDifference": True,
            },
        })

        if testnet:
            self.exchange.set_sandbox_mode(True)
            self._ws_base = self.TESTNET_WS_URL
        else:
            self._ws_base = self.PRODUCTION_WS_URL

        self._ws_connections: list = []
        self._ws_running = False

        logger.info(
            "BinanceClient inicializado | testnet={} | rate_limit={}",
            testnet,
            self.exchange.rateLimit,
        )

    # ------------------------------------------------------------------ #
    #  Dados de mercado (REST)
    # ------------------------------------------------------------------ #

    def get_historical_candles(
        self,
        par: str,
        timeframe: str,
        inicio: datetime,
        fim: datetime,
    ) -> list[list]:
        """Baixa candles historicos em lotes de 1000."""
        all_candles = []
        since_ms = int(inicio.timestamp() * 1000)
        fim_ms = int(fim.timestamp() * 1000)

        while since_ms < fim_ms:
            try:
                candles = self.exchange.fetch_ohlcv(
                    par, timeframe, since=since_ms, limit=1000
                )
            except ccxt.RateLimitExceeded:
                logger.warning("Rate limit atingido, aguardando 10s...")
                time.sleep(10)
                continue
            except ccxt.BaseError as e:
                logger.error("Erro ao buscar candles: {}", e)
                time.sleep(5)
                continue

            if not candles:
                break

            all_candles.extend(candles)
            since_ms = candles[-1][0] + 1
            time.sleep(self.exchange.rateLimit / 1000)

        # Filtra candles que passaram do fim
        all_candles = [c for c in all_candles if c[0] <= fim_ms]
        logger.info(
            "Baixados {} candles de {} ({} -> {})",
            len(all_candles), par, inicio, fim,
        )
        return all_candles

    def get_candles(self, par: str, timeframe: str, limite: int = 100) -> list[list]:
        """Retorna candles recentes."""
        try:
            return self.exchange.fetch_ohlcv(par, timeframe, limit=limite)
        except ccxt.BaseError as e:
            logger.error("Erro ao buscar candles recentes: {}", e)
            return []

    def get_order_book(self, par: str, profundidade: int = 20) -> dict:
        """Retorna livro de ordens."""
        try:
            return self.exchange.fetch_order_book(par, limit=profundidade)
        except ccxt.BaseError as e:
            logger.error("Erro ao buscar order book: {}", e)
            return {"bids": [], "asks": []}

    def get_funding_rate(self, par: str) -> Optional[dict]:
        """Retorna funding rate atual."""
        try:
            ticker = self.exchange.fetch_funding_rate(par)
            return {
                "funding_rate": ticker.get("fundingRate"),
                "next_funding_time": ticker.get("fundingDatetime"),
            }
        except ccxt.BaseError as e:
            logger.error("Erro ao buscar funding rate: {}", e)
            return None

    def get_open_interest(self, par: str) -> Optional[dict]:
        """Retorna open interest atual."""
        try:
            oi = self.exchange.fetch_open_interest(par)
            return {
                "open_interest": oi.get("openInterestAmount"),
                "open_interest_value": oi.get("openInterestValue"),
            }
        except ccxt.BaseError as e:
            logger.error("Erro ao buscar open interest: {}", e)
            return None

    def get_taker_ratio(self, par: str, periodo: str = "5m") -> Optional[dict]:
        """Retorna buy/sell taker ratio via API pública da Binance."""
        try:
            symbol = par.replace("/", "")
            response = self.exchange.fapiPublicGetGlobalLongShortAccountRatio({
                "symbol": symbol,
                "period": periodo,
                "limit": 1,
            })
            if response:
                return {
                    "long_short_ratio": float(response[0]["longShortRatio"]),
                    "long_account": float(response[0]["longAccount"]),
                    "short_account": float(response[0]["shortAccount"]),
                }
        except Exception as e:
            logger.error("Erro ao buscar taker ratio: {}", e)
        return None

    def get_liquidations(self, par: str) -> list:
        """Retorna liquidacoes recentes via API publica."""
        try:
            symbol = par.replace("/", "")
            response = self.exchange.fapiPublicGetForceOrders({
                "symbol": symbol,
                "limit": 50,
            })
            return response if response else []
        except Exception as e:
            logger.error("Erro ao buscar liquidacoes: {}", e)
            return []

    # ------------------------------------------------------------------ #
    #  Gerenciamento de conta e ordens
    # ------------------------------------------------------------------ #

    def set_leverage(self, par: str, alavancagem: int) -> bool:
        """Define alavancagem para o par."""
        try:
            self.exchange.set_leverage(alavancagem, par)
            logger.info("Alavancagem de {} definida para {}x", par, alavancagem)
            return True
        except ccxt.BaseError as e:
            logger.error("Erro ao definir alavancagem: {}", e)
            return False

    def create_limit_order(
        self, par: str, direcao: str, quantidade: float, preco: float
    ) -> Optional[dict]:
        """Cria ordem limit. direcao: 'buy' ou 'sell'."""
        try:
            order = self.exchange.create_limit_order(
                par, direcao, quantidade, preco
            )
            logger.info(
                "Ordem limit criada: {} {} {} @ {}",
                direcao, quantidade, par, preco,
            )
            return order
        except ccxt.BaseError as e:
            logger.error("Erro ao criar ordem limit: {}", e)
            return None

    def create_market_order(
        self, par: str, direcao: str, quantidade: float
    ) -> Optional[dict]:
        """Cria ordem market. direcao: 'buy' ou 'sell'."""
        try:
            order = self.exchange.create_market_order(par, direcao, quantidade)
            logger.info(
                "Ordem market criada: {} {} {}",
                direcao, quantidade, par,
            )
            return order
        except ccxt.BaseError as e:
            logger.error("Erro ao criar ordem market: {}", e)
            return None

    def cancel_order(self, par: str, order_id: str) -> bool:
        """Cancela uma ordem."""
        try:
            self.exchange.cancel_order(order_id, par)
            logger.info("Ordem {} cancelada em {}", order_id, par)
            return True
        except ccxt.BaseError as e:
            logger.error("Erro ao cancelar ordem: {}", e)
            return False

    def get_open_positions(self) -> list[dict]:
        """Retorna posicoes abertas."""
        try:
            positions = self.exchange.fetch_positions()
            return [
                p for p in positions
                if float(p.get("contracts", 0)) > 0
            ]
        except ccxt.BaseError as e:
            logger.error("Erro ao buscar posicoes: {}", e)
            return []

    def get_balance(self) -> Optional[dict]:
        """Retorna saldo da conta."""
        try:
            balance = self.exchange.fetch_balance()
            return {
                "total": balance.get("total", {}).get("USDT", 0),
                "free": balance.get("free", {}).get("USDT", 0),
                "used": balance.get("used", {}).get("USDT", 0),
            }
        except ccxt.BaseError as e:
            logger.error("Erro ao buscar saldo: {}", e)
            return None

    def close_position(self, par: str) -> Optional[dict]:
        """Fecha posicao aberta no par."""
        try:
            positions = self.exchange.fetch_positions([par])
            for pos in positions:
                contracts = float(pos.get("contracts", 0))
                if contracts > 0:
                    side = "sell" if pos["side"] == "long" else "buy"
                    order = self.exchange.create_market_order(
                        par, side, contracts, params={"reduceOnly": True}
                    )
                    logger.info("Posicao fechada em {}: {} contratos", par, contracts)
                    return order
            logger.info("Nenhuma posicao aberta em {}", par)
            return None
        except ccxt.BaseError as e:
            logger.error("Erro ao fechar posicao: {}", e)
            return None

    # ------------------------------------------------------------------ #
    #  WebSocket streams (asyncio)
    # ------------------------------------------------------------------ #

    async def _connect_stream(
        self,
        stream_name: str,
        callback: Callable,
        max_retries: int = 10,
    ):
        """Conecta a um stream WebSocket com reconexao automatica e backoff exponencial."""
        url = f"{self._ws_base}/{stream_name}"
        retries = 0

        while self._ws_running and retries < max_retries:
            try:
                async with websockets.connect(url, ping_interval=20) as ws:
                    logger.info("WebSocket conectado: {}", stream_name)
                    retries = 0
                    self._ws_connections.append(ws)
                    async for msg in ws:
                        try:
                            data = json.loads(msg)
                            await callback(data)
                        except json.JSONDecodeError:
                            logger.warning("Mensagem WS invalida: {}", msg[:100])
                        except Exception as e:
                            logger.error("Erro no callback WS: {}", e)
            except websockets.ConnectionClosed as e:
                logger.warning(
                    "WebSocket {} desconectado: {}. Reconectando...",
                    stream_name, e,
                )
            except Exception as e:
                logger.error("Erro WebSocket {}: {}", stream_name, e)

            retries += 1
            wait_time = min(2 ** retries, 60)
            logger.info(
                "Reconectando {} em {}s (tentativa {}/{})",
                stream_name, wait_time, retries, max_retries,
            )
            await asyncio.sleep(wait_time)

        if retries >= max_retries:
            logger.error(
                "Max retries atingido para stream {}", stream_name
            )

    async def start_kline_stream(
        self, par: str, callback: Callable, timeframe: str = "5m"
    ):
        """Stream de candles em tempo real."""
        self._ws_running = True
        symbol = par.replace("/", "").lower()
        stream_name = f"{symbol}@kline_{timeframe}"
        await self._connect_stream(stream_name, callback)

    async def start_liquidation_stream(self, callback: Callable):
        """Stream de liquidacoes."""
        self._ws_running = True
        stream_name = "!forceOrder@arr"
        await self._connect_stream(stream_name, callback)

    async def start_book_ticker_stream(self, par: str, callback: Callable):
        """Stream de melhor bid/ask."""
        self._ws_running = True
        symbol = par.replace("/", "").lower()
        stream_name = f"{symbol}@bookTicker"
        await self._connect_stream(stream_name, callback)

    async def start_agg_trade_stream(self, par: str, callback: Callable):
        """Stream de trades agregados (para CVD)."""
        self._ws_running = True
        symbol = par.replace("/", "").lower()
        stream_name = f"{symbol}@aggTrade"
        await self._connect_stream(stream_name, callback)

    async def stop_streams(self):
        """Para todos os streams WebSocket."""
        self._ws_running = False
        for ws in self._ws_connections:
            try:
                await ws.close()
            except Exception:
                pass
        self._ws_connections.clear()
        logger.info("Todos os streams WebSocket encerrados")

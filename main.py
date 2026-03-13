"""
Show Me The Money - Bot de Scalping Alavancado na Binance.

Orquestrador principal que coordena todos os modulos:
- Coleta de dados via WebSocket e REST
- Calculo de indicadores tecnicos
- Geracao de sinais via ML + analise tecnica + sentimento
- Execucao de trades com gestao de risco
- Retreino semanal do modelo
"""

import asyncio
import signal
import sys
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import schedule
from loguru import logger

# Configuracoes e banco
from config import (
    BINANCE_TESTNET,
    PARES,
    TIMEFRAME,
    ALAVANCAGEM,
    CONFIANCA_MINIMA,
    LOGS_DIR,
    MODELS_DIR,
    DATA_DIR,
    validar_config,
)
from database import create_tables, insert_features, insert_candle

# Modulos core
from core.binance_client import BinanceClient
from core.data_collector import DataCollector
from core.indicators import calculate_all, calculate_order_book_imbalance
from core.model import ScalpingModel
from core.news_collector import NewsCollector
from core.signal_generator import SignalGenerator

# Modulos que podem nao existir ainda (criados por outro agente)
try:
    from core.risk_manager import RiskManager
except ImportError:
    RiskManager = None
    logger.warning("core.risk_manager nao encontrado — gestao de risco desabilitada")

try:
    from core.trader import Trader
except ImportError:
    Trader = None
    logger.warning("core.trader nao encontrado — execucao de trades desabilitada")

try:
    from core.trainer import ModelTrainer
except ImportError:
    ModelTrainer = None
    logger.warning("core.trainer nao encontrado — retreino automatico desabilitado")


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
VERSION = "0.1.0"
BOT_NAME = "Show Me The Money"
RECONNECT_INTERVAL = 30  # segundos entre tentativas de reconexao
DB_QUEUE_MAX = 1000  # maximo de registros na fila local de fallback

# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------

def _print_banner() -> None:
    """Exibe banner de inicializacao no terminal."""
    modo = "TESTNET" if BINANCE_TESTNET else "PRODUCAO"
    pares_str = ", ".join(PARES)
    banner = f"""
================================================================================
   {BOT_NAME} v{VERSION}
   Bot de Scalping Alavancado - Binance Futures
--------------------------------------------------------------------------------
   Modo:       {modo}
   Pares:      {pares_str}
   Timeframe:  {TIMEFRAME}
   Confianca:  {CONFIANCA_MINIMA:.0%}
   Hora:       {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC
================================================================================
"""
    print(banner)
    logger.info("{} v{} iniciado em modo {}", BOT_NAME, VERSION, modo)


# ---------------------------------------------------------------------------
# Classe principal
# ---------------------------------------------------------------------------

class ScalpingBot:
    """Orquestrador principal do bot de scalping."""

    def __init__(self) -> None:
        self._running = False
        self._tasks: list[asyncio.Task] = []

        # Fila local para salvar no banco caso ele caia
        self._db_queue: deque = deque(maxlen=DB_QUEUE_MAX)

        # Estado do ultimo candle processado por par
        self._last_candle_ts: Dict[str, int] = {}

        # Dados em tempo real vindos dos WebSockets
        self._ws_data: Dict[str, Dict[str, Any]] = {
            par: {
                "last_kline": None,
                "ob_imbalance": 0.0,
                "liquidations": [],
            }
            for par in PARES
        }

        # Componentes (inicializados em _setup)
        self._client: Optional[BinanceClient] = None
        self._data_collector: Optional[DataCollector] = None
        self._model: Optional[ScalpingModel] = None
        self._news: Optional[NewsCollector] = None
        self._signal_gen: Optional[SignalGenerator] = None
        self._risk_manager: Optional[Any] = None
        self._trader: Optional[Any] = None
        self._trainer: Optional[Any] = None

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _setup(self) -> bool:
        """Inicializa todos os componentes. Retorna True se sucesso."""
        logger.info("Inicializando componentes...")

        # 1. Validar configuracao
        if not validar_config():
            logger.error("Configuracao invalida. Verifique .env")
            return False

        # 2. Criar diretorios necessarios
        for d in [LOGS_DIR, MODELS_DIR, DATA_DIR]:
            d.mkdir(parents=True, exist_ok=True)

        # 3. Banco de dados
        try:
            create_tables()
            logger.info("Banco de dados inicializado")
        except Exception as e:
            logger.warning("Falha ao inicializar banco: {}. Continuando sem persistencia.", e)

        # 4. Cliente Binance
        self._client = BinanceClient(testnet=BINANCE_TESTNET)

        # 5. Configurar alavancagem para cada par
        for par, alav in ALAVANCAGEM.items():
            self._client.set_leverage(par, alav)

        # 6. Data Collector
        self._data_collector = DataCollector(self._client)

        # 7. NewsCollector
        self._news = NewsCollector()

        # 8. Modelo ML
        self._model = ScalpingModel()

        # 9. Signal Generator
        self._signal_gen = SignalGenerator(self._model, self._news)

        # 10. Risk Manager (pode nao existir)
        if RiskManager is not None:
            try:
                self._risk_manager = RiskManager(self._client)
                logger.info("RiskManager inicializado")
            except Exception as e:
                logger.warning("Falha ao inicializar RiskManager: {}", e)

        # 11. Trader (pode nao existir)
        if Trader is not None:
            try:
                self._trader = Trader(self._client, self._risk_manager)
                logger.info("Trader inicializado")
            except Exception as e:
                logger.warning("Falha ao inicializar Trader: {}", e)

        # 12. Trainer (pode nao existir)
        if ModelTrainer is not None:
            try:
                self._trainer = ModelTrainer(self._model, self._data_collector, None)
                logger.info("ModelTrainer inicializado")
            except Exception as e:
                logger.warning("Falha ao inicializar ModelTrainer: {}", e)

        logger.info("Todos os componentes inicializados com sucesso")
        return True

    # ------------------------------------------------------------------
    # WebSocket callbacks
    # ------------------------------------------------------------------

    async def _on_kline(self, data: Dict[str, Any]) -> None:
        """Callback para stream de klines."""
        try:
            kline = data.get("k", {})
            symbol = kline.get("s", "")
            # Converter symbol (BTCUSDT) para par (BTC/USDT)
            par = self._symbol_to_par(symbol)
            if par not in self._ws_data:
                return

            self._ws_data[par]["last_kline"] = kline

            # Se o candle fechou (is_final=True), processar
            if kline.get("x", False):
                ts = kline.get("t", 0)
                if ts != self._last_candle_ts.get(par, 0):
                    self._last_candle_ts[par] = ts
                    await self._process_closed_candle(par, kline)
        except Exception as e:
            logger.error("Erro no callback kline: {}", e)

    async def _on_liquidation(self, data: Dict[str, Any]) -> None:
        """Callback para stream de liquidacoes."""
        try:
            orders = data if isinstance(data, list) else [data]
            for order in orders:
                o = order.get("o", order)
                symbol = o.get("s", "")
                par = self._symbol_to_par(symbol)
                if par in self._ws_data:
                    self._ws_data[par]["liquidations"].append({
                        "side": o.get("S", ""),
                        "qty": float(o.get("q", 0)),
                        "price": float(o.get("p", 0)),
                        "timestamp": o.get("T", 0),
                    })
                    # Manter apenas as ultimas 100 liquidacoes
                    if len(self._ws_data[par]["liquidations"]) > 100:
                        self._ws_data[par]["liquidations"] = \
                            self._ws_data[par]["liquidations"][-100:]
        except Exception as e:
            logger.error("Erro no callback liquidacao: {}", e)

    async def _on_book_ticker(self, data: Dict[str, Any]) -> None:
        """Callback para stream de book ticker (bid/ask)."""
        try:
            symbol = data.get("s", "")
            par = self._symbol_to_par(symbol)
            if par not in self._ws_data:
                return

            bid_qty = float(data.get("B", 0))
            ask_qty = float(data.get("A", 0))
            self._ws_data[par]["ob_imbalance"] = calculate_order_book_imbalance(
                bid_qty, ask_qty
            )
        except Exception as e:
            logger.error("Erro no callback book ticker: {}", e)

    # ------------------------------------------------------------------
    # Processamento de candle fechado
    # ------------------------------------------------------------------

    async def _process_closed_candle(
        self, par: str, kline: Dict[str, Any]
    ) -> None:
        """Processa um candle fechado: indicadores, sinal, trade.

        Este e o nucleo do loop de scalping. Executado a cada 5 minutos
        quando um candle fecha.
        """
        import pandas as pd

        logger.info("[{}] Candle fechado: O={} H={} L={} C={} V={}",
                     par, kline.get("o"), kline.get("h"),
                     kline.get("l"), kline.get("c"), kline.get("v"))

        try:
            # a. Buscar candles recentes para calcular indicadores (200 de warmup)
            candles_raw = self._client.get_candles(par, TIMEFRAME, 200)
            if not candles_raw or len(candles_raw) < 50:
                logger.warning("[{}] Candles insuficientes: {}", par, len(candles_raw) if candles_raw else 0)
                return

            df = pd.DataFrame(
                candles_raw,
                columns=["timestamp", "open", "high", "low", "close", "volume"],
            )

            # b. Calcular indicadores tecnicos
            df = calculate_all(df)

            # c. Obter snapshot de features (tecnico + mercado + externo)
            features = self._build_features(par, df)
            if features is None:
                return

            # d. Gerar sinal via SignalGenerator
            sinal = self._signal_gen.analyze(par, df, features)

            # e. Se sinal != NEUTRO: executar via Trader
            if sinal["sinal"] != "NEUTRO":
                await self._execute_signal(par, sinal, features)

            # f. Monitorar posicoes abertas
            await self._monitor_positions(par)

            # g. Salvar features no banco para futuro treino
            self._save_features(par, features)

        except Exception as e:
            logger.error("[{}] Erro ao processar candle: {}", par, e)

    def _build_features(
        self, par: str, df: "pd.DataFrame"
    ) -> Optional[Dict[str, Any]]:
        """Monta dicionario de features a partir do DataFrame de indicadores."""
        import pandas as pd

        if df.empty:
            return None

        latest = df.iloc[-1]

        # Features tecnicas
        features: Dict[str, Any] = {
            "ema9": latest.get("ema_9", 0),
            "ema25": latest.get("ema_25", 0),
            "ema50": latest.get("ema_50", 0),
            "ema100": latest.get("ema_100", 0),
            "rsi": latest.get("rsi_7", 50),
            "atr": latest.get("atr_14", 0),
            "vwap": latest.get("vwap", 0),
            "cvd": latest.get("cvd", 0),
            "volume_relativo": latest.get("relative_volume", 1.0),
            "candle_position": latest.get("close_position", 0.5),
            "sombra_superior": latest.get("upper_shadow_ratio", 0),
            "sombra_inferior": latest.get("lower_shadow_ratio", 0),
            "corpo_candle": latest.get("body_ratio", 0),
            "sequencia_candles": latest.get("candle_sequence", 0),
        }

        # Regime encoded
        regime = latest.get("regime", "LATERAL")
        regime_map = {"LATERAL": 0, "TREND_UP": 1, "TREND_DOWN": 2}
        features["regime_encoded"] = regime_map.get(regime, 0)
        features["regime"] = regime

        # Dados de microestrutura (do WebSocket)
        ws = self._ws_data.get(par, {})
        features["ob_imbalance"] = ws.get("ob_imbalance", 0.0)
        features["taker_ratio"] = latest.get("taker_buy_ratio", 0.5)

        # Dados externos
        try:
            fg = self._news.get_fear_greed_index()
            features["fear_greed"] = fg.get("valor", 50)
        except Exception:
            features["fear_greed"] = 50

        try:
            simbolo = par.split("/")[0]
            features["sentimento_noticias"] = self._news.get_news_sentiment_score(simbolo)
        except Exception:
            features["sentimento_noticias"] = 0.0

        # Funding rate e open interest
        try:
            funding = self._client.get_funding_rate(par)
            features["funding_rate"] = funding["funding_rate"] if funding else 0.0
        except Exception:
            features["funding_rate"] = 0.0

        try:
            oi = self._client.get_open_interest(par)
            features["open_interest"] = oi["open_interest"] if oi else 0.0
            features["open_interest_change"] = 0.0  # TODO: calcular delta vs anterior
        except Exception:
            features["open_interest"] = 0.0
            features["open_interest_change"] = 0.0

        # Relacoes preco vs EMAs (percentual)
        close = latest.get("close", 0)
        if close > 0:
            features["preco_vs_ema25"] = ((close - features["ema25"]) / close) * 100 if features["ema25"] else 0
            features["preco_vs_ema50"] = ((close - features["ema50"]) / close) * 100 if features["ema50"] else 0
            features["preco_vs_ema100"] = ((close - features["ema100"]) / close) * 100 if features["ema100"] else 0
        else:
            features["preco_vs_ema25"] = 0
            features["preco_vs_ema50"] = 0
            features["preco_vs_ema100"] = 0

        return features

    async def _execute_signal(
        self, par: str, sinal: Dict[str, Any], features: Dict[str, Any]
    ) -> None:
        """Executa um sinal de trade via Trader."""
        if self._trader is None:
            logger.warning("[{}] Sinal {} ignorado — Trader nao disponivel",
                          par, sinal["sinal"])
            return

        if self._risk_manager is not None:
            try:
                pode_operar = self._risk_manager.pode_operar(par)
                if not pode_operar:
                    logger.info("[{}] RiskManager bloqueou operacao", par)
                    return
            except Exception as e:
                logger.warning("[{}] Erro ao consultar RiskManager: {}", par, e)

        try:
            logger.info("[{}] Executando sinal {} com confianca {:.2%}",
                       par, sinal["sinal"], sinal["confianca"])
            await asyncio.to_thread(
                self._trader.executar,
                par,
                sinal["sinal"],
                sinal["confianca"],
                features,
            )
        except Exception as e:
            logger.error("[{}] Erro ao executar trade: {}", par, e)

    async def _monitor_positions(self, par: str) -> None:
        """Verifica posicoes abertas e decide se deve sair antecipadamente."""
        if self._trader is None:
            return

        try:
            positions = self._client.get_open_positions()
            for pos in positions:
                pos_symbol = pos.get("symbol", "")
                pos_par = self._symbol_to_par(pos_symbol)
                if pos_par != par:
                    continue

                # Verificar se risk manager recomenda saida
                if self._risk_manager is not None:
                    try:
                        deve_sair = self._risk_manager.verificar_saida_antecipada(pos)
                        if deve_sair:
                            logger.info("[{}] Saida antecipada recomendada", par)
                            await asyncio.to_thread(self._client.close_position, par)
                    except Exception as e:
                        logger.warning("[{}] Erro ao verificar saida: {}", par, e)

        except Exception as e:
            logger.error("[{}] Erro ao monitorar posicoes: {}", par, e)

    def _save_features(self, par: str, features: Dict[str, Any]) -> None:
        """Salva features no banco. Se falhar, guarda na fila local."""
        try:
            # Filtrar apenas features que correspondem as colunas do banco
            db_features = {
                "ema9": features.get("ema9"),
                "ema25": features.get("ema25"),
                "ema50": features.get("ema50"),
                "ema100": features.get("ema100"),
                "rsi": features.get("rsi"),
                "atr": features.get("atr"),
                "vwap": features.get("vwap"),
                "cvd": features.get("cvd"),
                "ob_imbalance": features.get("ob_imbalance"),
                "taker_ratio": features.get("taker_ratio"),
                "vol_relativo": features.get("volume_relativo"),
                "regime": features.get("regime"),
                "fear_greed": features.get("fear_greed"),
                "sentimento_noticias": features.get("sentimento_noticias"),
                "funding_rate": features.get("funding_rate"),
                "open_interest": features.get("open_interest"),
            }
            insert_features(par, datetime.now(timezone.utc), **db_features)
        except Exception as e:
            logger.warning("[{}] Falha ao salvar features no banco: {}. Adicionando a fila.", par, e)
            self._db_queue.append({
                "par": par,
                "timestamp": datetime.now(timezone.utc),
                "features": features,
            })

    def _flush_db_queue(self) -> None:
        """Tenta salvar registros da fila local no banco."""
        if not self._db_queue:
            return

        saved = 0
        while self._db_queue:
            item = self._db_queue[0]
            try:
                insert_features(
                    item["par"],
                    item["timestamp"],
                    **{k: v for k, v in item["features"].items()
                       if k in ("ema9", "ema25", "ema50", "ema100", "rsi",
                                "atr", "vwap", "cvd", "ob_imbalance",
                                "taker_ratio", "vol_relativo", "regime",
                                "fear_greed", "sentimento_noticias",
                                "funding_rate", "open_interest")},
                )
                self._db_queue.popleft()
                saved += 1
            except Exception:
                break

        if saved:
            logger.info("Fila DB: {} registros sincronizados, {} restantes",
                       saved, len(self._db_queue))

    # ------------------------------------------------------------------
    # Retreino semanal
    # ------------------------------------------------------------------

    def _schedule_retrain(self) -> None:
        """Configura retreino semanal via schedule em thread separada."""
        if self._trainer is None:
            logger.info("ModelTrainer nao disponivel — retreino semanal desabilitado")
            return

        def _retrain_job():
            logger.info("Verificando necessidade de retreino...")
            try:
                retreinou = self._trainer.retreinar_se_necessario()
                if retreinou:
                    logger.info("Modelo retreinado com sucesso")
                else:
                    logger.info("Retreino nao necessario")
            except Exception as e:
                logger.error("Erro no retreino: {}", e)

        # Agendar para domingos as 03:00 UTC
        schedule.every().sunday.at("03:00").do(_retrain_job)

        def _schedule_loop():
            while self._running:
                schedule.run_pending()
                time.sleep(60)

        thread = threading.Thread(target=_schedule_loop, daemon=True, name="retrain-scheduler")
        thread.start()
        logger.info("Scheduler de retreino configurado (domingos 03:00 UTC)")

    # ------------------------------------------------------------------
    # News polling callback
    # ------------------------------------------------------------------

    def _on_news_update(self, payload: Dict[str, Any]) -> None:
        """Callback chamado pelo polling de noticias."""
        noticias = payload.get("noticias", [])
        fg = payload.get("fear_greed", {})
        logger.debug("News update: {} noticias, F&G={}",
                     len(noticias), fg.get("valor", "N/A"))

    # ------------------------------------------------------------------
    # WebSocket streams
    # ------------------------------------------------------------------

    async def _start_ws_streams(self) -> None:
        """Inicia todos os streams WebSocket como tasks paralelas."""
        for par in PARES:
            # Kline stream (candles)
            task = asyncio.create_task(
                self._client.start_kline_stream(par, self._on_kline, TIMEFRAME),
                name=f"ws-kline-{par}",
            )
            self._tasks.append(task)

            # Book ticker stream
            task = asyncio.create_task(
                self._client.start_book_ticker_stream(par, self._on_book_ticker),
                name=f"ws-book-{par}",
            )
            self._tasks.append(task)

        # Liquidation stream (global)
        task = asyncio.create_task(
            self._client.start_liquidation_stream(self._on_liquidation),
            name="ws-liquidations",
        )
        self._tasks.append(task)

        logger.info("{} streams WebSocket iniciados", len(self._tasks))

    # ------------------------------------------------------------------
    # News polling
    # ------------------------------------------------------------------

    async def _start_news_polling(self) -> None:
        """Inicia polling de noticias como task em background."""
        task = asyncio.create_task(
            self._news.start_news_polling(self._on_news_update, intervalo_segundos=300),
            name="news-polling",
        )
        self._tasks.append(task)
        logger.info("Polling de noticias iniciado")

    # ------------------------------------------------------------------
    # Flush periodico da fila DB
    # ------------------------------------------------------------------

    async def _db_flush_loop(self) -> None:
        """Loop que tenta sincronizar a fila local com o banco periodicamente."""
        while self._running:
            await asyncio.sleep(60)
            self._flush_db_queue()

    # ------------------------------------------------------------------
    # Graceful shutdown
    # ------------------------------------------------------------------

    async def _shutdown(self) -> None:
        """Encerramento gracioso: fecha WebSockets, posicoes e salva estado."""
        logger.info("Iniciando shutdown...")
        self._running = False

        # Parar streams WebSocket
        try:
            await self._client.stop_streams()
        except Exception as e:
            logger.error("Erro ao parar WebSockets: {}", e)

        # Parar news polling
        if self._news:
            self._news.stop_news_polling()

        # Cancelar tasks asyncio
        for task in self._tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # Fechar posicoes abertas (seguranca)
        if self._client:
            try:
                positions = self._client.get_open_positions()
                for pos in positions:
                    par_symbol = pos.get("symbol", "")
                    par = self._symbol_to_par(par_symbol)
                    if par in PARES:
                        logger.warning("Fechando posicao aberta em {} no shutdown", par)
                        self._client.close_position(par)
            except Exception as e:
                logger.error("Erro ao fechar posicoes no shutdown: {}", e)

        # Tentar salvar fila pendente no banco
        self._flush_db_queue()

        logger.info("Shutdown concluido")

    # ------------------------------------------------------------------
    # Utilitarios
    # ------------------------------------------------------------------

    @staticmethod
    def _symbol_to_par(symbol: str) -> str:
        """Converte symbol da Binance (BTCUSDT) para formato par (BTC/USDT)."""
        symbol = symbol.upper()
        for quote in ("USDT", "BUSD", "USDC", "BTC", "ETH"):
            if symbol.endswith(quote):
                base = symbol[: -len(quote)]
                return f"{base}/{quote}"
        return symbol

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Metodo principal que inicia o bot."""
        _print_banner()

        if not self._setup():
            logger.error("Falha na inicializacao. Encerrando.")
            sys.exit(1)

        self._running = True

        # Verificar se modelo precisa de treino inicial
        if self._model.retrain_if_needed():
            if self._trainer is not None:
                logger.info("Executando treino inicial do modelo...")
                try:
                    self._trainer.treinar_inicial()
                except Exception as e:
                    logger.warning("Treino inicial falhou: {}. Bot continuara com predicoes neutras.", e)
            else:
                logger.warning("Modelo nao treinado e ModelTrainer indisponivel. "
                             "Predicoes serao neutras (0.5).")

        # Iniciar scheduler de retreino
        self._schedule_retrain()

        # Iniciar WebSocket streams
        await self._start_ws_streams()

        # Iniciar news polling
        await self._start_news_polling()

        # Iniciar flush periodico da fila DB
        flush_task = asyncio.create_task(
            self._db_flush_loop(), name="db-flush"
        )
        self._tasks.append(flush_task)

        logger.info("Bot em execucao. Pressione Ctrl+C para encerrar.")

        # Manter o bot rodando enquanto as tasks estiverem ativas
        try:
            while self._running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass

        await self._shutdown()


# ---------------------------------------------------------------------------
# Signal handlers
# ---------------------------------------------------------------------------

_bot_instance: Optional[ScalpingBot] = None
_loop: Optional[asyncio.AbstractEventLoop] = None


def _handle_signal(signum, frame):
    """Handler para SIGINT e SIGTERM — dispara shutdown gracioso."""
    sig_name = signal.Signals(signum).name
    logger.info("Sinal {} recebido. Encerrando bot...", sig_name)

    if _bot_instance is not None:
        _bot_instance._running = False

    if _loop is not None and _loop.is_running():
        _loop.call_soon_threadsafe(_loop.stop)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Ponto de entrada do bot."""
    global _bot_instance, _loop

    # Registrar signal handlers
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    _bot_instance = ScalpingBot()
    _loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_loop)

    try:
        _loop.run_until_complete(_bot_instance.run())
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt recebido")
        _loop.run_until_complete(_bot_instance._shutdown())
    finally:
        _loop.close()
        logger.info("{} encerrado.", BOT_NAME)


if __name__ == "__main__":
    main()

"""
Configuracoes centrais do bot de scalping alavancado.
Carrega variaveis do .env e define constantes globais.
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from loguru import logger

# Carregar .env do diretorio raiz do projeto
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# ---------------------------------------------------------------------------
# Binance API
# ---------------------------------------------------------------------------
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")
BINANCE_TESTNET = os.getenv("BINANCE_TESTNET", "true").lower() == "true"

# ---------------------------------------------------------------------------
# Pares e timeframe
# ---------------------------------------------------------------------------
PARES = ["BTC/USDT", "ETH/USDT", "XRP/USDT"]
TIMEFRAME = "5m"

# Alavancagem por par (default 10x)
ALAVANCAGEM = {
    "BTC/USDT": 10,
    "ETH/USDT": 10,
    "XRP/USDT": 10,
}

# ---------------------------------------------------------------------------
# Gestao de risco
# ---------------------------------------------------------------------------
RISCO_POR_TRADE = 0.02        # 2% do capital por trade
TAXA_MAKER = 0.0002           # 0.02%
TAXA_TAKER = 0.0005           # 0.05%
RR_ALVO = 2.0                 # Risk/Reward 2:1
CONFIANCA_MINIMA = 0.65       # 65% de confianca minima do modelo
PERDA_MAXIMA_DIARIA = 0.06    # 6% de perda maxima diaria

# ---------------------------------------------------------------------------
# Modelo ML
# ---------------------------------------------------------------------------
JANELA_LABEL = 6              # Proximas 6 velas para rotular win/loss

# ---------------------------------------------------------------------------
# Database (TimescaleDB)
# ---------------------------------------------------------------------------
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "showmethemoney")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")

DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# ---------------------------------------------------------------------------
# APIs externas
# ---------------------------------------------------------------------------
CRYPTOPANIC_API_KEY = os.getenv("CRYPTOPANIC_API_KEY", "")
WHALE_ALERT_API_KEY = os.getenv("WHALE_ALERT_API_KEY", "")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
DATA_DIR = BASE_DIR / "data"
HISTORICAL_DIR = DATA_DIR / "historical"
MODELS_DIR = BASE_DIR / "models"
LOGS_DIR = BASE_DIR / "logs"

# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------
WS_RECONNECT_DELAY = 5        # Segundos entre tentativas de reconexao
WS_RECONNECT_MAX_RETRIES = 10 # Maximo de tentativas antes de desistir
WS_PING_INTERVAL = 20         # Intervalo de ping em segundos
WS_PING_TIMEOUT = 10          # Timeout do pong em segundos

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logger.remove()  # Remove handler padrao
logger.add(
    sys.stderr,
    level="INFO",
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>",
)
logger.add(
    LOGS_DIR / "bot_{time:YYYY-MM-DD}.log",
    rotation="1 day",
    retention="30 days",
    level="DEBUG",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function} - {message}",
)

# ---------------------------------------------------------------------------
# Validacao de variaveis obrigatorias
# ---------------------------------------------------------------------------
_REQUIRED_VARS = {
    "BINANCE_API_KEY": BINANCE_API_KEY,
    "BINANCE_API_SECRET": BINANCE_API_SECRET,
    "DB_PASSWORD": DB_PASSWORD,
}


def validar_config():
    """Verifica se todas as variaveis obrigatorias estao definidas."""
    faltando = [nome for nome, valor in _REQUIRED_VARS.items() if not valor]
    if faltando:
        logger.warning(
            f"Variaveis de ambiente obrigatorias nao definidas: {', '.join(faltando)}. "
            "Copie .env.example para .env e preencha os valores."
        )
        return False
    logger.info("Configuracao validada com sucesso.")
    return True

"""
Dashboard Streamlit para monitoramento em tempo real do bot de scalping.
Executa com: streamlit run dashboard/app.py
"""

import sys
import time
from datetime import datetime, timedelta, timezone, date
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ---------------------------------------------------------------------------
# Paths e imports do projeto
# ---------------------------------------------------------------------------
PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

try:
    from config import (
        PARES, ALAVANCAGEM, RISCO_POR_TRADE, CONFIANCA_MINIMA,
        LOGS_DIR, MODELS_DIR,
    )
except ImportError:
    PARES = ["BTC/USDT", "ETH/USDT", "XRP/USDT"]
    ALAVANCAGEM = {"BTC/USDT": 10, "ETH/USDT": 10, "XRP/USDT": 10}
    RISCO_POR_TRADE = 0.02
    CONFIANCA_MINIMA = 0.65
    LOGS_DIR = PROJECT_DIR / "logs"
    MODELS_DIR = PROJECT_DIR / "models"

# ---------------------------------------------------------------------------
# Cores do tema
# ---------------------------------------------------------------------------
COR_VERDE = "#00ff88"
COR_VERMELHO = "#ff4444"
COR_AZUL = "#4488ff"
COR_LARANJA = "#ff8800"
COR_FUNDO = "#0e1117"
COR_CARD = "#1a1d23"

# ---------------------------------------------------------------------------
# Conexao com banco (fallback para dados mock)
# ---------------------------------------------------------------------------
DB_AVAILABLE = False

try:
    from database import (
        get_connection,
        get_trades_recentes,
        get_performance_diaria,
    )
    conn = get_connection()
    conn.close()
    DB_AVAILABLE = True
except Exception:
    DB_AVAILABLE = False


# =========================================================================
# GERADORES DE DADOS MOCK
# =========================================================================

def _mock_candles(par: str, n: int = 100) -> pd.DataFrame:
    """Gera candles mock realistas para demonstracao."""
    np.random.seed(hash(par) % 2**31)
    base_prices = {"BTC/USDT": 67500.0, "ETH/USDT": 3450.0, "XRP/USDT": 0.62}
    base = base_prices.get(par, 1000.0)

    now = datetime.now(timezone.utc)
    timestamps = [now - timedelta(minutes=5 * (n - i)) for i in range(n)]
    closes = [base]
    for _ in range(n - 1):
        change = np.random.normal(0, 0.002) * base
        closes.append(closes[-1] + change)

    rows = []
    for i, ts in enumerate(timestamps):
        c = closes[i]
        h = c * (1 + abs(np.random.normal(0, 0.001)))
        l = c * (1 - abs(np.random.normal(0, 0.001)))
        o = l + (h - l) * np.random.random()
        vol = np.random.uniform(50, 500)
        rows.append({
            "timestamp": ts, "open": o, "high": h, "low": l,
            "close": c, "volume": vol,
        })
    return pd.DataFrame(rows)


def _mock_emas(df: pd.DataFrame) -> pd.DataFrame:
    """Calcula EMAs a partir dos candles."""
    df = df.copy()
    df["ema25"] = df["close"].ewm(span=25, adjust=False).mean()
    df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()
    df["ema100"] = df["close"].ewm(span=100, adjust=False).mean()
    return df


def _mock_trades(n: int = 20) -> pd.DataFrame:
    """Gera trades mock."""
    np.random.seed(42)
    pares = np.random.choice(PARES, n)
    direcoes = np.random.choice(["LONG", "SHORT"], n)
    resultados = np.random.choice(["WIN", "LOSS"], n, p=[0.58, 0.42])
    entradas = []
    for p in pares:
        base = {"BTC/USDT": 67500, "ETH/USDT": 3450, "XRP/USDT": 0.62}.get(p, 100)
        entradas.append(base * (1 + np.random.uniform(-0.01, 0.01)))
    entradas = np.array(entradas)
    lucros = np.where(
        resultados == "WIN",
        np.random.uniform(5, 80, n),
        -np.random.uniform(5, 40, n),
    )
    now = datetime.now(timezone.utc)
    timestamps = [now - timedelta(minutes=np.random.randint(5, 1440)) for _ in range(n)]

    saidas = []
    sls = []
    tps = []
    for i in range(n):
        e = entradas[i]
        d = direcoes[i]
        mult = 1 if d == "LONG" else -1
        sl = e - mult * e * 0.005
        tp = e + mult * e * 0.01
        saida = tp if resultados[i] == "WIN" else sl
        saidas.append(saida)
        sls.append(sl)
        tps.append(tp)

    return pd.DataFrame({
        "par": pares, "direcao": direcoes, "preco_entrada": entradas,
        "preco_saida": saidas, "sl": sls, "tp": tps,
        "resultado": resultados, "lucro_usd": lucros,
        "timestamp_entrada": timestamps,
    })


def _mock_performance_hoje() -> dict:
    """Retorna metricas de performance do dia."""
    np.random.seed(int(datetime.now().strftime("%Y%m%d")))
    wins = np.random.randint(3, 12)
    losses = np.random.randint(1, 6)
    total = wins + losses
    lucro = np.random.uniform(50, 350)
    return {
        "total_trades": total,
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / total * 100, 1),
        "lucro_total": round(lucro, 2),
        "lucro_pct": round(lucro / 10000 * 100, 2),
    }


def _mock_market_info() -> dict:
    """Retorna info de mercado mock."""
    np.random.seed(int(time.time()) // 30)
    regimes = ["TREND_UP", "TREND_DOWN", "LATERAL"]
    return {
        "fear_greed": np.random.randint(15, 85),
        "funding_rate": {
            "BTC/USDT": round(np.random.uniform(-0.01, 0.03), 4),
            "ETH/USDT": round(np.random.uniform(-0.01, 0.03), 4),
            "XRP/USDT": round(np.random.uniform(-0.01, 0.03), 4),
        },
        "open_interest_change": {
            "BTC/USDT": round(np.random.uniform(-5, 8), 2),
            "ETH/USDT": round(np.random.uniform(-5, 8), 2),
            "XRP/USDT": round(np.random.uniform(-5, 8), 2),
        },
        "regime": np.random.choice(regimes),
    }


def _mock_noticias() -> list[dict]:
    """Retorna noticias mock."""
    titulos = [
        ("Bitcoin supera resistencia de $68k com volume crescente", 0.7),
        ("SEC adia decisao sobre ETF de Ethereum", -0.3),
        ("Ripple fecha parceria com banco asiatico", 0.5),
        ("Mercado cripto mostra sinais de recuperacao", 0.4),
        ("Reguladores europeus discutem novas regras para stablecoins", -0.2),
    ]
    noticias = []
    for titulo, score in titulos:
        noticias.append({"titulo": titulo, "sentimento_score": score})
    return noticias


def _mock_model_info() -> dict:
    """Retorna info do modelo mock."""
    features = {
        "rsi": 850.5, "ob_imbalance": 720.3, "cvd": 680.1,
        "volume_relativo": 620.8, "atr": 580.2, "ema25": 540.6,
        "funding_rate": 490.3, "taker_ratio": 450.7, "vwap": 410.1,
        "sentimento_noticias": 380.5, "ema50": 350.2, "fear_greed": 320.8,
    }
    return {
        "acuracia": 72.4,
        "train_date": (datetime.now(timezone.utc) - timedelta(days=2)).strftime(
            "%Y-%m-%d %H:%M"
        ),
        "feature_importance": features,
        "confianca_atual": round(np.random.uniform(0.55, 0.85), 2),
    }


def _mock_equity_curve(n: int = 60) -> pd.DataFrame:
    """Gera curva de equity mock."""
    np.random.seed(123)
    capital = 10000.0
    valores = [capital]
    for _ in range(n - 1):
        ret = np.random.normal(0.002, 0.01)
        capital *= (1 + ret)
        valores.append(capital)
    dias = [datetime.now(timezone.utc) - timedelta(days=n - i) for i in range(n)]
    return pd.DataFrame({"data": dias, "equity": valores})


def _mock_sinais(df: pd.DataFrame) -> list[dict]:
    """Gera sinais de entrada mock para o grafico."""
    np.random.seed(99)
    sinais = []
    indices = np.random.choice(range(20, len(df)), size=5, replace=False)
    for idx in indices:
        row = df.iloc[idx]
        direcao = np.random.choice(["LONG", "SHORT"])
        sinais.append({
            "timestamp": row["timestamp"],
            "preco": row["close"],
            "direcao": direcao,
        })
    return sinais


def _mock_posicao_aberta() -> dict | None:
    """Retorna posicao aberta mock (ou None)."""
    np.random.seed(int(time.time()) // 60)
    if np.random.random() < 0.6:
        par = np.random.choice(PARES)
        base = {"BTC/USDT": 67500, "ETH/USDT": 3450, "XRP/USDT": 0.62}[par]
        direcao = np.random.choice(["LONG", "SHORT"])
        entrada = base * (1 + np.random.uniform(-0.005, 0.005))
        mult = 1 if direcao == "LONG" else -1
        preco_atual = entrada + mult * entrada * np.random.uniform(-0.003, 0.006)
        pnl = (preco_atual - entrada) / entrada * 100 * mult * 10
        return {
            "par": par,
            "direcao": direcao,
            "entrada": round(entrada, 2),
            "preco_atual": round(preco_atual, 2),
            "sl": round(entrada - mult * entrada * 0.005, 2),
            "tp": round(entrada + mult * entrada * 0.01, 2),
            "pnl_usd": round(pnl, 2),
            "pnl_pct": round(pnl / 100, 2),
        }
    return None


# =========================================================================
# FUNCOES DE DADOS (DB ou MOCK)
# =========================================================================

def get_candles(par: str) -> pd.DataFrame:
    if DB_AVAILABLE:
        try:
            from database import get_connection
            conn = get_connection()
            query = """
                SELECT timestamp, open, high, low, close, volume
                FROM candles
                WHERE par = %s AND timeframe = '5m'
                ORDER BY timestamp DESC LIMIT 100;
            """
            df = pd.read_sql(query, conn, params=(par,))
            conn.close()
            if not df.empty:
                return df.sort_values("timestamp").reset_index(drop=True)
        except Exception:
            pass
    return _mock_candles(par)


def get_trades() -> pd.DataFrame:
    if DB_AVAILABLE:
        try:
            trades = get_trades_recentes(20)
            if trades:
                return pd.DataFrame(trades)
        except Exception:
            pass
    return _mock_trades(20)


def get_performance() -> dict:
    if DB_AVAILABLE:
        try:
            perf = get_performance_diaria(
                data_inicio=date.today(), data_fim=date.today()
            )
            if perf:
                return perf[0]
        except Exception:
            pass
    return _mock_performance_hoje()


def get_precos_atuais() -> dict:
    """Retorna precos atuais dos pares."""
    precos = {}
    for par in PARES:
        df = get_candles(par)
        if not df.empty:
            ultimo = df.iloc[-1]["close"]
            primeiro = df.iloc[0]["close"]
            var = (ultimo - primeiro) / primeiro * 100
            precos[par] = {"preco": round(ultimo, 4), "variacao": round(var, 2)}
    return precos


def read_bot_log(n_lines: int = 20) -> str:
    """Le as ultimas linhas do log do bot."""
    log_dir = LOGS_DIR
    if log_dir.exists():
        logs = sorted(log_dir.glob("bot_*.log"), reverse=True)
        if logs:
            try:
                lines = logs[0].read_text().strip().split("\n")
                return "\n".join(lines[-n_lines:])
            except Exception:
                pass
    return "Nenhum log disponivel. Bot ainda nao foi iniciado."


# =========================================================================
# CONFIGURACAO DA PAGINA
# =========================================================================

st.set_page_config(
    layout="wide",
    page_title="Show Me The Money",
    page_icon="$",
    initial_sidebar_state="expanded",
)

# CSS customizado para tema escuro
st.markdown("""
<style>
    .stApp {
        background-color: #0e1117;
    }
    .metric-card {
        background-color: #1a1d23;
        border-radius: 10px;
        padding: 20px;
        border: 1px solid #2d3139;
    }
    .status-running {
        color: #00ff88;
        font-weight: bold;
        font-size: 1.1em;
    }
    .status-stopped {
        color: #ff4444;
        font-weight: bold;
        font-size: 1.1em;
    }
    .status-waiting {
        color: #ffcc00;
        font-weight: bold;
        font-size: 1.1em;
    }
    div[data-testid="stMetric"] {
        background-color: #1a1d23;
        border: 1px solid #2d3139;
        border-radius: 10px;
        padding: 15px;
    }
    .win-text { color: #00ff88; }
    .loss-text { color: #ff4444; }
</style>
""", unsafe_allow_html=True)


# =========================================================================
# SIDEBAR
# =========================================================================

with st.sidebar:
    st.title("$ Show Me The Money")
    st.divider()

    par_ativo = st.selectbox("Par Ativo", PARES, index=0)

    st.divider()
    st.subheader("Controles do Bot")
    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        if st.button("Iniciar Bot", use_container_width=True, type="primary"):
            st.session_state["bot_status"] = "RODANDO"
    with col_btn2:
        if st.button("Parar Bot", use_container_width=True):
            st.session_state["bot_status"] = "PARADO"

    if "bot_status" not in st.session_state:
        st.session_state["bot_status"] = "AGUARDANDO SINAL"

    st.divider()
    st.subheader("Configuracoes")
    alav = st.slider(
        "Alavancagem",
        min_value=1, max_value=50,
        value=ALAVANCAGEM.get(par_ativo, 10),
    )
    risco = st.slider(
        "Risco por trade (%)",
        min_value=0.5, max_value=10.0,
        value=RISCO_POR_TRADE * 100, step=0.5,
    )
    threshold = st.slider(
        "Confianca minima (%)",
        min_value=50, max_value=95,
        value=int(CONFIANCA_MINIMA * 100),
    )

    st.divider()
    st.subheader("Log do Bot")
    log_text = read_bot_log(20)
    st.code(log_text, language="log")

    st.divider()
    st.caption("Auto-refresh: 5s")
    if not DB_AVAILABLE:
        st.warning("Banco indisponivel. Usando dados mock.")


# =========================================================================
# SECAO 1 — HEADER
# =========================================================================

header_col1, header_col2 = st.columns([1, 3])

with header_col1:
    status = st.session_state.get("bot_status", "AGUARDANDO SINAL")
    status_icons = {
        "RODANDO": ("RODANDO", "status-running"),
        "PARADO": ("PARADO", "status-stopped"),
        "AGUARDANDO SINAL": ("AGUARDANDO SINAL", "status-waiting"),
    }
    icon_label, css_class = status_icons.get(status, ("PARADO", "status-stopped"))
    st.markdown(f'<p class="{css_class}">Bot: {icon_label}</p>', unsafe_allow_html=True)

    saldo_mock = round(np.random.RandomState(42).uniform(9500, 11000), 2)
    capital_pos = round(saldo_mock * 0.15, 2)
    st.metric("Saldo Disponivel", f"${saldo_mock:,.2f}")
    st.metric("Capital em Posicoes", f"${capital_pos:,.2f}")

with header_col2:
    precos = get_precos_atuais()
    price_cols = st.columns(len(PARES))
    for i, par in enumerate(PARES):
        with price_cols[i]:
            info = precos.get(par, {"preco": 0, "variacao": 0})
            simbolo = par.split("/")[0]
            delta_color = "normal"
            st.metric(
                label=simbolo,
                value=f"${info['preco']:,.4f}" if info["preco"] < 10
                    else f"${info['preco']:,.2f}",
                delta=f"{info['variacao']:+.2f}%",
                delta_color=delta_color,
            )


# =========================================================================
# SECAO 2 — GRAFICO PRINCIPAL (CANDLESTICK)
# =========================================================================

st.subheader(f"Grafico {par_ativo} - 5min")

df_candles = get_candles(par_ativo)
df_candles = _mock_emas(df_candles)
sinais = _mock_sinais(df_candles)
posicao = _mock_posicao_aberta()

fig = go.Figure()

# Candlestick
fig.add_trace(go.Candlestick(
    x=df_candles["timestamp"],
    open=df_candles["open"],
    high=df_candles["high"],
    low=df_candles["low"],
    close=df_candles["close"],
    name="OHLC",
    increasing_line_color=COR_VERDE,
    decreasing_line_color=COR_VERMELHO,
))

# EMAs
fig.add_trace(go.Scatter(
    x=df_candles["timestamp"], y=df_candles["ema25"],
    name="EMA 25", line=dict(color=COR_AZUL, width=1.5),
    mode="lines",
))
fig.add_trace(go.Scatter(
    x=df_candles["timestamp"], y=df_candles["ema50"],
    name="EMA 50", line=dict(color=COR_LARANJA, width=1.5),
    mode="lines",
))
fig.add_trace(go.Scatter(
    x=df_candles["timestamp"], y=df_candles["ema100"],
    name="EMA 100", line=dict(color=COR_VERMELHO, width=1.5),
    mode="lines",
))

# Sinais de entrada
for sinal in sinais:
    marker_symbol = "triangle-up" if sinal["direcao"] == "LONG" else "triangle-down"
    marker_color = COR_VERDE if sinal["direcao"] == "LONG" else COR_VERMELHO
    fig.add_trace(go.Scatter(
        x=[sinal["timestamp"]],
        y=[sinal["preco"]],
        mode="markers",
        marker=dict(symbol=marker_symbol, size=14, color=marker_color),
        name=sinal["direcao"],
        showlegend=False,
    ))

# Posicao aberta — linhas horizontais
if posicao and posicao["par"] == par_ativo:
    fig.add_hline(
        y=posicao["entrada"], line_dash="dash", line_color="white",
        annotation_text=f"Entrada: {posicao['entrada']}",
    )
    fig.add_hline(
        y=posicao["tp"], line_dash="dash", line_color=COR_VERDE,
        annotation_text=f"TP: {posicao['tp']}",
    )
    fig.add_hline(
        y=posicao["sl"], line_dash="dash", line_color=COR_VERMELHO,
        annotation_text=f"SL: {posicao['sl']}",
    )

fig.update_layout(
    template="plotly_dark",
    paper_bgcolor=COR_FUNDO,
    plot_bgcolor="#141720",
    xaxis_rangeslider_visible=False,
    height=520,
    margin=dict(l=10, r=10, t=30, b=10),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    xaxis=dict(gridcolor="#1e2230"),
    yaxis=dict(gridcolor="#1e2230"),
)

st.plotly_chart(fig, use_container_width=True)


# =========================================================================
# SECAO 3 — CARDS DE METRICAS
# =========================================================================

perf = get_performance()
model_info = _mock_model_info()

mc1, mc2, mc3, mc4 = st.columns(4)

with mc1:
    st.metric(
        "Trades Hoje",
        f"{perf['total_trades']}",
        delta=f"WR {perf['win_rate']}%",
    )
with mc2:
    st.metric(
        "Lucro do Dia",
        f"${perf['lucro_total']:,.2f}",
        delta=f"{perf['lucro_pct']:+.2f}%",
    )
with mc3:
    if posicao:
        pnl_color = COR_VERDE if posicao["pnl_usd"] >= 0 else COR_VERMELHO
        st.metric(
            f"Posicao: {posicao['par']} {posicao['direcao']}",
            f"${posicao['pnl_usd']:+.2f}",
            delta=f"{posicao['pnl_pct']:+.2f}%",
        )
    else:
        st.metric("Posicao Aberta", "Nenhuma", delta="--")
with mc4:
    conf = model_info["confianca_atual"]
    st.metric(
        "Confianca do Modelo",
        f"{conf:.0%}",
        delta="Ativo" if conf >= CONFIANCA_MINIMA else "Abaixo do limiar",
    )


# =========================================================================
# SECAO 4 — LINHA INFERIOR (3 COLUNAS)
# =========================================================================

col_trades, col_market, col_model = st.columns(3)

# ---- Coluna 1: Historico de Trades ----
with col_trades:
    st.subheader("Historico de Trades")
    df_trades = get_trades()
    if not df_trades.empty:
        display_df = df_trades[[
            "par", "direcao", "preco_entrada", "preco_saida",
            "sl", "tp", "resultado", "lucro_usd",
        ]].copy()
        display_df.columns = [
            "Par", "Dir", "Entrada", "Saida", "SL", "TP", "Resultado", "Lucro",
        ]
        display_df["Entrada"] = display_df["Entrada"].apply(lambda x: f"{x:.4f}" if x < 10 else f"{x:.2f}")
        display_df["Saida"] = display_df["Saida"].apply(lambda x: f"{x:.4f}" if x < 10 else f"{x:.2f}")
        display_df["SL"] = display_df["SL"].apply(lambda x: f"{x:.4f}" if x < 10 else f"{x:.2f}")
        display_df["TP"] = display_df["TP"].apply(lambda x: f"{x:.4f}" if x < 10 else f"{x:.2f}")
        display_df["Resultado"] = display_df["Resultado"].apply(
            lambda x: "WIN" if x == "WIN" else "LOSS"
        )
        display_df["Lucro"] = display_df["Lucro"].apply(lambda x: f"${x:+.2f}")

        def _color_resultado(val):
            if val == "WIN":
                return f"color: {COR_VERDE}"
            return f"color: {COR_VERMELHO}"

        styled = display_df.style.applymap(
            _color_resultado, subset=["Resultado"]
        )
        st.dataframe(styled, use_container_width=True, height=400)
    else:
        st.info("Nenhum trade registrado.")


# ---- Coluna 2: Informacoes de Mercado ----
with col_market:
    st.subheader("Mercado")
    market = _mock_market_info()

    # Fear & Greed Gauge
    fg_value = market["fear_greed"]
    fig_gauge = go.Figure(go.Indicator(
        mode="gauge+number",
        value=fg_value,
        title={"text": "Fear & Greed Index"},
        gauge={
            "axis": {"range": [0, 100], "tickcolor": "white"},
            "bar": {"color": COR_AZUL},
            "steps": [
                {"range": [0, 25], "color": COR_VERMELHO},
                {"range": [25, 45], "color": COR_LARANJA},
                {"range": [45, 55], "color": "#888888"},
                {"range": [55, 75], "color": "#66bb6a"},
                {"range": [75, 100], "color": COR_VERDE},
            ],
            "threshold": {
                "line": {"color": "white", "width": 2},
                "thickness": 0.8,
                "value": fg_value,
            },
        },
    ))
    fig_gauge.update_layout(
        template="plotly_dark",
        paper_bgcolor=COR_FUNDO,
        height=220,
        margin=dict(l=20, r=20, t=50, b=10),
    )
    st.plotly_chart(fig_gauge, use_container_width=True)

    # Funding Rate
    st.markdown("**Funding Rate**")
    for par_fr, fr_val in market["funding_rate"].items():
        simbolo = par_fr.split("/")[0]
        cor = COR_VERDE if fr_val >= 0 else COR_VERMELHO
        st.markdown(
            f"<span style='color:{cor}'>{simbolo}: {fr_val:+.4f}%</span>",
            unsafe_allow_html=True,
        )

    # Open Interest
    st.markdown("**Open Interest (var %)**")
    for par_oi, oi_val in market["open_interest_change"].items():
        simbolo = par_oi.split("/")[0]
        cor = COR_VERDE if oi_val >= 0 else COR_VERMELHO
        st.markdown(
            f"<span style='color:{cor}'>{simbolo}: {oi_val:+.2f}%</span>",
            unsafe_allow_html=True,
        )

    # Regime
    regime = market["regime"]
    regime_cores = {
        "TREND_UP": COR_VERDE, "TREND_DOWN": COR_VERMELHO, "LATERAL": "#888888",
    }
    st.markdown(
        f"**Regime:** <span style='color:{regime_cores.get(regime, '#fff')}'>"
        f"{regime}</span>",
        unsafe_allow_html=True,
    )

    # Noticias
    st.markdown("**Ultimas Noticias**")
    noticias = _mock_noticias()
    for noticia in noticias:
        score = noticia["sentimento_score"]
        if score > 0.2:
            indicador = f"<span style='color:{COR_VERDE}'>[+]</span>"
        elif score < -0.2:
            indicador = f"<span style='color:{COR_VERMELHO}'>[-]</span>"
        else:
            indicador = "<span style='color:#888888'>[~]</span>"
        st.markdown(
            f"{indicador} {noticia['titulo']}",
            unsafe_allow_html=True,
        )


# ---- Coluna 3: Modelo ML ----
with col_model:
    st.subheader("Modelo ML")

    st.metric("Acuracia Historica", f"{model_info['acuracia']}%")
    st.metric("Ultimo Retreino", model_info["train_date"])

    # Feature Importance (top 10)
    feat_imp = model_info["feature_importance"]
    top_features = dict(list(feat_imp.items())[:10])
    feat_names = list(reversed(top_features.keys()))
    feat_values = list(reversed(top_features.values()))

    fig_feat = go.Figure(go.Bar(
        x=feat_values,
        y=feat_names,
        orientation="h",
        marker_color=COR_AZUL,
    ))
    fig_feat.update_layout(
        title="Top 10 Features (Importancia)",
        template="plotly_dark",
        paper_bgcolor=COR_FUNDO,
        plot_bgcolor="#141720",
        height=320,
        margin=dict(l=10, r=10, t=40, b=10),
        xaxis=dict(gridcolor="#1e2230"),
        yaxis=dict(gridcolor="#1e2230"),
    )
    st.plotly_chart(fig_feat, use_container_width=True)

    # Curva de Equity
    df_equity = _mock_equity_curve()
    fig_equity = go.Figure(go.Scatter(
        x=df_equity["data"],
        y=df_equity["equity"],
        mode="lines",
        fill="tozeroy",
        line=dict(color=COR_VERDE, width=2),
        fillcolor="rgba(0,255,136,0.1)",
    ))
    fig_equity.update_layout(
        title="Curva de Equity",
        template="plotly_dark",
        paper_bgcolor=COR_FUNDO,
        plot_bgcolor="#141720",
        height=250,
        margin=dict(l=10, r=10, t=40, b=10),
        xaxis=dict(gridcolor="#1e2230"),
        yaxis=dict(gridcolor="#1e2230", tickprefix="$"),
    )
    st.plotly_chart(fig_equity, use_container_width=True)


# =========================================================================
# AUTO-REFRESH (5 segundos)
# =========================================================================

time.sleep(5)
st.rerun()

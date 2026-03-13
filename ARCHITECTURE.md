# Arquitetura — Show Me The Money

## Visão Geral do Fluxo

```
Binance API/WebSocket
        ↓
  binance_client.py       ← dados de mercado em tempo real
        ↓
  data_collector.py       ← monta snapshot de features
        ↓
  indicators.py           ← calcula EMA/RSI/ATR/VWAP/CVD/Regime
        ↓
  news_collector.py       ← Fear&Greed + notícias + sentimento
        ↓
  signal_generator.py     ← 9 verificações + consulta ao modelo
        ↓
  model.py                ← LightGBM → probabilidade de WIN
        ↓
  risk_manager.py         ← calcula SL / TP / tamanho de posição
        ↓
  trader.py               ← executa ordens na Binance
        ↓
  database.py             ← salva tudo no TimescaleDB
        ↓
  dashboard/app.py        ← exibe tudo em tempo real
```

---

## Arquivos e responsabilidades

### Raiz do projeto

| Arquivo | O que faz |
|---|---|
| `main.py` | Ponto de entrada. Inicializa todos os módulos, sobe WebSockets, roda o loop principal |
| `config.py` | Todas as configurações (pares, alavancagem, risco, taxas, thresholds). **Mexa aqui para ajustar parâmetros** |
| `database.py` | Conexão com TimescaleDB. Criação de tabelas e métodos de leitura/escrita |
| `requirements.txt` | Dependências Python |
| `Makefile` | Atalhos de comando (make run-bot, make run-dashboard, etc.) |
| `.env` | Credenciais (API keys, banco). **Nunca commitar este arquivo** |

---

### core/ — Módulos principais

| Arquivo | O que faz | Quando mexer |
|---|---|---|
| `binance_client.py` | Toda comunicação com a Binance (REST + WebSocket). Ordens, saldos, candles, order book | Alterar tipo de ordem, adicionar novos streams |
| `indicators.py` | Calcula todos os indicadores técnicos (EMA, RSI, ATR, VWAP, CVD, regime) | Adicionar/remover indicadores |
| `data_collector.py` | Baixa histórico e monta o snapshot de features para o modelo | Adicionar novas fontes de dados |
| `news_collector.py` | Busca notícias (CryptoPanic), Fear & Greed (alternative.me), Whale Alert e analisa sentimento (FinBERT) | Trocar fonte de notícias, ajustar sentimento |
| `model.py` | Treina e serve o modelo LightGBM. 24 features. Versionamento automático | Ajustar hiperparâmetros, adicionar features |
| `signal_generator.py` | Combina técnico + modelo ML para decidir LONG/SHORT/NEUTRO. 9 verificações | Ajustar regras de entrada, thresholds |
| `risk_manager.py` | Calcula tamanho de posição, SL via EMA100, TP com 2:1 líquido de taxas, circuit breaker | Ajustar % de risco, RR alvo, perda máxima diária |
| `trader.py` | Executa ordens: LIMIT entrada, LIMIT TP, MARKET SL. Monitora saída antecipada | Mudar lógica de execução ou timing |
| `trainer.py` | Gerencia treino inicial e retreino semanal do modelo | Ajustar frequência de retreino |

---

### dashboard/

| Arquivo | O que faz |
|---|---|
| `app.py` | Dashboard Streamlit completo. Candlestick + EMAs, posições, métricas, notícias, modelo. Roda com `make run-dashboard` |

---

### scripts/

| Arquivo | Uso |
|---|---|
| `download_history.py` | Baixa anos de dados históricos da Binance. Rodar uma vez antes do primeiro treino |
| `train_model.py` | Treina o modelo com dados históricos. Rodar depois do download |

---

## Banco de Dados (TimescaleDB)

| Tabela | O que armazena |
|---|---|
| `candles` | OHLCV de todos os pares e timeframes |
| `order_book_snapshots` | Imbalance do livro de ordens por timestamp |
| `funding_rate` | Taxa de funding e open interest |
| `features` | Snapshot completo de todas as features no momento de cada sinal (usado para retreino) |
| `trades` | Histórico completo de operações (entrada, saída, SL, TP, resultado, taxas) |
| `performance_diaria` | Win rate, lucro, drawdown por dia |
| `noticias` | Notícias com score de sentimento |
| `model_versions` | Versões do modelo com métricas de acurácia |

---

## Parâmetros importantes (config.py)

| Parâmetro | Default | O que controla |
|---|---|---|
| `RISCO_POR_TRADE` | 2% | % do capital arriscado por operação |
| `PERDA_MAXIMA_DIARIA` | 6% | Circuit breaker — para o bot ao atingir |
| `RR_ALVO` | 2.0 | Risk/Reward alvo (2:1 líquido de taxas) |
| `CONFIANCA_MINIMA` | 65% | Threshold mínimo do modelo para operar |
| `ALAVANCAGEM` | 10x | Alavancagem padrão por par |
| `JANELA_LABEL` | 6 velas | Quantas velas olha à frente para rotular WIN/LOSS |
| `TAXA_MAKER` | 0.02% | Taxa de ordem LIMIT |
| `TAXA_TAKER` | 0.05% | Taxa de ordem MARKET |

---

## Como rodar

```bash
# Primeiro uso
cp .env.example .env        # preencher credenciais
make install                # instalar dependências
make download-history       # baixar 3 anos de dados (~20 min)
make train                  # treinar modelo

# Dia a dia
make run-testnet            # rodar no testnet (sem dinheiro real)
make run-dashboard          # abrir dashboard em localhost:8501
make run-prod               # rodar em produção (com dinheiro real)
```

---

## Variáveis de ambiente (.env)

| Variável | Obrigatória | Descrição |
|---|---|---|
| `BINANCE_API_KEY` | Sim | API Key da Binance |
| `BINANCE_API_SECRET` | Sim | Secret da Binance |
| `BINANCE_TESTNET` | Não | `true` para testnet, `false` para produção |
| `DB_HOST` | Sim | Host do TimescaleDB |
| `DB_PORT` | Não | Porta (default: 5432) |
| `DB_NAME` | Sim | Nome do banco |
| `DB_USER` | Sim | Usuário do banco |
| `DB_PASSWORD` | Sim | Senha do banco |
| `CRYPTOPANIC_API_KEY` | Não | Notícias (funciona sem, usa mock) |
| `WHALE_ALERT_API_KEY` | Não | Alertas de baleias (funciona sem, usa mock) |

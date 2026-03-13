# Show Me The Money 🤖

Bot de scalping alavancado na Binance com ML especialista.

## Pares
BTC/USDT · ETH/USDT · XRP/USDT — Futures

## Estratégia
- Timeframe: 5 minutos
- Indicadores: EMA 25/50/100 + RSI + ATR + VWAP + CVD + Order Book
- Modelo: LightGBM treinado com histórico completo (do dia zero)
- Retorno alvo: 2:1 líquido de taxas
- Entrada: LIMIT | Stop Loss: MARKET | Take Profit: LIMIT

## Stack
- Python · ccxt · pandas-ta · LightGBM · TimescaleDB · Streamlit

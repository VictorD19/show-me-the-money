import axios from 'axios'

const API_BASE = 'http://localhost:8000/api'

export const api = {
  getBalance: () => axios.get(`${API_BASE}/balance`),
  getPrices: () => axios.get(`${API_BASE}/prices`),
  getCandles: (symbol, limit = 100) => axios.get(`${API_BASE}/candles/${symbol}?limit=${limit}`),
  getIndicators: (symbol) => axios.get(`${API_BASE}/indicators/${symbol}`),
  getTrades: (limit = 20) => axios.get(`${API_BASE}/trades?limit=${limit}`),
  getPerformance: () => axios.get(`${API_BASE}/performance`),
  getModelInfo: () => axios.get(`${API_BASE}/model/info`),
  getNews: () => axios.get(`${API_BASE}/news`),
  getFearGreed: () => axios.get(`${API_BASE}/fear_greed`),
  getOpenPositions: () => axios.get(`${API_BASE}/open_positions`),
  startBot: () => axios.post(`${API_BASE}/bot/start`),
  stopBot: () => axios.post(`${API_BASE}/bot/stop`),
}

export const WS_URL = 'ws://localhost:8000/ws'

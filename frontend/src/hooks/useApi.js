import { useState, useEffect, useCallback } from 'react'
import { api } from '../api/client'

export default function useApi(interval = 5000) {
  const [data, setData] = useState({
    balance: null,
    prices: null,
    trades: [],
    performance: null,
    modelInfo: null,
    news: [],
    fearGreed: null,
    openPositions: [],
  })
  const [loading, setLoading] = useState(true)

  const fetchAll = useCallback(async () => {
    try {
      const [
        balanceRes,
        pricesRes,
        tradesRes,
        performanceRes,
        modelRes,
        newsRes,
        fearGreedRes,
        positionsRes,
      ] = await Promise.allSettled([
        api.getBalance(),
        api.getPrices(),
        api.getTrades(),
        api.getPerformance(),
        api.getModelInfo(),
        api.getNews(),
        api.getFearGreed(),
        api.getOpenPositions(),
      ])

      setData({
        balance: balanceRes.status === 'fulfilled' ? balanceRes.value.data : null,
        prices: pricesRes.status === 'fulfilled' ? pricesRes.value.data : null,
        trades: tradesRes.status === 'fulfilled' ? tradesRes.value.data : [],
        performance: performanceRes.status === 'fulfilled' ? performanceRes.value.data : null,
        modelInfo: modelRes.status === 'fulfilled' ? modelRes.value.data : null,
        news: newsRes.status === 'fulfilled' ? newsRes.value.data : [],
        fearGreed: fearGreedRes.status === 'fulfilled' ? fearGreedRes.value.data : null,
        openPositions: positionsRes.status === 'fulfilled' ? positionsRes.value.data : [],
      })
    } catch {
      // keep previous data on error
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchAll()
    const timer = setInterval(fetchAll, interval)
    return () => clearInterval(timer)
  }, [fetchAll, interval])

  return { ...data, loading, refetch: fetchAll }
}

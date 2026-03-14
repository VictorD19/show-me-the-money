import { useEffect, useRef, useCallback } from 'react'
import { createChart, CrosshairMode, LineStyle } from 'lightweight-charts'
import ChartHeader from './ChartHeader'

const MOCK_CANDLES = Array.from({ length: 100 }, (_, i) => {
  const base = 65000 + Math.sin(i / 10) * 500
  const open = base + Math.random() * 200 - 100
  const close = base + Math.random() * 200 - 100
  return {
    time: Math.floor(Date.now() / 1000) - (99 - i) * 300,
    open,
    high: Math.max(open, close) + Math.random() * 200,
    low: Math.min(open, close) - Math.random() * 200,
    close,
    volume: 500 + Math.random() * 1000,
  }
})

function createChartInstance(container) {
  return createChart(container, {
    layout: {
      background: { color: '#161920' },
      textColor: '#8B8FA8',
      fontSize: 12,
      fontFamily: 'JetBrains Mono, monospace',
    },
    grid: {
      vertLines: { color: '#1E2028' },
      horzLines: { color: '#1E2028' },
    },
    crosshair: {
      mode: CrosshairMode.Normal,
      vertLine: { color: '#4A4E61', labelBackgroundColor: '#161920' },
      horzLine: { color: '#4A4E61', labelBackgroundColor: '#161920' },
    },
    rightPriceScale: {
      borderColor: '#1E2028',
      textColor: '#8B8FA8',
    },
    timeScale: {
      borderColor: '#1E2028',
      textColor: '#8B8FA8',
      timeVisible: true,
      secondsVisible: false,
    },
    width: container.clientWidth,
    height: container.clientHeight,
  })
}

export default function ChartPanel({
  symbol = 'BTCUSDT',
  candles,
  indicators,
  openPosition,
  onSymbolChange,
}) {
  const containerRef = useRef(null)
  const chartRef = useRef(null)
  const seriesRef = useRef({})
  const priceLinesRef = useRef([])

  // Initialize chart
  useEffect(() => {
    if (!containerRef.current) return

    const chart = createChartInstance(containerRef.current)
    chartRef.current = chart

    const candleSeries = chart.addCandlestickSeries({
      upColor: '#00D4AA',
      downColor: '#FF4757',
      borderUpColor: '#00D4AA',
      borderDownColor: '#FF4757',
      wickUpColor: '#00D4AA',
      wickDownColor: '#FF4757',
    })

    const ema25Series = chart.addLineSeries({
      color: '#4C8BF5',
      lineWidth: 1,
      title: 'EMA 25',
      priceLineVisible: false,
      lastValueVisible: true,
    })

    const ema50Series = chart.addLineSeries({
      color: '#FF8C42',
      lineWidth: 1,
      title: 'EMA 50',
      priceLineVisible: false,
      lastValueVisible: true,
    })

    const ema100Series = chart.addLineSeries({
      color: '#FF4757',
      lineWidth: 2,
      title: 'EMA 100',
      priceLineVisible: false,
      lastValueVisible: true,
    })

    const volumeSeries = chart.addHistogramSeries({
      color: '#1E2028',
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
    })
    volumeSeries.priceScale().applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 },
    })

    seriesRef.current = {
      candle: candleSeries,
      ema25: ema25Series,
      ema50: ema50Series,
      ema100: ema100Series,
      volume: volumeSeries,
    }

    return () => {
      chart.remove()
      chartRef.current = null
      seriesRef.current = {}
    }
  }, [])

  // Resize handler
  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const handleResize = () => {
      if (chartRef.current) {
        chartRef.current.applyOptions({
          width: container.clientWidth,
          height: container.clientHeight,
        })
      }
    }

    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [])

  // Update candle and volume data
  useEffect(() => {
    const series = seriesRef.current
    if (!series.candle) return

    const data = candles && candles.length > 0 ? candles : MOCK_CANDLES

    series.candle.setData(
      data.map((c) => ({
        time: c.time,
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
      }))
    )

    series.volume.setData(
      data.map((c) => ({
        time: c.time,
        value: c.volume,
        color: c.close >= c.open ? 'rgba(0,212,170,0.15)' : 'rgba(255,71,87,0.15)',
      }))
    )
  }, [candles])

  // Update indicator data
  useEffect(() => {
    const series = seriesRef.current
    if (!series.ema25 || !indicators) return

    if (indicators.ema25?.length) {
      series.ema25.setData(indicators.ema25)
    }
    if (indicators.ema50?.length) {
      series.ema50.setData(indicators.ema50)
    }
    if (indicators.ema100?.length) {
      series.ema100.setData(indicators.ema100)
    }

    if (indicators.signals?.length && series.candle) {
      series.candle.setMarkers(
        indicators.signals.map((signal) => ({
          time: signal.time,
          position: signal.direcao === 'LONG' ? 'belowBar' : 'aboveBar',
          color: signal.direcao === 'LONG' ? '#00D4AA' : '#FF4757',
          shape: signal.direcao === 'LONG' ? 'arrowUp' : 'arrowDown',
          text: `${signal.direcao} ${(signal.confianca * 100).toFixed(0)}%`,
        }))
      )
    }
  }, [indicators])

  // Update position price lines
  useEffect(() => {
    const series = seriesRef.current
    if (!series.candle) return

    // Remove existing price lines
    priceLinesRef.current.forEach((line) => {
      series.candle.removePriceLine(line)
    })
    priceLinesRef.current = []

    if (!openPosition) return

    const entryLine = series.candle.createPriceLine({
      price: openPosition.preco_entrada,
      color: '#EAEAEA',
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      title: 'Entrada',
    })

    const tpLine = series.candle.createPriceLine({
      price: openPosition.tp,
      color: '#00D4AA',
      lineWidth: 1,
      lineStyle: LineStyle.Dotted,
      title: 'TP',
    })

    const slLine = series.candle.createPriceLine({
      price: openPosition.sl,
      color: '#FF4757',
      lineWidth: 1,
      lineStyle: LineStyle.Dotted,
      title: 'SL',
    })

    priceLinesRef.current = [entryLine, tpLine, slLine]
  }, [openPosition])

  const hasData = candles && candles.length > 0

  return (
    <div className="bg-bg-card border border-bg-border rounded-xl h-full flex flex-col">
      <ChartHeader symbol={symbol} onSymbolChange={onSymbolChange} />
      <div ref={containerRef} className="flex-1 relative">
        {!hasData && (
          <div className="absolute inset-0 flex items-center justify-center z-10">
            <span className="text-text-muted text-sm font-mono">
              Carregando dados mock...
            </span>
          </div>
        )}
      </div>
    </div>
  )
}

import { TrendingUp, TrendingDown } from 'lucide-react'

const regimeDisplay = {
  TREND_UP: { label: 'TREND UP', color: 'text-accent-green', arrow: '\u25B2' },
  TREND_DOWN: { label: 'TREND DOWN', color: 'text-accent-red', arrow: '\u25BC' },
  LATERAL: { label: 'LATERAL', color: 'text-text-muted', arrow: '\u2192' },
}

export default function MarketPanel({ data, balance }) {
  const fundingRates = data?.fundingRates || {}
  const openInterest = data?.openInterest || {}
  const regime = data?.regime || 'LATERAL'
  const regimeInfo = regimeDisplay[regime] || regimeDisplay.LATERAL

  return (
    <div className="bg-bg-card border border-bg-border rounded-xl p-4">
      <h3 className="text-text-secondary text-xs uppercase tracking-wide font-medium mb-3">Mercado</h3>

      <div className="space-y-3">
        <div>
          <span className="text-text-muted text-xs">Funding Rate</span>
          <div className="space-y-1 mt-1">
            {Object.entries(fundingRates).length > 0 ? (
              Object.entries(fundingRates).map(([symbol, rate]) => (
                <div key={symbol} className="flex justify-between items-center">
                  <span className="text-xs text-text-secondary">{symbol}</span>
                  <span className={`font-mono text-xs font-medium ${
                    rate > 0 ? 'text-accent-red' : rate < 0 ? 'text-accent-green' : 'text-text-muted'
                  }`}>
                    {rate > 0 ? '+' : ''}{(rate * 100).toFixed(4)}%
                  </span>
                </div>
              ))
            ) : (
              <span className="text-text-muted text-xs">--</span>
            )}
          </div>
        </div>

        <div>
          <span className="text-text-muted text-xs">Open Interest</span>
          <div className="space-y-1 mt-1">
            {Object.entries(openInterest).length > 0 ? (
              Object.entries(openInterest).map(([symbol, oi]) => (
                <div key={symbol} className="flex justify-between items-center">
                  <span className="text-xs text-text-secondary">{symbol}</span>
                  <span className="flex items-center gap-1 font-mono text-xs">
                    {oi.change >= 0 ? (
                      <TrendingUp size={10} className="text-accent-green" />
                    ) : (
                      <TrendingDown size={10} className="text-accent-red" />
                    )}
                    <span className={oi.change >= 0 ? 'text-accent-green' : 'text-accent-red'}>
                      {oi.change >= 0 ? '+' : ''}{oi.change?.toFixed(2)}%
                    </span>
                  </span>
                </div>
              ))
            ) : (
              <span className="text-text-muted text-xs">--</span>
            )}
          </div>
        </div>

        <div>
          <span className="text-text-muted text-xs">Regime Detectado</span>
          <div className={`font-mono text-sm font-bold mt-1 ${regimeInfo.color}`}>
            {regimeInfo.arrow} {regimeInfo.label}
          </div>
        </div>

        <div className="pt-2 border-t border-bg-border">
          <span className="text-text-muted text-xs">Saldo Binance</span>
          <div className="font-mono text-lg font-bold text-text-primary mt-1">
            ${balance?.total != null ? Number(balance.total).toLocaleString(undefined, { minimumFractionDigits: 2 }) : '--'}
          </div>
        </div>
      </div>
    </div>
  )
}

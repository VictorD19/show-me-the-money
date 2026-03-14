import { Wifi, WifiOff } from 'lucide-react'

function PriceBadge({ symbol, price, change }) {
  const isPositive = change >= 0
  return (
    <div className="flex items-center gap-2 px-3 py-1 rounded-lg bg-bg-secondary">
      <span className="text-text-secondary text-xs font-medium">{symbol}</span>
      <span className="font-mono text-sm text-text-primary">
        ${typeof price === 'number' ? price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '--'}
      </span>
      <span className={`font-mono text-xs ${isPositive ? 'text-accent-green' : 'text-accent-red'}`}>
        {isPositive ? '+' : ''}{typeof change === 'number' ? change.toFixed(2) : '0.00'}%
      </span>
    </div>
  )
}

export default function TopBar({ prices, isConnected, mode = 'TESTNET' }) {
  const priceList = prices || {}

  return (
    <header className="flex items-center justify-between px-4 h-12 bg-bg-secondary border-b border-bg-border shrink-0">
      <div className="flex items-center gap-4">
        <span className="font-mono font-bold text-accent-green text-lg tracking-wider">SMTM</span>
        <div className="flex items-center gap-2">
          <PriceBadge symbol="BTC" price={priceList.BTC?.price} change={priceList.BTC?.change} />
          <PriceBadge symbol="ETH" price={priceList.ETH?.price} change={priceList.ETH?.change} />
          <PriceBadge symbol="XRP" price={priceList.XRP?.price} change={priceList.XRP?.change} />
        </div>
      </div>

      <div className="flex items-center gap-3">
        <div className="flex items-center gap-1.5">
          {isConnected ? (
            <>
              <Wifi size={14} className="text-accent-green" />
              <span className="text-accent-green text-xs font-medium">LIVE</span>
            </>
          ) : (
            <>
              <WifiOff size={14} className="text-accent-red" />
              <span className="text-accent-red text-xs font-medium">OFFLINE</span>
            </>
          )}
        </div>
        <span className={`px-2 py-0.5 rounded text-xs font-bold ${
          mode === 'TESTNET' ? 'bg-accent-yellow/20 text-accent-yellow' : 'bg-accent-red/20 text-accent-red'
        }`}>
          [{mode}]
        </span>
      </div>
    </header>
  )
}

export default function ChartHeader({ symbol, onSymbolChange }) {
  const pairs = ['BTCUSDT', 'ETHUSDT', 'XRPUSDT']

  return (
    <div className="flex items-center justify-between p-3 border-b border-bg-border">
      <div className="flex gap-2">
        {pairs.map((s) => (
          <button
            key={s}
            onClick={() => onSymbolChange(s)}
            className={`px-3 py-1 rounded text-sm font-mono ${
              symbol === s
                ? 'bg-accent-blue text-white'
                : 'text-text-secondary hover:text-text-primary'
            }`}
          >
            {s.replace('USDT', '/USDT')}
          </button>
        ))}
      </div>

      <div className="flex gap-4 text-xs font-mono">
        <span className="text-accent-blue">── EMA 25</span>
        <span className="text-accent-orange">── EMA 50</span>
        <span className="text-accent-red">── EMA 100</span>
      </div>

      <span className="text-text-muted text-xs">5m</span>
    </div>
  )
}

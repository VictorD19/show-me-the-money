export default function PositionCard({ position }) {
  if (!position || !position.symbol) {
    return (
      <div className="bg-bg-card border border-bg-border rounded-xl p-4 h-full flex items-center justify-center">
        <span className="text-text-muted text-sm">Sem posicao aberta</span>
      </div>
    )
  }

  const isLong = position.side === 'LONG'
  const pnl = position.pnl || 0
  const pnlPercent = position.pnlPercent || 0
  const isPnlPositive = pnl >= 0

  const slProgress = position.slDistance != null
    ? Math.min(100, Math.max(0, (1 - position.slDistance) * 100))
    : 0
  const tpProgress = position.tpDistance != null
    ? Math.min(100, Math.max(0, position.tpDistance * 100))
    : 0

  return (
    <div className="bg-bg-card border border-bg-border rounded-xl p-4 h-full">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="text-text-primary font-bold text-sm">{position.symbol}</span>
          <span className={`px-2 py-0.5 rounded text-xs font-bold ${
            isLong ? 'bg-accent-green/20 text-accent-green' : 'bg-accent-red/20 text-accent-red'
          }`}>
            {isLong ? 'LONG' : 'SHORT'}
          </span>
        </div>
        <span className="px-2 py-0.5 rounded bg-accent-purple/20 text-accent-purple text-xs font-bold">
          {position.leverage || 1}x
        </span>
      </div>

      <div className="mb-3">
        <span className="text-text-secondary text-xs uppercase tracking-wide">Entrada</span>
        <div className="font-mono text-sm text-text-primary">
          ${typeof position.entryPrice === 'number' ? position.entryPrice.toLocaleString() : '--'}
        </div>
      </div>

      <div className="mb-4">
        <span className="text-text-secondary text-xs uppercase tracking-wide">P&L</span>
        <div className={`font-mono text-2xl font-bold ${isPnlPositive ? 'text-accent-green' : 'text-accent-red'}`}>
          {isPnlPositive ? '+' : ''}{pnl.toFixed(2)} USD
        </div>
        <span className={`font-mono text-xs ${isPnlPositive ? 'text-accent-green' : 'text-accent-red'}`}>
          ({isPnlPositive ? '+' : ''}{pnlPercent.toFixed(2)}%)
        </span>
      </div>

      <div className="space-y-2">
        <div>
          <div className="flex justify-between text-xs mb-1">
            <span className="text-accent-red">SL</span>
            <span className="text-text-muted font-mono">{slProgress.toFixed(0)}%</span>
          </div>
          <div className="w-full h-1.5 bg-bg-secondary rounded-full">
            <div className="h-full bg-accent-red rounded-full transition-all" style={{ width: `${slProgress}%` }} />
          </div>
        </div>
        <div>
          <div className="flex justify-between text-xs mb-1">
            <span className="text-accent-green">TP</span>
            <span className="text-text-muted font-mono">{tpProgress.toFixed(0)}%</span>
          </div>
          <div className="w-full h-1.5 bg-bg-secondary rounded-full">
            <div className="h-full bg-accent-green rounded-full transition-all" style={{ width: `${tpProgress}%` }} />
          </div>
        </div>
      </div>
    </div>
  )
}

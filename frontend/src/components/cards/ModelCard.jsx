function ConfidenceGauge({ value = 0 }) {
  const radius = 40
  const stroke = 6
  const circumference = 2 * Math.PI * radius
  const progress = (value / 100) * circumference
  const color = value >= 70 ? '#00D4AA' : value >= 40 ? '#FFD166' : '#FF4757'

  return (
    <div className="relative inline-flex items-center justify-center">
      <svg width={100} height={100} viewBox="0 0 100 100">
        <circle
          cx="50" cy="50" r={radius}
          fill="none" stroke="#1E2028" strokeWidth={stroke}
        />
        <circle
          cx="50" cy="50" r={radius}
          fill="none" stroke={color} strokeWidth={stroke}
          strokeDasharray={circumference}
          strokeDashoffset={circumference - progress}
          strokeLinecap="round"
          transform="rotate(-90 50 50)"
          className="transition-all duration-500"
        />
      </svg>
      <div className="absolute inset-0 flex items-center justify-center">
        <span className="font-mono text-lg font-bold text-text-primary">{value}%</span>
      </div>
    </div>
  )
}

const regimeDisplay = {
  TREND_UP: { label: 'TREND UP', color: 'text-accent-green', arrow: '\u25B2' },
  TREND_DOWN: { label: 'TREND DOWN', color: 'text-accent-red', arrow: '\u25BC' },
  LATERAL: { label: 'LATERAL', color: 'text-text-muted', arrow: '\u2192' },
}

export default function ModelCard({ model }) {
  const confidence = model?.confidence ?? 0
  const accuracy = model?.accuracy ?? 0
  const regime = model?.regime || 'LATERAL'
  const lastRetrain = model?.lastRetrain || '--'
  const regimeInfo = regimeDisplay[regime] || regimeDisplay.LATERAL

  return (
    <div className="bg-bg-card border border-bg-border rounded-xl p-4 h-full">
      <h3 className="text-text-secondary text-xs uppercase tracking-wide font-medium mb-3">Modelo ML</h3>

      <div className="flex items-center gap-4">
        <ConfidenceGauge value={confidence} />
        <div className="flex-1 space-y-2">
          <div>
            <span className="text-text-muted text-xs">Acuracia</span>
            <div className="font-mono text-sm text-text-primary">{accuracy.toFixed(1)}%</div>
          </div>
          <div>
            <span className="text-text-muted text-xs">Regime</span>
            <div className={`font-mono text-sm font-bold ${regimeInfo.color}`}>
              {regimeInfo.arrow} {regimeInfo.label}
            </div>
          </div>
          <div>
            <span className="text-text-muted text-xs">Ultimo Treino</span>
            <div className="text-xs text-text-secondary">{lastRetrain}</div>
          </div>
        </div>
      </div>
    </div>
  )
}

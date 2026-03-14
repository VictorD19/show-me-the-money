import { TrendingUp, TrendingDown, Minus } from 'lucide-react'

const trendIcons = {
  up: TrendingUp,
  down: TrendingDown,
  neutral: Minus,
}

const colorMap = {
  green: 'text-accent-green',
  red: 'text-accent-red',
  blue: 'text-accent-blue',
  orange: 'text-accent-orange',
  purple: 'text-accent-purple',
}

export default function MetricCard({ title, value, subtitle, trend, color }) {
  const TrendIcon = trend ? trendIcons[trend] : null
  const valueColor = color ? colorMap[color] : 'text-text-primary'
  const trendColor = trend === 'up' ? 'text-accent-green' : trend === 'down' ? 'text-accent-red' : 'text-text-muted'

  return (
    <div className="bg-bg-card border border-bg-border rounded-xl p-4">
      <div className="flex items-center justify-between mb-2">
        <span className="text-text-secondary text-xs uppercase tracking-wide font-medium">{title}</span>
        {TrendIcon && <TrendIcon size={14} className={trendColor} />}
      </div>
      <div className={`font-mono text-2xl font-bold ${valueColor}`}>
        {value}
      </div>
      {subtitle && (
        <span className="text-text-muted text-xs mt-1 block">{subtitle}</span>
      )}
    </div>
  )
}

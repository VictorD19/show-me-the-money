import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, Area, AreaChart } from 'recharts'

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null
  return (
    <div className="bg-bg-card border border-bg-border rounded-lg p-2 text-xs">
      <div className="text-text-muted mb-1">{label}</div>
      <div className="font-mono text-accent-green font-bold">
        ${payload[0].value?.toFixed(2)}
      </div>
    </div>
  )
}

export default function EquityChart({ trades = [] }) {
  const chartData = trades.reduce((acc, trade, i) => {
    const prev = acc[acc.length - 1]?.equity || 0
    acc.push({
      date: trade.date || `T${i + 1}`,
      equity: prev + (trade.profit || 0),
    })
    return acc
  }, [])

  if (chartData.length === 0) {
    chartData.push({ date: 'Inicio', equity: 0 })
  }

  return (
    <div className="bg-bg-card border border-bg-border rounded-xl p-4">
      <h3 className="text-text-secondary text-xs uppercase tracking-wide font-medium mb-3">Curva de Equity</h3>
      <div className="h-40">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={chartData}>
            <defs>
              <linearGradient id="equityGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#00D4AA" stopOpacity={0.3} />
                <stop offset="95%" stopColor="#00D4AA" stopOpacity={0} />
              </linearGradient>
            </defs>
            <XAxis
              dataKey="date"
              tick={{ fill: '#4A4E61', fontSize: 10 }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              tick={{ fill: '#4A4E61', fontSize: 10 }}
              axisLine={false}
              tickLine={false}
              width={50}
              tickFormatter={(v) => `$${v}`}
            />
            <Tooltip content={<CustomTooltip />} />
            <Area
              type="monotone"
              dataKey="equity"
              stroke="#00D4AA"
              strokeWidth={2}
              fill="url(#equityGradient)"
              dot={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

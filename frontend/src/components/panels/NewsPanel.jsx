function getFearGreedStyle(value) {
  if (value <= 25) return { label: 'Extreme Fear', color: 'bg-accent-red', textColor: 'text-accent-red' }
  if (value <= 45) return { label: 'Fear', color: 'bg-accent-orange', textColor: 'text-accent-orange' }
  if (value <= 55) return { label: 'Neutral', color: 'bg-text-muted', textColor: 'text-text-muted' }
  if (value <= 75) return { label: 'Greed', color: 'bg-accent-green/70', textColor: 'text-accent-green' }
  return { label: 'Extreme Greed', color: 'bg-accent-green', textColor: 'text-accent-green' }
}

function timeAgo(timestamp) {
  if (!timestamp) return ''
  const now = Date.now()
  const diff = now - new Date(timestamp).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'agora'
  if (mins < 60) return `ha ${mins} min`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `ha ${hours}h`
  return `ha ${Math.floor(hours / 24)}d`
}

function sentimentIcon(score) {
  if (score > 0.3) return '\uD83D\uDFE2'
  if (score < -0.3) return '\uD83D\uDD34'
  return '\u26AA'
}

export default function NewsPanel({ news = [], fearGreed }) {
  const fgValue = fearGreed?.value ?? 50
  const fgStyle = getFearGreedStyle(fgValue)

  return (
    <div className="bg-bg-card border border-bg-border rounded-xl p-4">
      <h3 className="text-text-secondary text-xs uppercase tracking-wide font-medium mb-3">Fear & Greed</h3>

      <div className="flex items-center gap-3 mb-3">
        <span className={`font-mono text-3xl font-bold ${fgStyle.textColor}`}>{fgValue}</span>
        <div>
          <div className={`text-sm font-medium ${fgStyle.textColor}`}>{fgStyle.label}</div>
        </div>
      </div>
      <div className="w-full h-2 bg-bg-secondary rounded-full mb-4">
        <div
          className={`h-full rounded-full transition-all ${fgStyle.color}`}
          style={{ width: `${fgValue}%` }}
        />
      </div>

      <h3 className="text-text-secondary text-xs uppercase tracking-wide font-medium mb-2">Noticias</h3>
      <div className="space-y-2">
        {news.length === 0 ? (
          <p className="text-text-muted text-xs">Sem noticias recentes</p>
        ) : (
          news.slice(0, 5).map((item, i) => (
            <div key={i} className="flex items-start gap-2">
              <span className="text-sm shrink-0">{sentimentIcon(item.sentiment ?? 0)}</span>
              <div className="min-w-0 flex-1">
                <a
                  href={item.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-xs text-text-primary hover:text-accent-blue truncate block"
                >
                  {item.title}
                </a>
                <span className="text-text-muted text-[10px]">{timeAgo(item.timestamp)}</span>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}

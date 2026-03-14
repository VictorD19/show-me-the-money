import { useState } from 'react'
import { Check, X } from 'lucide-react'

const PAGE_SIZE = 10

export default function TradesTable({ trades = [] }) {
  const [page, setPage] = useState(0)
  const totalPages = Math.max(1, Math.ceil(trades.length / PAGE_SIZE))
  const paginated = trades.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)

  return (
    <div className="bg-bg-card border border-bg-border rounded-xl p-4">
      <h3 className="text-text-secondary text-xs uppercase tracking-wide font-medium mb-3">Historico de Trades</h3>

      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-text-muted border-b border-bg-border">
              <th className="text-left py-2 px-2 font-medium">Par</th>
              <th className="text-left py-2 px-2 font-medium">Direcao</th>
              <th className="text-right py-2 px-2 font-medium">Entrada</th>
              <th className="text-right py-2 px-2 font-medium">Saida</th>
              <th className="text-right py-2 px-2 font-medium">SL</th>
              <th className="text-right py-2 px-2 font-medium">TP</th>
              <th className="text-center py-2 px-2 font-medium">Resultado</th>
              <th className="text-right py-2 px-2 font-medium">Lucro</th>
              <th className="text-right py-2 px-2 font-medium">Data</th>
            </tr>
          </thead>
          <tbody>
            {paginated.length === 0 ? (
              <tr>
                <td colSpan={9} className="text-center py-8 text-text-muted">
                  Nenhum trade registrado
                </td>
              </tr>
            ) : (
              paginated.map((trade, i) => {
                const isWin = trade.result === 'WIN'
                return (
                  <tr
                    key={trade.id || i}
                    className={`border-b border-bg-border/50 ${
                      isWin ? 'bg-accent-green/5' : 'bg-accent-red/5'
                    }`}
                  >
                    <td className="py-2 px-2 text-text-primary font-medium">{trade.symbol}</td>
                    <td className="py-2 px-2">
                      <span className={isWin ? 'text-accent-green' : 'text-accent-red'}>
                        {trade.side}
                      </span>
                    </td>
                    <td className="py-2 px-2 text-right font-mono text-text-primary">
                      {trade.entryPrice?.toLocaleString() ?? '--'}
                    </td>
                    <td className="py-2 px-2 text-right font-mono text-text-primary">
                      {trade.exitPrice?.toLocaleString() ?? '--'}
                    </td>
                    <td className="py-2 px-2 text-right font-mono text-text-muted">
                      {trade.sl?.toLocaleString() ?? '--'}
                    </td>
                    <td className="py-2 px-2 text-right font-mono text-text-muted">
                      {trade.tp?.toLocaleString() ?? '--'}
                    </td>
                    <td className="py-2 px-2 text-center">
                      {isWin ? (
                        <span className="inline-flex items-center gap-1 text-accent-green">
                          <Check size={12} /> WIN
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-accent-red">
                          <X size={12} /> LOSS
                        </span>
                      )}
                    </td>
                    <td className={`py-2 px-2 text-right font-mono font-bold ${
                      (trade.profit || 0) >= 0 ? 'text-accent-green' : 'text-accent-red'
                    }`}>
                      {(trade.profit || 0) >= 0 ? '+' : ''}{(trade.profit || 0).toFixed(2)}
                    </td>
                    <td className="py-2 px-2 text-right text-text-muted">
                      {trade.date || '--'}
                    </td>
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>

      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2 mt-3">
          <button
            onClick={() => setPage(p => Math.max(0, p - 1))}
            disabled={page === 0}
            className="px-2 py-1 text-xs rounded bg-bg-secondary text-text-secondary disabled:opacity-30 hover:bg-bg-border transition-colors"
          >
            Anterior
          </button>
          <span className="text-xs text-text-muted font-mono">{page + 1}/{totalPages}</span>
          <button
            onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))}
            disabled={page >= totalPages - 1}
            className="px-2 py-1 text-xs rounded bg-bg-secondary text-text-secondary disabled:opacity-30 hover:bg-bg-border transition-colors"
          >
            Proximo
          </button>
        </div>
      )}
    </div>
  )
}

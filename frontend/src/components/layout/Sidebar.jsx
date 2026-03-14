import { useState } from 'react'
import { LayoutDashboard, History, Settings } from 'lucide-react'

const navItems = [
  { icon: LayoutDashboard, label: 'Dashboard', id: 'dashboard' },
  { icon: History, label: 'Trades', id: 'trades' },
  { icon: Settings, label: 'Configuracoes', id: 'settings' },
]

export default function Sidebar({ active = 'dashboard', onNavigate }) {
  const [hovered, setHovered] = useState(null)

  return (
    <aside className="w-16 bg-bg-secondary border-r border-bg-border flex flex-col items-center py-4 gap-2 shrink-0">
      {navItems.map((item) => {
        const Icon = item.icon
        const isActive = active === item.id
        return (
          <div key={item.id} className="relative">
            <button
              onClick={() => onNavigate?.(item.id)}
              onMouseEnter={() => setHovered(item.id)}
              onMouseLeave={() => setHovered(null)}
              className={`w-10 h-10 rounded-lg flex items-center justify-center transition-colors ${
                isActive
                  ? 'bg-accent-green/10 text-accent-green'
                  : 'text-text-muted hover:text-text-secondary hover:bg-bg-card'
              }`}
            >
              <Icon size={20} />
            </button>
            {hovered === item.id && (
              <div className="absolute left-14 top-1/2 -translate-y-1/2 px-2 py-1 bg-bg-card border border-bg-border rounded text-xs text-text-primary whitespace-nowrap z-50">
                {item.label}
              </div>
            )}
          </div>
        )
      })}
    </aside>
  )
}

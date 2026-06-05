import { Layers, BarChart3, Settings } from 'lucide-react'
import type { Page } from '../App'

const navItems = [
  { icon: Layers, label: 'Topology', page: 'topology' as Page },
  { icon: BarChart3, label: 'Analytics', page: 'analytics' as Page },
  { icon: Settings, label: 'Settings', page: 'settings' as Page },
]

interface SidebarProps {
  activePage: Page
  onNavigate: (page: Page) => void
}

export function Sidebar({ activePage, onNavigate }: SidebarProps) {
  return (
    <aside className="w-20 h-screen bg-on-background flex flex-col items-center pt-6 pb-6 gap-3 shrink-0">
      {/* Logo mark */}
      <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-primary to-primary-container flex items-center justify-center mb-8">
        <span className="text-on-primary font-display font-bold text-lg">Z</span>
      </div>

      {/* Nav items */}
      <nav className="flex flex-col gap-2 flex-1">
        {navItems.map(({ icon: Icon, label, page }) => (
          <button
            key={label}
            title={label}
            onClick={() => onNavigate(page)}
            className={`w-12 h-12 rounded-xl flex items-center justify-center transition-all duration-200
              ${activePage === page
                ? 'bg-white/10 text-on-primary'
                : 'text-white/40 hover:text-white/70 hover:bg-white/5'
              }`}
          >
            <Icon size={22} strokeWidth={1.5} />
          </button>
        ))}
      </nav>
    </aside>
  )
}

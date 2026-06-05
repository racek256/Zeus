import { useState } from 'react'
import { Map as MapIcon, Satellite, Moon, Globe, Type } from 'lucide-react'

const styles = [
  { id: 'streets-v12', label: 'Streets', icon: Globe },
  { id: 'satellite-v9', label: 'Satellite', icon: Satellite },
  { id: 'dark-v11', label: 'Dark', icon: Moon },
]

interface MapStyleSwitcherProps {
  currentStyle: string
  onChange: (style: string) => void
  labelsEnabled: boolean
  onLabelsChange: (enabled: boolean) => void
  is3d: boolean
  onViewModeChange: (enabled: boolean) => void
}

export function MapStyleSwitcher({ currentStyle, onChange, labelsEnabled, onLabelsChange, is3d, onViewModeChange }: MapStyleSwitcherProps) {
  const [open, setOpen] = useState(false)

  return (
    <div className="absolute bottom-6 right-6 z-10 flex items-end gap-2">
      <button
        onClick={() => onLabelsChange(!labelsEnabled)}
        className={`h-12 min-w-12 rounded-xl px-3 backdrop-blur-sm flex items-center justify-center shadow-lg transition-colors ${
          labelsEnabled
            ? 'bg-on-background text-white'
            : 'bg-on-background/78 text-white/55 hover:text-white hover:bg-on-background/90'
        }`}
        title={labelsEnabled ? 'Hide Czech labels' : 'Show Czech labels'}
      >
        <Type size={19} strokeWidth={1.8} />
      </button>

      <button
        onClick={() => onViewModeChange(!is3d)}
        className={`h-12 min-w-12 rounded-xl px-3 backdrop-blur-sm flex items-center justify-center shadow-lg transition-colors text-[11px] font-semibold tracking-[0.14em] ${
          is3d
            ? 'bg-on-background text-white'
            : 'bg-on-background/78 text-white/55 hover:text-white hover:bg-on-background/90'
        }`}
        title={is3d ? 'Switch to 2D view' : 'Switch to 3D view'}
      >
        {is3d ? '3D' : '2D'}
      </button>

      <button
        onClick={() => setOpen(!open)}
        className="w-12 h-12 rounded-xl bg-on-background/90 backdrop-blur-sm text-white/70 hover:text-white flex items-center justify-center shadow-lg transition-colors"
        title="Map style"
      >
        <MapIcon size={22} strokeWidth={1.5} />
      </button>

      {open && (
        <div className="absolute bottom-14 right-0 flex flex-col gap-1">
          {styles.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => {
                onChange(id)
                setOpen(false)
              }}
              className={`w-12 h-12 rounded-xl flex items-center justify-center transition-all duration-200
                ${currentStyle === id
                  ? 'bg-on-background text-white ring-2 ring-white/30'
                  : 'bg-on-background/80 backdrop-blur-sm text-white/50 hover:text-white hover:bg-on-background'
                }`}
              title={label}
            >
              <Icon size={20} strokeWidth={1.5} />
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

import { RotateCcw, Sliders, Globe, Satellite, Moon } from 'lucide-react'
import { useSettings } from '../hooks/useSettings'

const REFRESH_OPTIONS = [10, 30, 60, 120, 300]

const MAP_STYLES = [
  { id: 'streets-v12', label: 'Streets', icon: Globe },
  { id: 'satellite-v9', label: 'Satellite', icon: Satellite },
  { id: 'dark-v11', label: 'Dark', icon: Moon },
]

export function Settings() {
  const { settings, updateSetting, resetSettings } = useSettings()

  return (
    <div className="flex-1 overflow-auto p-6 bg-surface-low">
      <div className="mb-6">
        <h2 className="font-display text-2xl font-bold text-on-background tracking-tight">
          Settings
        </h2>
        <p className="text-sm text-on-surface-variant mt-1">
          Configure grid topology dashboard preferences
        </p>
      </div>

      <div className="bg-surface-lowest rounded-2xl p-6 max-w-xl space-y-6">
        <div>
          <h3 className="font-display text-sm font-semibold text-on-background mb-4 flex items-center gap-2">
            <Sliders size={16} strokeWidth={1.8} />
            Map Configuration
          </h3>
          <div className="space-y-6">
            <div className="space-y-2">
              <label className="text-sm text-on-surface-variant">Map Style</label>
              <div className="flex gap-2 flex-wrap">
                {MAP_STYLES.map(({ id, label, icon: Icon }) => (
                  <button
                    key={id}
                    onClick={() => updateSetting('mapStyle', id)}
                    className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                      settings.mapStyle === id
                        ? 'bg-primary text-on-primary'
                        : 'bg-surface-high text-on-surface-variant hover:text-on-background hover:bg-surface-highest'
                    }`}
                  >
                    <Icon size={16} strokeWidth={1.8} />
                    {label}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>

        <div className="h-px bg-surface-high" />

        <div>
          <h3 className="font-display text-sm font-semibold text-on-background mb-4">
            Data Configuration
          </h3>
          <div className="space-y-6">
            <div className="space-y-2">
              <label className="text-sm text-on-surface-variant">Refresh Interval</label>
              <div className="flex gap-2 flex-wrap">
                {REFRESH_OPTIONS.map(seconds => (
                  <button
                    key={seconds}
                    onClick={() => updateSetting('refreshInterval', seconds)}
                    className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                      settings.refreshInterval === seconds
                        ? 'bg-primary text-on-primary'
                        : 'bg-surface-high text-on-surface-variant hover:text-on-background hover:bg-surface-highest'
                    }`}
                  >
                    {seconds >= 60 ? `${seconds / 60}m` : `${seconds}s`}
                  </button>
                ))}
              </div>
            </div>

            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <label className="text-sm text-on-surface-variant">Data Timeout</label>
                <span className="text-sm font-medium text-on-background bg-surface-high px-3 py-1.5 rounded-lg min-w-[4rem] text-center">
                  {settings.dataTimeout}s
                </span>
              </div>
              <input
                type="range"
                min={5}
                max={120}
                step={5}
                value={settings.dataTimeout}
                onChange={e => updateSetting('dataTimeout', parseInt(e.target.value, 10))}
                className="w-full h-2 bg-surface-high rounded-lg appearance-none cursor-pointer accent-primary"
              />
              <div className="flex justify-between text-[10px] text-on-surface-variant">
                <span>5s</span>
                <span>120s</span>
              </div>
            </div>
          </div>
        </div>

        <div className="h-px bg-surface-high" />

        <div className="flex justify-end">
          <button
            onClick={resetSettings}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-surface-high text-on-surface-variant hover:text-on-background hover:bg-surface-highest transition-colors text-sm font-medium"
          >
            <RotateCcw size={16} strokeWidth={1.8} />
            Reset to Defaults
          </button>
        </div>
      </div>
    </div>
  )
}
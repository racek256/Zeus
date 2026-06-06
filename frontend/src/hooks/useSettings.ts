import { useState, useEffect, useCallback } from 'react'

const STORAGE_KEY = 'grid-settings'

export const DEFAULTS = {
  mapStyle: 'satellite-v9',
  refreshInterval: 30,
  dataTimeout: 30,
}

export interface SettingsState {
  mapStyle: string
  refreshInterval: number
  dataTimeout: number
}

function loadSettings(): SettingsState {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored) {
      return { ...DEFAULTS, ...JSON.parse(stored) }
    }
  } catch {
    // ignore parse errors
  }
  return DEFAULTS
}

const settingsChangeEvent = new EventTarget()

export function useSettings() {
  const [settings, setSettings] = useState<SettingsState>(loadSettings)

  useEffect(() => {
    const handler = () => setSettings(loadSettings())
    settingsChangeEvent.addEventListener('change', handler)
    return () => settingsChangeEvent.removeEventListener('change', handler)
  }, [])

  const updateSetting = useCallback(<K extends keyof SettingsState>(key: K, value: SettingsState[K]) => {
    setSettings(prev => {
      const next = { ...prev, [key]: value }
      localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
      settingsChangeEvent.dispatchEvent(new Event('change'))
      return next
    })
  }, [])

  const resetSettings = useCallback(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(DEFAULTS))
    setSettings(DEFAULTS)
    settingsChangeEvent.dispatchEvent(new Event('change'))
  }, [])

  return { settings, updateSetting, resetSettings }
}
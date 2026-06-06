import { useState } from 'react'
import { Sidebar } from './components/Sidebar'
import { Navbar } from './components/Navbar'
import { MapView } from './components/MapView'
import { Analytics } from './pages/Analytics'
import { Settings } from './pages/Settings'
import { useSettings } from './hooks/useSettings'

export type Page = 'topology' | 'analytics' | 'settings'

function App() {
  const { settings, updateSetting } = useSettings()
  const [activePage, setActivePage] = useState<Page>('topology')

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-surface">
      <Sidebar activePage={activePage} onNavigate={setActivePage} />
      <div className="flex flex-col flex-1 min-w-0">
        <Navbar />
        <div className="relative flex-1 min-h-0">
          <div
            aria-hidden={activePage !== 'topology'}
            className={activePage === 'topology' ? 'absolute inset-0 z-10' : 'absolute inset-0 pointer-events-none opacity-0'}
          >
            <MapView mapStyle={settings.mapStyle} onStyleChange={(style) => updateSetting('mapStyle', style)} />
          </div>
          {activePage === 'analytics' && (
            <div className="absolute inset-0 z-10">
              <Analytics />
            </div>
          )}
          <div
            aria-hidden={activePage !== 'settings'}
            className={activePage === 'settings' ? 'absolute inset-0 z-10' : 'absolute inset-0 pointer-events-none opacity-0'}
          >
            <Settings />
          </div>
        </div>
      </div>
    </div>
  )
}

export default App

export function Settings() {
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

      <div className="bg-surface-lowest rounded-2xl p-6 max-w-xl">
        <h3 className="font-display text-sm font-semibold text-on-background mb-4">
          Map Configuration
        </h3>
        <div className="space-y-4">
          {[
            { label: 'Default Zoom Level', value: '6.5' },
            { label: 'Center Longitude', value: '15.5' },
            { label: 'Center Latitude', value: '49.8' },
            { label: 'Refresh Interval', value: '30s' },
          ].map(({ label, value }) => (
            <div key={label} className="flex items-center justify-between">
              <span className="text-sm text-on-surface-variant">{label}</span>
              <span className="text-sm font-medium text-on-background bg-surface-high px-3 py-1.5 rounded-lg">
                {value}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

export function Navbar() {
  return (
    <header className="h-14 flex items-center justify-between px-6 shrink-0">
      {/* Title */}
      <div className="flex items-baseline gap-3">
        <h1 className="font-display text-lg font-bold tracking-tight text-on-background">
          Grid Topology
        </h1>
        <span className="text-xs font-medium text-on-surface-variant uppercase tracking-widest">
          Dashboard
        </span>
      </div>

      {/* Right side - placeholder */}
      <div className="flex items-center gap-4">
        
        <div className="w-8 h-8 rounded-full bg-surface-high flex items-center justify-center">
          <span className="text-xs font-medium text-on-background">R</span>
        </div>
      </div>
    </header>
  )
}

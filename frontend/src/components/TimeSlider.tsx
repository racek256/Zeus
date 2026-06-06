import { useCallback, useMemo } from 'react'

interface TimeSliderProps {
  timestamps: string[]
  selected: string | null
  onChange: (timestamp: string) => void
}

function formatTimestamp(ts: string): string {
  try {
    const date = new Date(ts)
    return date.toLocaleString('cs-CZ', {
      day: '2-digit',
      month: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return ts
  }
}

export function TimeSlider({ timestamps, selected, onChange }: TimeSliderProps) {
  const currentIndex = useMemo(() => {
    if (!selected || timestamps.length === 0) return 0
    const idx = timestamps.indexOf(selected)
    return idx >= 0 ? idx : 0
  }, [selected, timestamps])

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const idx = Number(e.target.value)
      if (timestamps[idx]) {
        onChange(timestamps[idx])
      }
    },
    [timestamps, onChange],
  )

  if (timestamps.length === 0) return null

  return (
    <div className="absolute bottom-6 left-1/2 z-10 -translate-x-1/2">
      <div className="flex flex-col items-center gap-2 rounded-xl bg-surface-low/90 px-6 py-3 backdrop-blur-md">
        <span className="font-display text-xs font-semibold tracking-wide text-on-surface-variant">
          {selected ? formatTimestamp(selected) : 'Select time'}
        </span>
        <input
          type="range"
          min={0}
          max={timestamps.length - 1}
          value={currentIndex}
          onChange={handleChange}
          className="w-72 cursor-pointer accent-primary"
        />
        <div className="flex w-72 justify-between text-[10px] text-on-surface-variant">
          <span>{formatTimestamp(timestamps[0])}</span>
          <span>{formatTimestamp(timestamps[timestamps.length - 1])}</span>
        </div>
      </div>
    </div>
  )
}

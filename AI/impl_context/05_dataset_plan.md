# Phase Dataset Plan

## Clarified decision

If `gens_ts.csv` is missing one complete generator hour, **detect and skip that hour** during full replay.

## Dataset facts

- Root: `./greenhack-2026-ČEPS-dataset`.
- Static topology: `data/static/`.
- Ground-truth pandapower snapshots: `data/snapshots/`, 8,760 hourly JSON files.
- Realtime actuals withheld from agents: `data/realtime/gens_ts.csv`, `data/realtime/loads_ts.csv`.
- Agent-safe forecasts: `data/forecasts/DA/Load`, `Solar`, `Wind`.
- Fuel prices: `data/other/Fuel prices 2024.csv`.

## Implementation rules

- Use `pathlib.Path` for the `ČEPS` path and the fuel-price filename containing spaces.
- Parse forecast datetimes explicitly; forecast CSVs differ from realtime ISO timestamps.
- Preload/index large realtime CSVs before simulation steps; do not parse full CSVs during each step.
- Snapshots are ground truth for evaluation and must not be exposed to agents as forecasts or observations.
- When skipping a missing generator-actual hour, log it and exclude it from final replay coverage metrics.

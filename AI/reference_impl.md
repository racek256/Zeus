# Czech grid AI operator — implementation handoff

## What you are building

An AI system that operates the Czech Republic's power grid autonomously for a full day (8,760-hour dataset available for testing). The system uses opencode with MCP integrations. The design principle: **agents reason, tools calculate** — no LLM ever estimates a number that a deterministic algorithm can compute exactly.

---

## Architecture

### Four layers

**L1 — National coordinator agent**
Single agent with ČEPS-level authority. Responsibilities:
- Day-ahead generation schedule approval (runs at D-1, i.e. the day before the operating day)
- N-1 contingency scan as a hard gate on every schedule change
- Cross-border tie-line management (Germany, Slovakia, Austria, Poland via ENTSO-E)
- Conflict arbitration: regional disagreements escalate here, coordinator veto is final
- Deadlock protocol: if unresolved after 30s → safe mode (freeze schedules, alert human)

**L2 — Four regional agents (peers)**
Each agent has a production-aware identity that shapes its reasoning:

| Agent | Character |
|---|---|
| Bohemia West | Generation-heavy: Temelín/Dukovany nuclear proximity, brown coal (Prunéřov) |
| Bohemia East | Prague load centre: high demand density, limited local generation |
| Moravia | Flexibility provider: gas peakers + pumped hydro at Dalešice |
| Silesia | Industrial demand: large sheddable loads, cross-border exposure |

Agents communicate via a **shared peer bus** (not direct calls):
- Each agent continuously publishes: current load vs schedule, available headroom, reserve status, active alarms
- Negotiation messages (transfer requests, redispatch asks) are explicitly typed, not commands
- Read-only telemetry is visible to all agents at all times

**L3 — Tool layer (pure functions, deterministic)**

*Physics tools*
- AC load flow (Newton-Raphson)
- Optimal power flow (OPF)
- N-1 contingency scan
- Frequency response simulation
- Short-circuit calculation
- State estimation (returns value ± uncertainty bounds — agents must use the bounds, not just the point estimate)

*Market tools*
- Merit-order dispatch
- Redispatch cost calculation
- Balancing group check
- Interconnect schedule
- Reserve adequacy check
- Imbalance pricing

*Forecast tools*
- 15-minute load forecast
- Wind/solar nowcast
- Ramp event detector
- Day-ahead schedule optimisation
- Temperature → demand model
- EV/flexible load model

**L4 — MCP integrations**
- `SCADA MCP` — live RTU telemetry (simulated from dataset in test environment)
- `ENTSO-E MCP` — cross-border flow data
- `Weather MCP` — ČHMÚ forecast feed
- `OTE / PXE MCP` — spot and balancing market data

**Human override rail**
Any action tagged `EXEC` (close breaker, issue redispatch order, curtail generator) requires explicit operator confirmation. Full opencode session trace is the audit log.

---

## Operating modes

Agents run in three temporal modes, not one:

**Day-ahead planning (D-1)**
Runs once per simulated day. Coordinator receives 24h forecasts → runs OPF → N-1 scan must pass → schedule locked. Output: committed hourly generation schedule per region.

**Intraday adjustment (every 15 minutes)**
Actual values for elapsed hours are released. Each regional agent compares actuals to schedule, decides whether to redispatch locally or request inter-regional support via peer bus.

**Real-time dispatch (each hourly step)**
SCADA MCP delivers current snapshot. Agents respond to frequency deviations, branch overloads, voltage violations. Speed matters here — agents should pattern-match to pre-computed contingency responses, not deliberate.

---

## Test environment

### Dataset available

| # | Dataset | Size | Role in simulation |
|---|---|---|---|
| 1 | Network snapshots | 8,760 pandapower JSON files | Ground truth oracle — load flow validation after every agent action |
| 2 | Static network topology | CSV | Initialises SCADA MCP: buses, branches, generators, loads, coordinates |
| 3 | Realtime generator output | 244 MB CSV, 322 generators | Withheld from agents; revealed as SCADA actuals at correct timestep |
| 4 | Realtime load demand | 43 MB CSV, 91 loads | Same — agents must forecast first, then see actuals |
| 5 | Day-ahead load forecasts | Per-region R1/R2/R3 | What agents actually receive at D-1; intentionally imperfect |
| 6 | Day-ahead solar forecasts | 75 solar units | Fed to forecast tools, not actuals |
| 7 | Day-ahead wind forecasts | 17 wind units | Fed to forecast tools, not actuals |
| 8 | Fuel prices | Monthly by fuel type & region | Feeds merit-order dispatch in market tools |

**Critical rule:** agents never see datasets 3 or 4 in advance. They receive forecasts (5/6/7), then actuals are revealed hour by hour as the simulation clock advances.

### Simulation loop (per hour)

1. **Phase 1 — D-1 planning** (once/day): release next 24h forecasts → coordinator produces schedule → N-1 gate → lock schedule
2. **Phase 2 — Intraday update**: release actuals for elapsed hours → regional agents reconcile deviation → peer bus negotiation if needed
3. **Phase 3 — Real-time dispatch**: SCADA MCP delivers current snapshot → agents respond to violations
4. **Phase 4 — Scoring**: apply agent decisions to pandapower network → solve load flow → compare against ground-truth snapshot → record delta

### Implementation stack

- **Simulator**: Python service (pandapower-native). Exposes two endpoints:
  - `step(hour)` → returns observation bundle: topology, SCADA readings, forecasts for that hour
  - `evaluate(actions)` → applies agent decisions, solves load flow, returns scored result
- **Data layer**: load datasets 3 and 4 into a local database at startup, indexed by hour and ID — do not parse CSV during simulation steps
- **Agents**: call tools which call the simulator API. Agents never touch pandapower directly.

### Scoring metrics

*Physical validity (binary per hour)*
- Did load flow converge after AI decisions?
- Any branch loadings above thermal limit?
- Any bus voltages outside ±5% nominal?

*Operational quality*
- Generation/load balance (proxy for frequency deviation from 50 Hz)
- Total redispatch volume vs optimal OPF baseline
- Schedule adherence: AI schedule vs ground-truth OPF solution

*Forecast exploitation*
- Compare AI performance against naive baseline (repeat yesterday's schedule)
- If AI does not meaningfully beat naive baseline, forecast integration is broken

### Scenario injection (stress tests)

Beyond passive replay, inject these events:
- **Generator trip**: zero out a generator mid-hour in SCADA feed; verify agents cover deficit
- **Forecast error**: replace wind forecast with value 30% above actual; verify agents recover when ramp doesn't materialise
- **Branch trip**: remove a line from topology mid-hour; verify pre-computed N-1 response activates

### Full-year replay target

Run all 8,760 hours unattended. Aggregate: fraction of hours with physically valid outcomes, worst voltage/loading violations, performance degradation by time-of-year (winter morning peaks, summer solar ramps, low-wind weekends). A system that scores well on average but fails catastrophically on specific hours is not ready for autopilot.

---

## Key design rules (do not compromise)

1. Tools are pure functions. Agents reason about tool outputs — they never estimate what a tool would return.
2. Tools must return uncertainty bounds, not just point estimates. State estimation always has measurement error.
3. N-1 security is a constraint on the schedule, not a post-hoc check.
4. The peer bus is read-only telemetry + typed negotiation messages. Agents do not issue commands to each other.
5. Coordinator authority is hierarchical and final. Regional agents cannot override it.
6. Agents are initialised with regional character (generation mix, demand profile) — this context shapes their reasoning without hardcoding rules.

# AthenaAI - Czech Grid AI Operator Bootstrap

## Overview

AthenaAI is an autonomous AI system for operating the Czech Republic power grid, built on OpenCode with MCP-first integration.

## Project Structure

```
AthenaAI/
├── pyproject.toml              # Python project configuration
├── opencode/
│   ├── opencode.jsonc          # OpenCode agent configuration
│   └── package.json            # Node.js dependencies (if any)
├── athenaai/
│   ├── __init__.py             # Package exports
│   ├── config.py               # Centralized configuration (model, paths, agents)
│   ├── peer_bus.py             # MCP-first peer-to-peer message bus
│   ├── agents.py               # Agent prompts and configurations
│   ├── wrapper.py              # Headless OpenCode wrapper
│   └── tools/
│       ├── __init__.py
│       └── physics.py          # 19 placeholder deterministic tool APIs
├── run_simulation.py           # Simulation entry point
└── tests/
    ├── conftest.py             # Pytest fixtures
    ├── test_config.py          # Configuration and model consistency tests
    ├── test_agents.py          # Agent prompt and definition tests
    ├── test_peer_bus.py        # Peer bus message tests
    ├── test_tools.py           # Tool API structure tests
    ├── test_wrapper.py         # Headless wrapper tests
    └── test_timestamp_propagation.py  # Simulation time tests
```

## Prerequisites

- **Python 3.10+** (3.11 or 3.12 recommended)
- **pip** and **venv**
- **An OpenCode API key** for the LLM backend that drives agent decisions
- **Dataset**: The ČEPS 2026 grid dataset. Default location is `../../dataset/greenhack-2026-ČEPS-dataset/` relative to this directory, configurable via `ATHENAAI_DATASET_ROOT`.

## Installation

### 1. Create and activate a virtual environment

```bash
cd AI/AthenaAI
python3 -m venv .venv
source .venv/bin/activate        # Bash/Zsh
# On Windows: .venv\Scripts\activate
```

### 2. Install the package

Core simulator and agent dependencies:

```bash
pip install -e .
```

For physics (pandapower load flow, N-1 contingency scans):

```bash
pip install -e ".[physics]"
```

For the full stack including market data and forecast models:

```bash
pip install -e ".[full]"
```

Dev dependencies (pytest, mypy, ruff) are in the `dev` extra:

```bash
pip install -e ".[dev]"
```

### 3. Set environment variables

Create a `.env` file in `AI/AthenaAI/` (already gitignored):

```bash
OPENCODE_GO_API_KEY=your-key-here
```

Optional overrides:

| Variable | Default | Purpose |
|---|---|---|
| `OPENCODE_GO_API_URL` | `https://opencode.ai/zen/go/v1` | OpenCode-compatible API base URL |
| `ATHENAAI_DATASET_ROOT` | `../../dataset/greenhack-2026-ČEPS-dataset` | Path to the grid dataset |
| `ATHENAAI_TRACE` | unset | Set to `1` to enable verbose function-level trace logging |

The `.env` file is loaded automatically by `python-dotenv` on import.

### 4. Verify the install

```bash
python3 -m compileall -q athenaai tests
python3 -c "import athenaai; print('Import OK')"
```

## Configuration

### API Key

The OpenCode API key is read from the `OPENCODE_GO_API_KEY` environment variable. Set it before running:

```bash
export OPENCODE_GO_API_KEY="your-key-here"
```

**Never hardcode API keys in tracked files.**

### Model Configuration

All agents use the `deepseek-v4-pro` model (overridable at runtime), centralized in `athenaai/config.py` via `KIMI_K2_6_MODEL`.

### OpenCode Config

The OpenCode configuration is at `./AthenaAI/opencode/opencode.jsonc`. It includes:
- Centralized model identifier
- Agent definitions (coordinator, regional agents, oracle)
- MCP server placeholders
- Simulation configuration

## Running the Simulator

The entry point is `run_simulation.py`. It runs a synchronous hour-by-hour simulation loop where agents observe grid state, propose actions, and those actions are validated against physics.

### Basic run (hours 0 through 24)

```bash
python run_simulation.py
```

### CLI flags

| Flag | Default | Description |
|---|---|---|
| `--start-hour` | `0` | First hour to simulate |
| `--end-hour` | `24` | Last hour (exclusive). Max range is 24 hours from `--start-hour` |
| `--model` | *(config default)* | Override the model for **all** agents |
| `--coordinator-model` | *(config default)* | Override only the coordinator agent model |
| `--regional-model` | *(config default)* | Override all regional agent models |
| `--oracle-model` | *(config default)* | Override only the oracle agent model |
| `--bohemia-west-model` | *(config default)* | Override a single regional agent |
| `--bohemia-east-model` | *(config default)* | Override a single regional agent |
| `--moravia-model` | *(config default)* | Override a single regional agent |
| `--silesia-model` | *(config default)* | Override a single regional agent |
| `--no-stop-on-failure` | off | Continue simulating after a failed hour instead of stopping |
| `--allow-fallback-physics` | off | Accept deterministic fallback load-flow results when pandapower is unavailable |
| `--full-n1-scan` | off | Run every N-1 contingency instead of stopping at the first violation |
| `--dataset-root` | *(config default)* | Override the dataset root path |
| `--quiet` | off | Suppress hour-by-hour progress output |
| `--verbose-agent-logs` | off | Print every agent response, model choice, and action summary |
| `--tui` | off | Show a live terminal dashboard (requires a TTY) |
| `--tui-lines` | `30` | Max lines in the TUI dashboard |
| `--trace-functions` | off | Verbose function-level trace to stderr (also enabled by `ATHENAAI_TRACE=1`) |
| `--agent-output-only` | off | Print only agent reasoning/action lines and audit events; suppress progress and summary |
| `--agent-output-log` | `logs/agent-output-YYYYMMDD-HHMMSS.log` | Path for the agent output log file |

### Examples

Run hours 6 through 18 with a specific model, continuing past failures:

```bash
python run_simulation.py \
  --start-hour 6 \
  --end-hour 18 \
  --model deepseek-v4-flash \
  --no-stop-on-failure
```

Benchmark the coordinator with a different model while keeping regional agents on the default:

```bash
python run_simulation.py \
  --coordinator-model gpt-4.1-mini \
  --verbose-agent-logs
```

Capture agent output to a file for post-run analysis:

```bash
python run_simulation.py \
  --agent-output-only \
  --agent-output-log logs/benchmark-run-001.log
```

### Async mode

An async variant is available for concurrent agent execution. It uses the same flags:

```bash
python -m athenaai.run_simulation_async
```

Or, if you prefer running the async entry point directly, the `main_async()` function in `run_simulation.py` can be invoked. The CLI flags are identical to the synchronous version.

## Benchmarking

### Key metrics

After a simulation run, the summary prints:

- **Total hours**: Number of hours the simulator attempted
- **Failed hours**: Count and list of hours where physics validation or N-1 security failed
- **Replay coverage**: Percentage of attempted hours that passed all checks
- **Missing gen hours**: Hours skipped due to missing generator data in the dataset

The return dict from `run_simulation()` also contains:

| Key | Type | What it measures |
|---|---|---|
| `replay_coverage_percent` | `float` | Passed hours / attempted hours * 100 |
| `failed_hours` | `list[int]` | Hour indices where the step failed |
| `results` | `list[dict]` | Per-hour detail: observation, agent responses, evaluation results, N-1 status |
| `audit_logs` | `list` | Full audit trail |
| `agent_work_logs` | `list` | Per-agent reasoning and action logs |
| `agent_output_log_path` | `str` | Path to the written log file |
| `missing_gen_hours` | `list[int]` | Hours skipped due to missing data |

### Per-hour result structure

Each entry in `results` contains:

- `hour_index` and `timestamp`: Simulation time
- `observation`: Grid state snapshot (generation, load, frequency, violations)
- `agent_responses`: What each agent decided and why
- `evaluation_results`: Whether actions were accepted and load-flow convergence
- `n1_passed`: Whether the N-1 contingency scan passed
- `n1_violations`: Which contingencies failed (if any)
- `step_failed`: Boolean indicating overall hour success

### Benchmark workflow

1. **Run the baseline** with default model settings:

   ```bash
   python run_simulation.py --end-hour 24
   ```

2. **Run with model overrides** to compare agent quality:

   ```bash
   python run_simulation.py --end-hour 24 --model <alternative-model>
   ```

3. **Compare metrics**: Look at `replay_coverage_percent` and `failed_hours` across runs. Higher coverage and fewer failed hours mean better agent decisions.

4. **Inspect agent logs**: The `--agent-output-log` file captures per-hour agent reasoning, tool calls, and action proposals. Use it to understand *why* a particular hour failed.

5. **Full N-1 audit**: For a thorough security check, run with `--full-n1-scan` to enumerate all contingencies rather than stopping at the first violation:

   ```bash
   python run_simulation.py --end-hour 24 --full-n1-scan --no-stop-on-failure
   ```

## Running Tests

```bash
# All tests
pytest tests/ -v

# With coverage
pytest tests/ --cov=athenaai --cov-report=term-missing

# Specific test file
pytest tests/test_config.py -v
```

### Compile check (without pytest)

```bash
python3 -m compileall -q athenaai tests
python3 -c "import athenaai; print('Import OK')"
```

## Troubleshooting

| Problem | Fix |
|---|---|
| `Dataset root not found` | Set `ATHENAAI_DATASET_ROOT` or place the dataset at the default path |
| `OpenCode config not found` | Ensure `opencode/opencode.jsonc` exists under `AI/AthenaAI/` |
| `ModuleNotFoundError: pandapower` | Install physics extras: `pip install -e ".[physics]"` |
| API key errors | Check that `OPENCODE_GO_API_KEY` is set in `.env` or your shell environment |
| Missing generator actuals warnings | Some hours lack data in the dataset; those hours are skipped automatically |

## Agent Architecture

### Coordinator (coordinator)
- ČEPS-level authority
- Day-ahead schedule approval
- N-1 contingency scanning (hard gate)
- Cross-border management (DE, AT, SK, PL)
- Conflict arbitration

### Regional Agents
- **bohemia-west**: Nuclear-heavy (Temelín, Dukovany), coal (Prunéřov)
- **bohemia-east**: Prague load centre
- **moravia**: Flexibility provider (gas peakers, Dalešice hydro)
- **silesia**: Industrial demand, cross-border Poland

### Oracle (oracle)
- Read-only diagnostic consultant
- Architectural guidance
- Debugging assistance

## Tool Categories

### Physics Tools (6)
AC Load Flow, Optimal Power Flow, N-1 Contingency Scan, Frequency Response, Short-Circuit, State Estimation

### Market Tools (6)
Merit-Order Dispatch, Redispatch Cost Calculation, Balancing Group Check, Interconnect Schedule, Reserve Adequacy Check, Imbalance Pricing

### Forecast Tools (7)
15-Minute Load Forecast, Wind Nowcast, Solar Nowcast, Ramp Event Detector, Day-Ahead Schedule Optimisation, Temperature-to-Demand, EV/Flexible Load Model

## Simulation

The `SimulationClock` runs with 15-minute steps. Agents are always informed of simulated time via `AgentContext`.

## Phase 2.1 Scope

- OpenCode environment setup ✓
- Agent prompts (ASD/OhMyOpenCode style) ✓
- MCP-first peer-bus scaffold ✓
- Placeholder deterministic tool APIs ✓
- Headless Python wrapper ✓
- Exhaustive unit tests ✓

**NOT included in Phase 2.1**: Full physics (pandapower), actual market logic, TimesFM forecast integration. These come in Phase 2.2+.

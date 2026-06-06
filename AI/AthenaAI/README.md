# AthenaAI Phase 2.1 - Czech Grid AI Operator Bootstrap

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
└── tests/
    ├── conftest.py             # Pytest fixtures
    ├── test_config.py          # Configuration and model consistency tests
    ├── test_agents.py          # Agent prompt and definition tests
    ├── test_peer_bus.py        # Peer bus message tests
    ├── test_tools.py           # Tool API structure tests
    ├── test_wrapper.py         # Headless wrapper tests
    └── test_timestamp_propagation.py  # Simulation time tests
```

## Running Tests

### Prerequisites

Python 3.10+ is required. Create a virtual environment and install dependencies:

```bash
cd AthenaAI
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -e ".[dev]"   # Install package with dev dependencies
```

Or install test dependencies directly:

```bash
pip install pytest pytest-asyncio
```

### Run Tests

```bash
# Run all tests
cd AthenaAI
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=athenaai --cov-report=term-missing

# Run specific test file
pytest tests/test_config.py -v
```

### Compile Check (without pytest)

If pytest is not available, you can still verify syntax:

```bash
cd AthenaAI
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

All agents use the `kimi-k2.6` model, centralized in `athenaai/config.py` via `KIMI_K2_6_MODEL`.

### OpenCode Config

The OpenCode configuration is at `./AthenaAI/opencode/opencode.jsonc`. It includes:
- Centralized model identifier
- Agent definitions (coordinator, regional agents, oracle)
- MCP server placeholders
- Simulation configuration

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
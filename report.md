# Grid Pulse Dashboard — Deep Research Report

## Table of Contents
1. [What a Grid Operator Actually Does](#1-what-a-grid-operator-actually-does)
2. [Operator Pain Points & Challenges](#2-operator-pain-points--challenges)
3. [Dashboard Design Best Practices](#3-dashboard-design-best-practices)
4. [GreenHack 2026 "Grid Pulse" Challenge Details](#4-greenhack-2026-grid-pulse-challenge-details)
5. [AI/ML Models for Forecasting](#5-aiml-models-for-forecasting)
6. [All Available Data Sources for CZ](#6-all-available-data-sources-for-cz)
7. [What to Build in the Dashboard](#7-what-to-build-in-the-dashboard)
8. [Recommended Tech Stack](#8-recommended-tech-stack)
9. [Key GitHub Repos & Libraries](#9-key-github-repos--libraries)
10. [Sources & References](#10-sources--references)

---

## 1. What a Grid Operator Actually Does

### Main Roles in a TSO Control Room

| Role | Responsibility |
|------|----------------|
| **Dispatcher** | Real-time balance between supply and demand, frequency control, voltage management, emergency handling |
| **Balancing Operator** | Power balance using aFRP, mFRP, reserve activation |
| **Network Analyst** | Contingency analysis, redispatching simulations, operational situation evaluation |
| **Operational Planner** | Day-ahead planning, DACF modelling, outage coordination |
| **Trading Coordinator** | Cross-border exchange schedules, emergency assistance requests |

### Typical Shift & Hourly Decisions

Dispatch control has three phases:
1. **Operational planning** (day-ahead)
2. **Real-time control** (continuous)
3. **Operational evaluation** (post-event)

**Hourly decisions include:**
- Monitoring expected load on the power system
- Checking scheduled cross-border exchanges
- Reviewing current status of purchased ancillary services
- Activating regulation energy when supply-demand imbalance occurs
- Managing power flows and voltage within the transmission system
- Executing simulation calculations before taking actions (e.g., tripping a power line)
- Coordinating with neighbouring TSOs on cross-border flows

### Critical Situations Handled

**Generation emergencies:**
- Unexpected weather changes
- Inaccurate load prediction
- Failures at generating plants
- Changes in cross-border exchanges

**Network management emergencies:**
- Power line overloading
- N-1 criterion violations
- Congestion on cross-border lines

**Emergency declarations (per Czech Energy Act):**
- Regulation stages: Basic → Alert → Emergency
- Frequency Maintenance Schedule
- Switching-off Schedule
- Consumption Regulation Schedule

### Tools & Software Used

| Vendor | Product | Notes |
|--------|---------|-------|
| Siemens | Spectrum Power | Widely used in European TSOs |
| ABB | ABB Ability Network Manager | Formerly ABB MicroSCADA |
| GE Grid Solutions | e-terra | Used by many North American ISOs |
| Schneider Electric | EcoStruxure ADMS | Primarily for DSOs |
| ETAP | Real-Time | Power system analysis |
| OSIsoft (AVEVA) | PI System | Data historian |

### At-a-Glance vs Deep-Dive Information

**At-a-glance (continuous monitoring):**
- System frequency (target: 50 Hz)
- Total generation vs. consumption
- Cross-border exchange flows
- Transmission line loading percentages
- Voltage levels at key substations
- Active ancillary services status
- Alarm status

**Deep-dive (analysis/simulation):**
- Contingency analysis results
- Power flow calculations
- Redispatching scenarios
- Network reconfiguration options
- Historical trend analysis
- Forecast models

### Main KPIs Monitored Continuously

| Category | KPIs |
|----------|------|
| **Frequency** | Frequency deviation from 50 Hz, FCP/aFRP/mFRP activation |
| **Power balance** | Real-time supply-demand balance, cross-border exchange compliance, imbalance volume |
| **Voltage** | Voltage levels at pilot nodes, reactive power balance, SVQC performance |
| **Reliability** | N-1 criterion compliance, transmission capacity utilization, SAIDI/SAIFI |

### Decision-Making During Grid Emergency

1. **Detection** — Contingency analysis detects potential N-1 violations
2. **Assessment** — Dispatcher evaluates severity using simulation tools
3. **Preventive action** — Redispatching, reconfiguration, or ancillary service activation
4. **Emergency declaration** — If preventive measures insufficient
5. **Restoration** — If blackout occurs: black start, island operation, gradual restoration

### International Coordination

| Organization | Role |
|--------------|------|
| **ENTSO-E** | European network codes, operation handbook, regional coordination |
| **IGCC** | 21 TSOs from 18 countries, imbalance netting in real-time |
| **TSC/TSCNET** | Regional security coordination |
| **CEE TSO** | Central East European TSO cooperation |
| **4M Market Coupling** | CZ-SK-HU-RO cross-border market integration |

### System Services Procured

| Service | Response Time | Description |
|---------|---------------|-------------|
| FCP (Frequency Containment Process) | 30 seconds | Primary control, automatic |
| aFRR (Automatic Frequency Restoration) | 5-10 minutes | Secondary control, automatic |
| mFRR5 (Manual Frequency Restoration 5min) | 5 minutes | Tertiary control, manual |
| mFRR15+ (Manual Frequency Restoration 15min+) | 15 minutes | Manual activation |
| mFRR15- (Manual Frequency Restoration 15min-) | 15 minutes | Negative reserves |
| SVQC (Secondary Voltage & Reactive Power Control) | — | Voltage support |
| Black Start Capability | — | Generator starts without external power |
| Island Operation Capability | — | Supplying isolated system parts |

---

## 2. Operator Pain Points & Challenges

### Biggest Challenges Today

**Renewable Integration:**
- Higher volatility and reduced system strength
- 70% of new renewable capacity connects to distribution grids (TSO-DSO coordination challenge)
- Inverter-based resources create reduced inertia, new oscillatory phenomena, and network congestion

**Aging Infrastructure:**
- Major incidents documented: Jan 2021 CE separation, Jul 2021 Iberia separation, Jun 2024 SE Europe incident, Apr 2025 Spain/Portugal incident

**Cybersecurity:**
- ENTSO-E developed dedicated Network Code on Cybersecurity (NCCS)
- NIST published "Situational Awareness for Electric Utilities" guide

**Data Overload:**
- "Higher volumes of information (that might be contradicting) and shorter decision times are difficult to reconcile" — Val Escudero et al., CIGRE Green Book, 2024

### Information Operators Struggle to Get

- **Real-time state of neighboring control areas** — need awareness beyond own control area
- **Distributed energy resources (DERs) visibility** — limited insights into DER activity
- **Low-voltage grid utilization** — lack of transparency about utilization
- **Three-state gap** — actual state ≠ presented state (screens) ≠ perceived state (operator understanding)
- **Dynamic system behavior** — system inertia, RoCoF, voltage trajectories, oscillatory phenomena
- **State estimator failures** — 2003 Northeast USA blackout: failures in state estimator and alarm processing

### Common Operator Errors

- **Inadequate situational awareness** — contributing factor in major blackouts (2003 USA, 2003 Italy, 2006 Europe, 2011 Arizona)
- **Alarm flooding** — hundreds of simultaneous alarms during emergencies without effective prioritization
- **Out-of-the-loop problem** — dependency on automated tools reduces ability to respond when automation fails

### How the Role is Changing with Renewables

- **From centralized to decentralized** — many small generators instead of few large ones
- **Bidirectional power flows** — traditional unidirectional flow replaced by bidirectional
- **Reduced system inertia** — inverter-based resources don't provide rotational inertia
- **Shorter decision times** — more entities to monitor, faster decisions needed
- **Weather dependency** — renewables are intermittent and weather-driven

### New Capabilities Needed

- **Look-ahead security assessment** — identify critical situations ahead of time
- **Dynamic security assessment (DSA)** — moving from static to real-time
- **Wide Area Monitoring, Protection and Control (WAMPAC)** — CIGRE TB 917
- **Grid-forming converter capabilities** — ENTSO-E 2022 report

---

## 3. Dashboard Design Best Practices

### Color Schemes for Grid Elements

**Voltage Levels:**
| Voltage Level | Color | Hex |
|---------------|-------|-----|
| Extra High Voltage (380kV+) | Deep Red | `#8B0000` |
| High Voltage (110-220kV) | Orange | `#FF8C00` |
| Medium Voltage (10-35kV) | Yellow | `#FFD700` |
| Low Voltage (<1kV) | Green | `#228B22` |

**Loading States:**
| Loading State | Color | Hex |
|---------------|-------|-----|
| Normal (<70%) | Green | `#4CAF50` |
| Elevated (70-85%) | Yellow/Amber | `#FF9800` |
| High (85-95%) | Orange | `#FF5722` |
| Critical (>95%) | Red | `#F44336` |
| Overloaded (>100%) | Flashing Red | `#D32F2F` |

**Alert Levels (ISA-18.2 / IEC 62682):**
| Priority | Color | Visual |
|----------|-------|--------|
| Critical (P1) | Red `#F44336` | Flashing + audible |
| High (P2) | Orange `#FF9800` | Flashing |
| Medium (P3) | Yellow `#FFC107` | Solid |
| Low (P4) | Blue `#2196F3` | Solid |
| Information | Gray `#9E9E9E` | Subtle |

### Layout: Hierarchical Multi-Screen Architecture

```
Level 1: System Overview (Single Screen)
├── Geographic/Schematic map view
├── Key performance indicators (KPIs)
├── Active alarm summary
└── System status indicators

Level 2: Area/Zone Views (Multiple Screens)
├── Regional grid sections
├── Substation details
├── Generation unit status
└── Load distribution

Level 3: Equipment Detail (Drill-down)
├── Individual equipment faceplates
├── Historical trends
├── Diagnostic data
└── Control interfaces
```

### Information Hierarchy

1. **Critical Alerts** (Top 10%) — Always visible
2. **System Status** (Next 20%) — Key metrics at a glance
3. **Process Overview** (Middle 40%) — Main visualization area
4. **Supporting Data** (Bottom 20%) — Detailed information
5. **Navigation** (Bottom 10%) — Menu and controls

### Chart Types for Power System Data

| Data Type | Best Chart | Alternative |
|-----------|------------|-------------|
| Generation Mix | Stacked Area | Sankey Diagram |
| Load Flow | Sankey Diagram | Chord Diagram |
| Grid Topology | Single-Line Diagram | Network Graph |
| Time Series | Line Chart | Area Chart |
| Geographic Data | Choropleth Map | Heatmap |
| Capacity vs Demand | Bar Chart | Gauge Chart |
| Voltage Profiles | Line Chart with Bands | Contour Plot |
| Contingency Analysis | Spider/Radar | Parallel Coordinates |

### Geographic vs Schematic Views

| Aspect | Geographic View | Schematic View |
|--------|-----------------|----------------|
| Best For | Spatial relationships, field operations | Logical understanding, control room |
| Accuracy | Geographically precise | Topologically clear |
| Use Case | Outage management, field dispatch | System control, load balancing |

**Recommendation:** Provide both views with synchronized navigation

### Thresholds (NERC/IEC Standards)

| Parameter | Normal | Alert | Alarm | Critical |
|-----------|--------|-------|-------|----------|
| Frequency | 49.95-50.05 Hz | 49.90-49.95 Hz | 49.50-49.90 Hz | <49.50 Hz |
| Voltage | ±5% nominal | ±5-10% | ±10-15% | >±15% |
| Loading | <80% | 80-90% | 90-100% | >100% |

### Visualizing Forecast Uncertainty

| Method | Best For |
|--------|----------|
| Fan Charts | Demand forecasts, price projections |
| Confidence Intervals | Generation forecasts |
| Probability Cones | Storm/outage paths |
| Ensemble Plots | Multiple scenarios |
| Box Plots | Statistical distributions |

### Tooltips vs Dedicated Panels

**Tooltips:** Current value, unit, status, timestamp, min/max (last 24h)
**Dedicated Panels:** Historical trends, diagnostics, related equipment, control interfaces, alarm history

### Real-Time Refresh Rates

| Data Type | Rate | Method |
|-----------|------|--------|
| Critical Alarms | 1-2 seconds | WebSocket push |
| Voltage/Current | 2-5 seconds | WebSocket push |
| Power Flow | 5-10 seconds | WebSocket push |
| Generation Mix | 15-60 seconds | Polling or push |
| Prices | 1-5 minutes | Polling |
| Weather | 5-15 minutes | Polling |

### Real-World Dashboard Examples

| Dashboard | URL | Key Feature |
|-----------|-----|-------------|
| Electricity Maps | app.electricitymaps.com | Real-time carbon intensity, dark theme, choropleth |
| SMARD.de | smard.de | German market data, interactive charts |
| RTE eco2mix | rte-france.com/eco2mix | French generation/consumption, clean design |
| National Grid ESO | nationalgrideso.com/data-portal | UK generation mix, live dashboard |

### Standards & References

- **ISA-101.01-2015** — Human Machine Interfaces for Process Automation Systems
- **ISA-18.2-2016** — Management of Alarm Systems for the Process Industries
- **IEC 62682** — Management of Alarm Systems
- **IEEE Std 315-1975** — Graphic Symbols for Electrical Diagrams
- **WCAG 2.1** — Web Content Accessibility Guidelines
- **NERC CIP** — Critical Infrastructure Protection Standards

---

## 4. GreenHack 2026 "Grid Pulse" Challenge Details

### What to Build

> "Build an AI-powered, visually strong map-based view of the power grid that turns complex data into clear insight — helping humans stay in control of a rapidly changing energy system."

**Key requirements:**
1. **AI-powered** — must incorporate artificial intelligence
2. **Visually strong** — emphasis on visual design quality
3. **Map-based view** — geographic/spatial representation of the power grid
4. **Complex data → clear insight** — data visualization and simplification
5. **Helping humans stay in control** — human-in-the-loop design, not full automation
6. **Rapidly changing energy system** — must handle dynamic, real-time or near-real-time data

### ČEPS Innovation Strategy Context

ČEPS identifies four priority fields relevant to Grid Pulse:
1. **Dispatch control** — AI/ML for decision support, data filtering, automation
2. **TS equipment operation** — lifecycle management
3. **TS development** — new materials, cybersecurity, data exchange with DSOs
4. **Markets and flexibility** — new sources, technologies, flexibility knowledge

**Key quote from ČEPS:** "Future time for control room operators' decision making will become shorter while there will be a greater number of entities connected to the grid... necessary to automate some processes, filter and preprocess data, and present the data to the control room operator together with proposed actions (based on machine learning and artificial intelligence)"

### ČEPS Existing Infrastructure

- **45 substations** with 79 transformers
- ~6,000 km of 400 kV and 220 kV power lines
- **Hosting Capacity Map** — ArcGIS-based, color-coded (green/orange/red), updated monthly
- **Control Centre** in Prague (backup in Ostrava)
- **BAART** — Battery storage testing (4 MW, 2.8 MWh) at Tušimice
- **Dflex** — Demand-side flexibility aggregation
- **SecureFlex** — Analytical tools for safe power flexibility utilization

### Hackathon Timeline

| Date | Event |
|------|-------|
| 5 June, 08:45-09:30 | Registration |
| 5 June, 09:30-10:00 | Welcome & Keynotes |
| 5 June, 10:00-11:30 | Challenge presentations (ČEPS presents Grid Pulse) |
| 5 June, 11:30-12:00 | Mentor introduction |
| 5-6 June | Hacking |
| 6 June, 09:00-10:00 | Workshop: "How to pitch?" |
| 6 June, 11:00 | **Submissions deadline** |
| 6 June, 12:30-17:00 | Pitch session |
| 6 June, 17:30-18:30 | Winners announcement |

### Prizes

| Place | Prize |
|-------|-------|
| 1st Place | 2,000 € |
| 2nd Place | 1,000 € |
| 3rd Place | 500 € |
| ČEPS Prize | MetaQuest VR Glasses |

### Deliverables

- Working prototype/demo
- Pitch presentation (delivered during 12:30-17:00 window on Saturday)

---

## 5. AI/ML Models for Forecasting

### Foundation Models Comparison

| Model | Provider | Params | Max Context | Multivariate | Covariates | License | Install |
|-------|----------|--------|-------------|--------------|------------|---------|---------|
| **TimesFM 2.5** | Google | 200M | 16,384 | No (univariate) | Yes (XReg) | Apache 2.0 | `pip install timesfm` |
| **Chronos-2** | Amazon | 120M | ~512 | Yes | Yes | Apache 2.0 | `pip install chronos-forecasting` |
| **TimeGPT** | Nixtla | Closed | Varies | Yes | Yes | Closed | `pip install nixtla` |
| **Lag-Llama** | Morgan Stanley | ~15M | 32-1024 | No | No | Apache 2.0 | `pip install lag-llama` |
| **MOMENT** | CMU | ~300M | 512 | Yes | No | MIT | `pip install momentfm` |
| **Moirai** | Salesforce | Various | Varies | Yes | Yes | Apache 2.0 | `pip install uni2ts` |

### TimesFM 2.5 Details

- **Architecture:** Decoder-only transformer, patch-based (patch length 32)
- **Pre-trained on:** 10 billion time points from diverse domains
- **Version history:** 1.0 (200M, 512 ctx) → 2.0 (500M, 2048 ctx) → 2.5 (200M, 16384 ctx)
- **Key capabilities:** Zero-shot forecasting, any horizon, any granularity, covariates via XReg, quantile forecasts (10th-90th), LoRA fine-tuning
- **Accuracy:** #1 on GIFT-Eval benchmark, 15-20% RMSE improvement for energy demand (Frontiers study, Feb 2026)
- **Code example:**

```python
import torch
import numpy as np
import timesfm

model = timesfm.TimesFM_2p5_200M_torch.from_pretrained(
    "google/timesfm-2.5-200m-pytorch"
)
model.compile(timesfm.ForecastConfig(
    max_context=1024,
    max_horizon=24,
    normalize_inputs=True,
    use_continuous_quantile_head=True,
    force_flip_invariance=True,
    infer_is_positive=True,  # Load is always >= 0
    fix_quantile_crossing=True,
))

point_forecast, quantile_forecast = model.forecast(
    horizon=24,
    inputs=[load_data],  # hourly load array
    freq=[0],  # 0 = hourly
)
```

### Chronos-2 Details

- **Architecture:** T5 (encoder-decoder) for v1; Patch-based for Chronos-Bolt/Chronos-2
- **Key feature:** Multivariate support, covariate integration
- **Latest:** Chronos-2 (Oct 2025) — close #2 on GIFT-Eval
- **Code example:**

```python
from chronos import Chronos2Pipeline
pipeline = Chronos2Pipeline.from_pretrained("amazon/chronos-2", device_map="cuda")
pred_df = pipeline.predict_df(
    context_df, future_df=future_df,
    prediction_length=24, quantile_levels=[0.1, 0.5, 0.9],
    id_column="id", timestamp_column="timestamp", target="target",
)
```

### TimeGPT Details

- **Key feature:** Easiest to use (3 lines of code), API-based (no GPU needed)
- **Also supports:** Anomaly detection, cross-validation
- **Code example:**

```python
from nixtla import NixtlaClient
nixtla_client = NixtlaClient(api_key='YOUR_API_KEY')
fcst_df = nixtla_client.forecast(df, h=24, level=[80, 90])
anomalies_df = nixtla_client.detect_anomalies(df)
```

### Recommendation

1. Start with **TimesFM 2.5 zero-shot** on hourly load data
2. Add **covariates** (temperature, day-of-week, holidays) via XReg
3. If multivariate interactions are critical, try **Chronos-2**
4. Consider **TimesFM-ICF** (in-context fine-tuning) for +6.8% improvement without retraining

### Solar/Wind Forecasting

| Project | Description | GitHub |
|---------|-------------|--------|
| Open Climate Fix Quartz Solar | Open-source site-level solar forecast | openclimatefix/open-source-quartz-solar-forecast |
| PVNet | National GSP PV forecasting | openclimatefix/pvnet |
| MetNet | PyTorch MetNet/MetNet-2 | openclimatefix/metnet |
| Atlite | Weather data → renewable power potentials | PyPSA/atlite |

---

## 6. All Available Data Sources for CZ

### Primary Sources (Machine-Readable, API)

| Source | Data | Access | Priority |
|--------|------|--------|----------|
| **ENTSO-E** | Load, generation by type, prices, cross-border flows, balancing | `entsoe-py` API (free key) | **HIGH** |
| **ČEPS** | Load, generation, RES, imbalances, frequency, flows | Web portal + SOAP API | **HIGH** |
| **OTE** | Day-ahead prices (CZK/EUR), imbalance settlement, load profiles | Web portal | **HIGH** |
| **Open-Meteo** | Temperature, wind, solar radiation, cloud cover | REST API (free, no key) | **HIGH** |
| **Electricity Maps** | Real-time carbon intensity for CZ | REST API | **HIGH** |

### Secondary Sources

| Source | Data | Access | Priority |
|--------|------|--------|----------|
| **OPSD** | Pre-processed load, solar, wind, prices (2015-2020) | CSV download | MEDIUM |
| **CZSO** | Annual/monthly production/consumption statistics | Database download | LOW |
| **JAO** | Cross-border capacity auction results | API + portal | MEDIUM |
| **WattTime** | Marginal emissions data | REST API | MEDIUM |
| **CHMI** | Czech-specific weather observations | Web portal | LOW |

### ENTSO-E via entsoe-py

```python
pip install entsoe-py

from entsoe import EntsoePandasClient
client = EntsoePandasClient(api_key='YOUR_KEY')

# CZ bidding zone code: 'CZ'
client.query_day_ahead_prices('CZ', start, end)      # Returns Series
client.query_load('CZ', start, end)                   # Returns DataFrame
client.query_generation('CZ', start, end)             # Returns DataFrame
client.query_crossborder_flows('CZ', 'DE_LU', start, end)  # Returns Series
client.query_imbalance_prices('CZ', start, end)       # Returns DataFrame
client.query_wind_and_solar_forecast('CZ', start, end)
```

### ČEPS Public Data Portal

**URL:** https://www.ceps.cz/en/all-data

**Datasets available (downloadable as TXT, CSV, XML):**
- Consumption (Load)
- Power balance
- Cross-border power flows
- Emergency exchange
- Generation plan
- Generation
- Generation RES
- Estimated imbalance price
- Unforeseeably rejected balancing capacity bids
- Activated power from balancing services
- Frequency
- Current imbalance in Czechia
- Maximum price of balancing capacity
- Emissions, % of renewable energy sources

**Date range:** 2010–present, hourly resolution

**Web Services API:** https://www.ceps.cz/en/web-services (SOAP, TLS 1.2 required)

### Open-Meteo API

```
https://api.open-meteo.com/v1/forecast?latitude=50.08&longitude=14.44&hourly=temperature_2m,wind_speed_10m,direct_radiation&timezone=Europe/Prague
```

**Variables:** Temperature (2m/80m/120m), wind speed/direction, solar radiation (GHI/DNI/DHI), cloud cover, precipitation, pressure, humidity

**Time resolution:** Hourly, 15-minutely (Central Europe), daily
**Forecast:** Up to 16 days
**Historical:** Available via Historical Weather API

---

## 7. What to Build in the Dashboard

### Layer 1 — Grid Visualization (from hackathon dataset)

- Interactive map with 118 buses (geodata), colored by voltage
- Line loading heatmap (177 lines, loading_percent)
- Transformer status (9 trafos)
- Click-to-inspect any element
- Generator locations and output

### Layer 2 — Real-Time Operations (from ENTSO-E + ČEPS)

- Live load, generation by type, frequency
- Cross-border flows (DE, SK, PL, AT)
- Day-ahead prices
- Balancing/imbalance data

### Layer 3 — AI Forecasting (TimesFM + Open-Meteo)

- Load forecast: next 24-48h with uncertainty bands
- Solar/wind forecast: weather-driven generation prediction
- Forecast vs actual comparison
- Anomaly detection alerts

### Layer 4 — Carbon & Costs (Electricity Maps + OTE)

- Real-time carbon intensity (gCO2/kWh)
- Generation cost by fuel type
- Emissions tracking

### Layer 5 — AI Assistant (LLM integration)

- Natural language grid state summaries
- Alert explanations
- Recommendations for operators

### AI Features to Implement

| Feature | Model/Tool | Description |
|---------|------------|-------------|
| Load Forecasting | TimesFM 2.5 | Zero-shot, 24h horizon, quantile bands |
| Solar/Wind Forecasting | Atlite + Open-Meteo | Weather-driven generation prediction |
| Anomaly Detection | Isolation Forest / TimeGPT | Unusual patterns in load/generation |
| Narrative Generation | LLM (GPT-4/Gemini) | "Grid is stable. Load peaked at 45,231 MW..." |
| Carbon Tracking | Electricity Maps API | Real-time gCO2/kWh |
| Optimization | PyPSA | Economic dispatch, OPF |

---

## 8. Recommended Tech Stack

```
Frontend:  React + TypeScript + Vite
Map:       Mapbox GL JS + react-map-gl
Overlay:   Deck.gl (arc layers, heatmaps)
Charts:    Plotly.js (react-plotly)
Routing:   react-router-dom
State:     React Context + hooks
Styling:   CSS modules or Tailwind (dark theme)
Data:      Static JSON (from hackathon dataset)
AI/ML:     TimesFM 2.5 (Python backend, later)
Grid Sim:  pandapower (power flow analysis)
Streaming: WebSocket (future real-time)
LLM:       GPT-4/Gemini for narrative generation
```

### Data Flow

```
┌─────────────────────────────────────────────────────┐
│                    Frontend (React)                   │
│                                                       │
│  ┌─────────┐   ┌──────────┐   ┌───────────────────┐ │
│  │ Sidebar │   │ GridMap  │   │ Charts / Panels   │ │
│  │ (nav)   │   │ (Mapbox) │   │ (Plotly)          │ │
│  └─────────┘   └────┬─────┘   └────────▲──────────┘ │
│                     │                   │             │
│              ┌──────▼───────────────────┘             │
│              │      useGridData (context)             │
│              │      - static topology                 │
│              │      - current snapshot                │
│              │      - forecasts                       │
│              └──────┬───────────────────┐             │
│                     │                   │             │
│              ┌──────▼─────┐    ┌───────▼──────┐      │
│              │ /data/*.json│    │  TimesFM     │      │
│              │ (static)    │    │  (Python API │      │
│              └─────────────┘    │   or local)  │      │
│                                 └──────────────┘      │
└─────────────────────────────────────────────────────┘
```

---

## 9. Key GitHub Repos & Libraries

### Core Power System Analysis
| Repo | Stars | Purpose |
|------|-------|---------|
| PyPSA/PyPSA | 2,000 | Python for Power System Analysis (MIT) |
| e2nIEE/pandapower | 1,200 | Power system modeling & analysis (BSD) |
| Grid2op/grid2op | 435 | RL testbed for power grid operations |
| SanPen/VeraGrid | 553 | Cross-platform power systems software with GUI |

### Time Series Foundation Models
| Repo | Stars | Purpose |
|------|-------|---------|
| google-research/timesfm | 20,500 | TimesFM 2.5 — Google's time series foundation model |
| amazon-science/chronos-forecasting | 5,400 | Chronos-2 — Amazon's pretrained forecasting models |
| Nixtla/nixtla | 3,900 | TimeGPT — Foundation model for forecasting & anomaly detection |

### Solar & Renewable Forecasting
| Repo | Stars | Purpose |
|------|-------|---------|
| openclimatefix/open-source-quartz-solar-forecast | 144 | Open-source solar site-level forecast |
| openclimatefix/pvnet | 54 | PV forecasting neural network |
| openclimatefix/metnet | 296 | PyTorch MetNet/MetNet-2 implementation |
| PyPSA/atlite | 389 | Weather data → renewable power potentials |

### Carbon & Emissions
| Repo | Stars | Purpose |
|------|-------|---------|
| electricitymaps/electricitymaps-contrib | 4,000 | Open-source electricity data parsers |

### Grid Visualization
| Repo | Stars | Purpose |
|------|-------|---------|
| open-energy-transition/MapYourGrid | 93 | JavaScript-based grid mapping |
| open-energy-transition/grid2poster | 229 | Design posters showcasing electrical grids |
| openinframap/openinframap | — | Global infrastructure map including power grid |
| open-energy-transition/Awesome-Electrical-Grid-Mapping | 145 | Curated list of global grid maps |

### Python Packages to Install

```bash
# Core power system
pip install pypsa pandapower grid2op

# Time series forecasting
pip install timesfm chronos-forecasting nixtla

# Renewable potential
pip install atlite

# ML & anomaly detection
pip install scikit-learn xgboost lightgbm pyod

# Optimization solvers
pip install highspy  # HiGHS open-source solver

# Carbon tracking
pip install electricitymaps  # (community parsers)
```

---

## 10. Sources & References

### Academic Papers

| Paper | Authors | Year | Key Finding |
|-------|---------|------|-------------|
| "Situation awareness in power systems" | Panteli & Kirschen | 2015 | Seminal SA paper, 198 citations |
| "The effect of interactive analytical dashboard features" | Nadj, Maedche & Schieder | 2020 | What-if analysis improves performance but can reduce SA |
| "Visualization proposal for power system control rooms" | Betancur et al. | 2022 | Specific visualization techniques for control rooms |
| "Operational Decision Support Tools" | Val Escudero, Kelly & Liao | 2024 | CIGRE Green Book chapter on decision support |
| "A decoder-only foundation model for time-series forecasting" | Das et al. | 2024 | TimesFM paper (ICML) |
| "Chronos: Learning the Language of Time Series" | Ansari et al. | 2024 | Chronos paper |
| "TimeGPT-1" | Garza & Mergenthaler-Canseco | 2023 | TimeGPT paper |
| "GIFT-Eval: A Benchmark For General Time Series Forecasting" | Salesforce | 2024 | TimesFM 2.5 #1 by MASE |

### Industry Standards

| Standard | Description |
|----------|-------------|
| ISA-101.01-2015 | Human Machine Interfaces for Process Automation Systems |
| ISA-18.2-2016 | Management of Alarm Systems for the Process Industries |
| IEC 62682 | Management of Alarm Systems |
| IEEE Std 315-1975 | Graphic Symbols for Electrical Diagrams |
| WCAG 2.1 | Web Content Accessibility Guidelines |
| NERC CIP | Critical Infrastructure Protection Standards |

### Data Sources

| Source | URL |
|--------|-----|
| ENTSO-E Transparency | https://transparency.entsoe.eu/ |
| ČEPS All Data | https://www.ceps.cz/en/all-data |
| ČEPS Web Services | https://www.ceps.cz/en/web-services |
| OTE | https://www.ote-cr.cz/en |
| Open Power System Data | https://data.open-power-system-data.org/time_series/ |
| Open-Meteo | https://open-meteo.com/en/docs |
| Electricity Maps | https://app.electricitymaps.com/ |
| WattTime | https://watttime.org |
| Czech Statistical Office | https://csu.gov.cz/energy |
| JAO | https://www.jao.eu/ |

### Dashboard Examples

| Dashboard | URL |
|-----------|-----|
| Electricity Maps | https://app.electricitymaps.com |
| SMARD.de | https://www.smard.de |
| RTE eco2mix | https://www.rte-france.com/eco2mix |
| National Grid ESO | https://www.nationalgrideso.com/data-portal |
| ENTSO-E Grid Map | https://www.entsoe.eu/data/grid-map/ |
| ČEPS Hosting Capacity Map | https://www.ceps.cz/en/hosting-capacity-map |

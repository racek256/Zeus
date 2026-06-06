"""
FastAPI backend for serving grid topology and snapshot data.
IEEE-118 bus system from CEPS/GreenHack dataset.
"""

import json
import math
import os
import re
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

# --- Paths ---
DATA_DIR = Path(__file__).resolve().parent.parent / "dataset" / "greenhack-2026-ČEPS-dataset" / "data"
STATIC_DIR = DATA_DIR / "static"
SNAPSHOTS_DIR = DATA_DIR / "snapshots"

# --- Load static data at startup ---
buses_df = pd.read_csv(STATIC_DIR / "buses.csv")
branches_df = pd.read_csv(STATIC_DIR / "branches.csv")
gens_df = pd.read_csv(STATIC_DIR / "gens.csv")
loads_df = pd.read_csv(STATIC_DIR / "loads.csv")

# Build bus_name -> index mapping (bus_001 -> 0, bus_002 -> 1, ...)
bus_names = sorted(buses_df["bus_name"].tolist())
bus_name_to_idx = {name: i for i, name in enumerate(bus_names)}

bus_coords: dict[str, tuple[float, float]] = {}
for _, row in buses_df.iterrows():
    bus_coords[row["bus_name"]] = (float(row["x_coordinate"]), float(row["y_coordinate"]))


CORRIDOR_NODES: dict[str, tuple[float, float]] = {
    "plzen": (13.3833, 49.7500),
    "praha": (14.4378, 50.0755),
    "usti": (14.0333, 50.6667),
    "liberec": (15.0544, 50.7671),
    "hradec": (15.8327, 50.0836),
    "jihlava": (15.5833, 49.4000),
    "budejovice": (14.4747, 48.9747),
    "brno": (16.6068, 49.1951),
    "olomouc": (17.2500, 49.6000),
    "ostrava": (18.2625, 49.8209),
    "zlin": (17.6667, 49.2333),
}

CORRIDOR_EDGES: dict[str, tuple[str, ...]] = {
    "plzen": ("praha", "budejovice"),
    "praha": ("plzen", "usti", "liberec", "hradec", "jihlava", "budejovice"),
    "usti": ("praha", "liberec"),
    "liberec": ("usti", "praha", "hradec"),
    "hradec": ("liberec", "praha", "olomouc", "jihlava"),
    "jihlava": ("praha", "hradec", "brno", "budejovice"),
    "budejovice": ("plzen", "praha", "jihlava", "brno"),
    "brno": ("jihlava", "budejovice", "olomouc", "zlin"),
    "olomouc": ("hradec", "brno", "ostrava", "zlin"),
    "ostrava": ("olomouc", "zlin"),
    "zlin": ("brno", "olomouc", "ostrava"),
}


def distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def nearest_corridor_node(point: tuple[float, float]) -> str:
    return min(CORRIDOR_NODES, key=lambda node: distance(point, CORRIDOR_NODES[node]))


def corridor_path(start: str, end: str) -> list[str]:
    queue: list[list[str]] = [[start]]
    seen = {start}
    while queue:
        path = queue.pop(0)
        node = path[-1]
        if node == end:
            return path
        for next_node in CORRIDOR_EDGES[node]:
            if next_node not in seen:
                seen.add(next_node)
                queue.append([*path, next_node])
    return [start, end]


def routed_branch_coordinates(start: tuple[float, float], end: tuple[float, float]) -> list[list[float]]:
    if distance(start, end) < 0.55:
        return [[start[0], start[1]], [end[0], end[1]]]

    nodes = corridor_path(nearest_corridor_node(start), nearest_corridor_node(end))
    points = [[start[0], start[1]]]
    for node in nodes:
        point = CORRIDOR_NODES[node]
        if distance(tuple(points[-1]), point) > 0.08:
            points.append([point[0], point[1]])
    if distance(tuple(points[-1]), end) > 0.08:
        points.append([end[0], end[1]])
    else:
        points[-1] = [end[0], end[1]]
    return points


def parse_pandapower_df(obj: dict) -> pd.DataFrame:
    """Parse a pandapower serialized DataFrame (split orient)."""
    inner = json.loads(obj["_object"])
    return pd.DataFrame(data=inner["data"], columns=inner["columns"], index=inner.get("index"))


# --- App ---
app = FastAPI(title="Grid Topology API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _row_to_dict(row: pd.Series) -> dict:
    result = {}
    for col in row.index:
        val = row[col]
        if pd.isna(val):
            result[col] = None
        elif isinstance(val, (int, float)):
            result[col] = val
        elif isinstance(val, bool):
            result[col] = val
        else:
            result[col] = str(val)
    return result


@app.get("/api/grid/topology")
def get_topology():
    """Return grid topology with all asset metadata."""

    buses = []
    for _, row in buses_df.iterrows():
        entry = _row_to_dict(row)
        entry["id"] = row["bus_name"]
        entry["coordinates"] = [float(row["x_coordinate"]), float(row["y_coordinate"])]
        entry["v_kV"] = float(row["v_rated_kv"])
        entry["in_service"] = bool(row["in_service"])
        entry["is_slack"] = bool(row["is_slack"])
        buses.append(entry)

    branches = []
    for _, row in branches_df.iterrows():
        from_bus = row["from_bus"]
        to_bus = row["to_bus"]
        if from_bus not in bus_coords or to_bus not in bus_coords:
            continue
        lng1, lat1 = bus_coords[from_bus]
        lng2, lat2 = bus_coords[to_bus]
        entry = _row_to_dict(row)
        entry["id"] = row["branch_name"]
        entry["in_service"] = bool(row["in_service"])
        entry["is_trafo"] = pd.notna(row["trafo_ratio_rel"])
        entry["coordinates"] = routed_branch_coordinates((lng1, lat1), (lng2, lat2))
        branches.append(entry)

    generators = []
    for _, row in gens_df.iterrows():
        bus = row["bus_name"]
        if bus not in bus_coords:
            continue
        lng, lat = bus_coords[bus]
        entry = _row_to_dict(row)
        entry["id"] = row["gen_name"]
        entry["coordinates"] = [lng, lat]
        generators.append(entry)

    loads = []
    for _, row in loads_df.iterrows():
        bus = row["bus_name"]
        if bus not in bus_coords:
            continue
        lng, lat = bus_coords[bus]
        entry = _row_to_dict(row)
        entry["id"] = row["load_name"]
        entry["bus_name"] = bus
        entry["coordinates"] = [lng, lat]
        loads.append(entry)

    return {
        "buses": buses,
        "branches": branches,
        "generators": generators,
        "loads": loads,
    }


@app.get("/api/grid/snapshots")
def list_snapshots():
    """List available snapshot timestamps as ISO strings."""
    timestamps = []
    pattern = re.compile(r"^(\d{4}_\d{2}_\d{2}_\d{2}_\d{2}_\d{2})\.json$")
    for f in sorted(SNAPSHOTS_DIR.iterdir()):
        m = pattern.match(f.name)
        if m:
            ts = m.group(1)
            # Convert 2024_01_01_00_00_00 -> 2024-01-01T00:00:00
            parts = ts.split("_")
            iso = f"{parts[0]}-{parts[1]}-{parts[2]}T{parts[3]}:{parts[4]}:{parts[5]}"
            timestamps.append(iso)
    return timestamps


@app.get("/api/grid/snapshot/{timestamp}")
def get_snapshot(timestamp: str):
    """Return bus voltages and branch loading for a specific snapshot.
    Accepts either ISO format (2024-01-01T00:00:00) or underscore format (2024_01_01_00_00_00)."""
    if "T" in timestamp:
        ts = timestamp.replace("T", "_").replace("-", "_").replace(":", "_")
    else:
        ts = timestamp
    filename = f"{ts}.json"
    filepath = SNAPSHOTS_DIR / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail=f"Snapshot '{timestamp}' not found")

    with open(filepath, "r") as f:
        raw = json.load(f)

    obj = raw["_object"]

    # --- Parse res_bus (vm_pu, va_degree, p_mw, q_mvar per bus index) ---
    res_bus_df = parse_pandapower_df(obj["res_bus"])
    bus_results = []
    for idx in range(len(res_bus_df)):
        row = res_bus_df.iloc[idx]
        bus_name = bus_names[idx] if idx < len(bus_names) else f"bus_{idx:03d}"
        bus_results.append({
            "bus_name": bus_name,
            "vm_pu": float(row["vm_pu"]) if pd.notna(row["vm_pu"]) else None,
            "va_degree": float(row["va_degree"]) if pd.notna(row["va_degree"]) else None,
            "p_mw": float(row["p_mw"]) if pd.notna(row["p_mw"]) else None,
            "q_mvar": float(row["q_mvar"]) if pd.notna(row["q_mvar"]) else None,
        })

    # --- Parse res_line (loading_percent per line index) ---
    res_line_df = parse_pandapower_df(obj["res_line"])
    # Get line names from the line table
    line_df = parse_pandapower_df(obj["line"])
    line_names = line_df["name"].tolist()

    line_results = []
    for idx in range(len(res_line_df)):
        row = res_line_df.iloc[idx]
        name = line_names[idx] if idx < len(line_names) else f"line_{idx}"
        line_results.append({
            "branch_name": name,
            "loading_percent": float(row["loading_percent"]) if pd.notna(row["loading_percent"]) else None,
            "p_from_mw": float(row["p_from_mw"]) if pd.notna(row["p_from_mw"]) else None,
            "p_to_mw": float(row["p_to_mw"]) if pd.notna(row["p_to_mw"]) else None,
            "i_from_ka": float(row["i_from_ka"]) if pd.notna(row["i_from_ka"]) else None,
        })

    # --- Parse res_trafo (loading_percent per trafo index) ---
    res_trafo_df = parse_pandapower_df(obj["res_trafo"])
    trafo_df = parse_pandapower_df(obj["trafo"])
    trafo_names = trafo_df["name"].tolist()

    trafo_results = []
    for idx in range(len(res_trafo_df)):
        row = res_trafo_df.iloc[idx]
        name = trafo_names[idx] if idx < len(trafo_names) else f"trafo_{idx}"
        trafo_results.append({
            "branch_name": name,
            "loading_percent": float(row["loading_percent"]) if pd.notna(row["loading_percent"]) else None,
            "p_hv_mw": float(row["p_hv_mw"]) if pd.notna(row["p_hv_mw"]) else None,
            "p_lv_mw": float(row["p_lv_mw"]) if pd.notna(row["p_lv_mw"]) else None,
        })

    return {
        "timestamp": timestamp,
        "buses": [{"id": b["bus_name"], "vm_pu": b["vm_pu"], "p_mw": b["p_mw"]} for b in bus_results],
        "branches": [
            {"id": b["branch_name"], "loading_percent": b["loading_percent"]}
            for b in line_results + trafo_results
        ],
    }


from analytics import compute_overview, compute_safety, compute_alarms, load_timeseries, load_snapshot, build_bus_coords

_analytics_bus_coords = build_bus_coords(STATIC_DIR)


@app.get("/api/analytics/overview")
def analytics_overview():
    files = sorted(SNAPSHOTS_DIR.iterdir())
    if not files:
        raise HTTPException(status_code=404, detail="No snapshots available")
    latest = files[-1]
    data = load_snapshot(latest)
    return compute_overview(data)


@app.get("/api/analytics/timeseries")
def analytics_timeseries(hours: int = 24):
    return load_timeseries(SNAPSHOTS_DIR, hours=hours)


@app.get("/api/analytics/safety")
def analytics_safety():
    files = sorted(SNAPSHOTS_DIR.iterdir())
    if not files:
        raise HTTPException(status_code=404, detail="No snapshots available")
    latest = files[-1]
    data = load_snapshot(latest)
    return {"corridors": compute_safety(data, _analytics_bus_coords)}


@app.get("/api/analytics/alarms")
def analytics_alarms():
    files = sorted(SNAPSHOTS_DIR.iterdir())
    if not files:
        raise HTTPException(status_code=404, detail="No snapshots available")
    latest = files[-1]
    data = load_snapshot(latest)
    return compute_alarms(data)


# ──────────────────────────────────────────────────────────────────────────────
# AI Copilot endpoints
# ──────────────────────────────────────────────────────────────────────────────

from pydantic import BaseModel
from copilot import (
    initialise as copilot_initialise,
    start_simulation as copilot_start_simulation,
    get_simulation_status as copilot_get_sim_status,
    get_simulation_hours as copilot_get_sim_hours,
    get_simulation_hour as copilot_get_sim_hour,
    chat as copilot_chat,
    get_proposals as copilot_get_proposals,
    get_status as copilot_get_status,
)


class SimRequest(BaseModel):
    start_hour: int = 0
    end_hour: int | None = None
    stop_on_failure: bool = True
    allow_fallback_physics: bool = False
    full_n1_scan: bool = False
    model: str | None = None


class ChatRequest(BaseModel):
    message: str


@app.post("/api/copilot/init")
def api_copilot_init():
    """Initialise the AthenaAI copilot (idempotent)."""
    try:
        return copilot_initialise()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/copilot/status")
def api_copilot_status():
    """Return copilot + simulation status."""
    return copilot_get_status()


@app.post("/api/copilot/simulate")
def api_copilot_simulate(req: SimRequest):
    """Start the full simulation loop in a background thread."""
    try:
        return copilot_start_simulation(
            start_hour=req.start_hour,
            end_hour=req.end_hour,
            stop_on_failure=req.stop_on_failure,
            allow_fallback_physics=req.allow_fallback_physics,
            full_n1_scan=req.full_n1_scan,
            model=req.model,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)[:500])


@app.get("/api/copilot/simulation")
def api_copilot_simulation():
    """Get current simulation run status."""
    return copilot_get_sim_status()


@app.get("/api/copilot/simulation/hours")
def api_copilot_simulation_hours():
    """Get all completed hour results from the current simulation."""
    return copilot_get_sim_hours()


@app.get("/api/copilot/simulation/hour/{hour_index}")
def api_copilot_simulation_hour(hour_index: int):
    """Get a specific hour's detailed result."""
    result = copilot_get_sim_hour(hour_index)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Hour {hour_index} not found")
    return result


@app.get("/api/copilot/proposals")
def api_copilot_proposals(status: str | None = None):
    """List all proposals from the simulation."""
    return copilot_get_proposals(status)


@app.post("/api/copilot/chat")
def api_copilot_chat(req: ChatRequest):
    """Ask the copilot a question about the simulation."""
    try:
        return copilot_chat(req.message)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)[:500])


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

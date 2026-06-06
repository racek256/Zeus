"""Analytics computation from pandapower snapshots."""

import json
import math
import re
from pathlib import Path
from typing import Any

import pandas as pd

def parse_pandapower_df(obj: dict) -> pd.DataFrame:
    """Parse a pandapower serialized DataFrame (split orient)."""
    inner = json.loads(obj["_object"])
    return pd.DataFrame(data=inner["data"], columns=inner["columns"], index=inner.get("index"))


def load_snapshot(filepath: Path) -> dict[str, Any]:
    """Load and parse a single snapshot file."""
    with open(filepath, "r") as f:
        raw = json.load(f)
    obj = raw["_object"]

    # Parse result tables
    res_bus = parse_pandapower_df(obj["res_bus"])
    res_line = parse_pandapower_df(obj["res_line"])
    res_trafo = parse_pandapower_df(obj["res_trafo"])
    res_gen = parse_pandapower_df(obj["res_gen"])
    res_load = parse_pandapower_df(obj["res_load"])

    # Parse static tables for names
    line_df = parse_pandapower_df(obj["line"])
    trafo_df = parse_pandapower_df(obj["trafo"])
    gen_df = parse_pandapower_df(obj["gen"])
    load_df = parse_pandapower_df(obj["load"])
    bus_df = parse_pandapower_df(obj["bus"])

    return {
        "res_bus": res_bus,
        "res_line": res_line,
        "res_trafo": res_trafo,
        "res_gen": res_gen,
        "res_load": res_load,
        "line": line_df,
        "trafo": trafo_df,
        "gen": gen_df,
        "load": load_df,
        "bus": bus_df,
    }


def compute_overview(data: dict[str, Any]) -> dict[str, Any]:
    """Compute overview metrics from a single snapshot."""
    total_gen = float(data["res_gen"]["p_mw"].sum())
    total_load = float(data["res_load"]["p_mw"].sum())
    imbalance = total_gen - total_load
    ratio = total_gen / total_load if total_load > 0 else 0.0

    max_line_loading = float(data["res_line"]["loading_percent"].max()) if not data["res_line"].empty else 0.0
    max_trafo_loading = float(data["res_trafo"]["loading_percent"].max()) if not data["res_trafo"].empty else 0.0

    res_bus = data["res_bus"]
    bus_limits = data["bus"][["min_vm_pu", "max_vm_pu"]]
    vm = res_bus["vm_pu"]
    vmin = bus_limits["min_vm_pu"]
    vmax = bus_limits["max_vm_pu"]
    overvoltage = int((vm > vmax).sum())
    undervoltage = int((vm < vmin).sum())
    voltage_violations = overvoltage + undervoltage

    if max_line_loading > 95 or max_trafo_loading > 95 or voltage_violations > 0:
        safety_state = "Critical"
    elif max_line_loading > 85 or max_trafo_loading > 85:
        safety_state = "Tightening"
    elif max_line_loading > 70 or max_trafo_loading > 70:
        safety_state = "Elevated"
    else:
        safety_state = "Normal"

    # Generation headroom
    gen_max = pd.to_numeric(data["gen"]["max_p_mw"], errors="coerce").sum()
    reserve_headroom = float(gen_max - total_gen)

    return {
        "consumption_now": round(total_load, 1),
        "production_now": round(total_gen, 1),
        "prod_cons_ratio": round(ratio, 2),
        "net_imbalance": round(imbalance, 1),
        "safety_state": safety_state,
        "max_line_loading": round(max_line_loading, 1),
        "max_trafo_loading": round(max_trafo_loading, 1),
        "reserve_headroom": round(reserve_headroom, 1),
        "voltage_violations": voltage_violations,
    }


def classify_branch_direction(
    from_lng: float, from_lat: float, to_lng: float, to_lat: float
) -> str:
    """Classify a branch into a corridor based on its midpoint and direction."""
    mid_lng = (from_lng + to_lng) / 2
    mid_lat = (from_lat + to_lat) / 2
    d_lng = to_lng - from_lng
    d_lat = to_lat - from_lat

    # Prague center
    prague_lng, prague_lat = 14.4208, 50.0880
    dist_to_prague = math.sqrt((mid_lng - prague_lng) ** 2 + (mid_lat - prague_lat) ** 2)

    # Classify by direction and region
    if dist_to_prague < 0.8:
        return "Prague ring"

    # Angle from north (0 = north, 90 = east, 180 = south, 270 = west)
    angle = math.degrees(math.atan2(d_lng, d_lat))  # Note: atan2(x, y) gives angle from north
    angle = (angle + 360) % 360

    # Midpoint-based region classification
    if mid_lat > 50.4 and mid_lng < 14.0:
        return "CZ-PL North"
    if mid_lat > 50.4 and mid_lng >= 14.0:
        return "CZ-DE North"
    if mid_lat < 49.3:
        return "CZ-AT South"
    if mid_lng > 16.5:
        return "CZ-SK East"

    # Default by angle
    if 0 <= angle < 45 or 315 <= angle < 360:
        return "CZ-DE North"
    if 45 <= angle < 135:
        return "CZ-SK East"
    if 135 <= angle < 225:
        return "CZ-AT South"
    if 225 <= angle < 315:
        return "CZ-PL North"

    return "Moravia spine"


def build_bus_coords(static_dir: Path) -> dict[str, tuple[float, float]]:
    """Build bus_name -> (lng, lat) mapping from static CSV."""
    buses_df = pd.read_csv(static_dir / "buses.csv")
    coords: dict[str, tuple[float, float]] = {}
    for _, row in buses_df.iterrows():
        coords[row["bus_name"]] = (float(row["x_coordinate"]), float(row["y_coordinate"]))
    return coords


def compute_safety(data: dict[str, Any], bus_coords: dict[str, tuple[float, float]]) -> list[dict[str, Any]]:
    """Compute line loading grouped by corridor."""
    line_df = data["line"]
    res_line = data["res_line"]
    trafo_df = data["trafo"]
    res_trafo = data["res_trafo"]

    corridor_loadings: dict[str, list[float]] = {}

    # Process lines
    for idx in range(len(res_line)):
        if idx >= len(line_df):
            continue
        row = line_df.iloc[idx]
        from_bus = row["from_bus"]
        to_bus = row["to_bus"]
        if from_bus not in bus_coords or to_bus not in bus_coords:
            continue
        from_lng, from_lat = bus_coords[from_bus]
        to_lng, to_lat = bus_coords[to_bus]
        corridor = classify_branch_direction(from_lng, from_lat, to_lng, to_lat)
        loading = float(res_line.iloc[idx]["loading_percent"])
        corridor_loadings.setdefault(corridor, []).append(loading)

    # Process transformers
    for idx in range(len(res_trafo)):
        if idx >= len(trafo_df):
            continue
        row = trafo_df.iloc[idx]
        hv_bus = row["hv_bus"]
        lv_bus = row["lv_bus"]
        bus_names = data["bus"]["name"].tolist()
        hv_name = bus_names[hv_bus] if hv_bus < len(bus_names) else f"bus_{hv_bus:03d}"
        lv_name = bus_names[lv_bus] if lv_bus < len(bus_names) else f"bus_{lv_bus:03d}"
        if hv_name not in bus_coords or lv_name not in bus_coords:
            continue
        hv_lng, hv_lat = bus_coords[hv_name]
        lv_lng, lv_lat = bus_coords[lv_name]
        corridor = classify_branch_direction(hv_lng, hv_lat, lv_lng, lv_lat)
        loading = float(res_trafo.iloc[idx]["loading_percent"])
        corridor_loadings.setdefault(corridor, []).append(loading)

    # Return max loading per corridor, sorted descending
    results = []
    for corridor, loadings in corridor_loadings.items():
        if loadings:
            results.append({
                "corridor": corridor,
                "max_loading": round(max(loadings), 1),
                "avg_loading": round(sum(loadings) / len(loadings), 1),
                "count": len(loadings),
            })

    results.sort(key=lambda x: x["max_loading"], reverse=True)
    return results


def compute_alarms(data: dict[str, Any]) -> dict[str, int]:
    """Count alarms from voltage and loading violations."""
    res_bus = data["res_bus"]
    res_line = data["res_line"]
    res_trafo = data["res_trafo"]
    bus_limits = data["bus"][["min_vm_pu", "max_vm_pu"]]
    vm = res_bus["vm_pu"]
    vmin = bus_limits["min_vm_pu"]
    vmax = bus_limits["max_vm_pu"]

    p1_count = 0
    p1_count += int((res_line["loading_percent"] > 100).sum())
    p1_count += int((res_trafo["loading_percent"] > 100).sum())
    p1_count += int((vm > vmax).sum())
    p1_count += int((vm < vmin).sum())

    p2_count = 0
    p2_count += int(((res_line["loading_percent"] > 85) & (res_line["loading_percent"] <= 100)).sum())
    p2_count += int(((res_trafo["loading_percent"] > 85) & (res_trafo["loading_percent"] <= 100)).sum())

    upper_margin = (vmax - vm) / (vmax - vmin)
    lower_margin = (vm - vmin) / (vmax - vmin)
    voltage_margin = pd.concat([upper_margin, lower_margin], axis=1).min(axis=1)
    p3_count = int(((voltage_margin >= 0) & (voltage_margin < 0.08)).sum())

    info_count = int(((voltage_margin >= 0.08) & (voltage_margin < 0.15)).sum())

    return {
        "P1": p1_count,
        "P2": p2_count,
        "P3": p3_count,
        "Info": info_count,
    }


def load_timeseries(snapshots_dir: Path, hours: int = 24) -> dict[str, Any]:
    """Load the last N hours of snapshots and compute timeseries data."""
    # Get sorted list of snapshot files
    pattern = re.compile(r"^(\d{4}_\d{2}_\d{2}_\d{2}_\d{2}_\d{2})\.json$")
    files = []
    for f in sorted(snapshots_dir.iterdir()):
        m = pattern.match(f.name)
        if m:
            files.append(f)

    if not files:
        return {}

    # Take the last N hours
    selected = files[-hours:] if len(files) >= hours else files

    bus_coords = build_bus_coords(snapshots_dir.parent / "static")

    # Build timeseries
    hours_list = []
    load_actual = []
    generation_actual = []
    balance_actual = []

    for f in selected:
        parts = f.stem.split("_")
        hour_str = f"{parts[3]}:{parts[4]}"
        hours_list.append(hour_str)

        data = load_snapshot(f)
        total_gen = float(data["res_gen"]["p_mw"].sum())
        total_load = float(data["res_load"]["p_mw"].sum())

        generation_actual.append(round(total_gen, 1))
        load_actual.append(round(total_load, 1))
        balance_actual.append(round(total_gen - total_load, 1))

    gen_df = load_snapshot(selected[-1])["gen"] if selected else None
    if gen_df is not None:
        gen_max = pd.to_numeric(gen_df["max_p_mw"], errors="coerce").sum()
        gen_min = pd.to_numeric(gen_df["min_p_mw"], errors="coerce").sum()
        max_capacity = float(gen_max)
    else:
        max_capacity = max(generation_actual) * 1.2 if generation_actual else 1000

    # Safety watchlist from last snapshot
    last_data = load_snapshot(selected[-1]) if selected else None
    safety = compute_safety(last_data, bus_coords) if last_data else []

    # Reserve breakdown from last snapshot
    last_gen = last_data["res_gen"] if last_data else None
    last_gen_static = last_data["gen"] if last_data else None
    reserve_types = []
    reserve_used = []
    reserve_available = []
    if last_gen is not None and last_gen_static is not None:
        # Simplify: group by opt_category or just show aggregate
        # Since we have 321 generators, aggregate into categories
        gen_static = last_gen_static
        gen_res = last_gen

        # Total headroom
        total_actual = float(gen_res["p_mw"].sum())
        total_max = pd.to_numeric(gen_static["max_p_mw"], errors="coerce").sum()
        total_available = float(total_max - total_actual)

        # Reserve categories (simplified allocation)
        # FCP 30s: ~5% of available
        # aFRR 5-10m: ~15% of available
        # mFRR 5m: ~20% of available
        # mFRR 15m: ~30% of available
        # SVQC: remainder
        reserve_alloc = {
            "FCP 30s": 0.05,
            "aFRR 5-10m": 0.15,
            "mFRR 5m": 0.20,
            "mFRR 15m": 0.30,
            "SVQC": 0.30,
        }

        for rtype, ratio in reserve_alloc.items():
            avail = round(total_available * ratio, 1)
            used = round(avail * (0.3 + 0.4 * hash(rtype) % 100 / 100), 1)  # Pseudo-random used ratio
            reserve_types.append(rtype)
            reserve_available.append(round(avail, 1))
            reserve_used.append(round(used, 1))

    return {
        "hours": hours_list,
        "load_actual": load_actual,
        "generation_actual": generation_actual,
        "balance_actual": balance_actual,
        "safety_watchlist": safety,
        "reserve_types": reserve_types,
        "reserve_used": reserve_used,
        "reserve_available": reserve_available,
    }

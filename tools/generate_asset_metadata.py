#!/usr/bin/env python3
"""Generate realistic metadata for all grid assets."""
import csv
import math
import random
from datetime import datetime, timedelta
from pathlib import Path

SEED = 42
random.seed(SEED)

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "dataset" / "greenhack-2026-ČEPS-dataset" / "data" / "static"

OPERATORS_TRANSMISSION = ["ČEPS, přenosová a.s."]
OPERATORS_DISTRIBUTION = ["EG.D, a.s.", "ČEZ Distribuce, a.s.", "PREdistribuce, a.s."]
OPERATORS_GENERATION = ["ČEZ, a.s.", "Skupina ČEZ", "EPH Česká republika", "Sev.en Energy", "Pražská energetika a.s.", "Veolia Energie ČR"]

CITY_NAMES = [
    "Praha", "Brno", "Ostrava", "Plzeň", "Liberec", "Olomouc", "Hradec Králové",
    "Pardubice", "Ústí nad Labem", "České Budějovice", "Karlovy Vary", "Jihlava",
    "Kladno", "Most", "Opava", "Zlín", "Havířov", "Teplice", "Chomutov", "Děčín",
    "Kolín", "Kroměříž", "Prostějov", "Přerov", "Frýdek-Místek", "Znojmo", "Třebíč",
    "Chrudim", "Břeclav", "Beroun", "Kutná Hora", "Nymburk", "Mladá Boleslav",
    "Klatovy", "Domažlice", "Cheb", "Mariánské Lázně", "Tábor", "Strakonice",
    "Prachatice", "Písek", "Blansko", "Vyškov", "Hodonín", "Uherské Hradiště",
    "Vsetín", "Jeseník", "Šumperk", "Bruntál", "Krnov", "Bílovec",
]

CUSTOMER_TYPES = ["residential", "industrial", "commercial", "mixed", "railway", "hospital", "datacenter"]
PRIORITY_CLASSES = ["normal", "important", "critical"]
LINE_TYPES = ["overhead", "overhead", "overhead", "overhead", "underground", "mixed"]
CONDUCTOR_TYPES = ["ACSR", "ACSR", "ACSR", "aluminum", "composite", "HTLS"]
TECH_FUEL = {
    "solar": "photovoltaic", "wind": "wind", "hydro": "water",
    "biomass": "biomass", "geothermal": "geothermal",
    "combustion_gas": "natural gas", "combined_cycle_gas": "natural gas",
    "internal_combustion_gas": "natural gas", "steam_gas": "natural gas",
    "steam_coal": "coal", "steam_other": "coal", "combustion_oil": "fuel oil",
}

ALARM_TYPES = ["voltage_deviation", "frequency_deviation", "line_overload", "transformer_overload", "bus_fault", "communication_loss", "protection_trip", "weather_event", "vegetation_encroachment", "none"]

def random_date(start_year, end_year):
    y = random.randint(start_year, end_year)
    m = random.randint(1, 12)
    d = random.randint(1, 28)
    return f"{y}-{m:02d}-{d:02d}"

def random_datetime(start_year, end_year):
    d = random_date(start_year, end_year)
    h = random.randint(0, 23)
    mi = random.randint(0, 59)
    return f"{d} {h:02d}:{mi:02d}"

def inspection_dates(commissioning_year):
    last = random_date(2022, 2024)
    next_d = random_date(2025, 2027)
    return last, next_d

def maintenance_dates(commissioning_year):
    last = random_date(2022, 2024)
    next_d = random_date(2025, 2027)
    return last, next_d

def repair_dates():
    return random_date(2018, 2024)

def alarm_dates():
    last = random_date(2023, 2024)
    alarm_type = random.choice(ALARM_TYPES[:-1])
    count = random.randint(0, 12)
    return last, alarm_type, count

def outage_counts():
    return random.randint(0, 8)

def random_operator(asset_type):
    if asset_type == "bus":
        return random.choice(OPERATORS_TRANSMISSION + OPERATORS_DISTRIBUTION)
    elif asset_type == "branch":
        return random.choice(OPERATORS_TRANSMISSION)
    elif asset_type == "generator":
        return random.choice(OPERATORS_GENERATION)
    else:
        return random.choice(OPERATORS_DISTRIBUTION)

def common_fields(name, region, commissioning_year, asset_type):
    li, ni = inspection_dates(commissioning_year)
    lm, nm = maintenance_dates(commissioning_year)
    lr = repair_dates()
    la, lat, ac = alarm_dates()
    oc = outage_counts()
    wo = random.randint(0, 3)
    notes_options = [
        "", "", "", "",
        "Regular maintenance scheduled",
        "Minor vegetation work needed",
        "SCADA upgrade in progress",
        "Connection point for new industrial customer",
        "Part of grid modernization program",
        "Weather-hardened since 2020",
    ]
    return {
        "asset_name": name,
        "operator": random_operator(asset_type),
        "region": region,
        "commissioning_year": commissioning_year,
        "last_inspection_date": li,
        "next_inspection_date": ni,
        "last_maintenance_date": lm,
        "next_maintenance_date": nm,
        "last_repair_date": lr,
        "last_alarm_date": la,
        "last_alarm_type": lat,
        "alarm_count_12m": ac,
        "outage_count_12m": oc,
        "open_work_orders": wo,
        "notes": random.choice(notes_options),
    }

def generate_bus_metadata(bus_row, gen_map, load_map, branch_map):
    name = bus_row["bus_name"]
    region = bus_row["region"]
    voltage = int(bus_row["v_rated_kv"])
    cy = random.randint(1962, 2005)

    base = common_fields(f"Substation {name.replace('bus_', 'SS-')}", region, cy, "bus")
    connected_lines = len(branch_map.get(name, []))
    connected_gens = len(gen_map.get(name, []))
    connected_loads = len(load_map.get(name, []))
    connected_trafos = 1 if voltage >= 345 else 0
    substation_names = [f"SS {random.choice(CITY_NAMES)} {random.choice(['Jih', 'Sever', 'Střed', 'Východ', 'Západ'])}" for _ in range(1)]
    base.update({
        "substation_name": f"SS {name.replace('bus_', '')}",
        "voltage_kv": voltage,
        "busbar_section": random.choice(["A", "B", "C", "AB", "ABC"]),
        "bus_type": "transmission" if voltage >= 345 else random.choice(["distribution", "generator_connection", "load_connection"]),
        "connected_lines_count": connected_lines,
        "connected_generators_count": connected_gens,
        "connected_loads_count": connected_loads,
        "connected_transformers_count": connected_trafos,
        "last_protection_test_date": random_date(2022, 2024),
        "last_outage_date": random_date(2020, 2024),
        "scada_available": random.choice(["yes", "yes", "yes", "no"]),
        "remote_control_enabled": random.choice(["yes", "yes", "no"]),
    })
    return base

def generate_branch_metadata(branch_row, buses_dict):
    name = branch_row["branch_name"]
    from_bus = branch_row["from_bus"]
    to_bus = branch_row["to_bus"]
    region_from = buses_dict.get(from_bus, {}).get("region", "r1")
    region_to = buses_dict.get(to_bus, {}).get("region", "r2")
    voltage = int(buses_dict.get(from_bus, {}).get("v_rated_kv", 138))
    cy = random.randint(1965, 2010)

    lng1 = float(buses_dict.get(from_bus, {}).get("x_coordinate", 14.5))
    lat1 = float(buses_dict.get(from_bus, {}).get("y_coordinate", 49.8))
    lng2 = float(buses_dict.get(to_bus, {}).get("x_coordinate", 15.0))
    lat2 = float(buses_dict.get(to_bus, {}).get("y_coordinate", 50.0))
    length_km = round(math.hypot(lng2 - lng1, lat2 - lat1) * 111 * 0.9, 1)
    length_km = max(length_km, 2.0)

    base = common_fields(f"Line {name.replace('branch_', '').replace('_', '-')}", region_from, cy, "branch")
    base.update({
        "from_substation": f"SS {from_bus.replace('bus_', '')}",
        "to_substation": f"SS {to_bus.replace('bus_', '')}",
        "voltage_kv": voltage,
        "line_length_km": length_km,
        "line_type": random.choice(LINE_TYPES),
        "circuit_count": random.choice([1, 1, 2, 2, 4]) if voltage >= 345 else random.choice([1, 1, 2]),
        "conductor_type": random.choice(CONDUCTOR_TYPES),
        "tower_count": max(int(length_km / 0.35), 10),
        "last_vegetation_clearance_date": random_date(2022, 2024),
        "next_vegetation_clearance_date": random_date(2025, 2027),
        "last_outage_date": random_date(2020, 2024),
        "planned_outage_date": random_date(2025, 2026),
    })
    return base

def generate_gen_metadata(gen_row):
    name = gen_row["gen_name"]
    bus = gen_row["bus_name"]
    max_mw = float(gen_row["max_p_mw"])
    min_mw = float(gen_row["min_p_mw"])

    tech = "_".join(name.split("_")[:-1])
    fuel = TECH_FUEL.get(tech, "unknown")
    region = "r1" if bus.startswith("bus_0") and int(bus.split("_")[1]) <= 32 else "r2" if int(bus.split("_")[1]) <= 81 else "r3"
    cy = random.randint(1970, 2023)

    base = common_fields(f"Generator {name.replace('_', '-')}", region, cy, "generator")
    base.update({
        "plant_name": f"Power Plant {random.choice(CITY_NAMES)}",
        "unit_name": f"{tech.replace('_', ' ').title()} Unit {name.split('_')[-1]}",
        "technology_type": tech,
        "fuel_type": fuel,
        "installed_capacity_mw": round(max_mw, 1),
        "min_output_mw": round(min_mw, 1),
        "max_output_mw": round(max_mw, 1),
        "black_start_capable": random.choice(["yes", "no", "no", "no"]),
        "reserve_capable": random.choice(["yes", "yes", "no"]),
        "remote_dispatchable": random.choice(["yes", "yes", "yes", "no"]),
        "last_major_overhaul_date": random_date(2018, 2023),
        "planned_outage_date": random_date(2025, 2026),
        "forced_outage_count_12m": random.randint(0, 5),
    })
    return base

def generate_load_metadata(load_row):
    name = load_row["load_name"]
    bus = load_row["bus_name"]
    region = "r1" if int(bus.split("_")[1]) <= 32 else "r2" if int(bus.split("_")[1]) <= 81 else "r3"
    cy = random.randint(1970, 2015)

    base = common_fields(f"Load Point {name.replace('_', '-')}", region, cy, "load")
    base.update({
        "load_area_name": f"Area {random.choice(CITY_NAMES)} {random.choice(['North', 'South', 'East', 'West', 'Center'])}",
        "customer_type": random.choice(CUSTOMER_TYPES),
        "priority_class": random.choice(PRIORITY_CLASSES),
        "critical_infrastructure": random.choice(["yes", "no", "no", "no", "no"]),
        "interruptible": random.choice(["yes", "yes", "no"]),
        "demand_response_capable": random.choice(["yes", "no", "no", "no"]),
        "backup_supply_available": random.choice(["yes", "yes", "no", "no"]),
        "last_outage_date": random_date(2020, 2024),
        "planned_outage_date": random_date(2025, 2026),
    })
    return base

def main():
    print("Reading existing data...")
    with open(STATIC / "buses.csv", newline="") as f:
        buses = list(csv.DictReader(f))
    with open(STATIC / "branches.csv", newline="") as f:
        branches = list(csv.DictReader(f))
    with open(STATIC / "gens.csv", newline="") as f:
        gens = list(csv.DictReader(f))
    with open(STATIC / "loads.csv", newline="") as f:
        loads = list(csv.DictReader(f))

    buses_dict = {b["bus_name"]: b for b in buses}

    gen_map = {}
    for g in gens:
        gen_map.setdefault(g["bus_name"], []).append(g["gen_name"])

    load_map = {}
    for l in loads:
        load_map.setdefault(l["bus_name"], []).append(l["load_name"])

    branch_map = {}
    for br in branches:
        branch_map.setdefault(br["from_bus"], []).append(br["branch_name"])
        branch_map.setdefault(br["to_bus"], []).append(br["branch_name"])

    print(f"Generating metadata for {len(buses)} buses, {len(branches)} branches, {len(gens)} generators, {len(loads)} loads...")

    bus_meta = []
    for b in buses:
        meta = generate_bus_metadata(b, gen_map, load_map, branch_map)
        bus_meta.append({**b, **meta})

    branch_meta = []
    for br in branches:
        meta = generate_branch_metadata(br, buses_dict)
        branch_meta.append({**br, **meta})

    gen_meta = []
    for g in gens:
        meta = generate_gen_metadata(g)
        gen_meta.append({**g, **meta})

    load_meta = []
    for l in loads:
        meta = generate_load_metadata(l)
        load_meta.append({**l, **meta})

    print("Writing updated CSVs...")
    for filename, data in [("buses.csv", bus_meta), ("branches.csv", branch_meta), ("gens.csv", gen_meta), ("loads.csv", load_meta)]:
        with open(STATIC / filename, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=data[0].keys())
            writer.writeheader()
            writer.writerows(data)
        print(f"  {filename}: {len(data)} rows, {len(data[0].keys())} columns")

    print("\nDone! Generated metadata for all assets.")

if __name__ == "__main__":
    main()

#!/usr/bin/env python3

import csv
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ZIP_PATH = ROOT / "greenhack-2026-CEPS-dataset.zip"
STATIC_DIR = ROOT / "dataset" / "greenhack-2026-ČEPS-dataset" / "data" / "static"
ZIP_BUSES = "greenhack-2026-ČEPS-dataset/data/static/buses.csv"


REGION_TARGETS = {
    "r1": {
        "lng_min": 12.45,
        "lng_max": 15.20,
        "lat_min": 48.86,
        "lat_max": 50.48,
    },
    "r2": {
        "lng_min": 14.25,
        "lng_max": 18.28,
        "lat_min": 49.05,
        "lat_max": 50.42,
    },
    "r3": {
        "lng_min": 15.25,
        "lng_max": 18.35,
        "lat_min": 48.78,
        "lat_max": 49.72,
    },
}


CITY_PULLS = [
    (14.4378, 50.0755, 0.16),
    (16.6068, 49.1951, 0.11),
    (17.1067, 49.5938, 0.10),
    (13.3833, 49.7500, 0.10),
    (15.8327, 50.0836, 0.07),
    (15.5833, 49.4000, 0.06),
    (14.4747, 48.9747, 0.05),
]


def read_original_rows() -> list[dict[str, str]]:
    with zipfile.ZipFile(ZIP_PATH) as archive:
        with archive.open(ZIP_BUSES) as handle:
            return list(csv.DictReader(line.decode("utf-8") for line in handle))


def region_bounds(rows: list[dict[str, str]]) -> dict[str, tuple[float, float, float, float]]:
    bounds = {}
    for region in REGION_TARGETS:
        region_rows = [row for row in rows if row["region"] == region]
        xs = [float(row["x_coordinate"]) for row in region_rows]
        ys = [float(row["y_coordinate"]) for row in region_rows]
        bounds[region] = (min(xs), max(xs), min(ys), max(ys))
    return bounds


def envelope_lat_bounds(lng: float) -> tuple[float, float]:
    anchors = [
        (12.20, 49.62, 50.35),
        (13.20, 49.15, 50.70),
        (14.20, 48.78, 50.95),
        (15.20, 48.72, 50.90),
        (16.30, 48.75, 50.32),
        (17.30, 48.84, 50.18),
        (18.70, 49.26, 49.95),
    ]
    if lng <= anchors[0][0]:
        return anchors[0][1], anchors[0][2]
    if lng >= anchors[-1][0]:
        return anchors[-1][1], anchors[-1][2]
    for left, right in zip(anchors, anchors[1:]):
        if left[0] <= lng <= right[0]:
            t = (lng - left[0]) / (right[0] - left[0])
            lat_min = left[1] + t * (right[1] - left[1])
            lat_max = left[2] + t * (right[2] - left[2])
            return lat_min, lat_max
    raise RuntimeError("unreachable")


def clamp_to_czech_envelope(lng: float, lat: float) -> tuple[float, float]:
    lat_min, lat_max = envelope_lat_bounds(lng)
    margin = 0.06
    lat = max(lat_min + margin, min(lat_max - margin, lat))
    return lng, lat


def pull_toward_cities(lng: float, lat: float) -> tuple[float, float]:
    total_weight = 0.0
    pulled_lng = lng
    pulled_lat = lat
    for city_lng, city_lat, weight in CITY_PULLS:
        dist2 = (lng - city_lng) ** 2 + (lat - city_lat) ** 2
        local_weight = weight / (dist2 + 0.20)
        pulled_lng += local_weight * city_lng
        pulled_lat += local_weight * city_lat
        total_weight += local_weight
    blend = min(0.14, total_weight / 80)
    lng = lng * (1 - blend) + (pulled_lng / (1 + total_weight)) * blend
    lat = lat * (1 - blend) + (pulled_lat / (1 + total_weight)) * blend
    return lng, lat


def project_rows(rows: list[dict[str, str]]) -> dict[str, tuple[float, float]]:
    bounds = region_bounds(rows)
    projected = {}

    for row in rows:
        region = row["region"]
        x = float(row["x_coordinate"])
        y = float(row["y_coordinate"])
        x_min, x_max, y_min, y_max = bounds[region]
        target = REGION_TARGETS[region]

        nx = (x - x_min) / (x_max - x_min)
        ny = (y - y_min) / (y_max - y_min)

        lng = target["lng_min"] + nx * (target["lng_max"] - target["lng_min"])
        lat = target["lat_max"] - ny * (target["lat_max"] - target["lat_min"])

        if region == "r1":
            lat += 0.10 * (nx - 0.5)
        elif region == "r2":
            lat -= 0.18 * (nx - 0.5)
        elif region == "r3":
            lat += 0.10 * (nx - 0.5)

        lng, lat = pull_toward_cities(lng, lat)
        lng, lat = clamp_to_czech_envelope(lng, lat)
        projected[row["bus_name"]] = (round(lng, 5), round(lat, 5))

    return projected


def update_csv(filename: str, projected: dict[str, tuple[float, float]]) -> None:
    path = STATIC_DIR / filename
    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))

    for row in rows:
        lng, lat = projected[row["bus_name"]]
        row["x_coordinate"] = lng
        row["y_coordinate"] = lat

    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    rows = read_original_rows()
    projected = project_rows(rows)
    update_csv("buses.csv", projected)
    update_csv("bus_coordinates.csv", projected)

    lngs = [lng for lng, _ in projected.values()]
    lats = [lat for _, lat in projected.values()]
    print(f"Projected {len(projected)} buses")
    print(f"Longitude: {min(lngs):.5f} to {max(lngs):.5f}")
    print(f"Latitude: {min(lats):.5f} to {max(lats):.5f}")


if __name__ == "__main__":
    main()

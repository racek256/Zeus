"""Real marginal cost curves for Czech generator fleet.

Calculates per-unit marginal costs using fuel prices, plant efficiencies,
CO2 emission factors, EU ETS carbon prices, and O&M costs. Produces
merit-order-sorted generator lists for realistic market simulation.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from athenaai.config import DATASET_FUEL_PRICES

_GJ_TO_MWH = 3.6

_FUEL_COLUMN_MAP: dict[str, str] = {
    "coal": "Coal R1",
    "brown_coal": "Coal R1",
    "lignite": "Coal R1",
    "steam_coal": "Coal R1",
    "natural_gas": "Natural Gas R1",
    "gas": "Natural Gas R1",
    "ccgt": "Natural Gas R1",
    "oil": "Oil Distillate R1",
    "biomass": "Biomass R1",
    "uranium": "nuclear_fuel",
    "nuclear": "nuclear_fuel",
    "geo": "Geo R1",
    "hydro": "hydro",
    "wind": "wind",
    "solar": "solar",
}

_GENERATOR_DEFAULTS: dict[str, dict[str, float]] = {
    "nuclear": {
        "efficiency": 0.33,
        "co2_factor_t_per_mwh": 0.0,
        "om_cost_eur_mwh": 8.0,
        "variable_cost_eur_mwh": 2.0,
    },
    "brown_coal": {
        "efficiency": 0.38,
        "co2_factor_t_per_mwh": 0.95,
        "om_cost_eur_mwh": 5.0,
        "variable_cost_eur_mwh": 2.5,
    },
    "coal": {
        "efficiency": 0.42,
        "co2_factor_t_per_mwh": 0.85,
        "om_cost_eur_mwh": 4.0,
        "variable_cost_eur_mwh": 2.0,
    },
    "lignite": {
        "efficiency": 0.36,
        "co2_factor_t_per_mwh": 1.1,
        "om_cost_eur_mwh": 5.0,
        "variable_cost_eur_mwh": 2.5,
    },
    "ccgt": {
        "efficiency": 0.58,
        "co2_factor_t_per_mwh": 0.35,
        "om_cost_eur_mwh": 3.0,
        "variable_cost_eur_mwh": 1.5,
    },
    "natural_gas": {
        "efficiency": 0.55,
        "co2_factor_t_per_mwh": 0.40,
        "om_cost_eur_mwh": 3.5,
        "variable_cost_eur_mwh": 1.5,
    },
    "gas": {
        "efficiency": 0.50,
        "co2_factor_t_per_mwh": 0.45,
        "om_cost_eur_mwh": 4.0,
        "variable_cost_eur_mwh": 2.0,
    },
    "oil": {
        "efficiency": 0.38,
        "co2_factor_t_per_mwh": 0.75,
        "om_cost_eur_mwh": 6.0,
        "variable_cost_eur_mwh": 3.0,
    },
    "biomass": {
        "efficiency": 0.30,
        "co2_factor_t_per_mwh": 0.0,
        "om_cost_eur_mwh": 12.0,
        "variable_cost_eur_mwh": 3.0,
    },
    "hydro": {
        "efficiency": 0.90,
        "co2_factor_t_per_mwh": 0.0,
        "om_cost_eur_mwh": 3.0,
        "variable_cost_eur_mwh": 1.0,
    },
    "wind": {
        "efficiency": 1.0,
        "co2_factor_t_per_mwh": 0.0,
        "om_cost_eur_mwh": 10.0,
        "variable_cost_eur_mwh": 0.0,
    },
    "solar": {
        "efficiency": 1.0,
        "co2_factor_t_per_mwh": 0.0,
        "om_cost_eur_mwh": 8.0,
        "variable_cost_eur_mwh": 0.0,
    },
}

_FUEL_EUR_MWH_DEFAULTS: dict[str, float] = {
    "nuclear_fuel": 5.0,
    "Coal R1": 28.0,
    "Natural Gas R1": 45.0,
    "Oil Distillate R1": 126.0,
    "Biomass R1": 8.6,
    "Geo R1": 0.0,
    "hydro": 0.0,
    "wind": 0.0,
    "solar": 0.0,
}


@dataclass
class GeneratorCost:
    generator_id: str
    fuel_type: str
    capacity_mw: float
    marginal_cost_eur_mwh: float
    fuel_cost_eur_mwh: float
    co2_cost_eur_mwh: float
    om_cost_eur_mwh: float
    variable_cost_eur_mwh: float
    efficiency: float
    co2_factor_t_per_mwh: float
    carbon_price_eur_ton: float


@dataclass
class CostCurveResult:
    timestamp: datetime
    generators: list[GeneratorCost] = field(default_factory=list)
    fuel_prices: dict[str, float] = field(default_factory=dict)
    carbon_price_eur_ton: float = 80.0
    data_source: str = "default"

    def merit_order(self) -> list[GeneratorCost]:
        return sorted(self.generators, key=lambda g: g.marginal_cost_eur_mwh)

    def get_cost(self, generator_id: str) -> GeneratorCost | None:
        for g in self.generators:
            if g.generator_id == generator_id:
                return g
        return None

    def to_unit_cost_map(self) -> dict[str, float]:
        return {g.generator_id: g.marginal_cost_eur_mwh for g in self.generators}


class CostCurveCalculator:
    def __init__(
        self,
        fuel_prices_csv: Path | None = None,
        carbon_price_eur_ton: float | None = None,
    ) -> None:
        self._csv_path = fuel_prices_csv or Path(DATASET_FUEL_PRICES)
        self._carbon_price = carbon_price_eur_ton if carbon_price_eur_ton is not None else 80.0
        self._fuel_prices_eur_mwh: dict[str, float] = {}
        self._loaded = False

    @property
    def fuel_prices(self) -> dict[str, float]:
        if not self._loaded:
            self._load_fuel_prices()
        return dict(self._fuel_prices_eur_mwh)

    @property
    def carbon_price(self) -> float:
        return self._carbon_price

    def _load_fuel_prices(self) -> None:
        self._loaded = True
        if not self._csv_path.exists():
            self._fuel_prices_eur_mwh = dict(_FUEL_EUR_MWH_DEFAULTS)
            return

        raw: dict[str, float] = {}
        try:
            with open(self._csv_path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    for col_name, value_str in row.items():
                        if col_name == "Datetime":
                            continue
                        try:
                            val = float(value_str)
                            if col_name not in raw:
                                raw[col_name] = val
                            else:
                                raw[col_name] = min(raw[col_name], val)
                        except (ValueError, TypeError):
                            continue
        except OSError:
            pass

        if not raw:
            self._fuel_prices_eur_mwh = dict(_FUEL_EUR_MWH_DEFAULTS)
            return

        for column_name, eur_gj in raw.items():
            self._fuel_prices_eur_mwh[column_name] = eur_gj * _GJ_TO_MWH

        self._fuel_prices_eur_mwh.setdefault("nuclear_fuel", _FUEL_EUR_MWH_DEFAULTS["nuclear_fuel"])

    def get_fuel_price_eur_mwh(self, fuel_type: str) -> float:
        if not self._loaded:
            self._load_fuel_prices()
        mapped = _FUEL_COLUMN_MAP.get(fuel_type, fuel_type)
        price = self._fuel_prices_eur_mwh.get(mapped)
        if price is not None:
            return price
        return _FUEL_EUR_MWH_DEFAULTS.get(mapped, 50.0)

    def calculate_marginal_cost(
        self,
        fuel_type: str,
        efficiency: float | None = None,
        capacity_mw: float = 100.0,
    ) -> float:
        gen_type = fuel_type.lower().replace(" ", "_")
        defaults = _GENERATOR_DEFAULTS.get(gen_type, _GENERATOR_DEFAULTS["gas"])
        eff = efficiency if efficiency is not None else defaults["efficiency"]
        eff = max(eff, 0.01)

        fuel_price = self.get_fuel_price_eur_mwh(fuel_type)
        fuel_cost = fuel_price / eff

        co2_factor = defaults["co2_factor_t_per_mwh"]
        co2_cost = co2_factor * self._carbon_price

        om_cost = defaults["om_cost_eur_mwh"]
        var_cost = defaults["variable_cost_eur_mwh"]

        return fuel_cost + co2_cost + om_cost + var_cost

    def calculate_for_generator(
        self,
        generator: dict[str, Any],
    ) -> GeneratorCost:
        gid = str(generator.get("generator_id", generator.get("name", "unknown")))
        fuel_type = str(generator.get("fuel_type", "gas"))
        capacity = float(generator.get("capacity_mw", generator.get("max_p_mw", 100.0)))
        efficiency = generator.get("efficiency_percent")
        if efficiency is not None:
            efficiency = float(efficiency) / 100.0

        gen_type = fuel_type.lower().replace(" ", "_")
        defaults = _GENERATOR_DEFAULTS.get(gen_type, _GENERATOR_DEFAULTS["gas"])
        eff = efficiency if efficiency is not None else defaults["efficiency"]
        eff = max(eff, 0.01)
        co2_factor = defaults["co2_factor_t_per_mwh"]
        om_cost = defaults["om_cost_eur_mwh"]
        var_cost = defaults["variable_cost_eur_mwh"]

        fuel_price = self.get_fuel_price_eur_mwh(fuel_type)
        fuel_cost = fuel_price / eff
        co2_cost = co2_factor * self._carbon_price
        marginal_cost = fuel_cost + co2_cost + om_cost + var_cost

        return GeneratorCost(
            generator_id=gid,
            fuel_type=fuel_type,
            capacity_mw=capacity,
            marginal_cost_eur_mwh=marginal_cost,
            fuel_cost_eur_mwh=fuel_cost,
            co2_cost_eur_mwh=co2_cost,
            om_cost_eur_mwh=om_cost,
            variable_cost_eur_mwh=var_cost,
            efficiency=eff,
            co2_factor_t_per_mwh=co2_factor,
            carbon_price_eur_ton=self._carbon_price,
        )

    def build_cost_curve(
        self,
        generators: list[dict[str, Any]],
        timestamp: datetime | None = None,
    ) -> CostCurveResult:
        if not self._loaded:
            self._load_fuel_prices()
        ts = timestamp or datetime.utcnow()
        gen_costs = [self.calculate_for_generator(g) for g in generators]
        return CostCurveResult(
            timestamp=ts,
            generators=gen_costs,
            fuel_prices=dict(self._fuel_prices_eur_mwh),
            carbon_price_eur_ton=self._carbon_price,
            data_source="csv" if self._csv_path.exists() else "default",
        )

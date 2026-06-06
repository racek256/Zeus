"""GridSimulator - the only authority over physical state evolution.

This class is the single source of truth for grid state in the simulation.
It loads topology and time-series data, maintains current network state and
historical cache, and provides step()/evaluate() interfaces.

Key rules:
- Only GridSimulator mutates physical state
- All agent actions go through validate() -> evaluate() pipeline
- Historical state is cached for rollback/scoring
- Missing generator actual hours are detected and skipped in metrics
"""

from __future__ import annotations

import csv
import copy
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from athenaai.config import (
    DATASET_FUEL_PRICES,
    DATASET_FORECASTS,
    DATASET_REALTIME,
    DATASET_ROOT,
    DATASET_SNAPSHOTS,
    DATASET_STATIC,
)
from athenaai.market.cost_curves import CostCurveCalculator
from athenaai.market.data_loader import MarketDataLoader, MarketDataSnapshot
from athenaai.physics.engine import (
    PhysicsStatus,
    run_ac_load_flow,
    run_frequency_response,
    run_parallel_n1,
    run_short_circuit,
    run_state_estimation,
)
from athenaai.physics.process_pool import PhysicsProcessPool
from athenaai.trace import trace, trace_scope
from athenaai.schema import (
    ActionBundle,
    ActionValidationResult,
    BusReading,
    BranchReading,
    ForecastDataPoint,
    GeneratorReading,
    LoadForecastBundle,
    LoadReading,
    MarketState,
    NetworkConstraints,
    ObservationBundle,
    RenewablesForecastBundle,
    ScadaSnapshot,
    validate_action_bundle,
)


@dataclass
class HistoricalState:
    hour_index: int
    timestamp: datetime
    network_state: dict[str, Any]
    observation: ObservationBundle
    action: ActionBundle | None
    load_flow_result: dict[str, Any] | None


class GridSimulator:
    def __init__(
        self,
        dataset_root: Path | None = None,
        start_hour: int = 0,
        allow_fallback_physics: bool = False,
        market_data_loader: MarketDataLoader | None = None,
        cost_calculator: CostCurveCalculator | None = None,
    ) -> None:
        self._dataset_root = dataset_root or DATASET_ROOT
        self._start_hour = start_hour
        self._current_hour = start_hour
        self._allow_fallback_physics = allow_fallback_physics

        self._topology: dict[str, Any] = {}
        self._gens_ts: dict[int, dict[str, float]] = {}
        self._loads_ts: dict[int, dict[str, float]] = {}
        self._fuel_prices: dict[str, float] = {}
        self._load_forecasts: dict[int, dict[str, Any]] = {}
        self._wind_forecasts: dict[int, dict[str, Any]] = {}
        self._solar_forecasts: dict[int, dict[str, Any]] = {}

        self._current_network_state: dict[str, Any] = {}
        self._historical: list[HistoricalState] = []

        self._missing_gen_hours: set[int] = set()

        self._constraints = NetworkConstraints()
        self._initialized = False

        self._market_loader = market_data_loader or MarketDataLoader()
        self._cost_calculator = cost_calculator or CostCurveCalculator()
        self._market_snapshot: MarketDataSnapshot | None = None

        self._physics_pool: PhysicsProcessPool | None = None

    @staticmethod
    def _float_or_default(value: Any, default: float = 0.0) -> float:
        if value is None or value == "":
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _bool_or_default(value: Any, default: bool = True) -> bool:
        if value is None or value == "":
            return default
        if isinstance(value, bool):
            return value
        return str(value).lower() in {"1", "true", "yes", "y"}

    @staticmethod
    def _normalize_datetime_hour(
        row: dict[str, str],
        timestamp_to_hour: dict[str, int],
    ) -> int:
        hour_value = row.get("hour")
        if hour_value not in (None, ""):
            return int(hour_value)

        timestamp = row.get("datetime", "")
        if timestamp not in timestamp_to_hour:
            timestamp_to_hour[timestamp] = len(timestamp_to_hour)
        return timestamp_to_hour[timestamp]

    @property
    def current_hour(self) -> int:
        return self._current_hour

    @property
    def current_timestamp(self) -> datetime:
        return datetime(2026, 1, 1, 0, 0, 0) + timedelta(hours=self._current_hour)

    @property
    def constraints(self) -> NetworkConstraints:
        return self._constraints

    @property
    def allow_fallback_physics(self) -> bool:
        return self._allow_fallback_physics

    @property
    def current_network_state(self) -> dict[str, Any]:
        return self._current_network_state

    @property
    def cost_calculator(self) -> CostCurveCalculator:
        return self._cost_calculator

    @property
    def market_snapshot(self) -> MarketDataSnapshot | None:
        return self._market_snapshot

    @property
    def physics_pool(self) -> PhysicsProcessPool | None:
        return self._physics_pool

    def get_or_create_physics_pool(self, max_workers: int | None = None) -> PhysicsProcessPool:
        if self._physics_pool is None or not self._physics_pool.is_available:
            max_w = max_workers or 2
            self._physics_pool = PhysicsProcessPool(max_workers=max_w)
        return self._physics_pool

    def shutdown_physics_pool(self) -> None:
        if self._physics_pool is not None:
            try:
                self._physics_pool.shutdown(wait=False, timeout=10.0)
            except Exception:
                pass
            self._physics_pool = None

    def _sync_current_network_state_to_hour(self, hour: int) -> None:
        if not self._current_network_state:
            self._current_network_state = copy.deepcopy(self._topology)

        gens_for_hour = self._gens_ts.get(hour, {})
        for generator in self._current_network_state.get("generators", []):
            gen_id = generator.get("generator_id", generator.get("name", ""))
            if gen_id in gens_for_hour:
                generator["p_mw"] = gens_for_hour[gen_id]

        loads_for_hour = self._loads_ts.get(hour, {})
        for load in self._current_network_state.get("loads", []):
            load_id = load.get("load_id", load.get("name", ""))
            if load_id in loads_for_hour:
                load["p_mw"] = loads_for_hour[load_id]

    def load_static_topology(self) -> dict[str, Any]:
        static_path = self._dataset_root / "data" / "static"
        topology: dict[str, Any] = {"buses": [], "branches": [], "generators": [], "loads": []}

        buses_file = static_path / "buses.csv"
        if buses_file.exists():
            with open(buses_file, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    bus_id = row.get("bus_id") or row.get("bus_name") or row.get("name") or ""
                    topology["buses"].append(
                        {
                            **dict(row),
                            "bus_id": bus_id,
                            "name": row.get("name") or bus_id,
                            "vn_kv": self._float_or_default(row.get("vn_kv") or row.get("v_rated_kv"), 110.0),
                            "is_slack": self._bool_or_default(row.get("is_slack"), False),
                            "min_v_pu": self._float_or_default(row.get("min_v_pu"), 0.95),
                            "max_v_pu": self._float_or_default(row.get("max_v_pu"), 1.05),
                            "in_service": self._bool_or_default(row.get("in_service"), True),
                        }
                    )

        if topology["buses"]:
            self._constraints = NetworkConstraints(
                max_branch_loading_percent=self._constraints.max_branch_loading_percent,
                min_voltage_pu=min(float(bus.get("min_v_pu", self._constraints.min_voltage_pu)) for bus in topology["buses"]),
                max_voltage_pu=max(float(bus.get("max_v_pu", self._constraints.max_voltage_pu)) for bus in topology["buses"]),
                max_frequency_deviation_hz=self._constraints.max_frequency_deviation_hz,
                min_frequency_hz=self._constraints.min_frequency_hz,
                max_frequency_hz=self._constraints.max_frequency_hz,
            )

        branches_file = static_path / "branches.csv"
        if branches_file.exists():
            with open(branches_file, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    branch_id = row.get("branch_id") or row.get("branch_name") or row.get("name") or ""
                    topology["branches"].append(
                        {
                            **dict(row),
                            "branch_id": branch_id,
                            "name": row.get("name") or branch_id,
                            "from_bus": row.get("from_bus", ""),
                            "to_bus": row.get("to_bus", ""),
                            "r_ohm_per_km": self._float_or_default(row.get("r_ohm_per_km") or row.get("r_ohm"), 0.1),
                            "x_ohm_per_km": self._float_or_default(row.get("x_ohm_per_km") or row.get("x_ohm"), 0.4),
                            "c_nf_per_km": self._float_or_default(row.get("c_nf_per_km"), 10.0),
                            "max_i_ka": self._float_or_default(row.get("max_i_ka"), 1.0),
                            "in_service": self._bool_or_default(row.get("in_service"), True),
                        }
                    )

        generators_file = static_path / "generators.csv"
        if not generators_file.exists():
            generators_file = static_path / "gens.csv"
        if generators_file.exists():
            with open(generators_file, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    gen_id = row.get("generator_id") or row.get("gen_name") or row.get("name") or ""
                    bus = row.get("bus") or row.get("bus_name") or ""
                    topology["generators"].append(
                        {
                            **dict(row),
                            "generator_id": gen_id,
                            "name": row.get("name") or gen_id,
                            "bus": bus,
                            "p_mw": self._float_or_default(row.get("p_mw"), 0.0),
                            "min_p_mw": self._float_or_default(row.get("min_p_mw"), 0.0),
                            "max_p_mw": self._float_or_default(row.get("max_p_mw"), 1000.0),
                            "in_service": self._bool_or_default(row.get("in_service"), True),
                        }
                    )

        loads_file = static_path / "loads.csv"
        if loads_file.exists():
            with open(loads_file, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    load_id = row.get("load_id") or row.get("load_name") or row.get("name") or ""
                    bus = row.get("bus") or row.get("bus_name") or ""
                    topology["loads"].append(
                        {
                            **dict(row),
                            "load_id": load_id,
                            "name": row.get("name") or load_id,
                            "bus": bus,
                            "p_mw": self._float_or_default(row.get("p_mw"), 0.0),
                            "q_mvar": self._float_or_default(row.get("q_mvar"), 0.0),
                            "in_service": self._bool_or_default(row.get("in_service"), True),
                        }
                    )

        self._topology = topology
        return topology

    def load_realtime_data(self) -> None:
        gens_ts_path = self._dataset_root / "data" / "realtime" / "gens_ts.csv"
        if gens_ts_path.exists():
            with open(gens_ts_path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                timestamp_to_hour: dict[str, int] = {}
                for row in reader:
                    hour = self._normalize_datetime_hour(row, timestamp_to_hour)
                    gen_id = row.get("generator_id") or row.get("gen_name") or ""
                    actual_mw_str = row.get("actual_mw") or row.get("p_mw") or ""
                    if actual_mw_str == "" or actual_mw_str.lower() == "nan":
                        self._missing_gen_hours.add(hour)
                        continue
                    if hour not in self._gens_ts:
                        self._gens_ts[hour] = {}
                    self._gens_ts[hour][gen_id] = float(actual_mw_str)

        loads_ts_path = self._dataset_root / "data" / "realtime" / "loads_ts.csv"
        if loads_ts_path.exists():
            with open(loads_ts_path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                timestamp_to_hour: dict[str, int] = {}
                for row in reader:
                    hour = self._normalize_datetime_hour(row, timestamp_to_hour)
                    load_id = row.get("load_id") or row.get("load_name") or ""
                    actual_mw_str = row.get("actual_mw") or row.get("p_mw") or ""
                    if actual_mw_str == "" or actual_mw_str.lower() == "nan":
                        continue
                    if hour not in self._loads_ts:
                        self._loads_ts[hour] = {}
                    self._loads_ts[hour][load_id] = float(actual_mw_str)

    def load_fuel_prices(self) -> dict[str, float]:
        fuel_prices = self._cost_calculator.fuel_prices
        if fuel_prices:
            self._fuel_prices = fuel_prices
            return self._fuel_prices

        fuel_path = Path(DATASET_FUEL_PRICES)
        if fuel_path.exists():
            with open(fuel_path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    fuel_type = row.get("fuel_type", "")
                    price_str = row.get("price_eur_mwh", "0")
                    if fuel_type and price_str:
                        try:
                            self._fuel_prices[fuel_type] = float(price_str)
                        except ValueError:
                            continue
        return self._fuel_prices

    def load_forecasts(self) -> None:
        da_load_path = self._dataset_root / "data" / "forecasts" / "DA" / "Load"
        if da_load_path.exists():
            for csv_file in da_load_path.glob("*.csv"):
                with open(csv_file, newline="", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        hour = int(row.get("hour", -1))
                        if hour not in self._load_forecasts:
                            self._load_forecasts[hour] = {}
                        region = row.get("region", csv_file.stem)
                        self._load_forecasts[hour][region] = {
                            "forecast_mw": float(row.get("forecast_mw", 0)),
                            "lower_bound": float(row.get("lower_bound", 0)),
                            "upper_bound": float(row.get("upper_bound", 0)),
                        }

        wind_path = self._dataset_root / "data" / "forecasts" / "DA" / "Wind"
        if wind_path.exists():
            for csv_file in wind_path.glob("*.csv"):
                with open(csv_file, newline="", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        hour = int(row.get("hour", -1))
                        if hour not in self._wind_forecasts:
                            self._wind_forecasts[hour] = {}
                        unit_id = row.get("unit_id", csv_file.stem)
                        self._wind_forecasts[hour][unit_id] = {
                            "forecast_mw": float(row.get("forecast_mw", 0)),
                            "lower_bound": float(row.get("lower_bound", 0)),
                            "upper_bound": float(row.get("upper_bound", 0)),
                        }

        solar_path = self._dataset_root / "data" / "forecasts" / "DA" / "Solar"
        if solar_path.exists():
            for csv_file in solar_path.glob("*.csv"):
                with open(csv_file, newline="", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        hour = int(row.get("hour", -1))
                        if hour not in self._solar_forecasts:
                            self._solar_forecasts[hour] = {}
                        unit_id = row.get("unit_id", csv_file.stem)
                        self._solar_forecasts[hour][unit_id] = {
                            "forecast_mw": float(row.get("forecast_mw", 0)),
                            "lower_bound": float(row.get("lower_bound", 0)),
                            "upper_bound": float(row.get("upper_bound", 0)),
                        }

    def load_snapshot(self, hour: int) -> dict[str, Any] | None:
        snapshot_file = self._dataset_root / "data" / "snapshots" / f" snapshot_{hour:04d}.json"
        if not snapshot_file.exists():
            snapshot_file = self._dataset_root / "data" / "snapshots" / f"snapshot_{hour:04d}.json"
        if snapshot_file.exists():
            with open(snapshot_file, encoding="utf-8") as f:
                return json.load(f)
        return None

    def initialize(self) -> None:
        self.load_static_topology()
        self.load_realtime_data()
        self.load_fuel_prices()
        self.load_forecasts()
        self._current_network_state = copy.deepcopy(self._topology)
        self._sync_current_network_state_to_hour(self._current_hour)
        self._initialized = True

    def load_market_data(self, force_refresh: bool = False) -> MarketDataSnapshot:
        if not force_refresh and self._market_snapshot is not None:
            return self._market_snapshot
        sim_date = self.current_timestamp.date()
        try:
            self._market_snapshot = self._market_loader.get_market_snapshot(sim_date)
        except Exception:
            self._market_snapshot = MarketDataSnapshot(
                timestamp=self.current_timestamp,
                data_source="error_fallback",
            )
        return self._market_snapshot

    def get_observation(self, hour: int | None = None) -> ObservationBundle:
        h = hour if hour is not None else self._current_hour
        ts = datetime(2026, 1, 1, 0, 0, 0) + timedelta(hours=h)

        if not self._topology:
            self.load_static_topology()
        source_state = self._current_network_state if self._current_network_state else self._topology

        bus_readings: list[BusReading] = []
        for b in source_state.get("buses", []):
            bus_readings.append(
                BusReading(
                    bus_id=b.get("bus_id", str(b.get("name", ""))),
                    voltage_pu=1.0,
                    voltage_angle_deg=0.0,
                )
            )

        branch_readings: list[BranchReading] = []
        for br in source_state.get("branches", []):
            branch_readings.append(
                BranchReading(
                    branch_id=br.get("branch_id", str(br.get("name", ""))),
                    from_bus=str(br.get("from_bus", "")),
                    to_bus=str(br.get("to_bus", "")),
                    flow_mw=0.0,
                    loading_percent=0.0,
                )
            )

        gen_readings: list[GeneratorReading] = []
        gens_for_hour = self._gens_ts.get(h, {})
        for g in source_state.get("generators", []):
            gid = g.get("generator_id", g.get("name", ""))
            generation_mw = float(g.get("p_mw", gens_for_hour.get(gid, 0.0)))
            gen_readings.append(
                GeneratorReading(
                    generator_id=gid,
                    bus=str(g.get("bus", "")),
                    generation_mw=generation_mw,
                    setpoint_mw=generation_mw,
                    status="online" if self._bool_or_default(g.get("in_service"), True) else "offline",
                    fuel_type=g.get("fuel_type"),
                )
            )

        load_readings: list[LoadReading] = []
        loads_for_hour = self._loads_ts.get(h, {})
        for l in source_state.get("loads", []):
            lid = l.get("load_id", l.get("name", ""))
            demand_mw = float(l.get("p_mw", loads_for_hour.get(lid, 0.0)))
            load_readings.append(
                LoadReading(
                    load_id=lid,
                    bus=str(l.get("bus", "")),
                    demand_mw=demand_mw,
                    status="connected" if self._bool_or_default(l.get("in_service"), True) else "disconnected",
                )
            )

        total_gen = sum(g.generation_mw for g in gen_readings)
        total_load = sum(ld.demand_mw for ld in load_readings)

        scada = ScadaSnapshot(
            timestamp=ts,
            buses=tuple(bus_readings),
            branches=tuple(branch_readings),
            generators=tuple(gen_readings),
            loads=tuple(load_readings),
            total_generation_mw=total_gen,
            total_load_mw=total_load,
        )

        load_fc_bundles: list[LoadForecastBundle] = []
        fc_data = self._load_forecasts.get(h, {})
        for region, fc in fc_data.items():
            load_fc_bundles.append(
                LoadForecastBundle(
                    region=region,
                    timestamp=ts,
                    forecasts=(
                        ForecastDataPoint(
                            horizon_h=1.0,
                            value=fc["forecast_mw"],
                            lower_bound=fc["lower_bound"],
                            upper_bound=fc["upper_bound"],
                        ),
                    ),
                )
            )

        renewables_fc: list[RenewablesForecastBundle] = []
        wind_data = self._wind_forecasts.get(h, {})
        for unit_id, fc in wind_data.items():
            renewables_fc.append(
                RenewablesForecastBundle(
                    unit_id=unit_id,
                    unit_type="wind",
                    timestamp=ts,
                    forecasts=(
                        ForecastDataPoint(
                            horizon_h=1.0,
                            value=fc["forecast_mw"],
                            lower_bound=fc["lower_bound"],
                            upper_bound=fc["upper_bound"],
                        ),
                    ),
                )
            )
        solar_data = self._solar_forecasts.get(h, {})
        for unit_id, fc in solar_data.items():
            renewables_fc.append(
                RenewablesForecastBundle(
                    unit_id=unit_id,
                    unit_type="solar",
                    timestamp=ts,
                    forecasts=(
                        ForecastDataPoint(
                            horizon_h=1.0,
                            value=fc["forecast_mw"],
                            lower_bound=fc["lower_bound"],
                            upper_bound=fc["upper_bound"],
                        ),
                    ),
                )
            )

        snap = self.load_market_data()
        marginal = 50.0
        imbalance = 55.0
        if snap.day_ahead_prices:
            day_prices = list(snap.day_ahead_prices.values())
            marginal = sum(day_prices) / len(day_prices)
            specific_hour = h % 24
            if specific_hour in snap.day_ahead_prices:
                marginal = snap.day_ahead_prices[specific_hour]
        if snap.imbalance_prices:
            imb_vals = list(snap.imbalance_prices.values())
            if imb_vals:
                imbalance = sum(imb_vals) / len(imb_vals)
        reserve_total = sum(snap.generation_forecast.values()) * 0.05
        reserve_req = max(snap.generation_forecast.values()) * 0.03 if snap.generation_forecast else 400.0

        market = MarketState(
            timestamp=ts,
            system_marginal_price_eur_mwh=marginal,
            imbalance_price_eur_mwh=imbalance,
            total_reserve_mw=reserve_total if reserve_total > 0 else 500.0,
            reserve_requirement_mw=reserve_req if reserve_req > 0 else 400.0,
            atc_values={"DE": 1500.0, "SK": 1000.0, "AT": 800.0, "PL": 600.0},
            day_ahead_prices=snap.day_ahead_prices,
            imbalance_prices=snap.imbalance_prices,
            crossborder_schedules=snap.crossborder_flows,
            reserve_status={
                "FCR": reserve_req * 0.15 if reserve_req > 0 else 60.0,
                "aFRR": reserve_req * 0.35 if reserve_req > 0 else 140.0,
                "mFRR": reserve_req * 0.50 if reserve_req > 0 else 200.0,
            },
            carbon_price_eur_ton=snap.carbon_price_eur_ton,
            data_source=snap.data_source,
            price_uncertainty_eur_mwh=5.0,
        )

        return ObservationBundle(
            hour_index=h,
            timestamp=ts,
            scada=scada,
            load_forecasts=tuple(load_fc_bundles),
            renewables_forecasts=tuple(renewables_fc),
            network_constraints=self._constraints,
            market_state=market,
            is_intraday=(h < self._current_hour),
        )

    def step(self, hour: int) -> ObservationBundle:
        with trace_scope("GridSimulator.step", hour=hour):
            self._current_hour = hour
            self._sync_current_network_state_to_hour(hour)
            return self.get_observation(hour)

    def validate_action(
        self, action: ActionBundle, observation: ObservationBundle
    ) -> ActionValidationResult:
        return validate_action_bundle(action, observation)

    def evaluate(
        self, action: ActionBundle, observation: ObservationBundle
    ) -> dict[str, Any]:
        return self._evaluate_action(action, observation, commit=True)

    def simulate_action(
        self, action: ActionBundle, observation: ObservationBundle
    ) -> dict[str, Any]:
        """Predict action acceptance without committing state or history."""
        return self._evaluate_action(action, observation, commit=False)

    def _run_load_flow(
        self, network_state: dict[str, Any], simulated_time: datetime | None = None
    ) -> Any:
        pool = self._physics_pool
        if pool is not None and pool.is_available:
            try:
                future = pool.submit(run_ac_load_flow, network_state, simulated_time)
                return future.result(timeout=30.0)
            except Exception:
                trace("GridSimulator._run_load_flow.process_pool_failed", error_type="ProcessError")
        return run_ac_load_flow(network_state, simulated_time)

    def _evaluate_action(
        self, action: ActionBundle, observation: ObservationBundle, commit: bool
    ) -> dict[str, Any]:
        with trace_scope(
            "GridSimulator.evaluate" if commit else "GridSimulator.simulate_action",
            agent_id=action.agent_id,
            generator_setpoint_changes=len(action.generator_setpoint_changes),
            load_shedding_flags=len(action.load_shedding_flags),
            commit=commit,
        ):
            validation = validate_action_bundle(action, observation)
            trace(
                "GridSimulator.evaluate.validation",
                valid=validation.valid,
                errors=len(validation.errors),
                warnings=len(validation.warnings),
            )
            if not validation.valid:
                return {
                    "accepted": False,
                    "validation_errors": validation.errors,
                    "validation_warnings": validation.warnings,
                    "load_flow_result": None,
                }

            modified_state = copy.deepcopy(self._current_network_state)

            for change in action.generator_setpoint_changes:
                trace(
                    "GridSimulator.evaluate.apply_generator_setpoint",
                    generator_id=change.generator_id,
                    new_setpoint_mw=change.new_setpoint_mw,
                )
                for g in modified_state.get("generators", []):
                    if g.get("generator_id") == change.generator_id:
                        g["p_mw"] = change.new_setpoint_mw

            for flag in action.load_shedding_flags:
                trace(
                    "GridSimulator.evaluate.apply_load_shedding",
                    load_id=flag.load_id,
                    shed_mw=flag.shed_mw,
                )
                for l in modified_state.get("loads", []):
                    if l.get("load_id") == flag.load_id:
                        l["p_mw"] = max(0.0, l.get("p_mw", 0.0) - flag.shed_mw)

            with trace_scope("GridSimulator.evaluate.run_ac_load_flow", hour=self._current_hour):
                lf_result = self._run_load_flow(modified_state, self.current_timestamp)

            violations = lf_result.violations(
                self._constraints.max_branch_loading_percent,
                self._constraints.min_voltage_pu,
                self._constraints.max_voltage_pu,
            )

            fallback_blocked = (
                lf_result.status == PhysicsStatus.FALLBACK_USED
                and not self._allow_fallback_physics
            )
            accepted = lf_result.converged and len(violations) == 0 and not fallback_blocked
            trace(
                "GridSimulator.evaluate.load_flow_result",
                accepted=accepted,
                converged=lf_result.converged,
                status=lf_result.status.value,
                violations=len(violations),
                fallback_blocked=fallback_blocked,
            )
            if accepted and commit:
                self._current_network_state = copy.deepcopy(modified_state)

            if commit:
                historical_entry = HistoricalState(
                    hour_index=self._current_hour,
                    timestamp=self.current_timestamp,
                    network_state=copy.deepcopy(modified_state),
                    observation=observation,
                    action=action,
                    load_flow_result={
                        "converged": lf_result.converged,
                        "status": lf_result.status.value,
                        "violations": violations,
                    },
                )
                self._historical.append(historical_entry)

            return {
                "accepted": accepted,
                "committed": accepted and commit,
                "validation_errors": validation.errors,
                "validation_warnings": validation.warnings,
                "load_flow_result": {
                    "converged": lf_result.converged,
                    "status": lf_result.status.value,
                    "violations": violations,
                    "message": lf_result.message,
                    "fallback_blocked": fallback_blocked,
                },
            }

    def get_historical(self) -> list[HistoricalState]:
        return list(self._historical)

    def get_missing_gen_hours(self) -> set[int]:
        return set(self._missing_gen_hours)

    def validate_state_with_estimation(
        self,
        measurements: dict[str, Any] | None = None,
        min_voltage_pu: float | None = None,
        max_voltage_pu: float | None = None,
    ) -> dict[str, Any]:
        min_v = min_voltage_pu or self._constraints.min_voltage_pu
        max_v = max_voltage_pu or self._constraints.max_voltage_pu

        with trace_scope("GridSimulator.validate_state_with_estimation"):
            result = run_state_estimation(
                self._current_network_state,
                measurements=measurements,
                min_voltage_pu=min_v,
                max_voltage_pu=max_v,
                simulated_time=self.current_timestamp,
            )
            bus_estimates = {
                bid: {"vm_pu": vm_pu, "va_deg": va_deg}
                for bid, vm_pu, va_deg in result.bus_estimates
            }
            return {
                "success": result.success,
                "status": result.status.value,
                "bus_estimates": bus_estimates,
                "estimated_v_mag_pu": result.estimated_v_mag_pu,
                "estimated_v_angle_deg": result.estimated_v_angle_deg,
                "chi_squared": result.chi_squared,
                "bad_data_detected": result.bad_data_detected,
                "suspicious_measurements": list(result.suspicious_measurements),
                "message": result.message,
            }

    def run_protection_coordination(
        self,
        fault_bus: str = "",
        fault_type: str = "3ph",
    ) -> dict[str, Any]:
        with trace_scope("GridSimulator.run_protection_coordination", fault_bus=fault_bus, fault_type=fault_type):
            result = run_short_circuit(
                self._current_network_state,
                fault_bus=fault_bus,
                fault_type=fault_type,
                simulated_time=self.current_timestamp,
            )
            bus_voltages = {
                bid: {"vm_pu": vm_pu, "va_deg": va_deg}
                for bid, vm_pu, va_deg in result.bus_voltages
            }
            gen_contributions = {
                gen_id: ikss_ka
                for gen_id, ikss_ka in result.generator_contributions
            }
            return {
                "success": result.success,
                "status": result.status.value,
                "fault_current_ka": result.fault_current_ka,
                "fault_power_mva": result.fault_power_mva,
                "bus_voltages": bus_voltages,
                "generator_contributions": gen_contributions,
                "message": result.message,
            }

    def assess_stability(
        self,
        disturbance: dict[str, Any] | None = None,
        min_frequency_hz: float | None = None,
    ) -> dict[str, Any]:
        min_f = min_frequency_hz or self._constraints.min_frequency_hz

        with trace_scope("GridSimulator.assess_stability"):
            result = run_frequency_response(
                self._current_network_state,
                disturbance=disturbance,
                min_frequency_hz=min_f,
                simulated_time=self.current_timestamp,
            )
            return {
                "success": result.success,
                "status": result.status.value,
                "frequency_nadir_hz": result.frequency_nadir_hz,
                "rocof_hz_s": result.rocof_hz_s,
                "settling_frequency_hz": result.settling_frequency_hz,
                "system_inertia_s": result.system_inertia_s,
                "critical_clearing_time_cycles": result.critical_clearing_time_cycles,
                "delta_p_mw": result.delta_p_mw,
                "message": result.message,
            }

    def run_parallel_n1_scan(
        self,
        contingencies: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        with trace_scope("GridSimulator.run_parallel_n1_scan"):
            result = run_parallel_n1(
                self._current_network_state,
                contingencies=contingencies,
                max_loading_percent=self._constraints.max_branch_loading_percent,
                min_voltage_pu=self._constraints.min_voltage_pu,
                max_voltage_pu=self._constraints.max_voltage_pu,
                simulated_time=self.current_timestamp,
                pool=self._physics_pool,
            )
            return {
                "passed": result.passed,
                "status": result.status.value,
                "secure_contingencies": list(result.secure_contingencies),
                "violated_contingencies": list(result.violated_contingencies),
                "num_contingencies": len(result.contingencies),
                "message": result.message,
            }

    def rollback_to_hour(self, hour: int) -> None:
        self._historical = [h for h in self._historical if h.hour_index < hour]
        self._current_hour = hour

"""Strict observation and action schemas for AthenaAI simulation.

All schemas use dataclasses with validation. ObservationBundle is the canonical
view of grid state exposed to agents. ActionBundle represents validated agent
decisions before execution by the GridSimulator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class ViolationType(str, Enum):
    """Types of physics constraint violations."""

    THERMAL_OVERLOAD = "thermal_overload"
    VOLTAGE_HIGH = "voltage_high"
    VOLTAGE_LOW = "voltage_low"
    RAMP_RATE = "ramp_rate"
    ISLANDING = "islanding"
    NON_CONVERGENCE = "non_convergence"
    N1_SECURITY_FAILURE = "n1_security_failure"


@dataclass(frozen=True)
class BusReading:
    """SCADA reading for a single bus."""

    bus_id: str
    voltage_pu: float
    voltage_angle_deg: float
    frequency_proxy_hz: float = 50.0


@dataclass(frozen=True)
class BranchReading:
    """SCADA reading for a single branch (line or transformer)."""

    branch_id: str
    from_bus: str
    to_bus: str
    flow_mw: float
    loading_percent: float
    status: str = "closed"


@dataclass(frozen=True)
class GeneratorReading:
    """SCADA reading for a single generator."""

    generator_id: str
    bus: str
    generation_mw: float
    setpoint_mw: float
    status: str = "online"
    fuel_type: str | None = None


@dataclass(frozen=True)
class LoadReading:
    """SCADA reading for a single load."""

    load_id: str
    bus: str
    demand_mw: float
    status: str = "connected"


@dataclass(frozen=True)
class ScadaSnapshot:
    """SCADA telemetry snapshot at a point in time.

    This is the real-time observation of the grid state. It excludes
    future actuals - only information available at the simulated time.
    """

    timestamp: datetime
    buses: tuple[BusReading, ...]
    branches: tuple[BranchReading, ...]
    generators: tuple[GeneratorReading, ...]
    loads: tuple[LoadReading, ...]
    system_frequency_hz: float = 50.0
    total_generation_mw: float = 0.0
    total_load_mw: float = 0.0
    interchange_mw: float = 0.0

    def get_bus(self, bus_id: str) -> BusReading | None:
        for b in self.buses:
            if b.bus_id == bus_id:
                return b
        return None

    def get_branch(self, branch_id: str) -> BranchReading | None:
        for b in self.branches:
            if b.branch_id == branch_id:
                return b
        return None

    def get_generator(self, generator_id: str) -> GeneratorReading | None:
        for g in self.generators:
            if g.generator_id == generator_id:
                return g
        return None

    def get_load(self, load_id: str) -> LoadReading | None:
        for l in self.loads:
            if l.load_id == load_id:
                return l
        return None


@dataclass(frozen=True)
class ForecastDataPoint:
    """Single forecast data point with uncertainty bounds."""

    horizon_h: float
    value: float
    lower_bound: float
    upper_bound: float
    confidence: float = 0.95


@dataclass(frozen=True)
class LoadForecastBundle:
    """Load forecast for a region."""

    region: str
    timestamp: datetime
    forecasts: tuple[ForecastDataPoint, ...]


@dataclass(frozen=True)
class RenewablesForecastBundle:
    """Wind/solar forecast bundle."""

    unit_id: str
    unit_type: str  # "wind" or "solar"
    timestamp: datetime
    forecasts: tuple[ForecastDataPoint, ...]


@dataclass(frozen=True)
class NetworkConstraints:
    """Network security constraints."""

    max_branch_loading_percent: float = 100.0
    min_voltage_pu: float = 0.95
    max_voltage_pu: float = 1.05
    max_frequency_deviation_hz: float = 0.5
    min_frequency_hz: float = 49.5
    max_frequency_hz: float = 50.5


@dataclass(frozen=True)
class MarketState:
    """Current market state with real European electricity market data.

    Advisory layer only - never mutates physical state. Populated from
    ENTSO-E Transparency Platform, OTE (Czech market operator), and
    local fuel price datasets.
    """

    timestamp: datetime
    system_marginal_price_eur_mwh: float
    imbalance_price_eur_mwh: float
    total_reserve_mw: float
    reserve_requirement_mw: float
    atc_values: dict[str, float] = field(default_factory=dict)  # border -> MW

    # --- New real-market fields (backward-compatible with defaults) ---

    # Day-ahead hourly prices for next 24h (CET/CEST), hour 0-23 -> EUR/MWh
    day_ahead_prices: dict[int, float] = field(default_factory=dict)

    # Imbalance settlement prices: "upward" and "downward" EUR/MWh
    imbalance_prices: dict[str, float] = field(default_factory=dict)

    # Scheduled cross-border interchanges per border code (e.g. "DE", "SK") -> MW
    crossborder_schedules: dict[str, float] = field(default_factory=dict)

    # Reserve availability by type: FCR, aFRR, mFRR -> MW available
    reserve_status: dict[str, float] = field(default_factory=dict)

    # EU ETS carbon price (EUR/tCO2), default based on 2024-2025 range
    carbon_price_eur_ton: float = 75.0

    # Real market data source: "live", "cached", "fallback", or "default"
    data_source: str = "default"

    # Uncertainty estimate for marginal price (std dev, EUR/MWh)
    price_uncertainty_eur_mwh: float = 5.0


@dataclass(frozen=True)
class ObservationBundle:
    """Complete observation presented to agents.

    Contains all information available at the simulated decision time.
    Agents must use uncertainty bounds, not just point estimates.
    """

    hour_index: int
    timestamp: datetime
    scada: ScadaSnapshot
    load_forecasts: tuple[LoadForecastBundle, ...]
    renewables_forecasts: tuple[RenewablesForecastBundle, ...]
    network_constraints: NetworkConstraints
    market_state: MarketState
    is_intraday: bool = False  # True if actuals for elapsed hours are revealed

    def has_violations(self) -> bool:
        """Check if current SCADA state violates any constraints."""
        for bus in self.scada.buses:
            if bus.voltage_pu < self.network_constraints.min_voltage_pu:
                return True
            if bus.voltage_pu > self.network_constraints.max_voltage_pu:
                return True
        for branch in self.scada.branches:
            if branch.loading_percent > self.network_constraints.max_branch_loading_percent:
                return True
        return False


@dataclass(frozen=True)
class GeneratorSetpointChange:
    """Request to change a generator's active power setpoint."""

    generator_id: str
    new_setpoint_mw: float
    ramp_rate_mw_per_min: float | None = None


@dataclass(frozen=True)
class RedispatchRequest:
    """Request for redispatch from a specific unit."""

    generator_id: str
    region: str
    upward_mw: float = 0.0
    downward_mw: float = 0.0
    reason: str = ""


@dataclass(frozen=True)
class LoadSheddingFlag:
    """Instruction to shed load at a specific bus/region."""

    load_id: str
    region: str
    shed_mw: float
    priority: int = 1  # 1=highest


@dataclass(frozen=True)
class InterconnectFlowAdjustment:
    """Request to adjust cross-border flow."""

    border: str  # DE, SK, AT, PL
    target_flow_mw: float
    current_flow_mw: float


@dataclass(frozen=True)
class ActionBundle:
    """Validated action bundle from agent.

    All actions must be validated before execution by GridSimulator.
    """

    timestamp: datetime
    agent_id: str
    generator_setpoint_changes: tuple[GeneratorSetpointChange, ...] = field(
        default_factory=tuple
    )
    redispatch_requests: tuple[RedispatchRequest, ...] = field(default_factory=tuple)
    load_shedding_flags: tuple[LoadSheddingFlag, ...] = field(default_factory=tuple)
    interconnect_flow_adjustments: tuple[InterconnectFlowAdjustment, ...] = field(
        default_factory=tuple
    )

    def is_empty(self) -> bool:
        return (
            len(self.generator_setpoint_changes) == 0
            and len(self.redispatch_requests) == 0
            and len(self.load_shedding_flags) == 0
            and len(self.interconnect_flow_adjustments) == 0
        )


@dataclass
class ActionValidationResult:
    """Result of validating an ActionBundle before execution."""

    valid: bool
    errors: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def __bool__(self) -> bool:
        return self.valid


def validate_action_bundle(
    action: ActionBundle, observation: ObservationBundle
) -> ActionValidationResult:
    """Validate an action bundle against current observation.

    Returns errors for hard violations and warnings for soft issues.
    """
    errors: list[str] = []
    warnings: list[str] = []

    # Check generator setpoint changes against constraints
    for change in action.generator_setpoint_changes:
        gen = observation.scada.get_generator(change.generator_id)
        if gen is None:
            errors.append(f"Unknown generator: {change.generator_id}")
            continue

        # Check ramp rate (if applicable)
        if change.ramp_rate_mw_per_min is not None:
            max_ramp = change.ramp_rate_mw_per_min * 60  # per hour
            delta = abs(change.new_setpoint_mw - gen.setpoint_mw)
            if delta > max_ramp:
                errors.append(
                    f"Generator {change.generator_id} ramp rate violation: "
                    f"delta {delta:.1f}MW exceeds limit {max_ramp:.1f}MW"
                )

        # Check voltage limits at generator bus
        bus = observation.scada.get_bus(gen.bus)
        if bus is not None:
            if bus.voltage_pu < observation.network_constraints.min_voltage_pu:
                warnings.append(
                    f"Generator {change.generator_id} at low-voltage bus {gen.bus}"
                )
            if bus.voltage_pu > observation.network_constraints.max_voltage_pu:
                warnings.append(
                    f"Generator {change.generator_id} at high-voltage bus {gen.bus}"
                )

    # Check load shedding is not excessive
    for flag in action.load_shedding_flags:
        load = observation.scada.get_load(flag.load_id)
        if load is not None:
            if flag.shed_mw > load.demand_mw:
                errors.append(
                    f"Load shed {flag.shed_mw}MW exceeds demand {load.demand_mw}MW "
                    f"for load {flag.load_id}"
                )

    # Check interconnect adjustments against ATC
    for adj in action.interconnect_flow_adjustments:
        atc = observation.market_state.atc_values.get(adj.border, float("inf"))
        if abs(adj.target_flow_mw) > atc:
            errors.append(
                f"Interconnect flow {adj.target_flow_mw}MW exceeds ATC {atc:.1f}MW "
                f"for border {adj.border}"
            )

    return ActionValidationResult(
        valid=len(errors) == 0,
        errors=tuple(errors),
        warnings=tuple(warnings),
    )
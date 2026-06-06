"""TimesFM model wrapper for AthenaAI forecast layer.

TimesFM is the required forecast model per Phase 2.2 spec. This module
provides specialized forecasters for power grid load, wind, and solar
using Google's TimesFM 2.5-200M foundation model.

Statistical baselines serve as fallbacks when TimesFM is unavailable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from statistics import stdev
from typing import Any, Sequence

import numpy as np

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class TimesFMUnavailableError(Exception):
    """Raised when TimesFM is required but not available."""


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ForecastPoint:
    """Single forecast horizon point with uncertainty bounds."""

    horizon_h: float
    mean: float
    lower_80: float  # 80% prediction interval lower bound
    upper_80: float  # 80% prediction interval upper bound
    lower_90: float  # 90% prediction interval lower bound
    upper_90: float  # 90% prediction interval upper bound


@dataclass(frozen=True)
class ForecastOutput:
    """Multi-horizon forecast output with per-point uncertainty."""

    points: tuple[ForecastPoint, ...]
    model: str
    timestamp: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.80

    @property
    def mean(self) -> float:
        """Mean of the first forecast point (backward compatibility)."""
        return self.points[0].mean if self.points else 0.0

    @property
    def lower_bound(self) -> float:
        """Lower 80% bound of first point (backward compatibility)."""
        return self.points[0].lower_80 if self.points else 0.0

    @property
    def upper_bound(self) -> float:
        """Upper 80% bound of first point (backward compatibility)."""
        return self.points[0].upper_80 if self.points else 0.0

    @property
    def horizon_h(self) -> float:
        return self.points[0].horizon_h if self.points else 0.0


# ---------------------------------------------------------------------------
# TimesFM model loader (singleton)
# ---------------------------------------------------------------------------

_MODEL_INSTANCE: Any = None
_MODEL_AVAILABLE: bool | None = None  # tri-state: None=unchecked


def _check_timesfm_available() -> bool:
    """Check if timesfm package is importable AND has a usable backend."""
    global _MODEL_AVAILABLE
    if _MODEL_AVAILABLE is not None:
        return _MODEL_AVAILABLE
    try:
        import timesfm  # type: ignore[import-untyped]

        torch_ok = hasattr(timesfm, "TimesFM_2p5_200M_torch")
        flax_ok = hasattr(timesfm, "TimesFM_2p5_200M_flax")

        if torch_ok or flax_ok:
            _MODEL_AVAILABLE = True
        else:
            logger.warning(
                "timesfm installed but no backend available "
                "(torch/jax not installed); falling back to statistical baselines"
            )
            _MODEL_AVAILABLE = False
    except ImportError:
        logger.warning("timesfm not installed; falling back to statistical baselines")
        _MODEL_AVAILABLE = False
    return _MODEL_AVAILABLE


def _get_timesfm_model() -> Any:
    """Load TimesFM 2.5-200M model (lazy singleton).

    Returns:
        Compiled TimesFM model or None if unavailable.
    """
    global _MODEL_INSTANCE, _MODEL_AVAILABLE
    if _MODEL_INSTANCE is not None:
        return _MODEL_INSTANCE

    if not _check_timesfm_available():
        return None

    try:
        import timesfm  # type: ignore[import-untyped]

        if not hasattr(timesfm, "TimesFM_2p5_200M_torch"):
            logger.warning(
                "TimesFM torch backend not available; install torch to use TimesFM"
            )
            _MODEL_AVAILABLE = False
            return None

        logger.info("Loading TimesFM 2.5-200M from HuggingFace...")
        model = timesfm.TimesFM_2p5_200M_torch.from_pretrained(
            "google/timesfm-2.5-200m-pytorch",
        )

        model.compile(
            timesfm.ForecastConfig(
                max_context=1024,
                max_horizon=256,
                normalize_inputs=True,
                use_continuous_quantile_head=True,
                force_flip_invariance=True,
                infer_is_positive=True,
                fix_quantile_crossing=True,
            )
        )
        logger.info("TimesFM 2.5-200M loaded and compiled successfully.")
        _MODEL_INSTANCE = model
        return model

    except Exception as exc:
        logger.error("Failed to load TimesFM model: %s", exc)
        _MODEL_AVAILABLE = False
        return None


# ---------------------------------------------------------------------------
# Data preprocessing utilities
# ---------------------------------------------------------------------------


def _validate_and_clean_series(
    values: Sequence[float],
    min_length: int = 2,
    fill_method: str = "forward",
) -> np.ndarray:
    """Clean a time series: handle NaN/Inf, ensure minimum length.

    Args:
        values: Raw time series values.
        min_length: Minimum required length.
        fill_method: How to fill missing values ('forward', 'zero', 'mean').

    Returns:
        Cleaned numpy array.
    """
    arr = np.asarray(values, dtype=np.float64)

    # Replace inf with NaN
    arr = np.where(np.isinf(arr), np.nan, arr)

    # Fill NaN values
    if np.any(np.isnan(arr)):
        nans = np.isnan(arr)
        if fill_method == "forward":
            # Forward fill then backward fill remaining
            arr = _forward_fill(arr)
        elif fill_method == "zero":
            arr = np.where(nans, 0.0, arr)
        elif fill_method == "mean":
            mean_val = np.nanmean(arr)
            arr = np.where(nans, mean_val if not np.isnan(mean_val) else 0.0, arr)

    # Ensure minimum length by repeating last value if needed
    if len(arr) < min_length:
        pad = np.full(min_length - len(arr), arr[-1] if len(arr) > 0 else 0.0)
        arr = np.concatenate([arr, pad])

    return arr


def _forward_fill(arr: np.ndarray) -> np.ndarray:
    """Forward-fill NaN values, then backward-fill any remaining leading NaNs."""
    mask = np.isnan(arr)
    if not np.any(mask):
        return arr
    idx = np.arange(len(arr))
    # Forward fill
    valid_idx = np.where(~mask)[0]
    if len(valid_idx) == 0:
        return np.zeros_like(arr)
    # For each position, find the last valid value before it
    idx_filled = np.clip(
        np.searchsorted(valid_idx, idx) - 1, 0, len(valid_idx) - 1
    )
    result = arr[valid_idx[idx_filled]]
    return result


def _normalize_series(arr: np.ndarray) -> tuple[np.ndarray, float, float]:
    """Z-score normalize a series. Returns (normalized, mean, std)."""
    mean = float(np.mean(arr))
    std = float(np.std(arr))
    if std < 1e-8:
        std = 1.0
    normalized = (arr - mean) / std
    return normalized, mean, std


def _resample_to_15min(
    timestamps: Sequence[datetime],
    values: Sequence[float],
) -> tuple[list[datetime], np.ndarray]:
    """Resample irregular time series to 15-minute intervals.

    Uses linear interpolation for up-sampling and mean aggregation for
    down-sampling. Returns (timestamps, values).
    """
    if len(timestamps) < 2:
        return list(timestamps), np.asarray(values, dtype=np.float64)

    import pandas as pd

    df = pd.DataFrame({"t": pd.to_datetime(timestamps), "v": values})
    df = df.set_index("t").sort_index()
    # Remove duplicate indices
    df = df[~df.index.duplicated(keep="last")]
    # Resample to 15min with linear interpolation
    resampled = df.resample("15min").mean().interpolate(method="linear")
    # Drop any remaining NaN at edges
    resampled = resampled.dropna()

    timestamps_out = [ts.to_pydatetime() for ts in resampled.index]
    values_out = resampled["v"].to_numpy(dtype=np.float64)
    return timestamps_out, values_out


# ---------------------------------------------------------------------------
# Covariate builders
# ---------------------------------------------------------------------------


def _build_covariates(
    length: int,
    temperature: float | None = None,
    wind_speed: float | None = None,
    irradiance: float | None = None,
    hour_of_day: int | None = None,
    day_of_week: int | None = None,
) -> dict[str, np.ndarray]:
    """Build covariate arrays for TimesFM forecasting.

    Covariates are constant-length arrays matching the historical series length.
    TimesFM 2.5 supports XReg covariates as additional input series.
    """
    covariates: dict[str, np.ndarray] = {}

    if temperature is not None:
        covariates["temperature"] = np.full(length, temperature, dtype=np.float64)
    if wind_speed is not None:
        covariates["wind_speed"] = np.full(length, wind_speed, dtype=np.float64)
    if irradiance is not None:
        covariates["irradiance"] = np.full(length, irradiance, dtype=np.float64)
    if hour_of_day is not None:
        # Encode hour as sine/cosine for cyclical continuity
        hour_rad = 2.0 * np.pi * hour_of_day / 24.0
        covariates["hour_sin"] = np.full(length, np.sin(hour_rad), dtype=np.float64)
        covariates["hour_cos"] = np.full(length, np.cos(hour_rad), dtype=np.float64)
    if day_of_week is not None:
        dow_rad = 2.0 * np.pi * day_of_week / 7.0
        covariates["dow_sin"] = np.full(length, np.sin(dow_rad), dtype=np.float64)
        covariates["dow_cos"] = np.full(length, np.cos(dow_rad), dtype=np.float64)

    return covariates


# ---------------------------------------------------------------------------
# Quantile extraction from TimesFM output
# ---------------------------------------------------------------------------

# TimesFM 2.5 quantile_forecast layout:
#   shape: (batch_size, horizon, 10)
#   indices: [0]=mean, [1]=10th, [2]=20th, ..., [9]=90th percentile
_QI_MEAN = 0
_QI_P10 = 1
_QI_P90 = 9
# For 90% interval (5th-95th), we estimate from 10th-90th with widening:
#   lower_90 ≈ lower_80 - 0.25 * (upper_80 - lower_80)
#   upper_90 ≈ upper_80 + 0.25 * (upper_80 - lower_80)
# This is a heuristic assuming roughly normal tails.


def _extract_forecast_points(
    quantile_forecast: np.ndarray,
    horizon_hours: Sequence[float],
    model_label: str,
) -> list[ForecastPoint]:
    """Extract forecast points with 80% and 90% prediction intervals.

    Args:
        quantile_forecast: Array of shape (1, horizon, 10) from TimesFM.
        horizon_hours: Horizon in hours for each step.
        model_label: Label for the model field.

    Returns:
        List of ForecastPoint objects.
    """
    points: list[ForecastPoint] = []
    qf = quantile_forecast[0]  # shape (horizon, 10)

    for i, hh in enumerate(horizon_hours):
        mean_val = float(qf[i, _QI_MEAN])
        p10 = float(qf[i, _QI_P10])
        p90 = float(qf[i, _QI_P90])

        # 80% interval (P10-P90 from decile quantiles)
        lower_80 = p10
        upper_80 = p90

        # 90% interval (estimated by widening)
        spread = upper_80 - lower_80
        lower_90 = lower_80 - 0.25 * spread
        upper_90 = upper_80 + 0.25 * spread

        points.append(
            ForecastPoint(
                horizon_h=hh,
                mean=mean_val,
                lower_80=lower_80,
                upper_80=upper_80,
                lower_90=lower_90,
                upper_90=upper_90,
            )
        )

    return points


# ---------------------------------------------------------------------------
# Statistical baseline forecasters (updated for multi-horizon)
# ---------------------------------------------------------------------------


def _statistical_forecast_points(
    historical_values: np.ndarray,
    horizon_hours: list[float],
    method: str = "naive",
) -> list[ForecastPoint]:
    """Generate multi-horizon statistical baselines.

    Args:
        historical_values: 1D numpy array of historical values.
        horizon_hours: List of horizon lengths in hours.
        method: One of 'naive', 'moving_average', 'seasonal_naive'.

    Returns:
        List of ForecastPoint objects.
    """
    if len(historical_values) == 0:
        return [
            ForecastPoint(
                horizon_h=h, mean=0.0, lower_80=0.0, upper_80=0.0,
                lower_90=0.0, upper_90=0.0,
            )
            for h in horizon_hours
        ]

    if method == "naive":
        base_mean = float(historical_values[-1])
    elif method == "moving_average":
        window = min(24, len(historical_values))
        base_mean = float(np.mean(historical_values[-window:]))
    elif method == "seasonal_naive":
        if len(historical_values) >= 24:
            base_mean = float(historical_values[-24])
        else:
            base_mean = float(historical_values[-1])
    else:
        base_mean = float(historical_values[-1])

    # Estimate standard deviation
    if len(historical_values) > 1:
        base_std = float(np.std(historical_values))
        if base_std < 1e-8:
            base_std = abs(base_mean) * 0.05 if abs(base_mean) > 0 else 1.0
    else:
        base_std = abs(base_mean) * 0.05 if abs(base_mean) > 0 else 1.0

    points: list[ForecastPoint] = []
    for h in horizon_hours:
        # Uncertainty grows with horizon
        horizon_factor = 1.0 + h * 0.5
        std_h = base_std * horizon_factor

        z80 = 1.282  # 80% CI z-score
        z90 = 1.645  # 90% CI z-score

        points.append(
            ForecastPoint(
                horizon_h=h,
                mean=base_mean,
                lower_80=base_mean - z80 * std_h,
                upper_80=base_mean + z80 * std_h,
                lower_90=base_mean - z90 * std_h,
                upper_90=base_mean + z90 * std_h,
            )
        )

    return points


# ---------------------------------------------------------------------------
# TimesFMWrapper (backward-compatible wrapper around new forecasters)
# ---------------------------------------------------------------------------


class TimesFMWrapper:
    """Backward-compatible TimesFM wrapper.

    Delegates to internal forecaster instances. Kept for API compatibility
    with existing code that uses TimesFMWrapper directly.
    """

    def __init__(self, model_path: str | None = None) -> None:
        self._model_path = model_path
        self._model_handle: Any = None
        self._available = _check_timesfm_available()
        if not self._available:
            raise TimesFMUnavailableError(
                "TimesFM is not installed. Install with: pip install timesfm "
                "(or see https://github.com/google-research/timesfm)"
            )

    @property
    def is_available(self) -> bool:
        return self._available

    def forecast(
        self,
        historical_values: list[float],
        horizon_h: int,
        confidence: float = 0.95,
    ) -> ForecastOutput:
        """Single-horizon forecast (backward-compatible).

        Uses the new load forecaster internally.
        """
        forecaster = PowerGridLoadForecaster()
        result = forecaster.forecast(
            historical_load=np.array(historical_values, dtype=np.float64),
            horizon_steps=horizon_h * 4,  # Convert hours to 15-min steps
        )
        return result


# ---------------------------------------------------------------------------
# Specialized forecasters
# ---------------------------------------------------------------------------


class PowerGridLoadForecaster:
    """15-minute load forecaster using TimesFM 2.5 with covariates.

    Features:
    - Loads TimesFM 2.5-200M from HuggingFace (lazy, singleton)
    - Supports covariates: temperature, hour of day, day of week
    - Falls back to statistical baselines if TimesFM unavailable
    - Returns mean + 80%/90% prediction intervals
    """

    def __init__(self, seed: int = 42) -> None:
        self._seed = seed
        self._model = _get_timesfm_model()
        self._rng = np.random.default_rng(seed)

    @property
    def is_available(self) -> bool:
        return self._model is not None

    def forecast(
        self,
        historical_load: np.ndarray,
        horizon_steps: int = 4,  # 4 steps = 1 hour at 15min
        temperature: float | None = None,
        hour_of_day: int | None = None,
        day_of_week: int | None = None,
    ) -> ForecastOutput:
        """Generate 15-minute load forecast.

        Args:
            historical_load: Historical load values in MW. Should be at
                15-minute resolution if available.
            horizon_steps: Number of 15-min steps to forecast (default 4 = 1h).
            temperature: Current temperature in Celsius for covariate.
            hour_of_day: 0-23 hour for calendar covariate.
            day_of_week: 0=Monday, 6=Sunday for calendar covariate.

        Returns:
            ForecastOutput with multi-point forecasts.
        """
        # Clean input data
        clean_load = _validate_and_clean_series(historical_load, min_length=4)

        horizon_hours = [(i + 1) * 0.25 for i in range(horizon_steps)]

        if not self.is_available:
            logger.info("TimesFM unavailable; using statistical baseline for load")
            points = _statistical_forecast_points(
                clean_load, horizon_hours, method="moving_average"
            )
            return ForecastOutput(
                points=tuple(points),
                model="statistical_moving_average",
                metadata={"method": "fallback"},
            )

        try:
            norm_load, load_mean, load_std = _normalize_series(clean_load)

            covs = _build_covariates(
                length=len(clean_load),
                temperature=temperature,
                hour_of_day=hour_of_day,
                day_of_week=day_of_week,
            )

            input_series = norm_load.astype(np.float32)

            import torch
            with torch.no_grad():
                point_forecast, quantile_forecast = self._model.forecast(  # type: ignore[union-attr]
                    horizon=horizon_steps,
                    inputs=[input_series],
                )

            point_forecast = point_forecast * load_std + load_mean
            quantile_forecast = quantile_forecast * load_std + load_mean

            points = _extract_forecast_points(
                quantile_forecast, horizon_hours, "timesfm_2.5_200M"
            )

            return ForecastOutput(
                points=tuple(points),
                model="timesfm_2.5_200M",
                metadata={
                    "load_mean": load_mean,
                    "load_std": load_std,
                    "input_length": len(clean_load),
                    "covariates": list(covs.keys()),
                },
            )

        except Exception as exc:
            logger.error("TimesFM load forecast failed: %s", exc, exc_info=True)
            points = _statistical_forecast_points(
                clean_load, horizon_hours, method="moving_average"
            )
            return ForecastOutput(
                points=tuple(points),
                model="statistical_moving_average",
                metadata={"method": "fallback_due_to_error", "error": str(exc)},
            )


class WindNowcaster:
    """Wind power nowcaster using TimesFM 2.5.

    Forecasts wind speed and converts to power via wind power curve.
    """

    def __init__(self, seed: int = 42) -> None:
        self._seed = seed
        self._model = _get_timesfm_model()
        self._rng = np.random.default_rng(seed)

    @property
    def is_available(self) -> bool:
        return self._model is not None

    def _wind_to_power(
        self,
        wind_speed_ms: float,
        rated_power_mw: float = 2.0,
        v_cut_in: float = 3.0,
        v_rated: float = 12.0,
        v_cut_out: float = 25.0,
    ) -> float:
        """Convert wind speed to power using standard IEC 61400 power curve."""
        if wind_speed_ms < v_cut_in or wind_speed_ms >= v_cut_out:
            return 0.0
        if wind_speed_ms >= v_rated:
            return rated_power_mw
        v_range = v_rated - v_cut_in
        v_position = (wind_speed_ms - v_cut_in) / v_range
        return rated_power_mw * (v_position**3)

    def forecast(
        self,
        historical_wind_speed: np.ndarray,
        horizon_steps: int = 4,
        rated_power_mw: float = 2.0,
        v_cut_in: float = 3.0,
        v_rated: float = 12.0,
        v_cut_out: float = 25.0,
    ) -> ForecastOutput:
        """Generate wind nowcast.

        Args:
            historical_wind_speed: Historical wind speed in m/s.
            horizon_steps: Number of 15-min steps to forecast.
            rated_power_mw: Turbine rated power.
            v_cut_in, v_rated, v_cut_out: Wind power curve parameters.

        Returns:
            ForecastOutput with wind speed and power outputs.
        """
        clean_wind = _validate_and_clean_series(historical_wind_speed, min_length=4)
        horizon_hours = [(i + 1) * 0.25 for i in range(horizon_steps)]

        if not self.is_available:
            logger.info("TimesFM unavailable; using persistence baseline for wind")
            points = _statistical_forecast_points(
                clean_wind, horizon_hours, method="naive"
            )
            # Convert wind speed forecasts to power
            power_points = []
            for pt in points:
                ws = pt.mean
                pw = self._wind_to_power(ws, rated_power_mw, v_cut_in, v_rated, v_cut_out)
                power_points.append(
                    ForecastPoint(
                        horizon_h=pt.horizon_h,
                        mean=pw,
                        lower_80=self._wind_to_power(
                            pt.lower_80, rated_power_mw, v_cut_in, v_rated, v_cut_out
                        ),
                        upper_80=self._wind_to_power(
                            pt.upper_80, rated_power_mw, v_cut_in, v_rated, v_cut_out
                        ),
                        lower_90=self._wind_to_power(
                            pt.lower_90, rated_power_mw, v_cut_in, v_rated, v_cut_out
                        ),
                        upper_90=self._wind_to_power(
                            pt.upper_90, rated_power_mw, v_cut_in, v_rated, v_cut_out
                        ),
                    )
                )
            return ForecastOutput(
                points=tuple(power_points),
                model="statistical_persistence",
                metadata={
                    "method": "fallback",
                    "rated_power_mw": rated_power_mw,
                    "wind_points": [
                        {"horizon_h": pt.horizon_h, "wind_speed_ms": pt.mean}
                        for pt in points
                    ],
                },
            )

        try:
            norm_wind, wind_mean, wind_std = _normalize_series(clean_wind)
            input_series = norm_wind.astype(np.float32)

            import torch
            with torch.no_grad():
                point_forecast, quantile_forecast = self._model.forecast(  # type: ignore[union-attr]
                    horizon=horizon_steps,
                    inputs=[input_series],
                )

            # De-normalize wind speeds
            wind_point = point_forecast * wind_std + wind_mean
            wind_quantile = quantile_forecast * wind_std + wind_mean

            # Extract wind speed forecast points
            wind_points = _extract_forecast_points(
                wind_quantile, horizon_hours, "timesfm_2.5_200M_wind"
            )

            # Convert to power output
            power_points = []
            for pt in wind_points:
                power_points.append(
                    ForecastPoint(
                        horizon_h=pt.horizon_h,
                        mean=self._wind_to_power(pt.mean, rated_power_mw, v_cut_in, v_rated, v_cut_out),
                        lower_80=self._wind_to_power(pt.lower_80, rated_power_mw, v_cut_in, v_rated, v_cut_out),
                        upper_80=self._wind_to_power(pt.upper_80, rated_power_mw, v_cut_in, v_rated, v_cut_out),
                        lower_90=self._wind_to_power(pt.lower_90, rated_power_mw, v_cut_in, v_rated, v_cut_out),
                        upper_90=self._wind_to_power(pt.upper_90, rated_power_mw, v_cut_in, v_rated, v_cut_out),
                    )
                )

            return ForecastOutput(
                points=tuple(power_points),
                model="timesfm_2.5_200M",
                metadata={
                    "wind_mean": wind_mean,
                    "wind_std": wind_std,
                    "rated_power_mw": rated_power_mw,
                    "wind_speed_points": [
                        {"horizon_h": pt.horizon_h, "wind_speed_ms": pt.mean}
                        for pt in wind_points
                    ],
                },
            )

        except Exception as exc:
            logger.error("TimesFM wind forecast failed: %s", exc, exc_info=True)
            points = _statistical_forecast_points(
                clean_wind, horizon_hours, method="naive"
            )
            power_points = []
            for pt in points:
                pw = self._wind_to_power(pt.mean, rated_power_mw, v_cut_in, v_rated, v_cut_out)
                power_points.append(
                    ForecastPoint(
                        horizon_h=pt.horizon_h,
                        mean=pw,
                        lower_80=self._wind_to_power(pt.lower_80, rated_power_mw, v_cut_in, v_rated, v_cut_out),
                        upper_80=self._wind_to_power(pt.upper_80, rated_power_mw, v_cut_in, v_rated, v_cut_out),
                        lower_90=self._wind_to_power(pt.lower_90, rated_power_mw, v_cut_in, v_rated, v_cut_out),
                        upper_90=self._wind_to_power(pt.upper_90, rated_power_mw, v_cut_in, v_rated, v_cut_out),
                    )
                )
            return ForecastOutput(
                points=tuple(power_points),
                model="statistical_persistence",
                metadata={"method": "fallback_due_to_error", "error": str(exc)},
            )


class SolarNowcaster:
    """Solar power nowcaster using TimesFM 2.5.

    Forecasts solar irradiance and converts to power output.
    """

    def __init__(self, seed: int = 42) -> None:
        self._seed = seed
        self._model = _get_timesfm_model()
        self._rng = np.random.default_rng(seed)

    @property
    def is_available(self) -> bool:
        return self._model is not None

    def _irradiance_to_power(
        self,
        irradiance_wm2: float,
        rated_power_mw: float = 1.0,
        panel_efficiency: float = 0.18,
        system_loss_factor: float = 0.85,
        cloud_cover_okta: float = 3.0,
    ) -> float:
        """Convert irradiance to solar PV power output.

        Args:
            irradiance_wm2: Global horizontal irradiance in W/m².
            rated_power_mw: Panel rated power at STC (1000 W/m²).
            panel_efficiency: Panel efficiency (default 18%).
            system_loss_factor: System losses (default 0.85 = 15% loss).
            cloud_cover_okta: Cloud cover on 0-8 okta scale.

        Returns:
            Estimated power output in MW.
        """
        # Cloud reduction
        cloud_factor = 1.0 - (cloud_cover_okta / 8.0) * 0.75
        effective_irradiance = irradiance_wm2 * cloud_factor

        # Standard Test Condition reference: 1000 W/m²
        stc_irradiance = 1000.0
        capacity_factor = effective_irradiance / stc_irradiance
        power = rated_power_mw * capacity_factor * panel_efficiency * system_loss_factor

        return max(0.0, min(rated_power_mw, power))

    def forecast(
        self,
        historical_irradiance: np.ndarray,
        horizon_steps: int = 4,
        rated_power_mw: float = 1.0,
        panel_efficiency: float = 0.18,
        system_loss_factor: float = 0.85,
        cloud_cover_okta: float = 3.0,
        hour_of_day: int | None = None,
    ) -> ForecastOutput:
        """Generate solar nowcast.

        Args:
            historical_irradiance: Historical GHI in W/m².
            horizon_steps: Number of 15-min steps to forecast.
            rated_power_mw: Panel rated power.
            panel_efficiency: Panel conversion efficiency.
            system_loss_factor: System derating factor.
            cloud_cover_okta: Cloud cover 0-8.
            hour_of_day: 0-23 hour for diurnal covariate.

        Returns:
            ForecastOutput with irradiance and power outputs.
        """
        clean_irr = _validate_and_clean_series(historical_irradiance, min_length=4)
        horizon_hours = [(i + 1) * 0.25 for i in range(horizon_steps)]

        if not self.is_available:
            logger.info("TimesFM unavailable; using clear-sky baseline for solar")
            points = _statistical_forecast_points(
                clean_irr, horizon_hours, method="moving_average"
            )
            power_points = []
            for pt in points:
                pw = self._irradiance_to_power(
                    pt.mean, rated_power_mw, panel_efficiency,
                    system_loss_factor, cloud_cover_okta,
                )
                power_points.append(
                    ForecastPoint(
                        horizon_h=pt.horizon_h,
                        mean=pw,
                        lower_80=self._irradiance_to_power(
                            pt.lower_80, rated_power_mw, panel_efficiency,
                            system_loss_factor, cloud_cover_okta,
                        ),
                        upper_80=self._irradiance_to_power(
                            pt.upper_80, rated_power_mw, panel_efficiency,
                            system_loss_factor, cloud_cover_okta,
                        ),
                        lower_90=self._irradiance_to_power(
                            pt.lower_90, rated_power_mw, panel_efficiency,
                            system_loss_factor, cloud_cover_okta,
                        ),
                        upper_90=self._irradiance_to_power(
                            pt.upper_90, rated_power_mw, panel_efficiency,
                            system_loss_factor, cloud_cover_okta,
                        ),
                    )
                )
            return ForecastOutput(
                points=tuple(power_points),
                model="statistical_clear_sky",
                metadata={
                    "method": "fallback",
                    "rated_power_mw": rated_power_mw,
                    "irradiance_points": [
                        {"horizon_h": pt.horizon_h, "irradiance_wm2": pt.mean}
                        for pt in points
                    ],
                },
            )

        try:
            norm_irr, irr_mean, irr_std = _normalize_series(clean_irr)

            covs = _build_covariates(
                length=len(clean_irr),
                irradiance=float(np.mean(clean_irr)),
                hour_of_day=hour_of_day,
            )
            input_series = norm_irr.astype(np.float32)

            import torch
            with torch.no_grad():
                point_forecast, quantile_forecast = self._model.forecast(  # type: ignore[union-attr]
                    horizon=horizon_steps,
                    inputs=[input_series],
                )

            # De-normalize
            irr_point = point_forecast * irr_std + irr_mean
            irr_quantile = quantile_forecast * irr_std + irr_mean

            # Ensure non-negative irradiance
            irr_point = np.maximum(irr_point, 0.0)
            irr_quantile = np.maximum(irr_quantile, 0.0)

            irradiance_points = _extract_forecast_points(
                irr_quantile, horizon_hours, "timesfm_2.5_200M_solar"
            )

            # Convert to power
            power_points = []
            for pt in irradiance_points:
                power_points.append(
                    ForecastPoint(
                        horizon_h=pt.horizon_h,
                        mean=self._irradiance_to_power(
                            pt.mean, rated_power_mw, panel_efficiency,
                            system_loss_factor, cloud_cover_okta,
                        ),
                        lower_80=self._irradiance_to_power(
                            pt.lower_80, rated_power_mw, panel_efficiency,
                            system_loss_factor, cloud_cover_okta,
                        ),
                        upper_80=self._irradiance_to_power(
                            pt.upper_80, rated_power_mw, panel_efficiency,
                            system_loss_factor, cloud_cover_okta,
                        ),
                        lower_90=self._irradiance_to_power(
                            pt.lower_90, rated_power_mw, panel_efficiency,
                            system_loss_factor, cloud_cover_okta,
                        ),
                        upper_90=self._irradiance_to_power(
                            pt.upper_90, rated_power_mw, panel_efficiency,
                            system_loss_factor, cloud_cover_okta,
                        ),
                    )
                )

            return ForecastOutput(
                points=tuple(power_points),
                model="timesfm_2.5_200M",
                metadata={
                    "irradiance_mean": irr_mean,
                    "irradiance_std": irr_std,
                    "rated_power_mw": rated_power_mw,
                    "irradiance_points": [
                        {"horizon_h": pt.horizon_h, "irradiance_wm2": pt.mean}
                        for pt in irradiance_points
                    ],
                },
            )

        except Exception as exc:
            logger.error("TimesFM solar forecast failed: %s", exc, exc_info=True)
            points = _statistical_forecast_points(
                clean_irr, horizon_hours, method="moving_average"
            )
            power_points = []
            for pt in points:
                pw = self._irradiance_to_power(
                    pt.mean, rated_power_mw, panel_efficiency,
                    system_loss_factor, cloud_cover_okta,
                )
                power_points.append(
                    ForecastPoint(
                        horizon_h=pt.horizon_h,
                        mean=pw,
                        lower_80=self._irradiance_to_power(
                            pt.lower_80, rated_power_mw, panel_efficiency,
                            system_loss_factor, cloud_cover_okta,
                        ),
                        upper_80=self._irradiance_to_power(
                            pt.upper_80, rated_power_mw, panel_efficiency,
                            system_loss_factor, cloud_cover_okta,
                        ),
                        lower_90=self._irradiance_to_power(
                            pt.lower_90, rated_power_mw, panel_efficiency,
                            system_loss_factor, cloud_cover_okta,
                        ),
                        upper_90=self._irradiance_to_power(
                            pt.upper_90, rated_power_mw, panel_efficiency,
                            system_loss_factor, cloud_cover_okta,
                        ),
                    )
                )
            return ForecastOutput(
                points=tuple(power_points),
                model="statistical_clear_sky",
                metadata={"method": "fallback_due_to_error", "error": str(exc)},
            )


# ---------------------------------------------------------------------------
# Legacy apply_statistical_baseline (backward compatible)
# ---------------------------------------------------------------------------


def apply_statistical_baseline(
    historical_values: list[float],
    horizon_h: int,
    method: str = "naive",
    confidence: float = 0.95,
) -> ForecastOutput:
    """Legacy single-horizon statistical baseline (backward-compatible).

    Args:
        historical_values: Historical time series values.
        horizon_h: Forecast horizon in hours.
        method: 'naive', 'moving_average', or 'seasonal_naive'.
        confidence: Confidence level (0.80 or 0.95).

    Returns:
        ForecastOutput with a single point.
    """
    arr = np.asarray(historical_values, dtype=np.float64)
    horizon_hours = [float(horizon_h)]

    if not historical_values:
        return ForecastOutput(
            points=(
                ForecastPoint(
                    horizon_h=float(horizon_h), mean=0.0,
                    lower_80=0.0, upper_80=0.0,
                    lower_90=0.0, upper_90=0.0,
                ),
            ),
            model=f"statistical_{method}",
            confidence=confidence,
        )

    points = _statistical_forecast_points(arr, horizon_hours, method=method)

    # Adjust bounds for requested confidence if not standard
    if confidence == 0.95:
        # Recompute with z=1.96 for 95%
        base_mean = float(arr[-1])
        base_std = float(np.std(arr)) if len(arr) > 1 else abs(base_mean) * 0.05
        if method == "moving_average":
            w = min(24, len(arr))
            base_mean = float(np.mean(arr[-w:]))
            base_std = float(np.std(arr[-w:])) if len(arr[-w:]) > 1 else abs(base_mean) * 0.05
        elif method == "seasonal_naive" and len(arr) >= 24:
            base_mean = float(arr[-24])

        h_factor = 1.0 + float(horizon_h) * 0.5
        std_h = base_std * h_factor
        z95 = 1.96

        # Overwrite first point with 95% bounds
        pts = list(points)
        pts[0] = ForecastPoint(
            horizon_h=float(horizon_h),
            mean=pts[0].mean,
            lower_80=pts[0].lower_80,
            upper_80=pts[0].upper_80,
            lower_90=base_mean - z95 * std_h,
            upper_90=base_mean + z95 * std_h,
        )
        points = pts

    return ForecastOutput(
        points=tuple(points),
        model=f"statistical_{method}",
        confidence=confidence,
    )

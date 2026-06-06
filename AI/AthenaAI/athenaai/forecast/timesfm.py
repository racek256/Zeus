"""TimesFM model wrapper for AthenaAI forecast layer.

TimesFM is the required forecast model per Phase 2.2 spec. This module
provides a wrapper that fails clearly if TimesFM is unavailable rather
than silently substituting statistical baselines.

Statistical baselines exist only as explicit comparison helpers, NOT as
silent replacement for TimesFM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import importlib
from statistics import stdev
from typing import Any


class TimesFMUnavailableError(Exception):
    pass


@dataclass(frozen=True)
class ForecastOutput:
    mean: float
    lower_bound: float
    upper_bound: float
    confidence: float
    horizon_h: float
    model: str
    timestamp: datetime | None = None


class TimesFMWrapper:
    def __init__(self, model_path: str | None = None) -> None:
        self._model_path = model_path
        self._model_handle: Any = None
        self._available = False
        self._initialize()

    def _initialize(self) -> None:
        try:
            importlib.import_module("timesfm")
            self._available = True
        except ImportError:
            raise TimesFMUnavailableError(
                "TimesFM is not installed. This is a required dependency for "
                "forecast runtime. Install with: pip install timesfm "
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
        if not self._available:
            raise TimesFMUnavailableError(
                "TimesFM is not available. Forecasts require TimesFM."
            )

        try:
            tfm = importlib.import_module("timesfm")
        except ImportError:
            raise TimesFMUnavailableError(
                "TimesFM import failed. Please ensure TimesFM is properly installed."
            )

        try:
            if self._model_handle is None:
                timesfm_cls = getattr(tfm, "TimesFM")
                self._model_handle = timesfm_cls(
                    checkpoint_path=self._model_path,
                )

            forecast = self._model_handle.forecast(
                historical_values,
                horizon=horizon_h,
            )

            mean_values = forecast.mean if hasattr(forecast, "mean") else forecast[0]
            std_values = forecast.std if hasattr(forecast, "std") else forecast[1]

            z = 1.96 if confidence == 0.95 else 1.65

            mean_val = float(mean_values[0]) if hasattr(mean_values, "__iter__") else float(mean_values)
            std_val = float(std_values[0]) if hasattr(std_values, "__iter__") else float(std_values)

            lower = mean_val - z * std_val
            upper = mean_val + z * std_val

            return ForecastOutput(
                mean=mean_val,
                lower_bound=lower,
                upper_bound=upper,
                confidence=confidence,
                horizon_h=float(horizon_h),
                model="timesfm",
            )

        except Exception as e:
            raise TimesFMUnavailableError(
                f"TimesFM forecast failed: {str(e)}"
            )


def apply_statistical_baseline(
    historical_values: list[float],
    horizon_h: int,
    method: str = "naive",
    confidence: float = 0.95,
) -> ForecastOutput:
    if not historical_values:
        return ForecastOutput(
            mean=0.0,
            lower_bound=0.0,
            upper_bound=0.0,
            confidence=confidence,
            horizon_h=float(horizon_h),
            model=f"statistical_{method}",
        )

    if method == "naive":
        mean_val = historical_values[-1]
        std_val = 0.0
        if len(historical_values) > 1:
            std_val = float(stdev(historical_values))

    elif method == "moving_average":
        window = min(24, len(historical_values))
        mean_val = sum(historical_values[-window:]) / window
        if len(historical_values) > 1:
            std_val = float(stdev(historical_values[-window:]))
        else:
            std_val = 0.0

    elif method == "seasonal_naive":
        if len(historical_values) >= 24:
            mean_val = historical_values[-24]
            std_val = 0.0
        else:
            mean_val = historical_values[-1]
            std_val = float(stdev(historical_values)) if len(historical_values) > 1 else 0.0

    else:
        mean_val = historical_values[-1]
        std_val = 0.0

    z = 1.96 if confidence == 0.95 else 1.65

    return ForecastOutput(
        mean=mean_val,
        lower_bound=mean_val - z * std_val if std_val > 0 else mean_val,
        upper_bound=mean_val + z * std_val if std_val > 0 else mean_val,
        confidence=confidence,
        horizon_h=float(horizon_h),
        model=f"statistical_{method}",
    )

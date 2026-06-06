"""AthenaAI forecast package - TimesFM wrapper and statistical baselines."""

from athenaai.forecast.timesfm import (
    ForecastOutput,
    ForecastPoint,
    PowerGridLoadForecaster,
    SolarNowcaster,
    TimesFMUnavailableError,
    TimesFMWrapper,
    WindNowcaster,
    _check_timesfm_available,
    apply_statistical_baseline,
)

__all__ = [
    "TimesFMWrapper",
    "TimesFMUnavailableError",
    "ForecastOutput",
    "ForecastPoint",
    "PowerGridLoadForecaster",
    "WindNowcaster",
    "SolarNowcaster",
    "apply_statistical_baseline",
    "_check_timesfm_available",
]
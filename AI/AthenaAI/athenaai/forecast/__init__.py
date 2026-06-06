"""AthenaAI forecast package - TimesFM wrapper and statistical baselines."""

from athenaai.forecast.timesfm import (
    ForecastOutput,
    TimesFMUnavailableError,
    TimesFMWrapper,
    apply_statistical_baseline,
)

__all__ = [
    "TimesFMWrapper",
    "TimesFMUnavailableError",
    "ForecastOutput",
    "apply_statistical_baseline",
]
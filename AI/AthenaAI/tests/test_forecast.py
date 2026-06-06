"""Tests for forecast layer - TimesFM wrapper and statistical baselines."""

from datetime import datetime

from athenaai.forecast import TimesFMUnavailableError, apply_statistical_baseline


class TestTimesFMUnavailable:
    def test_timesfm_raises_when_unavailable(self):
        try:
            from athenaai.forecast import TimesFMWrapper
            TimesFMWrapper()
        except TimesFMUnavailableError:
            return
        raise AssertionError("Expected TimesFMUnavailableError when timesfm is unavailable")


class TestStatisticalBaselines:
    def test_statistical_baseline_naive(self):
        historical = [100.0, 105.0, 102.0, 108.0]
        result = apply_statistical_baseline(historical, 1, method="naive")
        assert result.mean == 108.0
        assert result.model == "statistical_naive"

    def test_statistical_baseline_moving_average(self):
        historical = [100.0, 105.0, 102.0, 108.0]
        result = apply_statistical_baseline(historical, 1, method="moving_average")
        assert result.mean > 0
        assert result.model == "statistical_moving_average"

    def test_statistical_baseline_empty_history(self):
        result = apply_statistical_baseline([], 1, method="naive")
        assert result.mean == 0.0

    def test_statistical_baseline_seasonal_naive(self):
        historical = [100.0] * 24 + [110.0]
        result = apply_statistical_baseline(historical, 1, method="seasonal_naive")
        assert result.mean == 100.0

    def test_statistical_baseline_uncertainty_bounds(self):
        historical = [100.0, 105.0, 102.0, 108.0, 103.0, 107.0]
        result = apply_statistical_baseline(historical, 1, method="naive", confidence=0.95)
        assert result.lower_bound <= result.mean <= result.upper_bound
        assert result.confidence == 0.95

# Phase Forecast Plan

## Clarified decision

**TimesFM is required** for v1 forecast runtime/tests.

**Note**: TimesFM integration and full forecast tool coverage in this plan are binding for **Phase 2.2+**. Phase 2.1 is explicitly allowed to contain deterministic placeholder forecast interfaces only. This plan governs what the forecast layer must eventually become, not what Phase 2.1 must already be.

## Implementation target

- Integrate TimesFM as the main forecast model wrapper.
- Forecast APIs must return mean plus uncertainty bounds/quantiles; no single-point forecast-only API is acceptable.
- Statistical baselines may exist for comparison, but they must not silently replace TimesFM when TimesFM is unavailable.
- If TimesFM or required model assets are missing, forecast initialization/tests should fail clearly.

## Leakage rules

- Realtime generator/load actuals are never used as future forecast features.
- Forecast tools may use only information available at the simulated decision time.
- Day-ahead forecasts, elapsed actuals, calendar features, and known exogenous forecast inputs are allowed.

## Required tool coverage

- 15-minute load forecast.
- Wind nowcast.
- Solar nowcast.
- Ramp event detector.
- Day-ahead schedule optimization input forecasts.
- Temperature-to-demand model.
- EV/flexible-load model.

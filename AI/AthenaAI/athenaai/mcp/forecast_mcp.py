"""MCP server exposing AthenaAI forecast tools.

Provides three tools via the Model Context Protocol:
  - forecast_load: 15-minute load forecasting
  - forecast_wind: Wind power nowcasting
  - forecast_solar: Solar power nowcasting

Can run as a standalone process: python -m athenaai.mcp.forecast_mcp
"""

from __future__ import annotations

import json
import logging
import sys
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

import numpy as np

from athenaai.forecast.timesfm import (
    ForecastOutput,
    PowerGridLoadForecaster,
    SolarNowcaster,
    WindNowcaster,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# In-memory cache with TTL
# ---------------------------------------------------------------------------


@dataclass
class _CacheEntry:
    value: dict[str, Any]
    expires_at: float


class _TTLCache:
    """Simple in-memory cache with per-key TTL and LRU eviction."""

    def __init__(self, max_size: int = 256, default_ttl: float = 300.0) -> None:
        self._max_size = max_size
        self._default_ttl = default_ttl
        self._store: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._lock = threading.Lock()

    def _evict_expired(self) -> None:
        now = time.monotonic()
        expired = [k for k, v in self._store.items() if v.expires_at <= now]
        for k in expired:
            del self._store[k]

    def _evict_lru(self) -> None:
        while len(self._store) >= self._max_size:
            self._store.popitem(last=False)

    def get(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            if entry.expires_at <= time.monotonic():
                del self._store[key]
                return None
            self._store.move_to_end(key)
            return entry.value

    def set(self, key: str, value: dict[str, Any], ttl: float | None = None) -> None:
        ttl = ttl if ttl is not None else self._default_ttl
        with self._lock:
            self._evict_expired()
            if key in self._store:
                self._store.move_to_end(key)
            else:
                self._evict_lru()
            self._store[key] = _CacheEntry(
                value=value,
                expires_at=time.monotonic() + ttl,
            )

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


# ---------------------------------------------------------------------------
# MCP Tool handlers
# ---------------------------------------------------------------------------


def _make_error_result(message: str, error_code: str = "FORECAST_ERROR") -> dict[str, Any]:
    return {
        "status": {"success": False, "message": message, "error_code": error_code},
        "simulated_time": None,
        "inputs_summary": {},
        "uncertainty": {},
        "results": {},
    }


def _forecast_output_to_result(
    output: ForecastOutput,
    inputs: dict[str, Any],
    simulated_time: datetime | None = None,
) -> dict[str, Any]:
    """Convert ForecastOutput to _make_result-compatible dict."""
    points_list = []
    for pt in output.points:
        points_list.append({
            "horizon_h": pt.horizon_h,
            "mean": round(pt.mean, 4),
            "lower_80": round(pt.lower_80, 4),
            "upper_80": round(pt.upper_80, 4),
            "lower_90": round(pt.lower_90, 4),
            "upper_90": round(pt.upper_90, 4),
        })

    uncertainty = {}
    if points_list:
        first = points_list[0]
        uncertainty = {
            "std_80": round((first["upper_80"] - first["lower_80"]) / 2.564, 4),
            "std_90": round((first["upper_90"] - first["lower_90"]) / 3.29, 4),
            "confidence_80_pct": 80.0,
            "confidence_90_pct": 90.0,
        }

    return {
        "status": {"success": True, "message": "Forecast generated successfully", "error_code": None},
        "simulated_time": simulated_time.isoformat() if simulated_time else None,
        "inputs_summary": inputs,
        "uncertainty": uncertainty,
        "results": {
            "forecast_points": points_list,
            "model": output.model,
            "metadata": output.metadata,
        },
    }


def _build_cache_key(prefix: str, **kwargs: Any) -> str:
    parts = [prefix]
    for k in sorted(kwargs.keys()):
        v = kwargs[k]
        if isinstance(v, (list, np.ndarray)):
            parts.append(f"{k}={hash(str(v))}")
        else:
            parts.append(f"{k}={v}")
    return ":".join(parts)


class ForecastMCPServer:
    """MCP-compatible forecast server with caching and fallback."""

    def __init__(self, cache_ttl: float = 300.0, seed: int = 42) -> None:
        self._cache = _TTLCache(default_ttl=cache_ttl)
        self._seed = seed
        self._load_forecaster: PowerGridLoadForecaster | None = None
        self._wind_forecaster: WindNowcaster | None = None
        self._solar_forecaster: SolarNowcaster | None = None

    @property
    def load_forecaster(self) -> PowerGridLoadForecaster:
        if self._load_forecaster is None:
            self._load_forecaster = PowerGridLoadForecaster(seed=self._seed)
        return self._load_forecaster

    @property
    def wind_forecaster(self) -> WindNowcaster:
        if self._wind_forecaster is None:
            self._wind_forecaster = WindNowcaster(seed=self._seed)
        return self._wind_forecaster

    @property
    def solar_forecaster(self) -> SolarNowcaster:
        if self._solar_forecaster is None:
            self._solar_forecaster = SolarNowcaster(seed=self._seed)
        return self._solar_forecaster

    def forecast_load(
        self,
        historical_load: list[float],
        horizon_steps: int = 4,
        temperature: float | None = None,
        hour_of_day: int | None = None,
        day_of_week: int | None = None,
        simulated_time: str | None = None,
    ) -> dict[str, Any]:
        """15-minute load forecast tool.

        Args:
            historical_load: List of historical load values in MW.
            horizon_steps: Number of 15-min steps to forecast (default 4 = 1h).
            temperature: Current temperature in Celsius.
            hour_of_day: 0-23 hour.
            day_of_week: 0=Monday, 6=Sunday.
            simulated_time: ISO-format datetime string.
        """
        cache_key = _build_cache_key(
            "load",
            values=historical_load,
            steps=horizon_steps,
            temp=temperature,
            hod=hour_of_day,
            dow=day_of_week,
        )

        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.debug("Cache hit for load forecast")
            return cached

        sim_time = datetime.fromisoformat(simulated_time) if simulated_time else None
        inputs = {
            "num_historical_points": len(historical_load),
            "horizon_steps": horizon_steps,
            "temperature_c": temperature,
            "hour_of_day": hour_of_day,
            "day_of_week": day_of_week,
        }

        try:
            output = self.load_forecaster.forecast(
                historical_load=np.array(historical_load, dtype=np.float64),
                horizon_steps=horizon_steps,
                temperature=temperature,
                hour_of_day=hour_of_day,
                day_of_week=day_of_week,
            )
            result = _forecast_output_to_result(output, inputs, sim_time)
        except Exception as exc:
            logger.error("Load forecast failed: %s", exc, exc_info=True)
            result = _make_error_result(f"Load forecast error: {exc}")

        self._cache.set(cache_key, result)
        return result

    def forecast_wind(
        self,
        historical_wind_speed: list[float],
        horizon_steps: int = 4,
        rated_power_mw: float = 2.0,
        v_cut_in: float = 3.0,
        v_rated: float = 12.0,
        v_cut_out: float = 25.0,
        simulated_time: str | None = None,
    ) -> dict[str, Any]:
        """Wind power nowcast tool.

        Args:
            historical_wind_speed: List of historical wind speed values in m/s.
            horizon_steps: Number of 15-min steps to forecast.
            rated_power_mw: Turbine rated power in MW.
            v_cut_in: Cut-in wind speed in m/s.
            v_rated: Rated wind speed in m/s.
            v_cut_out: Cut-out wind speed in m/s.
            simulated_time: ISO-format datetime string.
        """
        cache_key = _build_cache_key(
            "wind",
            values=historical_wind_speed,
            steps=horizon_steps,
            rated=rated_power_mw,
            cut_in=v_cut_in,
            rated_ws=v_rated,
            cut_out=v_cut_out,
        )

        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.debug("Cache hit for wind forecast")
            return cached

        sim_time = datetime.fromisoformat(simulated_time) if simulated_time else None
        inputs = {
            "num_historical_points": len(historical_wind_speed),
            "horizon_steps": horizon_steps,
            "rated_power_mw": rated_power_mw,
            "v_cut_in": v_cut_in,
            "v_rated": v_rated,
            "v_cut_out": v_cut_out,
        }

        try:
            output = self.wind_forecaster.forecast(
                historical_wind_speed=np.array(historical_wind_speed, dtype=np.float64),
                horizon_steps=horizon_steps,
                rated_power_mw=rated_power_mw,
                v_cut_in=v_cut_in,
                v_rated=v_rated,
                v_cut_out=v_cut_out,
            )
            result = _forecast_output_to_result(output, inputs, sim_time)
        except Exception as exc:
            logger.error("Wind forecast failed: %s", exc, exc_info=True)
            result = _make_error_result(f"Wind forecast error: {exc}")

        self._cache.set(cache_key, result)
        return result

    def forecast_solar(
        self,
        historical_irradiance: list[float],
        horizon_steps: int = 4,
        rated_power_mw: float = 1.0,
        panel_efficiency: float = 0.18,
        system_loss_factor: float = 0.85,
        cloud_cover_okta: float = 3.0,
        hour_of_day: int | None = None,
        simulated_time: str | None = None,
    ) -> dict[str, Any]:
        """Solar power nowcast tool.

        Args:
            historical_irradiance: List of historical GHI values in W/m².
            horizon_steps: Number of 15-min steps to forecast.
            rated_power_mw: Panel rated power in MW.
            panel_efficiency: Panel conversion efficiency (default 0.18).
            system_loss_factor: System derating factor (default 0.85).
            cloud_cover_okta: Cloud cover 0-8 okta scale.
            hour_of_day: 0-23 hour for diurnal covariate.
            simulated_time: ISO-format datetime string.
        """
        cache_key = _build_cache_key(
            "solar",
            values=historical_irradiance,
            steps=horizon_steps,
            rated=rated_power_mw,
            eff=panel_efficiency,
            loss=system_loss_factor,
            cloud=cloud_cover_okta,
            hod=hour_of_day,
        )

        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.debug("Cache hit for solar forecast")
            return cached

        sim_time = datetime.fromisoformat(simulated_time) if simulated_time else None
        inputs = {
            "num_historical_points": len(historical_irradiance),
            "horizon_steps": horizon_steps,
            "rated_power_mw": rated_power_mw,
            "panel_efficiency": panel_efficiency,
            "system_loss_factor": system_loss_factor,
            "cloud_cover_okta": cloud_cover_okta,
            "hour_of_day": hour_of_day,
        }

        try:
            output = self.solar_forecaster.forecast(
                historical_irradiance=np.array(historical_irradiance, dtype=np.float64),
                horizon_steps=horizon_steps,
                rated_power_mw=rated_power_mw,
                panel_efficiency=panel_efficiency,
                system_loss_factor=system_loss_factor,
                cloud_cover_okta=cloud_cover_okta,
                hour_of_day=hour_of_day,
            )
            result = _forecast_output_to_result(output, inputs, sim_time)
        except Exception as exc:
            logger.error("Solar forecast failed: %s", exc, exc_info=True)
            result = _make_error_result(f"Solar forecast error: {exc}")

        self._cache.set(cache_key, result)
        return result

    def get_tools(self) -> list[dict[str, Any]]:
        """Return MCP-compatible tool listing."""
        return [
            {
                "name": "forecast_load",
                "description": "Generate 15-minute power grid load forecast using TimesFM 2.5 with uncertainty bounds. Returns mean, 80%, and 90% prediction intervals for each horizon step.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "historical_load": {
                            "type": "array",
                            "items": {"type": "number"},
                            "description": "Historical load values in MW (at least 4 points recommended)",
                        },
                        "horizon_steps": {
                            "type": "integer",
                            "default": 4,
                            "description": "Number of 15-minute steps to forecast",
                        },
                        "temperature": {
                            "type": "number",
                            "description": "Current temperature in Celsius (optional covariate)",
                        },
                        "hour_of_day": {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": 23,
                            "description": "Current hour 0-23 (optional covariate)",
                        },
                        "day_of_week": {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": 6,
                            "description": "Current day 0=Monday, 6=Sunday (optional covariate)",
                        },
                        "simulated_time": {
                            "type": "string",
                            "description": "ISO-format datetime for the simulation timestamp",
                        },
                    },
                    "required": ["historical_load"],
                },
            },
            {
                "name": "forecast_wind",
                "description": "Generate wind power nowcast using TimesFM 2.5. Converts predicted wind speed to power via IEC 61400 power curve.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "historical_wind_speed": {
                            "type": "array",
                            "items": {"type": "number"},
                            "description": "Historical wind speed values in m/s",
                        },
                        "horizon_steps": {
                            "type": "integer",
                            "default": 4,
                            "description": "Number of 15-minute steps to forecast",
                        },
                        "rated_power_mw": {
                            "type": "number",
                            "default": 2.0,
                            "description": "Turbine rated power in MW",
                        },
                        "v_cut_in": {
                            "type": "number",
                            "default": 3.0,
                            "description": "Cut-in wind speed in m/s",
                        },
                        "v_rated": {
                            "type": "number",
                            "default": 12.0,
                            "description": "Rated wind speed in m/s",
                        },
                        "v_cut_out": {
                            "type": "number",
                            "default": 25.0,
                            "description": "Cut-out wind speed in m/s",
                        },
                        "simulated_time": {
                            "type": "string",
                            "description": "ISO-format datetime for the simulation timestamp",
                        },
                    },
                    "required": ["historical_wind_speed"],
                },
            },
            {
                "name": "forecast_solar",
                "description": "Generate solar power nowcast using TimesFM 2.5. Converts predicted irradiance to power output using PV model.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "historical_irradiance": {
                            "type": "array",
                            "items": {"type": "number"},
                            "description": "Historical GHI values in W/m²",
                        },
                        "horizon_steps": {
                            "type": "integer",
                            "default": 4,
                            "description": "Number of 15-minute steps to forecast",
                        },
                        "rated_power_mw": {
                            "type": "number",
                            "default": 1.0,
                            "description": "Panel rated power in MW",
                        },
                        "panel_efficiency": {
                            "type": "number",
                            "default": 0.18,
                            "description": "Panel conversion efficiency",
                        },
                        "system_loss_factor": {
                            "type": "number",
                            "default": 0.85,
                            "description": "System derating factor (1.0 = no loss)",
                        },
                        "cloud_cover_okta": {
                            "type": "number",
                            "default": 3.0,
                            "description": "Cloud cover on 0-8 okta scale",
                        },
                        "hour_of_day": {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": 23,
                            "description": "Current hour 0-23 (optional covariate)",
                        },
                        "simulated_time": {
                            "type": "string",
                            "description": "ISO-format datetime for the simulation timestamp",
                        },
                    },
                    "required": ["historical_irradiance"],
                },
            },
        ]

    def handle_request(self, request: dict[str, Any]) -> dict[str, Any]:
        """Process a single MCP JSON-RPC-style request.

        Args:
            request: Dict with 'method' and 'params' keys.

        Returns:
            Response dict.
        """
        method = request.get("method", "")
        params = request.get("params", {})

        if method == "tools/list":
            return {"tools": self.get_tools()}

        if method == "tools/call":
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})

            handler_map: dict[str, Callable[..., dict[str, Any]]] = {
                "forecast_load": self.forecast_load,
                "forecast_wind": self.forecast_wind,
                "forecast_solar": self.forecast_solar,
            }

            if tool_name not in handler_map:
                return _make_error_result(
                    f"Unknown tool: {tool_name}. Available: {list(handler_map.keys())}",
                    error_code="UNKNOWN_TOOL",
                )

            try:
                return handler_map[tool_name](**arguments)
            except TypeError as exc:
                return _make_error_result(
                    f"Invalid arguments for {tool_name}: {exc}",
                    error_code="INVALID_ARGUMENTS",
                )

        return _make_error_result(
            f"Unknown method: {method}",
            error_code="UNKNOWN_METHOD",
        )


# ---------------------------------------------------------------------------
# Standalone process entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Run the forecast MCP server as a standalone JSON-line stdin/stdout process."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )

    server = ForecastMCPServer()
    logger.info("AthenaAI Forecast MCP server starting on stdin/stdout")

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            error_resp = _make_error_result(f"Invalid JSON: {exc}", "PARSE_ERROR")
            sys.stdout.write(json.dumps(error_resp) + "\n")
            sys.stdout.flush()
            continue

        response = server.handle_request(request)
        sys.stdout.write(json.dumps(response, default=str) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()

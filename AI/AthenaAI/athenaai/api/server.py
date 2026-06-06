"""Headless API server for AthenaAI simulation.

Provides deterministic replay mode and agent decision logging.
Uses stdlib http.server - no external web framework required.
"""

from __future__ import annotations

import json
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

from athenaai.agent_runtime import AgentRuntime, create_runtime
from athenaai.audit.logger import AuditLogger
from athenaai.schema import ActionBundle
from athenaai.simulator import GridSimulator


class SimulationAPIServer:
    def __init__(
        self,
        simulator: GridSimulator,
        runtime: AgentRuntime | None = None,
        host: str = "localhost",
        port: int = 8080,
    ) -> None:
        self._simulator = simulator
        self._runtime = runtime or create_runtime(simulator)
        self._host = host
        self._port = port
        self._server: HTTPServer | None = None
        self._running = False
        self._replay_mode = True

    @property
    def replay_mode(self) -> bool:
        return self._replay_mode

    @replay_mode.setter
    def replay_mode(self, value: bool) -> None:
        self._replay_mode = value

    def start(self) -> None:
        if self._running:
            return

        handler = self._create_request_handler()
        self._server = HTTPServer((self._host, self._port), handler)
        self._running = True
        self._server.serve_forever()

    def stop(self) -> None:
        if self._server and self._running:
            self._server.shutdown()
            self._running = False

    def _create_request_handler(self) -> type[BaseHTTPRequestHandler]:
        simulator_ref = self._simulator
        runtime_ref = self._runtime
        replay_mode_ref = self._replay_mode

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if self.path == "/health":
                    self._send_json(200, {"status": "ok", "replay_mode": replay_mode_ref})
                elif self.path == "/observation":
                    obs = simulator_ref.get_observation()
                    self._send_json(200, self._observation_to_dict(obs))
                elif self.path == "/audit":
                    self._send_json(200, {"logs": runtime_ref.audit_logger.get_logs()})
                else:
                    self._send_json(404, {"error": "Not found"})

            def do_POST(self) -> None:
                if self.path == "/step":
                    content_length = int(self.headers.get("Content-Length", 0))
                    body = self.rfile.read(content_length).decode("utf-8")
                    data = json.loads(body) if body else {}
                    hour = data.get("hour", simulator_ref.current_hour + 1)
                    result = runtime_ref.run_hour_step(hour)
                    self._send_json(200, self._step_result_to_dict(result))
                elif self.path == "/action":
                    content_length = int(self.headers.get("Content-Length", 0))
                    body = self.rfile.read(content_length).decode("utf-8")
                    data = json.loads(body)
                    action = self._dict_to_action(data)
                    obs = simulator_ref.get_observation()
                    eval_result = simulator_ref.evaluate(action, obs)
                    self._send_json(200, eval_result)
                else:
                    self._send_json(404, {"error": "Not found"})

            def _send_json(self, code: int, data: Any) -> None:
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(data).encode("utf-8"))

            def _observation_to_dict(self, obs: Any) -> dict[str, Any]:
                return {
                    "hour_index": obs.hour_index,
                    "timestamp": obs.timestamp.isoformat(),
                    "is_intraday": obs.is_intraday,
                    "has_violations": obs.has_violations(),
                    "scada": {
                        "total_generation_mw": obs.scada.total_generation_mw,
                        "total_load_mw": obs.scada.total_load_mw,
                        "num_buses": len(obs.scada.buses),
                        "num_branches": len(obs.scada.branches),
                        "num_generators": len(obs.scada.generators),
                        "num_loads": len(obs.scada.loads),
                    },
                }

            def _step_result_to_dict(self, result: dict[str, Any]) -> dict[str, Any]:
                return {
                    "hour_index": result["hour_index"],
                    "observation": self._observation_to_dict(result["observation"]),
                    "num_evaluation_results": len(result["evaluation_results"]),
                }

            def _dict_to_action(self, data: dict[str, Any]) -> ActionBundle:
                return ActionBundle(
                    timestamp=datetime.fromisoformat(data["timestamp"]),
                    agent_id=data["agent_id"],
                )

        return _Handler
"""AthenaAI configuration module.

This module centralizes all configuration for AthenaAI including:
- Model identifiers (Kimi K2.6)
- Environment variable handling for API keys
- OpenCode configuration paths
- Agent definitions
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final

from dotenv import load_dotenv

load_dotenv()

# =============================================================================
# Model Configuration
# =============================================================================

# Centralized model identifier for all agents.
# Use this constant in agent configs to ensure consistency.
# Provider slug is intentionally abstracted to allow easy provider switching.
KIMI_K2_6_MODEL: Final[str] = "kimi-k2.6"

# OpenCode Go configuration
# The API key is consumed from this env var by opencode Go binary.
# SECURITY: Never hardcode the actual key value in tracked files.
OPENCODE_GO_API_KEY_ENV_VAR: Final[str] = "OPENCODE_GO_API_KEY"
OPENCODE_GO_API_URL_ENV_VAR: Final[str] = "OPENCODE_GO_API_URL"
DEFAULT_OPENCODE_GO_API_URL: Final[str] = "https://opencode.ai/zen/go/v1"


def get_opencode_api_key() -> str | None:
    """Retrieve the OpenCode Go API key from environment variable.

    Returns:
        The API key value if set, otherwise None.

    Note:
        The actual key value is set by the deployment environment.
        This function never logs or exposes the key value.
    """
    return os.environ.get(OPENCODE_GO_API_KEY_ENV_VAR)


def get_opencode_api_url() -> str:
    """Return the OpenAI-compatible base URL for model control."""
    return os.environ.get(OPENCODE_GO_API_URL_ENV_VAR, DEFAULT_OPENCODE_GO_API_URL)


# =============================================================================
# Path Configuration
# =============================================================================

# Root AthenaAI directory
ATHENAAI_ROOT: Path = Path(__file__).parent.parent.resolve()

# OpenCode configuration directory
OPENCODE_CONFIG_DIR: Path = ATHENAAI_ROOT / "opencode"

# Verify OpenCode config exists
def get_opencode_config_path() -> Path:
    """Return the path to the OpenCode configuration file.

    Returns:
        Path to opencode.jsonc in the AthenaAI opencode directory.

    Raises:
        FileNotFoundError: If the config file does not exist.
    """
    config_path = OPENCODE_CONFIG_DIR / "opencode.jsonc"
    if not config_path.exists():
        raise FileNotFoundError(
            f"OpenCode config not found at {config_path}. "
            "Please ensure ./AthenaAI/opencode/opencode.jsonc exists."
        )
    return config_path


# =============================================================================
# Agent Definitions
# =============================================================================

# Agent identifiers
AGENT_COORDINATOR: Final[str] = "coordinator"
AGENT_BOHEMIA_WEST: Final[str] = "bohemia-west"
AGENT_BOHEMIA_EAST: Final[str] = "bohemia-east"
AGENT_MORAVIA: Final[str] = "moravia"
AGENT_SILESIA: Final[str] = "silesia"
AGENT_ORACLE: Final[str] = "oracle"

# All regional agents
REGIONAL_AGENTS: list[str] = [
    AGENT_BOHEMIA_WEST,
    AGENT_BOHEMIA_EAST,
    AGENT_MORAVIA,
    AGENT_SILESIA,
]

# All agents including coordinator
ALL_AGENTS: list[str] = [AGENT_COORDINATOR] + REGIONAL_AGENTS + [AGENT_ORACLE]


# =============================================================================
# Simulation Configuration
# =============================================================================

# Default simulation parameters
DEFAULT_SIMULATION_STEP_MINUTES: Final[int] = 15
DEFAULT_DAY_AHEAD_HOURS: Final[int] = 24

# Dataset paths (relative to AthenaAI root)
DATASET_ROOT: Path = ATHENAAI_ROOT.parent / "greenhack-2026-ČEPS-dataset"
DATASET_STATIC: Path = DATASET_ROOT / "data" / "static"
DATASET_SNAPSHOTS: Path = DATASET_ROOT / "data" / "snapshots"
DATASET_REALTIME: Path = DATASET_ROOT / "data" / "realtime"
DATASET_FORECASTS: Path = DATASET_ROOT / "data" / "forecasts"
DATASET_FUEL_PRICES: Path = DATASET_ROOT / "data" / "other" / "Fuel prices 2024.csv"

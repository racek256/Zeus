"""Test agents module."""

from athenaai.agents import (
    get_agent_config,
    get_all_agent_configs,
    AgentConfig,
    COORDINATOR_PROMPT,
    BOHEMIA_WEST_PROMPT,
    BOHEMIA_EAST_PROMPT,
    MORAVIA_PROMPT,
    SILESIA_PROMPT,
    ORACLE_PROMPT,
)
from athenaai.config import (
    KIMI_K2_6_MODEL,
    AGENT_COORDINATOR,
    AGENT_BOHEMIA_WEST,
    AGENT_BOHEMIA_EAST,
    AGENT_MORAVIA,
    AGENT_SILESIA,
    AGENT_ORACLE,
)


class TestAgentConfigs:
    def test_get_coordinator_config(self):
        config = get_agent_config(AGENT_COORDINATOR)
        assert config.agent_id == AGENT_COORDINATOR
        assert config.model == KIMI_K2_6_MODEL
        assert len(config.system_prompt) > 0

    def test_get_bohemia_west_config(self):
        config = get_agent_config(AGENT_BOHEMIA_WEST)
        assert config.agent_id == AGENT_BOHEMIA_WEST
        assert config.model == KIMI_K2_6_MODEL
        assert "Temelín" in config.system_prompt or "nuclear" in config.system_prompt.lower()

    def test_get_bohemia_east_config(self):
        config = get_agent_config(AGENT_BOHEMIA_EAST)
        assert config.agent_id == AGENT_BOHEMIA_EAST
        assert "Prague" in config.system_prompt

    def test_get_moravia_config(self):
        config = get_agent_config(AGENT_MORAVIA)
        assert config.agent_id == AGENT_MORAVIA
        assert "Dalešice" in config.system_prompt or "hydro" in config.system_prompt.lower()

    def test_get_silesia_config(self):
        config = get_agent_config(AGENT_SILESIA)
        assert config.agent_id == AGENT_SILESIA
        assert "Poland" in config.system_prompt

    def test_get_oracle_config(self):
        config = get_agent_config(AGENT_ORACLE)
        assert config.agent_id == AGENT_ORACLE
        assert "read-only" in config.system_prompt.lower() or "diagnostic" in config.system_prompt.lower()

    def test_get_invalid_agent_raises(self):
        try:
            get_agent_config("invalid-agent")
        except ValueError:
            return
        raise AssertionError("Expected ValueError for invalid agent")

    def test_all_agent_configs_returns_six(self):
        configs = get_all_agent_configs()
        assert len(configs) == 6


class TestAgentPrompts:
    def test_coordinator_prompt_mentions_n1(self):
        assert "N-1" in COORDINATOR_PROMPT

    def test_coordinator_prompt_mentions_deadlock(self):
        assert "deadlock" in COORDINATOR_PROMPT.lower()

    def test_all_prompts_mention_todo_discipline(self):
        for prompt in [COORDINATOR_PROMPT, BOHEMIA_WEST_PROMPT, BOHEMIA_EAST_PROMPT, MORAVIA_PROMPT, SILESIA_PROMPT, ORACLE_PROMPT]:
            assert "TODO" in prompt

    def test_all_prompts_mention_agents_reason_tools_calculate(self):
        for prompt in [COORDINATOR_PROMPT, BOHEMIA_WEST_PROMPT, BOHEMIA_EAST_PROMPT, MORAVIA_PROMPT, SILESIA_PROMPT, ORACLE_PROMPT]:
            assert "agents reason" in prompt.lower() or "tools calculate" in prompt.lower()

    def test_all_prompts_mention_simulation_time(self):
        for prompt in [COORDINATOR_PROMPT, BOHEMIA_WEST_PROMPT, BOHEMIA_EAST_PROMPT, MORAVIA_PROMPT, SILESIA_PROMPT]:
            assert "simulation time" in prompt.lower() or "simulated time" in prompt.lower()

    def test_regional_prompts_are_not_coordinator(self):
        for prompt in [BOHEMIA_WEST_PROMPT, BOHEMIA_EAST_PROMPT, MORAVIA_PROMPT, SILESIA_PROMPT]:
            assert "coordinator" in prompt.lower()
            assert "peer agent" in prompt.lower() or "peer" in prompt.lower()

    def test_oracle_prompt_is_read_only(self):
        assert "never make decisions" in ORACLE_PROMPT.lower()


class TestAgentModelConsistency:
    def test_all_configs_use_kimi_k2_6(self):
        configs = get_all_agent_configs()
        for config in configs:
            assert config.model == KIMI_K2_6_MODEL

    def test_global_model_override_applies_to_all_agents(self):
        configs = get_all_agent_configs({"all": "test/global-model"})
        assert {config.model for config in configs} == {"test/global-model"}

    def test_role_model_overrides_take_precedence_over_global(self):
        configs = {
            config.agent_id: config
            for config in get_all_agent_configs(
                {
                    "all": "test/global-model",
                    "coordinator": "test/coordinator-model",
                    "regional": "test/regional-model",
                    "oracle": "test/oracle-model",
                }
            )
        }
        assert configs[AGENT_COORDINATOR].model == "test/coordinator-model"
        assert configs[AGENT_BOHEMIA_WEST].model == "test/regional-model"
        assert configs[AGENT_BOHEMIA_EAST].model == "test/regional-model"
        assert configs[AGENT_MORAVIA].model == "test/regional-model"
        assert configs[AGENT_SILESIA].model == "test/regional-model"
        assert configs[AGENT_ORACLE].model == "test/oracle-model"

    def test_exact_agent_model_override_takes_highest_precedence(self):
        config = get_agent_config(
            AGENT_BOHEMIA_WEST,
            {
                "all": "test/global-model",
                "regional": "test/regional-model",
                AGENT_BOHEMIA_WEST: "test/west-model",
            },
        )
        assert config.model == "test/west-model"

    def test_all_configs_have_nonempty_prompt(self):
        configs = get_all_agent_configs()
        for config in configs:
            assert len(config.system_prompt) > 100

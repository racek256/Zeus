# Phase OpenCode Plan

## Clarified decision

Use **MCP-first integration** for Phase 2.1.

## Implementation target

- Expose AthenaAI physics, market, forecast, SCADA, peer-bus, and audit functions through local MCP-style Python services/wrappers.
- Keep OpenCode configuration under `./AthenaAI/opencode` and run it through an explicit custom config path/environment.
- Use plugins only if needed for coordination glue; do not make TypeScript OpenCode plugins the main compute/tool layer.
- Add a read-only Oracle subagent using the Oh My OpenAgent Oracle prompt source found at `code-yeongyu/oh-my-openagent/src/agents/oracle.ts`.

## Research constraints to preserve

- Agents reason; tools calculate.
- MCP/tool calls are the boundary between LLMs and deterministic simulator state.
- Custom OpenCode config should use the official schema URL where possible.
- Peer communication should be a shared bus with typed messages, not direct regional-agent commands.
- API keys must not be printed in logs, tests, or final output.

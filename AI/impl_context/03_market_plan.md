# Phase Market Plan

## Clarified decision

Use **EU/Czech market approximations** in v1.

## Implementation target

- Market tools are advisory only and must never mutate simulator physics state.
- Merit-order dispatch uses fuel prices, generator categories, marginal-cost approximations, and available capacity.
- Redispatch cost calculation uses upward/downward adjustment volume and technology/fuel marginal-cost estimates.
- Balancing group check reports deviations per region/group and settlement interval.
- Interconnect schedule calculation uses simplified ATC/flow constraints where exact Core flow-based coupling is unavailable.
- Reserve adequacy checks largest contingency, available headroom, and reserve margins.
- Imbalance pricing uses simplified EU/Czech-style activated-balancing-cost logic.

## Validation expectations

- Outputs must be deterministic for a fixed input.
- Every tool returns recommendations/costs/violations, not physical commands.
- Coordinator must validate any recommendation through physics tools before execution.

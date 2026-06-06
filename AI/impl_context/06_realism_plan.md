# Phase Realism Plan

## Clarified decision

Enforce **hard P0 physics gates** in v1.

**Note**: Hard P0 physics gates in this plan are binding for **Phase 2.2+**. Phase 2.1 operates in bootstrap/placeholder mode where physics tools return deterministic stub results. This plan governs what the realism enforcement must eventually become, not what Phase 2.1 must already implement.

## Oracle-derived non-negotiables

- Physics engine is the only authority over physical state evolution.
- Agents are advisory only.
- Non-convergence means physically impossible, not a soft warning.
- Thermal and voltage limits are hard gates.
- Ramp rates prevent infinite generator flexibility.
- N-1 security is a pre-dispatch gate, not a post-hoc score.
- State-estimation uncertainty must prevent omniscient operation at 99.9% limits.
- Topology/islanding must be detected after contingencies or trips.

## Test implications

- Tests must include non-convergence rejection.
- Tests must include thermal and voltage violation rejection.
- Tests must include ramp-rate rejection.
- Tests must include N-1 contingency failure detection.
- Tests must include uncertainty bounds for observations/state estimation.
- Tests must prove no market or agent component bypasses the simulator.

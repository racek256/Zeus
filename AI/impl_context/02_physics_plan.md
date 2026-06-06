# Phase Physics Plan

## Clarified decision

Implement **full physics now** where practical: pandapower steady-state physics plus PyPSA/ANDES-capable wrappers rather than placeholder-only interfaces.

**Note**: Full physics requirements in this plan are binding for **Phase 2.2+**. Phase 2.1 is explicitly allowed to contain deterministic placeholder interfaces only. This plan governs what the physics layer must eventually become, not what Phase 2.1 must already be.

## Implementation target

- AC load flow: pandapower Newton-Raphson via `runpp`; non-convergence is a hard failure.
- OPF: include a real OPF path, preferably PyPSA-backed when available, with pandapower/DC fallback only as explicit degraded mode.
- N-1: sequential deterministic scan over critical lines, transformers, and generators; failed contingency is a hard security failure.
- Frequency response: provide an ANDES-capable integration path and deterministic aggregate swing-equation fallback only when ANDES is unavailable in tests.
- Short-circuit: pandapower IEC 60909 wrapper.
- State estimation: pandapower WLS plus uncertainty bounds; conservative bounds are acceptable where tight bounds are not available.

## Hard gates

- Reject non-convergent load flow.
- Reject thermal-limit violations.
- Reject voltage-limit violations.
- Reject ramp-rate violations.
- Reject failed N-1 security.
- Detect islanding and unsupplied buses.

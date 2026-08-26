# P0-P5 Proof Ladder

Use the lowest-cost evidence first and escalate only as far as the request and claim require. A higher level includes relevant lower-level gates; it does not erase their failures.

## Levels

- **P0 — Static Proof:** syntax, import, parse, and other static checks succeed for changed material.
- **P1 — Runtime Proof:** the relevant project boots or starts, runtime errors are checked, and runtime readiness is established.
- **P2 — Layout Proof:** UI and layout are measured and inspected through static visual evidence and screenshots.
- **P3 — Behavior Proof:** deterministic scenarios prove gameplay, input, and state-transition behavior.
- **P4 — Visual Motion Proof:** animation and motion are inspected through capture and temporal evidence, including a proof sheet or video when required.
- **P5 — Release Proof:** the intended export or artifact is produced and audited as a release candidate for launchability, required content, configuration, and distributable artifacts.

## Escalation and repair

Choose the target level from the requested completion claim. Run P0 before expensive launches, P1 before interactive inspection, and P2 before P3-P5. Skip a level only when it is genuinely irrelevant and record why; a required skipped gate makes the result UNKNOWN.

When a gate fails, preserve its evidence, repair the smallest attributable cause, then rerun that gate and every downstream gate invalidated by the repair. Stop when the target level passes, a required fact or dependency remains unknown, the same failure no longer has a safe in-scope repair, or the next step needs user authority.

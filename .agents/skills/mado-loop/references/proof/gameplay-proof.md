# Gameplay and Playtest Proof

Use this protocol for `GAMEPLAY` or `PLAYTEST` work. A playtest is evidence only when another operator can reconstruct what ran, what input was applied, and what was observed. Do not promote an impression or a specialist assertion into a measurable claim.

## Test declaration

Record before execution:

- build identity: commit or package identifier, Godot version, platform, configuration, and relevant feature flags;
- scene and state: project path, entry scene, save/checkpoint or fixture, viewport, locale, input map, and initial game state;
- intent and acceptance criteria, including the required P0-P5 levels;
- an ordered input sequence with device, action, value, timing or frame boundary, and expected state transition;
- assumptions, constraints, and unresolved facts in `unknowns` when they could invalidate the claim.

Prefer a seeded fixture, fixed timestep, known save, scripted input, stable viewport, and controlled locale. Record every seed and timing rule. When determinism is impossible, state the source of variation, repeat count, and allowed tolerance; never describe a nondeterministic run as deterministic.

## Execution record

For each step, pair **expected** and **observed** results. Include the starting state, exact reproduction steps, first divergent step, frequency, and whether a clean restart reproduces it. Capture relevant stdout/stderr, Godot logs, structured result JSON, screenshots or video, save/fixture data, and build metadata. Artifact records should include stable paths and hashes where the proof tooling provides them; do not embed secrets or personal data.

Classify findings consistently:

| Severity | Meaning |
| --- | --- |
| Blocker | Prevents launch, test execution, proof collection, or release use; no viable continuation. |
| Critical | Crash, data loss, security/privacy exposure, or mandatory core path failure. |
| Major | Required behavior is wrong or unusable, with no acceptable normal-workflow workaround. |
| Minor | Localized incorrect behavior with a practical workaround; acceptance is still affected. |
| Cosmetic | Presentation defect that does not change behavior, readability, or required interaction. |
| Observation | Non-defect note or hypothesis requiring no pass/fail claim. |

Retest a fix with the original sequence, then run neighboring and previously passing paths. Record regressions separately, linking each to the build, original finding, rerun, and new artifact evidence.

## Human feel versus measurable claims

Keep two explicit sections:

- **Measured:** state transitions, frames/times, counts, positions, error output, input response, tolerances, and acceptance outcome.
- **Human feel:** perceived responsiveness, clarity, pacing, comfort, delight, confusion, and tester context.

Human feel can motivate a requirement or follow-up experiment, but it cannot make a measured failure pass. Attribute it to the tester and session; do not generalize one person's preference into a universal conclusion.

## P0-P5 relationship

Use the proof runner's definitions and results as authoritative. The gameplay record contributes evidence as follows:

- **P0:** project/build opens and the declared entry point can be exercised.
- **P1:** runtime starts without disqualifying parse or runtime errors.
- **P2:** declared scene, layout, resources, and initial state are structurally valid.
- **P3:** the input sequence produces the required deterministic behavior and state transitions.
- **P4:** captures or proof sheets show the required visible/motion outcome under the declared setup.
- **P5:** export/package and release artifacts contain the tested outcome and pass artifact audit.

Do not infer one level from another. Report the highest level actually established and retain per-level checks. A mandatory level that cannot run is not a pass.

## Result semantics

Emit schema v1.1 with canonical `task_domains` and derived `MIXED` when applicable. A reproducible deviation from a measurable requirement is `FAIL`. An unresolved fact that could invalidate the claim belongs in `unknowns` and makes the result `UNKNOWN` unless a failure already exists. An unavailable required runtime, input, or capture route is a required `SKIPPED` check and therefore `UNKNOWN`; an unavailable optional helper is optional `SKIPPED` plus warning. Top-level `SKIPPED` applies only when the entire playtest is legitimately not requested or not applicable. Precedence is `FAIL` over `UNKNOWN` over `WARN` over `PASS`.

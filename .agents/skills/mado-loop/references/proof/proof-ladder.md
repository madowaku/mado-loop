# P0-P5 Proof Ladder

Use the lowest-cost evidence first and escalate only as far as the request and claim require. A higher level includes relevant lower-level gates; it does not erase their failures.

## Levels

- **P0 — Syntax/import:** parse, load, import, and deterministic contract checks succeed for changed material.
- **P1 — Headless/static integration:** Godot headless checks, resource resolution, scene loading, and nonvisual integration checks succeed.
- **P2 — Runtime smoke:** the relevant scene or game starts and the changed path executes without blocking runtime errors.
- **P3 — Visual and interaction inspection:** captured output and input behavior demonstrate the intended UI, animation, sprite, or gameplay state.
- **P4 — Gameplay/playtest:** declared scenarios exercise mechanics and user flows, with measurable observations separated from subjective feel.
- **P5 — Export/release:** the intended export or release candidate is produced and audited for launchability, required content, configuration, and distributable artifacts.

## Escalation and repair

Choose the target level from the requested completion claim. Run P0 before expensive launches, P1 before interactive inspection, and P2 before P3-P5. Skip a level only when it is genuinely irrelevant and record why; a required skipped gate makes the result UNKNOWN.

When a gate fails, preserve its evidence, repair the smallest attributable cause, then rerun that gate and every downstream gate invalidated by the repair. Stop when the target level passes, a required fact or dependency remains unknown, the same failure no longer has a safe in-scope repair, or the next step needs user authority.

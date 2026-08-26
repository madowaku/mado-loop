# Routing architecture

Read this reference when a request spans production domains or when MADO LOOP must decide which specialists and tools participate. For capability availability and source provenance, continue to [capability-registry.md](capability-registry.md) and [source-policy.md](source-policy.md).

## Layer boundaries

MADO LOOP uses four layers with distinct ownership:

1. **ORCHESTRATOR** understands the request, classifies domains, composes the route, controls acceptance, and aggregates evidence. It does not silently substitute a weaker capability for a required one.
2. **SPECIALISTS** supply domain-specific instructions through progressively disclosed references or an explicitly routed installed capability. They do not own the final status.
3. **ENGINE / ASSET TOOLS** perform deterministic engine or asset operations through first-party adapters. Vendored payloads remain immutable.
4. **PROOF SYSTEM** combines checks into P0-P5 evidence and computes the result. A specialist's assertion is not proof by itself.

Keep orchestration separate from implementation. Route only the references and capabilities needed for the classified domains; do not load the entire specialist library.

## Domain classification

The concrete domain order is canonical:

`CODE`, `GAMEPLAY`, `UI`, `SPRITE`, `IMAGE`, `ANIMATION`, `ASSET_INTEGRATION`, `REFERENCE_TO_UI`, `PIXEL_ART`, `PLAYTEST`, `RELEASE`.

Deduplicate classified domains while retaining this order. Append `MIXED` only when two or more concrete domains are present. `MIXED` is a derived marker: never route it alone, duplicate it, or treat it as a specialist.

Route each concrete domain as follows:

| Domain | Primary responsibility | Typical composition |
| --- | --- | --- |
| `CODE` | Godot project and GDScript implementation | Godot engine tooling, then relevant proof checks |
| `GAMEPLAY` | Mechanics, state, controls, and game feel | Code plus playtest when observable behavior matters |
| `UI` | Game UI structure, interaction, layout, and legibility | UI guidance, engine integration, visual inspection |
| `SPRITE` | Sprite generation, sheet normalization, and frame integrity | Sprite guidance plus deterministic sprite processing |
| `IMAGE` | New or edited raster imagery | Optional ImageGen or an explicitly selected external editor |
| `ANIMATION` | Frame or engine animation behavior | Sprite and/or Godot animation path according to asset type |
| `ASSET_INTEGRATION` | Import settings, resource wiring, and scene use | Asset processor plus Godot engine tooling |
| `REFERENCE_TO_UI` | Translating a supplied reference into game UI | No-copy product-design guidance plus UI and integration routes |
| `PIXEL_ART` | Pixel-safe constraints and review | Owner-authored generic rules plus sprite/image route as needed |
| `PLAYTEST` | Runtime interaction and observable regressions | Game playtest guidance and proof capture |
| `RELEASE` | P0-P5 release audit and package readiness | Proof system across all required checks |

## Route composition

Classify the user's requested outcome before selecting capabilities. Compose a minimal route in dependency order:

`specialist guidance -> engine/asset operation -> integration -> inspection/playtest -> proof`

Examples of composition rules:

- `SPRITE + ANIMATION + ASSET_INTEGRATION` uses sprite guidance, deterministic processing, then Godot import/wiring and runtime proof.
- `REFERENCE_TO_UI + UI + ASSET_INTEGRATION` uses no-copy reference interpretation, game UI guidance, Godot implementation, and visual/runtime checks.
- `GAMEPLAY + PLAYTEST` implements the mechanic before running interaction-based checks.
- `RELEASE` does not imply new implementation. It audits the requested release surface and reports missing proof.

Progressively disclose specialist material only when its domain is active. A routed installed specialist may contribute guidance, but MADO LOOP retains route control and result aggregation.

## Capability absence

Distinguish required from optional capability before execution:

- A missing **required** dependency prevents the claim from being established. Record the required check as `SKIPPED` and the operation as `UNKNOWN`, unless another check already establishes `FAIL`.
- A missing **optional** capability records an optional `SKIPPED` check and a warning. Continue through available routes without claiming the skipped output.
- Use top-level `SKIPPED` only when the entire operation is legitimately not applicable or was not requested.
- Do not put a merely unavailable optional feature in `unknowns`. Reserve `unknowns` for unresolved facts that could invalidate a claim.

Never auto-install a skill, plugin, registry entry, editor, model, or other external capability. Report the route and ask for authorization when installation or external mutation would be necessary.

## Optional routed capabilities

ImageGen, an external image editor, Agent Skills Hub entries, and already installed specialist skills are routing targets, not bundled implementation. Use them only when available and appropriate to an active domain. Preserve these rules:

- Do not install or enable them automatically.
- Do not imply they were used when unavailable.
- Do not copy their private or registry-delivered content into MADO LOOP.
- Validate their output with the same integration and proof layers as first-party output.

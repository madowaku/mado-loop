---
name: mado-loop
description: Orchestrate production work and evidence for Godot 4.x games when the user explicitly invokes $mado-loop.
---

# MADO LOOP

Use this skill only when the user explicitly invokes `$mado-loop`. Turn a game-development request into implemented, integrated, and honestly proven Godot work.

## Operating loop

Run **UNDERSTAND -> ROUTE -> MAKE -> INTEGRATE -> RUN -> INSPECT -> VERIFY -> FIX -> PROVE**. Repeat the run-through-fix segment only while an in-scope, safe repair remains and the active [runtime budgets](references/protocol/runtime-budgets.md) allow it. Stop when the requested outcome is proven, an unresolved fact prevents an honest claim, a budget is exhausted, or further action needs new authority.

At **UNDERSTAND**, establish one invocation budget and keep it for the life of the run. Never invoke `$mado-loop` from inside an already-active MADO LOOP run; continue inside the existing run instead. MADO LOOP must never raise or reset its own limits. A user may explicitly raise one named limit for the current invocation, and that override must be recorded.

1. **UNDERSTAND:** inspect the project, request, constraints, existing changes, proof target, and active budget. Record facts that could invalidate the result as `unknowns`.
2. **ROUTE:** run `python scripts/classify_task.py "<task>"` and use its schema-v1.1 `task_domains`. Read [routing architecture](references/routing/architecture.md) and [capability registry](references/routing/capability-registry.md), then load only references needed by the selected domains. Apply [source policy](references/routing/source-policy.md) before adopting external material.
3. **MAKE:** implement the smallest coherent change through the selected specialists and tools. Keep the orchestrator responsible for routing and acceptance, specialists responsible for domain guidance, engine/asset tools responsible for deterministic operations, and the proof system responsible for claims.
4. **INTEGRATE:** connect code, scenes, resources, imports, UI, and gameplay in the user's project without taking ownership away from existing project structure.
5. **RUN, INSPECT, VERIFY, FIX:** escalate evidence from the cheapest relevant proof level. Before each repair, file reversal, asset regeneration, or full-video inspection, check the active Loop Budget. Inspect actual output, repair observed defects, and rerun only affected checks. When a meaningful boundary is crossed, compact the working context according to the Context Budget instead of reloading raw evidence.
6. **PROVE:** report a schema-v1.1 result using `scripts/common/result.py`, artifact evidence, the achieved P0-P5 level, remaining unknowns, and an AI Creole handoff when work continues across agents. If a budget stopped the run, include the budget state and the next bounded action.

## Domain references

Load only the references relevant to the routed domains:

- `IMAGE`: [art direction](references/production/art-direction.md).
- `SPRITE`: [sprite production](references/production/sprite-production.md); also read [pixel-art profile](references/production/pixel-art-profile.md) for `PIXEL_ART`.
- `UI`: [game UI](references/production/game-ui.md).
- `REFERENCE_TO_UI`: [image to game UI](references/production/image-to-game-ui.md) and the game UI reference.
- `ASSET_INTEGRATION`: [asset integration](references/production/asset-integration.md).
- `GAMEPLAY` or `PLAYTEST`: [gameplay proof](references/proof/gameplay-proof.md).
- `CODE`, `ANIMATION`, or `RELEASE`: follow the shared loop, project conventions, and proof ladder; combine with other routed references when the result is `MIXED`.

Optional image generation or external editing is a routed capability, not an automatic dependency. Do not install or invoke it without availability and authority. Treat absence of an optional capability as an optional `SKIPPED` check and warning, not an unknown.

## Non-negotiable contracts

Before changing a project, read [project safety](references/safety/project-safety.md) and [runtime budgets](references/protocol/runtime-budgets.md). Before claiming completion, read the [completion contract](references/proof/completion-contract.md) and [proof ladder](references/proof/proof-ladder.md).

For multi-agent or resumable work, exchange [AI Creole handoffs](references/protocol/ai-creole-handoff.md). Admit durable observations only under the [FIELD NOTES policy](references/protocol/field-notes-policy.md).

Never embed specialist procedure in the final report. State what changed, checks run, proof level reached, artifacts, warnings or unknowns, budget exhaustion when relevant, and the next bounded action if incomplete.

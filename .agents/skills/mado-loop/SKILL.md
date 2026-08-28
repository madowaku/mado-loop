---
name: mado-loop
description: Orchestrate production work and evidence for Godot 4.x games when the user explicitly invokes $mado-loop.
---

# MADO LOOP

Use this skill only when the user explicitly invokes `$mado-loop`. Turn a game-development request into implemented, integrated, and honestly proven Godot work.

## Operating loop

Run **UNDERSTAND -> ROUTE -> MAKE -> INTEGRATE -> RUN -> INSPECT -> VERIFY -> FIX -> PROVE**. Repeat the run-through-fix segment while an in-scope, safe repair remains. Stop when the requested outcome is proven, an unresolved fact prevents an honest claim, or further action needs new authority.

1. **UNDERSTAND:** inspect the project, request, constraints, existing changes, and proof target. Record facts that could invalidate the result as `unknowns`.
2. **ROUTE:** run `python scripts/classify_task.py "<task>"` and use its schema-v1.1 `task_domains`. Read [routing architecture](references/routing/architecture.md) and [capability registry](references/routing/capability-registry.md), then load only references needed by the selected domains. Apply [source policy](references/routing/source-policy.md) before adopting external material. Run `python scripts/select_skills.py "<task>"` and follow the [specialist skill selection contract](references/routing/skill-selection.md) plus the machine-readable [`skill_registry.yaml`](skill_registry.yaml): treat recommendations as candidates, load only selected specialists that are actually installed and in scope, never auto-install, use registered first-party fallbacks when appropriate, and keep the smallest useful specialist set. When a bounded model worker could reduce cost or parallelize analysis, read [worker provider router](references/routing/provider-router.md). When independent model proposals create leverage, choose between the [parallel worker swarm](references/routing/worker-swarm.md) for an explicitly known role set and the [adaptive worker swarm](references/routing/adaptive-swarm.md) when task domains should compose the smallest useful team automatically.
3. **MAKE:** implement the smallest coherent change through the selected specialists and tools. Keep the orchestrator responsible for routing and acceptance, specialists responsible for domain guidance, engine/asset tools responsible for deterministic operations, optional worker providers responsible only for bounded proposals, and the proof system responsible for claims.
4. **INTEGRATE:** connect code, scenes, resources, imports, UI, and gameplay in the user's project without taking ownership away from existing project structure. Worker majority vote is never an integration rule; choose from proposals using project facts and requested acceptance criteria.
5. **RUN, INSPECT, VERIFY, FIX:** escalate evidence from the cheapest relevant proof level. Inspect actual output, repair observed defects, and rerun affected checks.
6. **PROVE:** report a schema-v1.1 result using `scripts/common/result.py`, artifact evidence, the achieved P0-P5 level, remaining unknowns, and an AI Creole handoff when work continues across agents. In every bounded task receipt, include `skills_used` with canonical registry ids for specialist skills actually opened or invoked; use an empty list when none were used. Recommendations, internal references, worker roles, providers, and ordinary tools do not count as `skills_used`.

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

## Worker delegation

Worker models are optional execution lanes, not new authorities. Use them only for bounded, independently checkable work such as repository reconnaissance, narrow code proposals, test generation, or read-only review. A worker response is always an untrusted proposal until the orchestrator inspects it and the normal proof path validates the resulting project state.

Use `scripts/provider_router.py` for one configured OpenAI-compatible worker. Keep provider and model separate: OpenRouter is the primary external worker hub, an explicitly enabled logged free endpoint may be used only for `public` payloads, and `secret` payloads require a configured local provider. Never silently weaken data handling, silently change a requested model, or send credentials and secret-bearing output to an external worker.

Use `scripts/worker_swarm.py` when the role set is already known. Its default fixed swarm runs `architect`, `implementer`, and `test_writer` concurrently, then runs a `reviewer` over the primary proposals.

Use `scripts/adaptive_swarm.py` when the task domains should determine the team. The adaptive planner is deterministic first-party code, not an LLM planner. It may compose `architect`, `recon`, `gameplay_specialist`, `ui_specialist`, `asset_specialist`, `implementer`, `test_writer`, and `release_auditor`, then optionally fan in through `reviewer`. Role-specific or tier-specific provider/model profiles may refine execution, but every assignment still passes through the provider sensitivity policy.

For multi-worker execution:

- keep primary workers read-only proposal generators;
- give every worker the same bounded task and only the repository context needed for that task;
- never let model output recursively create new roles or workers;
- never feed one primary worker another primary worker's answer before the fan-in review stage;
- do not use worker majority vote as acceptance;
- let the orchestrator choose, apply, and merge the smallest coherent change;
- run normal P0-P5 proof after integration.

Both fixed and adaptive swarm runtimes preserve deterministic role ordering, isolate individual worker failures, redact credentials, and always report `proof_status: UNPROVEN` plus `integration_required: true`.

A trivial or deterministic task does not justify a swarm. Prefer the cheapest route that can produce independently checkable value.

## Non-negotiable contracts

Before changing a project, read [project safety](references/safety/project-safety.md). Before claiming completion, read the [completion contract](references/proof/completion-contract.md) and [proof ladder](references/proof/proof-ladder.md).

For multi-agent or resumable work, exchange [AI Creole handoffs](references/protocol/ai-creole-handoff.md). Admit durable observations only under the [FIELD NOTES policy](references/protocol/field-notes-policy.md).

Never embed specialist procedure in the final report. State what changed, checks run, proof level reached, artifacts, `skills_used`, warnings or unknowns, and the next bounded action if incomplete.

---
name: mado-loop
description: Orchestrate production work and evidence for Godot 4.x games when the user explicitly invokes $mado-loop.
---

# MADO LOOP

Use this skill only when the user explicitly invokes `$mado-loop`. Turn a game-development request into implemented, integrated, and honestly proven Godot work.

## Operating loop

Run **UNDERSTAND -> ROUTE -> MAKE -> INTEGRATE -> RUN -> INSPECT -> VERIFY -> FIX -> PROVE**. Repeat the run-through-fix segment while an in-scope, safe repair remains. Stop when the requested outcome is proven, an unresolved fact prevents an honest claim, or further action needs new authority.

1. **UNDERSTAND:** inspect the project, request, constraints, existing changes, and proof target. Record facts that could invalidate the result as `unknowns`.
2. **ROUTE:** run `python scripts/classify_task.py "<task>"` and use its schema-v1.1 `task_domains`. Read [routing architecture](references/routing/architecture.md) and [capability registry](references/routing/capability-registry.md), then load only references needed by the selected domains. Apply [source policy](references/routing/source-policy.md) before adopting external material. Run `python scripts/select_skills.py "<task>"` and follow the [specialist skill selection contract](references/routing/skill-selection.md) plus the machine-readable [`skill_registry.yaml`](skill_registry.yaml): treat recommendations as candidates, load only selected specialists that are actually installed and in scope, never auto-install, use registered first-party fallbacks when appropriate, and keep the smallest useful specialist set. When a bounded model worker could reduce cost or parallelize analysis, read [worker provider router](references/routing/provider-router.md). When MADO LOOP is already running in Codex with ChatGPT-plan authentication and included subscription usage should be paced against the next reset, read [Codex Plus native lane](references/routing/codex-plus-lane.md). When free/hosted/local lanes should be tried before scarce Plus worker usage, read [Budget Governor 2.0](references/routing/budget-governor-v2.md). When independent model proposals create leverage, choose between the [parallel worker swarm](references/routing/worker-swarm.md) for an explicitly known role set and the [adaptive worker swarm](references/routing/adaptive-swarm.md) when task domains should compose the smallest useful team automatically. When isolated project mutation by delegated workers would create concrete leverage, read the [Orchestration & Verification Protocol](references/protocol/orchestration-verification.md) before dispatch and use `scripts/ovp_runtime.py` to preserve its preflight, isolation, receipt, review, integration, and proof-binding boundaries.
3. **MAKE:** implement the smallest coherent change through the selected specialists and tools. Keep the orchestrator responsible for routing and acceptance, specialists responsible for domain guidance, engine/asset tools responsible for deterministic operations, optional proposal workers responsible only for bounded proposals, OVP mutation workers responsible only for their assigned isolated workspace through `REVIEW_READY`, and the proof system responsible for claims.
4. **INTEGRATE:** connect code, scenes, resources, imports, UI, and gameplay in the user's project without taking ownership away from existing project structure. Worker majority vote is never an integration rule; choose from proposals or mutation receipts using project facts and requested acceptance criteria. Mutation workers never merge or accept their own work. For OVP tasks, accept only after `ovp_runtime.py review --inspected-diff`, integrate from the leader checkout, then bind the normal schema-v1.1 proof result with `ovp_runtime.py proof`.
5. **RUN, INSPECT, VERIFY, FIX:** escalate evidence from the cheapest relevant proof level. Inspect actual output, repair observed defects, and rerun affected checks.
6. **PROVE:** report a schema-v1.1 result using `scripts/common/result.py`, artifact evidence, the achieved P0-P5 level, remaining unknowns, and an AI Creole handoff when work continues across agents. In every final bounded MADO LOOP task receipt, include `skills_used` with canonical registry ids for specialist skills actually opened or invoked across the orchestrator and accepted worker evidence; use an empty list when none were used. OVP mutation receipts are lower-level evidence bundles and do not replace this final provenance field. Recommendations, internal references, worker roles, providers, and ordinary tools do not count as `skills_used`.

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

Worker models are optional execution lanes, not new authorities. Use them only for bounded, independently checkable work such as repository reconnaissance, narrow code proposals, test generation, read-only review, or OVP-governed isolated mutation. A proposal-worker response is always an untrusted proposal until the orchestrator inspects it and the normal proof path validates the resulting project state. A mutation worker may change only its isolated assigned workspace and must stop at `REVIEW_READY`; it never receives acceptance, merge, or final proof authority.

Use [Orchestration & Verification Protocol](references/protocol/orchestration-verification.md) whenever a delegated worker will mutate project state. Use `scripts/ovp_runtime.py preflight` or `prepare` before fan-out, isolate every mutation task in the runtime-owned Git worktree, dispatch the generated AI Creole Agent Contract, require the worker to commit and submit an exact-ID evidence receipt, and review before integration. The runtime stores manifests under the Git common directory rather than the tracked checkout, rejects out-of-scope changes, rechecks branch/HEAD identity at review, aborts failed integration, and binds P0-P5 proof to the exact integrated HEAD. Existing read-only swarm runtimes do not become mutation workers merely because they can propose code.

Use `scripts/budget_governor_v2.py` when the task can benefit from mixed-lane routing and preserving ChatGPT Plus allowance matters. It composes the smallest useful automatic worker set, uses reset-aware Plus pressure, prefers OpenRouter `tencent/hy3-preview:free` for routine recon/test work, uses the curated NVIDIA fleet for role-specific external work when permitted, moves free/local lanes ahead of Luna as Plus pressure rises, and executes deterministic fallbacks without weakening sensitivity policy. WorkBuddy Hy4 promotional access is advisory/manual only and never becomes an automatic or paid API route. Read [Budget Governor 2.0](references/routing/budget-governor-v2.md) before relying on this path.

Use `scripts/codex_plus_lane.py` when MADO LOOP is already running under Codex with **Sign in with ChatGPT** and a bounded worker should use the included ChatGPT-plan Codex allowance instead of an API key. Keep Sol Medium in the current parent session for orchestration, architecture, integration, review, and acceptance. Use `scripts/codex_plus_budget.py sync` to append coarse `/status` observations and pace against the **next observed reset**, not an assumed seven-day window. Use `scripts/codex_plus_swarm.py` to compose the smallest useful Luna team from the existing adaptive role classifier: normal/headroom operation spawns at most two workers, conservation or critical mode at most one. Luna xhigh remains the default for bounded implementation and specialist work, Luna high for recon/test work, but xhigh roles may automatically promote to Luna max when observed account burn projects substantial unused headroom at reset. Do not hard-code a temporary Max discount; infer its practical effect from the observed remaining-percentage burn. If burn accelerates, remove Max automatically and downshift. The Codex `/status` output or ChatGPT usage dashboard remains authoritative for actual plan allowance. Read [Codex Plus native lane](references/routing/codex-plus-lane.md) before relying on this path.

Use `scripts/provider_router.py` for one configured OpenAI-compatible API/local worker. Keep provider and model separate: OpenRouter is the primary external worker hub, NVIDIA NIM is a hosted external lane, an explicitly enabled logged free endpoint may be used only for `public` payloads, and `secret` payloads require a configured local provider. Never silently weaken data handling, silently change a requested model, or send credentials and secret-bearing output to an external worker.

Use `scripts/worker_swarm.py` when the role set is already known. Its default fixed swarm runs `architect`, `implementer`, and `test_writer` concurrently, then runs a `reviewer` over the primary proposals.

Use `scripts/adaptive_swarm.py` when the task domains should determine the team. The adaptive planner is deterministic first-party code, not an LLM planner. It may compose `architect`, `recon`, `gameplay_specialist`, `ui_specialist`, `asset_specialist`, `implementer`, `test_writer`, and `release_auditor`, then optionally fan in through `reviewer`. Role-specific or tier-specific provider/model profiles may refine execution, but every API/local assignment still passes through the provider sensitivity policy.

Use `scripts/nvidia_fleet_benchmark.py` when the curated NVIDIA fleet itself needs an empirical role-fit check. The benchmark runs Kimi K3 (`architect`), DeepSeek V4 Pro (`implementer`), and Nemotron 3.5 Lightning (`test_writer`) concurrently, then fans their proposals into Nemotron 3 Ultra (`reviewer`). It records per-call request profiles, latency, provider token usage when available, JSON output-contract compliance, and reviewer-assigned role-quality scores. Treat reviewer scores as model-graded tuning signals only: they are not independent ground truth, do not grant mutation authority, and never substitute for P0-P5 proof. Benchmark public or synthetic tasks by default; do not use secret payloads with hosted NVIDIA endpoints.

For multi-worker execution:

- keep primary proposal workers read-only unless the route explicitly opts into OVP;
- for OVP mutation work, run first-party preflight first and give every mutation worker a separate runtime-owned worktree;
- give every worker the same bounded task semantics and only the repository context needed for that task;
- express OVP mutation assignments with AI Creole core fields `TASK / GOAL / STATE / TARGET / DO / KEEP / NO / OUT / CHECK / RISK / NEXT`;
- require mutation workers to commit their bounded change and end at `REVIEW_READY`, never `DONE`;
- require mutation receipt check IDs to match the dispatch acceptance IDs exactly;
- never let model output recursively create new roles or workers;
- never feed one primary proposal worker another primary worker's answer before the fan-in review stage;
- do not use worker majority vote as acceptance;
- let the orchestrator choose, review, apply, and merge the smallest coherent change;
- use narrow typed visual-broker actions rather than unrestricted desktop automation when delegated visual inspection is required;
- run normal P0-P5 proof after integration and bind its schema-v1.1 result to the integrated HEAD;
- aggregate specialist provenance into the final bounded MADO LOOP task receipt's `skills_used` field.

Fixed/adaptive API swarms, the Codex-native subscription swarm, and Budget Governor 2.0 preserve deterministic role ordering, isolate individual worker failures, avoid credential persistence, and report `proof_status: UNPROVEN` plus `integration_required: true`. They remain proposal systems unless explicitly upgraded with the OVP isolation and mutation contract.

A trivial or deterministic task does not justify a swarm. Prefer the cheapest route that can produce independently checkable value.

## Non-negotiable contracts

Before changing a project, read [project safety](references/safety/project-safety.md). Before claiming completion, read the [completion contract](references/proof/completion-contract.md) and [proof ladder](references/proof/proof-ladder.md).

For multi-agent or resumable work, exchange [AI Creole handoffs](references/protocol/ai-creole-handoff.md). For delegated project mutation, also apply the [Orchestration & Verification Protocol](references/protocol/orchestration-verification.md) through `scripts/ovp_runtime.py`. Admit durable observations only under the [FIELD NOTES policy](references/protocol/field-notes-policy.md).

Never embed specialist procedure in the final report. State what changed, checks run, proof level reached, artifacts, `skills_used`, warnings or unknowns, and the next bounded action if incomplete.

# Capability registry

Use this registry after domain classification. It describes capability roles and availability behavior; provenance and update rules are in [source-policy.md](source-policy.md). Model-worker data handling and selection rules are in [provider-router.md](provider-router.md), fixed parallel model orchestration rules are in [worker-swarm.md](worker-swarm.md), and adaptive composition rules are in [adaptive-swarm.md](adaptive-swarm.md).

| Capability | Domains | Mode | Required when | Absence behavior |
| --- | --- | --- | --- | --- |
| MADO LOOP orchestrator | All | First-party | Every invocation | Internal error if unavailable |
| Godot skill snapshot and first-party adapter | `CODE`, `GAMEPLAY`, `UI`, `ANIMATION`, `ASSET_INTEGRATION`, `PLAYTEST`, `RELEASE` | Vendored tool | A route requires deterministic Godot inspection or execution | Required `SKIPPED`; result `UNKNOWN` unless already `FAIL` |
| Sprite production guidance | `SPRITE`, `ANIMATION`, `PIXEL_ART` | Distilled reference | Sprite work is requested | Required `SKIPPED` if the applicable guidance is absent |
| Agent Sprite Forge processor and first-party adapter | `SPRITE`, `ANIMATION`, `PIXEL_ART`, `ASSET_INTEGRATION` | Narrow vendored tool | Deterministic normalization, slicing, preview, or atlas work is requested | Required `SKIPPED`; result `UNKNOWN` unless already `FAIL` |
| Game UI guidance | `UI`, `REFERENCE_TO_UI` | Distilled reference | Game UI design or review is requested | Required `SKIPPED`; result `UNKNOWN` unless already `FAIL` |
| Game playtest guidance | `GAMEPLAY`, `PLAYTEST`, `RELEASE` | Distilled reference | Interactive runtime evidence is required | Required `SKIPPED`; result `UNKNOWN` unless already `FAIL` |
| Product Design image-to-code concepts | `REFERENCE_TO_UI`, `UI` | Distilled, no-copy reference | A visual reference must become implementable game UI | Required only for that transformation route; otherwise not selected |
| Generic pixel-art rules | `PIXEL_ART`, `SPRITE`, `IMAGE` | First-party reference | Pixel-safe output is requested | Required `SKIPPED` when pixel correctness is part of acceptance |
| ImageGen | `IMAGE`, optionally `SPRITE` or `UI` | Optional routed capability | Only when the user requests or accepts generated imagery | Optional `SKIPPED` plus warning; continue if another valid route exists |
| External image editor | `IMAGE`, `SPRITE`, `PIXEL_ART` | Optional routed capability | Only when explicitly selected and authorized | Optional `SKIPPED` plus warning |
| OpenRouter worker | Any bounded reasoning/coding subtask | Optional external worker | Only when configured and selected by the orchestrator | Optional `SKIPPED`; never invent credentials or silently change model/data policy |
| Empero logged free worker | Public bounded reasoning/coding subtask | Optional external worker | Only with public payload plus explicit logged-free consent | Optional `SKIPPED`; forbidden for private/secret payloads |
| Local OpenAI-compatible worker | Any bounded reasoning/coding subtask | Optional local worker | Required only when a delegated `secret` payload must use a model | Optional `SKIPPED` unless secret delegation was explicitly required |
| Parallel worker swarm | Any bounded subtask where an explicit role set should run concurrently | First-party orchestration over configured workers | Only when selected by the orchestrator or explicitly required by the user | Optional `SKIPPED`; fall back to one worker or local orchestration without weakening sensitivity or acceptance |
| Adaptive worker swarm | Any bounded subtask where classified domains should compose the smallest useful worker team | First-party deterministic composition over configured workers | Only when adaptive composition creates concrete leverage | Optional `SKIPPED`; use fixed swarm, one worker, or local orchestration without weakening sensitivity or acceptance |
| Installed specialist skill | Matching declared domains | Optional routed capability | Only when explicitly available and selected by the route | Optional `SKIPPED` unless the user made it a required dependency |
| Agent Skills Hub registry | Matching declared domains | Discovery route only | Only when the user requests registry discovery | Optional `SKIPPED`; never auto-install |

## Selection contract

For each selected capability, record:

- active domain or domains;
- whether it is required or optional for the requested claim;
- availability before execution;
- adapter, reference, worker, fixed-swarm, or adaptive-swarm role;
- checks needed to validate its output;
- for an external worker, sensitivity and provider data policy;
- for a fixed swarm, requested primary roles, reviewer use, parallelism bound, and worker failures;
- for an adaptive swarm, classified domains, complexity score, selected roles, role tiers, resolved credential-redacted provider/model routes, reviewer decision, parallelism bound, and worker failures.

An installed specialist or worker model cannot replace the MADO LOOP result contract or release proof. A worker response is an untrusted proposal until integrated and verified. Swarm transport `PASS` only means the scheduled proposal calls completed; every fixed or adaptive swarm result remains `UNPROVEN`. Adaptive planning must remain deterministic first-party code: model output cannot create roles, recursively spawn workers, relax sensitivity, or alter acceptance authority. A vendor payload cannot be edited to fit a route; adapt it at the first-party boundary. An optional route becoming unavailable must not silently change the requested artifact or acceptance standard.

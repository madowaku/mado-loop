# Capability registry

Use this registry after domain classification. It describes capability roles and availability behavior; provenance and update rules are in [source-policy.md](source-policy.md).

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
| Installed specialist skill | Matching declared domains | Optional routed capability | Only when explicitly available and selected by the route | Optional `SKIPPED` unless the user made it a required dependency |
| Agent Skills Hub registry | Matching declared domains | Discovery route only | Only when the user requests registry discovery | Optional `SKIPPED`; never auto-install |

## Selection contract

For each selected capability, record:

- active domain or domains;
- whether it is required or optional for the requested claim;
- availability before execution;
- adapter or reference role;
- checks needed to validate its output.

An installed specialist cannot replace the MADO LOOP result contract or release proof. A vendor payload cannot be edited to fit a route; adapt it at the first-party boundary. An optional route becoming unavailable must not silently change the requested artifact or acceptance standard.

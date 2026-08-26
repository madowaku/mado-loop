# Reference Image to Godot Game UI

Use this workflow for `REFERENCE_TO_UI` plus `UI`; add `ASSET_INTEGRATION` when the implementation imports or changes project assets. A reference is visual evidence and intent, not an executable specification. Reconstruct its hierarchy and behavior with Godot semantics rather than copying web/DOM, CSS, SaaS, or proprietary implementation rules.

## Intake, rights, and comparison contract

Record every reference image, source and permitted use, target Godot project/scene, required viewport and resolution, expected game state, supported devices, languages, and which aspects are authoritative. Unknown ownership or reuse permission that can invalidate delivery belongs in `unknowns`; do not infer a license from public visibility.

Define the comparison contract before implementation: exact state, resolution, stretch mode, safe area, fonts, dynamic values, animation time, cursor/focus state, and capture method. Separate must-match features from inspiration-only features and intentional adaptations. Keep the original reference and a recoverable project diff; record assets, scenes, themes, and imports to restore.

## Decompose before building

Turn visible pixels into an explicit model:

- hierarchy: screen layers, regions, panels, repeated groups, overlays, and modal order;
- assets: backgrounds, frames, icons, portraits, fonts, masks, nine-patches, and effects;
- layout: alignment, padding, gaps, minimum sizes, anchors, aspect behavior, and safe-area relations;
- theme: palette, typography, borders, radii/corners, shadows, emphasis, and state variants;
- states: default, hover, focus, pressed, selected, disabled, loading, error, empty, paused, and open/closed;
- behavior: navigation order, activation, cancel/back, scrolling, modal capture, transitions, and data changes.

Mark occluded, cropped, ambiguous, or absent behavior as an assumption or unknown. Do not invent a hidden interaction and then claim reference parity.

## Map appearance to Godot semantics

Choose semantic `Control` nodes by behavior: labels for text, buttons for actions, range controls for values, scroll containers for overflow, containers for responsive grouping, and explicit modal/focus owners for overlays. Express responsive relationships with anchors, size flags, minimum sizes, and `Container` composition. Use `Theme`, style boxes, fonts, icons, nine-patches, and reusable scenes for coherent presentation. Use `CanvasLayer` deliberately for screen-space ownership.

Do not rasterize the entire interface into a single texture when text, focus, localization, accessibility, state changes, or interaction are required. Do not mimic pixels with arbitrary nodes when an equivalent semantic control exists. Route extracted or recreated art through the [asset-integration workflow](asset-integration.md) and retain provenance; never claim editable layers or source fidelity that the reference does not prove.

## Same-state comparison and tolerances

Capture the implementation and reference at the same named state and resolution. Normalize only declared environmental differences; never resize or crop away a mismatch without reporting it. Compare global composition first, then region bounds, alignment, spacing, typography, colors, assets, states, and effects. Overlay, blink, or use a deterministic image-difference tool where permitted, while retaining both source captures and parameters.

Set tolerances by feature and purpose. Geometry, clipping, state visibility, and interaction targets usually require exact or near-exact agreement. Font rasterization, antialiasing, platform shader output, and compression may need a documented pixel/color tolerance. A tolerance must not conceal wrong hierarchy, missing content, incorrect assets, or a different interaction state. Report measurements and representative diff regions, not only a subjective similarity score.

## Interaction and nonvisual proof

Visual similarity does not prove usability. Exercise keyboard/controller focus, pointer and touch paths where required, modal blocking, pause ownership, scroll limits, text expansion, screen-reader/accessibility provisions defined by the project, and device switching. Verify states absent from the reference using the project's design language, and label them as derived decisions rather than reference matches. Capture runtime errors and missing-resource logs alongside visual evidence.

## Repair loop and acceptance

1. Establish a baseline capture and classify mismatches as hierarchy, layout, theme, asset, state, interaction, or environmental.
2. Repair the smallest owning cause; avoid compensating offsets that merely hide a structural error.
3. Re-capture the identical state and resolution with the same comparison parameters.
4. Re-run interaction and nonvisual checks affected by the change, plus one neighboring state or viewport.
5. Repeat until every required feature is within its declared tolerance and no compensating regression remains.

Accept when rights and authoritative scope are known, the Godot hierarchy and resources are maintainable, required same-state comparisons meet declared tolerances, responsive and localized variants remain usable, interaction/nonvisual states pass, assets have provenance, runtime evidence is retained, and rollback is mechanically clear.

A measurable mismatch outside tolerance, broken interaction, invalid resource, runtime error, or rights violation is `FAIL`. Unresolved rights, unavailable authoritative state, missing target settings, or absent required runtime/comparison evidence goes in `unknowns` and produces `UNKNOWN` unless already `FAIL`. A required unavailable capture or execution route is required `SKIPPED` and therefore `UNKNOWN`; an unavailable optional diff helper is optional `SKIPPED` plus warning and does not by itself enter `unknowns`. Top-level `SKIPPED` is reserved for an entire operation that is legitimately not requested or not applicable. Emit schema v1.1 with canonical `task_domains` (`UI`, `ASSET_INTEGRATION`, `REFERENCE_TO_UI`, and derived `MIXED` as applicable), evidence artifacts, tolerances, assumptions, and rollback notes.

# Godot Game UI Production

Use this workflow for `UI`, and add `ASSET_INTEGRATION` when project resources or imported art change. It is guidance for Godot runtime interfaces, not a web/DOM layout recipe. Preserve the requested player experience and the project's established scene, theme, and input conventions.

## Preflight and rollback

Record target scenes, viewports and aspect ratios, supported input devices, languages, safe-area requirements, pause behavior, UI state transitions, and acceptance captures. Inspect the current scene/resource owners before editing. Establish a recoverable diff, preserve source art and existing `.tres` resources, and name the scenes, resources, input actions, and imports to restore if validation fails.

## Structure and ownership

- Put screen-space HUD and menus under an intentional `CanvasLayer`; define whether each layer follows world transforms, pause state, and visibility transitions.
- Build layout with `Control` minimum sizes, size flags, anchors, offsets, and `Container` nodes. Let containers own child placement; do not fight them with hand-authored child positions.
- Separate stable screen composition, reusable widgets, presentation resources, and state logic. Prefer reusable scenes for compound controls and shared `Theme`/`ThemeVariation` resources over per-node overrides.
- Keep UI state explicit: hidden, disabled, focused, selected, pressed, loading, error, paused, and modal states must not be inferred only from color or animation.
- Define who owns gameplay-to-UI data and signals. UI presentation may observe a model or state adapter, but should not become an accidental second gameplay authority.

Godot's primary references are [Control](https://docs.godotengine.org/en/stable/classes/class_control.html), [Container](https://docs.godotengine.org/en/stable/classes/class_container.html), [Theme](https://docs.godotengine.org/en/stable/classes/class_theme.html), and [CanvasLayer](https://docs.godotengine.org/en/stable/classes/class_canvaslayer.html).

## Layout, scale, and text

Test the minimum and maximum supported viewport, intermediate aspect ratios, stretch settings, and platform safe area. Anchors express the relationship to the parent; offsets express the remaining margin. Use containers and minimum sizes for content-driven growth. Do not use viewport-specific magic coordinates as the primary layout system.

Budget for localization before polish. Exercise long translations, narrow glyphs, wide glyphs, multiline labels, dynamic values, plural forms, and the configured font fallbacks. Text may wrap, truncate, scroll, or expand only according to an explicit policy. No required meaning may disappear behind ellipsis. Check font size, contrast, line spacing, overlay backgrounds, and information hierarchy at the real play distance, not only in an enlarged editor view.

## Input, focus, and modal behavior

Provide a complete path for every supported device: keyboard, controller, pointer, and touch where requested. Define initial focus, directional neighbors or a verified automatic path, focus restoration after closing a screen, activation, cancellation/back behavior, held/repeated input, and device switching. Visible focus must remain distinguishable from hover and selection.

A modal stack has one active top owner. Opening a modal captures relevant UI input, blocks or deliberately passes gameplay input, moves focus inside, and records where focus must return. Closing it restores focus and prior pause/input state. Prevent click-through, double activation, and lower-layer shortcuts. Touch targets must be large and separated enough for the target device, with feedback that does not rely on hover.

For pause screens, specify whether the tree pauses, which UI nodes process while paused, and who resumes the game. HUD elements must not consume gameplay input unless that is their declared role. Menus must not leave the player in a mixed paused/unpaused or captured/free mouse state.

## Assets, performance, and polish

Route imported fonts, textures, icons, nine-patches, and atlases through the [asset-integration workflow](asset-integration.md). Verify filtering, margins, scaling, alpha, and theme variation at target resolution. Avoid per-frame node creation, repeated resource loads, layout thrashing, and rebuilding whole trees for small value changes. Profile frequently updated HUDs in representative gameplay. Cache stable references and update presentation only when state changes, while keeping correctness ahead of speculative optimization.

Common anti-patterns include absolute-positioning every control, mixing container ownership with manual offsets, per-node theme drift, color-only state, mouse-only interaction, invisible focus, modal click-through, hard-coded English widths, HUD logic that mutates gameplay truth, and screenshots taken from editor-only or nonrepresentative states.

## Runtime proof and repair loop

1. Run the real project in each required viewport, language, input mode, pause state, and UI state.
2. Capture the same named states consistently and record environment, resolution, scale/stretch configuration, and input path.
3. Exercise focus traversal, back/cancel, modal nesting, rapid open/close, device switching, text expansion, safe-area edges, and gameplay underneath overlays.
4. Inspect runtime errors, warnings, missing resources, input leakage, clipping, overlap, illegible text, frame-time spikes, and regressions in unrelated screens.
5. Repair the smallest owning layer—layout, theme, asset, state adapter, or scene—and rerun the affected matrix plus a neighboring regression case.

Accept only when required screens render and behave correctly across the declared matrix, focus and input paths complete, modal/pause ownership is deterministic, localized content remains usable, assets resolve, readability meets the project target, representative runtime performance is acceptable, and rollback is mechanically clear.

Measured layout, interaction, resource, accessibility/readability, runtime error, or performance-budget violations are `FAIL`. Missing project context or required runtime evidence that could invalidate acceptance is listed in `unknowns` and produces `UNKNOWN` unless already `FAIL`. A required unavailable execution/input route is a required `SKIPPED` check and therefore `UNKNOWN`; an unavailable optional helper is optional `SKIPPED` plus warning. Top-level `SKIPPED` applies only when the whole UI operation is legitimately not requested or not applicable. Emit schema v1.1 results with canonical `task_domains`, checks, captures/logs as artifacts, and rollback notes.

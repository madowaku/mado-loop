# Godot Asset Integration Contract

Use for `ASSET_INTEGRATION` with `IMAGE`, `SPRITE`, `ANIMATION`, or `UI`. Integration is complete only when the imported resource is wired into a runnable scene and supported by proof. Do not claim editor or runtime behavior that was not executed or inspected.

## Preflight and rollback

Record source asset, generated files, import target, expected node/resource owner, and current project state. Preserve the original asset and project-owned import/settings files. Before changing scenes or resources, establish a recoverable diff or backup and name the rollback steps.

## Import contract

Verify the actual Godot import state, not only source dimensions:

- texture filtering matches the art profile; pixel art normally uses nearest filtering;
- mipmaps are disabled unless camera scale and project evidence justify them;
- alpha, color space, compression, and repeat mode match the asset function;
- scale and pixels-per-unit assumptions are consistent across related assets;
- region rectangles, atlas cells, margins, spacing, and bounds match metadata.

For sprite sheets, create or update `AtlasTexture`/`SpriteFrames` mappings deterministically. Name animations, set per-frame durations, playback speed, loop mode, and anchors from the production metadata. Use `AnimationPlayer` for authored property timelines and `AnimationTree` only when the project actually needs a state/blend graph. Do not add either merely to satisfy a checklist.

## Scene wiring

Wire resources to the owning scene with stable project-relative paths. Confirm node type, draw order, visibility, transform, region/frame selection, and ownership. Connect signals only to named receivers with documented payload and lifecycle. Prefer reusable `.tres` resources for shared data and avoid duplicating mutable resources unintentionally.

For layered characters, keep body animation and FX independently controllable. Confirm that action transitions, one-shot completion, looping, interruption, and reset behavior agree with gameplay. Check missing-resource behavior and scene reload.

## Proof ladder

Collect only evidence actually available:

1. static inspection of source, metadata, `.import`, resource, and scene references;
2. headless import/load or parser proof when supported;
3. runnable scene proof of scale, animation, signals, and resource loading;
4. visual captures at representative camera scale;
5. regression/release evidence required by the active P0–P5 plan.

The highest completed step limits the claim. Static files alone cannot prove runtime animation or signals.

## Acceptance and failure handling

Accept when imports are deterministic, resources resolve, regions and frames are correct, runtime wiring behaves as specified, visuals pass target-scale inspection, no unrelated project behavior regresses, and rollback was tested or is mechanically clear.

Broken paths, wrong imports, clipped regions, invalid scene/resource syntax, runtime errors, incorrect signal behavior, or visible scale/filter defects are `FAIL`. If required Godot execution, import output, or project context is unavailable, make the applicable required check `SKIPPED` and the result `UNKNOWN` unless already `FAIL`; list the evidence gap in `unknowns`. An unavailable optional visual tool is optional `SKIPPED` plus warning. Report modified resources, captures, logs, and rollback notes as artifacts.

For upstream planning and result semantics, see [routing architecture](../routing/architecture.md) and the [capability registry](../routing/capability-registry.md).

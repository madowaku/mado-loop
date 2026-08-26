# Art Direction Contract

Use this contract for `IMAGE`, `SPRITE`, `UI`, or `MIXED` work that creates or changes visual assets. It turns an art request into inspectable constraints; it does not imply that an image generator or editor is installed.

## Brief before making

Record the following in the work note or result artifacts:

- intended gameplay function and camera/view distance;
- subject identity, silhouette, proportions, materials, and recurring motifs;
- palette intent, value hierarchy, lighting direction, and background relationship;
- target dimensions, alpha policy, scale in Godot, and delivery format;
- references described as traits to interpret, never as content to copy;
- invariants shared by every action, pose, and UI appearance.

For a character with multiple actions, establish one approved neutral/reference frame first. Generate or draw each action from the same identity sheet and constraints. Keep body motion and transient FX on separate layers or assets so hit flashes, trails, particles, and weapon arcs can be timed or replaced without changing the body silhouette.

## Capability route

ImageGen is optional. Route to it only when the user requested or accepted generated imagery. If it is unavailable, report an optional `SKIPPED` check and a warning, then continue with an authorized manual asset, placeholder, or explicitly selected external editor. Never install, launch, or authorize an external editor automatically.

Do not claim an editable source, layer separation, animation, or engine-ready import unless the produced artifact proves it. A placeholder must be labeled as such and cannot satisfy final-art acceptance.

## Review gate

Accept when:

1. the asset's gameplay function reads at target display scale;
2. identity invariants survive every action and facing;
3. silhouette, palette, light, and perspective are coherent with the brief;
4. body and FX can be controlled independently where the design requires it;
5. dimensions, alpha, naming, and source provenance are recorded;
6. the selected asset has an integration route and rollback source.

Treat a visible mismatch, corrupt alpha, wrong dimensions, or broken invariant as `FAIL`. Put unresolved facts that could invalidate acceptance—such as unknown rights, missing target scale, or an unverified source file—in `unknowns`, producing `UNKNOWN` unless a failure already exists. A missing optional generator/editor alone is a warning, not an unknown.

Continue with [sprite production](sprite-production.md), [pixel-art profile](pixel-art-profile.md), or [asset integration](asset-integration.md) according to the classified domains.

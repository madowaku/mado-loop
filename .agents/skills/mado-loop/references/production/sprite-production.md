# Sprite Production Contract

Use for `SPRITE` and related `ANIMATION`, `PIXEL_ART`, or `ASSET_INTEGRATION` work. Preserve a reversible source and treat every exported frame as data with explicit timing, anchor, scale, bounds, and alpha expectations.

## Build sequence

1. Define action names, directions, frame counts, playback mode, frames per second or per-frame durations, and interruption rules.
2. Approve `frame01` as the identity/reference frame. Record canvas size, ground point, facing, silhouette, proportions, palette, light direction, and equipment placement.
3. Produce coherent actions from the same reference. Keep body frames separate from FX frames or overlays.
4. After each action, compare its first and last frame back to `frame01`. Correct identity drift before packing more actions.
5. Normalize frames without interpolation: fixed canvas, nearest-neighbor resize when needed, stable anchor, consistent crop policy, and transparent padding.
6. Pack deterministically. Record action/frame ordering, cell size, margins, spacing, atlas bounds, and filename-to-frame mapping.
7. Export a preview that demonstrates cadence and loop seams; keep the atlas and metadata as separate proof artifacts.

## Frame rules

- Anchors represent the same gameplay point—normally feet or locomotion origin—not the visible bounding-box center.
- Bounds must contain every nontransparent body pixel; FX may use separate, larger bounds.
- Scale changes must be integral for pixel art and documented for all sprites.
- Alpha outside intended pixels is zero; reject halos, matte colors, partial-alpha noise, and clipped pixels unless deliberately specified.
- Looping actions must have an intentional seam. One-shots must not silently loop.
- Timing is gameplay data. Do not infer uniform timing when anticipation, contact, recovery, or holds require distinct durations.

## Acceptance and reporting

Accept only when deterministic processing can reproduce the atlas and preview, frame order matches metadata, anchors do not jitter, target-scale inspection is legible, action timing is correct, and `frame01` lockback shows no unexplained identity drift. Report atlas, metadata, preview, and source paths as artifacts.

Use `FAIL` for measurable violations such as a mismatched cell, clipped frame, bad ordering, jitter, alpha contamination, or broken loop. Use `UNKNOWN` when required evidence cannot be established—for example undocumented frame timing or an unavailable source needed to verify bounds. If the optional generation route is unavailable, record optional `SKIPPED` plus a warning and use an approved manual/placeholder route; do not put capability absence alone in `unknowns`.

Apply [pixel-art profile](pixel-art-profile.md) when `PIXEL_ART` is present, then complete [asset integration](asset-integration.md).

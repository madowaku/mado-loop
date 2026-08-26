# Configurable Pixel-Art Profile

Use this profile when `PIXEL_ART` is classified. Values are project inputs, not house defaults. Record them beside the asset or in a project-owned profile.

## Required profile

```yaml
base_canvas: [width, height]
display_scale: integer
palette: named_or_embedded_palette
max_colors: project_value_or_unbounded
alpha: binary_or_declared_levels
outline_policy: project_rule
light_direction: project_rule
anchor: [x, y]
filter: nearest
mipmaps: false_unless_explicitly_justified
```

If resolution, palette, display scale, or alpha policy is not yet chosen, do not invent a universal value. Record the unresolved choice in `unknowns` when it can invalidate the asset; use a clearly labeled temporary profile only for exploratory work.

## Pixel-safe operations

- Draw and transform on the base pixel grid.
- Resize by integer multiples with nearest-neighbor sampling.
- Align pivots, regions, and frame cells to integer coordinates.
- Use the configured palette consistently; deliberate exceptions must be named.
- Avoid accidental antialiasing, subpixel placement, filtered rotation, color-profile drift, and semi-transparent edge halos.
- Inspect both 1:1 pixels and intended in-game scale against representative backgrounds.

Non-integral resizing or smooth filtering requires explicit art direction and becomes raster-art handling, not a passing pixel-art result.

## Acceptance

Accept when the file dimensions match the profile, colors and alpha obey policy, scaling is integer and nearest-neighbor, frame cells and anchors are pixel-aligned, no unintended smoothing or halo is visible, and the asset remains readable at gameplay scale. Preserve the configured profile and inspection images as proof.

Any measured profile violation is `FAIL`. Missing evidence that can change the verdict is `UNKNOWN` unless a failure already exists. A tool that cannot enforce a setting must not claim it; verify through exported pixels or Godot import state instead. Continue to [asset integration](asset-integration.md) for engine settings.

# Specialist skill selection

MADO LOOP remains the sole orchestrator. Specialist skills are temporary lenses selected for one bounded task; they do not become nested routers and they never replace MADO LOOP acceptance or proof.

The machine-readable registry is [`../../skill_registry.yaml`](../../skill_registry.yaml). It is intentionally JSON-compatible YAML so the first-party selector can parse it with the Python standard library and avoid adding a YAML runtime dependency.

## Selection order

1. Run `python scripts/classify_task.py "<task>"` to determine concrete task domains.
2. Run `python scripts/select_skills.py "<task>"` to get deterministic specialist recommendations.
3. Exclude `manual_only` skills unless the user or orchestrator explicitly selects that route. Current web-only specialists stay manual because MADO LOOP 1.x is Godot-focused.
4. Inspect the actual installed-skill inventory. Load only recommended skills that are available. Never install a skill automatically.
5. If a selected skill is unavailable, use its registered first-party fallback when one exists. Otherwise continue without it unless the user made that skill a required dependency.
6. Keep the smallest useful team. The registry caps automatic recommendations at four skills, ordered by priority then skill id.
7. Record only skills actually opened or invoked under `skills_used` in the task receipt. A recommendation alone does not count as use.

The Scout may propose specialist skills, but the MADO LOOP orchestrator owns the final route. Worker models cannot recursively add specialists. A Judge may independently use another installed specialist for review, but that skill must also be recorded in the receipt.

## Receipt contract

Every bounded task receipt should include `skills_used`, even when empty:

```yaml
receipt:
  result: done
  skills_used:
    - game-feel
    - godot-gdscript
  summary: "Improved hit feedback and verified the resulting Godot behavior."
```

Use canonical registry ids. Do not record internal references, worker roles, providers, or ordinary tools as skills. Those continue to use their existing evidence fields.

For unavailable recommendations, keep a separate note rather than pretending they ran:

```yaml
receipt:
  result: done
  skills_used: []
  skill_notes:
    unavailable:
      - puzzle
    fallback_used:
      - references/production/gameplay-proof.md
```

## Routing examples

| Task | Typical specialist route |
| --- | --- |
| HUD, focus, safe area, menu layout | `godot-ui-control` + `game-ui-ux` |
| GDScript bug or refactor | `godot-gdscript` |
| Scene/node/resource structure | `godot-nodes-scenes` |
| Hit stop, shake, impact, juice | `game-feel` |
| Puzzle solvability, undo, hint, difficulty | `puzzle` |
| Existing OSS/library exploration | `oss-librarian` |
| Online synchronization or matchmaking | `multiplayer-game` |
| Game-design balance/psychology review | `game-design-theory` |

`develop-web-game`, `threejs-game-ui-designer`, and `higgsfield-game-generation` are registered as `manual_only`. They are useful for future or adjacent web work, but automatic routing must not silently broaden a Godot MADO LOOP task into another runtime.

## Proof boundary

A specialist recommendation is not evidence. A specialist response is not evidence. Only the normal MADO LOOP RUN → INSPECT → VERIFY → PROVE path establishes completion. `skills_used` is provenance for how the work was approached, not a substitute for checks, artifacts, proof level, or remaining unknowns.

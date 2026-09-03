# Specialist skill selection

MADO LOOP remains the sole orchestrator. Specialist skills are temporary lenses selected for one bounded task; they do not become nested routers and they never replace MADO LOOP acceptance or proof.

The machine-readable registry is [`../../skill_registry.yaml`](../../skill_registry.yaml). It is intentionally JSON-compatible YAML so the first-party selector can parse it with the Python standard library and avoid adding a YAML runtime dependency.

## Selection order

1. Run `python scripts/classify_task.py "<task>"` to determine concrete task domains.
2. Run `python scripts/select_skills.py "<task>"` to get deterministic specialist recommendations. When `.mado-loop/skill_stats.json` exists, the selector reads only that compact cache, not the raw feedback ledger.
3. Exclude `manual_only` skills unless the user or orchestrator explicitly selects that route. Current web-only specialists stay manual because MADO LOOP 1.x is Godot-focused.
4. Inspect the actual installed-skill inventory. Load only recommended skills that are available. Never install a skill automatically.
5. If a selected skill is unavailable, use its registered first-party fallback when one exists. Otherwise continue without it unless the user made that skill a required dependency.
6. Keep the smallest useful team. The registry caps automatic recommendations at four skills. Semantic task matching creates candidates first; empirical feedback may only make a bounded priority adjustment among those candidates.
7. Record only skills actually opened or invoked under `skills_used` in the final bounded MADO LOOP task receipt. A recommendation alone does not count as use.
8. When project-local MADO metadata writes are permitted, record the final outcome with `scripts/record_skill_feedback.py`. The raw ledger remains content-free and the selector consumes only its aggregated cache on future routes.

The Scout may propose specialist skills, but the MADO LOOP orchestrator owns the final route. Worker models cannot recursively add specialists. A Judge may independently use another installed specialist for review, but that skill must also be recorded in the final task receipt.

## Receipt contract

Every final bounded MADO LOOP task receipt should include `skills_used`, even when empty:

```yaml
receipt:
  result: done
  skills_used:
    - game-feel
    - godot-gdscript
  summary: "Improved hit feedback and verified the resulting Godot behavior."
```

Use canonical registry ids. Do not record internal references, worker roles, providers, or ordinary tools as skills. Those continue to use their existing evidence fields.

An OVP `mutation receipt` is a lower-level evidence bundle exchanged between one mutation worker and the orchestrator. It is not the final bounded MADO LOOP task receipt and therefore does not replace or redefine this provenance contract. The orchestrator aggregates specialist usage across its own work and accepted worker evidence into the final `skills_used` field. Provider/runtime metadata stays in its separate evidence fields.

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

## Feedback loop

The learning loop deliberately separates **evidence history** from **routing context**:

- `.mado-loop/skill_feedback.jsonl` is an append-only, content-free ledger. Each event contains only a short opaque receipt id, final `PASS` / `WARN` / `UNKNOWN` / `FAIL`, canonical `skills_used`, repair-cycle count, and optional observed task-total token count.
- `.mado-loop/skill_stats.json` is a compact aggregate cache containing per-skill use/outcome/rework counters plus token totals associated with tasks where that skill participated. Those token counters are correlational, not attribution to one skill.
- Prompts, completions, summaries, source code, secrets, credentials, user data, and raw command logs must never enter the feedback ledger.
- `record_skill_feedback.py` is idempotent by receipt id. Re-recording the exact same event is a no-op; a conflicting duplicate is rejected.
- Feedback never creates a candidate skill. Task-domain and trigger rules still decide relevance first.
- Feedback is ignored until the registry's `feedback_min_samples` threshold is reached, then applies at most `feedback_max_adjustment` priority points. This prevents one lucky or unlucky run from hijacking routing.
- Outcome and repair cycles affect the bounded priority adjustment. Associated task token totals are collected for later normalized efficiency analysis but do not yet change ranking because raw token counts are not comparable across tasks of different complexity or multi-skill participation.
- Missing feedback files are normal. MADO LOOP falls back to the static deterministic registry with no warning and no loss of proof authority.

Example recording command after the final task receipt is known:

```text
python scripts/record_skill_feedback.py --receipt-id T123 --status PASS --skill game-feel --skill godot-gdscript --repair-cycles 1 --tokens 4200
```

Only pass `--tokens` when an actual provider/runtime counter is available. Never estimate token usage just to fill the field.

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

A specialist recommendation is not evidence. A specialist response is not evidence. A favorable historical score is not evidence. Only the normal MADO LOOP RUN → INSPECT → VERIFY → PROVE path establishes completion. `skills_used` is provenance for how the work was approached, and feedback stats are routing hints; neither substitutes for checks, artifacts, proof level, or remaining unknowns.

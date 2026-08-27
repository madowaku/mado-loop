# Runtime Budgets

MADO LOOP must bound its own repair loop and working context. These budgets are safety controls, not optimization hints. They apply per explicit `$mado-loop` invocation unless the user explicitly raises one named limit for that invocation.

## Loop Budget defaults

| Budget | Default | Meaning |
| --- | ---: | --- |
| repair cycles | 5 | Total failed-proof → repair → rerun cycles in one invocation |
| same failure repairs | 2 | Repairs attempted against one normalized failure signature |
| file reversals | 2 per file | Direction changes that undo or reapply substantially the same file change |
| asset regenerations | 3 per asset | Fresh generations of the same logical visual asset |
| full-video inspections | 1 | Full temporal inspection after cheaper evidence was insufficient |
| nested MADO LOOP invocations | 0 | `$mado-loop` may not invoke or delegate back to itself while active |

Crossing a limit is not a retry request. Stop before performing the over-budget action, emit required check `orchestrator.loop_budget` as `UNKNOWN`, retain the current evidence, and report one bounded next action. MADO LOOP may never reset or raise its own limits. The user may explicitly raise one named limit; record the override in the budget state and AI Creole handoff.

A repair cycle begins when a proof/check failure causes a project mutation and ends when the affected check is rerun. Pure inspection, reading, and evidence summarization do not consume a repair cycle. Re-running the same check without a project mutation does not create a repair cycle, but repeated no-change reruns should stop once they no longer produce new evidence.

A failure signature should be stable and compact. Prefer `(proof level, check id, normalized error class, primary path/node/resource)` rather than raw log text. Cosmetic timestamps, temporary paths, frame numbers, and line-number drift should not manufacture a new signature.

A file reversal means an edit substantially restores or reintroduces a state that an earlier repair changed. Ordinary forward edits to the same file do not automatically count as reversals.

## Context Budget

Do not invent exact token counts when the host does not expose reliable token-usage data. Context Budget is enforced through bounded retention and progressive disclosure instead.

Rules:

1. Load only references for active routed domains. Do not preload the specialist library.
2. Keep raw logs, command output, screenshots, and videos as artifacts when possible. Retain only the minimal excerpt needed to explain a finding.
3. Do not paste the same evidence back into context after it has been summarized and linked by stable path/hash/check id.
4. At a meaningful boundary, create or refresh a compact AI Creole checkpoint. Good boundaries include a domain handoff, two repair cycles, a proof-level transition, or before loading another specialist after substantial work.
5. A checkpoint retains: goal, scope, constraints, assumptions, unknowns, routed capabilities, touched files, current diff intent, active proof target, failure signatures and counts, check results, artifact paths/hashes, rollback notes, budget state, and next action.
6. A checkpoint omits: transient full logs, duplicate command output, obsolete failed approaches, repeated reference text, and visual artifacts that can be referred to by path/hash.
7. Do not re-read a large artifact unless a later decision genuinely depends on information not represented in the checkpoint.
8. Full video is last-resort evidence. Prefer structured state, logs, UI report, screenshot, then proof sheet before full temporal inspection.

Context compaction must not erase evidence needed to reproduce a failure or justify the final result. Machine-readable result JSON and durable artifacts remain authoritative; the compact checkpoint is an index and continuation envelope.

## Proof invalidation

After a repair, rerun the failed gate and only downstream gates whose evidence was invalidated by the mutation. Do not automatically replay every earlier proof. Reuse unchanged evidence when its inputs, relevant project files, environment, and tool version remain valid.

## Budget result semantics

Budget exhaustion is an unresolved condition, not a functional failure in itself. Unless another required check already establishes `FAIL`, budget exhaustion makes the operation `UNKNOWN` because the requested claim was not fully established within the authorized work envelope.

Use `scripts/common/budget.py` when a deterministic ledger is useful. Its defaults mirror this document and its required check is compatible with schema-v1.1 aggregation.

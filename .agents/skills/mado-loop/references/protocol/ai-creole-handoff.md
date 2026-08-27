# AI Creole Handoff

AI Creole is a compact handoff envelope for transferring MADO LOOP work between humans and agents. It is a coordination summary, not a replacement for source files, schema v1.1 result JSON, or the human completion report.

## Required envelope

Keep fields in this order so the record remains easy to scan and parse:

```yaml
version: "1.0"
task: "stable task id and short name"
domains: [CODE]
intent: "requested outcome"
scope: {include: [], exclude: []}
constraints: []
assumptions: []
unknowns: []
capabilities_routes: []
touched_files: []
actions: []
checks_results: []
artifacts: []
budget_state: {}
rollback: []
risks: []
next_action: "one concrete continuation or none"
owner: "responsible role or person"
```

`domains` follows schema v1.1 canonical domain order, deduplicates concrete domains, and appends derived `MIXED` for two or more concrete domains; never supply `MIXED` alone. `unknowns` contains only unresolved facts that could invalidate a claim. `capabilities_routes` names selected, missing, or declined routes and whether each is required or optional. `checks_results` links check IDs to status and evidence rather than copying large logs. `artifacts` uses repository-relative or explicitly portable paths plus hashes when available. `budget_state` records Loop Budget limits, usage, explicit overrides, blocked reasons, and context checkpoint count when relevant; do not invent token counts if the host does not expose them. `rollback` states how to reverse touched state safely. `owner` identifies who must act, not who merely observed.

Never include passwords, tokens, cookies, private keys, personal data, or secret-bearing command output. Redact rather than encode. Do not paste transient logs; link a durable evidence artifact and summarize the relevant finding.

## Authority and status

Machine-readable schema v1.1 JSON is the source evidence for checks, statuses, artifacts, domains, and exit behavior. The human completion report is authoritative for the final explanation, decisions, limitations, and handoff. AI Creole must agree with both but cannot change either. If they conflict, preserve the conflict in `unknowns` or `risks`, link both records, and request reconciliation; never silently choose a more favorable status.

Use `FAIL > UNKNOWN > WARN > PASS`. Required `SKIPPED` yields `UNKNOWN`; optional `SKIPPED` yields a warning. Top-level `SKIPPED` is valid only when the entire operation is not applicable or was not requested. Keep unknowns, assumptions, risks, optional capability absence, and budget exhaustion distinct.

Update the envelope at a meaningful handoff or Context Budget boundary, not after every command. Good compaction points include domain handoff, two repair cycles, proof-level transition, or before loading a new specialist after substantial work. Preserve stable IDs and append evidence links rather than rewriting history. The receiver validates scope, unknowns, required routes, touched files, budget state, and next owner before continuing. A receiver continues the existing logical run from the handoff; it does not create a nested `$mado-loop` invocation to reset budgets.

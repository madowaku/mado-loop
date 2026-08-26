# FIELD NOTES Policy

FIELD NOTES retain durable, project-specific lessons that materially improve future MADO LOOP work. They are evidence-backed memory, not a log, knowledge dump, preference file, or proof of completion.

## Admission criteria

A note must contain:

- date recorded and, when known, the evidence date;
- project and scope where the lesson applies;
- the lesson stated as a bounded observation;
- durable evidence links such as a result, issue, fixture, commit, capture, or measured comparison;
- confidence (`low`, `medium`, or `high`) and why;
- a revalidation trigger such as engine upgrade, platform change, scene redesign, dependency update, or contradictory result;
- owner or role responsible for revalidation.

Exclude secrets and personal data, transient command output, raw session logs, generic Godot knowledge, unsupported preferences, speculation presented as fact, duplicated documentation, and any claim that work or release is complete. A note may link authoritative evidence but cannot award `PASS` or override schema v1.1 results.

## Lifecycle

**Write:** Add a note only after a repeatable project-specific lesson or consequential constraint is supported by durable evidence. Minimize it to the decision-relevant fact. Redact sensitive values and use portable repository-relative links where possible.

**Read:** Filter notes by project, applicable scope, date, confidence, and revalidation trigger. Treat a note as context, then confirm it still applies before using it as an acceptance premise. If confirmation is required but unavailable, record the fact in schema v1.1 `unknowns`; do not turn note confidence into proof confidence.

**Update:** Preserve the original date and evidence, append the new evidence/date, revise confidence and scope explicitly, and record why the conclusion changed. Mark a triggered note `needs-revalidation` until checked. Do not silently rewrite contradictory history.

**Prune:** Remove or archive notes that are superseded, duplicated, disproved, outside project scope, or no longer actionable. Preserve a short tombstone when deletion would break evidence links. Immediately remove exposed secrets from the note and follow the project's credential-rotation process; do not retain the secret in history for explanatory value.

Review notes at release audit and whenever a revalidation trigger fires. Missing FIELD NOTES never makes an otherwise proven claim fail, and an unavailable optional notes store is optional `SKIPPED` plus warning. If a required project-specific fact is unresolved, represent that fact—not the absence of a note—in `unknowns`.

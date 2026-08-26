# Project Safety Contract

## Before mutation

- Resolve the Godot project root and inspect project conventions, version-control state, and overlapping user changes.
- Keep work inside the user-authorized project and task scope. Do not replace project architecture or unrelated assets to simplify the task.
- Choose reversible edits and preserve source assets. Record any generated or imported files so they can be reviewed or removed precisely.

## Authority boundaries

- Never expose, copy, log, or commit secrets. Use existing credential mechanisms without printing their values.
- Do not delete, overwrite, force-reset, force-push, publish, deploy, purchase, or message external parties without explicit authority for that action.
- Do not auto-install skills, plugins, packages, editors, generators, or system dependencies. Report a missing required dependency as `UNKNOWN`; report an unavailable optional capability as an optional `SKIPPED` check and warning.
- Treat third-party code and assets according to their license, provenance, and the source-adoption policy. Do not modify immutable vendor payloads.

## Repair boundary

Repair only defects attributable to the requested work. Reinspect the affected project state after each repair. Stop before a destructive action, a scope expansion, an unresolved ownership conflict, or a change that requires product or architectural judgment from the user.

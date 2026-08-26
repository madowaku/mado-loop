# Source adoption policy

Audit every external source as `VENDOR`, `DISTILL`, `ROUTE`, or `REJECT`. Do not bulk-copy repositories. A copied artifact requires an exact revision, license, retained provenance, manifest coverage, and a deliberate update procedure.

## VENDOR

Vendored payloads are immutable. First-party adapters own normalization, schema conversion, policy enforcement, and error handling.

### Godot skill

- Source: `haxqer/godot-skill`
- Revision: `8e0552b158861020d6a9a12059ce11c4ba8cd303`
- License: MIT, retained with the snapshot
- Copied path: full repository payload under MADO LOOP's `vendor/godot-skill/payload/`, plus its license, provenance record, and checksum manifest
- Role: pinned Godot engine tooling behind a first-party adapter
- Update policy: an explicit updater fetches the named revision, verifies the exact file set and bytes, regenerates the manifest and provenance, and requires tests/review before adoption; never float a branch or tag

### Agent Sprite Forge processor

- Source: `0x0funky/agent-sprite-forge`
- Revision: `64fd0b57d3f2ae117ef0a95e4c2decc25b4c9dd2`
- License: MIT, retained with the snapshot
- Copied path: only `skills/generate2dsprite/scripts/generate2dsprite.py` and the repository license, stored with provenance and checksum metadata
- Role: deterministic sprite processor behind a first-party adapter; the adapter owns pixel-art-safe nearest-neighbor behavior, result conversion, frame lockback, preview, and atlas integration
- Update policy: an explicit updater fetches only the named file and license at an exact revision, verifies bytes and checksums, and requires adapter/tests review before adoption; broad repository copying is prohibited

If the exact provenance or license for a proposed copied file cannot be verified, stop and do not vendor it.

## DISTILL

Distillation extracts decision rules into original MADO LOOP references. Do not copy source wording, templates, examples, or code. Record the dependency so later maintainers can repeat the audit.

- **OpenAI Game Studio — Sprite Pipeline, Game UI Frontend, Game Playtest**: local plugin sources, MIT. Distill sprite workflow, game UI concerns, and playtest practice into domain references; do not make the plugin a runtime dependency.
- **OpenAI Product Design — image-to-code**: proprietary. Distill only high-level, independently expressed reference-to-interface decision patterns. Copy no text, code, templates, or assets and create no runtime dependency.
- **nextlevelbuilder/ui-ux-pro-max-skill** at `9f1824aa7bd87b7a2db8e19afd7fbe40d5f354e5`, MIT: distill applicable UI quality heuristics into game-specific guidance; do not vendor the repository.
- **awesome-gamedev-agent-skills** at `7110607ab816ece9669274bc84937857a8819796`, Apache-2.0: distill relevant game-development routing and review concepts; do not copy its skill collection.
- **Owner-authored generic pixel-art rules**: first-party source of generic pixel rules. Maintain them as original MADO LOOP guidance; they do not authorize copying from unidentified repositories.

Distilled guidance is maintained as first-party text. Re-audit its named source and license before incorporating material from a newer revision.

## ROUTE

Routed capabilities remain external and optional unless the user explicitly makes one required:

- **Agent Skills Hub** is registry/discovery only. Route to a matching installed or user-approved capability; never copy registry entries or auto-install a result.
- **ImageGen** is an optional image creation/editing route. Use only when available and appropriate; do not bundle it or claim availability.
- **External image editors** are optional routed tools. Require explicit selection and authorization for external state changes.
- **Installed specialist skills** may be routed by declared capability. Do not assume installation, read private implementation into MADO LOOP, or let them bypass integration proof.

## REJECT

Reject these adoption patterns:

- unidentified “Pixel Art Game Builder” or “Pixel Art Skills” repositories without verified identity, revision, and license;
- bulk vendoring when a narrow file or distilled rule is sufficient;
- copied proprietary Product Design material;
- branch-, tag-, or latest-based vendor snapshots;
- patched vendor payloads presented as upstream bytes;
- automatic installation of registry entries, skills, plugins, editors, or models.

When a rejected source appears useful, use owner-authored generic rules, a verified audited alternative, or an optional routed capability instead. Escalate for a new source decision rather than weakening provenance requirements.

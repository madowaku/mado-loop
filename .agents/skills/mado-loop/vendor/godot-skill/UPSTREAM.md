# Upstream provenance

- Source: https://github.com/haxqer/godot-skill.git
- Commit: `8e0552b158861020d6a9a12059ce11c4ba8cd303`
- Acquisition date: 2026-08-25
- Vendored upstream paths: `skill/godot/**` -> `payload/**`; `LICENSE` -> `LICENSE`
- Local modifications: none

## Update procedure

Run `python scripts/update_vendor.py --update --pin <full-40-character-sha> --acquired YYYY-MM-DD`.
Review the resulting snapshot and provenance, then run the same command with `--check` and the explicit pin. The updater stages and validates all content before atomically replacing this directory; Git metadata and cache files are never included.

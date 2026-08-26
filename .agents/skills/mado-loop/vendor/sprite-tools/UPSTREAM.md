# Upstream provenance

- Source: https://github.com/0x0funky/agent-sprite-forge.git
- Commit: `64fd0b57d3f2ae117ef0a95e4c2decc25b4c9dd2`
- Acquisition date: 2026-08-25
- Vendored upstream paths: `skills/generate2dsprite/scripts/generate2dsprite.py` -> `payload/generate2dsprite.py`; `LICENSE` -> `LICENSE`
- Local modifications: none

## Runtime dependencies

The vendored processor requires Pillow >= 10 and NumPy >= 1.26. MADO LOOP does not install them automatically.


## Update procedure

Run `python scripts/update_vendor.py --vendor sprite-tools --update --pin <full-40-character-sha> --acquired YYYY-MM-DD`.
Review the resulting snapshot and provenance, then run the same command with `--check` and the explicit pin. The updater stages and validates all content before atomically replacing this directory; Git metadata and cache files are never included.

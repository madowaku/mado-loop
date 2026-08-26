#!/usr/bin/env python3
"""Update or verify approved pinned vendor snapshots using only stdlib."""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


DEFAULT_REPOSITORY = "https://github.com/haxqer/godot-skill.git"
PINNED_COMMIT = "8e0552b158861020d6a9a12059ce11c4ba8cd303"
SPRITE_REPOSITORY = "https://github.com/0x0funky/agent-sprite-forge.git"
SPRITE_PINNED_COMMIT = "64fd0b57d3f2ae117ef0a95e4c2decc25b4c9dd2"
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
VENDOR_ROOT = REPOSITORY_ROOT / ".agents" / "skills" / "mado-loop" / "vendor" / "godot-skill"
SPRITE_VENDOR_ROOT = REPOSITORY_ROOT / ".agents" / "skills" / "mado-loop" / "vendor" / "sprite-tools"
PIN_RE = re.compile(r"[0-9a-f]{40}")
JUNK_NAMES = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".DS_Store"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _snapshot_files(root: Path) -> list[Path]:
    files = [root / "LICENSE"]
    files.extend(path for path in (root / "payload").rglob("*") if path.is_file())
    return sorted(files, key=lambda path: path.relative_to(root).as_posix())


def _vendor_settings(vendor: str) -> tuple[str, str, Path, str, str]:
    if vendor == "godot-skill":
        return DEFAULT_REPOSITORY, PINNED_COMMIT, VENDOR_ROOT, "skill/godot", "payload"
    if vendor == "sprite-tools":
        return (
            SPRITE_REPOSITORY, SPRITE_PINNED_COMMIT, SPRITE_VENDOR_ROOT,
            "skills/generate2dsprite/scripts/generate2dsprite.py",
            "payload/generate2dsprite.py",
        )
    raise ValueError(f"unknown vendor: {vendor}")


def _manifest_text(root: Path) -> str:
    return "".join(
        f"{_sha256(path)}  {path.relative_to(root).as_posix()}\n"
        for path in _snapshot_files(root)
    )


def _upstream_text(
    repository: str, pin: str, acquired: str, source: str, destination: str, vendor: str,
) -> str:
    dependency_note = ""
    if vendor == "sprite-tools":
        dependency_note = """
## Runtime dependencies

The vendored processor requires Pillow >= 10 and NumPy >= 1.26. MADO LOOP does not install them automatically.
"""
    return f"""# Upstream provenance

- Source: {repository}
- Commit: `{pin}`
- Acquisition date: {acquired}
- Vendored upstream paths: `{source}` -> `{destination}`; `LICENSE` -> `LICENSE`
- Local modifications: none
{dependency_note}

## Update procedure

Run `python scripts/update_vendor.py --vendor {vendor} --update --pin <full-40-character-sha> --acquired YYYY-MM-DD`.
Review the resulting snapshot and provenance, then run the same command with `--check` and the explicit pin. The updater stages and validates all content before atomically replacing this directory; Git metadata and cache files are never included.
"""


def _validate_pin(pin: str) -> None:
    if PIN_RE.fullmatch(pin) is None:
        raise ValueError("--pin must be a lowercase full 40-character commit SHA")


def _assert_no_junk(root: Path) -> None:
    junk = [path for path in root.rglob("*") if path.name in JUNK_NAMES or path.suffix == ".pyc"]
    if junk:
        raise RuntimeError("vendor snapshot contains junk: " + ", ".join(str(path) for path in junk))


def check(pin: str, root: Path = VENDOR_ROOT) -> None:
    """Verify provenance and every vendored byte without network access."""
    _validate_pin(pin)
    required = [root / "payload", root / "LICENSE", root / "UPSTREAM.md", root / "MANIFEST.sha256"]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise RuntimeError("missing vendor artifacts: " + ", ".join(missing))
    provenance = (root / "UPSTREAM.md").read_text(encoding="utf-8")
    if f"Commit: `{pin}`" not in provenance or "Local modifications: none" not in provenance:
        raise RuntimeError("UPSTREAM.md does not attest the explicit pin and unmodified snapshot")
    _assert_no_junk(root)
    actual = _manifest_text(root)
    expected = (root / "MANIFEST.sha256").read_text(encoding="ascii")
    if actual != expected:
        raise RuntimeError("vendor manifest does not match snapshot bytes")


def _checkout(repository: str, pin: str, destination: Path) -> None:
    subprocess.run(
        ["git", "clone", "--filter=blob:none", "--no-checkout", repository, str(destination)],
        check=True,
    )
    subprocess.run(["git", "-C", str(destination), "checkout", "--detach", pin], check=True)
    resolved = subprocess.run(
        ["git", "-C", str(destination), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if resolved != pin:
        raise RuntimeError(f"resolved SHA {resolved} does not match explicit pin {pin}")


def compare_live(
    repository: str, pin: str, root: Path = VENDOR_ROOT,
    source: str = "skill/godot", destination: str = "payload",
) -> None:
    """Checkout a pinned source and compare selected paths byte-for-byte."""
    _validate_pin(pin)
    with tempfile.TemporaryDirectory(prefix="mado-loop-vendor-live-") as temp_name:
        checkout = Path(temp_name) / "checkout"
        _checkout(repository, pin, checkout)
        source_payload = checkout / source
        source_license = checkout / "LICENSE"
        if not source_payload.exists() or not source_license.is_file():
            raise RuntimeError(f"upstream is missing {source} or LICENSE")
        if source_payload.is_file():
            vendor_payload = root / destination
            if not vendor_payload.is_file() or source_payload.read_bytes() != vendor_payload.read_bytes():
                raise RuntimeError(f"payload byte mismatch: {destination}")
            if source_license.read_bytes() != (root / "LICENSE").read_bytes():
                raise RuntimeError("LICENSE byte mismatch")
            return
        source_paths = {
            path.relative_to(source_payload).as_posix(): path
            for path in source_payload.rglob("*")
            if path.is_file()
        }
        vendor_paths = {
            path.relative_to(root / "payload").as_posix(): path
            for path in (root / "payload").rglob("*")
            if path.is_file()
        }
        if source_paths.keys() != vendor_paths.keys():
            missing = sorted(source_paths.keys() - vendor_paths.keys())
            extra = sorted(vendor_paths.keys() - source_paths.keys())
            raise RuntimeError(f"payload path mismatch; missing={missing}, extra={extra}")
        changed = sorted(
            relative
            for relative in source_paths
            if source_paths[relative].read_bytes() != vendor_paths[relative].read_bytes()
        )
        if changed:
            raise RuntimeError("payload byte mismatch: " + ", ".join(changed))
        if source_license.read_bytes() != (root / "LICENSE").read_bytes():
            raise RuntimeError("LICENSE byte mismatch")


def update(
    repository: str, pin: str, acquired: str, root: Path = VENDOR_ROOT,
    source: str = "skill/godot", destination: str = "payload", vendor: str = "godot-skill",
) -> None:
    _validate_pin(pin)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", acquired) is None:
        raise ValueError("--acquired must use YYYY-MM-DD")
    root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{root.name}-stage-", dir=root.parent) as temp_name:
        temp = Path(temp_name)
        checkout = temp / "checkout"
        staged = temp / "vendor"
        _checkout(repository, pin, checkout)
        source_payload = checkout / source
        source_license = checkout / "LICENSE"
        if not source_payload.exists() or not source_license.is_file():
            raise RuntimeError(f"upstream is missing {source} or LICENSE")
        target_payload = staged / destination
        target_payload.parent.mkdir(parents=True, exist_ok=True)
        if source_payload.is_dir():
            shutil.copytree(source_payload, target_payload)
        else:
            shutil.copy2(source_payload, target_payload)
        shutil.copy2(source_license, staged / "LICENSE")
        (staged / "UPSTREAM.md").write_text(
            _upstream_text(repository, pin, acquired, source, destination, vendor),
            encoding="utf-8", newline="\n"
        )
        (staged / "MANIFEST.sha256").write_text(
            _manifest_text(staged), encoding="ascii", newline="\n"
        )
        _assert_no_junk(staged)
        check(pin, staged)

        backup = root.with_name(root.name + ".backup")
        if backup.exists():
            raise RuntimeError(f"refusing update while stale backup exists: {backup}")
        replaced = False
        try:
            if root.exists():
                os.replace(root, backup)
                replaced = True
            os.replace(staged, root)
        except BaseException:
            if replaced and backup.exists() and not root.exists():
                os.replace(backup, root)
            raise
        else:
            if backup.exists():
                shutil.rmtree(backup)


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--check-live", action="store_true")
    mode.add_argument("--update", action="store_true")
    parser.add_argument("--vendor", choices=("godot-skill", "sprite-tools"), default="godot-skill")
    parser.add_argument("--pin", help="lowercase full 40-character commit SHA")
    parser.add_argument("--repository")
    parser.add_argument("--acquired", help="acquisition date (YYYY-MM-DD), required for --update")
    args = parser.parse_args()
    try:
        default_repository, default_pin, root, source, destination = _vendor_settings(args.vendor)
        pin = args.pin or default_pin
        repository = args.repository or default_repository
        if args.update:
            if args.acquired is None:
                parser.error("--acquired is required for --update")
            update(repository, pin, args.acquired, root, source, destination, args.vendor)
        elif args.check_live:
            check(pin, root)
            compare_live(repository, pin, root, source, destination)
        else:
            check(pin, root)
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"vendor verification failed: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

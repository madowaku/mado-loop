#!/usr/bin/env python3
"""Build a byte-reproducible, install-ready MADO LOOP skill archive."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Sequence


ARCHIVE_ROOT = "mado-loop"
FIXED_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
FILE_MODE = stat.S_IFREG | 0o644
COMPRESSION = zipfile.ZIP_DEFLATED
COMPRESSION_LEVEL = 9
FORBIDDEN_PARTS = frozenset(
    {".git", ".github", ".godot", "__pycache__", "dist", "docs", "tests"}
)
REQUIRED_MEMBERS = frozenset(
    {
        "mado-loop/SKILL.md",
        "mado-loop/vendor/godot-skill/LICENSE",
        "mado-loop/vendor/godot-skill/payload/SKILL.md",
        "mado-loop/vendor/sprite-tools/LICENSE",
        "mado-loop/vendor/sprite-tools/payload/generate2dsprite.py",
    }
)


class PackageError(RuntimeError):
    """Raised when a safe, complete package cannot be produced."""


def _is_forbidden(relative_path: PurePosixPath) -> bool:
    return any(part.lower() in FORBIDDEN_PARTS for part in relative_path.parts) or (
        relative_path.suffix.lower() in {".pyc", ".zip"}
    )


def audit_member_name(name: str) -> None:
    """Reject archive names that could escape or vary across platforms."""
    if not name or "\\" in name or name.startswith(("/", "//")):
        raise PackageError(f"unsafe archive member: {name!r}")
    if re.match(r"^[A-Za-z]:", name):
        raise PackageError(f"drive-qualified archive member: {name!r}")
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or path.parts[0] != ARCHIVE_ROOT:
        raise PackageError(f"unsafe archive member: {name!r}")


def audit_archive(archive_path: Path) -> tuple[str, ...]:
    """Audit every member of an existing ZIP and return its ordered names."""
    with zipfile.ZipFile(archive_path, "r") as archive:
        names = tuple(info.filename for info in archive.infolist())
    for name in names:
        audit_member_name(name)
    if len(names) != len(set(names)):
        raise PackageError("duplicate archive members")
    return names


def collect_payload(source: Path) -> tuple[tuple[str, Path], ...]:
    """Collect safe payload files in deterministic archive order."""
    source = source.resolve()
    if not source.is_dir() or not (source / "SKILL.md").is_file():
        raise PackageError(f"not a skill payload directory: {source}")

    collected: list[tuple[str, Path]] = []
    for candidate in source.rglob("*"):
        relative = PurePosixPath(candidate.relative_to(source).as_posix())
        if _is_forbidden(relative):
            continue
        if candidate.is_symlink():
            raise PackageError(f"symbolic links are not packageable: {relative}")
        if candidate.is_dir():
            continue
        if not candidate.is_file():
            raise PackageError(f"unsupported payload entry: {relative}")
        member = f"{ARCHIVE_ROOT}/{relative.as_posix()}"
        audit_member_name(member)
        collected.append((member, candidate))

    collected.sort(key=lambda item: item[0])
    names = {name for name, _ in collected}
    missing = sorted(REQUIRED_MEMBERS - names)
    if missing:
        raise PackageError("required payload missing: " + ", ".join(missing))
    return tuple(collected)


def _zip_info(member: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(member, FIXED_TIMESTAMP)
    info.compress_type = COMPRESSION
    info.create_system = 3
    info.create_version = 20
    info.extract_version = 20
    info.external_attr = FILE_MODE << 16
    info.internal_attr = 0
    info.flag_bits = 0x800
    info.extra = b""
    info.comment = b""
    return info


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_package(source: Path, output: Path) -> dict[str, object]:
    """Atomically build a deterministic ZIP from the MADO LOOP payload."""
    source = source.resolve()
    output = output.resolve()
    entries = collect_payload(source)

    if output.exists() and output.is_dir():
        raise PackageError(f"output is a directory: {output}")
    try:
        output_relative = PurePosixPath(output.relative_to(source).as_posix())
    except ValueError:
        output_relative = None
    if output_relative is not None and not _is_forbidden(output_relative):
        raise PackageError("output inside payload must be a generated .zip or forbidden path")

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{output.name}.", suffix=".tmp", dir=output.parent
        )
        os.close(descriptor)
        temporary_path = Path(temporary_name)
        with zipfile.ZipFile(
            temporary_path,
            "w",
            compression=COMPRESSION,
            compresslevel=COMPRESSION_LEVEL,
            strict_timestamps=True,
        ) as archive:
            archive.comment = b""
            for member, payload_path in entries:
                archive.writestr(
                    _zip_info(member),
                    payload_path.read_bytes(),
                    compress_type=COMPRESSION,
                    compresslevel=COMPRESSION_LEVEL,
                )
        names = audit_archive(temporary_path)
        if names != tuple(sorted(names)):
            raise PackageError("archive members are not lexicographically ordered")
        os.replace(temporary_path, output)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    return {
        "archive": str(output),
        "member_count": len(entries),
        "root": f"{ARCHIVE_ROOT}/",
        "sha256": sha256_file(output),
        "status": "PASS",
    }


def build_parser() -> argparse.ArgumentParser:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=repo_root / ".agents" / "skills" / ARCHIVE_ROOT,
        help="skill payload directory (default: repository MADO LOOP payload)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=repo_root / "dist" / f"{ARCHIVE_ROOT}.zip",
        help="output ZIP path",
    )
    parser.add_argument("--json", action="store_true", help="emit compact JSON evidence")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        evidence = build_package(args.source, args.output)
    except (OSError, PackageError, zipfile.BadZipFile) as error:
        failure = {"status": "FAIL", "error": str(error)}
        print(json.dumps(failure, sort_keys=True) if args.json else f"FAIL: {error}")
        return 1
    if args.json:
        print(json.dumps(evidence, sort_keys=True, separators=(",", ":")))
    else:
        print(
            f"PASS: {evidence['archive']} "
            f"({evidence['member_count']} members, sha256={evidence['sha256']})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Strict, offline audit of Android APK and AAB release artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
from time import monotonic
from typing import Mapping, Sequence
import zipfile

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common.result import (  # noqa: E402
    EXIT_INTERNAL, EXIT_USAGE_CONFIG, elapsed_ms, exit_code_for_status,
    make_artifact, make_check, make_result, result_json,
)

APK_REQUIRED = ("AndroidManifest.xml", "classes.dex")
AAB_REQUIRED = ("BundleConfig.pb", "base/manifest/AndroidManifest.xml", "base/dex/classes.dex")


def _unsafe_or_confusing(names: Sequence[str]) -> tuple[list[str], list[list[str]]]:
    unsafe = []
    identities: dict[str, list[str]] = {}
    for name in names:
        normalized = name.replace("\\", "/")
        path = PurePosixPath(normalized)
        if path.is_absolute() or ".." in path.parts or "\\" in name:
            unsafe.append(name)
        identity = "/".join(part for part in path.parts if part not in ("", ".")).casefold()
        identities.setdefault(identity, []).append(name)
    duplicates = [sorted(values) for values in identities.values() if len(values) > 1]
    return sorted(unsafe), sorted(duplicates, key=lambda item: tuple(item))


def _run_apksigner(executable: str, artifact: Path, timeout: float) -> tuple[str, str]:
    try:
        completed = subprocess.run(
            [executable, "verify", "--verbose", str(artifact)], capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return "UNKNOWN", type(exc).__name__
    output = ((completed.stdout or "") + (completed.stderr or "")).strip()[:500]
    return ("PASS" if completed.returncode == 0 else "FAIL"), output or f"exit {completed.returncode}"


def audit_release(
    artifact_path: str | Path, *, artifact_type: str | None = None,
    verify_signature: bool = False, apksigner: str | None = None, timeout: float = 10.0,
) -> dict[str, object]:
    """Audit one APK/AAB without network access, installation, or secret material."""
    started = monotonic()
    path = Path(artifact_path)
    inferred = path.suffix.lower().lstrip(".")
    kind = (artifact_type or inferred).lower()
    checks = []
    errors = []
    warnings = []
    unknowns = []

    regular = path.is_file()
    checks.append(make_check("artifact.regular_file", "PASS" if regular else "FAIL",
                             message="Artifact is a regular file." if regular else "Artifact path is missing or not a regular file."))
    extension_ok = kind in {"apk", "aab"} and path.suffix.lower() == f".{kind}"
    checks.append(make_check("artifact.type_extension", "PASS" if extension_ok else "FAIL",
                             message="Artifact type and extension agree." if extension_ok else "Expected an APK or AAB with matching extension.",
                             details={"declared_type": kind, "extension": path.suffix.lower()}))
    nonzero = regular and path.stat().st_size > 0
    checks.append(make_check("artifact.nonzero", "PASS" if nonzero else "FAIL",
                             message="Artifact is non-empty." if nonzero else "Artifact is empty or unavailable."))

    names: list[str] = []
    zip_ok = False
    if regular and nonzero:
        try:
            with zipfile.ZipFile(path) as archive:
                names = archive.namelist()
                bad = archive.testzip()
                zip_ok = bad is None
                if bad:
                    errors.append({"id": "zip.corrupt_member", "member": bad})
        except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
            errors.append({"id": "zip.invalid", "error": type(exc).__name__})
    checks.append(make_check("archive.zip_integrity", "PASS" if zip_ok else "FAIL",
                             message="ZIP container and members are readable." if zip_ok else "ZIP container is invalid or corrupt."))

    required = APK_REQUIRED if kind == "apk" else AAB_REQUIRED if kind == "aab" else ()
    missing = [name for name in required if name not in names]
    structure_ok = zip_ok and bool(required) and not missing
    checks.append(make_check(f"archive.{kind or 'unknown'}_structure", "PASS" if structure_ok else "FAIL",
                             message=f"{kind.upper()} required structure is present." if structure_ok else "Required package entries are missing.",
                             evidence=list(required), details={"missing": missing}))

    unsafe, duplicates = _unsafe_or_confusing(names)
    safe = zip_ok and not unsafe and not duplicates
    checks.append(make_check("archive.safe_names", "PASS" if safe else "FAIL",
                             message="Archive member names are safe and unambiguous." if safe else "Unsafe or confusing archive member names were found.",
                             details={"confusing_duplicates": duplicates, "unsafe": unsafe}))

    if kind == "apk":
        signature_entries = sorted(name for name in names if name.upper().startswith("META-INF/") and name.upper().endswith((".RSA", ".DSA", ".EC")))
        present = bool(signature_entries)
        checks.append(make_check("signature.presence", "PASS" if present else "SKIPPED", required=False,
                                 message="APK signature container entries are present." if present else "No legacy APK signature container entry was observed.",
                                 evidence=signature_entries))
        if not present:
            warnings.append({"id": "signature.not_observed", "message": "Signature presence was not observed; APK signing scheme v2+ may require apksigner to inspect."})
        if verify_signature:
            executable = apksigner or shutil.which("apksigner")
            if not executable:
                message = "Signature verification was requested but apksigner was not explicitly located or found on PATH."
                checks.append(make_check("signature.verification", "UNKNOWN", message=message))
                unknowns.append({"id": "signature.tool_missing", "message": message})
            else:
                status, evidence = _run_apksigner(executable, path, timeout)
                checks.append(make_check("signature.verification", status,
                                         message="APK signature verified." if status == "PASS" else "APK signature could not be verified.",
                                         evidence=[evidence], details={"tool": executable}))
                if status == "UNKNOWN":
                    unknowns.append({"id": "signature.tool_unavailable", "message": evidence})
                elif status == "FAIL":
                    errors.append({"id": "signature.invalid", "message": evidence})
    elif verify_signature:
        message = "This auditor has no bounded AAB signature-verification capability."
        checks.append(make_check("signature.verification", "UNKNOWN", message=message))
        unknowns.append({"id": "signature.aab_unverified", "message": message})

    result = make_result(
        "release_audit", proof_level="P5", task_domains=["RELEASE"],
        summary=f"Offline {kind.upper() if kind else 'Android'} artifact audit completed.",
        checks=checks, errors=errors, warnings=warnings, unknowns=unknowns,
        artifacts=[make_artifact(path, kind or "android-package")],
        environment={"metadata_network": False, "signature_verification_requested": verify_signature,
                     "timeout_seconds": timeout}, duration_ms=elapsed_ms(started),
    )
    return result


def human_output(payload: Mapping[str, object]) -> str:
    lines = [f"MADO Release Audit: {payload['status']}", str(payload["summary"])]
    for check in payload["checks"]:  # type: ignore[union-attr]
        lines.append(f"[{check['status']}] {check['id']}: {check['message']}")
    return "\n".join(lines) + "\n"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact")
    parser.add_argument("--type", choices=("apk", "aab"), dest="artifact_type")
    parser.add_argument("--verify-signature", action="store_true")
    parser.add_argument("--apksigner", help="explicit apksigner executable path")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--human", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
        if not 0 < args.timeout <= 60:
            raise ValueError("timeout must be greater than 0 and at most 60 seconds")
        payload = audit_release(args.artifact, artifact_type=args.artifact_type,
                                verify_signature=args.verify_signature, apksigner=args.apksigner,
                                timeout=args.timeout)
        if args.human:
            sys.stdout.write(human_output(payload))
        elif args.pretty:
            sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        else:
            sys.stdout.write(result_json(payload))
        return exit_code_for_status(str(payload["status"]))
    except SystemExit as exc:
        return 0 if exc.code == 0 else EXIT_USAGE_CONFIG
    except ValueError as exc:
        sys.stderr.write(f"release_audit configuration error: {exc}\n")
        return EXIT_USAGE_CONFIG
    except Exception as exc:  # pragma: no cover
        sys.stderr.write(f"release_audit internal error: {exc}\n")
        return EXIT_INTERNAL


if __name__ == "__main__":
    raise SystemExit(main())

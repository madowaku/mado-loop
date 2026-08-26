"""Export and audit a real Godot ZIP pack as schema-v1.1 P5 evidence."""

from __future__ import annotations

import hashlib
import re
import stat
import zipfile
from pathlib import Path, PurePosixPath
from time import monotonic
from typing import Any, Callable

from .godot_tool import run_godot_tool
from .result import elapsed_ms, make_artifact, make_check, make_result

Adapter = Callable[..., dict[str, Any]]
SOURCE_SUFFIXES = {".gd", ".godot", ".tscn", ".tres", ".cfg", ".json"}
REQUIRED_MEMBERS = {
    ".godot/global_script_class_cache.cfg",
    ".godot/uid_cache.bin",
    "export_fixture.gd.remap",
    "export_fixture.gdc",
    "main.tscn.remap",
    "project.binary",
}
EXPORTED_SCENE = re.compile(r"\.godot/exported/[0-9]+/export-[0-9a-f]+-main\.scn\Z")


def _source_hash(project_path: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(project_path.rglob("*"), key=lambda item: item.as_posix()):
        if not path.is_file() or ".godot" in path.relative_to(project_path).parts:
            continue
        if path.suffix.lower() not in SOURCE_SUFFIXES and path.name != "project.godot":
            continue
        relative = path.relative_to(project_path).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _unknown(summary: str, check_id: str, *, started: float,
             environment: dict[str, Any]) -> dict[str, Any]:
    return make_result(
        "godot_release_proof", proof_level="P5", task_domains=["RELEASE"], summary=summary,
        checks=[make_check(check_id, "UNKNOWN", message=summary)],
        unknowns=[{"id": check_id, "message": summary}], environment=environment,
        duration_ms=elapsed_ms(started),
    )


def _fail(summary: str, check_id: str, *, started: float,
          environment: dict[str, Any], artifact: Path | None = None,
          evidence: list[Any] | None = None) -> dict[str, Any]:
    artifacts = [make_artifact(artifact, "godot-pack")] if artifact is not None else []
    return make_result(
        "godot_release_proof", proof_level="P5", task_domains=["RELEASE"], summary=summary,
        checks=[make_check(check_id, "FAIL", message=summary, evidence=evidence)],
        errors=[{"id": check_id, "message": summary}], artifacts=artifacts,
        environment=environment, duration_ms=elapsed_ms(started),
    )


def _audit_zip(artifact: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    evidence: dict[str, Any] = {"members": [], "member_count": 0, "manifest_sha256": ""}
    try:
        with zipfile.ZipFile(artifact) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            evidence["members"] = sorted(names)
            evidence["member_count"] = len(names)
            if not names or len(names) > 16:
                failures.append({"id": "release.zip_bounds", "message": "ZIP member count is outside the fixture contract."})
            if archive.testzip() is not None:
                failures.append({"id": "release.zip_integrity", "message": "ZIP CRC integrity failed."})

            folded: set[str] = set()
            exact: set[str] = set()
            for info in infos:
                name = info.filename
                path = PurePosixPath(name)
                unsafe = (
                    not name or len(name) > 256 or "\\" in name or "\x00" in name
                    or path.is_absolute() or ".." in path.parts or bool(path.drive)
                )
                mode = (info.external_attr >> 16) & 0xFFFF
                if unsafe or stat.S_ISLNK(mode):
                    failures.append({"id": "release.zip_paths", "message": f"Unsafe ZIP member: {name!r}"})
                lowered = name.casefold()
                if name in exact or lowered in folded:
                    failures.append({"id": "release.zip_duplicates", "message": f"Duplicate or case-confusing member: {name!r}"})
                exact.add(name)
                folded.add(lowered)
                if not info.is_dir() and info.file_size <= 0:
                    failures.append({"id": "release.zip_contents", "message": f"Empty fixture member: {name!r}"})

            exported = sorted(name for name in names if EXPORTED_SCENE.fullmatch(name))
            expected = REQUIRED_MEMBERS | set(exported)
            if len(exported) != 1 or set(names) != expected:
                failures.append({"id": "release.fixture_members", "message": "ZIP members do not match the bounded Godot fixture contract."})
            if not failures:
                scene_name = exported[0]
                gd_remap = archive.read("export_fixture.gd.remap")
                scene_remap = archive.read("main.tscn.remap")
                checks = (
                    (archive.read("export_fixture.gdc").startswith(b"GDSC"), "Compiled fixture script is missing its Godot signature."),
                    (b'path="res://export_fixture.gdc"' in gd_remap, "Script remap does not target the compiled fixture."),
                    (scene_name.encode("utf-8") in scene_remap, "Scene remap does not target the exported fixture scene."),
                    (b"res://export_fixture.gd" in archive.read(scene_name), "Exported scene does not reference the fixture script."),
                    (b"ExportFixture" in archive.read(scene_name), "Exported scene does not contain the fixture root."),
                    (b"MADO Export Fixture" in archive.read("project.binary"), "Exported project metadata is not the P5 fixture."),
                    (b"res://main.tscn" in archive.read("project.binary"), "Exported project has no fixture main scene."),
                )
                for passed, message in checks:
                    if not passed:
                        failures.append({"id": "release.fixture_contents", "message": message})

            manifest = hashlib.sha256()
            for name in sorted(names):
                data = archive.read(name)
                encoded = name.encode("utf-8")
                manifest.update(len(encoded).to_bytes(4, "big"))
                manifest.update(encoded)
                manifest.update(hashlib.sha256(data).digest())
            evidence["manifest_sha256"] = manifest.hexdigest()
    except (OSError, zipfile.BadZipFile, RuntimeError, KeyError) as exc:
        failures.append({"id": "release.zip_integrity", "message": f"ZIP audit failed: {exc}"})
    return failures, evidence


def run_p5_release(
    *, godot_bin: str | Path, project_path: str | Path, output_path: str | Path,
    preset_name: str = "Windows Desktop", timeout: float = 120.0,
    adapter: Adapter = run_godot_tool,
) -> dict[str, Any]:
    """Export a template-independent ZIP pack and audit its measured contents."""
    if timeout <= 0 or timeout > 600:
        raise ValueError("timeout must be greater than zero and at most 600 seconds")
    started = monotonic()
    project = Path(project_path).resolve()
    artifact = Path(output_path).resolve()
    godot = Path(godot_bin)
    environment: dict[str, Any] = {
        "godot_bin": str(godot), "mode": "pack", "preset_name": preset_name,
        "project_path": str(project),
    }
    if not godot.is_file() or not project.is_dir() or not (project / "project.godot").is_file():
        return _unknown("Required Godot or project evidence is unavailable.", "release.inputs",
                        started=started, environment=environment)

    before = _source_hash(project)
    environment["source_sha256_before"] = before
    try:
        adapted = adapter(
            "export", godot_bin=godot, project_path=project, output_path=artifact,
            preset_name=preset_name, mode="pack", timeout=timeout,
        )
    except (OSError, ValueError) as exc:
        return _unknown(f"Godot export adapter is unavailable: {exc}", "release.adapter",
                        started=started, environment=environment)
    if adapted.get("status") == "UNKNOWN":
        environment["adapter_result"] = adapted
        return _unknown("Godot export evidence is unavailable.", "release.adapter",
                        started=started, environment=environment)
    if adapted.get("status") not in {"PASS", "WARN"} or not artifact.is_file() or artifact.stat().st_size <= 0:
        return _fail("Godot pack export failed or produced no regular artifact.", "release.export",
                     started=started, environment=environment, artifact=artifact, evidence=[adapted])

    failures, audit = _audit_zip(artifact)
    environment.update({
        "zip_manifest_sha256": audit["manifest_sha256"],
        "zip_member_count": audit["member_count"],
        "zip_members": audit["members"],
    })
    after = _source_hash(project)
    environment["source_sha256_after"] = after
    if failures:
        return _fail("Exported Godot ZIP failed release audit.", "release.audit",
                     started=started, environment=environment, artifact=artifact, evidence=failures)
    if after != before:
        return _fail("Godot source tree changed during release proof.", "release.source_hash",
                     started=started, environment=environment, artifact=artifact,
                     evidence=[{"before": before, "after": after}])

    adapter_warnings = list(adapted.get("warnings", ()))
    checks = [
        make_check("release.export", "WARN" if adapter_warnings else "PASS",
                   message=(str(adapter_warnings[0]) if adapter_warnings else "Godot produced a non-empty ZIP pack."),
                   evidence=[adapted]),
        make_check("release.audit", "PASS", message="ZIP integrity, paths, members, and fixture contents passed.", evidence=[audit]),
        make_check("release.source_hash", "PASS", message="Fixture source tree remained unchanged.",
                   evidence=[{"before": before, "after": after}]),
    ]
    return make_result(
        "godot_release_proof", proof_level="P5", task_domains=["RELEASE"],
        summary=f"Exported and audited {audit['member_count']} Godot ZIP members.",
        checks=checks, warnings=adapter_warnings, artifacts=[make_artifact(artifact, "godot-pack")],
        environment=environment, duration_ms=elapsed_ms(started),
    )

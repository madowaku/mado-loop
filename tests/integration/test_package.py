from __future__ import annotations

import hashlib
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PAYLOAD = REPO_ROOT / ".agents" / "skills" / "mado-loop"
PACKAGE_SCRIPT = REPO_ROOT / "scripts" / "package.py"


def validator_path() -> Path:
    explicit = os.environ.get("MADO_SKILL_VALIDATOR")
    if explicit:
        return Path(explicit)
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    return codex_home / "skills" / ".system" / "skill-creator" / "scripts" / "quick_validate.py"

SPEC = importlib.util.spec_from_file_location("mado_package", PACKAGE_SCRIPT)
assert SPEC is not None and SPEC.loader is not None
PACKAGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PACKAGE)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PackageIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="mado-package-")
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def build(self, name: str = "mado-loop.zip", source: Path = PAYLOAD) -> Path:
        output = self.root / name
        evidence = PACKAGE.build_package(source, output)
        self.assertEqual("PASS", evidence["status"])
        self.assertEqual(digest(output), evidence["sha256"])
        return output

    def test_build_succeeds_with_install_ready_root(self) -> None:
        archive = self.build()
        with zipfile.ZipFile(archive) as package:
            names = package.namelist()
        self.assertTrue(names)
        self.assertTrue(all(name.startswith("mado-loop/") for name in names))
        self.assertIn("mado-loop/SKILL.md", names)

    def test_two_builds_are_byte_identical(self) -> None:
        first = self.build("first.zip")
        second = self.build("second.zip")
        self.assertEqual(first.read_bytes(), second.read_bytes())
        self.assertEqual(digest(first), digest(second))

    def test_paths_and_zip_metadata_are_deterministic(self) -> None:
        archive = self.build()
        with zipfile.ZipFile(archive) as package:
            infos = package.infolist()
        names = [info.filename for info in infos]
        self.assertEqual(sorted(names), names)
        self.assertEqual(len(names), len(set(names)))
        for info in infos:
            self.assertNotIn("\\", info.filename)
            self.assertEqual(PACKAGE.FIXED_TIMESTAMP, info.date_time)
            self.assertEqual(3, info.create_system)
            self.assertEqual(PACKAGE.FILE_MODE, info.external_attr >> 16)
            self.assertEqual(zipfile.ZIP_DEFLATED, info.compress_type)
            PACKAGE.audit_member_name(info.filename)

    def test_vendor_payloads_and_licenses_are_present(self) -> None:
        archive = self.build()
        with zipfile.ZipFile(archive) as package:
            names = set(package.namelist())
        required = {
            "mado-loop/vendor/godot-skill/LICENSE",
            "mado-loop/vendor/godot-skill/MANIFEST.sha256",
            "mado-loop/vendor/godot-skill/payload/SKILL.md",
            "mado-loop/vendor/sprite-tools/LICENSE",
            "mado-loop/vendor/sprite-tools/MANIFEST.sha256",
            "mado-loop/vendor/sprite-tools/payload/generate2dsprite.py",
        }
        self.assertTrue(required.issubset(names))

    def test_repo_only_and_generated_files_are_absent(self) -> None:
        copied = self.root / "payload"
        shutil.copytree(PAYLOAD, copied)
        generated = (
            copied / "tests" / "fixture.txt",
            copied / "docs" / "note.md",
            copied / ".github" / "workflow.yml",
            copied / "scripts" / "__pycache__" / "cache.pyc",
            copied / ".godot" / "cache.bin",
            copied / "dist" / "old.bin",
            copied / "old.zip",
        )
        for path in generated:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"generated")
        archive = self.build(source=copied)
        with zipfile.ZipFile(archive) as package:
            names = package.namelist()
        self.assertFalse(any("/tests/" in name for name in names))
        self.assertFalse(any("/docs/" in name for name in names))
        self.assertFalse(any("/.github/" in name for name in names))
        self.assertFalse(any("/__pycache__/" in name for name in names))
        self.assertFalse(any(name.endswith((".pyc", ".zip")) for name in names))
        self.assertFalse(any("/.godot/" in name or "/dist/" in name for name in names))

    def test_archive_cannot_recursively_package_itself(self) -> None:
        copied = self.root / "payload"
        shutil.copytree(PAYLOAD, copied)
        output = copied / "nested" / "mado-loop.zip"
        PACKAGE.build_package(copied, output)
        first_digest = digest(output)
        PACKAGE.build_package(copied, output)
        self.assertEqual(first_digest, digest(output))
        with zipfile.ZipFile(output) as package:
            self.assertFalse(any(name.endswith(".zip") for name in package.namelist()))

    def test_extracted_skill_passes_official_validation(self) -> None:
        archive = self.build()
        extracted = self.root / "extracted"
        with zipfile.ZipFile(archive) as package:
            package.extractall(extracted)
        validator = validator_path()
        self.assertTrue(validator.is_file(), f"required validator missing: {validator}")
        result = subprocess.run(
            [sys.executable, str(validator), str(extracted / "mado-loop")],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("Skill is valid!", result.stdout)

    def test_zip_slip_names_are_rejected(self) -> None:
        for unsafe in (
            "../escape",
            "mado-loop/../escape",
            "/absolute",
            "//server/share",
            r"C:\escape",
            r"mado-loop\escape",
        ):
            with self.subTest(unsafe=unsafe):
                with self.assertRaises(PACKAGE.PackageError):
                    PACKAGE.audit_member_name(unsafe)

    def test_cli_emits_stable_json_evidence(self) -> None:
        output = self.root / "cli.zip"
        result = subprocess.run(
            [
                sys.executable,
                str(PACKAGE_SCRIPT),
                "--source",
                str(PAYLOAD),
                "--output",
                str(output),
                "--json",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn('"status":"PASS"', result.stdout)
        self.assertIn(digest(output), result.stdout)


if __name__ == "__main__":
    unittest.main()

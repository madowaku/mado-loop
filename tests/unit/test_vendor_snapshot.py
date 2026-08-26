from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = REPOSITORY_ROOT / ".agents" / "skills" / "mado-loop"
VENDOR_ROOT = SKILL_ROOT / "vendor" / "godot-skill"
UPDATER = REPOSITORY_ROOT / "scripts" / "update_vendor.py"
PIN = "8e0552b158861020d6a9a12059ce11c4ba8cd303"
EXPECTED_LICENSE_SHA256 = "6533d1d78eb3fe015e914cc6bfa802d3d5d97325c72432506ce9249c74b8bf74"


class VendorSnapshotTests(unittest.TestCase):
    def test_offline_snapshot_and_manifest(self) -> None:
        payload_files = sorted(path for path in (VENDOR_ROOT / "payload").rglob("*") if path.is_file())
        self.assertEqual(69, len(payload_files))

        result = subprocess.run(
            [sys.executable, str(UPDATER), "--check", "--pin", PIN],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        manifest_lines = (VENDOR_ROOT / "MANIFEST.sha256").read_text(encoding="ascii").splitlines()
        self.assertEqual(70, len(manifest_lines))
        self.assertFalse((SKILL_ROOT / "scripts" / "update_vendor.py").exists())

    @unittest.skipUnless(shutil.which("git"), "git is required for live comparison")
    def test_live_comparison_uses_exact_pinned_checkout_bytes(self) -> None:
        spec = importlib.util.spec_from_file_location("mado_update_vendor", UPDATER)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temp_name:
            upstream = Path(temp_name) / "upstream"
            (upstream / "skill").mkdir(parents=True)
            shutil.copytree(VENDOR_ROOT / "payload", upstream / "skill" / "godot")
            shutil.copy2(VENDOR_ROOT / "LICENSE", upstream / "LICENSE")
            subprocess.run(["git", "init", "-q", str(upstream)], check=True)
            subprocess.run(["git", "-C", str(upstream), "add", "."], check=True)
            subprocess.run(
                [
                    "git", "-C", str(upstream), "-c", "user.name=MADO LOOP Test",
                    "-c", "user.email=test@example.invalid", "commit", "-q", "-m", "fixture",
                ],
                check=True,
            )
            fixture_pin = subprocess.run(
                ["git", "-C", str(upstream), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            module.compare_live(str(upstream), fixture_pin, VENDOR_ROOT)

    def test_provenance_and_license(self) -> None:
        provenance = (VENDOR_ROOT / "UPSTREAM.md").read_text(encoding="utf-8")
        self.assertIn("https://github.com/haxqer/godot-skill.git", provenance)
        self.assertIn(PIN, provenance)
        self.assertIn("Acquisition date: 2026-08-25", provenance)
        self.assertIn("Local modifications: none", provenance)

        license_bytes = (VENDOR_ROOT / "LICENSE").read_bytes()
        self.assertEqual(EXPECTED_LICENSE_SHA256, hashlib.sha256(license_bytes).hexdigest())
        self.assertIn(b"MIT License", license_bytes)
        self.assertIn(b"Copyright (c) 2026 Qian Xiao", license_bytes)
        notices = (REPOSITORY_ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
        self.assertIn("MIT License", notices)
        self.assertIn("Copyright (c) 2026 Qian Xiao", notices)

    def test_snapshot_has_no_repository_or_cache_junk(self) -> None:
        forbidden_names = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".DS_Store"}
        junk = [
            path.relative_to(VENDOR_ROOT).as_posix()
            for path in VENDOR_ROOT.rglob("*")
            if path.name in forbidden_names or path.suffix == ".pyc"
        ]
        self.assertEqual([], junk)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = REPOSITORY_ROOT / ".agents" / "skills" / "mado-loop" / "scripts"
sys.path.insert(0, str(SCRIPTS_ROOT))

from common import sprite_processor  # noqa: E402


FIXTURE = REPOSITORY_ROOT / "tests" / "fixtures" / "sprite" / "two-by-two.ppm"
VENDOR_ROOT = REPOSITORY_ROOT / ".agents" / "skills" / "mado-loop" / "vendor" / "sprite-tools"
PROCESSOR_SHA256 = "970895ef904fed5e41f2be1533e00218e64c100ecb0d6c8814c7d2352730581f"
LICENSE_SHA256 = "54c15f9d745197c6d3d8548ddcaf2f2c8863eda64429c85ecfc4c0571ac74f3e"
PIN = "64fd0b57d3f2ae117ef0a95e4c2decc25b4c9dd2"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class SpriteVendorTests(unittest.TestCase):
    def test_exact_narrow_snapshot_manifest_and_notice(self) -> None:
        payload_files = sorted(path for path in (VENDOR_ROOT / "payload").rglob("*") if path.is_file())
        self.assertEqual([VENDOR_ROOT / "payload" / "generate2dsprite.py"], payload_files)
        self.assertEqual(PROCESSOR_SHA256, digest(payload_files[0]))
        self.assertEqual(LICENSE_SHA256, digest(VENDOR_ROOT / "LICENSE"))
        provenance = (VENDOR_ROOT / "UPSTREAM.md").read_text(encoding="utf-8")
        self.assertIn(PIN, provenance)
        self.assertIn("Local modifications: none", provenance)
        self.assertIn("Pillow >= 10", provenance)
        self.assertIn("NumPy >= 1.26", provenance)

        completed = subprocess.run(
            [sys.executable, "scripts/update_vendor.py", "--check", "--vendor", "sprite-tools", "--pin", PIN],
            cwd=REPOSITORY_ROOT, capture_output=True, text=True, check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)

    def test_missing_dependency_is_unknown_without_installation(self) -> None:
        original = sprite_processor.metadata.version

        def version(name: str) -> str:
            if name == "Pillow":
                raise sprite_processor.metadata.PackageNotFoundError
            return original(name)

        with mock.patch.object(sprite_processor.metadata, "version", side_effect=version):
            with tempfile.TemporaryDirectory() as output:
                result = sprite_processor.process_sprite(FIXTURE, output, rows=2, cols=2, cell_size=16)
        self.assertEqual("UNKNOWN", result["status"])
        self.assertTrue(any("Pillow>=10.0" in item for item in result["unknowns"]))


class SpriteProcessorTests(unittest.TestCase):
    def test_split_normalize_anchor_scale_qc_preview_and_atlas_are_deterministic(self) -> None:
        source_before = digest(FIXTURE)
        vendor_before = digest(sprite_processor.PROCESSOR)
        with tempfile.TemporaryDirectory() as temp_name:
            temp = Path(temp_name)
            first = sprite_processor.process_sprite(FIXTURE, temp / "first", rows=2, cols=2, cell_size=16)
            second = sprite_processor.process_sprite(FIXTURE, temp / "second", rows=2, cols=2, cell_size=16)
            self.assertEqual("PASS", first["status"])
            self.assertEqual("PASS", second["status"])
            checks = {item["id"]: item["status"] for item in first["checks"]}
            for check_id in ("frame_split", "shared_anchor", "shared_scale", "qc", "vendor_immutable"):
                self.assertEqual("PASS", checks[check_id])
            for filename in ("sheet-transparent.png", "animation.gif"):
                self.assertEqual(digest(temp / "first" / filename), digest(temp / "second" / filename))
            frame_files = sorted((temp / "first").glob("frame-*.png"))
            self.assertEqual(4, len(frame_files))
            metadata_payload = json.loads((temp / "first" / "pipeline-meta.json").read_text(encoding="utf-8"))
            self.assertTrue(all(frame["scale_changed"] for frame in metadata_payload["frames"]))
            self.assertEqual({(13, 13)}, {tuple(frame["output_size"]) for frame in metadata_payload["frames"]})
            self.assertEqual(0.0, metadata_payload["qc_summary"]["body_scale_cv"])
            self.assertEqual(0.0, metadata_payload["qc_summary"]["anchor_y_std"])
        self.assertEqual(source_before, digest(FIXTURE))
        self.assertEqual(vendor_before, digest(sprite_processor.PROCESSOR))

    def test_unicode_and_space_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name) / "入力 sprite 空間"
            root.mkdir()
            source = root / "絵 シート.ppm"
            source.write_bytes(FIXTURE.read_bytes())
            output = root / "出力 atlas 空間"
            result = sprite_processor.process_sprite(source, output, rows=2, cols=2, cell_size=16)
            self.assertEqual("PASS", result["status"])
            self.assertTrue((output / "sheet-transparent.png").is_file())
            self.assertTrue((output / "animation.gif").is_file())

    def test_cli_emits_schema_v11(self) -> None:
        with tempfile.TemporaryDirectory() as output:
            environment = dict(__import__("os").environ)
            environment["PYTHONPATH"] = str(SCRIPTS_ROOT)
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            completed = subprocess.run(
                [
                    sys.executable, "-m", "common.sprite_processor", str(FIXTURE), output,
                    "--rows", "2", "--cols", "2", "--cell-size", "16",
                ],
                cwd=REPOSITORY_ROOT, env=environment, capture_output=True, text=True, check=False,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual("1.1", payload["schema_version"])
            self.assertEqual(["SPRITE", "PIXEL_ART", "MIXED"], payload["task_domains"])


if __name__ == "__main__":
    unittest.main()

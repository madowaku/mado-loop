from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / ".agents" / "skills" / "mado-loop" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from common.release_proof import run_p5_release  # noqa: E402


class P5IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        configured = os.environ.get("MADO_GODOT_BIN", "")
        if not configured or not Path(configured).is_file():
            raise unittest.SkipTest("MADO_GODOT_BIN is not an available file")
        cls.godot_bin = Path(configured)
        cls.fixture = ROOT / "tests" / "fixtures" / "godot-export"

    def _copied_fixture(self, root: Path, name: str = "fixture") -> Path:
        project = root / name
        shutil.copytree(self.fixture, project)
        return project

    def test_actual_pack_and_audit_pass(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mado-p5-") as temporary:
            root = Path(temporary)
            project = self._copied_fixture(root)
            result = run_p5_release(
                godot_bin=self.godot_bin, project_path=project,
                output_path=root / "build" / "fixture.zip", timeout=60.0,
            )
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual(result["schema_version"], "1.1")
        self.assertEqual(result["proof_level"], "P5")
        self.assertEqual(result["environment"]["zip_member_count"], 7)
        self.assertEqual(result["environment"]["source_sha256_before"], result["environment"]["source_sha256_after"])
        self.assertTrue(result["artifacts"][0]["exists"])
        self.assertGreater(result["artifacts"][0]["size_bytes"], 0)

    def test_stable_rerun_evidence(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mado-p5-stable-") as temporary:
            root = Path(temporary)
            project = self._copied_fixture(root)
            first = run_p5_release(
                godot_bin=self.godot_bin, project_path=project,
                output_path=root / "one" / "fixture.zip", timeout=60.0,
            )
            second = run_p5_release(
                godot_bin=self.godot_bin, project_path=project,
                output_path=root / "two" / "fixture.zip", timeout=60.0,
            )
        self.assertEqual(first["status"], "PASS", first)
        self.assertEqual(second["status"], "PASS", second)
        for key in ("zip_manifest_sha256", "zip_members", "source_sha256_before", "source_sha256_after"):
            self.assertEqual(first["environment"][key], second["environment"][key])

    def test_unicode_space_paths_pass(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mado-p5-unicode-") as temporary:
            root = Path(temporary)
            project = self._copied_fixture(root, "日本語 space/export fixture")
            result = run_p5_release(
                godot_bin=self.godot_bin, project_path=project,
                output_path=root / "出力 space" / "fixture pack.zip", timeout=60.0,
            )
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual(result["environment"]["source_sha256_before"], result["environment"]["source_sha256_after"])

    def test_missing_tool_is_unknown(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mado-p5-unknown-") as temporary:
            result = run_p5_release(
                godot_bin=Path(temporary) / "missing-godot.exe", project_path=self.fixture,
                output_path=Path(temporary) / "fixture.zip", timeout=60.0,
            )
        self.assertEqual(result["status"], "UNKNOWN", result)

    def test_corrupt_export_is_fail(self) -> None:
        def corrupt_adapter(operation: str, **kwargs: object) -> dict[str, object]:
            output = Path(str(kwargs["output_path"]))
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"not a zip")
            return {"status": "PASS", "proof_level": "P5", "operation": operation}

        with tempfile.TemporaryDirectory(prefix="mado-p5-corrupt-") as temporary:
            root = Path(temporary)
            project = self._copied_fixture(root)
            result = run_p5_release(
                godot_bin=self.godot_bin, project_path=project,
                output_path=root / "fixture.zip", adapter=corrupt_adapter,
            )
        self.assertEqual(result["status"], "FAIL", result)
        self.assertEqual(result["checks"][0]["id"], "release.audit")

    def test_actionable_adapter_warning_survives_release_audit(self) -> None:
        def warning_adapter(operation: str, **kwargs: object) -> dict[str, object]:
            from common.godot_tool import run_godot_tool
            result = run_godot_tool(operation, **kwargs)
            if result["status"] == "PASS":
                result["status"] = "WARN"
                result["warnings"] = ["actionable release warning"]
                result["checks"][0]["status"] = "WARN"
            return result

        with tempfile.TemporaryDirectory(prefix="mado-p5-warning-") as temporary:
            root = Path(temporary)
            project = self._copied_fixture(root)
            result = run_p5_release(
                godot_bin=self.godot_bin, project_path=project,
                output_path=root / "fixture.zip", adapter=warning_adapter,
            )
        self.assertEqual(result["status"], "WARN", result)
        self.assertEqual(result["warnings"], ["actionable release warning"])


if __name__ == "__main__":
    unittest.main()

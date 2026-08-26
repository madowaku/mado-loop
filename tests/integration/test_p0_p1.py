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

from common.godot_runner import run_p0_p1  # noqa: E402


class P0P1IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        configured = os.environ.get("MADO_GODOT_BIN", "")
        if not configured or not Path(configured).is_file():
            raise unittest.SkipTest("MADO_GODOT_BIN is not an available file")
        cls.godot_bin = Path(configured)
        cls.fixtures = ROOT / "tests" / "fixtures"

    def run_fixture(self, name: str) -> dict[str, object]:
        return run_p0_p1(
            godot_bin=self.godot_bin,
            project_path=self.fixtures / name,
            validate_timeout=60,
            boot_timeout=30,
        )

    def test_valid_project_passes_p0_and_p1(self) -> None:
        result = self.run_fixture("godot-valid")
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual([check["status"] for check in result["checks"]], ["PASS", "PASS"])
        self.assertTrue(result["environment"]["p1_invoked"])

    def test_parse_error_fails_p0_and_prevents_p1(self) -> None:
        result = self.run_fixture("godot-parse-error")
        self.assertEqual(result["status"], "FAIL", result)
        checks = {check["id"]: check for check in result["checks"]}
        self.assertEqual(checks["godot.p0.validate"]["status"], "FAIL")
        self.assertEqual(checks["godot.p1.boot"]["status"], "SKIPPED")
        self.assertFalse(checks["godot.p1.boot"]["details"]["invoked"])
        self.assertFalse(result["environment"]["p1_invoked"])

    def test_runtime_error_passes_p0_then_fails_p1_with_diagnostic(self) -> None:
        result = self.run_fixture("godot-runtime-error")
        self.assertEqual(result["status"], "FAIL", result)
        checks = {check["id"]: check for check in result["checks"]}
        self.assertEqual(checks["godot.p0.validate"]["status"], "PASS")
        self.assertEqual(checks["godot.p1.boot"]["status"], "FAIL")
        self.assertTrue(result["environment"]["p1_invoked"])
        self.assertIn("MADO_RUNTIME_FIXTURE", str(checks["godot.p1.boot"]["evidence"]))

    def test_unicode_and_space_project_path(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mado-loop-") as temporary:
            copied = Path(temporary) / "Unicode 日本語 space" / "valid project"
            shutil.copytree(self.fixtures / "godot-valid", copied)
            result = run_p0_p1(
                godot_bin=self.godot_bin,
                project_path=copied,
                validate_timeout=60,
                boot_timeout=30,
            )
        self.assertEqual(result["status"], "PASS", result)
        self.assertTrue(result["environment"]["p1_invoked"])


if __name__ == "__main__":
    unittest.main()

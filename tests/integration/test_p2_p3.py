from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / ".agents" / "skills" / "mado-loop" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from common.behavior_proof import run_p3_behavior  # noqa: E402
from common.layout_proof import run_p2_layout  # noqa: E402


class P2P3IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        configured = os.environ.get("MADO_GODOT_BIN", "")
        if not configured or not Path(configured).is_file():
            raise unittest.SkipTest("MADO_GODOT_BIN is not an available file")
        cls.godot_bin = Path(configured)
        cls.fixtures = ROOT / "tests" / "fixtures"

    def test_valid_ui_passes_two_viewports(self) -> None:
        project = self.fixtures / "godot-ui-layout"
        result = run_p2_layout(
            godot_bin=self.godot_bin, project_path=project,
            scenario_paths=[project / "valid_1280.json", project / "valid_800.json"],
        )
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual(result["proof_level"], "P2")
        self.assertEqual(len(result["checks"]), 2)

    def test_broken_ui_measurably_fails(self) -> None:
        project = self.fixtures / "godot-ui-layout"
        result = run_p2_layout(
            godot_bin=self.godot_bin, project_path=project,
            scenario_paths=[project / "broken.json"],
        )
        self.assertEqual(result["status"], "FAIL", result)
        self.assertIn("overlap", str(result["checks"][0]["evidence"]))

    def test_clean_geometry_preserves_adapter_warning(self) -> None:
        payload = {"ui_reports": [{"passed": True}]}
        adapted = {
            "status": "WARN", "warnings": ["actionable layout warning"],
            "checks": [{"evidence": [payload]}],
        }
        with patch("common.layout_proof.run_godot_tool", return_value=adapted):
            result = run_p2_layout(
                godot_bin=self.godot_bin, project_path=self.fixtures / "godot-ui-layout",
                scenario_paths=[Path("warning.json")],
            )
        self.assertEqual(result["status"], "WARN", result)
        self.assertEqual(result["warnings"], ["actionable layout warning"])

    def test_behavior_transition_is_stable_across_runs(self) -> None:
        project = self.fixtures / "godot-behavior"
        scenario = project / "transition.json"
        first = run_p3_behavior(godot_bin=self.godot_bin, project_path=project, scenario_path=scenario)
        second = run_p3_behavior(godot_bin=self.godot_bin, project_path=project, scenario_path=scenario)
        self.assertEqual(first["status"], "PASS", first)
        self.assertEqual(second["status"], "PASS", second)
        self.assertEqual(first["checks"][0]["status"], second["checks"][0]["status"])

    def test_unicode_and_space_copy_passes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mado-p2p3-") as temporary:
            copied = Path(temporary) / "日本語 space" / "behavior fixture"
            shutil.copytree(self.fixtures / "godot-behavior", copied)
            result = run_p3_behavior(
                godot_bin=self.godot_bin, project_path=copied,
                scenario_path=copied / "transition.json",
            )
        self.assertEqual(result["status"], "PASS", result)


if __name__ == "__main__":
    unittest.main()

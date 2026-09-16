from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / ".agents" / "skills" / "mado-loop" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from run_eval_case import run_eval_case  # noqa: E402

CASES = ROOT / ".agents" / "skills" / "mado-loop" / "evals" / "cases"


class MadoEvalsIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        configured = os.environ.get("MADO_GODOT_BIN", "")
        if not configured or not Path(configured).is_file():
            raise unittest.SkipTest("MADO_GODOT_BIN is not an available file")
        cls.godot_bin = Path(configured)

    def test_ui_visible_control_case_passes_p2(self) -> None:
        case_path = CASES / "ui" / "ui.visible-control" / "case.json"
        with tempfile.TemporaryDirectory(prefix="mado-eval-ui-") as temporary:
            result, run_dir = run_eval_case(
                case_path,
                candidate_id="ci-current",
                run_id="integration-ui-001",
                output_root=Path(temporary),
                godot=self.godot_bin,
            )
            self.assertEqual(result["status"], "PASS", result)
            self.assertEqual(result["proof_status"], "PROVEN")
            self.assertEqual(result["proof"][0]["id"], "P2")
            self.assertEqual(result["proof"][0]["status"], "PASS")
            self.assertTrue((run_dir / "workspace" / "fixture" / "project.godot").is_file())
            self.assertTrue((run_dir / "evidence" / "godot-layout.json").is_file())

    def test_gameplay_transition_case_passes_repeatably(self) -> None:
        case_path = CASES / "gameplay" / "gameplay.stable-transition" / "case.json"
        with tempfile.TemporaryDirectory(prefix="mado-eval-gameplay-") as temporary:
            result, run_dir = run_eval_case(
                case_path,
                candidate_id="ci-current",
                run_id="integration-gameplay-001",
                output_root=Path(temporary),
                godot=self.godot_bin,
            )
            self.assertEqual(result["status"], "PASS", result)
            self.assertEqual(result["proof_status"], "PROVEN")
            self.assertEqual(result["proof"][0]["id"], "P3")
            by_id = {item["id"]: item for item in result["acceptance"]}
            self.assertEqual(by_id["gameplay.transition-pass"]["status"], "PASS")
            self.assertEqual(by_id["gameplay.repeatable"]["status"], "PASS")
            self.assertTrue((run_dir / "evidence" / "godot-behavior.json").is_file())


if __name__ == "__main__":
    unittest.main()

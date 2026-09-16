import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).parents[2]
MODULE_PATH = ROOT / ".agents" / "skills" / "mado-loop" / "scripts" / "eval_result.py"
SPEC = importlib.util.spec_from_file_location("eval_result", MODULE_PATH)
evals = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(evals)


class EvalResultTests(unittest.TestCase):
    def manifest(self):
        return {
            "schema_version": "0.1",
            "case_id": "ui.visible-control",
            "case_digest": "sha256:" + "a" * 64,
            "case": {
                "id": "ui.visible-control",
                "required_proof": ["P0", "P2", "P3"],
                "acceptance": [
                    {
                        "id": "ui.quit-visible",
                        "kind": "evidence",
                        "required": True,
                        "description": "QUIT is visible",
                    },
                    {
                        "id": "ui.project-boots",
                        "kind": "invariant",
                        "required": True,
                        "description": "Project still boots",
                    },
                ],
            },
        }

    def test_missing_required_evidence_becomes_unknown(self):
        result = evals.build_eval_result(
            run_id="run:001",
            case_manifest=self.manifest(),
            candidate_id="game-ui@1.5",
            proof_observations={"P0": "PASS"},
            acceptance_observations={"ui.project-boots": "PASS"},
        )
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertEqual(result["proof_status"], "PARTIAL")
        by_proof = {item["id"]: item for item in result["proof"]}
        self.assertEqual(by_proof["P2"]["status"], "UNKNOWN")
        self.assertEqual(by_proof["P3"]["status"], "UNKNOWN")
        by_acceptance = {item["id"]: item for item in result["acceptance"]}
        self.assertEqual(by_acceptance["ui.quit-visible"]["status"], "UNKNOWN")
        self.assertIn("proof:P2:UNKNOWN", result["failure_signatures"])
        self.assertIn("acceptance:ui.quit-visible:UNKNOWN", result["failure_signatures"])

    def test_failed_invariant_forces_failure(self):
        result = evals.build_eval_result(
            run_id="run:002",
            case_manifest=self.manifest(),
            candidate_id="game-ui@1.5",
            proof_observations={"P0": "PASS", "P2": "PASS", "P3": "PASS"},
            acceptance_observations={
                "ui.quit-visible": "PASS",
                "ui.project-boots": "FAIL",
            },
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["proof_status"], "PROVEN")
        self.assertEqual(result["regressions"][0]["status"], "FAIL")
        self.assertIn("regression:ui.project-boots:FAIL", result["failure_signatures"])

    def test_efficiency_metrics_do_not_change_proof_status(self):
        result = evals.build_eval_result(
            run_id="run:003",
            case_manifest=self.manifest(),
            candidate_id="game-ui@1.5",
            proof_observations={"P0": "FAIL", "P2": "PASS", "P3": "PASS"},
            acceptance_observations={
                "ui.quit-visible": "PASS",
                "ui.project-boots": "PASS",
            },
            repair_cycles=0,
            tokens=1,
            wall_time_ms=1,
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["proof_status"], "FAILED")

    def test_evidence_is_sorted_and_hashed_form_is_checked(self):
        result = evals.build_eval_result(
            run_id="run:004",
            case_manifest=self.manifest(),
            candidate_id="game-ui@1.5",
            evidence=[
                {"kind": "screenshot", "path": "evidence/b.png", "sha256": "b" * 64},
                {"kind": "log", "path": "evidence/a.log", "sha256": None},
            ],
        )
        self.assertEqual([item["path"] for item in result["evidence"]], ["evidence/a.log", "evidence/b.png"])
        with self.assertRaisesRegex(ValueError, "sha256"):
            evals.build_eval_result(
                run_id="run:005",
                case_manifest=self.manifest(),
                candidate_id="game-ui@1.5",
                evidence=[{"kind": "log", "path": "a.log", "sha256": "XYZ"}],
            )


if __name__ == "__main__":
    unittest.main()

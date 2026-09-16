from __future__ import annotations

import importlib.util
import json
import platform
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[2]
SCRIPTS = ROOT / ".agents" / "skills" / "mado-loop" / "scripts"
MODULE_PATH = SCRIPTS / "run_eval_case.py"
SPEC = importlib.util.spec_from_file_location("run_eval_case", MODULE_PATH)
runner = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(runner)

CASES = ROOT / ".agents" / "skills" / "mado-loop" / "evals" / "cases"


class EvalRunnerTests(unittest.TestCase):
    def test_builtin_corpus_validates_and_binds_runner(self) -> None:
        case_paths = sorted(CASES.rglob("case.json"))
        self.assertEqual(len(case_paths), 4)
        ids = []
        for case_path in case_paths:
            manifest = runner.load_and_digest_case(case_path)
            config = runner.load_runner_config(case_path, manifest)
            ids.append(manifest["case_id"])
            self.assertIn(config["adapter"], runner.ADAPTERS)
            self.assertIn("runner.json", {item["path"] for item in manifest["files"]})
            self.assertTrue(manifest["case_digest"].startswith("sha256:"))
        self.assertEqual(len(ids), len(set(ids)))

    def test_routing_case_replays_offline_without_live_feedback(self) -> None:
        case_path = CASES / "routing" / "routing.skill-selection" / "case.json"
        with tempfile.TemporaryDirectory(prefix="mado-eval-routing-") as temporary:
            root = Path(temporary)
            result, run_dir = runner.run_eval_case(
                case_path,
                candidate_id="current",
                run_id="unit-routing-001",
                output_root=root,
            )
            self.assertEqual(result["status"], "PASS", result)
            self.assertEqual(result["case_id"], "routing.skill-selection")
            self.assertEqual(result["proof_status"], "UNPROVEN")
            self.assertTrue((run_dir / "result.json").is_file())
            self.assertTrue((run_dir / "evidence" / "skill-router.json").is_file())
            self.assertFalse((root / "skill_feedback.jsonl").exists())
            by_id = {item["id"]: item for item in result["acceptance"]}
            self.assertEqual(by_id["routing.expected-skills"]["status"], "PASS")
            self.assertEqual(by_id["routing.no-unrelated-skills"]["status"], "PASS")
            self.assertEqual(by_id["routing.repeatable"]["status"], "PASS")

    def test_semantic_repeatability_ignores_duration_and_artifact_noise(self) -> None:
        first = {
            "status": "PASS",
            "proof_level": "P3",
            "duration_ms": 10,
            "artifacts": [{"path": "one"}],
            "checks": [{"id": "behavior.transition", "status": "PASS", "required": True}],
        }
        second = {
            "status": "PASS",
            "proof_level": "P3",
            "duration_ms": 999,
            "artifacts": [{"path": "two"}],
            "checks": [{"id": "behavior.transition", "status": "PASS", "required": True}],
        }
        self.assertTrue(runner._stable_results([first, second]))
        second["checks"][0]["status"] = "FAIL"
        self.assertFalse(runner._stable_results([first, second]))

    def test_adapter_error_is_unknown_not_product_fail(self) -> None:
        current = runner.PLATFORM_NAMES.get(platform.system().casefold(), platform.system().casefold())
        with tempfile.TemporaryDirectory(prefix="mado-eval-error-") as temporary:
            root = Path(temporary)
            case_dir = root / "case"
            case_dir.mkdir()
            (case_dir / "task.md").write_text("Observe a bounded external playtest.\n", encoding="utf-8")
            (case_dir / "runner.json").write_text(
                json.dumps({
                    "schema_version": "0.1",
                    "adapter": "external_receipt",
                    "config": {"required_evidence_kinds": ["screenshot"]},
                }),
                encoding="utf-8",
            )
            (case_dir / "case.json").write_text(
                json.dumps({
                    "schema_version": "0.1",
                    "id": "playtest.unit-error",
                    "title": "External receipt failure boundary",
                    "domains": ["PLAYTEST"],
                    "task_file": "task.md",
                    "required_proof": ["P3"],
                    "acceptance": [{
                        "id": "playtest.observed",
                        "kind": "evidence",
                        "required": True,
                        "description": "External observation is supplied."
                    }],
                    "policy": {
                        "sensitivity": "public",
                        "network": "offline",
                        "mutation": "none",
                        "timeout_seconds": 30,
                        "allowed_platforms": [current]
                    },
                    "expected_paths": ["runner.json"]
                }),
                encoding="utf-8",
            )
            result, run_dir = runner.run_eval_case(
                case_dir / "case.json",
                candidate_id="current",
                run_id="unit-error-001",
                output_root=root / "runs",
            )
            self.assertEqual(result["status"], "UNKNOWN", result)
            self.assertNotEqual(result["status"], "FAIL")
            self.assertIn("runner:external_receipt:ERROR", result["failure_signatures"])
            self.assertTrue((run_dir / "evidence" / "runner-error.json").is_file())


if __name__ == "__main__":
    unittest.main()

import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).parents[2]
MODULE_PATH = ROOT / ".agents" / "skills" / "mado-loop" / "scripts" / "compare_eval_results.py"
SPEC = importlib.util.spec_from_file_location("compare_eval_results", MODULE_PATH)
compare = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(compare)


class EvalComparisonTests(unittest.TestCase):
    def result(
        self,
        *,
        candidate,
        proof="PASS",
        acceptance="PASS",
        invariant="PASS",
        repairs=1,
        tokens=100,
        wall=1000,
        digest=None,
    ):
        return {
            "schema_version": "0.1",
            "run_id": f"run:{candidate}",
            "case_id": "ui.visible-control",
            "case_digest": digest or ("sha256:" + "a" * 64),
            "candidate": {"id": candidate, "revision": None, "digest": None},
            "status": "PASS",
            "proof_status": "PROVEN",
            "proof": [
                {"id": "P2", "status": proof, "required": True, "evidence": [], "detail": None},
            ],
            "acceptance": [
                {"id": "ui.quit-visible", "status": acceptance, "required": True, "evidence": [], "detail": None},
                {"id": "ui.project-boots", "status": invariant, "required": True, "evidence": [], "detail": None},
            ],
            "regressions": [
                {"id": "ui.project-boots", "status": invariant, "required": True, "evidence": [], "detail": None},
            ],
            "metrics": {"repair_cycles": repairs, "tokens": tokens, "wall_time_ms": wall},
            "failure_signatures": [],
            "evidence": [],
            "environment": {},
        }

    def test_hard_gate_regression_rejects_even_when_cheaper(self):
        champion = self.result(candidate="champion", proof="PASS", tokens=1000, wall=10000)
        challenger = self.result(candidate="challenger", proof="FAIL", tokens=1, wall=1)
        comparison = compare.compare_results(champion, challenger)
        self.assertEqual(comparison["verdict"], "REJECT")
        self.assertEqual(comparison["reason"], "hard_gate_regression")

    def test_hard_gate_improvement_can_be_promotion_candidate(self):
        champion = self.result(candidate="champion", acceptance="UNKNOWN")
        challenger = self.result(candidate="challenger", acceptance="PASS")
        comparison = compare.compare_results(champion, challenger)
        self.assertEqual(comparison["verdict"], "PROMOTE_CANDIDATE")
        self.assertEqual(comparison["reason"], "hard_gate_improvement_without_regression")

    def test_equal_gates_lower_repairs_can_promote(self):
        champion = self.result(candidate="champion", repairs=3, tokens=100, wall=1000)
        challenger = self.result(candidate="challenger", repairs=1, tokens=100, wall=1000)
        comparison = compare.compare_results(champion, challenger)
        self.assertEqual(comparison["verdict"], "PROMOTE_CANDIDATE")
        self.assertEqual(comparison["reason"], "stability_improvement")

    def test_equal_gates_efficiency_improvement_is_only_used_after_stability(self):
        champion = self.result(candidate="champion", repairs=1, tokens=200, wall=2000)
        challenger = self.result(candidate="challenger", repairs=1, tokens=100, wall=1000)
        comparison = compare.compare_results(champion, challenger)
        self.assertEqual(comparison["verdict"], "PROMOTE_CANDIDATE")
        self.assertEqual(comparison["reason"], "efficiency_improvement_after_equal_gates")

    def test_mixed_efficiency_holds(self):
        champion = self.result(candidate="champion", tokens=100, wall=2000)
        challenger = self.result(candidate="challenger", tokens=80, wall=3000)
        comparison = compare.compare_results(champion, challenger)
        self.assertEqual(comparison["verdict"], "HOLD")
        self.assertEqual(comparison["reason"], "mixed_efficiency")

    def test_case_digest_mismatch_is_unknown_not_comparable(self):
        champion = self.result(candidate="champion", digest="sha256:" + "a" * 64)
        challenger = self.result(candidate="challenger", digest="sha256:" + "b" * 64)
        comparison = compare.compare_results(champion, challenger)
        self.assertEqual(comparison["verdict"], "UNKNOWN")
        self.assertEqual(comparison["reason"], "case_digest_mismatch")


if __name__ == "__main__":
    unittest.main()

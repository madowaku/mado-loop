import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).parents[2]
MODULE_PATH = ROOT / ".agents" / "skills" / "mado-loop" / "scripts" / "classify_proof.py"
SPEC = importlib.util.spec_from_file_location("mado_classify_proof", MODULE_PATH)
classifier = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(classifier)


class ClassifyProofTests(unittest.TestCase):
    def test_each_level_and_prerequisite_ladder(self):
        cases = {
            "Check syntax and imports": "P0",
            "Confirm boot without runtime errors": "P1",
            "Inspect the HUD layout": "P2",
            "Verify deterministic player movement": "P3",
            "Capture the animation over time": "P4",
            "Audit the release export artifact": "P5",
        }
        for claim, expected in cases.items():
            with self.subTest(claim=claim):
                payload = classifier.classify_proof(claim)
                self.assertEqual(payload["proof_level"], expected)
                index = classifier.PROOF_LEVELS.index(expected)
                self.assertEqual(
                    payload["checks"][0]["details"]["recommended_ladder"],
                    list(classifier.PROOF_LEVELS[: index + 1]),
                )
                self.assertIn("no proof step was executed", payload["checks"][0]["message"])

    def test_highest_requirement_wins_and_order_is_stable(self):
        first = classifier.classify_proof(
            "Inspect UI then capture motion", task_domains=["ANIMATION", "UI", "UI"]
        )
        second = classifier.classify_proof(
            "Inspect UI then capture motion", task_domains=["UI", "ANIMATION"]
        )
        self.assertEqual(first["proof_level"], "P4")
        self.assertEqual(first["task_domains"], ["UI", "ANIMATION", "MIXED"])
        self.assertEqual(classifier.result_json(first), classifier.result_json(second))

    def test_requested_proof_can_raise_but_not_lower_requirement(self):
        self.assertEqual(
            classifier.classify_proof("release export", requested_proof="P1")["proof_level"],
            "P5",
        )
        self.assertEqual(
            classifier.classify_proof("syntax", requested_proof="P3")["proof_level"],
            "P3",
        )

    def test_domain_can_supply_required_context(self):
        payload = classifier.classify_proof("Validate this change", task_domains=["GAMEPLAY"])
        self.assertEqual(payload["proof_level"], "P3")
        self.assertEqual(payload["status"], "PASS")

    def test_ambiguity_is_unknown(self):
        payload = classifier.classify_proof("Make it better somehow")
        self.assertEqual(payload["status"], "UNKNOWN")
        self.assertEqual(payload["task_domains"], [])
        self.assertEqual(payload["unknowns"][0]["id"], "proof.insufficient_claim_context")

    def test_explicit_whole_operation_not_applicable(self):
        payload = classifier.classify_proof("not requested", not_applicable=True)
        self.assertEqual(payload["status"], "SKIPPED")
        self.assertEqual(payload["checks"], [])

    def test_unicode_space_path_cli_and_serialization(self):
        completed = subprocess.run(
            [sys.executable, str(MODULE_PATH), "画面 素材/UI レイアウト", "を確認", "--domain", "UI"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(completed.returncode, 0)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["proof_level"], "P2")
        self.assertIn("画面", "画面 素材/UI レイアウト")
        self.assertEqual(classifier.result_json(payload), completed.stdout)

    def test_cli_unknown_skipped_and_usage_codes(self):
        unknown = subprocess.run(
            [sys.executable, str(MODULE_PATH), "vague"], capture_output=True, text=True, encoding="utf-8"
        )
        skipped = subprocess.run(
            [sys.executable, str(MODULE_PATH), "unused", "--not-applicable"], capture_output=True, text=True, encoding="utf-8"
        )
        usage = subprocess.run(
            [sys.executable, str(MODULE_PATH)], capture_output=True, text=True, encoding="utf-8"
        )
        self.assertEqual(unknown.returncode, 2)
        self.assertEqual(skipped.returncode, 3)
        self.assertEqual(usage.returncode, 64)


if __name__ == "__main__":
    unittest.main()

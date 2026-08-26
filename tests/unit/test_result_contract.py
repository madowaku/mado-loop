import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


MODULE_PATH = (
    Path(__file__).parents[2]
    / ".agents" / "skills" / "mado-loop" / "scripts" / "common" / "result.py"
)
SPEC = importlib.util.spec_from_file_location("mado_result", MODULE_PATH)
result = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(result)


class ResultContractTests(unittest.TestCase):
    def test_result_schema_and_deterministic_ordering(self):
        checks = [
            result.make_check("z", "PASS", details={"b": 2, "a": 1}),
            result.make_check("a", "PASS"),
        ]
        payload = result.make_result(
            "test-tool", proof_level="P2", summary="ok", checks=checks,
            task_domains=["UI", "CODE", "UI"],
            environment={"z": 1, "a": 2}, duration_ms=12,
        )
        self.assertEqual(tuple(payload), result.RESULT_KEYS)
        self.assertEqual(tuple(payload["checks"][0]), result.CHECK_KEYS)
        self.assertEqual([item["id"] for item in payload["checks"]], ["a", "z"])
        self.assertEqual(list(payload["environment"]), ["a", "z"])
        self.assertEqual(payload["task_domains"], ["CODE", "UI", "MIXED"])
        self.assertEqual(json.loads(result.result_json(payload)), payload)

    def test_task_domain_validation_and_domain_neutral_results(self):
        self.assertEqual(result.canonical_task_domains(["SPRITE", "CODE", "SPRITE"]),
                         ["CODE", "SPRITE", "MIXED"])
        self.assertEqual(result.canonical_task_domains([], domain_neutral=True), [])
        for domains in (["MIXED"], ["CODE", "MIXED"], ["MIXED", "MIXED"]):
            with self.subTest(domains=domains), self.assertRaises(ValueError):
                result.canonical_task_domains(domains)
        with self.assertRaises(ValueError):
            result.canonical_task_domains([])
        with self.assertRaises(ValueError):
            result.canonical_task_domains(["CODE"], domain_neutral=True)

    def test_aggregate_precedence(self):
        check = result.make_check
        cases = [
            ([check("x", "FAIL")], (), "FAIL"),
            ([check("x", "SKIPPED")], (), "UNKNOWN"),
            ([check("x", "UNKNOWN")], (), "UNKNOWN"),
            ([check("x", "FAIL", required=False)], (), "WARN"),
            ([check("x", "WARN")], (), "WARN"),
            ([check("x", "PASS")], ("notice",), "WARN"),
            ([check("x", "PASS")], (), "PASS"),
        ]
        for checks, warnings, expected in cases:
            with self.subTest(expected=expected, checks=checks):
                self.assertEqual(result.aggregate_status(checks, warnings=warnings), expected)

        self.assertEqual(
            result.aggregate_status([check("x", "FAIL")], unknowns=["unresolved"]), "FAIL"
        )
        self.assertEqual(
            result.aggregate_status([check("x", "PASS")], unknowns=["unresolved"]), "UNKNOWN"
        )
        self.assertEqual(result.aggregate_status([check("x", "SKIPPED")]), "UNKNOWN")
        self.assertEqual(
            result.aggregate_status([check("x", "SKIPPED", required=False)]), "WARN"
        )

    def test_top_level_skipped_requires_explicit_whole_operation_marker(self):
        payload = result.make_result(
            "not-requested", proof_level=None, summary="not requested",
            task_domains=["PLAYTEST"], status="SKIPPED", operation_skipped=True,
        )
        self.assertEqual(payload["status"], "SKIPPED")
        with self.assertRaises(ValueError):
            result.make_result(
                "x", proof_level=None, summary="x", task_domains=["CODE"], status="SKIPPED"
            )

    def test_artifact_fields_and_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "proof.txt"
            path.write_bytes(b"proof")
            artifact = result.make_artifact(path, "log")
            self.assertEqual(tuple(artifact), result.ARTIFACT_KEYS)
            self.assertTrue(artifact["exists"])
            self.assertEqual(artifact["size_bytes"], 5)
            self.assertEqual(len(artifact["sha256"]), 64)

    def test_enums_and_exit_codes(self):
        self.assertEqual(
            {status: result.exit_code_for_status(status) for status in result.STATUSES},
            {"PASS": 0, "FAIL": 1, "WARN": 0, "UNKNOWN": 2, "SKIPPED": 3},
        )
        self.assertEqual(result.EXIT_USAGE_CONFIG, 64)
        self.assertEqual(result.EXIT_INTERNAL, 70)
        with self.assertRaises(ValueError):
            result.make_check("x", "BROKEN")
        with self.assertRaises(ValueError):
            result.make_result("x", proof_level="P9", summary="x", task_domains=["CODE"])

    def test_explicit_status_must_match_aggregate(self):
        with self.assertRaises(ValueError):
            result.make_result(
                "x", proof_level=None, summary="x", task_domains=["CODE"], status="FAIL"
            )


if __name__ == "__main__":
    unittest.main()

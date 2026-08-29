from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = ROOT / ".agents" / "skills" / "mado-loop" / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import nvidia_fleet_benchmark as benchmark  # noqa: E402


NVIDIA_ENV = {"NVIDIA_API_KEY": "test-nvidia-key"}


class NvidiaFleetBenchmarkTests(unittest.TestCase):
    def fake_caller(
        self,
        selected,
        *,
        prompt,
        system,
        max_tokens,
        temperature,
        timeout,
        env,
        workload,
    ):
        del prompt, system, max_tokens, temperature, timeout, env
        payloads = {
            "architect": {
                "boundaries": ["UI owns presentation"],
                "invariants": ["pause input remains stable"],
                "risks": ["settings persistence drift"],
                "plan": ["separate settings state from menu view"],
            },
            "implementer": {
                "files": ["pause_menu.gd"],
                "changes": ["wire settings panel through existing menu state"],
                "assumptions": ["audio bus already exists"],
                "checks": ["preserve pause toggle behavior"],
            },
            "test_writer": {
                "tests": ["toggle pause and settings repeatedly"],
                "edge_cases": ["fullscreen switch while paused"],
                "proof_gates": ["P2 scene wiring", "P3 interaction"],
                "failure_conditions": ["input remains captured after close"],
            },
            "reviewer": {
                "agreements": ["all proposals preserve current input flow"],
                "contradictions": ["none material"],
                "reject": ["unbounded settings refactor"],
                "verify_next": ["inspect persistence owner before mutation"],
                "quality_scores": {
                    "architect": 91,
                    "implementer": 88,
                    "test_writer": 94,
                },
            },
        }
        return {
            "provider": selected.public_dict(),
            "content": json.dumps(payloads[workload]),
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
                "completion_tokens_details": {"reasoning_tokens": 20},
            },
            "request_profile": {"name": f"fake-{workload}"},
        }

    def test_full_fleet_runs_in_role_order_and_reports_scores(self) -> None:
        report = benchmark.run_benchmark(env=NVIDIA_ENV, caller=self.fake_caller)
        self.assertEqual(report["status"], "PASS")
        results = report["results"]
        self.assertEqual(
            [item["role"] for item in results],
            ["architect", "implementer", "test_writer", "reviewer"],
        )
        self.assertEqual(
            [item["model"] for item in results],
            [
                "moonshotai/kimi-k3",
                "deepseek-ai/deepseek-v4-pro-0813",
                "nvidia/nemotron-3.5-lightning-30b-a3b",
                "nvidia/nemotron-3-ultra-550b-a55b",
            ],
        )
        self.assertTrue(all(item["contract_score"] == 100 for item in results))
        by_role = {item["role"]: item for item in results}
        self.assertEqual(by_role["architect"]["reviewer_quality_score"], 91)
        self.assertEqual(by_role["implementer"]["reviewer_quality_score"], 88)
        self.assertEqual(by_role["test_writer"]["reviewer_quality_score"], 94)
        self.assertIsNone(by_role["reviewer"]["reviewer_quality_score"])
        self.assertEqual(report["summary"]["highest_reviewer_quality_role"], "test_writer")
        self.assertEqual(report["summary"]["highest_reviewer_quality_model"], "nvidia/nemotron-3.5-lightning-30b-a3b")
        self.assertEqual(report["summary"]["proof_status"], "UNPROVEN")

    def test_usage_metrics_include_reasoning_and_rate(self) -> None:
        report = benchmark.run_benchmark(env=NVIDIA_ENV, caller=self.fake_caller)
        for item in report["results"]:
            usage = item["usage"]
            self.assertEqual(usage["prompt_tokens"], 100)
            self.assertEqual(usage["completion_tokens"], 50)
            self.assertEqual(usage["reasoning_tokens"], 20)
            self.assertEqual(usage["total_tokens"], 150)
            if item["duration_ms"] > 0:
                self.assertIsInstance(usage["completion_tokens_per_second"], float)
            else:
                self.assertIsNone(usage["completion_tokens_per_second"])

    def test_secret_is_never_exposed(self) -> None:
        report = benchmark.run_benchmark(env=NVIDIA_ENV, caller=self.fake_caller)
        serialized = json.dumps(report)
        self.assertNotIn("test-nvidia-key", serialized)
        self.assertNotIn('"api_key"', serialized)

    def test_markdown_report_contains_all_models_and_caveat(self) -> None:
        report = benchmark.run_benchmark(env=NVIDIA_ENV, caller=self.fake_caller)
        text = benchmark.markdown_report(report)
        for model in benchmark.ROLE_MODELS.values():
            self.assertIn(model, text)
        self.assertIn("model-graded", text)
        self.assertIn("UNPROVEN", text)

    def test_contract_score_penalizes_invalid_json(self) -> None:
        score, parsed = benchmark._contract_score("architect", "boundaries only")
        self.assertLess(score, 100)
        self.assertIsNone(parsed)

    def test_requires_nvidia_key(self) -> None:
        with self.assertRaisesRegex(Exception, "NVIDIA fleet requires"):
            benchmark.run_benchmark(env={}, caller=self.fake_caller)


if __name__ == "__main__":
    unittest.main()

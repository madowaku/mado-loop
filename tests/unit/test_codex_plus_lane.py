from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = ROOT / ".agents" / "skills" / "mado-loop" / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import codex_plus_lane as lane  # noqa: E402


class CodexPlusLaneTests(unittest.TestCase):
    def test_default_roles_keep_sol_parent_and_luna_workers(self) -> None:
        architect = lane.choose_profile("architect")
        implementer = lane.choose_profile("implementer")
        tester = lane.choose_profile("test_writer")
        reviewer = lane.choose_profile("reviewer")

        self.assertEqual((architect.model, architect.effort, architect.owner), (lane.SOL_MODEL, "medium", "parent"))
        self.assertEqual((implementer.model, implementer.effort, implementer.owner), (lane.LUNA_MODEL, "xhigh", "spawn"))
        self.assertEqual((tester.model, tester.effort, tester.owner), (lane.LUNA_MODEL, "high", "spawn"))
        self.assertEqual((reviewer.model, reviewer.effort, reviewer.owner), (lane.SOL_MODEL, "medium", "parent"))

    def test_budget_pressure_downshifts_luna(self) -> None:
        self.assertEqual(lane.choose_profile("implementer", budget_mode="conserve").effort, "high")
        self.assertEqual(lane.choose_profile("test_writer", budget_mode="critical").effort, "medium")
        self.assertEqual(lane.choose_profile("ui_specialist", budget_mode="critical").effort, "high")

    def test_luna_max_is_explicit_only(self) -> None:
        self.assertEqual(lane.choose_profile("bounded_retry").effort, "xhigh")
        self.assertEqual(lane.choose_profile("bounded_retry", allow_max=True).effort, "max")

    def test_critical_mode_rejects_spawned_sol(self) -> None:
        with self.assertRaisesRegex(lane.CodexPlusConfigError, "forbids spawned Sol"):
            lane.choose_profile("architect", budget_mode="critical", spawn_parent_role=True)

    def test_credit_estimate_applies_cached_discount(self) -> None:
        usage = lane.Usage(input_tokens=1_000_000, cached_input_tokens=500_000, output_tokens=100_000)
        credits = lane.estimate_credits(lane.LUNA_MODEL, usage)
        self.assertEqual(credits, 5.75)

    def test_parse_codex_jsonl_extracts_final_message_and_usage(self) -> None:
        stream = "\n".join(
            [
                json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "first"}}),
                json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "final"}}),
                json.dumps({
                    "type": "turn.completed",
                    "usage": {
                        "input_tokens": 100,
                        "cached_input_tokens": 20,
                        "output_tokens": 40,
                        "reasoning_output_tokens": 15,
                    },
                }),
            ]
        )
        content, usage = lane.parse_codex_jsonl(stream)
        self.assertEqual(content, "final")
        self.assertEqual(usage, lane.Usage(100, 20, 40, 15))

    def test_command_uses_existing_codex_auth_and_read_only_ephemeral_exec(self) -> None:
        profile = lane.choose_profile("implementer")
        command = lane.build_codex_command(profile, cwd=Path("C:/repo"), codex_bin="codex")
        joined = " ".join(command)
        self.assertIn("exec", command)
        self.assertIn("--json", command)
        self.assertIn("--ephemeral", command)
        self.assertIn("--ignore-user-config", command)
        self.assertIn("--sandbox read-only", joined)
        self.assertIn("--model gpt-5.6-luna", joined)
        self.assertIn('model_reasoning_effort="xhigh"', command)
        self.assertEqual(command[-1], "-")
        self.assertNotIn("api", joined.casefold())

    def test_budget_summary_switches_modes_when_user_guardrail_is_configured(self) -> None:
        now = datetime(2026, 8, 29, tzinfo=timezone.utc)
        rows = [
            {
                "schema_version": lane.LEDGER_VERSION,
                "timestamp": (now - timedelta(hours=2)).isoformat(),
                "model": lane.LUNA_MODEL,
                "estimated_credits": 20.0,
            }
        ]
        conserve = lane.budget_summary(ledger=rows, weekly_budget_credits=140.0, now=now)
        self.assertEqual(conserve["mode"], "conserve")

        rows[0]["estimated_credits"] = 35.0
        critical = lane.budget_summary(ledger=rows, weekly_budget_credits=140.0, now=now)
        self.assertEqual(critical["mode"], "critical")

    def test_ledger_never_persists_content_or_credentials(self) -> None:
        result = lane.CodexCallResult(
            status="PASS",
            role="implementer",
            model=lane.LUNA_MODEL,
            effort="xhigh",
            duration_ms=10,
            content="secret prompt echo",
            usage=lane.Usage(100, 0, 20, 10),
            estimated_credits=0.001,
            error=None,
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "usage.jsonl"
            lane.append_ledger(path, result, now=datetime(2026, 8, 29, tzinfo=timezone.utc))
            text = path.read_text(encoding="utf-8")
        self.assertNotIn("secret prompt echo", text)
        self.assertNotIn("api_key", text)

    def test_secret_plan_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(lane.CodexPlusConfigError, "secret tasks"):
                lane._plan(
                    role="implementer",
                    sensitivity="secret",
                    ledger_path=Path(tmp) / "usage.jsonl",
                    weekly_budget_credits=None,
                    allow_max=False,
                    spawn_parent_role=False,
                    env={},
                )


if __name__ == "__main__":
    unittest.main()

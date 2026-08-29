from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = ROOT / ".agents" / "skills" / "mado-loop" / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import codex_plus_budget as budget  # noqa: E402
import codex_plus_lane as lane  # noqa: E402
import codex_plus_swarm as swarm  # noqa: E402


class CodexPlusSwarmTests(unittest.TestCase):
    def test_code_task_spawns_luna_implementer_and_test_writer_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan = swarm.plan_swarm(
                task="codeを実装してテストも追加して",
                ledger_path=Path(tmp) / "usage.jsonl",
                status_path=Path(tmp) / "status.json",
                env={},
            )
        roles = [item["role"] for item in plan["assignments"]]
        self.assertEqual(roles, ["implementer", "test_writer"])
        self.assertTrue(all(item["model"] == lane.LUNA_MODEL for item in plan["assignments"]))
        self.assertEqual(plan["assignments"][0]["effort"], "xhigh")
        self.assertEqual(plan["assignments"][1]["effort"], "high")
        self.assertFalse(plan["max_is_automatic"])
        self.assertEqual(plan["parent"]["model"], lane.SOL_MODEL)
        self.assertIn("reviewer", plan["parent"]["responsibilities"])
        self.assertEqual(plan["max_spawned_workers"], 2)

    def test_complex_ui_keeps_architect_and_review_with_sol_parent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan = swarm.plan_swarm(
                task="HUD UI architectureを整理して実装と検証まで設計して",
                ledger_path=Path(tmp) / "usage.jsonl",
                status_path=Path(tmp) / "status.json",
                env={},
            )
        roles = [item["role"] for item in plan["assignments"]]
        self.assertEqual(roles, ["ui_specialist", "implementer"])
        self.assertIn("architect", plan["parent"]["responsibilities"])
        self.assertIn("reviewer", plan["parent"]["responsibilities"])
        self.assertNotIn("architect", roles)

    def test_release_prefers_release_auditor_over_generic_test_when_only_one_slot(self) -> None:
        roles, _, _, _ = __import__("adaptive_swarm").choose_roles(
            "release packagingとproofを監査して", ("RELEASE",)
        )
        selected = swarm._select_spawn_roles(roles, domains=("RELEASE",), max_spawned=1)
        self.assertEqual(selected, ("release_auditor",))

    def test_legacy_local_guardrail_is_fallback_when_status_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "usage.jsonl"
            result = lane.CodexCallResult(
                "PASS", "implementer", lane.LUNA_MODEL, "xhigh", 1, "x", lane.Usage(), 20.0, None
            )
            lane.append_ledger(ledger, result)
            plan = swarm.plan_swarm(
                task="codeを実装してテストも追加して",
                ledger_path=ledger,
                status_path=Path(tmp) / "status.json",
                weekly_budget_credits=140.0,
                env={},
            )
        self.assertEqual(plan["budget"]["mode_source"], "local-ledger-fallback")
        self.assertEqual(plan["budget"]["mode"], "conserve")
        self.assertEqual(plan["max_spawned_workers"], 1)
        self.assertEqual(plan["assignments"][0]["effort"], "high")

    def test_calibrated_account_status_overrides_legacy_weekly_guardrail(self) -> None:
        start = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            status_path = Path(tmp) / "status.json"
            first = budget.make_observation(remaining_percent=80, hours_until_reset=48, now=start)
            second = budget.make_observation(
                remaining_percent=79,
                hours_until_reset=44,
                now=start + timedelta(hours=4),
            )
            budget.save_observation(status_path, first)
            budget.save_observation(status_path, second)

            ledger = Path(tmp) / "usage.jsonl"
            result = lane.CodexCallResult(
                "PASS", "implementer", lane.LUNA_MODEL, "xhigh", 1, "x", lane.Usage(), 20.0, None
            )
            lane.append_ledger(ledger, result)
            plan = swarm.plan_swarm(
                task="codeを実装してテストも追加して",
                ledger_path=ledger,
                status_path=status_path,
                weekly_budget_credits=20.0,
                env={},
            )
        self.assertEqual(plan["budget"]["mode_source"], "account-status-reset-controller")
        self.assertEqual(plan["budget"]["mode"], "normal")
        self.assertEqual(plan["budget"]["burn_state"], "aggressive")

    def test_low_burn_headroom_promotes_xhigh_roles_to_max(self) -> None:
        start = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            status_path = Path(tmp) / "status.json"
            budget.save_observation(
                status_path,
                budget.make_observation(remaining_percent=80, hours_until_reset=48, now=start),
            )
            budget.save_observation(
                status_path,
                budget.make_observation(
                    remaining_percent=79,
                    hours_until_reset=44,
                    now=start + timedelta(hours=4),
                ),
            )
            plan = swarm.plan_swarm(
                task="codeを実装してテストも追加して",
                ledger_path=Path(tmp) / "usage.jsonl",
                status_path=status_path,
                env={},
            )
        self.assertEqual(plan["budget"]["burn_state"], "aggressive")
        self.assertTrue(plan["max_is_automatic"])
        self.assertEqual(plan["assignments"][0]["role"], "implementer")
        self.assertEqual(plan["assignments"][0]["effort"], "max")
        self.assertEqual(plan["assignments"][1]["role"], "test_writer")
        self.assertEqual(plan["assignments"][1]["effort"], "high")

    def test_fast_burn_forces_critical_and_downshifts(self) -> None:
        start = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            status_path = Path(tmp) / "status.json"
            budget.save_observation(
                status_path,
                budget.make_observation(remaining_percent=40, hours_until_reset=48, now=start),
            )
            budget.save_observation(
                status_path,
                budget.make_observation(
                    remaining_percent=30,
                    hours_until_reset=44,
                    now=start + timedelta(hours=4),
                ),
            )
            plan = swarm.plan_swarm(
                task="codeを実装してテストも追加して",
                ledger_path=Path(tmp) / "usage.jsonl",
                status_path=status_path,
                env={},
            )
        self.assertEqual(plan["budget"]["mode"], "critical")
        self.assertEqual(plan["max_spawned_workers"], 1)
        self.assertFalse(plan["max_is_automatic"])
        self.assertEqual(plan["assignments"][0]["effort"], "high")

    def test_run_preserves_order_without_status_and_does_not_invent_max(self) -> None:
        seen: list[tuple[str, str, str]] = []

        def fake_caller(profile, *, prompt, cwd, timeout):
            del prompt, cwd, timeout
            seen.append((profile.role, profile.model, profile.effort))
            return lane.CodexCallResult(
                "PASS",
                profile.role,
                profile.model,
                profile.effort,
                5,
                f"proposal:{profile.role}",
                lane.Usage(100, 20, 40, 10),
                lane.estimate_credits(profile.model, lane.Usage(100, 20, 40, 10)),
                None,
            )

        with tempfile.TemporaryDirectory() as tmp:
            result = swarm.run_swarm(
                task="codeを実装してテストも追加して",
                cwd=Path(tmp),
                ledger_path=Path(tmp) / "usage.jsonl",
                status_path=Path(tmp) / "status.json",
                env={},
                caller=fake_caller,
            )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual([item["role"] for item in result["results"]], ["implementer", "test_writer"])
        self.assertTrue(all(effort != "max" for _, _, effort in seen))
        self.assertFalse(result["parent_handoff"]["automatic_luna_max"])
        self.assertFalse(result["parent_handoff"]["automatic_retry"])
        self.assertEqual(result["proof_status"], "UNPROVEN")

    def test_secret_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(swarm.CodexPlusSwarmConfigError, "local-only"):
                swarm.plan_swarm(
                    task="secret codeを確認して",
                    sensitivity="secret",
                    ledger_path=Path(tmp) / "usage.jsonl",
                    status_path=Path(tmp) / "status.json",
                    env={},
                )


if __name__ == "__main__":
    unittest.main()

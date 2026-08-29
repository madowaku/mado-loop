from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = ROOT / ".agents" / "skills" / "mado-loop" / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import budget_governor_v2 as governor  # noqa: E402
import codex_plus_lane as plus_lane  # noqa: E402


class BudgetGovernorV2Tests(unittest.TestCase):
    def _paths(self, root: str) -> tuple[Path, Path, Path]:
        base = Path(root)
        return base / "plus.jsonl", base / "status.json", base / "governor.jsonl"

    def test_normal_code_task_uses_nvidia_for_implementation_and_hy3_for_tests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger, status, _ = self._paths(tmp)
            plan = governor.plan_governor(
                task="codeを実装してテストも追加して",
                sensitivity="public",
                ledger_path=ledger,
                status_path=status,
                env={"OPENROUTER_API_KEY": "or", "NVIDIA_API_KEY": "nv"},
                codex_available=True,
                now=datetime(2026, 8, 29, tzinfo=timezone.utc),
            )
        by_role = {item["role"]: item for item in plan["assignments"]}
        self.assertEqual(by_role["implementer"]["selected"]["lane"], "nvidia-fleet")
        self.assertEqual(by_role["test_writer"]["selected"]["lane"], "openrouter-hy3-free")
        self.assertEqual(by_role["test_writer"]["selected"]["model"], governor.HY3_FREE_MODEL)
        self.assertFalse(plan["paid_api_fallback_enabled"])

    def test_critical_mode_prefers_hy3_before_nvidia_and_plus(self) -> None:
        availability = governor.LaneAvailability(True, True, False, True, True, False)
        lanes = governor._ordered_lane_names(
            "implementer",
            mode="critical",
            burn_state="critical",
            availability=availability,
        )
        self.assertEqual(
            lanes,
            ("openrouter-hy3-free", "nvidia-fleet", "local", "codex-plus-luna"),
        )

    def test_private_nvidia_requires_existing_explicit_opt_in(self) -> None:
        env = {"OPENROUTER_API_KEY": "or", "NVIDIA_API_KEY": "nv"}
        without = governor.detect_availability(
            sensitivity="private", env=env, codex_available=True
        )
        with_opt_in = governor.detect_availability(
            sensitivity="private", env=env, codex_available=True, allow_nvidia_private=True
        )
        self.assertFalse(without.nvidia)
        self.assertTrue(with_opt_in.nvidia)
        self.assertTrue(without.openrouter_hy3)

    def test_secret_is_local_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger, status, _ = self._paths(tmp)
            plan = governor.plan_governor(
                task="secret codeを実装してテストして",
                sensitivity="secret",
                ledger_path=ledger,
                status_path=status,
                env={
                    "OPENROUTER_API_KEY": "or",
                    "NVIDIA_API_KEY": "nv",
                    "MADO_LOCAL_BASE_URL": "http://127.0.0.1:8000/v1",
                    "MADO_LOCAL_MODEL": "local-test",
                },
                codex_available=True,
            )
        self.assertTrue(plan["assignments"])
        self.assertTrue(all(item["selected"]["lane"] == "local" for item in plan["assignments"]))
        self.assertFalse(plan["availability"]["openrouter_hy3"])
        self.assertFalse(plan["availability"]["nvidia"])
        self.assertFalse(plan["availability"]["codex_plus"])
        self.assertIsNone(plan["parent"]["model"])

    def test_secret_without_local_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger, status, _ = self._paths(tmp)
            with self.assertRaisesRegex(governor.BudgetGovernorConfigError, "local provider"):
                governor.plan_governor(
                    task="secret codeを確認して",
                    sensitivity="secret",
                    ledger_path=ledger,
                    status_path=status,
                    env={"OPENROUTER_API_KEY": "or"},
                    codex_available=True,
                )

    def test_workbuddy_hy4_is_manual_advisory_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger, status, _ = self._paths(tmp)
            plan = governor.plan_governor(
                task="codeを実装してテストして",
                sensitivity="public",
                ledger_path=ledger,
                status_path=status,
                env={"OPENROUTER_API_KEY": "or"},
                codex_available=True,
                now=datetime(2026, 8, 29, tzinfo=timezone.utc),
            )
        self.assertEqual(len(plan["manual_opportunities"]), 1)
        manual = plan["manual_opportunities"][0]
        self.assertEqual(manual["lane"], "workbuddy-hy4-manual")
        self.assertEqual(manual["model"], governor.HY4_PREVIEW_MODEL)
        self.assertFalse(manual["automatic"])
        automatic = [
            item["selected"]["lane"]
            for item in plan["assignments"]
        ]
        self.assertNotIn("workbuddy-hy4-manual", automatic)

    def test_workbuddy_campaign_advisory_expires_without_override(self) -> None:
        availability = governor.detect_availability(
            sensitivity="public",
            env={},
            codex_available=False,
            now=datetime(2026, 9, 12, tzinfo=timezone.utc),
        )
        forced = governor.detect_availability(
            sensitivity="public",
            env={"MADO_WORKBUDDY_HY4_FREE": "1"},
            codex_available=False,
            now=datetime(2026, 9, 12, tzinfo=timezone.utc),
        )
        self.assertFalse(availability.workbuddy_hy4_manual)
        self.assertTrue(forced.workbuddy_hy4_manual)

    def test_run_falls_back_after_lane_failure_and_preserves_role_order(self) -> None:
        seen: list[tuple[str, str]] = []

        def fake_caller(candidate, *, role, prompt, **kwargs):
            del prompt, kwargs
            lane = str(candidate["lane"])
            seen.append((role, lane))
            if role == "implementer" and lane == "nvidia-fleet":
                raise RuntimeError("simulated nvidia outage")
            return {
                "content": f"proposal:{role}:{lane}",
                "usage": {"total_tokens": 10},
                "provider": {"name": candidate["provider"], "model": candidate["model"]},
                "request_profile": None,
            }

        with tempfile.TemporaryDirectory() as tmp:
            ledger, status, gov_ledger = self._paths(tmp)
            result = governor.run_governor(
                task="codeを実装してテストも追加して",
                sensitivity="public",
                ledger_path=ledger,
                status_path=status,
                governor_ledger_path=gov_ledger,
                env={"OPENROUTER_API_KEY": "or", "NVIDIA_API_KEY": "nv"},
                codex_available=True,
                lane_caller=fake_caller,
            )
            rows = [json.loads(line) for line in gov_ledger.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(result["status"], "PASS")
        self.assertEqual([item["role"] for item in result["results"]], ["implementer", "test_writer"])
        implementer = result["results"][0]
        self.assertEqual(implementer["attempts"][0]["lane"], "nvidia-fleet")
        self.assertEqual(implementer["attempts"][0]["status"], "ERROR")
        self.assertEqual(implementer["attempts"][1]["lane"], "codex-plus-luna")
        self.assertEqual(implementer["attempts"][1]["status"], "PASS")
        self.assertIn(("test_writer", "openrouter-hy3-free"), seen)
        self.assertTrue(rows)
        self.assertTrue(all("content" not in row and "prompt" not in row for row in rows))
        self.assertTrue(all(row["schema_version"] == governor.LEDGER_VERSION for row in rows))

    def test_no_automatic_lane_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger, status, _ = self._paths(tmp)
            with self.assertRaisesRegex(governor.BudgetGovernorConfigError, "no permitted automatic lane"):
                governor.plan_governor(
                    task="codeを実装してテストして",
                    sensitivity="private",
                    ledger_path=ledger,
                    status_path=status,
                    env={},
                    codex_available=False,
                    now=datetime(2026, 8, 29, tzinfo=timezone.utc),
                )

    def test_luna_profile_can_still_use_reset_aware_max_when_selected(self) -> None:
        budget = {
            "mode": "normal",
            "max_recommended": True,
        }
        profile = __import__("codex_plus_swarm")._profile_for_role("implementer", budget=budget)
        self.assertEqual(profile.model, plus_lane.LUNA_MODEL)
        self.assertEqual(profile.effort, "max")


if __name__ == "__main__":
    unittest.main()

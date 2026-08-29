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

import codex_plus_budget as budget  # noqa: E402


class CodexPlusBudgetTests(unittest.TestCase):
    def test_single_far_reset_snapshot_is_normal_without_invented_weekly_pace(self) -> None:
        now = datetime(2026, 8, 29, tzinfo=timezone.utc)
        observation = budget.make_observation(remaining_percent=80, hours_until_reset=72, now=now)
        pressure = budget.calibrated_pressure(observation, now=now)
        self.assertEqual(pressure["mode"], "normal")
        self.assertEqual(pressure["burn_state"], "normal")
        self.assertTrue(pressure["calibrated"])
        self.assertIsNone(pressure["burn_rate_percent_per_hour"])

    def test_single_close_reset_snapshot_with_headroom_is_aggressive(self) -> None:
        now = datetime(2026, 8, 29, tzinfo=timezone.utc)
        observation = budget.make_observation(remaining_percent=50, hours_until_reset=12, now=now)
        pressure = budget.calibrated_pressure(observation, now=now)
        self.assertEqual(pressure["mode"], "normal")
        self.assertEqual(pressure["burn_state"], "aggressive")
        self.assertTrue(pressure["max_recommended"])

    def test_low_observed_burn_rate_recommends_aggressive_max(self) -> None:
        start = datetime(2026, 8, 29, tzinfo=timezone.utc)
        first = budget.make_observation(remaining_percent=80, hours_until_reset=48, now=start)
        second = budget.make_observation(
            remaining_percent=79,
            hours_until_reset=44,
            now=start + timedelta(hours=4),
        )
        store = {"schema_version": budget.SCHEMA_VERSION, "observations": [first, second]}
        pressure = budget.calibrated_pressure(store, now=start + timedelta(hours=4))
        self.assertEqual(pressure["burn_state"], "aggressive")
        self.assertTrue(pressure["max_recommended"])
        self.assertLess(pressure["burn_to_sustainable_ratio"], 0.60)

    def test_fast_observed_burn_rate_enters_critical(self) -> None:
        start = datetime(2026, 8, 29, tzinfo=timezone.utc)
        first = budget.make_observation(remaining_percent=40, hours_until_reset=48, now=start)
        second = budget.make_observation(
            remaining_percent=30,
            hours_until_reset=44,
            now=start + timedelta(hours=4),
        )
        store = {"schema_version": budget.SCHEMA_VERSION, "observations": [first, second]}
        pressure = budget.calibrated_pressure(store, now=start + timedelta(hours=4))
        self.assertEqual(pressure["mode"], "critical")
        self.assertEqual(pressure["burn_state"], "critical")
        self.assertFalse(pressure["max_recommended"])

    def test_new_reset_window_does_not_inherit_old_burn_rate(self) -> None:
        start = datetime(2026, 8, 29, tzinfo=timezone.utc)
        old_first = budget.make_observation(remaining_percent=40, hours_until_reset=24, now=start)
        old_second = budget.make_observation(
            remaining_percent=20,
            hours_until_reset=20,
            now=start + timedelta(hours=4),
        )
        after_reset = budget.make_observation(
            remaining_percent=100,
            hours_until_reset=72,
            now=start + timedelta(hours=5),
        )
        store = {
            "schema_version": budget.SCHEMA_VERSION,
            "observations": [old_first, old_second, after_reset],
        }
        pressure = budget.calibrated_pressure(store, now=start + timedelta(hours=5))
        self.assertEqual(pressure["burn_state"], "normal")
        self.assertEqual(pressure["observations_in_current_window"], 1)
        self.assertIsNone(pressure["burn_rate_percent_per_hour"])

    def test_expired_observation_requires_refresh(self) -> None:
        observed = datetime(2026, 8, 20, tzinfo=timezone.utc)
        observation = budget.make_observation(remaining_percent=10, hours_until_reset=24, now=observed)
        pressure = budget.calibrated_pressure(observation, now=datetime(2026, 8, 29, tzinfo=timezone.utc))
        self.assertEqual(pressure["mode"], "normal")
        self.assertFalse(pressure["calibrated"])
        self.assertIn("refresh", pressure["reason"])

    def test_status_file_appends_coarse_history_without_content(self) -> None:
        start = datetime(2026, 8, 29, tzinfo=timezone.utc)
        first = budget.make_observation(remaining_percent=75, hours_until_reset=40, now=start)
        second = budget.make_observation(
            remaining_percent=74,
            hours_until_reset=39,
            now=start + timedelta(hours=1),
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "status.json"
            budget.save_observation(path, first)
            budget.save_observation(path, second)
            loaded = budget.load_observation(path)
            text = path.read_text(encoding="utf-8")
        self.assertEqual(len(loaded["observations"]), 2)
        self.assertEqual(loaded["observations"][-1]["remaining_percent"], 74.0)
        self.assertNotIn("prompt", text.casefold())
        self.assertNotIn("api_key", text.casefold())
        self.assertNotIn("response", text.casefold())

    def test_legacy_single_snapshot_is_migrated_in_memory(self) -> None:
        legacy = {
            "schema_version": budget.LEGACY_SCHEMA_VERSION,
            "observed_at": "2026-08-29T00:00:00Z",
            "reset_at": "2026-08-30T00:00:00Z",
            "remaining_percent": 50.0,
            "source": "legacy",
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "status.json"
            path.write_text(json.dumps(legacy), encoding="utf-8")
            loaded = budget.load_observation(path)
        self.assertEqual(loaded["schema_version"], budget.SCHEMA_VERSION)
        self.assertEqual(len(loaded["observations"]), 1)

    def test_stricter_mode_keeps_legacy_fallback_contract(self) -> None:
        self.assertEqual(budget.stricter_mode("normal", "conserve"), "conserve")
        self.assertEqual(budget.stricter_mode("critical", "conserve"), "critical")


if __name__ == "__main__":
    unittest.main()

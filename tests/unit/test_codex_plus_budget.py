from __future__ import annotations

from datetime import datetime, timezone
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
    def test_even_pace_is_normal(self) -> None:
        now = datetime(2026, 8, 29, tzinfo=timezone.utc)
        observation = budget.make_observation(remaining_percent=80, hours_until_reset=120, now=now)
        pressure = budget.calibrated_pressure(observation, now=now)
        self.assertEqual(pressure["mode"], "normal")
        self.assertTrue(pressure["calibrated"])

    def test_low_remaining_for_time_left_enters_conserve_or_critical(self) -> None:
        now = datetime(2026, 8, 29, tzinfo=timezone.utc)
        conserve = budget.make_observation(remaining_percent=60, hours_until_reset=120, now=now)
        critical = budget.make_observation(remaining_percent=40, hours_until_reset=120, now=now)
        self.assertEqual(budget.calibrated_pressure(conserve, now=now)["mode"], "conserve")
        self.assertEqual(budget.calibrated_pressure(critical, now=now)["mode"], "critical")

    def test_expired_observation_requires_refresh(self) -> None:
        observed = datetime(2026, 8, 20, tzinfo=timezone.utc)
        observation = budget.make_observation(remaining_percent=10, hours_until_reset=24, now=observed)
        pressure = budget.calibrated_pressure(observation, now=datetime(2026, 8, 29, tzinfo=timezone.utc))
        self.assertEqual(pressure["mode"], "normal")
        self.assertFalse(pressure["calibrated"])
        self.assertIn("refresh", pressure["reason"])

    def test_status_file_contains_only_coarse_usage_observation(self) -> None:
        observation = budget.make_observation(remaining_percent=75, hours_until_reset=100)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "status.json"
            budget.save_observation(path, observation)
            loaded = budget.load_observation(path)
            text = path.read_text(encoding="utf-8")
        self.assertEqual(loaded["remaining_percent"], 75.0)
        self.assertNotIn("prompt", text.casefold())
        self.assertNotIn("api_key", text.casefold())

    def test_stricter_mode_wins(self) -> None:
        self.assertEqual(budget.stricter_mode("normal", "conserve"), "conserve")
        self.assertEqual(budget.stricter_mode("critical", "conserve"), "critical")


if __name__ == "__main__":
    unittest.main()

from pathlib import Path
import sys
import unittest


SCRIPTS_DIR = Path(__file__).parents[2] / ".agents" / "skills" / "mado-loop" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from common import BudgetLedger, BudgetPolicy, aggregate_status  # noqa: E402


class BudgetTests(unittest.TestCase):
    def test_same_failure_limit_blocks_before_over_budget_repair(self):
        ledger = BudgetLedger()
        self.assertTrue(ledger.try_repair("P3|state.assert|wrong_hp|player.gd"))
        self.assertTrue(ledger.try_repair("P3|state.assert|wrong_hp|player.gd"))
        self.assertFalse(ledger.try_repair("P3|state.assert|wrong_hp|player.gd"))
        state = ledger.state()
        self.assertEqual(2, state["usage"]["repair_cycles"])
        self.assertEqual("UNKNOWN", state["status"])
        self.assertIn("same_failure_repairs limit 2", state["blocked_reasons"][0])

    def test_total_repair_limit_is_independent_of_failure_signature(self):
        ledger = BudgetLedger()
        for index in range(5):
            self.assertTrue(ledger.try_repair(f"failure-{index}"))
        self.assertFalse(ledger.try_repair("failure-5"))
        self.assertEqual(5, ledger.state()["usage"]["repair_cycles"])
        self.assertTrue(
            any("repair_cycles limit 5" in reason for reason in ledger.state()["blocked_reasons"])
        )

    def test_reversal_regeneration_video_and_nested_guards(self):
        reversal = BudgetLedger()
        self.assertTrue(reversal.try_file_reversal("res://player.gd"))
        self.assertTrue(reversal.try_file_reversal("res://player.gd"))
        self.assertFalse(reversal.try_file_reversal("res://player.gd"))

        asset = BudgetLedger()
        for _ in range(3):
            self.assertTrue(asset.try_asset_regeneration("foxfire_attack"))
        self.assertFalse(asset.try_asset_regeneration("foxfire_attack"))

        video = BudgetLedger()
        self.assertTrue(video.try_full_video_inspection())
        self.assertFalse(video.try_full_video_inspection())

        nested = BudgetLedger()
        self.assertFalse(nested.reject_nested_invocation())
        self.assertIn("nested MADO LOOP invocation", nested.state()["blocked_reasons"][0])

    def test_explicit_override_only_raises_named_limit(self):
        policy = BudgetPolicy().with_override("repair_cycles", 7)
        self.assertEqual(7, policy.max_repair_cycles)
        self.assertEqual(2, policy.max_same_failure_repairs)
        ledger = BudgetLedger(policy=policy)
        self.assertEqual({"repair_cycles": 7}, ledger.overrides())
        with self.assertRaises(ValueError):
            BudgetPolicy().with_override("repair_cycles", 5)
        with self.assertRaises(ValueError):
            BudgetPolicy().with_override("unknown", 9)

    def test_context_checkpoints_do_not_consume_repair_budget(self):
        ledger = BudgetLedger()
        ledger.record_context_checkpoint()
        ledger.record_context_checkpoint()
        state = ledger.state()
        self.assertEqual(2, state["usage"]["context_checkpoints"])
        self.assertEqual(0, state["usage"]["repair_cycles"])
        self.assertEqual("PASS", state["status"])

    def test_budget_check_uses_required_unknown_semantics(self):
        ledger = BudgetLedger()
        self.assertFalse(ledger.reject_nested_invocation())
        check = ledger.to_check()
        self.assertEqual("orchestrator.loop_budget", check["id"])
        self.assertTrue(check["required"])
        self.assertEqual("UNKNOWN", check["status"])
        self.assertEqual("UNKNOWN", aggregate_status([check]))

    def test_state_order_is_deterministic(self):
        ledger = BudgetLedger()
        self.assertTrue(ledger.try_asset_regeneration("zeta"))
        self.assertTrue(ledger.try_asset_regeneration("alpha"))
        self.assertTrue(ledger.try_file_reversal("z.gd"))
        self.assertTrue(ledger.try_file_reversal("a.gd"))
        state = ledger.state()
        self.assertEqual(["alpha", "zeta"], list(state["usage"]["asset_regenerations"]))
        self.assertEqual(["a.gd", "z.gd"], list(state["usage"]["file_reversals"]))


if __name__ == "__main__":
    unittest.main()

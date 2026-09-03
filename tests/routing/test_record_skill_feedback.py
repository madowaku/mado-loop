import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


MODULE_PATH = (
    Path(__file__).parents[2]
    / ".agents" / "skills" / "mado-loop" / "scripts" / "record_skill_feedback.py"
)
SPEC = importlib.util.spec_from_file_location("mado_record_skill_feedback", MODULE_PATH)
feedback = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(feedback)


class RecordSkillFeedbackTests(unittest.TestCase):
    def test_event_is_content_free_and_canonical(self):
        event = feedback.canonical_event(
            receipt_id="T100",
            status="PASS",
            skills_used=["game-feel", "godot-gdscript", "game-feel"],
            repair_cycles=1,
            tokens=1200,
        )
        self.assertEqual(["game-feel", "godot-gdscript"], event["skills_used"])
        self.assertEqual(1, event["repair_cycles"])
        self.assertEqual(1200, event["tokens"])
        self.assertNotIn("prompt", event)
        self.assertNotIn("summary", event)

    def test_build_stats_aggregates_outcomes_repairs_and_tokens(self):
        events = [
            feedback.canonical_event(
                receipt_id="A", status="PASS", skills_used=["game-feel"], tokens=100
            ),
            feedback.canonical_event(
                receipt_id="B", status="WARN", skills_used=["game-feel", "puzzle"],
                repair_cycles=2, tokens=300,
            ),
            feedback.canonical_event(
                receipt_id="C", status="FAIL", skills_used=["puzzle"], repair_cycles=1
            ),
        ]
        stats = feedback.build_stats(events)
        self.assertEqual(3, stats["receipt_count"])
        feel = stats["skills"]["game-feel"]
        puzzle = stats["skills"]["puzzle"]
        self.assertEqual(2, feel["uses"])
        self.assertEqual(1, feel["pass"])
        self.assertEqual(1, feel["warn"])
        self.assertEqual(2, feel["repair_cycles_total"])
        self.assertEqual(2, feel["token_samples"])
        self.assertEqual(400, feel["tokens_total"])
        self.assertEqual(2, puzzle["uses"])
        self.assertEqual(1, puzzle["fail"])

    def test_record_is_idempotent_and_rebuilds_compact_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = root / "feedback.jsonl"
            stats_path = root / "stats.json"
            event = feedback.canonical_event(
                receipt_id="T200", status="PASS", skills_used=["game-feel"]
            )
            first, appended_first = feedback.record_event(
                ledger_path=ledger, stats_path=stats_path, event=event
            )
            second, appended_second = feedback.record_event(
                ledger_path=ledger, stats_path=stats_path, event=event
            )
            self.assertTrue(appended_first)
            self.assertFalse(appended_second)
            self.assertEqual(first, second)
            self.assertEqual(1, len(ledger.read_text(encoding="utf-8").splitlines()))
            self.assertEqual(first, json.loads(stats_path.read_text(encoding="utf-8")))

    def test_conflicting_duplicate_receipt_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = root / "feedback.jsonl"
            stats_path = root / "stats.json"
            original = feedback.canonical_event(
                receipt_id="T300", status="PASS", skills_used=["game-feel"]
            )
            conflict = feedback.canonical_event(
                receipt_id="T300", status="FAIL", skills_used=["game-feel"]
            )
            feedback.record_event(ledger_path=ledger, stats_path=stats_path, event=original)
            with self.assertRaises(ValueError):
                feedback.record_event(ledger_path=ledger, stats_path=stats_path, event=conflict)

    def test_invalid_feedback_is_rejected(self):
        with self.assertRaises(ValueError):
            feedback.canonical_event(receipt_id="", status="PASS", skills_used=["x"])
        with self.assertRaises(ValueError):
            feedback.canonical_event(
                receipt_id="task prompt with spaces", status="PASS", skills_used=["x"]
            )
        with self.assertRaises(ValueError):
            feedback.canonical_event(receipt_id="x", status="BROKEN", skills_used=["x"])
        with self.assertRaises(ValueError):
            feedback.canonical_event(receipt_id="x", status="PASS", skills_used=[])
        with self.assertRaises(ValueError):
            feedback.canonical_event(
                receipt_id="x", status="PASS", skills_used=["not a skill id"]
            )
        with self.assertRaises(ValueError):
            feedback.canonical_event(
                receipt_id="x", status="PASS", skills_used=["x"], repair_cycles=-1
            )


if __name__ == "__main__":
    unittest.main()

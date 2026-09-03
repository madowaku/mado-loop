import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = (
    Path(__file__).parents[2]
    / ".agents" / "skills" / "mado-loop" / "scripts" / "select_skills.py"
)
SPEC = importlib.util.spec_from_file_location("mado_select_skills", MODULE_PATH)
selector = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(selector)


class SelectSkillsTests(unittest.TestCase):
    def test_registry_is_valid_and_unique(self):
        registry = selector.load_registry()
        ids = [entry["id"] for entry in registry["skills"]]
        self.assertEqual(1, registry["version"])
        self.assertEqual(len(ids), len(set(ids)))
        self.assertFalse(registry["policy"]["auto_install"])
        self.assertEqual("skills_used", registry["policy"]["receipt_key"])
        self.assertEqual(3, registry["policy"]["feedback_min_samples"])
        self.assertEqual(4, registry["policy"]["feedback_max_adjustment"])

    def test_ui_route_selects_ui_specialists(self):
        payload = selector.route_task("HUDのsafe areaとfocusを直して")
        self.assertEqual(["UI"], payload["task_domains"])
        self.assertEqual(
            ["godot-ui-control", "game-ui-ux"], payload["recommended_skills"][:2]
        )
        self.assertFalse(payload["availability_known"])
        self.assertFalse(payload["feedback_stats_known"])
        self.assertEqual([], payload["loadable_skills"])

    def test_trigger_can_select_specialist_without_domain_match(self):
        puzzle = selector.route_task("パズルのsolvabilityとundoを検証して")
        feel = selector.route_task("ヒットストップと画面揺れを気持ちよくして")
        self.assertIn("puzzle", puzzle["recommended_skills"])
        self.assertIn("game-feel", feel["recommended_skills"])

    def test_availability_filters_without_auto_install(self):
        payload = selector.route_task(
            "UIのsafe areaを調整して",
            available=["game-ui-ux"],
        )
        self.assertTrue(payload["availability_known"])
        self.assertEqual(["game-ui-ux"], payload["loadable_skills"])
        self.assertIn("godot-ui-control", payload["unavailable_skills"])
        self.assertFalse(payload["policy"]["auto_install"])

    def test_manual_only_skills_require_explicit_manual_route(self):
        automatic = selector.route_task("browser gameをPlaywrightで検証して")
        manual = selector.route_task(
            "browser gameをPlaywrightで検証して", include_manual=True
        )
        self.assertNotIn("develop-web-game", automatic["recommended_skills"])
        self.assertIn("develop-web-game", manual["recommended_skills"])

    def test_selection_order_and_cap_are_deterministic(self):
        registry = selector.load_registry()
        payload = selector.route_task(
            "UI HUD menu safe area focus scene node game feel juice feedback"
        )
        self.assertLessEqual(
            len(payload["recommended_skills"]), registry["policy"]["max_auto_selected"]
        )
        effective = [item["effective_priority"] for item in payload["selection"]]
        self.assertEqual(effective, sorted(effective, reverse=True))

    def test_feedback_nudges_only_existing_candidates(self):
        stats = {
            "schema_version": "1",
            "receipt_count": 8,
            "skills": {
                "game-feel": {
                    "uses": 4, "pass": 4, "warn": 0, "unknown": 0, "fail": 0,
                    "repair_cycles_total": 0, "token_samples": 4, "tokens_total": 12000,
                },
                "godot-nodes-scenes": {
                    "uses": 4, "pass": 0, "warn": 0, "unknown": 0, "fail": 4,
                    "repair_cycles_total": 8, "token_samples": 4, "tokens_total": 8000,
                },
                "puzzle": {
                    "uses": 20, "pass": 20, "warn": 0, "unknown": 0, "fail": 0,
                    "repair_cycles_total": 0, "token_samples": 0, "tokens_total": 0,
                },
            },
        }
        payload = selector.route_task(
            "UI HUD scene node game feel juice feedback",
            stats=stats,
        )
        self.assertTrue(payload["feedback_stats_known"])
        self.assertIn("game-feel", payload["recommended_skills"])
        self.assertIn("godot-nodes-scenes", payload["recommended_skills"])
        self.assertNotIn("puzzle", payload["recommended_skills"])
        selected = {item["id"]: item for item in payload["selection"]}
        self.assertGreater(selected["game-feel"]["feedback_adjustment"], 0)
        self.assertLess(selected["godot-nodes-scenes"]["feedback_adjustment"], 0)
        self.assertGreater(
            payload["recommended_skills"].index("godot-nodes-scenes"),
            payload["recommended_skills"].index("game-feel"),
        )

    def test_feedback_requires_minimum_samples(self):
        stats = {
            "schema_version": "1",
            "receipt_count": 2,
            "skills": {
                "game-feel": {
                    "uses": 2, "pass": 0, "warn": 0, "unknown": 0, "fail": 2,
                    "repair_cycles_total": 10, "token_samples": 0, "tokens_total": 0,
                }
            },
        }
        payload = selector.route_task("game feel juice feedback", stats=stats)
        item = next(item for item in payload["selection"] if item["id"] == "game-feel")
        self.assertEqual(2, item["feedback_samples"])
        self.assertEqual(0.0, item["feedback_adjustment"])
        self.assertEqual(item["priority"], item["effective_priority"])


if __name__ == "__main__":
    unittest.main()

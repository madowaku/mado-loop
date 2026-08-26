import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).parents[2]
MODULE_PATH = ROOT / ".agents" / "skills" / "mado-loop" / "scripts" / "classify_task.py"
SPEC = importlib.util.spec_from_file_location("mado_classify_task", MODULE_PATH)
classifier = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(classifier)


class ClassifyTaskTests(unittest.TestCase):
    def test_single_domains(self):
        cases = {
            "Tune player movement and combat": ["GAMEPLAY"],
            "Build the HUD menu": ["UI"],
            "Pack the character sprite sheet": ["SPRITE"],
            "プレイテストで操作を確認": ["GAMEPLAY", "PLAYTEST", "MIXED"],
            "Prepare the release build": ["RELEASE"],
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(classifier.classify_task(text)["task_domains"], expected)

    def test_mixed_domains_are_canonical_and_stable(self):
        text = "Create UI code and a sprite animation"
        first = classifier.classify_task(text)
        second = classifier.classify_task(text)
        self.assertEqual(
            first["task_domains"], ["CODE", "UI", "SPRITE", "ANIMATION", "MIXED"]
        )
        self.assertEqual(classifier.result_json(first), classifier.result_json(second))

    def test_reference_pixel_art_and_asset_routing(self):
        payload = classifier.classify_task(
            "Turn a screenshot to UI, use pixel art, then import asset settings"
        )
        self.assertEqual(
            payload["task_domains"],
            ["UI", "ASSET_INTEGRATION", "REFERENCE_TO_UI", "PIXEL_ART", "MIXED"],
        )

    def test_unicode_input(self):
        payload = classifier.classify_task("ドット絵スプライトをアニメーションして配布する")
        self.assertEqual(
            payload["task_domains"], ["SPRITE", "ANIMATION", "PIXEL_ART", "RELEASE", "MIXED"]
        )
        self.assertEqual(payload["status"], "PASS")

    def test_ambiguity_is_unknown(self):
        payload = classifier.classify_task("Make it feel better somehow")
        self.assertEqual(payload["status"], "UNKNOWN")
        self.assertEqual(payload["task_domains"], [])
        self.assertEqual(payload["checks"][0]["status"], "UNKNOWN")
        self.assertEqual(payload["unknowns"][0]["id"], "routing.no_domain_match")

    def test_cli_json_and_exit_semantics(self):
        completed = subprocess.run(
            [sys.executable, str(MODULE_PATH), "HUD", "playtest"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(completed.returncode, 0)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["task_domains"], ["UI", "PLAYTEST", "MIXED"])

        unknown = subprocess.run(
            [sys.executable, str(MODULE_PATH), "something vague"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(unknown.returncode, 2)
        self.assertEqual(json.loads(unknown.stdout)["status"], "UNKNOWN")

        usage = subprocess.run(
            [sys.executable, str(MODULE_PATH)],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(usage.returncode, 64)


if __name__ == "__main__":
    unittest.main()

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).parents[2]
MODULE_PATH = ROOT / ".agents" / "skills" / "mado-loop" / "scripts" / "validate_eval_case.py"
SPEC = importlib.util.spec_from_file_location("validate_eval_case", MODULE_PATH)
evals = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(evals)


class EvalCaseValidationTests(unittest.TestCase):
    def make_case(self, root: Path, **overrides):
        case_dir = root / "ui" / "visible-control"
        case_dir.mkdir(parents=True)
        (case_dir / "task.md").write_text("Add one visible QUIT button.\n", encoding="utf-8")
        fixture = case_dir / "fixture"
        fixture.mkdir()
        (fixture / "project.godot").write_text("[application]\n", encoding="utf-8")
        payload = {
            "schema_version": "0.1",
            "id": "ui.visible-control",
            "title": "Visible control smoke",
            "domains": ["UI", "CODE"],
            "task_file": "task.md",
            "fixture": "fixture",
            "tags": ["smoke", "ui"],
            "required_proof": ["P3", "P0", "P2"],
            "acceptance": [
                {
                    "id": "ui.quit-button-visible",
                    "kind": "evidence",
                    "required": True,
                    "description": "A visible QUIT button exists in the running UI",
                },
                {
                    "id": "ui.project-still-boots",
                    "kind": "invariant",
                    "required": True,
                    "description": "The fixture still starts after the change",
                },
            ],
            "policy": {
                "sensitivity": "public",
                "network": "restricted",
                "mutation": "isolated_worktree",
                "timeout_seconds": 300,
                "allowed_platforms": ["linux", "windows"],
            },
            "expected_paths": [],
        }
        payload.update(overrides)
        path = case_dir / "case.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_valid_case_is_normalized_and_digest_is_stable(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = self.make_case(Path(temporary))
            first = evals.load_and_digest_case(path)
            second = evals.load_and_digest_case(path)
        self.assertEqual(first["case_digest"], second["case_digest"])
        self.assertRegex(first["case_digest"], r"^sha256:[a-f0-9]{64}$")
        self.assertEqual(first["case"]["domains"], ["CODE", "UI"])
        self.assertEqual(first["case"]["required_proof"], ["P0", "P2", "P3"])
        self.assertEqual(first["case"]["policy"]["allowed_platforms"], ["windows", "linux"])
        self.assertEqual([entry["path"] for entry in first["files"]], ["fixture/project.godot", "task.md"])

    def test_task_change_changes_case_digest(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = self.make_case(Path(temporary))
            before = evals.load_and_digest_case(path)["case_digest"]
            (path.parent / "task.md").write_text("Add two visible buttons.\n", encoding="utf-8")
            after = evals.load_and_digest_case(path)["case_digest"]
        self.assertNotEqual(before, after)

    def test_fixture_change_changes_case_digest(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = self.make_case(Path(temporary))
            before = evals.load_and_digest_case(path)["case_digest"]
            (path.parent / "fixture" / "project.godot").write_text("[application]\nrun/main_scene=\"main.tscn\"\n", encoding="utf-8")
            after = evals.load_and_digest_case(path)["case_digest"]
        self.assertNotEqual(before, after)

    def test_parent_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = self.make_case(Path(temporary), task_file="../task.md")
            with self.assertRaisesRegex(ValueError, "traverse parents"):
                evals.load_and_digest_case(path)

    def test_duplicate_acceptance_ids_are_rejected(self):
        duplicate = [
            {
                "id": "ui.same-check",
                "kind": "test",
                "required": True,
                "description": "First check",
            },
            {
                "id": "ui.same-check",
                "kind": "evidence",
                "required": True,
                "description": "Second check",
            },
        ]
        with tempfile.TemporaryDirectory() as temporary:
            path = self.make_case(Path(temporary), acceptance=duplicate)
            with self.assertRaisesRegex(ValueError, "duplicate acceptance id"):
                evals.load_and_digest_case(path)

    def test_unknown_case_keys_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = self.make_case(Path(temporary), magic_score=100)
            with self.assertRaisesRegex(ValueError, "unknown keys"):
                evals.load_and_digest_case(path)

    def test_missing_referenced_expected_path_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = self.make_case(Path(temporary), expected_paths=["expected/missing.json"])
            with self.assertRaisesRegex(ValueError, "expected path does not exist"):
                evals.load_and_digest_case(path)


if __name__ == "__main__":
    unittest.main()

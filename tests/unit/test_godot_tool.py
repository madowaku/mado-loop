import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS_ROOT = Path(__file__).resolve().parents[2] / ".agents" / "skills" / "mado-loop" / "scripts"
sys.path.insert(0, str(SCRIPTS_ROOT))

from common import godot_tool  # noqa: E402


def completed(payload, returncode=0):
    return subprocess.CompletedProcess(["python"], returncode, "noise\n" + json.dumps(payload), "")


class GodotToolTests(unittest.TestCase):
    @patch.object(godot_tool.subprocess, "run")
    def test_completed_decodes_wrapper_output_as_utf8_with_replacement(self, run):
        run.return_value = subprocess.CompletedProcess(["wrapper"], 0, "日本語", "")

        result = godot_tool._completed(["wrapper"], 12)

        self.assertEqual(result.stdout, "日本語")
        self.assertEqual(run.call_args.kwargs["encoding"], "utf-8")
        self.assertEqual(run.call_args.kwargs["errors"], "replace")
        self.assertEqual(run.call_args.kwargs["env"]["PYTHONDONTWRITEBYTECODE"], "1")

    def test_vendor_paths_select_exact_entrypoints(self):
        self.assertEqual(godot_tool.vendor_wrapper("validate").name, "validate_project.py")
        self.assertEqual(godot_tool.vendor_wrapper("run").name, "run_project.py")
        self.assertEqual(godot_tool.vendor_wrapper("scenario").name, "run_scenario.py")
        self.assertEqual(godot_tool.vendor_wrapper("export").name, "export_project.py")

    @patch.object(godot_tool, "_completed")
    def test_p0_validation_inspects_static_and_diagnostics(self, run):
        run.return_value = completed({"ok": False, "static": {"failed_count": 1}, "counts": {"errors": 0}})
        result = godot_tool.run_godot_tool("validate", godot_bin="C:/Godot 工具/godot.exe", project_path="C:/作品/test game")
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["proof_level"], "P0")
        self.assertEqual(run.call_args.args[0][1], "-B")
        self.assertEqual(run.call_args.args[0][3], str(Path("C:/作品/test game")))
        self.assertEqual(run.call_args.args[0][5], "C:/Godot 工具/godot.exe")

    @patch.object(godot_tool, "_completed")
    def test_p1_runtime_nonzero_wrapper_exit_fails(self, run):
        run.return_value = completed({"ok": True, "timed_out": False, "counts": {"errors": 0, "parse_errors": 0}}, 9)
        result = godot_tool.run_godot_tool("run", godot_bin="godot.exe", project_path="game")
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["proof_level"], "P1")

    @patch.object(godot_tool, "_completed")
    def test_payload_nonzero_exit_fails(self, run):
        run.return_value = completed({"ok": True, "exit_code": 7, "counts": {"errors": 0}})
        result = godot_tool.run_godot_tool("run", godot_bin="godot", project_path="game")
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("exit_code=7", str(result["errors"]))

    @patch.object(godot_tool, "_completed")
    def test_pack_ignores_only_exact_template_notice_and_preserves_other_warning(self, run):
        notice = "Matching Godot export templates were not found (not required for pack/patch data exports)"
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "fixture.zip"
            def invoke(command, timeout):
                if "--preflight-only" in command:
                    return completed({"preflight": {"ok": True, "errors": [], "warnings": [notice, "actionable warning"]}})
                output.write_bytes(b"artifact")
                return completed({"exit_code": 0})
            run.side_effect = invoke
            result = godot_tool.run_godot_tool("export", godot_bin="godot", project_path="game",
                                               preset_name="Desktop", output_path=output, mode="pack")
        self.assertEqual(result["status"], "WARN")
        self.assertEqual(result["warnings"], ["actionable warning"])

    @patch.object(godot_tool, "_completed")
    def test_export_preflight_payload_nonzero_exit_fails(self, run):
        run.return_value = completed({
            "exit_code": 3,
            "preflight": {"ok": True, "errors": [], "warnings": []},
        })
        with tempfile.TemporaryDirectory() as tmp:
            result = godot_tool.run_godot_tool(
                "export", godot_bin="godot", project_path="game", preset_name="Desktop",
                output_path=Path(tmp) / "fixture.zip", mode="pack",
            )
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("exit_code=3", str(result["errors"]))

    @patch.object(godot_tool, "_completed")
    def test_scenario_failed_assertion_is_fail(self, run):
        run.return_value = completed({"ok": True, "assertions": [{"passed": False}], "log_assertions": [], "performance_assertions": []})
        result = godot_tool.run_godot_tool("scenario", godot_bin="godot", project_path="game", scenario_path="case.json")
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["proof_level"], "P4")
        self.assertEqual(result["task_domains"], ["GAMEPLAY", "UI", "PLAYTEST", "MIXED"])

    @patch.object(godot_tool, "_completed")
    def test_malformed_timeout_and_missing_artifact_are_unknown(self, run):
        run.return_value = completed({"ok": True, "screenshots": [{"path": "missing.png"}]})
        absent = godot_tool.run_godot_tool("scenario", godot_bin="godot", project_path="game", scenario_path="case.json")
        self.assertEqual(absent["status"], "UNKNOWN")
        run.side_effect = subprocess.TimeoutExpired(["python"], 1)
        timeout = godot_tool.run_godot_tool("run", godot_bin="godot", project_path="game", timeout=1)
        self.assertEqual(timeout["status"], "UNKNOWN")
        run.side_effect = None
        run.return_value = subprocess.CompletedProcess([], 0, "not json", "")
        malformed = godot_tool.run_godot_tool("validate", godot_bin="godot", project_path="game")
        self.assertEqual(malformed["status"], "UNKNOWN")

    @patch.object(godot_tool, "_completed")
    def test_p5_requires_preflight_and_artifact(self, run):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "build.aab"
            def invoke(command, timeout):
                if "--preflight-only" in command:
                    return completed({"preflight": {"ok": True, "errors": [], "warnings": []}})
                output.write_bytes(b"artifact")
                return completed({}, 0)
            run.side_effect = invoke
            result = godot_tool.run_godot_tool("export", godot_bin="godot", project_path="game", preset_name="Android", output_path=output)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["proof_level"], "P5")
        self.assertTrue(result["artifacts"][0]["exists"])

    @patch.object(godot_tool, "_completed")
    def test_serialization_is_stable(self, run):
        run.return_value = completed({"ok": True, "counts": {"warnings": 0, "errors": 0, "parse_errors": 0}})
        first = godot_tool.run_godot_tool("validate", godot_bin="godot", project_path="game")
        second = godot_tool.run_godot_tool("validate", godot_bin="godot", project_path="game")
        first["duration_ms"] = second["duration_ms"] = 0
        self.assertEqual(json.dumps(first, ensure_ascii=False), json.dumps(second, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()

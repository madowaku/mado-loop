import importlib.util
import io
import json
from pathlib import Path
import subprocess
import unittest
from unittest import mock

ROOT = Path(__file__).parents[2]
MODULE_PATH = ROOT / ".agents" / "skills" / "mado-loop" / "scripts" / "mado_doctor.py"
SPEC = importlib.util.spec_from_file_location("mado_doctor", MODULE_PATH)
doctor = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(doctor)


class DoctorTests(unittest.TestCase):
    def completed(self, output="4.3.stable.official"):
        return subprocess.CompletedProcess([], 0, output, "")

    @mock.patch.object(doctor.importlib.util, "find_spec", return_value=object())
    @mock.patch.object(doctor.shutil, "which")
    @mock.patch.object(doctor.subprocess, "run")
    def test_explicit_precedes_path_and_parses_version(self, run, which, _spec):
        which.return_value = r"C:\PATH\godot.exe"
        run.return_value = self.completed()
        payload = doctor.diagnose(godot=r"C:\ゲーム 開発\Godot.exe")
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["environment"]["godot_source"], "explicit")
        self.assertEqual(payload["environment"]["godot_version"], "4.3.stable")
        self.assertEqual(run.call_args.args[0][0], r"C:\ゲーム 開発\Godot.exe")

    @mock.patch.object(doctor.importlib.util, "find_spec", return_value=object())
    @mock.patch.object(doctor.shutil, "which")
    @mock.patch.object(doctor.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "4.2.1", ""))
    def test_path_precedes_common_paths(self, _run, which, _spec):
        which.side_effect = lambda name: r"D:\Tools\Godot.exe" if name in {"godot", "godot4"} else None
        with mock.patch.object(Path, "is_file", return_value=True):
            payload = doctor.diagnose()
        self.assertEqual(payload["environment"]["godot_source"], "PATH")

    @mock.patch.object(doctor.importlib.util, "find_spec", return_value=object())
    @mock.patch.object(doctor.shutil, "which", return_value=None)
    @mock.patch.object(doctor.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "4.1", ""))
    def test_common_path_fallback_is_bounded(self, _run, _which, _spec):
        with mock.patch.object(Path, "is_file", side_effect=[False, True]):
            payload = doctor.diagnose()
        self.assertEqual(payload["environment"]["godot_source"], "common_windows_path")
        self.assertEqual(payload["environment"]["godot_path"], str(doctor.COMMON_WINDOWS_GODOT_PATHS[1]))

    @mock.patch.object(doctor.importlib.util, "find_spec", return_value=None)
    @mock.patch.object(doctor.shutil, "which", return_value=None)
    def test_missing_required_is_unknown_optional_is_skipped_warn(self, _which, _spec):
        with mock.patch.object(Path, "is_file", return_value=False):
            payload = doctor.diagnose()
        self.assertEqual(payload["status"], "UNKNOWN")
        self.assertNotEqual(payload["status"], "SKIPPED")
        by_id = {item["id"]: item for item in payload["checks"]}
        self.assertEqual(by_id["dependency.godot"]["status"], "SKIPPED")
        self.assertTrue(by_id["dependency.godot"]["required"])
        self.assertEqual(by_id["optional.numpy"]["status"], "SKIPPED")
        self.assertFalse(by_id["optional.numpy"]["required"])

    @mock.patch.object(doctor.importlib.util, "find_spec", return_value=object())
    @mock.patch.object(doctor.shutil, "which", return_value=r"C:\Godot.exe")
    @mock.patch.object(doctor.subprocess, "run", side_effect=subprocess.TimeoutExpired("godot", 1))
    def test_timeout_and_invalid_version_are_unknown(self, _run, _which, _spec):
        payload = doctor.diagnose(timeout=1)
        self.assertEqual(payload["status"], "UNKNOWN")
        self.assertEqual(payload["unknowns"][0]["id"], "dependency.godot_unverified")

    @mock.patch.object(doctor.importlib.util, "find_spec", return_value=object())
    @mock.patch.object(doctor.shutil, "which", return_value=r"C:\Godot.exe")
    @mock.patch.object(doctor.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "not-a-version", ""))
    def test_unparseable_version_is_unknown(self, _run, _which, _spec):
        self.assertEqual(doctor.diagnose()["status"], "UNKNOWN")

    @mock.patch.object(doctor.importlib.util, "find_spec", return_value=object())
    @mock.patch.object(doctor.shutil, "which", return_value=r"C:\broken.exe")
    @mock.patch.object(doctor.subprocess, "run", side_effect=OSError("invalid executable"))
    def test_invalid_executable_is_unknown(self, _run, _which, _spec):
        self.assertEqual(doctor.diagnose()["status"], "UNKNOWN")

    @mock.patch.object(doctor.importlib.util, "find_spec", return_value=object())
    @mock.patch.object(doctor.shutil, "which", return_value=r"C:\Godot.exe")
    @mock.patch.object(doctor.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "4.3", ""))
    def test_declared_capability_and_deterministic_outputs(self, _run, _which, _spec):
        with mock.patch.object(Path, "exists", autospec=True, side_effect=lambda path: "存在" in str(path)):
            payload = doctor.diagnose(declarations={"画像生成": r"C:\素材 フォルダ\存在.exe", "editor": "missing"})
        encoded = doctor.result_json(payload)
        self.assertEqual(json.loads(encoded)["schema_version"], "1.1")
        self.assertIn("画像生成", encoded)
        self.assertTrue(doctor.human_output(payload).startswith(f"MADO Doctor: {payload['status']}"))
        self.assertEqual([c["id"] for c in payload["checks"]], sorted(c["id"] for c in payload["checks"]))
        by_id = {item["id"]: item for item in payload["checks"]}
        self.assertEqual(by_id["routed.画像生成"]["status"], "PASS")
        self.assertEqual(by_id["routed.editor"]["status"], "SKIPPED")

    def test_cli_usage_timeout(self):
        stderr = io.StringIO()
        with mock.patch("sys.stderr", stderr):
            self.assertEqual(doctor.main(["--timeout", "0"]), 64)


if __name__ == "__main__":
    unittest.main()

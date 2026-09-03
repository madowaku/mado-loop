import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

MODULE_PATH = Path(__file__).parents[2] / ".agents" / "skills" / "mado-loop" / "scripts" / "visual_broker.py"
SPEC = importlib.util.spec_from_file_location("visual_broker", MODULE_PATH)
broker = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = broker
assert SPEC.loader is not None
SPEC.loader.exec_module(broker)


def git(repo: Path, *args: str) -> None:
    cp = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8")
    if cp.returncode != 0:
        raise AssertionError(cp.stderr)


class FakeProcess:
    def __init__(self, pid=4242, returncode=None):
        self.pid = pid
        self._returncode = returncode
        self.terminated = False

    def poll(self):
        return self._returncode

    def terminate(self):
        self.terminated = True


class VisualBrokerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-b", "main")
        git(self.repo, "config", "user.name", "Mado Test")
        git(self.repo, "config", "user.email", "mado@example.invalid")
        (self.repo / "project.godot").write_text("[application]\n", encoding="utf-8")
        (self.repo / "main.tscn").write_text("[gd_scene format=3]\n", encoding="utf-8")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-m", "init")
        self.godot = self.root / ("godot.exe" if sys.platform.startswith("win") else "godot")
        self.godot.write_text("fake", encoding="utf-8")
        self.identity = {"exe": str(self.godot.resolve()), "started": 123}

    def tearDown(self):
        self.temp.cleanup()

    def identity_reader(self, pid, *, host_platform=None):
        return dict(self.identity)

    def fake_popen(self, command, **kwargs):
        self.command = list(command)
        return FakeProcess()

    def launch(self, session="visual-1"):
        return broker.launch_session(
            repo=self.repo,
            session=session,
            godot_bin=self.godot,
            scene="main.tscn",
            startup_wait=0,
            popen=self.fake_popen,
            identity_reader=self.identity_reader,
            sleeper=lambda _: None,
            host_platform="win32",
        )

    def test_launch_capture_stop_roundtrip_uses_owned_process(self):
        launched = self.launch()
        self.assertEqual(launched["status"], "PASS")
        self.assertEqual(self.command[1:3], ["--path", str(self.repo.resolve())])

        def capture(pid, output):
            self.assertEqual(pid, 4242)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"not-empty")

        captured = broker.capture_session(
            repo=self.repo,
            session="visual-1",
            output="artifacts/window.png",
            identity_reader=self.identity_reader,
            capture_func=capture,
            host_platform="win32",
        )
        self.assertEqual(captured["status"], "PASS")
        self.assertTrue((self.repo / "artifacts" / "window.png").is_file())

        stopped_pids = []
        stopped = broker.stop_session(
            repo=self.repo,
            session="visual-1",
            identity_reader=self.identity_reader,
            terminator=lambda pid, **_: stopped_pids.append(pid) or True,
            host_platform="win32",
        )
        self.assertEqual(stopped["status"], "PASS")
        self.assertEqual(stopped_pids, [4242])
        state = broker._load_state(self.repo, "visual-1")
        self.assertEqual(state["status"], "STOPPED")

    def test_duplicate_running_session_is_rejected(self):
        self.launch()
        with self.assertRaises(broker.BrokerConfigError):
            self.launch()

    def test_capture_refuses_path_outside_repo(self):
        self.launch()
        with self.assertRaises(broker.BrokerConfigError):
            broker.capture_session(
                repo=self.repo,
                session="visual-1",
                output=self.root / "escape.png",
                identity_reader=self.identity_reader,
                capture_func=lambda *_: None,
                host_platform="win32",
            )

    def test_identity_mismatch_blocks_capture_and_stop(self):
        self.launch()
        wrong = lambda pid, **_: {"exe": "other", "started": 999}
        with self.assertRaises(broker.BrokerConfigError):
            broker.capture_session(
                repo=self.repo,
                session="visual-1",
                output="capture.png",
                identity_reader=wrong,
                host_platform="win32",
            )
        with self.assertRaises(broker.BrokerConfigError):
            broker.stop_session(
                repo=self.repo,
                session="visual-1",
                identity_reader=wrong,
                terminator=lambda *_args, **_kwargs: True,
                host_platform="win32",
            )

    def test_non_windows_capture_is_explicit_unknown(self):
        self.launch()
        result = broker.capture_session(
            repo=self.repo,
            session="visual-1",
            output="capture.png",
            identity_reader=self.identity_reader,
            capture_func=lambda *_: (_ for _ in ()).throw(AssertionError("must not capture")),
            host_platform="linux",
        )
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertIn("only on native Windows", result["summary"])

    def test_scene_must_stay_inside_project(self):
        outside = self.root / "outside.tscn"
        outside.write_text("[gd_scene format=3]\n", encoding="utf-8")
        with self.assertRaises(broker.BrokerConfigError):
            broker.launch_session(
                repo=self.repo,
                session="visual-1",
                godot_bin=self.godot,
                scene=str(outside),
                startup_wait=0,
                popen=self.fake_popen,
                identity_reader=self.identity_reader,
                sleeper=lambda _: None,
                host_platform="win32",
            )


if __name__ == "__main__":
    unittest.main()

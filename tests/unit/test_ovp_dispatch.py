import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

MODULE_PATH = Path(__file__).parents[2] / ".agents" / "skills" / "mado-loop" / "scripts" / "ovp_dispatch.py"
SPEC = importlib.util.spec_from_file_location("ovp_dispatch", MODULE_PATH)
dispatch = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = dispatch
assert SPEC.loader is not None
SPEC.loader.exec_module(dispatch)
ovp = dispatch.ovp


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    cp = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8")
    if check and cp.returncode != 0:
        raise AssertionError(f"git failed: {args}: {cp.stderr}")
    return cp


class OvpDispatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = self.root / "project"
        self.repo.mkdir()
        git(self.repo, "init", "-b", "main")
        git(self.repo, "config", "user.name", "Mado Test")
        git(self.repo, "config", "user.email", "mado@example.invalid")
        (self.repo / "src").mkdir()
        (self.repo / "src" / "player.gd").write_text("speed = 1\n", encoding="utf-8")
        (self.repo / "README.md").write_text("game\n", encoding="utf-8")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-m", "initial")
        self.workspace_root = self.root / "workers"

    def tearDown(self):
        self.temp.cleanup()

    def prepare(self, task_id="KAN-101"):
        result = ovp.prepare_task(
            repo=self.repo,
            task_id=task_id,
            goal="Increase player speed",
            include=["src/"],
            exclude=[],
            acceptance=["unit=player speed test passes"],
            optional_acceptance=["visual=screenshot is legible"],
            workspace_root=self.workspace_root,
            domains=["CODE", "GAMEPLAY"],
        )
        self.assertEqual(result["status"], "PASS")
        return result

    def handoff(self, *, checks=None):
        return {
            "schema_version": dispatch.HANDOFF_SCHEMA_VERSION,
            "summary": "Implemented bounded player speed change",
            "checks": checks or {"unit": "PASS", "visual": "PASS"},
            "evidence": {"unit": "python test_player.py", "visual": "artifacts/player.png"},
            "artifacts": [],
            "risks": [],
            "assumptions": [],
        }

    def mutation_runner(self, *, path="src/player.gd", content="speed = 2\n", handoff=None):
        payload = handoff or self.handoff()

        def runner(command, *, cwd, input, text, capture_output, timeout, check, env):
            workspace = Path(cwd)
            target = workspace / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            git(workspace, "add", ".")
            git(workspace, "commit", "-m", "worker mutation")
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")

        return runner

    def test_provider_plans_keep_mutation_scope_explicit(self):
        workspace = self.root / "worker"
        codex = dispatch.build_provider_plan("codex", workspace=workspace, model="gpt-test", reasoning_effort="high")
        self.assertIn("workspace-write", codex.command)
        self.assertIn(str(workspace), codex.command)
        self.assertEqual(codex.output_mode, "codex-jsonl")
        claude = dispatch.build_provider_plan("claude", workspace=workspace, model="sonnet-test")
        self.assertIn("acceptEdits", claude.command)
        self.assertEqual(claude.output_mode, "claude-json")
        with self.assertRaises(dispatch.DispatchConfigError):
            dispatch.build_provider_plan("local", workspace=workspace)

    def test_codex_windows_hermetic_plan_selects_usable_sandbox_backend(self):
        workspace = self.root / "worker"
        plan = dispatch.build_provider_plan("codex", workspace=workspace, host_platform="win32")
        self.assertIn("--ignore-user-config", plan.command)
        self.assertIn('windows.sandbox="elevated"', plan.command)
        user_config = dispatch.build_provider_plan(
            "codex", workspace=workspace, host_platform="win32", keep_user_config=True
        )
        self.assertNotIn("--ignore-user-config", user_config.command)
        self.assertNotIn('windows.sandbox="elevated"', user_config.command)

    def test_codex_windows_prompt_warns_against_linked_worktree_patch_path(self):
        manifest = {
            "acceptance": [
                {"id": "unit", "required": True},
                {"id": "visual", "required": False},
            ]
        }
        prompt = dispatch.render_worker_prompt(
            manifest,
            "TASK KAN-101\nNEXT REVIEW_READY\n",
            provider="codex",
            host_platform="win32",
        )
        self.assertIn("WINDOWS CODEX LINKED-WORKTREE NOTE", prompt)
        self.assertIn("instead of relying on apply_patch", prompt)
        linux_prompt = dispatch.render_worker_prompt(
            manifest,
            "TASK KAN-101\nNEXT REVIEW_READY\n",
            provider="codex",
            host_platform="linux",
        )
        self.assertNotIn("WINDOWS CODEX LINKED-WORKTREE NOTE", linux_prompt)

    def test_custom_command_args_are_redacted_from_public_metadata(self):
        workspace = self.root / "worker"
        plan = dispatch.build_provider_plan(
            "local", workspace=workspace, command_json='["agent", "--token", "secret-value"]'
        )
        self.assertEqual(plan.command[-1], "secret-value")
        public = json.dumps(plan.public_dict())
        self.assertNotIn("secret-value", public)
        self.assertIn("custom args redacted", public)

    def test_worker_env_does_not_inherit_secret_values_by_default(self):
        source = {"PATH": "/bin", "HOME": "/tmp/home", "OPENAI_API_KEY": "secret", "CUSTOM": "ok"}
        env, names = dispatch.build_worker_env(source=source)
        self.assertEqual(env["PATH"], "/bin")
        self.assertNotIn("OPENAI_API_KEY", env)
        self.assertNotIn("CUSTOM", env)
        self.assertIn("PATH", names)
        with self.assertRaises(dispatch.DispatchConfigError):
            dispatch.build_worker_env(source=source, pass_env=["OPENAI_API_KEY"])
        allowed, _ = dispatch.build_worker_env(source=source, pass_env=["OPENAI_API_KEY"], allow_secret_env=True)
        self.assertEqual(allowed["OPENAI_API_KEY"], "secret")

    def test_handoff_parser_accepts_fenced_json_and_rejects_invalid_status(self):
        payload = self.handoff()
        parsed = dispatch.parse_handoff("done\n```json\n" + json.dumps(payload) + "\n```")
        self.assertEqual(parsed["checks"]["unit"], "PASS")
        payload["checks"]["unit"] = "MAGIC"
        with self.assertRaises(dispatch.DispatchConfigError):
            dispatch.parse_handoff(json.dumps(payload))

    def test_dry_run_keeps_task_ready_and_does_not_call_worker(self):
        self.prepare()
        called = []

        def runner(*args, **kwargs):
            called.append(True)
            raise AssertionError("dry run must not execute worker")

        result = dispatch.dispatch_task(
            repo=self.repo,
            task_id="KAN-101",
            provider="local",
            command_json='["fake-agent"]',
            dry_run=True,
            env_source={"PATH": "/bin"},
            runner=runner,
        )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(ovp._load_manifest(self.repo, "KAN-101")["state"], "READY")
        self.assertEqual(called, [])

    def test_fresh_dispatch_rejects_dirty_workspace_before_state_change(self):
        self.prepare()
        manifest = ovp._load_manifest(self.repo, "KAN-101")
        workspace = Path(manifest["workspace"])
        (workspace / "src" / "player.gd").write_text("dirty\n", encoding="utf-8")
        with self.assertRaises(dispatch.DispatchConfigError):
            dispatch.dispatch_task(
                repo=self.repo,
                task_id="KAN-101",
                provider="local",
                command_json='["fake-agent"]',
                env_source={"PATH": "/bin"},
                runner=self.mutation_runner(),
            )
        self.assertEqual(ovp._load_manifest(self.repo, "KAN-101")["state"], "READY")

    def test_dispatch_rejects_worker_branch_identity_change_before_execution(self):
        self.prepare()
        manifest = ovp._load_manifest(self.repo, "KAN-101")
        workspace = Path(manifest["workspace"])
        git(workspace, "checkout", "-b", "hijack")
        with self.assertRaises(dispatch.DispatchConfigError):
            dispatch.dispatch_task(
                repo=self.repo,
                task_id="KAN-101",
                provider="local",
                command_json='["fake-agent"]',
                env_source={"PATH": "/bin"},
                runner=self.mutation_runner(),
            )
        self.assertEqual(ovp._load_manifest(self.repo, "KAN-101")["state"], "READY")

    def test_local_dispatch_reaches_review_ready_through_authoritative_receipt(self):
        self.prepare()
        result = dispatch.dispatch_task(
            repo=self.repo,
            task_id="KAN-101",
            provider="local",
            command_json='["fake-agent"]',
            env_source={"PATH": "/bin"},
            runner=self.mutation_runner(),
        )
        self.assertEqual(result["status"], "PASS")
        manifest = ovp._load_manifest(self.repo, "KAN-101")
        self.assertEqual(manifest["state"], "REVIEW_READY")
        self.assertEqual(manifest["receipt"]["summary"], "Implemented bounded player speed change")
        self.assertEqual((Path(manifest["workspace"]) / "src" / "player.gd").read_text(encoding="utf-8"), "speed = 2\n")

    def test_out_of_scope_worker_commit_is_rejected_by_receipt_gate(self):
        self.prepare()
        result = dispatch.dispatch_task(
            repo=self.repo,
            task_id="KAN-101",
            provider="local",
            command_json='["fake-agent"]',
            env_source={"PATH": "/bin"},
            runner=self.mutation_runner(path="README.md", content="escaped\n"),
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(ovp._load_manifest(self.repo, "KAN-101")["state"], "WORKING")

    def test_invalid_handoff_leaves_working_for_explicit_recovery(self):
        self.prepare()
        bad = self.handoff(checks={"unit": "PASS"})
        result = dispatch.dispatch_task(
            repo=self.repo,
            task_id="KAN-101",
            provider="local",
            command_json='["fake-agent"]',
            env_source={"PATH": "/bin"},
            runner=self.mutation_runner(handoff=bad),
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("handoff_error", result)
        self.assertEqual(ovp._load_manifest(self.repo, "KAN-101")["state"], "WORKING")

    def test_failed_provider_can_resume_without_replaying_dispatch_transition(self):
        self.prepare()

        def failed(command, **kwargs):
            return subprocess.CompletedProcess(command, 7, stdout="", stderr="worker crashed")

        first = dispatch.dispatch_task(
            repo=self.repo,
            task_id="KAN-101",
            provider="local",
            command_json='["fake-agent"]',
            env_source={"PATH": "/bin"},
            runner=failed,
        )
        self.assertEqual(first["status"], "FAIL")
        self.assertEqual(ovp._load_manifest(self.repo, "KAN-101")["state"], "WORKING")
        second = dispatch.dispatch_task(
            repo=self.repo,
            task_id="KAN-101",
            provider="local",
            command_json='["fake-agent"]',
            env_source={"PATH": "/bin"},
            runner=self.mutation_runner(),
            resume=True,
        )
        self.assertEqual(second["status"], "PASS")
        self.assertEqual(ovp._load_manifest(self.repo, "KAN-101")["state"], "REVIEW_READY")

    def test_worker_cannot_skip_commit_and_still_reach_review_ready(self):
        self.prepare()
        payload = self.handoff()

        def no_commit(command, *, cwd, input, text, capture_output, timeout, check, env):
            (Path(cwd) / "src" / "player.gd").write_text("speed = 3\n", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")

        result = dispatch.dispatch_task(
            repo=self.repo,
            task_id="KAN-101",
            provider="local",
            command_json='["fake-agent"]',
            env_source={"PATH": "/bin"},
            runner=no_commit,
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("receipt_error", result)
        self.assertEqual(ovp._load_manifest(self.repo, "KAN-101")["state"], "WORKING")


if __name__ == "__main__":
    unittest.main()

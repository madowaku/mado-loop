import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

MODULE_PATH = Path(__file__).parents[2] / ".agents" / "skills" / "mado-loop" / "scripts" / "ovp_runtime.py"
SPEC = importlib.util.spec_from_file_location("ovp_runtime", MODULE_PATH)
ovp = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(ovp)


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    cp = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8")
    if check and cp.returncode != 0:
        raise AssertionError(f"git failed: {args}: {cp.stderr}")
    return cp


class OvpRuntimeTests(unittest.TestCase):
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

    def prepare(self, task_id="KAN-001", include=None):
        return ovp.prepare_task(
            repo=self.repo, task_id=task_id, goal="Increase player speed",
            include=include or ["src/"], exclude=[], acceptance=["unit=player speed test passes"],
            optional_acceptance=["visual=screenshot is legible"], workspace_root=self.workspace_root,
            domains=["CODE", "GAMEPLAY"],
        )

    def mutate_and_commit(self, task_id="KAN-001", path="src/player.gd", content="speed = 2\n"):
        manifest = ovp._load_manifest(self.repo, task_id)
        workspace = Path(manifest["workspace"])
        target = workspace / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        git(workspace, "add", ".")
        git(workspace, "commit", "-m", "worker change")
        return workspace

    def receipt(self, workspace, task_id="KAN-001", unit="PASS", visual="PASS"):
        return ovp.submit_receipt(
            repo=workspace, task_id=task_id, summary="Implemented bounded change",
            checks=[f"unit={unit}"], optional_checks=[f"visual={visual}"],
            evidence=["unit=python test_player.py", "visual=screenshot.png"],
        )

    def test_preflight_uses_real_disposable_worktree_and_cleans_it(self):
        result = ovp.preflight(repo=self.repo, workspace_root=self.workspace_root, domains=["CODE"])
        self.assertEqual(result["status"], "PASS")
        by_id = {item["id"]: item for item in result["checks"]}
        self.assertEqual(by_id["ovp.worktree_roundtrip"]["status"], "PASS")
        self.assertEqual(by_id["ovp.commit_roundtrip"]["status"], "PASS")
        self.assertEqual(list(self.workspace_root.glob(".preflight-*")), [])

    def test_preflight_blocks_dirty_leader_by_default(self):
        (self.repo / "README.md").write_text("dirty\n", encoding="utf-8")
        result = ovp.preflight(repo=self.repo, workspace_root=self.workspace_root)
        self.assertEqual(result["status"], "FAIL")
        by_id = {item["id"]: item for item in result["checks"]}
        self.assertEqual(by_id["ovp.repo_clean"]["status"], "FAIL")

    def test_prepare_writes_manifest_and_ai_creole_contract_outside_worktree(self):
        result = self.prepare()
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["environment"]["ovp_state"], "READY")
        manifest = ovp._load_manifest(self.repo, "KAN-001")
        self.assertEqual(manifest["state"], "READY")
        self.assertTrue(Path(manifest["workspace"]).is_dir())
        contract_path = Path(result["environment"]["contract_path"])
        self.assertIn("TASK KAN-001", contract_path.read_text(encoding="utf-8"))
        self.assertNotEqual(contract_path.parent, Path(manifest["workspace"]))

    def test_receipt_rejects_out_of_scope_change(self):
        self.prepare()
        workspace = self.mutate_and_commit(path="README.md", content="escaped\n")
        result = self.receipt(workspace)
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(ovp._load_manifest(self.repo, "KAN-001")["state"], "READY")

    def test_receipt_requires_clean_committed_change_and_exact_acceptance_ids(self):
        self.prepare()
        manifest = ovp._load_manifest(self.repo, "KAN-001")
        workspace = Path(manifest["workspace"])
        (workspace / "src" / "player.gd").write_text("speed = 2\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.receipt(workspace)
        git(workspace, "add", ".")
        git(workspace, "commit", "-m", "worker change")
        with self.assertRaises(ValueError):
            ovp.submit_receipt(repo=workspace, task_id="KAN-001", summary="x", checks=["unit=PASS"])

    def test_acceptance_gate_requires_diff_inspection_and_required_pass(self):
        self.prepare()
        workspace = self.mutate_and_commit()
        self.receipt(workspace)
        blocked = ovp.review_task(repo=self.repo, task_id="KAN-001", decision="accept", reason="looks good")
        self.assertEqual(blocked["status"], "FAIL")
        self.assertEqual(ovp._load_manifest(self.repo, "KAN-001")["state"], "REVIEW_READY")
        accepted = ovp.review_task(repo=self.repo, task_id="KAN-001", decision="accept", reason="diff inspected", inspected_diff=True)
        self.assertEqual(accepted["status"], "PASS")
        self.assertEqual(ovp._load_manifest(self.repo, "KAN-001")["state"], "ACCEPTED")

    def test_review_blocks_worker_head_change_after_receipt(self):
        self.prepare()
        workspace = self.mutate_and_commit()
        self.receipt(workspace)
        (workspace / "src" / "player.gd").write_text("speed = 3\n", encoding="utf-8")
        git(workspace, "add", ".")
        git(workspace, "commit", "-m", "post receipt tamper")
        blocked = ovp.review_task(
            repo=self.repo, task_id="KAN-001", decision="accept",
            reason="tamper should block", inspected_diff=True,
        )
        self.assertEqual(blocked["status"], "FAIL")
        by_id = {item["id"]: item for item in blocked["checks"]}
        self.assertEqual(by_id["ovp.review.head_stable"]["status"], "FAIL")
        self.assertEqual(ovp._load_manifest(self.repo, "KAN-001")["state"], "REVIEW_READY")

    def test_required_worker_check_failure_blocks_accept_but_allows_rework(self):
        self.prepare()
        workspace = self.mutate_and_commit()
        receipt = self.receipt(workspace, unit="FAIL")
        self.assertEqual(receipt["status"], "FAIL")
        blocked = ovp.review_task(repo=self.repo, task_id="KAN-001", decision="accept", reason="cannot accept", inspected_diff=True)
        self.assertEqual(blocked["status"], "FAIL")
        rework = ovp.review_task(repo=self.repo, task_id="KAN-001", decision="rework", reason="fix unit check", inspected_diff=True)
        self.assertEqual(rework["status"], "PASS")
        self.assertEqual(ovp._load_manifest(self.repo, "KAN-001")["state"], "REWORK")

    def test_merge_integration_then_schema_proof_reaches_proven(self):
        self.prepare()
        workspace = self.mutate_and_commit()
        self.receipt(workspace)
        ovp.review_task(repo=self.repo, task_id="KAN-001", decision="accept", reason="diff inspected", inspected_diff=True)
        integrated = ovp.integrate_task(repo=self.repo, task_id="KAN-001", strategy="merge")
        self.assertEqual(integrated["status"], "PASS")
        self.assertEqual((self.repo / "src" / "player.gd").read_text(encoding="utf-8"), "speed = 2\n")
        self.assertEqual(ovp._load_manifest(self.repo, "KAN-001")["state"], "INTEGRATED")
        proof_file = self.root / "proof.json"
        proof_file.write_text(json.dumps({"schema_version":"1.1","status":"PASS","proof_level":"P3"}), encoding="utf-8")
        proven = ovp.record_proof(repo=self.repo, task_id="KAN-001", result_path=proof_file)
        self.assertEqual(proven["status"], "PASS")
        self.assertEqual(ovp._load_manifest(self.repo, "KAN-001")["state"], "PROVEN")

    def test_cleanup_only_removes_owned_clean_worktree_and_preserves_branch_by_default(self):
        self.prepare()
        workspace = self.mutate_and_commit()
        self.receipt(workspace)
        ovp.review_task(repo=self.repo, task_id="KAN-001", decision="accept", reason="diff inspected", inspected_diff=True)
        ovp.integrate_task(repo=self.repo, task_id="KAN-001")
        proof_file = self.root / "proof.json"
        proof_file.write_text(json.dumps({"schema_version":"1.1","status":"PASS","proof_level":"P2"}), encoding="utf-8")
        ovp.record_proof(repo=self.repo, task_id="KAN-001", result_path=proof_file)
        cleaned = ovp.cleanup_task(repo=self.repo, task_id="KAN-001")
        self.assertEqual(cleaned["status"], "PASS")
        self.assertFalse(workspace.exists())
        self.assertEqual(git(self.repo, "show-ref", "--verify", "refs/heads/mado/ovp/KAN-001", check=False).returncode, 0)

    def test_cleanup_refuses_dirty_rejected_worktree(self):
        self.prepare()
        workspace = self.mutate_and_commit()
        self.receipt(workspace)
        rejected = ovp.review_task(
            repo=self.repo, task_id="KAN-001", decision="reject",
            reason="not wanted", inspected_diff=True,
        )
        self.assertEqual(rejected["status"], "PASS")
        (workspace / "src" / "player.gd").write_text("uncommitted\n", encoding="utf-8")
        cleanup = ovp.cleanup_task(repo=self.repo, task_id="KAN-001")
        self.assertEqual(cleanup["status"], "FAIL")
        self.assertTrue(workspace.exists())
        by_id = {item["id"]: item for item in cleanup["checks"]}
        self.assertEqual(by_id["ovp.cleanup.workspace_clean"]["status"], "FAIL")

    def test_proof_is_blocked_when_leader_head_moves_after_integration(self):
        self.prepare()
        workspace = self.mutate_and_commit()
        self.receipt(workspace)
        ovp.review_task(repo=self.repo, task_id="KAN-001", decision="accept", reason="diff inspected", inspected_diff=True)
        ovp.integrate_task(repo=self.repo, task_id="KAN-001")
        (self.repo / "README.md").write_text("later\n", encoding="utf-8")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-m", "later")
        proof_file = self.root / "proof.json"
        proof_file.write_text(json.dumps({"schema_version":"1.1","status":"PASS","proof_level":"P3"}), encoding="utf-8")
        result = ovp.record_proof(repo=self.repo, task_id="KAN-001", result_path=proof_file)
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(ovp._load_manifest(self.repo, "KAN-001")["state"], "INTEGRATED")


if __name__ == "__main__":
    unittest.main()

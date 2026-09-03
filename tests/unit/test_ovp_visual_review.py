import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

MODULE_PATH = Path(__file__).parents[2] / ".agents" / "skills" / "mado-loop" / "scripts" / "ovp_visual_review.py"
SPEC = importlib.util.spec_from_file_location("ovp_visual_review", MODULE_PATH)
visual_review = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = visual_review
assert SPEC.loader is not None
SPEC.loader.exec_module(visual_review)


class OvpVisualReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.leader = self.root / "leader"
        self.workspace = self.root / "worker"
        self.state = self.root / "state"
        self.leader.mkdir()
        self.workspace.mkdir()
        self.state.mkdir()
        self.head = "a" * 40
        self.task_id = "VIS-1"
        self.manifest = {"task_domains": ["UI"], "state": "REVIEW_READY"}

    def tearDown(self):
        self.temp.cleanup()

    def context(self):
        return self.leader, self.manifest, self.workspace, self.head

    def atomic_record(self, payload):
        path = self.state / "visual-review.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def capture_patches(self, capture_status="PASS", stop_status="PASS", write_capture=True):
        def capture(**kwargs):
            if write_capture:
                output = Path(kwargs["output"])
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(b"png-evidence")
            return {"status": capture_status, "summary": capture_status}

        return (
            mock.patch.object(visual_review, "_context", return_value=self.context()),
            mock.patch.object(visual_review.ovp, "_task_dir", return_value=self.state),
            mock.patch.object(visual_review.ovp, "_commit", return_value=self.head),
            mock.patch.object(visual_review.ovp, "_clean", return_value=True),
            mock.patch.object(visual_review.visual, "launch_session", return_value={"status": "PASS"}),
            mock.patch.object(visual_review.visual, "capture_session", side_effect=capture),
            mock.patch.object(visual_review.visual, "stop_session", return_value={"status": stop_status}),
        )

    def test_capture_persists_hashed_artifact_and_cleans_temp(self):
        patches = self.capture_patches()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
            result = visual_review.capture_visual_evidence(
                repo=self.leader, task_id=self.task_id, godot_bin="godot.exe"
            )
        self.assertEqual(result["status"], "PASS")
        durable = self.state / "visual" / f"{self.head[:16]}.png"
        self.assertTrue(durable.is_file())
        self.assertFalse((self.workspace / ".mado-loop-visual" / f"{self.task_id}.png").exists())
        record = json.loads((self.state / "visual-review.json").read_text(encoding="utf-8"))
        self.assertEqual(record["artifact"]["sha256"], visual_review.make_artifact(durable, "visual-review")["sha256"])

    def test_capture_unknown_records_no_durable_artifact(self):
        patches = self.capture_patches(capture_status="UNKNOWN", write_capture=False)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
            result = visual_review.capture_visual_evidence(
                repo=self.leader, task_id=self.task_id, godot_bin="godot.exe"
            )
        self.assertEqual(result["status"], "UNKNOWN")
        record = json.loads((self.state / "visual-review.json").read_text(encoding="utf-8"))
        self.assertIsNone(record["artifact"])
        self.assertEqual(record["capture_status"], "UNKNOWN")

    def review_record(self, *, capture_status="PASS", with_artifact=True):
        artifact = None
        if with_artifact:
            path = self.state / "visual" / f"{self.head[:16]}.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"png-evidence")
            artifact = visual_review.make_artifact(path, "visual-review")
        return {
            "schema_version": visual_review.RECORD_SCHEMA,
            "task_id": self.task_id,
            "worker_head": self.head,
            "capture_status": capture_status,
            "stop_status": "PASS" if capture_status == "PASS" else "UNKNOWN",
            "artifact": artifact,
            "review": None,
        }

    def test_accept_requires_explicit_visual_inspection(self):
        self.atomic_record(self.review_record())
        reviewer = mock.Mock()
        with mock.patch.object(visual_review, "_context", return_value=self.context()), \
             mock.patch.object(visual_review.ovp, "_task_dir", return_value=self.state), \
             mock.patch.object(visual_review.ovp, "review_task", reviewer):
            result = visual_review.review_with_visual_evidence(
                repo=self.leader, task_id=self.task_id, decision="accept", reason="looks good",
                inspected_diff=True, inspected_visual=False,
            )
        self.assertEqual(result["status"], "FAIL")
        self.assertFalse(reviewer.called)
        self.assertEqual(result["environment"]["ovp_state"], "REVIEW_READY")

    def test_accept_calls_ovp_review_with_visual_hash(self):
        record = self.review_record()
        self.atomic_record(record)
        reviewer = mock.Mock(return_value={
            "status": "PASS", "summary": "accepted", "environment": {"ovp_state": "ACCEPTED"}
        })
        with mock.patch.object(visual_review, "_context", return_value=self.context()), \
             mock.patch.object(visual_review.ovp, "_task_dir", return_value=self.state), \
             mock.patch.object(visual_review.ovp, "review_task", reviewer):
            result = visual_review.review_with_visual_evidence(
                repo=self.leader, task_id=self.task_id, decision="accept", reason="visual verified",
                inspected_diff=True, inspected_visual=True,
            )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["environment"]["ovp_state"], "ACCEPTED")
        reason = reviewer.call_args.kwargs["reason"]
        self.assertIn(record["artifact"]["sha256"], reason)

    def test_accept_rejects_tampered_visual_artifact(self):
        record = self.review_record()
        self.atomic_record(record)
        Path(record["artifact"]["path"]).write_bytes(b"tampered")
        reviewer = mock.Mock()
        with mock.patch.object(visual_review, "_context", return_value=self.context()), \
             mock.patch.object(visual_review.ovp, "_task_dir", return_value=self.state), \
             mock.patch.object(visual_review.ovp, "review_task", reviewer):
            result = visual_review.review_with_visual_evidence(
                repo=self.leader, task_id=self.task_id, decision="accept", reason="accept",
                inspected_diff=True, inspected_visual=True,
            )
        self.assertEqual(result["status"], "FAIL")
        self.assertFalse(reviewer.called)

    def test_accept_blocks_when_broker_stop_failed(self):
        record = self.review_record()
        record["stop_status"] = "FAIL"
        self.atomic_record(record)
        reviewer = mock.Mock()
        with mock.patch.object(visual_review, "_context", return_value=self.context()), \
             mock.patch.object(visual_review.ovp, "_task_dir", return_value=self.state), \
             mock.patch.object(visual_review.ovp, "review_task", reviewer):
            result = visual_review.review_with_visual_evidence(
                repo=self.leader, task_id=self.task_id, decision="accept", reason="accept",
                inspected_diff=True, inspected_visual=True,
            )
        self.assertEqual(result["status"], "FAIL")
        self.assertFalse(reviewer.called)

    def test_rework_can_proceed_when_capture_is_unavailable(self):
        self.atomic_record(self.review_record(capture_status="UNKNOWN", with_artifact=False))
        reviewer = mock.Mock(return_value={
            "status": "PASS", "summary": "rework", "environment": {"ovp_state": "REWORK"}
        })
        with mock.patch.object(visual_review, "_context", return_value=self.context()), \
             mock.patch.object(visual_review.ovp, "_task_dir", return_value=self.state), \
             mock.patch.object(visual_review.ovp, "review_task", reviewer):
            result = visual_review.review_with_visual_evidence(
                repo=self.leader, task_id=self.task_id, decision="rework", reason="needs changes"
            )
        self.assertEqual(result["environment"]["ovp_state"], "REWORK")
        self.assertTrue(reviewer.called)


if __name__ == "__main__":
    unittest.main()

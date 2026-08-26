from __future__ import annotations

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / ".agents" / "skills" / "mado-loop" / "scripts" / "make_proof_sheet.py"
SPEC = importlib.util.spec_from_file_location("make_proof_sheet", MODULE_PATH)
assert SPEC and SPEC.loader
proof = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(proof)


class FakeRunner:
    def __init__(self, *, duration: str = "8.0", fail_at: int | None = None, timeout_at: int | None = None):
        self.duration = duration
        self.fail_at = fail_at
        self.timeout_at = timeout_at
        self.commands: list[list[str]] = []

    def __call__(self, command, **kwargs):
        self.commands.append(command)
        call = len(self.commands)
        if self.timeout_at == call:
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        if call == 1:
            return subprocess.CompletedProcess(command, 0, f'{{"format":{{"duration":"{self.duration}"}}}}', "")
        if self.fail_at == call:
            return subprocess.CompletedProcess(command, 1, "", "failed")
        Path(command[-1]).write_bytes(b"image-" + str(call).encode())
        return subprocess.CompletedProcess(command, 0, "", "")


class ProofSheetTests(unittest.TestCase):
    def test_duration_sampling_and_unicode_space_safe_commands(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "映像 source.mp4"
            output = root / "証拠 sheet.png"
            source.write_bytes(b"video")
            runner = FakeRunner(duration="8")
            result = proof.make_proof_sheet(source, output, count=4, columns=2, width=160, height=90, ffprobe="probe", ffmpeg="mpeg", runner=runner)
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["checks"][0]["details"]["timestamps"], [1.0, 3.0, 5.0, 7.0])
            self.assertEqual(result["checks"][0]["details"]["rows"], 2)
            self.assertIn(str(source), runner.commands[0])
            self.assertIn("scale=160:90:force_original_aspect_ratio=decrease,pad=160:90:(ow-iw)/2:(oh-ih)/2:black", runner.commands[1])
            self.assertIn("tile=2x2:nb_frames=4:padding=0:margin=0", runner.commands[-1])
            self.assertEqual(source.read_bytes(), b"video")
            self.assertTrue(output.is_file())

    def test_missing_tools_is_unknown(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "in.mp4"
            source.write_bytes(b"video")
            with mock.patch.object(proof.shutil, "which", return_value=None):
                result = proof.make_proof_sheet(source, Path(temporary) / "out.png")
            self.assertEqual(result["status"], "UNKNOWN")

    def test_invalid_probe_and_command_failure_are_fail(self):
        for runner in (FakeRunner(duration="bad"), FakeRunner(fail_at=2)):
            with self.subTest(runner=runner), tempfile.TemporaryDirectory() as temporary:
                source = Path(temporary) / "in.mp4"
                source.write_bytes(b"video")
                result = proof.make_proof_sheet(source, Path(temporary) / "out.png", ffprobe="probe", ffmpeg="mpeg", runner=runner)
                self.assertEqual(result["status"], "FAIL")

    def test_timeout_is_fail_and_leaves_existing_output_atomic(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "in.mp4"
            output = root / "out.png"
            source.write_bytes(b"video")
            output.write_bytes(b"old")
            result = proof.make_proof_sheet(source, output, count=2, ffprobe="probe", ffmpeg="mpeg", runner=FakeRunner(timeout_at=2))
            self.assertEqual(result["status"], "FAIL")
            self.assertEqual(output.read_bytes(), b"old")
            self.assertEqual(source.read_bytes(), b"video")

    def test_atomic_assembly_failure_preserves_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "in.mp4"
            output = root / "out.png"
            source.write_bytes(b"video")
            output.write_bytes(b"old")
            result = proof.make_proof_sheet(source, output, count=2, ffprobe="probe", ffmpeg="mpeg", runner=FakeRunner(fail_at=4))
            self.assertEqual(result["status"], "FAIL")
            self.assertEqual(output.read_bytes(), b"old")

    def test_source_hash_change_fails_before_replace(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "in.mp4"
            output = root / "out.png"
            source.write_bytes(b"video")
            runner = FakeRunner()

            def mutating_runner(command, **kwargs):
                completed = runner(command, **kwargs)
                if len(runner.commands) == 2:
                    source.write_bytes(b"changed")
                return completed

            result = proof.make_proof_sheet(source, output, count=1, ffprobe="probe", ffmpeg="mpeg", runner=mutating_runner)
            self.assertEqual(result["status"], "FAIL")
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()

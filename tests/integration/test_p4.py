from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / ".agents" / "skills" / "mado-loop" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from common.motion_proof import run_p4_motion  # noqa: E402


class P4IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        configured = os.environ.get("MADO_GODOT_BIN", "")
        if not configured or not Path(configured).is_file():
            raise unittest.SkipTest("MADO_GODOT_BIN is not an available file")
        cls.godot_bin = Path(configured)
        cls.ffmpeg = shutil.which("ffmpeg")
        cls.ffprobe = shutil.which("ffprobe")
        if not cls.ffmpeg or not cls.ffprobe:
            raise unittest.SkipTest("ffmpeg and ffprobe are required")
        cls.fixture = ROOT / "tests" / "fixtures" / "godot-motion"

    def _run(self, project: Path, output: Path) -> dict[str, object]:
        return run_p4_motion(
            godot_bin=self.godot_bin, project_path=project, output_dir=output,
            fps=12, expected_frames=24, timeout=60.0,
            ffmpeg=self.ffmpeg, ffprobe=self.ffprobe,
        )

    def test_actual_movie_and_proof_sheet_pass(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mado-p4-") as temporary:
            result = self._run(self.fixture, Path(temporary) / "proof")
            artifacts = result["artifacts"]
            self.assertEqual(result["status"], "PASS", result)
            self.assertEqual(result["schema_version"], "1.1")
            self.assertEqual(result["proof_level"], "P4")
            self.assertEqual(result["environment"]["captured_frames"], 24)
            self.assertEqual(result["environment"]["captured_fps"], 12.0)
            self.assertTrue(all(item["exists"] and item["size_bytes"] > 0 for item in artifacts))

    def test_stable_rerun_evidence(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mado-p4-stable-") as temporary:
            root = Path(temporary)
            first = self._run(self.fixture, root / "one")
            second = self._run(self.fixture, root / "two")
        self.assertEqual(first["status"], "PASS", first)
        self.assertEqual(second["status"], "PASS", second)
        for key in ("captured_frames", "captured_fps", "source_sha256_before", "source_sha256_after"):
            self.assertEqual(first["environment"][key], second["environment"][key])

    def test_unicode_space_copy_preserves_source_hash(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mado-p4-copy-") as temporary:
            root = Path(temporary)
            copied = root / "日本語 space" / "motion fixture"
            shutil.copytree(self.fixture, copied)
            result = self._run(copied, root / "出力 proof")
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual(result["environment"]["source_sha256_before"], result["environment"]["source_sha256_after"])

    def test_missing_tool_is_unknown(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mado-p4-unknown-") as temporary:
            result = run_p4_motion(
                godot_bin=Path(temporary) / "missing-godot.exe", project_path=self.fixture,
                output_dir=Path(temporary) / "proof", ffmpeg=self.ffmpeg, ffprobe=self.ffprobe,
            )
        self.assertEqual(result["status"], "UNKNOWN", result)


if __name__ == "__main__":
    unittest.main()

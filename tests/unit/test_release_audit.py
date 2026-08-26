import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile


SCRIPT = Path(__file__).parents[2] / ".agents" / "skills" / "mado-loop" / "scripts" / "release_audit.py"
SPEC = importlib.util.spec_from_file_location("release_audit", SCRIPT)
release_audit = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(release_audit)


class ReleaseAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "成果物 space"
        self.root.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def package(self, name, entries):
        path = self.root / name
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
            for member, data in entries:
                archive.writestr(member, data)
        return path

    def test_apk_pass_with_signature_and_unicode_path(self):
        path = self.package("ゲーム build.apk", [("AndroidManifest.xml", b"m"), ("classes.dex", b"d"), ("META-INF/CERT.RSA", b"s")])
        result = release_audit.audit_release(path)
        self.assertEqual("PASS", result["status"])
        self.assertEqual(["RELEASE"], result["task_domains"])
        self.assertEqual(64, len(result["artifacts"][0]["sha256"]))

    def test_aab_pass_has_distinct_structure(self):
        path = self.package("game.aab", [("BundleConfig.pb", b"b"), ("base/manifest/AndroidManifest.xml", b"m"), ("base/dex/classes.dex", b"d")])
        self.assertEqual("PASS", release_audit.audit_release(path)["status"])

    def test_unsigned_apk_is_warn_not_skipped_operation(self):
        path = self.package("game.apk", [("AndroidManifest.xml", b"m"), ("classes.dex", b"d")])
        result = release_audit.audit_release(path)
        self.assertEqual("WARN", result["status"])
        self.assertEqual("SKIPPED", next(c for c in result["checks"] if c["id"] == "signature.presence")["status"])

    def test_corrupt_zip_and_wrong_contents_fail(self):
        corrupt = self.root / "bad.apk"
        corrupt.write_bytes(b"not zip")
        self.assertEqual("FAIL", release_audit.audit_release(corrupt)["status"])
        wrong = self.package("wrong.aab", [("AndroidManifest.xml", b"m")])
        self.assertEqual("FAIL", release_audit.audit_release(wrong)["status"])

    def test_missing_and_wrong_extension_fail(self):
        self.assertEqual("FAIL", release_audit.audit_release(self.root / "missing.apk")["status"])
        wrong = self.package("game.zip", [("AndroidManifest.xml", b"m"), ("classes.dex", b"d")])
        self.assertEqual("FAIL", release_audit.audit_release(wrong, artifact_type="apk")["status"])

    def test_traversal_and_confusing_duplicates_fail(self):
        path = self.package("unsafe.apk", [("AndroidManifest.xml", b"m"), ("classes.dex", b"d"), ("../evil", b"x"), ("CLASSES.DEX", b"x")])
        result = release_audit.audit_release(path)
        self.assertEqual("FAIL", result["status"])
        check = next(c for c in result["checks"] if c["id"] == "archive.safe_names")
        self.assertTrue(check["details"]["unsafe"])
        self.assertTrue(check["details"]["confusing_duplicates"])

    @mock.patch.object(release_audit.shutil, "which", return_value=None)
    def test_requested_metadata_tool_absence_is_unknown(self, _which):
        path = self.package("game.apk", [("AndroidManifest.xml", b"m"), ("classes.dex", b"d"), ("META-INF/CERT.RSA", b"s")])
        self.assertEqual("UNKNOWN", release_audit.audit_release(path, verify_signature=True)["status"])

    @mock.patch.object(release_audit.subprocess, "run")
    def test_metadata_tool_failure_is_fail(self, run):
        run.return_value = mock.Mock(returncode=1, stdout="", stderr="verification failed")
        path = self.package("game.apk", [("AndroidManifest.xml", b"m"), ("classes.dex", b"d"), ("META-INF/CERT.RSA", b"s")])
        result = release_audit.audit_release(path, verify_signature=True, apksigner="tool")
        self.assertEqual("FAIL", result["status"])
        run.assert_called_once()

    @mock.patch.object(release_audit.subprocess, "run", side_effect=TimeoutError)
    def test_metadata_tool_timeout_is_unknown(self, _run):
        path = self.package("game.apk", [("AndroidManifest.xml", b"m"), ("classes.dex", b"d"), ("META-INF/CERT.RSA", b"s")])
        result = release_audit.audit_release(path, verify_signature=True, apksigner="tool")
        self.assertEqual("UNKNOWN", result["status"])

    def test_serialization_is_deterministic_except_duration(self):
        path = self.package("game.apk", [("classes.dex", b"d"), ("AndroidManifest.xml", b"m"), ("META-INF/CERT.RSA", b"s")])
        one = release_audit.audit_release(path)
        two = release_audit.audit_release(path)
        one["duration_ms"] = two["duration_ms"] = 0
        self.assertEqual(json.dumps(one, ensure_ascii=False, separators=(",", ":")), json.dumps(two, ensure_ascii=False, separators=(",", ":")))

    def test_cli_exit_and_human_output(self):
        path = self.package("game.apk", [("AndroidManifest.xml", b"m"), ("classes.dex", b"d"), ("META-INF/CERT.RSA", b"s")])
        self.assertEqual(0, release_audit.main([str(path)]))
        self.assertIn("MADO Release Audit: PASS", release_audit.human_output(release_audit.audit_release(path)))
        self.assertEqual(64, release_audit.main([str(path), "--timeout", "0"]))


if __name__ == "__main__":
    unittest.main()

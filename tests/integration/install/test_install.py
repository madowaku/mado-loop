from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
INSTALL = ROOT / "scripts" / "install.ps1"
UNINSTALL = ROOT / "scripts" / "uninstall.ps1"
PACKAGE = ROOT / "scripts" / "package.py"
SHELLS = ("powershell.exe", "pwsh.exe")
MARKER = ".mado-loop-install.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class InstallIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workspace = Path(tempfile.mkdtemp(prefix="mado-install-suite-"))
        cls.package = cls.workspace / "mado-loop.zip"
        subprocess.run(
            [os.environ.get("PYTHON", "python"), str(PACKAGE), "--output", str(cls.package), "--json"],
            cwd=ROOT, check=True, capture_output=True, text=True,
        )
        cls.real_target = Path.home() / ".agents" / "skills" / "mado-loop"
        cls.real_before = cls._tree_fingerprint(cls.real_target)
        for shell in SHELLS:
            found = shutil.which(shell)
            if found is None:
                raise AssertionError(f"required shell unavailable: {shell}")
            version = subprocess.run(
                [found, "-NoProfile", "-Command", "$PSVersionTable.PSVersion.ToString()"],
                check=True, capture_output=True, text=True,
            ).stdout.strip()
            if shell == "powershell.exe" and not version.startswith("5.1"):
                raise AssertionError(f"expected PowerShell 5.1, got {version}")
            if shell == "pwsh.exe" and not version.startswith("7.6.3"):
                raise AssertionError(f"expected pwsh 7.6.3, got {version}")

    @classmethod
    def tearDownClass(cls) -> None:
        if cls._tree_fingerprint(cls.real_target) != cls.real_before:
            raise AssertionError("real home skill tree was touched")
        shutil.rmtree(cls.workspace, ignore_errors=True)

    @staticmethod
    def _tree_fingerprint(root: Path) -> tuple[tuple[str, str], ...]:
        if not root.exists():
            return ()
        return tuple(sorted((p.relative_to(root).as_posix(), sha(p)) for p in root.rglob("*") if p.is_file()))

    def home(self, label: str) -> Path:
        path = self.workspace / label
        path.mkdir()
        return path

    def invoke(self, shell: str, script: Path, home: Path, *, package: Path | None = None,
               version: str | None = None, extra: list[str] | None = None,
               expect: int = 0, testing: bool = False) -> subprocess.CompletedProcess[str]:
        cmd = [shutil.which(shell) or shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
               "-HomePath", str(home)]
        if package is not None:
            cmd += ["-PackagePath", str(package), "-Mode", "Release"]
        if version is not None:
            cmd += ["-Version", version]
        cmd += extra or []
        env = os.environ.copy()
        if testing:
            env["MADO_LOOP_INSTALL_TESTING"] = "1"
        result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
        self.assertEqual(expect, result.returncode, result.stdout + result.stderr)
        return result

    @staticmethod
    def result_json(result: subprocess.CompletedProcess[str]) -> dict[str, object]:
        lines = [line for line in result.stdout.splitlines() if line.strip().startswith("{")]
        return json.loads(lines[-1])

    def test_clean_install_and_package_marker_hashes(self) -> None:
        for shell in SHELLS:
            with self.subTest(shell=shell):
                home = self.home("clean-" + shell)
                result = self.invoke(shell, INSTALL, home, package=self.package, version="1.0.0")
                data = self.result_json(result)
                target = home / ".agents" / "skills" / "mado-loop"
                marker = json.loads((target / MARKER).read_text(encoding="utf-8"))
                self.assertEqual("install", data["operation"])
                self.assertEqual(sha(self.package), marker["package_sha256"])
                self.assertEqual("mado-loop", marker["product"])
                for name, digest in marker["files"].items():
                    self.assertEqual(digest, sha(target / Path(name)))

    def test_reinstall_and_upgrade(self) -> None:
        for shell in SHELLS:
            with self.subTest(shell=shell):
                home = self.home("upgrade-" + shell)
                self.invoke(shell, INSTALL, home, package=self.package, version="1.0.0")
                same = self.result_json(self.invoke(shell, INSTALL, home, package=self.package, version="1.0.0"))
                up = self.result_json(self.invoke(shell, INSTALL, home, package=self.package, version="1.1.0"))
                self.assertEqual("reinstall", same["operation"])
                self.assertEqual("upgrade", up["operation"])
                self.assertEqual("1.0.0", up["previous_version"])

    def test_unmarked_and_malformed_collision_refused(self) -> None:
        for shell in SHELLS:
            for malformed in (False, True):
                with self.subTest(shell=shell, malformed=malformed):
                    home = self.home(f"collision-{shell}-{malformed}")
                    target = home / ".agents" / "skills" / "mado-loop"
                    target.mkdir(parents=True)
                    (target / "keep.txt").write_text("keep", encoding="utf-8")
                    if malformed:
                        (target / MARKER).write_text("{bad", encoding="utf-8")
                    self.invoke(shell, INSTALL, home, package=self.package, version="1.0.0", expect=1)
                    self.assertEqual("keep", (target / "keep.txt").read_text(encoding="utf-8"))

    def test_dirty_modified_and_untracked_upgrade_refused(self) -> None:
        for shell in SHELLS:
            for dirty in ("modified", "untracked"):
                with self.subTest(shell=shell, dirty=dirty):
                    home = self.home(f"dirty-{shell}-{dirty}")
                    self.invoke(shell, INSTALL, home, package=self.package, version="1.0.0")
                    target = home / ".agents" / "skills" / "mado-loop"
                    if dirty == "modified":
                        with (target / "SKILL.md").open("a", encoding="utf-8") as stream:
                            stream.write("dirty")
                    else:
                        (target / "untracked.txt").write_text("mine", encoding="utf-8")
                    before = self._tree_fingerprint(target)
                    self.invoke(shell, INSTALL, home, package=self.package, version="1.1.0", expect=1)
                    self.assertEqual(before, self._tree_fingerprint(target))

    def test_post_backup_failure_restores_exact_tree(self) -> None:
        for shell in SHELLS:
            with self.subTest(shell=shell):
                home = self.home("rollback-" + shell)
                self.invoke(shell, INSTALL, home, package=self.package, version="1.0.0")
                target = home / ".agents" / "skills" / "mado-loop"
                before = self._tree_fingerprint(target)
                self.invoke(shell, INSTALL, home, package=self.package, version="1.1.0",
                            extra=["-InjectPostBackupFailure"], expect=1, testing=True)
                self.assertEqual(before, self._tree_fingerprint(target))
                skills = target.parent
                self.assertFalse(list(skills.glob(".mado-loop.stage.*")))
                self.assertFalse(list(skills.glob(".mado-loop.backup.*")))

    def test_rollback_restore_failure_preserves_sole_exact_backup(self) -> None:
        for shell in SHELLS:
            with self.subTest(shell=shell):
                home = self.home("rollback-preserve-" + shell)
                self.invoke(shell, INSTALL, home, package=self.package, version="1.0.0")
                target = home / ".agents" / "skills" / "mado-loop"
                before = self._tree_fingerprint(target)
                self.invoke(shell, INSTALL, home, package=self.package, version="1.1.0",
                            extra=["-InjectRollbackRestoreFailure"], expect=1, testing=True)
                self.assertFalse(target.exists())
                skills = target.parent
                backups = list(skills.glob(".mado-loop.backup.*"))
                self.assertEqual(1, len(backups))
                self.assertEqual(before, self._tree_fingerprint(backups[0]))
                self.assertFalse(list(skills.glob(".mado-loop.stage.*")))
                # Test-only recovery is confined to this temporary fixture.
                backups[0].rename(target)
                self.assertEqual(before, self._tree_fingerprint(target))

    def test_uninstall_clean(self) -> None:
        for shell in SHELLS:
            with self.subTest(shell=shell):
                home = self.home("uninstall-clean-" + shell)
                self.invoke(shell, INSTALL, home, package=self.package, version="1.0.0")
                self.invoke(shell, UNINSTALL, home)
                self.assertFalse((home / ".agents" / "skills" / "mado-loop").exists())

    def test_uninstall_preserves_modified_and_untracked(self) -> None:
        for shell in SHELLS:
            with self.subTest(shell=shell):
                home = self.home("uninstall-dirty-" + shell)
                self.invoke(shell, INSTALL, home, package=self.package, version="1.0.0")
                target = home / ".agents" / "skills" / "mado-loop"
                (target / "SKILL.md").write_text("modified", encoding="utf-8")
                (target / "mine.txt").write_text("mine", encoding="utf-8")
                (target / "empty user dir").mkdir()
                self.invoke(shell, UNINSTALL, home)
                self.assertEqual("modified", (target / "SKILL.md").read_text(encoding="utf-8"))
                self.assertEqual("mine", (target / "mine.txt").read_text(encoding="utf-8"))
                self.assertFalse((target / MARKER).exists())
                self.assertEqual({"SKILL.md", "mine.txt", "empty user dir"}, {p.name for p in target.iterdir()})
                self.assertTrue((target / "empty user dir").is_dir())

    def test_downgrade_refusal_and_authorized_downgrade(self) -> None:
        for shell in SHELLS:
            with self.subTest(shell=shell):
                home = self.home("downgrade-" + shell)
                self.invoke(shell, INSTALL, home, package=self.package, version="2.0.0")
                self.invoke(shell, INSTALL, home, package=self.package, version="1.0.0", expect=1)
                marker = home / ".agents" / "skills" / "mado-loop" / MARKER
                self.assertEqual("2.0.0", json.loads(marker.read_text(encoding="utf-8"))["version"])
                result = self.result_json(self.invoke(shell, INSTALL, home, package=self.package,
                                                      version="1.0.0", extra=["-AllowDowngrade"]))
                self.assertEqual("downgrade", result["operation"])

    def test_unicode_space_home(self) -> None:
        for shell in SHELLS:
            with self.subTest(shell=shell):
                home = self.home("日本語 home " + shell)
                self.invoke(shell, INSTALL, home, package=self.package, version="1.0.0")
                self.assertTrue((home / ".agents" / "skills" / "mado-loop" / "SKILL.md").is_file())

    def test_reparse_ancestor_refused(self) -> None:
        for shell in SHELLS:
            with self.subTest(shell=shell):
                home = self.home("junction-home-" + shell)
                outside = self.home("junction-outside-" + shell)
                junction = home / ".agents"
                made = subprocess.run(
                    ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(outside)],
                    capture_output=True, text=True,
                )
                self.assertEqual(0, made.returncode, made.stdout + made.stderr)
                before = self._tree_fingerprint(outside)
                self.invoke(shell, INSTALL, home, package=self.package, version="1.0.0", expect=1)
                self.assertEqual(before, self._tree_fingerprint(outside))

    def test_uninstall_managed_subdirectory_junction_refuses_atomically(self) -> None:
        for shell in SHELLS:
            with self.subTest(shell=shell):
                home = self.home("uninstall-junction-home-" + shell)
                outside = self.home("uninstall-junction-outside-" + shell)
                self.invoke(shell, INSTALL, home, package=self.package, version="1.0.0")
                target = home / ".agents" / "skills" / "mado-loop"
                managed = target / "vendor" / "godot-skill"
                shutil.rmtree(managed)
                (outside / "LICENSE").write_bytes(
                    next(p for p in zipfile.ZipFile(self.package).namelist()
                         if p == "mado-loop/vendor/godot-skill/LICENSE").encode("utf-8")
                )
                made = subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(managed), str(outside)],
                                      capture_output=True, text=True)
                self.assertEqual(0, made.returncode, made.stdout + made.stderr)
                outside_before = self._tree_fingerprint(outside)
                marker_before = (target / MARKER).read_bytes()
                existing_before = self._tree_fingerprint(target)
                self.invoke(shell, UNINSTALL, home, expect=1)
                self.assertEqual(outside_before, self._tree_fingerprint(outside))
                self.assertEqual(marker_before, (target / MARKER).read_bytes())
                self.assertEqual(existing_before, self._tree_fingerprint(target))

    def test_strict_marker_validation_refuses_uninstall_and_upgrade(self) -> None:
        def variants(marker: dict[str, object]) -> list[tuple[str, str]]:
            outputs: list[tuple[str, str]] = []
            for label, mutate in (
                ("missing-version", lambda m: m.pop("version")),
                ("missing-package", lambda m: m.pop("package_sha256")),
                ("upper-package", lambda m: m.__setitem__("package_sha256", str(m["package_sha256"]).upper())),
                ("wrong-product-case", lambda m: m.__setitem__("product", "MADO-LOOP")),
            ):
                changed = json.loads(json.dumps(marker)); mutate(changed)
                outputs.append((label, json.dumps(changed)))
            changed = json.loads(json.dumps(marker)); first = next(iter(changed["files"]))
            changed["files"][first] = "a" * 63
            outputs.append(("short-digest", json.dumps(changed)))
            changed = json.loads(json.dumps(marker)); first = next(iter(changed["files"]))
            changed["files"][first] = str(changed["files"][first]).upper()
            outputs.append(("upper-file-digest", json.dumps(changed)))
            changed = json.loads(json.dumps(marker)); digest = changed["files"].pop("SKILL.md")
            changed["files"]["../SKILL.md"] = digest
            outputs.append(("unsafe-path", json.dumps(changed)))
            # Raw JSON retains both differently-cased property names.
            raw = json.dumps(marker)
            insert = f'"skill.md":"{marker["files"]["SKILL.md"]}",'
            outputs.append(("case-confusing-path", raw.replace('"files": {', '"files": {' + insert, 1)))
            return outputs

        for shell in SHELLS:
            seed_home = self.home("marker-seed-" + shell)
            self.invoke(shell, INSTALL, seed_home, package=self.package, version="1.0.0")
            seed = seed_home / ".agents" / "skills" / "mado-loop"
            original = json.loads((seed / MARKER).read_text(encoding="utf-8"))
            for operation in ("uninstall", "upgrade"):
                for label, raw in variants(original):
                    with self.subTest(shell=shell, operation=operation, variant=label):
                        home = self.home(f"marker-{shell}-{operation}-{label}")
                        target = home / ".agents" / "skills" / "mado-loop"
                        shutil.copytree(seed, target)
                        (target / MARKER).write_text(raw, encoding="utf-8")
                        before = self._tree_fingerprint(target)
                        if operation == "uninstall":
                            self.invoke(shell, UNINSTALL, home, expect=1)
                        else:
                            self.invoke(shell, INSTALL, home, package=self.package, version="1.1.0", expect=1)
                        self.assertEqual(before, self._tree_fingerprint(target))

    def make_bad_zip(self, label: str, mutate) -> Path:
        output = self.workspace / (label + ".zip")
        with zipfile.ZipFile(self.package) as source, zipfile.ZipFile(output, "w") as target:
            for info in source.infolist():
                target.writestr(info, source.read(info.filename))
            mutate(target)
        return output

    def test_corrupt_and_unsafe_zip_rejected(self) -> None:
        bad = self.workspace / "corrupt.zip"; bad.write_bytes(b"not zip")
        variants = [bad]
        variants.append(self.make_bad_zip("traversal", lambda z: z.writestr("mado-loop/../escape", b"x")))
        variants.append(self.make_bad_zip("drive", lambda z: z.writestr("C:/escape", b"x")))
        variants.append(self.make_bad_zip("case", lambda z: z.writestr("mado-loop/skill.md", b"x")))
        variants.append(self.make_bad_zip("root-case", lambda z: z.writestr("MADO-LOOP/extra", b"x")))
        def replace_required_case(z: zipfile.ZipFile) -> None:
            z.writestr("mado-loop/skill.md", b"replacement")
        variants.append(self.make_bad_zip("required-case", replace_required_case))
        def add_link(z: zipfile.ZipFile) -> None:
            info = zipfile.ZipInfo("mado-loop/link")
            info.create_system = 3; info.external_attr = 0o120777 << 16
            z.writestr(info, b"SKILL.md")
        variants.append(self.make_bad_zip("symlink", add_link))
        for shell in SHELLS:
            for index, package in enumerate(variants):
                with self.subTest(shell=shell, package=package.name):
                    home = self.home(f"unsafe-{shell}-{index}")
                    self.invoke(shell, INSTALL, home, package=package, version="1.0.0", expect=1)
                    self.assertFalse((home / ".agents" / "skills" / "mado-loop").exists())


if __name__ == "__main__":
    unittest.main()

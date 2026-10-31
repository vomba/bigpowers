"""Behavioral ownership, stale retention and partial-publication checks."""
import json
try:
    import resource
except ImportError:
    resource = None
import shutil
import signal
import unittest

from omp_support import OmpFixture, snapshot


class OmpOwnershipTests(OmpFixture):
    def test_user_resources_are_preserved_but_identical_collisions_are_not_adopted(self):
        self.generate()
        identical = self.generated().read_bytes()
        shutil.rmtree(self.output)
        self.generated().parent.mkdir(parents=True)
        self.generated().write_bytes(identical)
        self.assert_failure_unchanged(lambda: self.generate(expected=None))
        self.assertFalse((self.output / ".bigpowers-resources.json").exists())

    def test_unowned_command_collision_is_not_overwritten(self):
        path = self.output / "commands/bigpowers-demo.md"
        path.parent.mkdir(parents=True)
        path.write_text("User-authored command\n")
        self.assert_failure_unchanged(lambda: self.generate(expected=None))
        self.assertFalse(self.generated().exists())

    def test_unrelated_files_inside_native_root_and_owned_skill_remain_untouched(self):
        self.generate()
        files = [self.output / "commands/user-command.md", self.generated().parent / "user-note.txt"]
        for path in files:
            path.write_text("user content\n")
            path.chmod(0o600)
        before = {str(path): (path.read_bytes(), path.stat()) for path in files}
        self.generate()
        for path in files:
            data, info = before[str(path)]
            self.assertEqual(path.read_bytes(), data)
            self.assertEqual(path.stat().st_mode, info.st_mode)
            self.assertEqual(path.stat().st_mtime_ns, info.st_mtime_ns)
            self.assertEqual(path.stat().st_ctime_ns, info.st_ctime_ns)

    def test_changed_deleted_retyped_or_chmod_owned_files_refuse_refresh_and_check(self):
        for mutation in ("edit", "delete", "directory", "symlink", "mode"):
            with self.subTest(mutation=mutation):
                if self.output.exists():
                    shutil.rmtree(self.output)
                self.generate()
                path = self.generated()
                if mutation == "edit":
                    path.write_text("edited by user\n")
                elif mutation == "mode":
                    path.chmod(0o600)
                else:
                    path.unlink()
                    if mutation == "directory":
                        path.mkdir()
                    elif mutation == "symlink":
                        path.symlink_to(self.project / "skills/demo/SKILL.md")
                self.assert_failure_unchanged(lambda: self.generate(expected=None))
                self.assert_failure_unchanged(lambda: self.check(expected=None))

    def test_changed_owned_directory_mode_is_refused(self):
        self.generate()
        self.generated().parent.chmod(0o700)
        self.assert_failure_unchanged(lambda: self.generate(expected=None))

    def test_batch_single_batch_preserves_unselected_records_and_files(self):
        self.skill("second")
        self.generate()
        second_before = snapshot(self.generated("second").parent)
        old_records = {key: value for key, value in self.records().items() if value["skill"] == "second"}
        self.skill("demo", body="# Updated demo\n\nUse the selected workflow.\n")
        self.engine("skills/demo/SKILL.md", "--target", "omp")
        self.assertEqual(snapshot(self.generated("second").parent), second_before)
        self.assertEqual({key: value for key, value in self.records().items() if value["skill"] == "second"}, old_records)
        single_before = snapshot(self.output)
        self.generate()
        self.assertEqual(snapshot(self.output), single_before)
        self.check()

    def test_only_full_catalog_marks_stale_and_retains_absent_skill_and_assets(self):
        self.skill("second")
        asset = self.project / "skills/demo/old.txt"
        asset.write_text("retained old asset\n")
        self.generate()
        retained = snapshot(self.generated("second").parent)
        shutil.rmtree(self.project / "skills/second")
        asset.unlink()
        self.engine("skills/demo/SKILL.md", "--target", "omp")
        self.assertEqual(self.records()["skills/second/SKILL.md"]["status"], "active")
        result = self.generate()
        self.assertIn("second", result.stdout)
        self.assertEqual(self.records()["skills/second/SKILL.md"]["status"], "catalog-stale")
        self.assertEqual(self.records()["skills/demo/old.txt"]["status"], "catalog-stale")
        self.assertEqual(snapshot(self.generated("second").parent), retained)
        self.assertTrue((self.generated().parent / "old.txt").exists())
        self.check()
        self.generated("second").write_text("edited stale output\n")
        self.assert_failure_unchanged(lambda: self.engine("skills/demo/SKILL.md", "--target", "omp", expected=None))

    def test_output_root_inventory_and_nested_ancestor_symlinks_are_refused(self):
        real = self.project / "real-output"
        real.mkdir()
        root = self.project / ".omp"
        root.symlink_to(real, target_is_directory=True)
        self.assert_failure_unchanged(lambda: self.generate(expected=None))
        root.unlink()
        self.generate()
        inventory = root / ".bigpowers-resources.json"
        saved = self.project / "saved-inventory.json"
        inventory.replace(saved)
        inventory.symlink_to(saved)
        self.assert_failure_unchanged(lambda: self.generate(expected=None))
        inventory.unlink()
        saved.replace(inventory)
        directory = self.generated().parent
        moved = self.project / "moved-owned-skill"
        directory.replace(moved)
        directory.symlink_to(moved, target_is_directory=True)
        self.assert_failure_unchanged(lambda: self.generate(expected=None))

    def test_missing_or_corrupt_inventory_never_adopts_existing_outputs(self):
        self.generate()
        path = self.output / ".bigpowers-resources.json"
        original = path.read_bytes()
        for data in (None, b"{broken", b'{"version":99,"resources":[]}',
                     b'{"version":1,"resources":{}}'):
            with self.subTest(data=data):
                if data is None:
                    path.unlink()
                else:
                    path.write_bytes(data)
                self.assert_failure_unchanged(lambda: self.generate(expected=None))
                path.write_bytes(original)

    def test_unsafe_inventory_paths_are_rejected_before_touching_output(self):
        self.generate()
        path = self.output / ".bigpowers-resources.json"
        data = self.inventory()
        data["resources"][0]["path"] = "../outside.txt"
        path.write_text(json.dumps(data))
        self.assert_failure_unchanged(lambda: self.generate(expected=None))

    def test_interrupted_temporary_file_is_not_silently_ignored(self):
        self.generate()
        temporary = self.generated().parent / ".bigpowers-tmp-interrupted"
        temporary.write_bytes(b"partial")
        self.assert_failure_unchanged(lambda: self.generate(expected=None))
        self.assert_failure_unchanged(lambda: self.check(expected=None))

    @unittest.skipUnless(resource is not None and hasattr(resource, "RLIMIT_FSIZE"), "requires POSIX file-size limits")
    def test_handled_partial_write_reports_paths_and_refuses_ambiguous_retry(self):
        asset = self.project / "skills/demo/large.bin"
        asset.write_bytes(b"x" * 16384)

        def limit_files():
            signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
            resource.setrlimit(resource.RLIMIT_FSIZE, (4096, 4096))

        result = self.generate(expected=None, preexec_fn=limit_files)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("completed paths:", result.stderr)
        self.assertTrue(self.generated().exists())
        self.assertFalse((self.output / ".bigpowers-resources.json").exists())
        self.assertFalse((self.generated().parent / "large.bin").exists())
        self.assert_failure_unchanged(lambda: self.generate(expected=None))

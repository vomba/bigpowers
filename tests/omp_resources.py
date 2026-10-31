"""Resource readability, dependency projection and native metadata checks."""
import stat
import subprocess

from omp_support import OmpFixture, snapshot


def header(path):
    import yaml
    lines = path.read_text(encoding="utf-8").splitlines()
    return yaml.safe_load("\n".join(lines[1:lines.index("---", 1)]))


class OmpResourcesTests(OmpFixture):
    def test_source_body_stays_separate_from_nested_support_assets(self):
        source = self.skill("demo", body="# Demo\n\n[Reference](REFERENCE.md)\n[Runner](scripts/run.sh)\n")
        reference = source.parent / "REFERENCE.md"
        reference.write_text("# Independent support\n\n[Runner](scripts/run.sh)\n")
        script = source.parent / "scripts/run.sh"
        script.parent.mkdir()
        script.write_text("#!/bin/sh\nprintf '%s\\n' '$ARGUMENTS'\n")
        script.chmod(0o751)
        before = snapshot(self.project / "skills")
        self.generate()
        output = self.generated().parent
        result = subprocess.run([str(output / "scripts/run.sh")], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "$ARGUMENTS\n")
        self.assertEqual(stat.S_IMODE((output / "scripts/run.sh").stat().st_mode), 0o751)
        self.assertNotIn("# Independent support", self.generated().read_text())
        self.assertEqual(snapshot(self.project / "skills"), before)
        self.check()

    def test_outward_links_resolve_from_each_original_asset_without_copying_repository(self):
        docs = self.project / "docs"
        docs.mkdir()
        dependency = docs / "guide.md"
        dependency.write_text("# Repository dependency\n")
        source = self.skill("demo", body='[Guide](../../docs/guide.md#chapter "Reference")\n')
        asset = source.parent / "nested/REFERENCE.md"
        asset.parent.mkdir()
        asset.write_text("[Guide](../../../docs/guide.md)\n")
        self.generate()
        for path in (self.generated(), self.generated().parent / "nested/REFERENCE.md"):
            text = path.read_text()
            self.assertIn(dependency.as_uri(), text)
        self.assertIn('"Reference"', self.generated().read_text())
        self.assertFalse((self.output / "docs").exists())
        self.assertEqual(dependency.read_text(), "# Repository dependency\n")

    def test_literal_code_links_are_not_interpreted_as_dependencies(self):
        examples = ("`[inline](absent-inline.md)`\n\n```sh\n"
                    "[example](../../absent.md)\necho '$ARGUMENTS ${MODEL} $1'\n```\n")
        self.skill("demo", body=examples)
        self.generate()
        self.assertIn(examples, self.generated().read_text())
        self.check()

    def test_missing_asset_link_fails_whole_batch_before_publication(self):
        source = self.skill("zzz-late")
        (source.parent / "REFERENCE.md").write_text("[Required](missing.md)\n")
        self.assert_failure_unchanged(lambda: self.generate(expected=None))
        self.assertFalse(self.output.exists())

    def test_escaping_source_file_and_directory_links_fail_before_publication(self):
        outside = self.project.parent / (self.project.name + "-external")
        outside.mkdir()
        self.addCleanup(lambda: __import__("shutil").rmtree(outside))
        (outside / "private.txt").write_text("must not be copied")
        for target in (outside / "private.txt", outside):
            with self.subTest(target=target):
                link = self.project / "skills/demo/escape"
                link.symlink_to(target, target_is_directory=target.is_dir())
                self.assert_failure_unchanged(lambda: self.generate(expected=None))
                link.unlink()


    def test_check_is_read_only_and_rejects_missing_or_corrupt_inventory(self):
        before = snapshot(self.project)
        self.check(expected=1)
        self.assertEqual(snapshot(self.project), before)
        self.generate()
        before = snapshot(self.project)
        self.check()
        self.assertEqual(snapshot(self.project), before)
        inventory = self.output / ".bigpowers-resources.json"
        inventory.write_text("{broken")
        self.assert_failure_unchanged(lambda: self.check(expected=None))


class OmpProjectionBehaviorTests(OmpFixture):
    def test_descriptions_can_contain_frontmatter_marker_text(self):
        source = self.project / "skills/demo/SKILL.md"
        source.write_text('---\nname: demo\ndescription: "Inspect --- separators"\n'
                          'model: opus\n---\n\n# Demo\nInspect the assigned change.\n')
        self.generate()
        self.assertEqual(header(self.generated())["description"], "Inspect --- separators")
        self.engine(source, "--target", "omp")
        self.assertEqual(header(self.generated())["description"], "Inspect --- separators")
        self.check()

    def test_multiline_description_html_story_comment_and_native_controls_load(self):
        source = self.project / "skills/demo/SKILL.md"
        source.write_text("---\n<!-- story: e82s03 -->\nname: demo\nmodel: opus\n"
                          "description: >-\n  Inspect concrete changes\n  using existing conventions.\n"
                          "hide: true\ndisable-model-invocation: true\n---\n\n# Demo\n")
        before = source.read_bytes()
        self.generate()
        metadata = header(self.generated())
        self.assertEqual(metadata["name"], "demo")
        self.assertEqual(metadata["description"], "Inspect concrete changes using existing conventions.")
        self.assertTrue(metadata["hide"])
        self.assertTrue(metadata["disable-model-invocation"])
        self.assertNotIn("model", metadata)
        self.assertEqual(source.read_bytes(), before)
        self.check()

    def test_visible_and_disabled_skills_keep_distinct_invocation_metadata(self):
        self.skill("demo", metadata="hide: false\ndisable-model-invocation: false\n")
        self.skill("manual-only", metadata="disable-model-invocation: true\n")
        self.generate()
        self.assertFalse(header(self.generated())["hide"])
        self.assertFalse(header(self.generated())["disable-model-invocation"])
        self.assertTrue(header(self.generated("manual-only"))["disable-model-invocation"])
        self.assertTrue((self.output / "commands/bigpowers-manual-only.md").is_file())

    def test_generation_preserves_user_native_configuration_and_role_files(self):
        config = self.project / ".omp/config.yml"
        config.parent.mkdir()
        config.write_text("modelRoles:\n  task: synthetic/implementation\n  review: synthetic/review\n")
        for directory in ("agents", "extensions", "hooks"):
            path = config.parent / directory
            path.mkdir()
            (path / "user-owned").write_text(directory)
        before = {name: snapshot(config.parent / name) for name in ("agents", "extensions", "hooks")}
        config_bytes, info = config.read_bytes(), config.stat()
        self.generate()
        self.assertEqual(config.read_bytes(), config_bytes)
        self.assertEqual(config.stat().st_mtime_ns, info.st_mtime_ns)
        for name, values in before.items():
            self.assertEqual(snapshot(config.parent / name), values)
        self.assertFalse((config.parent / "providers").exists())
        self.assertFalse((config.parent / "mcp.json").exists())

    def test_omp_projection_does_not_change_pi_source_model_allocation(self):
        source = self.project / "skills/demo/SKILL.md"
        before = source.read_bytes()
        self.generate()
        self.engine(source, "--target", "pi")
        self.assertEqual(header(self.project / ".pi/skills/demo/SKILL.md")["model"], "opus")
        self.assertNotIn("model", header(self.generated()))
        self.assertEqual(source.read_bytes(), before)

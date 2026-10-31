"""Public selection and cross-integration isolation checks."""
import shutil

from omp_support import OmpFixture, snapshot


class OmpSelectionCases(OmpFixture):
    def test_both_shell_target_forms_and_redundant_distribution(self):
        self.generate()
        before = snapshot(self.output)
        self.shell("--target=omp", "--distribute-only")
        self.assertEqual(snapshot(self.output), before)
        self.check()

    def test_python_single_batch_and_direct_adapter_have_identical_effects(self):
        source = self.project / "skills/demo/SKILL.md"
        self.engine(source, "--target", "omp")
        before = snapshot(self.output)
        self.engine("--all", "--target", "omp")
        self.assertEqual(snapshot(self.output), before)
        self.env.update(SKILL_MD_PATH=str(source), IR_NAME="demo",
                        IR_DESCRIPTION="Inspect a concrete change.")
        self.run_cli(["bash", "-c", 'source scripts/adapters/omp.sh </dev/null; render_skill'])
        self.assertEqual(snapshot(self.output), before)

    def test_python_single_dry_run_has_no_filesystem_effects(self):
        before = snapshot(self.project)
        result = self.engine("skills/demo/SKILL.md", "--target", "omp", "--dry-run")
        self.assertIn("demo", result.stdout)
        self.assertEqual(snapshot(self.project), before)
        self.assertFalse(self.output.exists())

    def test_custom_output_directory_is_honored(self):
        self.env["OMP_SKILLS"] = str(self.project / "custom-native/native-skills")
        self.generate()
        self.assertTrue((self.output / "native-skills/demo/SKILL.md").is_file())
        self.assertFalse((self.project / ".omp").exists())
        self.check()

    def test_sourcing_adapter_without_input_is_inert(self):
        before = snapshot(self.project)
        self.run_cli(["bash", "-c", "source scripts/adapters/omp.sh </dev/null"])
        self.assertEqual(snapshot(self.project), before)


class OmpIsolationTests(OmpFixture):
    def seed_other_integrations(self):
        outputs = [".cursor/rules", ".gemini/extensions/bigpowers", ".pi/skills", ".cline/skills",
                   ".agents/skills", ".hermes/skills", ".zcode/skills", ".omc/skills",
                   ".opencode/skills", ".gemini/hooks", "specs/skills-wiki", "docs/wiki",
                   "website/src/content/docs", ".config/zed/assistant"]
        import yaml
        registry = yaml.safe_load((self.project / "scripts/targets.yaml").read_text())
        for target in registry["targets"]:
            if target["id"] != "omp" and target.get("skill"):
                value = target["skill"]["output"]
                outputs.append(value.replace("~/", self.env["HOME"] + "/", 1))
        for relative in outputs:
            directory = self.project / relative
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "user-resource").write_bytes(relative.encode())
            (directory / "user-resource").chmod(0o600)
        for relative in ("SKILL-INDEX.md", "README.md", "CLAUDE.md", "AGENTS.md", "GEMINI.md",
                         "SKILLS-MANIFEST.json", ".sync-stamp", "specs/state.yaml"):
            path = self.project / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(relative.encode())
        (self.project / ".cursor/rules/user-link").symlink_to("../../README.md")
        # A real post-sync execution would leave this observable sentinel.
        (self.project / "scripts/lib/sync-post.sh").write_text(
            'sync_post_run() { touch "$REPO_ROOT/post-sync-invoked"; }\n')

    def test_explicit_generation_preserves_all_non_omp_resources(self):
        self.seed_other_integrations()
        before = snapshot(self.project, exclude=(".omp",))
        self.generate()
        self.assertEqual(snapshot(self.project, exclude=(".omp",)), before)
        self.assertFalse((self.project / "post-sync-invoked").exists())

    def test_invalid_shell_options_never_publish(self):
        combinations = [("--target",), ("--target=",), ("--target", "cursor"),
                        ("--target", "omp", "--target=omp"),
                        ("--target", "omp", "--okf"), ("--opencode", "--target=omp")]
        for arguments in combinations:
            with self.subTest(arguments=arguments):
                self.assert_failure_unchanged(lambda: self.shell(*arguments, expected=None))

    def test_invalid_python_options_never_publish(self):
        combinations = [("--all", "--target"), ("--all", "--target="),
                        ("--all", "--target", "omp", "--target=omp"),
                        ("--all", "--target", "omp", "--okf"),
                        ("--all", "--target", "omp", "--dry-run"),
                        ("--all", "--target", "omp", "skills/demo/SKILL.md"),
                        ("skills/demo/SKILL.md", "--target", "omp", "unexpected"),
                        ("skills/demo/SKILL.md", "--target", "omp", "--opencode")]
        for arguments in combinations:
            with self.subTest(arguments=arguments):
                self.assert_failure_unchanged(lambda: self.engine(*arguments, expected=None))

    def test_late_invalid_name_and_duplicate_batch_names_publish_nothing(self):
        for name in ("../escape", "demo"):
            with self.subTest(name=name):
                self.skill(name, directory="zzz-late")
                self.assert_failure_unchanged(lambda: self.generate(expected=None))
                self.assertFalse(self.output.exists())
                shutil.rmtree(self.project / "skills/zzz-late")

    def test_missing_late_dependency_preserves_preexisting_outputs(self):
        self.generate()
        self.skill("zzz-late", body="[Required](../../docs/missing.md)\n")
        self.assert_failure_unchanged(lambda: self.generate(expected=None))

    def test_default_python_batch_does_not_touch_existing_omp(self):
        self.generate()
        before = snapshot(self.output)
        # Restrict this disposable registry to representative legacy skill adapters.
        (self.project / "scripts/targets.yaml").write_text(
            "targets:\n  - id: pi\n    skill:\n      adapter: pi\n"
            "  - id: cursor\n    skill:\n      adapter: cursor\n"
            "  - id: omp\n    skill:\n      adapter: omp\n")
        # Legacy direct batch callers, unlike sync-skills.sh, prepare this root.
        (self.project / ".cursor/rules").mkdir(parents=True)
        self.engine("--all")
        self.assertTrue((self.project / ".pi/skills/demo/SKILL.md").exists())
        self.assertTrue((self.project / ".cursor/rules/demo.mdc").exists())
        self.assertEqual(snapshot(self.output), before)

    def test_default_shell_distribution_does_not_touch_existing_omp(self):
        self.generate()
        before = snapshot(self.output)
        self.shell("--distribute-only")
        self.assertTrue((self.project / ".pi/skills/demo/SKILL.md").exists())
        self.assertTrue((self.project / ".cursor/rules/demo.mdc").exists())
        self.assertEqual(snapshot(self.output), before)

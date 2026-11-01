#!/usr/bin/env python3
"""Public generation regressions for the native OMP target. story: e82s03"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]


class OmpPipelineTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="omp pipeline $ARGUMENTS-$1 ")
        self.addCleanup(temporary.cleanup)
        self.project = Path(temporary.name).resolve()
        shutil.copytree(ROOT / "scripts", self.project / "scripts")
        self.env = dict(os.environ, PYTHON=sys.executable, PYTHONDONTWRITEBYTECODE="1")
        for key in tuple(self.env):
            if key.endswith("_SKILLS") or key in ("OMP_COMMANDS", "PI_PROMPTS"):
                self.env.pop(key)
        self.source = self.skill("demo")

    def skill(self, name, controls="", description='"Inspect --- separators"'):
        source = self.project / "skills" / name / "SKILL.md"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(f"---\n<!-- story: e82s03 -->\nname: {name}\n"
                          f"description: {description}\nmodel: opus\n{controls}---\n\n# Workflow\n")
        return source

    def run_cli(self, *arguments, cwd=None, expected=0):
        result = subprocess.run(arguments, cwd=cwd or self.project, env=self.env,
                                capture_output=True, text=True)
        if expected is not None:
            self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def generate(self, cwd=None, expected=0):
        return self.run_cli("bash", str(self.project / "scripts/sync-skills.sh"),
                            "--distribute-only", cwd=cwd, expected=expected)

    def header(self, name="demo"):
        text = (self.project / ".omp/skills" / name / "SKILL.md").read_text()
        return yaml.safe_load(text.split("---\n", 2)[1])

    def test_normal_sync_handles_native_metadata_and_preserves_pi_allocation(self):
        self.generate()
        self.assertEqual(self.header()["description"], "Inspect --- separators")
        self.assertNotIn("model", self.header())
        pi = (self.project / ".pi/skills/demo/SKILL.md").read_text()
        self.assertEqual(yaml.safe_load(pi.split("---\n", 2)[1])["model"], "opus")


    def test_quoted_html_is_data_not_a_story_comment(self):
        self.skill("demo", description='"Keep <!-- literal --> documentation"')
        result = self.run_cli(sys.executable, "scripts/lib/srp-engine.py", str(self.source), "--dry-run")
        self.assertEqual(json.loads(result.stdout)["description"], "Keep <!-- literal --> documentation")

    def test_batch_and_individual_controls_do_not_leak_between_skills(self):
        self.skill("demo", "hide: true\ndisable-model-invocation: true\n")
        self.skill("visible", "hide: false\ndisable-model-invocation: false\n")
        self.skill("z-unset")
        self.generate()
        self.assertTrue(self.header()["hide"])
        self.assertTrue(self.header()["disable-model-invocation"])
        self.assertFalse(self.header("visible")["hide"])
        self.assertFalse(self.header("visible")["disable-model-invocation"])
        self.assertNotIn("hide", self.header("z-unset"))
        self.assertNotIn("disable-model-invocation", self.header("z-unset"))
        self.skill("demo", "hide: false\n", description=">-\n  Inspect concrete changes\n  without model overrides.")
        untouched = (self.project / ".omp/skills/visible/SKILL.md").read_bytes()
        self.run_cli(sys.executable, "scripts/lib/srp-engine.py", str(self.source), "--target", "omp")
        self.assertFalse(self.header()["hide"])
        self.assertNotIn("disable-model-invocation", self.header())
        self.assertEqual(self.header()["description"], "Inspect concrete changes without model overrides.")
        self.assertEqual((self.project / ".omp/skills/visible/SKILL.md").read_bytes(), untouched)

    def test_invalid_native_controls_fail_before_native_publication(self):
        self.skill("demo", 'hide: "yes"\n')
        result = self.generate(expected=None)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("boolean invocation controls", result.stderr)
        self.assertFalse((self.project / ".omp/skills/demo/SKILL.md").exists())

    def test_unmarked_command_collision_preserves_both_resources(self):
        command = self.project / ".omp/commands/bigpowers-demo.md"
        command.parent.mkdir(parents=True)
        command.write_text("User-authored command\n")
        result = self.generate(expected=None)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(command.read_text(), "User-authored command\n")
        self.assertFalse((self.project / ".omp/skills/demo/SKILL.md").exists())

    def test_unmarked_skill_is_never_adopted(self):
        skill = self.project / ".omp/skills/demo/SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("User-authored skill\n")
        result = self.generate(expected=None)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(skill.read_text(), "User-authored skill\n")
        self.assertFalse((self.project / ".omp/commands/bigpowers-demo.md").exists())

    def test_symlinked_output_ancestor_does_not_write_through(self):
        outside = self.project / "preserved"
        outside.mkdir()
        (self.project / ".omp").symlink_to(outside, target_is_directory=True)
        result = self.generate(expected=None)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(list(outside.iterdir()), [])

    def test_dangling_destination_link_is_preserved(self):
        command = self.project / ".omp/commands/bigpowers-demo.md"
        command.parent.mkdir(parents=True)
        command.symlink_to(self.project / "missing-user-file")
        result = self.generate(expected=None)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(command.is_symlink())
        self.assertFalse((self.project / ".omp/skills/demo/SKILL.md").exists())

    def test_generation_preserves_unrelated_native_user_resources(self):
        config = self.project / ".omp/config.yml"
        config.parent.mkdir()
        config.write_text("modelRoles:\n  task: user/worker\n")
        authored = self.project / ".omp/skills/user-variant/SKILL.md"
        authored.parent.mkdir(parents=True)
        authored.write_text("---\nname: user-variant\ndescription: User-owned.\n---\n")
        before = (config.read_bytes(), config.stat().st_mtime_ns, authored.read_bytes())
        self.generate()
        unrelated = self.project / ".omp/skills/user-link"
        unrelated.symlink_to(self.source.parent, target_is_directory=True)
        self.run_cli(sys.executable, "scripts/validate-omp-resources.py", str(self.project))
        self.assertTrue(unrelated.is_symlink())
        self.assertEqual((config.read_bytes(), config.stat().st_mtime_ns, authored.read_bytes()), before)
        self.assertFalse((self.project / ".omp/agents").exists())
        self.assertFalse((self.project / ".omp/extensions").exists())

    def test_regeneration_is_portable_and_rooted_outside_cwd(self):
        caller = self.project / "elsewhere"
        caller.mkdir()
        self.generate(cwd=caller)
        self.assertFalse((caller / ".omp").exists())
        before = {path.relative_to(self.project / ".omp"): path.read_bytes()
                  for path in (self.project / ".omp").rglob("*") if path.is_file()}
        relocated = self.project / "relocated $ARGUMENTS $1"
        shutil.copytree(self.project / "scripts", relocated / "scripts")
        shutil.copytree(self.project / "skills", relocated / "skills")
        self.run_cli("bash", str(relocated / "scripts/sync-skills.sh"), "--distribute-only")
        after = {path.relative_to(relocated / ".omp"): path.read_bytes()
                 for path in (relocated / ".omp").rglob("*") if path.is_file()}
        self.assertEqual(after, before)

    def test_validator_rejects_missing_and_stale_generated_catalog_entries(self):
        self.generate()
        validator = self.project / "scripts/validate-omp-resources.py"
        self.run_cli(sys.executable, str(validator), str(self.project))
        command = self.project / ".omp/commands/bigpowers-demo.md"
        command.unlink()
        result = self.run_cli(sys.executable, str(validator), str(self.project), expected=None)
        self.assertNotEqual(result.returncode, 0)
        self.generate()
        self.skill("retired")
        self.generate()
        shutil.rmtree(self.project / "skills/retired")
        result = self.run_cli(sys.executable, str(validator), str(self.project), expected=None)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Stale generated artifact", result.stderr)

if __name__ == "__main__":
    unittest.main()

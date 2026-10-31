#!/usr/bin/env python3
"""Behavioral checks for explicit native OMP generation. story: e82s03"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import omp_selection
from omp_selection import OmpIsolationTests
from omp_resources import OmpResourcesTests, OmpProjectionBehaviorTests
from omp_ownership_cases import OmpOwnershipTests

ROOT = Path(__file__).resolve().parents[1]


class OmpSelectionTests(omp_selection.OmpSelectionCases):
    def test_explicit_omp_generation_preserves_existing_integration_resources(self):
        with tempfile.TemporaryDirectory(prefix="bp-omp-selection-") as directory:
            project = Path(directory)
            shutil.copytree(ROOT / "scripts", project / "scripts")
            skill = project / "skills" / "demo"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text(
                "---\nname: demo\ndescription: Inspect a concrete change.\n"
                "model: opus\n---\n\n# Demo\n\nRecord the observed change.\n",
                encoding="utf-8",
            )
            preserved = project / ".pi" / "skills" / "user-owned" / "SKILL.md"
            preserved.parent.mkdir(parents=True)
            preserved.write_bytes(b"user-authored skill\n")
            preserved.chmod(0o600)
            target = project / "existing-prompt.md"
            target.write_bytes(b"user prompt\n")
            link = project / ".cursor" / "rules" / "user.mdc"
            link.parent.mkdir(parents=True)
            link.symlink_to(target)
            before = (preserved.read_bytes(), preserved.stat().st_mode,
                      preserved.stat().st_mtime_ns, os.readlink(link))
            result = subprocess.run(
                ["bash", "scripts/sync-skills.sh", "--target", "omp"],
                cwd=project, env=os.environ.copy(), text=True, capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                (preserved.read_bytes(), preserved.stat().st_mode,
                 preserved.stat().st_mtime_ns, os.readlink(link)), before,
            )
            self.assertTrue((project / ".omp/skills/demo/SKILL.md").is_file())
            self.assertTrue((project / ".omp/commands/bigpowers-demo.md").is_file())
            self.assertFalse((project / ".gemini").exists())


if __name__ == "__main__":
    unittest.main()

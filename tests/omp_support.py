"""Disposable public-CLI fixtures for native OMP resource behavior."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def snapshot(root, exclude=()):
    result = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if relative.parts[0] in exclude:
            continue
        info = path.lstat()
        value = (stat.S_IFMT(info.st_mode), stat.S_IMODE(info.st_mode), info.st_uid,
                 info.st_gid, info.st_mtime_ns, info.st_ctime_ns)
        if path.is_symlink():
            value += (os.readlink(path),)
        elif path.is_file():
            value += (hashlib.sha256(path.read_bytes()).hexdigest(),)
        result[relative.as_posix()] = value
    return result


class OmpFixture(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="bp-omp-cli-")
        self.addCleanup(temporary.cleanup)
        self.project = Path(temporary.name).resolve()
        shutil.copytree(ROOT / "scripts", self.project / "scripts")
        self.env = {key: value for key, value in os.environ.items()
                    if not key.endswith("_SKILLS") and key not in (
                        "OMP_SKILLS", "SKILL_MD_PATH", "PYTHONDONTWRITEBYTECODE")}
        home = self.project / "isolated-home"
        home.mkdir()
        self.env.update(HOME=str(home), XDG_CONFIG_HOME=str(home / "config"),
                        XDG_DATA_HOME=str(home / "data"), PYTHON=sys.executable)
        self.env["PATH"] = os.pathsep.join([str(Path(sys.executable).parent)] + [
            part for part in os.environ.get("PATH", "").split(os.pathsep) if "mise/shims" not in part])
        self.skill("demo")

    def skill(self, name, body="# Demo\n\nRecord the observed change.\n", metadata="", directory=None):
        path = self.project / "skills" / (directory or name) / "SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"---\nname: {name}\ndescription: Inspect a concrete change.\nmodel: opus\n"
                        f"{metadata}---\n\n{body}", encoding="utf-8")
        return path

    def run_cli(self, arguments, expected=0, **kwargs):
        result = subprocess.run(arguments, cwd=self.project, env=self.env,
                                capture_output=True, text=True, **kwargs)
        if expected is not None:
            self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def shell(self, *arguments, expected=0, **kwargs):
        return self.run_cli(["bash", "scripts/sync-skills.sh", *arguments], expected, **kwargs)

    def engine(self, *arguments, expected=0, **kwargs):
        return self.run_cli([sys.executable, "scripts/lib/srp-engine.py", *map(str, arguments)],
                            expected, **kwargs)

    def generate(self, **kwargs):
        return self.shell("--target", "omp", **kwargs)

    def check(self, expected=0):
        return self.run_cli([sys.executable, "scripts/lib/omp-resources.py", "--check",
                             str(self.output)], expected)

    @property
    def output(self):
        return Path(self.env.get("OMP_SKILLS", str(self.project / ".omp/skills"))).parent

    def generated(self, name="demo"):
        return self.output / "skills" / name / "SKILL.md"

    def inventory(self):
        return json.loads((self.output / ".bigpowers-resources.json").read_text())

    def records(self):
        return {record["path"]: record for record in self.inventory()["resources"]}

    def assert_failure_unchanged(self, invoke):
        before = snapshot(self.project)
        result = invoke()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(snapshot(self.project), before)
        return result

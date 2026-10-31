#!/usr/bin/env python3
"""Render explicit repository-backed native OMP resources. story: e82s03"""
from __future__ import annotations
import json
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True

from omp_ownership import load_inventory, preflight, publish, safe_ancestors
from omp_projection import inside, render_skill, yaml_loader


def check(root: Path) -> None:
    records = load_inventory(root, required=True)
    if not records:
        raise ValueError(f"Ownership inventory has no native resources: {root}")
    for skill in {record["skill"] for record in records.values()}:
        commands = f"commands/bigpowers-{skill}.md"
        sources = [record for record in records.values() if record["skill"] == skill
                   and record["path"].endswith(f"/{skill}/SKILL.md") and record["type"] == "file"]
        if commands not in records or not sources:
            raise ValueError(f"Incomplete native skill/command ownership for {skill}: {root}")
    print(f"OMP resources verified: {len(records)} owned entries in {root}")


def generate(envelope: object) -> None:
    if not isinstance(envelope, dict) or set(envelope) != {"skills", "mode", "repo_root"}:
        raise ValueError("Expected OMP envelope with skills, mode and repo_root")
    mode, skills = envelope["mode"], envelope["skills"]
    if mode not in ("all", "single") or not isinstance(skills, list):
        raise ValueError("OMP mode must be all/single with a skills list")
    if mode == "single" and len(skills) != 1:
        raise ValueError("Single OMP render requires exactly one skill")
    if not isinstance(envelope["repo_root"], str) or not Path(envelope["repo_root"]).is_absolute():
        raise ValueError("OMP repo_root must be an absolute source repository path")
    repo = Path(envelope["repo_root"]).resolve(strict=True)
    if not repo.is_dir():
        raise ValueError(f"Source repository is not a directory: {repo}")
    configured = os.environ.get("OMP_SKILLS")
    if configured is not None and not configured:
        raise ValueError("OMP_SKILLS must not be empty")
    skills_dir = Path(os.path.abspath(configured or repo / ".omp" / "skills"))
    root = skills_dir.parent
    if skills_dir.name in ("commands", "agents", "extensions", "hooks"):
        raise ValueError(f"Unsafe OMP skills directory: {skills_dir}")
    safe_ancestors(skills_dir)
    previous = load_inventory(root)
    desired, names = {}, set()
    loader = yaml_loader()
    for record in skills:
        if not isinstance(record, dict):
            raise ValueError("Each OMP skill must be a metadata record")
        name = record.get("name")
        if not isinstance(name, str) or name in names:
            raise ValueError(f"Duplicate or invalid canonical name: {name!r}")
        source_value = record.get("source_path")
        if isinstance(source_value, str):
            source_dir = Path(source_value).parent.resolve(strict=True)
            if inside(root, source_dir) or inside(source_dir, root):
                raise ValueError(f"Source/output overlap refused: {source_dir} and {root}")
        names.add(name)
        rendered = render_skill(record, repo, root, skills_dir, loader)
        if desired.keys() & rendered.keys():
            raise ValueError(f"Duplicate native resource destinations for {name}")
        desired.update(rendered)
    preflight(root, desired, previous)
    stale = publish(root, desired, previous, mode)
    print(f"OMP resources generated: {len(skills)} skills, {len(desired)} owned entries in {root}")
    if stale:
        print("Retained stale/unselected owned resources (not pruned): " + ", ".join(stale))


def main() -> int:
    try:
        if sys.argv[1:2] == ["--check"] and len(sys.argv) == 3:
            check(Path(os.path.abspath(sys.argv[2])))
        elif len(sys.argv) != 1:
            raise ValueError("Usage: omp-resources.py [--check OMP_ROOT]; generation reads its JSON envelope from stdin")
        else:
            generate(json.load(sys.stdin))
    except (ValueError, OSError, UnicodeError) as error:
        print(f"omp-resources: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

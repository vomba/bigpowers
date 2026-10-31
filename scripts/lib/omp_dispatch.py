"""Explicit OMP dispatch; legacy adapters retain their original IR. story: e82s03"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Callable


def requests_omp(arguments: list[str]) -> bool:
    """Recognize the new OMP route without changing other target routes."""
    for index, argument in enumerate(arguments):
        if argument in ("--target=omp", "--target="):
            return True
        if argument == "--target":
            if index + 1 == len(arguments) or arguments[index + 1].startswith("--"):
                return True
            if arguments[index + 1] == "omp":
                return True
    return False


def omp_arguments(arguments: list[str]) -> tuple[bool, bool, str | None]:
    """Validate the OMP-only grammar before rendering or touching output."""
    target = None
    batch = dry_run = False
    sources: list[str] = []
    remaining = iter(arguments)
    for argument in remaining:
        if argument == "--target" or argument.startswith("--target="):
            if target is not None:
                raise ValueError("repeated --target; use exactly one --target omp")
            target = next(remaining, "") if argument == "--target" else argument[9:]
            if target != "omp":
                raise ValueError(f"invalid OMP target {target!r}; use --target omp")
        elif argument == "--all" and not batch:
            batch = True
        elif argument == "--dry-run" and not dry_run:
            dry_run = True
        elif argument.startswith("-"):
            raise ValueError(f"unsupported OMP argument {argument!r}; use --all --target omp or PATH --target omp")
        else:
            sources.append(argument)
    if target != "omp" or (batch and (sources or dry_run)) or (not batch and len(sources) != 1):
        raise ValueError("expected --all --target omp or PATH --target omp [--dry-run]")
    return batch, dry_run, None if batch else sources[0]


def validate_omp_target(root: Path, load_yaml: Callable) -> None:
    registry = root / "scripts" / "targets.yaml"
    if not registry.is_file():
        raise ValueError(f"OMP target registry is missing at {registry}; restore scripts/targets.yaml")
    targets = load_yaml(registry.read_text(encoding="utf-8"))
    records = targets.get("targets", []) if isinstance(targets, dict) else []
    selected = [entry for entry in records if isinstance(entry, dict) and entry.get("id") == "omp"]
    if len(selected) != 1 or not isinstance(selected[0].get("skill"), dict):
        raise ValueError("OMP must have exactly one skill target in scripts/targets.yaml")
    if selected[0]["skill"].get("adapter") != "omp" or not (root / "scripts/adapters/omp.sh").is_file():
        raise ValueError("OMP target adapter is unavailable; restore scripts/adapters/omp.sh")


def omp_metadata(source: str, load_yaml: Callable) -> dict:
    """Share native line-delimited parsing without touching the legacy parser."""
    from omp_projection import split_source

    content = Path(source).read_text(encoding="utf-8")
    try:
        data, body = split_source(content, Path(source), load_yaml)
    except Exception as error:
        raise ValueError(f"invalid native metadata in {source}; repair its frontmatter: {error}") from error
    return {"name": data.get("name", ""), "description": data.get("description", ""),
            "model": data.get("model", ""), "effort": data.get("effort", "standard"),
            "body": body.strip()}


def validate_omp_source(source: str, root: Path) -> None:
    """Refuse source escapes before reading native metadata, including dry runs."""
    path = Path(os.path.abspath(source))
    source_root = root.resolve() / "skills"
    if path.name != "SKILL.md" or path.resolve().parent.parent != source_root:
        raise ValueError(f"invalid OMP source {source}; use skills/<name>/SKILL.md inside {root}")
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError(f"symlinked OMP source {source}; use a regular source skill tree")


def run_omp(arguments: list[str], repo_root: str, *, load_yaml: Callable,
            iterate_skills: Callable, dispatch: Callable) -> None:
    """Build one private native batch; no legacy parser or stream changes."""
    try:
        batch, dry_run, source = omp_arguments(arguments)
        root = Path(repo_root)
        validate_omp_target(root, load_yaml)
        if batch and not (root / "skills").is_dir():
            raise ValueError(f"source skills directory missing at {root / 'skills'}; OMP needs canonical sources")
        paths = iterate_skills(repo_root) if batch else [source]
        records = []
        for path in paths:
            validate_omp_source(path, root)
            metadata = omp_metadata(path, load_yaml)
            if dry_run:
                print(json.dumps(metadata))
                return
            metadata["source_path"] = os.path.abspath(path)
            records.append(metadata)
        dispatch({"skills": records, "mode": "all" if batch else "single",
                  "repo_root": str(root)}, "omp", repo_root)
    except (OSError, ValueError, TypeError) as error:
        print(f"OMP dispatch: {error}", file=sys.stderr)
        raise SystemExit(2) from error

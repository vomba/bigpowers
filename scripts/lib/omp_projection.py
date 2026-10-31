"""Native OMP source/asset projection, independent of the flattened skill IR."""
from __future__ import annotations
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
from urllib.parse import quote, unquote, urlsplit
from typing import Callable, Iterator

from link_utils import LINK_RE, strip_code_spans
from omp_ownership import NAME, resource

POLICY = """## Native OMP execution boundary

This skill supplies instructions, not a model switch or permission to spawn.
Keep consultation and small work inline; inline use leaves the parent model unchanged.
Preserve this workflow's stages, acceptance criteria, review independence and review count.
Delegate only useful workflow work allowed by both the exposed tool contract and parent
spawn policy. Choose an existing agent by responsibility, never by source model tiers:
implementation uses the implementation-capable task agent; independent review uses
reviewer; delegated security analysis uses security-reviewer; warranted exploratory
repository research uses scout. Availability alone does not authorize delegation.
For implementation, omit the agent selector only if the tool's actual default resolves
to task. Select task explicitly only if that exposed contract permits it as a non-default.
If task is absent or disallowed, report the boundary: do not substitute a research agent,
create an agent, override the model, or change spawn settings. Respect stricter tool policy.
User-owned task.agentModelOverrides, agent configuration and modelRoles determine native
allocation at spawn time; source model names/examples do not override that resolution.
Do not choose concrete providers/models, persist settings, or invent role fallbacks.

Loading resources, command expansion, startup and directory entry never activate projects.
Before artifact-producing workflow steps, require verified owned protected Bigpowers
integration and explicit authorization. Otherwise keep consultation/planning chat-only.
Use only the separately managed bounded `bigpowers --context FILE status|init|remove`
lifecycle; status and init/remove without --yes are read-only. Only explicitly authorized
init --yes may provision after preflight and real command declarations. If unavailable,
report it; never replace it with upstream setup/install/sync/init or npx commands.
Respect current repository policies and common-directory exclusions across linked worktrees.
Preserve existing user skills, prompts, agent-role allocations, MCP services, memory backend,
credentials, signing and sessions. Resource ownership is not operational permission.
This instruction-based policy is not a filesystem sandbox or deterministic agent enforcement.

"""


def yaml_loader() -> Callable[[str], object]:
    spec = importlib.util.spec_from_file_location("omp_source_srp", Path(__file__).with_name("srp-engine.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._load_yaml


def inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def source_file(path: Path, repo: Path) -> Path:
    resolved = path.resolve(strict=True)
    if not inside(resolved, repo):
        raise ValueError(f"Escaping source path/link refused: {path}")
    if not resolved.is_file():
        raise ValueError(f"Required source file is not regular: {path}")
    return resolved


def split_source(text: str, path: Path, loader: Callable[[str], object]) -> tuple[dict, str]:
    match = re.match(r"\A(?:\ufeff)?---[ \t]*\r?\n(.*?)^---[ \t]*\r?\n", text, re.M | re.S)
    if not match:
        raise ValueError(f"Invalid native skill frontmatter: {path}")
    header = re.sub(r"<!--.*?-->", "", match.group(1), flags=re.S)
    metadata = loader(header)
    if not isinstance(metadata, dict):
        raise ValueError(f"Invalid native skill metadata: {path}")
    return metadata, text[match.end():]


def native_header(record: dict, metadata: dict) -> str:
    name, description = record.get("name"), record.get("description")
    if metadata.get("name") != name:
        raise ValueError(f"Canonical/source name mismatch: {name!r}")
    if not isinstance(description, str) or not description.strip():
        raise ValueError(f"Skill {name} needs a non-empty description")
    header = {"name": name, "description": description}
    for key in ("hide", "disable-model-invocation"):
        if key in metadata:
            if type(metadata[key]) is not bool:
                raise ValueError(f"Native {key} must be boolean for {name}")
            header[key] = metadata[key]
    # JSON scalars are valid YAML and safely encode multiline descriptions.
    return "---\n" + "".join(f"{key}: {json.dumps(value, ensure_ascii=False)}\n"
                                for key, value in header.items()) + "---\n\n"


def project_links(text: str, source: Path, destination: Path, skill_dir: Path,
                  repo: Path, dependencies: set[Path]) -> str:
    shadow = strip_code_spans(text)
    replacements = []
    for match in LINK_RE.finditer(shadow):
        raw = match.group(2)
        parsed = urlsplit(raw)
        if not raw or raw.startswith("#") or (parsed.scheme and parsed.scheme != "file"):
            continue
        if parsed.scheme == "file":
            target = Path(unquote(parsed.path))
        elif raw.startswith("/"):
            target = Path(unquote(parsed.path))
        else:
            target = source.parent / unquote(parsed.path)
        resolved = target.resolve(strict=True)
        if not inside(resolved, repo):
            raise ValueError(f"Escaping source dependency refused: {source}: {raw}")
        if not resolved.is_file() and not resolved.is_dir():
            raise ValueError(f"Unreadable source dependency: {source}: {raw}")
        if not os.access(resolved, os.R_OK):
            raise ValueError(f"Unreadable source dependency: {resolved}")
        if inside(resolved, skill_dir):
            projected = destination.parents[len(source.relative_to(skill_dir).parts) - 1] / resolved.relative_to(skill_dir)
            value = quote(os.path.relpath(projected, destination.parent), safe="/.-_")
        else:
            dependencies.add(resolved)
            value = resolved.as_uri()
        if parsed.query:
            value += "?" + parsed.query
        if parsed.fragment:
            value += "#" + parsed.fragment
        start, end = match.span(2)
        replacements.append((start, end, value))
    for start, end, value in reversed(replacements):
        text = text[:start] + value + text[end:]
    return text


def walk_assets(directory: Path, repo: Path, ancestry: tuple[Path, ...] = (),
                boundary: Path | None = None) -> Iterator[tuple[Path, str, int]]:
    resolved = directory.resolve(strict=True)
    boundary = boundary or resolved
    if not inside(resolved, boundary) or not inside(resolved, repo) or resolved in ancestry:
        raise ValueError(f"Escaping or cyclic source directory: {directory}")
    for entry in sorted(directory.iterdir()):
        actual = entry.resolve(strict=True)
        if not inside(actual, repo) or not inside(actual, boundary):
            raise ValueError(f"Escaping source link refused: {entry}")
        mode = stat.S_IMODE(actual.stat().st_mode)
        if mode & 0o7000:
            raise ValueError(f"Unsafe source mode: {entry}")
        if actual.is_dir():
            yield entry, "directory", mode
            yield from walk_assets(entry, repo, (*ancestry, resolved), boundary)
        elif actual.is_file():
            yield entry, "file", mode
        else:
            raise ValueError(f"Unsupported source object: {entry}")

def render_skill(record: dict, repo: Path, root: Path, skills_dir: Path,
                 loader: Callable[[str], object]) -> dict[str, tuple[dict, bytes | None]]:
    name = record.get("name")
    if not isinstance(name, str) or not NAME.fullmatch(name):
        raise ValueError(f"Unsafe canonical skill name: {name!r}")
    value = record.get("source_path")
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise ValueError(f"Skill {name} requires an absolute source_path")
    source = Path(value)
    actual = source_file(source, repo)
    if source.name != "SKILL.md":
        raise ValueError(f"Skill source must be SKILL.md: {source}")
    skill_dir = source.parent.resolve(strict=True)
    if not inside(skill_dir, repo):
        raise ValueError(f"Escaping source directory: {source.parent}")
    destination_dir = skills_dir / name
    metadata, body = split_source(actual.read_text(encoding="utf-8"), source, loader)
    dependencies, output = set(), {}
    prefix = destination_dir.relative_to(root).as_posix()
    output[prefix] = resource(prefix, "directory", stat.S_IMODE(skill_dir.stat().st_mode), name)
    for entry, kind, mode in walk_assets(skill_dir, repo):
        relative = entry.relative_to(skill_dir)
        destination = destination_dir / relative
        key = destination.relative_to(root).as_posix()
        data = None
        if kind == "file":
            data = entry.read_bytes()
            if entry == skill_dir / "SKILL.md":
                text = native_header(record, metadata) + POLICY + project_links(
                    body, entry, destination, skill_dir, repo, dependencies)
                data = text.encode("utf-8")
            elif entry.suffix.lower() == ".md":
                data = project_links(data.decode("utf-8"), entry, destination,
                                     skill_dir, repo, dependencies).encode("utf-8")
        output[key] = resource(key, kind, mode, name, data)
    if dependencies:
        key = f"{prefix}/SKILL.md"
        record_out, data = output[key]
        listing = "\n## Source-repository dependencies\n\n" + "".join(
            f"- {path.as_uri()}\n" for path in sorted(dependencies))
        output[key] = resource(key, "file", record_out["mode"], name, data + listing.encode())
    key = f"commands/bigpowers-{name}.md"
    # URI escaping prevents native $1/$ARGUMENTS expansion inside a source path.
    command = (f"Read the generated native skill file {json.dumps((destination_dir / 'SKILL.md').as_uri())} "
               "and follow its workflow and execution boundary.\n\n"
               "<bigpowers-arguments>\n$ARGUMENTS\n</bigpowers-arguments>\n")
    output[key] = resource(key, "file", 0o644, name, command.encode("utf-8"))
    return output

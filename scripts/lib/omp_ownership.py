"""Owned native OMP resource validation and inventory-last publication."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile

INVENTORY = ".bigpowers-resources.json"
NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_ancestors(path: Path) -> None:
    """Refuse symlink/retyped ancestors without resolving away their evidence."""
    path = Path(os.path.abspath(path))
    for ancestor in reversed((path, *path.parents)):
        if ancestor.is_symlink():
            raise ValueError(f"Symlink output path refused: {ancestor}")
        if ancestor.exists() and not ancestor.is_dir():
            raise ValueError(f"Output ancestor is not a directory: {ancestor}")


def relative_path(value: object) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError(f"Unsafe inventory path: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(p in ("", ".", "..") for p in value.split("/")):
        raise ValueError(f"Unsafe inventory path: {value!r}")
    return path


def validate_record(record: object) -> None:
    if not isinstance(record, dict) or set(record) != {
        "path", "type", "sha256", "mode", "skill", "status"
    }:
        raise ValueError("Invalid ownership resource record")
    path = relative_path(record["path"])
    name = record["skill"]
    if not isinstance(name, str) or not NAME.fullmatch(name):
        raise ValueError(f"Invalid inventory skill: {name!r}")
    skill_path = PurePosixPath(path.parts[0]) / name
    allowed = (NAME.fullmatch(path.parts[0]) is not None
               and path.parts[0] not in ("commands", "agents", "extensions", "hooks", "providers", "memory", "sessions")
               and (path == skill_path or skill_path in path.parents))
    command = path == PurePosixPath("commands") / f"bigpowers-{name}.md"
    if not allowed and not command:
        raise ValueError(f"Inventory path outside native resource namespace: {path}")
    if record["type"] not in ("file", "directory") or (command and record["type"] != "file"):
        raise ValueError(f"Invalid owned object type: {path}")
    mode = record["mode"]
    if type(mode) is not int or mode < 0 or mode > 0o777:
        raise ValueError(f"Invalid owned mode: {path}")
    fingerprint = record["sha256"]
    if record["type"] == "file":
        if not isinstance(fingerprint, str) or not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
            raise ValueError(f"Invalid content digest: {path}")
    elif fingerprint is not None:
        raise ValueError(f"Invalid directory digest: {path}")
    if record["status"] not in ("active", "catalog-stale"):
        raise ValueError(f"Invalid catalog status: {path}")


def verify_entry(root: Path, record: dict) -> None:
    path = root / record["path"]
    safe_ancestors(path.parent)
    if path.is_symlink() or not path.exists():
        raise ValueError(f"Owned resource missing or retyped: {path}; restore its recorded version")
    info = path.stat()
    kind = "directory" if stat.S_ISDIR(info.st_mode) else "file" if stat.S_ISREG(info.st_mode) else "other"
    if kind != record["type"] or stat.S_IMODE(info.st_mode) != record["mode"]:
        raise ValueError(f"Owned resource type/mode changed: {path}; restore its recorded version")
    if kind == "file" and digest(path.read_bytes()) != record["sha256"]:
        raise ValueError(f"Owned resource edited: {path}; restore its recorded version")
    if not os.access(path, os.R_OK):
        raise ValueError(f"Owned resource is not readable: {path}")


def load_inventory(root: Path, required: bool = False) -> dict[str, dict]:
    safe_ancestors(root)
    if root.exists():
        for directory, dirs, files in os.walk(root, followlinks=False):
            for name in dirs + files:
                if name.startswith(".bigpowers-tmp-"):
                    raise ValueError(f"Interrupted publication residue: {Path(directory) / name}; inspect before retry")
    inventory = root / INVENTORY
    if inventory.is_symlink():
        raise ValueError(f"Symlink inventory refused: {inventory}")
    if not inventory.exists():
        if required:
            raise ValueError(f"Missing ownership inventory: {inventory}; explicitly generate OMP resources first")
        return {}
    if not inventory.is_file():
        raise ValueError(f"Ownership inventory is not a regular file: {inventory}")
    try:
        data = json.loads(inventory.read_text(encoding="utf-8"))
    except (ValueError, OSError) as error:
        raise ValueError(f"Unreadable ownership inventory {inventory}: {error}") from error
    if (not isinstance(data, dict) or set(data) != {"version", "resources"}
            or type(data["version"]) is not int or data["version"] != 1):
        raise ValueError(f"Unsupported ownership inventory: {inventory}")
    if not isinstance(data["resources"], list):
        raise ValueError(f"Invalid resources list: {inventory}")
    records = {}
    for record in data["resources"]:
        validate_record(record)
        key = record["path"]
        if key in records:
            raise ValueError(f"Duplicate ownership path: {key}")
        verify_entry(root, record)
        records[key] = record
    return records


def resource(path: str, kind: str, mode: int, skill: str,
             data: bytes | None = None) -> tuple[dict, bytes | None]:
    record = {"path": path, "type": kind, "mode": mode, "skill": skill,
              "sha256": digest(data) if data is not None else None, "status": "active"}
    validate_record(record)
    return record, data


def preflight(root: Path, desired: dict[str, tuple[dict, bytes | None]],
              previous: dict[str, dict]) -> None:
    for key, (record, _) in desired.items():
        validate_record(record)
        path = root / key
        safe_ancestors(path.parent)
        if key in previous:
            if previous[key]["type"] != record["type"]:
                raise ValueError(f"Owned resource cannot change type: {path}")
        elif path.exists() or path.is_symlink():
            raise ValueError(f"Unowned resource collision: {path}; ownership is never inferred from matching bytes")
    for key in desired:
        for ancestor in PurePosixPath(key).parents:
            value = str(ancestor)
            if value in desired and desired[value][0]["type"] != "directory":
                raise ValueError(f"Resource conflicts with file ancestor: {value}")


def atomic_file(path: Path, data: bytes, mode: int) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=".bigpowers-tmp-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fchmod(stream.fileno(), mode)
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def publish(root: Path, desired: dict[str, tuple[dict, bytes | None]],
            previous: dict[str, dict], mode: str) -> list[str]:
    merged = {key: dict(value) for key, value in previous.items()}
    if mode == "all":
        for record in merged.values():
            if record["path"] not in desired:
                record["status"] = "catalog-stale"
    for key, (record, _) in desired.items():
        merged[key] = record
    completed = []
    current = root
    try:
        root.mkdir(parents=True, exist_ok=True)
        for key, (record, data) in sorted(desired.items(), key=lambda item: (len(PurePosixPath(item[0]).parts), item[0])):
            current = root / key
            safe_ancestors(current.parent)
            current.parent.mkdir(parents=True, exist_ok=True)
            if record["type"] == "directory":
                if key not in previous:
                    current.mkdir(mode=record["mode"])
                    current.chmod(record["mode"])
                    completed.append(key)
                elif previous[key] != record:
                    current.chmod(record["mode"])
                    completed.append(key)
            elif key not in previous or previous[key] != record:
                atomic_file(current, data, record["mode"])
                completed.append(key)
        current = root / INVENTORY
        payload = (json.dumps({"version": 1, "resources": [merged[k] for k in sorted(merged)]},
                              indent=2, sort_keys=True) + "\n").encode()
        if not current.exists() or current.read_bytes() != payload:
            atomic_file(current, payload, 0o644)
    except (OSError, ValueError) as error:
        raise ValueError(f"Partial OMP publication failed at {current}; completed paths: "
                         f"{', '.join(completed) or '(none)'}; inventory not advanced: {error}") from error
    stale = sorted(key for key, value in merged.items() if value["status"] == "catalog-stale" or key not in desired)
    return stale

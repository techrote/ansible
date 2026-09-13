"""Trusted local configuration and conservative repository discovery.

This is operator-owned local configuration, never task data.  Only the two fixed
repository identifiers used by the current program can be resolved.  Discovery is
limited to explicit absolute paths or sibling directories beside this checkout.
"""
from __future__ import annotations

from pathlib import Path
import re
import stat
from typing import Any

from .contract import Refusal, check, decode, safe_relative
from .state import StateError, default_state_root, read_bytes

ROOT = Path(__file__).resolve().parent.parent
KNOWN_REPOSITORIES = frozenset({"intrallm", "dashminimix"})
MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+-]{0,119}$")
MAX_CONFIG_BYTES = 32768


class ConfigError(ValueError):
    pass


def _plain(path: Path) -> Path:
    """Resolve an operator path and refuse symlink/reparse redirection in ancestors."""
    absolute = path.expanduser().absolute()
    for part in reversed((absolute, *absolute.parents)):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ConfigError("PATH_REDIRECTION_REFUSED")
    try:
        return absolute.resolve(strict=False)
    except OSError as exc:
        raise ConfigError("PATH_RESOLUTION_FAILED") from exc


def _read_json(path: Path) -> Any:
    try:
        raw = read_bytes(path, MAX_CONFIG_BYTES)
    except FileNotFoundError:
        return {}
    except StateError as exc:
        code = "CONFIG_TOO_LARGE" if str(exc) == "STATE_SIZE_LIMIT" else str(exc)
        raise ConfigError(code) from exc
    try:
        return decode(raw)
    except Refusal as exc:
        code = {"DUPLICATE_KEY": "DUPLICATE_CONFIG_KEY",
                "NONFINITE_NUMBER": "NONFINITE_CONFIG_NUMBER",
                "INPUT_COMPLEXITY": "CONFIG_COMPLEXITY"}.get(exc.code, "INVALID_LOCAL_CONFIG")
        raise ConfigError(code) from exc


def _repository(path_value: Any, name: str) -> Path:
    if type(path_value) is not str or not path_value:
        raise ConfigError(f"INVALID_REPOSITORY_PATH_{name.upper()}")
    path = Path(path_value)
    if not path.is_absolute():
        raise ConfigError(f"REPOSITORY_PATH_NOT_ABSOLUTE_{name.upper()}")
    path = _plain(path)
    if not path.is_dir() or not (path / ".git").exists():
        raise ConfigError(f"REPOSITORY_NOT_GIT_CHECKOUT_{name.upper()}")
    return path


def load(path: Path | None = None) -> dict:
    path = _plain(path or ROOT / "config" / "local.json")
    value = _read_json(path)
    if type(value) is not dict:
        raise ConfigError("CONFIG_NOT_OBJECT")
    try:
        check(value, "config-v1.schema.json")
    except Refusal as exc:
        raise ConfigError("INVALID_LOCAL_CONFIG_SCHEMA") from exc
    allowed = {"$comment", "repositories", "slots_dir", "approved_models", "local_state_dir", "remote_slots_enabled"}
    if value.keys() - allowed:
        raise ConfigError("UNKNOWN_CONFIG_KEY")

    normalized = {"repositories": {}, "slots_dir": "slots", "approved_models": ["none"],
                  "local_state_dir": None, "remote_slots_enabled": False}
    repositories = value.get("repositories", {})
    if type(repositories) is not dict or repositories.keys() - KNOWN_REPOSITORIES:
        raise ConfigError("INVALID_REPOSITORIES_CONFIG")
    for name, raw in repositories.items():
        normalized["repositories"][name] = str(_repository(raw, name))

    if "slots_dir" in value:
        if type(value["slots_dir"]) is not str:
            raise ConfigError("INVALID_SLOTS_DIR")
        try:
            safe_relative(value["slots_dir"])
        except Refusal as exc:
            raise ConfigError("INVALID_SLOTS_DIR") from exc
        normalized["slots_dir"] = value["slots_dir"]

    if "approved_models" in value:
        models = value["approved_models"]
        if (type(models) is not list or len(models) > 100
                or any(type(model) is not str or not MODEL_RE.fullmatch(model) for model in models)
                or len(set(models)) != len(models)):
            raise ConfigError("INVALID_MODEL_ALLOWLIST")
        normalized["approved_models"] = models[:] if models else ["none"]

    if "local_state_dir" in value:
        raw = value["local_state_dir"]
        if type(raw) is not str or not Path(raw).is_absolute():
            raise ConfigError("STATE_ROOT_NOT_ABSOLUTE")
        normalized["local_state_dir"] = str(_plain(Path(raw)))
    normalized["remote_slots_enabled"] = value.get("remote_slots_enabled", False)
    return normalized


def resolve_repository(name: str, config: dict | None = None, root: Path = ROOT) -> Path | None:
    if name not in KNOWN_REPOSITORIES:
        raise ConfigError("UNKNOWN_REPOSITORY_IDENTIFIER")
    config = config if config is not None else load()
    raw = config.get("repositories", {}).get(name)
    if raw:
        return _repository(raw, name)
    candidate = _plain(root.parent / name)
    if candidate.is_dir() and (candidate / ".git").exists():
        return candidate
    return None


def state_root(config: dict | None = None) -> Path:
    config = config if config is not None else load()
    if config.get("local_state_dir"):
        return _plain(Path(config["local_state_dir"]))
    try:
        return _plain(default_state_root())
    except StateError as exc:
        raise ConfigError(str(exc)) from exc


def assert_state_root_isolated(path: Path, config: dict | None = None, root: Path = ROOT) -> Path:
    candidate = _plain(path)
    protected = [_plain(root)]
    config = config if config is not None else load()
    for name in sorted(KNOWN_REPOSITORIES):
        resolved = resolve_repository(name, config=config, root=root)
        if resolved is not None:
            protected.append(_plain(resolved))
    for repo in protected:
        try:
            candidate.relative_to(repo)
        except ValueError:
            continue
        raise ConfigError("STATE_ROOT_INSIDE_GIT_CHECKOUT")
    return candidate

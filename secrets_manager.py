"""Local secrets with explicit keys, private atomic writes and no read side effects.

A cleared secret is kept as an empty .env entry. This suppresses inherited
environment values after a restart, rather than silently restoring a cleared key.
"""

from __future__ import annotations

import io
import os
from pathlib import Path
import re
import stat
import tempfile
import threading

from dotenv import dotenv_values

import config


ENV_PATH = config.BASE_DIR / ".env"
SECRET_ENV_KEYS = {
    "telegram_bot_token": "TELEGRAM_BOT_TOKEN",
    "search_model_api_key": "SEARCH_MODEL_API_KEY",
    "writer_model_api_key": "WRITER_MODEL_API_KEY",
    "perplexity_api_key": "PERPLEXITY_API_KEY",
    "openai_api_key": "OPENAI_API_KEY",
}
_ALLOWED_KEYS = frozenset(SECRET_ENV_KEYS.values())
_ENV_LOCK = threading.RLock()
_MAX_ENV_BYTES = 128 * 1024


def _require_key(env_key: str) -> None:
    if env_key not in _ALLOWED_KEYS:
        raise ValueError("Unsupported secret key")


def _checked_env_path() -> Path:
    path = Path(ENV_PATH).absolute()
    for component in (path, *path.parents):
        if component.is_symlink():
            raise ValueError("Symlink secret path is not supported")
    if not path.parent.is_dir():
        raise ValueError("Secret directory is missing")
    return path


def _read_env_map() -> dict:
    path = _checked_env_path()
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(path, flags)
    except FileNotFoundError:
        return {}
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("Secret input must be a regular file without hard links")
        current = path.lstat()
        if stat.S_ISLNK(current.st_mode) or (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
            raise ValueError("Secret input changed while opening")
        if os.name == "posix":
            os.fchmod(stream.fileno(), 0o600)
        raw = stream.read(_MAX_ENV_BYTES + 1)
    if len(raw) > _MAX_ENV_BYTES:
        raise ValueError("Secret input is too large")
    # Interpolation could read unrelated process variables. Values are literal.
    values = dotenv_values(stream=io.StringIO(raw.decode("utf-8")), interpolate=False)
    return {str(key): str(value or "") for key, value in values.items()}


def read_env_map() -> dict:
    """Read this project's .env; a missing file remains missing."""
    with _ENV_LOCK:
        return _read_env_map()


def get_secret(env_key: str, default: str = "") -> str:
    _require_key(env_key)
    env_map = read_env_map()
    if env_key in env_map:
        return env_map[env_key]
    return os.getenv(env_key, default)


def has_secret(env_key: str) -> bool:
    return bool(get_secret(env_key).strip())


def _write_env_map(values: dict) -> None:
    path = _checked_env_path()
    lines = []
    for key, value in values.items():
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise ValueError("Unsupported .env key format")
        escaped = str(value).replace("\\", "\\\\").replace("'", "\\'")
        lines.append(f"{key}='{escaped}'\n")
    content = "".join(lines).encode("utf-8")
    if len(content) > _MAX_ENV_BYTES:
        raise ValueError("Secret output is too large")
    fd, temporary = tempfile.mkstemp(prefix=".env-", suffix=".tmp", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd, "wb") as stream:
            if os.name == "posix":
                os.fchmod(stream.fileno(), 0o600)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        # replace publishes a directory entry; it does not write through it.
        _checked_env_path()
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def set_secret(env_key: str, value: str):
    _require_key(env_key)
    if not isinstance(value, str):
        raise ValueError("Secret must be text")
    cleaned = value.strip()
    if len(cleaned) > 16384 or any(ord(ch) < 32 or ord(ch) == 127 for ch in cleaned):
        raise ValueError("Invalid secret format")
    with _ENV_LOCK:
        values = _read_env_map()
        values[env_key] = cleaned
        _write_env_map(values)
        os.environ[env_key] = cleaned


def clear_secret(env_key: str):
    _require_key(env_key)
    with _ENV_LOCK:
        values = _read_env_map()
        values[env_key] = ""
        _write_env_map(values)
        # Disk errors propagate before the process environment is modified.
        os.environ.pop(env_key, None)


def secret_statuses() -> dict:
    return {name: has_secret(env_key) for name, env_key in SECRET_ENV_KEYS.items()}

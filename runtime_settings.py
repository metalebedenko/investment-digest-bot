"""
Runtime-настройки проекта.

Здесь хранятся все параметры, которыми управляет админ-панель:
- Telegram
- настройки дайджеста
- выбор тем
- параметры search/writer моделей

При первом запуске создаются:
- state/runtime_settings_baseline.json
- state/runtime_settings.json

Baseline фиксирует текущее рабочее состояние, чтобы к нему можно было вернуться.
"""

from __future__ import annotations

import json
import os
import tempfile
from urllib.parse import urlsplit
from copy import deepcopy

import config
import secrets_manager


def _default_settings() -> dict:
    theme_ids = config.get_theme_ids()
    env = secrets_manager.read_env_map()
    def setting(name, fallback):
        return os.environ.get(name, env.get(name) or fallback)
    return {
        "version": 1,
        "baseline_note": "Снимок исходных рабочих настроек проекта",
        "telegram": {
            "chat_id": setting("TELEGRAM_CHAT_ID", ""),
            "test_chat_id": "",
        },
        "digest": {
            "ideas_count_min": max(1, min(10, int(setting("IDEAS_COUNT_MIN", "5")))),
            "ideas_count_max": max(1, min(10, int(setting("IDEAS_COUNT_MAX", "10")))),
            "cover_title": "ИНВЕСТИЦИОННЫЙ ДАЙДЖЕСТ",
            "cover_subtitle": (
                "Ежедневный обзор бизнес-моделей и инвестиционных гипотез, "
                "для последующей самостоятельной проверки."
            ),
            "focus_line": "Производственные, торговые и воспроизводимые бизнес-модели",
            "disclaimer": (
                "Исследовательский прототип. Факты и оценки требуют проверки. "
                "Текст носит аналитический характер и не является индивидуальной "
                "инвестиционной рекомендацией."
            ),
            "footer_brand": config.DEFAULT_FOOTER_BRAND,
            "brand_name": config.DEFAULT_BRAND_NAME,
        },
        "themes": {
            "mode": "rotate",
            "fixed_theme_id": "dark_investment",
            "enabled_theme_ids": theme_ids,
        },
        "topic_memory": {
            "enabled": True,
            "recent_issue_window": 5,
        },
        "schedule": {
            "enabled": False,
            "frequency": "daily",
            "hour": 10,
            "minute": 45,
            "interval_hours": 24,
        },
        "models": {
            "search": {
                "source_provider": "duckduckgo",
                "provider": "ollama",
                "enabled": True,
                "model": "gpt-oss:120b-cloud",
                "base_url": "http://localhost:11434",
                "api_key_env_var": "SEARCH_MODEL_API_KEY",
                "temperature": 0.7,
                "timeout_sec": 240,
            },
            "writer": {
                "enabled": False,
                "provider": "ollama",
                "model": "gpt-oss:120b-cloud",
                "base_url": "http://localhost:11434",
                "api_key_env_var": "WRITER_MODEL_API_KEY",
                "temperature": 0.7,
                "timeout_sec": 180,
                "style_prompt": (
                    "Пиши как внимательный редактор для инвесторов: живо, по делу, "
                    "без бюрократического канцелярита, с акцентом на решение, рынок, "
                    "момент входа и практический смысл идеи."
                ),
            },
            "fallbacks": {
                "perplexity_api_key_env_var": "PERPLEXITY_API_KEY",
                "openai_api_key_env_var": "OPENAI_API_KEY",
            },
        },
    }


def _ensure_parent_dirs():
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)


def _read_json(path, fallback: dict) -> dict:
    if not path.exists():
        return deepcopy(fallback)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else deepcopy(fallback)
    except Exception:
        return deepcopy(fallback)


def _write_json(path, data: dict):
    if path.is_symlink():
        raise ValueError("Refusing a symlink settings file")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            temporary = stream.name
            json.dump(data, stream, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            os.unlink(temporary)


def _deep_merge(base: dict, override: dict) -> dict:
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _normalize_settings(data: dict) -> dict:
    defaults = _default_settings()
    merged = _deep_merge(defaults, data)
    merged.get("telegram", {}).pop("bot_token", None)
    merged.get("models", {}).get("search", {}).pop("api_key", None)
    merged.get("models", {}).get("writer", {}).pop("api_key", None)
    merged.get("models", {}).get("fallbacks", {}).pop("perplexity_api_key", None)
    merged.get("models", {}).get("fallbacks", {}).pop("openai_api_key", None)

    min_count = int(merged["digest"].get("ideas_count_min", defaults["digest"]["ideas_count_min"]))
    max_count = int(merged["digest"].get("ideas_count_max", defaults["digest"]["ideas_count_max"]))
    min_count = max(1, min(10, min_count))
    max_count = max(min_count, min(10, max_count))
    merged["digest"]["ideas_count_min"] = min_count
    merged["digest"]["ideas_count_max"] = max_count

    valid_theme_ids = set(config.get_theme_ids())
    enabled = [
        theme_id
        for theme_id in merged["themes"].get("enabled_theme_ids", [])
        if theme_id in valid_theme_ids
    ]
    if not enabled:
        enabled = config.get_theme_ids()
    merged["themes"]["enabled_theme_ids"] = enabled

    fixed_theme_id = merged["themes"].get("fixed_theme_id", enabled[0])
    if fixed_theme_id not in valid_theme_ids:
        fixed_theme_id = enabled[0]
    merged["themes"]["fixed_theme_id"] = fixed_theme_id

    if merged["themes"].get("mode") not in {"rotate", "fixed"}:
        merged["themes"]["mode"] = "rotate"

    topic_memory = merged.get("topic_memory", {})
    topic_memory["enabled"] = bool(topic_memory.get("enabled", True))
    topic_memory["recent_issue_window"] = max(1, min(100, int(topic_memory.get("recent_issue_window", 5))))
    merged["topic_memory"] = topic_memory

    schedule = merged.get("schedule", {})
    if schedule.get("frequency") not in {"daily", "hourly"}:
        schedule["frequency"] = "daily"
    schedule["hour"] = max(0, min(23, int(schedule.get("hour", 10))))
    schedule["minute"] = max(0, min(59, int(schedule.get("minute", 45))))
    schedule["interval_hours"] = max(1, min(24, int(schedule.get("interval_hours", 24))))
    schedule["enabled"] = bool(schedule.get("enabled", False))
    merged["schedule"] = schedule

    for key in ("search", "writer"):
        provider = merged["models"][key].get("provider", "ollama")
        if provider not in {"ollama", "openai_compatible", "openai"}:
            merged["models"][key]["provider"] = "ollama"
        merged["models"][key]["timeout_sec"] = max(30, int(merged["models"][key].get("timeout_sec", 120)))
        base_url = merged["models"][key].get("base_url", defaults["models"][key]["base_url"])
        parsed = urlsplit(base_url)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment
                or (parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"})):
            raise ValueError("Model endpoint must use HTTPS or loopback HTTP, without credentials or a query")
        merged["models"][key]["api_key_env_var"] = defaults["models"][key]["api_key_env_var"]

    source_provider = merged["models"]["search"].get("source_provider", "duckduckgo")
    if source_provider not in {"duckduckgo", "perplexity", "openai_search"}:
        merged["models"]["search"]["source_provider"] = "duckduckgo"

    fallbacks = merged["models"].get("fallbacks", {})
    fallbacks["perplexity_api_key_env_var"] = (
        defaults["models"]["fallbacks"]["perplexity_api_key_env_var"]
    )
    fallbacks["openai_api_key_env_var"] = (
        defaults["models"]["fallbacks"]["openai_api_key_env_var"]
    )
    merged["models"]["fallbacks"] = fallbacks

    merged["version"] = defaults["version"]
    return merged


def ensure_settings_files():
    """Создаёт baseline и runtime settings при первом запуске."""
    _ensure_parent_dirs()
    defaults = _default_settings()

    if not config.RUNTIME_BASELINE_FILE.exists():
        _write_json(config.RUNTIME_BASELINE_FILE, defaults)
    else:
        baseline = _read_json(config.RUNTIME_BASELINE_FILE, defaults)
        normalized_baseline = _normalize_settings(baseline)
        if normalized_baseline != baseline:
            _write_json(config.RUNTIME_BASELINE_FILE, normalized_baseline)

    if not config.RUNTIME_SETTINGS_FILE.exists():
        _write_json(config.RUNTIME_SETTINGS_FILE, defaults)
    else:
        current = _read_json(config.RUNTIME_SETTINGS_FILE, defaults)
        normalized = _normalize_settings(current)
        if normalized != current:
            _write_json(config.RUNTIME_SETTINGS_FILE, normalized)


def get_settings() -> dict:
    ensure_settings_files()
    data = _read_json(config.RUNTIME_SETTINGS_FILE, _default_settings())
    return _normalize_settings(data)


def get_baseline_settings() -> dict:
    ensure_settings_files()
    data = _read_json(config.RUNTIME_BASELINE_FILE, _default_settings())
    return _normalize_settings(data)


def save_settings(updated: dict) -> dict:
    normalized = _normalize_settings(updated)
    _write_json(config.RUNTIME_SETTINGS_FILE, normalized)
    return normalized


def reset_to_baseline() -> dict:
    baseline = get_baseline_settings()
    _write_json(config.RUNTIME_SETTINGS_FILE, baseline)
    return baseline

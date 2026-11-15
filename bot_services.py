"""
Сервисный слой для запуска бота и админ-панели.
"""

from __future__ import annotations

import logging
import random
from datetime import datetime

import config
import editorial_ai
import generic_searcher
import pdf_generator
import scheduler_runtime
import searcher
import secrets_manager
import state_manager
import telegram_sender
from idea_validation import MAX_IDEAS, validate_count, validate_ideas
from runtime_settings import ensure_settings_files, get_baseline_settings, get_settings, reset_to_baseline, save_settings


logger = logging.getLogger(__name__)


def ping_bot() -> bool:
    settings = get_settings()
    text = f"Investment Digest Bot — тест ({datetime.now():%d.%m.%Y %H:%M})"
    return telegram_sender.send_text_message(text, settings=settings)


def send_group_message(text: str) -> bool:
    settings = get_settings()
    return telegram_sender.send_text_message(text, settings=settings)


def run_digest(*, demo: bool = False, pdf_only: bool = False, count_override: int = 0, preview: bool = False) -> dict:
    validate_count(count_override, allow_auto=True)
    if demo:
        # An offline demonstration must not inherit live settings, keys or history.
        settings = _demo_settings()
        issue_number = 1
        theme = config.get_visual_theme("light_editorial")
        count = count_override or 5
        ideas = searcher.get_demo_ideas()
        editorial = None
    else:
        settings = get_settings()
        ensure_settings_files()
        state_manager.ensure_dirs()
        issue_number = state_manager.get_next_issue_number()
        theme = state_manager.get_runtime_theme(settings)
        digest_settings = settings.get("digest", {})
        min_count = validate_count(digest_settings.get("ideas_count_min", 5))
        max_count = validate_count(digest_settings.get("ideas_count_max", MAX_IDEAS))
        if max_count < min_count:
            raise ValueError("Maximum idea count must not be below the minimum")
        count = count_override or random.randint(min_count, max_count)
        sent_ideas = state_manager.get_sent_idea_names()
        topic_memory_settings = settings.get("topic_memory", {})
        issue_window = topic_memory_settings.get("recent_issue_window", 5) if topic_memory_settings.get("enabled", True) else None
        sent_topics = state_manager.get_sent_topic_signatures(issue_window=issue_window) if issue_window else []
        ideas = generic_searcher.search_ideas(
            settings,
            sent_ideas=sent_ideas,
            sent_topics=sent_topics,
            count=count,
        )

    ideas = validate_ideas(ideas, limit=count)
    if not demo:
        editorial = editorial_ai.build_editorial_package(ideas, issue_number, theme, settings)

    prefix = "demo" if demo else "preview" if preview else "digest"
    output_path = config.REPORTS_DIR / f"{prefix}_{issue_number:03d}_{datetime.now():%Y%m%d_%H%M%S}.pdf"
    pdf_path = pdf_generator.generate_pdf(
        ideas=ideas,
        issue_number=issue_number,
        theme=theme,
        output_path=str(output_path),
        settings=settings,
        editorial=editorial,
    )

    telegram_sent = False
    if not demo and not preview and not pdf_only:
        telegram_sent = telegram_sender.send_pdf_to_telegram(
            pdf_path=pdf_path,
            ideas=ideas,
            issue_number=issue_number,
            settings=settings,
        )
        if not telegram_sent:
            raise RuntimeError("PDF собран, но отправка в Telegram не удалась")

    if not preview and not demo and not pdf_only and telegram_sent:
        state_manager.add_ideas_to_log(ideas, issue_number)
        state_manager.add_issue_topics_to_memory(ideas, issue_number)
        state_manager.save_current_theme(theme["id"])

    return {
        "success": True,
        "synthetic": demo,
        "preview": preview,
        "pdf_path": pdf_path,
        "issue_number": issue_number,
        "theme_name": theme.get("name", ""),
        "theme_id": theme.get("id", ""),
        "ideas_count": len(ideas),
        "telegram_sent": telegram_sent,
        "editorial_used": bool(editorial),
    }


def _demo_settings() -> dict:
    """Fixed, nonsecret inputs for a synthetic local PDF, independent of .env/state."""
    return {
        "digest": {
            "demo": True,
            "cover_title": "DEMO · INVESTMENT DIGEST",
            "cover_subtitle": "Синтетические примеры для проверки оформления и пайплайна.",
            "focus_line": "DEMO: не актуальное исследование рынка",
            "disclaimer": (
                "ДЕМОНСТРАЦИОННЫЕ ДАННЫЕ. Примеры и оценки синтетические, "
                "не проверены по актуальным источникам и не являются инвестиционной рекомендацией."
            ),
            "brand_name": "Investment Digest · DEMO",
            "footer_brand": "SYNTHETIC DEMO · Investment Digest Bot",
        },
        "models": {"writer": {"enabled": False}},
    }


def load_dashboard_context() -> dict:
    settings = get_settings()
    baseline = get_baseline_settings()
    return {
        "settings": settings,
        "baseline": baseline,
        "secret_statuses": secrets_manager.secret_statuses(),
        "scheduler": scheduler_runtime.get_scheduler_snapshot(),
        "recent_topics": state_manager.get_recent_topics(
            issue_window=settings.get("topic_memory", {}).get("recent_issue_window", 5),
            limit=16,
        ),
        "themes": config.VISUAL_THEMES,
        "recent_reports": state_manager.list_recent_reports(limit=8),
        "recent_issues": state_manager.get_recent_issues(limit=8),
        "logs_tail": tail_log(),
    }


def tail_log(lines: int = 30) -> str:
    candidates = sorted(config.LOGS_DIR.glob("digest_*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        cron_log = config.LOGS_DIR / "cron_runs.log"
        candidates = [cron_log] if cron_log.exists() else []
    if not candidates:
        return "Логов пока нет."
    path = candidates[0]
    try:
        content = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        return "\n".join(content[-lines:])
    except Exception:
        return "Не удалось прочитать лог."


def update_digest_settings(form_data: dict) -> dict:
    current = get_settings()
    digest = current["digest"]
    themes = current["themes"]
    topic_memory = current.get("topic_memory", {})

    enabled_theme_ids = form_data.get("enabled_theme_ids", [])
    if isinstance(enabled_theme_ids, str):
        enabled_theme_ids = [enabled_theme_ids]

    digest.update(
        {
            "ideas_count_min": int(form_data.get("ideas_count_min", digest["ideas_count_min"])),
            "ideas_count_max": int(form_data.get("ideas_count_max", digest["ideas_count_max"])),
            "cover_title": form_data.get("cover_title", digest["cover_title"]).strip(),
            "cover_subtitle": form_data.get("cover_subtitle", digest["cover_subtitle"]).strip(),
            "focus_line": form_data.get("focus_line", digest["focus_line"]).strip(),
            "disclaimer": form_data.get("disclaimer", digest["disclaimer"]).strip(),
            "footer_brand": form_data.get("footer_brand", digest["footer_brand"]).strip(),
            "brand_name": form_data.get("brand_name", digest["brand_name"]).strip(),
        }
    )
    themes.update(
        {
            "mode": form_data.get("theme_mode", themes["mode"]),
            "fixed_theme_id": form_data.get("fixed_theme_id", themes["fixed_theme_id"]),
            "enabled_theme_ids": enabled_theme_ids,
        }
    )
    current["digest"] = digest
    current["themes"] = themes
    topic_memory.update(
        {
            "enabled": form_data.get("topic_memory_enabled") == "on",
            "recent_issue_window": int(form_data.get("topic_memory_recent_issue_window", topic_memory.get("recent_issue_window", 5))),
        }
    )
    current["topic_memory"] = topic_memory
    return save_settings(current)


def update_telegram_settings(form_data: dict) -> dict:
    current = get_settings()
    telegram = current["telegram"]
    telegram.update(
        {
            "chat_id": form_data.get("telegram_chat_id", telegram.get("chat_id", "")).strip(),
            "test_chat_id": form_data.get("telegram_test_chat_id", telegram.get("test_chat_id", "")).strip(),
        }
    )
    token_value = form_data.get("telegram_bot_token", "").strip()
    if token_value:
        secrets_manager.set_secret("TELEGRAM_BOT_TOKEN", token_value)
    if form_data.get("clear_telegram_bot_token") == "on":
        secrets_manager.clear_secret("TELEGRAM_BOT_TOKEN")
    current["telegram"] = telegram
    return save_settings(current)


def update_model_settings(form_data: dict) -> dict:
    current = get_settings()
    models = current["models"]

    writer_enabled = form_data.get("writer_enabled") == "on"

    models["search"].update(
        {
            "source_provider": form_data.get("search_source_provider", models["search"].get("source_provider", "duckduckgo")),
            "provider": form_data.get("search_provider", models["search"]["provider"]),
            "model": form_data.get("search_model", models["search"]["model"]).strip(),
            "base_url": form_data.get("search_base_url", models["search"]["base_url"]).strip(),
            "timeout_sec": int(form_data.get("search_timeout_sec", models["search"]["timeout_sec"])),
        }
    )
    models["writer"].update(
        {
            "enabled": writer_enabled,
            "provider": form_data.get("writer_provider", models["writer"]["provider"]),
            "model": form_data.get("writer_model", models["writer"]["model"]).strip(),
            "base_url": form_data.get("writer_base_url", models["writer"]["base_url"]).strip(),
            "timeout_sec": int(form_data.get("writer_timeout_sec", models["writer"]["timeout_sec"])),
            "style_prompt": form_data.get("writer_style_prompt", models["writer"]["style_prompt"]).strip(),
        }
    )

    search_api_key = form_data.get("search_api_key", "").strip()
    writer_api_key = form_data.get("writer_api_key", "").strip()
    perplexity_api_key = form_data.get("fallback_perplexity_api_key", "").strip()
    openai_api_key = form_data.get("fallback_openai_api_key", "").strip()

    if search_api_key:
        secrets_manager.set_secret(models["search"]["api_key_env_var"], search_api_key)
    if writer_api_key:
        secrets_manager.set_secret(models["writer"]["api_key_env_var"], writer_api_key)
    if perplexity_api_key:
        secrets_manager.set_secret(models["fallbacks"]["perplexity_api_key_env_var"], perplexity_api_key)
    if openai_api_key:
        secrets_manager.set_secret(models["fallbacks"]["openai_api_key_env_var"], openai_api_key)

    if form_data.get("clear_search_api_key") == "on":
        secrets_manager.clear_secret(models["search"]["api_key_env_var"])
    if form_data.get("clear_writer_api_key") == "on":
        secrets_manager.clear_secret(models["writer"]["api_key_env_var"])
    if form_data.get("clear_fallback_perplexity_api_key") == "on":
        secrets_manager.clear_secret(models["fallbacks"]["perplexity_api_key_env_var"])
    if form_data.get("clear_fallback_openai_api_key") == "on":
        secrets_manager.clear_secret(models["fallbacks"]["openai_api_key_env_var"])

    current["models"] = models
    return save_settings(current)


def update_schedule_settings(form_data: dict) -> dict:
    current = get_settings()
    schedule = current.get("schedule", {})
    schedule.update(
        {
            "enabled": form_data.get("schedule_enabled") == "on",
            "frequency": form_data.get("schedule_frequency", schedule.get("frequency", "daily")),
            "hour": int(form_data.get("schedule_hour", schedule.get("hour", 10))),
            "minute": int(form_data.get("schedule_minute", schedule.get("minute", 45))),
            "interval_hours": int(form_data.get("schedule_interval_hours", schedule.get("interval_hours", 24))),
        }
    )
    current["schedule"] = schedule
    return save_settings(current)


def reset_settings_to_baseline() -> dict:
    return reset_to_baseline()


def run_scheduled_digest() -> dict:
    return run_digest(demo=False, pdf_only=False, count_override=0, preview=False)


def clear_topic_memory() -> None:
    state_manager.clear_topic_memory()

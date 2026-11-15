"""
Отправка PDF в Telegram через Bot API.
"""
import logging
from html import escape
import requests
from pathlib import Path
from secrets_manager import get_secret
from runtime_settings import get_settings
from safe_errors import public_error

logger = logging.getLogger(__name__)


def _get_telegram_credentials(settings: dict | None = None) -> tuple[str, str]:
    active_settings = settings or get_settings()
    telegram = active_settings.get("telegram", {})
    return get_secret("TELEGRAM_BOT_TOKEN"), telegram.get("chat_id", "")


def send_pdf_to_telegram(pdf_path: str, ideas: list, issue_number: int, settings: dict | None = None) -> bool:
    """
    Отправляет PDF-файл в Telegram-группу.

    Args:
        pdf_path: путь к PDF файлу
        ideas: список идей (для формирования подписи)
        issue_number: номер выпуска

    Returns:
        True если отправка прошла успешно
    """
    bot_token, chat_id = _get_telegram_credentials(settings)

    if not bot_token:
        logger.error("TELEGRAM_BOT_TOKEN не задан в .env")
        return False
    if not chat_id:
        logger.error("TELEGRAM_CHAT_ID не задан в .env")
        return False

    pdf_file = Path(pdf_path)
    if not pdf_file.exists():
        logger.error(f"PDF файл не найден: {pdf_path}")
        return False

    # Формируем подпись
    caption = _build_caption(ideas, issue_number)

    url = f"https://api.telegram.org/bot{bot_token}/sendDocument"

    try:
        with open(pdf_path, "rb") as f:
            response = requests.post(
                url,
                data={
                    "chat_id": chat_id,
                    "caption": caption,
                    "parse_mode": "HTML",
                },
                files={"document": (pdf_file.name, f, "application/pdf")},
                timeout=60
            )

        if response.status_code == 200:
            data = response.json()
            if data.get("ok") is not True:
                logger.error("Telegram returned an unsuccessful result")
                return False
            msg_id = data.get("result", {}).get("message_id")
            logger.info("PDF отправлен в Telegram (message_id=%s)", msg_id if type(msg_id) is int else "unknown")
            return True
        else:
            logger.error("Ошибка Telegram API (HTTP %s)", _status_code(response.status_code))
            return False

    except Exception as e:
        logger.error("Исключение при отправке в Telegram (%s)", public_error(e))
        return False


def send_text_message(text: str, settings: dict | None = None, chat_id_override: str | None = None) -> bool:
    """Отправляет текстовое сообщение в группу."""
    bot_token, chat_id = _get_telegram_credentials(settings)
    target_chat_id = chat_id_override or chat_id
    if not bot_token or not target_chat_id:
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        response = requests.post(
            url,
            data={"chat_id": target_chat_id, "text": escape(str(text), quote=False), "parse_mode": "HTML"},
            timeout=30
        )
        return response.status_code == 200 and response.json().get("ok") is True
    except Exception as e:
        logger.error("Ошибка отправки сообщения (%s)", public_error(e))
        return False


def _status_code(value) -> str:
    return str(value) if type(value) is int and 100 <= value <= 599 else "unknown"


def _caption_text(value, limit: int) -> str:
    """Escape bounded text without splitting an HTML entity during truncation."""
    result = []
    used = 0
    text = str(value)
    for char in text:
        encoded = escape(char, quote=False)
        units = len(encoded.encode("utf-16-le")) // 2
        if used + units > limit - 3:
            return "".join(result) + "..."
        result.append(encoded)
        used += units
    return "".join(result)


def _score_total(idea: dict) -> int:
    """Суммарный балл идеи. Работает и с scores, и с localization."""
    scores = idea.get("scores", {})
    if scores and isinstance(scores, dict):
        return sum(v for v in scores.values() if isinstance(v, (int, float)))
    loc = idea.get("localization", {})
    if loc and isinstance(loc, dict):
        return sum(v for v in loc.values() if isinstance(v, (int, float)))
    return 0


def _build_caption(ideas: list, issue_number: int) -> str:
    """Формирует подпись к PDF."""
    from datetime import datetime
    # Русские названия месяцев для корректного отображения
    months = ["января","февраля","марта","апреля","мая","июня",
              "июля","августа","сентября","октября","ноября","декабря"]
    now = datetime.now()
    date_str = f"{now.day} {months[now.month-1]} {now.year}"

    # Топ-3 — используем безопасную функцию подсчёта
    sorted_ideas = sorted(ideas, key=_score_total, reverse=True)
    top3 = sorted_ideas[:3]

    # Категории (без пустых)
    cats = set()
    for idea in ideas:
        cat = str(idea.get("category", "")).split("/")[0].strip()[:70]
        if cat:
            cats.add(cat)

    top3_text = "\n".join(
        f"  {i+1}. {_caption_text(idea.get('name', '—'), 150)}"
        for i, idea in enumerate(top3)
    )

    cats_text = _caption_text(", ".join(sorted(cats)[:4]), 120) if cats else "Разные"

    caption = (
        f"📊 <b>Ежедневный обзор инвестиционных идей</b>\n"
        f"Выпуск #{issue_number:03d} | {date_str}\n\n"
        f"Внутри: {len(ideas)} свежих идей, аналитика, сравнительная оценка и источники.\n\n"
        f"<b>🏆 Топ-3 идеи:</b>\n{top3_text}\n\n"
        f"<b>📁 Категории:</b> {cats_text}\n\n"
        f"#инвестиции #бизнес #дайджест"
    )

    # Telegram caption ограничение — 1024 символа
    if len(caption.encode("utf-16-le")) // 2 > 1024:
        caption = f"Инвестиционный дайджест: {len(ideas)} идей."

    return caption

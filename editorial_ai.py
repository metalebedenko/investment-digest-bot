"""
AI-редактор дайджеста.

Не меняет фактуру идей, а добавляет более живую инвесторскую подачу:
- общий тон выпуска
- executive summary
- комментарии к топ-идеям
- investor take для каждой карточки
"""

from __future__ import annotations

import json
import logging
from safe_errors import public_error
import re

from llm_client import chat_completion
from secrets_manager import get_secret


logger = logging.getLogger(__name__)


WRITER_SYSTEM_PROMPT = """\
Ты — сильный редактор инвестиционного дайджеста для группы частных инвесторов.
Переписывай сухой аналитический материал в живой, практичный и полезный для решения формат.

ПРИНЦИПЫ СТИЛЯ:
- без бюрократического канцелярита
- без пустых общих слов
- коротко, энергично, по делу
- фокус на том, почему идея важна сейчас, где деньги, где риск, какой следующий шаг
- не выдумывай факты, не меняй цифры и не добавляй компании, которых нет в исходных данных

Верни ТОЛЬКО валидный JSON.
"""


def build_editorial_package(ideas: list[dict], issue_number: int, theme: dict, settings: dict) -> dict | None:
    writer_settings = settings.get("models", {}).get("writer", {})
    if not writer_settings.get("enabled"):
        return None

    prompt = _build_prompt(ideas, issue_number, theme, settings)

    try:
        raw = chat_completion(
            provider=writer_settings.get("provider", "ollama"),
            model=writer_settings.get("model", ""),
            base_url=writer_settings.get("base_url", ""),
            api_key=get_secret(writer_settings.get("api_key_env_var", "WRITER_MODEL_API_KEY")),
            system_prompt=_build_system_prompt(writer_settings),
            user_prompt=prompt,
            temperature=float(writer_settings.get("temperature", 0.7)),
            timeout_sec=int(writer_settings.get("timeout_sec", 180)),
        )
        package = _parse_editorial_json(raw)
        if package:
            return package
    except Exception as exc:
        logger.error("Editorial writer failed: %s", public_error(exc))

    return None


def _build_system_prompt(writer_settings: dict) -> str:
    extra = writer_settings.get("style_prompt", "").strip()
    if not extra:
        return WRITER_SYSTEM_PROMPT
    return f"{WRITER_SYSTEM_PROMPT}\n\nДОПОЛНИТЕЛЬНЫЙ СТИЛЬ:\n{extra}"


def _build_prompt(ideas: list[dict], issue_number: int, theme: dict, settings: dict) -> str:
    digest = settings.get("digest", {})
    minimal_ideas = []
    for idea in ideas:
        minimal_ideas.append({
            "name": idea.get("name", ""),
            "category": idea.get("category", ""),
            "summary": idea.get("summary", ""),
            "why_interesting": idea.get("why_interesting", ""),
            "investment_range": idea.get("investment_range", ""),
            "target_client": idea.get("target_client", ""),
            "revenue_model": idea.get("revenue_model", ""),
            "risks": idea.get("risks", ""),
            "scores": idea.get("scores", {}),
            "localization": idea.get("localization", {}),
        })

    return f"""
Подготовь редакторский слой для инвестиционного PDF-дайджеста.

Контекст выпуска:
- Выпуск: #{issue_number:03d}
- Тема оформления: {theme.get("name", "—")}
- Базовый заголовок: {digest.get("cover_title", "")}
- Базовый фокус: {digest.get("focus_line", "")}

Исходные идеи:
{json.dumps(minimal_ideas, ensure_ascii=False, indent=2)}

Верни JSON строго в таком формате:
{{
  "cover": {{
    "subtitle": "1-2 предложения: о чём этот выпуск и почему он полезен инвестору",
    "focus_line": "Короткая живая строка вместо формальной шапки"
  }},
  "executive_summary": "1 абзац на 3-5 предложений без канцелярита",
  "top_picks": [
    {{
      "name": "Название идеи",
      "comment": "Почему именно эта идея попала в топ"
    }}
  ],
  "ideas": [
    {{
      "name": "Название идеи",
      "investor_take": "2-3 предложения: в чём практический смысл идеи для инвестора",
      "why_now": "1 предложение: почему смотреть на это нужно сейчас",
      "verdict_label": "Короткий ярлык вроде: Стоит смотреть / Быстрый тест / Осторожно, но интересно"
    }}
  ]
}}

Сохраняй оригинальные названия идей без изменений.
"""


def _parse_editorial_json(raw: str) -> dict | None:
    if not isinstance(raw, str) or not raw or len(raw) > 200_000:
        return None

    cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    cleaned = re.sub(r"```(?:json)?\s*", "", cleaned)
    cleaned = cleaned.replace("```", "").strip()

    start = cleaned.find("{")
    end = cleaned.rfind("}") + 1
    if start == -1 or end <= start:
        return None

    try:
        data = json.loads(cleaned[start:end])
        if _valid_editorial_package(data):
            return data
    except Exception:
        logger.warning("Не удалось распарсить editorial JSON")

    return None


def _valid_editorial_package(data) -> bool:
    """Validate optional display fields without accepting arbitrary model shapes."""
    if not isinstance(data, dict):
        return False
    text = lambda value: isinstance(value, str) and len(value) <= 6000
    if "executive_summary" in data and not text(data["executive_summary"]):
        return False
    cover = data.get("cover", {})
    if not isinstance(cover, dict):
        return False
    if any(key in cover and not text(cover[key]) for key in ("subtitle", "focus_line")):
        return False
    for key, fields in (("top_picks", ("comment",)),
                        ("ideas", ("investor_take", "why_now", "verdict_label"))):
        entries = data.get(key, [])
        if not isinstance(entries, list) or len(entries) > 20:
            return False
        for entry in entries:
            if (not isinstance(entry, dict) or not text(entry.get("name"))
                    or not entry["name"].strip()
                    or any(field in entry and not text(entry[field]) for field in fields)):
                return False
    return True

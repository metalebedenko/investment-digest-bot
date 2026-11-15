"""
Генерация списка идей через:
- DuckDuckGo + настраиваемую LLM-модель анализа
- Perplexity как поисковый API
- OpenAI Search как поисковый API
"""

from __future__ import annotations

import logging
from safe_errors import public_error

import searcher
import searcher_ollama
from llm_client import chat_completion
from secrets_manager import get_secret
import state_manager
from idea_validation import validate_count, validate_ideas


logger = logging.getLogger(__name__)


def search_ideas(
    settings: dict,
    sent_ideas: list[str] | None = None,
    sent_topics: list[str] | None = None,
    count: int = 7,
) -> list[dict]:
    """
    Ищет идеи через primary search model из runtime settings.
    При неудаче откатывается на старый fallback pipeline.
    """
    validate_count(count)
    sent_names = sent_ideas or []
    topic_signatures = set(sent_topics or [])
    model_settings = settings.get("models", {}).get("search", {})
    source_provider = model_settings.get("source_provider", "duckduckgo")

    if source_provider == "perplexity":
        logger.info("Search source provider: Perplexity")
        try:
            ideas = searcher.search_with_perplexity(sent_names, count=count, settings=settings, sent_topics=sent_topics)
            return _filter_by_topics(ideas, topic_signatures, count)
        except Exception as exc:
            logger.error("Perplexity search source failed: %s", public_error(exc))

    if source_provider == "openai_search":
        logger.info("Search source provider: OpenAI Search")
        try:
            ideas = searcher.search_with_openai(sent_names, count=count, settings=settings, sent_topics=sent_topics)
            return _filter_by_topics(ideas, topic_signatures, count)
        except Exception as exc:
            logger.error("OpenAI Search source failed: %s", public_error(exc))

    if model_settings.get("enabled", True):
        try:
            ideas = _search_with_configured_model(model_settings, sent_names, topic_signatures, count)
            if ideas:
                return ideas
        except Exception as exc:
            logger.error("Primary search model failed: %s", public_error(exc))

    logger.info("Переходим на fallback search pipeline")
    ideas = searcher.search_ideas(sent_names, count=count, settings=settings, sent_topics=sent_topics)
    return _filter_by_topics(ideas, topic_signatures, count)


def _search_with_configured_model(
    model_settings: dict,
    sent_names: list[str],
    topic_signatures: set[str],
    count: int,
) -> list[dict]:
    request_count = count + 2
    logger.info(
        "Search source: DuckDuckGo | analysis model: provider=%s model=%s",
        model_settings.get("provider"),
        model_settings.get("model"),
    )

    ddg_context = searcher_ollama._gather_ddg_context(count)
    if not ddg_context.strip():
        raise RuntimeError("Live acquisition returned no source context")
    prompt = searcher_ollama._search_prompt(sent_names, request_count, ddg_context, sent_topics=list(topic_signatures))

    raw = chat_completion(
        provider=model_settings.get("provider", "ollama"),
        model=model_settings.get("model", ""),
        base_url=model_settings.get("base_url", ""),
        api_key=get_secret(model_settings.get("api_key_env_var", "SEARCH_MODEL_API_KEY")),
        system_prompt=searcher_ollama.SYSTEM_PROMPT,
        user_prompt=prompt,
        temperature=float(model_settings.get("temperature", 0.7)),
        timeout_sec=int(model_settings.get("timeout_sec", 240)),
    )

    ideas = searcher_ollama._parse_ideas(raw)
    if not ideas:
        return []

    sent_normalized = {searcher_ollama._normalize_name(name) for name in sent_names}
    unique_ideas = []
    seen_names = set()

    for idea in ideas:
        checked = validate_ideas([idea], limit=1)[0]
        normalized = searcher_ollama._normalize_idea(checked)
        norm_name = searcher_ollama._normalize_name(normalized.get("name", ""))
        if norm_name in seen_names or norm_name in sent_normalized:
            continue
        if state_manager.idea_conflicts_with_topics(normalized, topic_signatures):
            logger.info("Пропуск по памяти тем: %s", normalized.get("name", ""))
            continue
        seen_names.add(norm_name)
        unique_ideas.append(normalized)

    return unique_ideas[:count]


def _filter_by_topics(ideas: list[dict], topic_signatures: set[str], count: int) -> list[dict]:
    ideas = validate_ideas(ideas, limit=count)
    if not topic_signatures:
        return ideas[:count]

    filtered = []
    for idea in ideas:
        if state_manager.idea_conflicts_with_topics(idea, topic_signatures):
            logger.info("Пропуск по памяти тем: %s", idea.get("name", ""))
            continue
        filtered.append(idea)
    return filtered[:count]

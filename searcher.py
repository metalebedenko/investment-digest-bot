"""
Модуль поиска бизнес-идей.

Приоритеты поиска:
  1. Производство, торговля, дистрибуция, физические товары, франшизы
  2. AI/SaaS/IT — только сильные идеи с чёткой локализацией

Поддерживает:
  - Perplexity API (рекомендуется)
  - DuckDuckGo (pip install duckduckgo-search)
  - Fallback: демо-идеи для теста
"""
import json
import logging
import requests
from datetime import datetime
from secrets_manager import get_secret
from safe_errors import public_error
from idea_validation import validate_count, validate_ideas

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Ты — ежедневный AI-аналитик и инвестиционный ресерч-агент для закрытой группы инвесторов.

Твоя задача: найти по всему миру самые свежие и интересные бизнес-идеи, отобрать 5-10 лучших,
подготовить краткие инвестиционные паспорта на русском языке.

ПРИОРИТЕТЫ ТЕМАТИК:
ПЕРВЫЙ ПРИОРИТЕТ (основа отчёта):
- Производство (малое, среднее, контрактное)
- Локальные заводы, цеха, сборочные линии
- Упаковочные и сборочные модели
- Товары, которые можно производить руками или с умеренной механизацией
- Оптовая торговля, розница, дистрибуция
- Франшизы в торговле, private label, СТМ
- Физические товары, B2B-поставки, логистика

ВТОРОЙ ПРИОРИТЕТ (только очень сильные идеи):
- AI, IT, SaaS, цифровые сервисы
- Только при чёткой локализации и монетизации

ГЛАВНЫЙ ВОПРОС при отборе каждой идеи:
"Можно ли это локализовать, повторить или адаптировать силами российской инвестиционной группы?"

ДЛЯ КАЖДОЙ ИДЕИ верни JSON-объект со следующими полями:
{
  "name": "Название идеи",
  "category": "Категория (производство/торговля/франшиза/IT/etc)",
  "summary": "Краткая суть в 1-2 предложениях",
  "revenue_model": "Как зарабатывает проект",
  "target_client": "Для кого / кто клиент",
  "innovation": "В чём новизна или сильный угол",
  "investment_format": "тест гипотезы|MVP|масштабирование|франшиза|локализация|покупка доли|партнёрство|лицензирование|запуск аналога",
  "investment_range": "500к-3млн|3-15млн|15-50млн|50-200млн RUB",
  "why_interesting": "Почему это интересно инвестору",
  "risks": "Основные риски",
  "verdict": "интересно|спорно|требует проверки|не рекомендовано",
  "sources": ["URL1", "URL2"],
  "scores": {
    "novelty": 8,
    "market_potential": 7,
    "ease_of_launch": 6,
    "scalability": 7,
    "hypothesis_speed": 8,
    "investment_appeal": 7,
    "risk": 4
  },
  "localization": {
    "russia_potential": 8,
    "replication_ease": 7,
    "operational_feasibility": 8,
    "complexity_threshold": 7
  },
  "localization_label": "Высокий потенциал локализации в России|Хороший кейс для наблюдения, но сложен для прямого воспроизведения|Средний потенциал локализации"
}

Верни ТОЛЬКО валидный JSON массив идей. Без markdown, без объяснений. Только JSON."""

SEARCH_PROMPT_TEMPLATE = """Дата сегодня: {date}

Найди {count} свежих бизнес-идей со всего мира (последние 24-72 часа, максимум 7 дней).

Ищи в:
- Product Hunt (новые продукты недели)
- TechCrunch, YC Combinator (новые стартапы)
- Hacker News (стартапы, новые продукты)
- Franchise directories (новые франшизы)
- Manufacturing/trade media
- Reddit: r/entrepreneur, r/smallbusiness, r/manufacturing
- Краудфандинг: Kickstarter, Indiegogo

Уже отправленные идеи (НЕ повторять):
{sent_ideas}

Темы прошлых боевых выпусков (НЕ повторять категории и подкатегории):
{sent_topics}

Приоритет: производство, торговля, физические товары, франшизы.
Верни {count} идей в формате JSON массива."""


def _extract_chat_content(data: dict) -> str:
    choices = data.get("choices", [])
    if not choices:
        raise ValueError("LLM API вернул ответ без choices")

    message = choices[0].get("message", {})
    content = message.get("content", "")

    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
        content = "".join(parts)

    content = str(content or "").strip()
    if not content:
        raise ValueError("LLM API вернул пустой content")
    return content


def _get_fallback_keys(settings: dict | None = None) -> tuple[str, str]:
    fallbacks = (settings or {}).get("models", {}).get("fallbacks", {})
    return (
        get_secret(fallbacks.get("perplexity_api_key_env_var", "PERPLEXITY_API_KEY")),
        get_secret(fallbacks.get("openai_api_key_env_var", "OPENAI_API_KEY")),
    )


def search_with_perplexity(
    sent_ideas: list,
    count: int = 7,
    settings: dict | None = None,
    sent_topics: list | None = None,
) -> list:
    """Поиск через Perplexity API (sonar-pro модель)."""
    perplexity_api_key, _ = _get_fallback_keys(settings)
    if not perplexity_api_key:
        raise ValueError("PERPLEXITY_API_KEY не задан в .env")

    sent_str = "\n".join(f"- {name}" for name in sent_ideas[:30]) or "Нет (первый запуск)"
    sent_topics_str = "\n".join(f"- {topic}" for topic in (sent_topics or [])[:40]) or "Нет"
    user_prompt = SEARCH_PROMPT_TEMPLATE.format(
        date=datetime.now().strftime("%d %B %Y"),
        count=count,
        sent_ideas=sent_str,
        sent_topics=sent_topics_str,
    )

    headers = {
        "Authorization": f"Bearer {perplexity_api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "sonar-pro",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.3,
        "max_tokens": 8000,
        "search_recency_filter": "week",
        "return_citations": True
    }

    logger.info("Запрос к Perplexity API...")
    response = requests.post(
        "https://api.perplexity.ai/chat/completions",
        headers=headers,
        json=payload,
        timeout=120
    )
    response.raise_for_status()

    data = response.json()
    content = _extract_chat_content(data)
    ideas = _parse_ideas_json(content)
    if not ideas:
        raise ValueError("Perplexity вернул ответ без валидного JSON массива идей")
    return ideas


def search_with_openai(
    sent_ideas: list,
    count: int = 7,
    settings: dict | None = None,
    sent_topics: list | None = None,
) -> list:
    """Поиск через OpenAI API (GPT-4 с веб-поиском через browsing)."""
    _, openai_api_key = _get_fallback_keys(settings)
    if not openai_api_key:
        raise ValueError("OPENAI_API_KEY не задан в .env")

    sent_str = "\n".join(f"- {name}" for name in sent_ideas[:30]) or "Нет (первый запуск)"
    sent_topics_str = "\n".join(f"- {topic}" for topic in (sent_topics or [])[:40]) or "Нет"
    user_prompt = SEARCH_PROMPT_TEMPLATE.format(
        date=datetime.now().strftime("%d %B %Y"),
        count=count,
        sent_ideas=sent_str,
        sent_topics=sent_topics_str,
    )

    headers = {
        "Authorization": f"Bearer {openai_api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "gpt-4o-search-preview",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.3,
    }

    logger.info("Запрос к OpenAI API...")
    response = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers=headers,
        json=payload,
        timeout=120
    )
    response.raise_for_status()

    content = _extract_chat_content(response.json())
    ideas = _parse_ideas_json(content)
    if not ideas:
        raise ValueError("OpenAI вернул ответ без валидного JSON массива идей")
    return ideas


def search_with_duckduckgo(sent_ideas: list, count: int = 7) -> list:
    """Поиск через DuckDuckGo (требует: pip install duckduckgo-search)."""
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        raise ImportError("Установи: pip install duckduckgo-search")

    from datetime import datetime
    year = datetime.now().year
    queries = [
        f"new business startup franchise {year} manufacturing",
        f"new franchise business opportunity {year}",
        f"new physical product startup site:producthunt.com {year}",
        f"small business manufacturing idea {year}",
        f"new wholesale distribution business {year}",
    ]

    raw_results = []
    with DDGS() as ddgs:
        for query in queries:
            results = list(ddgs.text(query, max_results=5, timelimit="w"))
            raw_results.extend(results)
            logger.info(f"DuckDuckGo '{query}': {len(results)} результатов")

    # Формируем простые идеи из результатов (базовый вариант)
    ideas = []
    seen = set(sent_ideas)
    for r in raw_results:
        name = r.get("title", "Без названия")[:80]
        if name.lower() in seen:
            continue
        seen.add(name.lower())
        ideas.append({
            "name": name,
            "category": "Стартап",
            "summary": r.get("body", "")[:200],
            "revenue_model": "Требует уточнения",
            "target_client": "B2B/B2C",
            "innovation": "Требует анализа",
            "investment_format": "тест гипотезы",
            "investment_range": "3-15млн RUB",
            "why_interesting": "Свежий сигнал",
            "risks": "Требует анализа",
            "verdict": "требует проверки",
            "sources": [r.get("href", "")],
            "scores": {
                "novelty": 6, "market_potential": 5, "ease_of_launch": 5,
                "scalability": 5, "hypothesis_speed": 5, "investment_appeal": 5, "risk": 5
            },
            "localization": {
                "russia_potential": 5, "replication_ease": 5,
                "operational_feasibility": 5, "complexity_threshold": 5
            },
            "localization_label": "Средний потенциал локализации"
        })
        if len(ideas) >= count:
            break

    return ideas


def get_demo_ideas() -> list:
    """Демо-идеи для тестирования без API ключей."""
    return [
        {
            "name": "КонтрактПак — контрактная упаковка для малого бизнеса",
            "category": "Производство / Упаковка",
            "summary": "Сервис контрактной упаковки товаров для малого бизнеса. Принимаешь продукт клиента, упаковываешь под его брендом, отправляешь на маркетплейсы.",
            "revenue_model": "Оплата за единицу упакованного товара + хранение. Средний чек 80-150 руб/ед.",
            "target_client": "Малый бизнес на Wildberries/Ozon, DTC-бренды, производители без своей упаковки",
            "innovation": "Готовая инфраструктура упаковки как сервис — не нужно строить свой цех",
            "investment_format": "запуск аналога на локальном рынке",
            "investment_range": "3-15млн RUB",
            "why_interesting": "Рынок e-commerce растёт, малый бизнес ищет аутсорс упаковки. Модель FOCO работает в США и Индии.",
            "risks": "Низкая маржа на малых объёмах, конкуренция с фулфилментами",
            "verdict": "интересно",
            "sources": ["Синтетический пример; актуальные источники не запрашивались"],
            "scores": {
                "novelty": 6, "market_potential": 8, "ease_of_launch": 7,
                "scalability": 7, "hypothesis_speed": 8, "investment_appeal": 7, "risk": 4
            },
            "localization": {
                "russia_potential": 9, "replication_ease": 8,
                "operational_feasibility": 8, "complexity_threshold": 8
            },
            "localization_label": "Высокий потенциал локализации в России"
        },
        {
            "name": "ПрайватЛейбл Косметика — белая этикетка для локальных брендов",
            "category": "Производство / Косметика",
            "summary": "Производство косметики под чужим брендом (private label). Малые партии от 100 ед., быстрый вывод бренда на рынок.",
            "revenue_model": "Производство + упаковка под ключ. Маржа 40-60% при объёме от 500 ед/месяц.",
            "target_client": "Блогеры, малый бизнес, салоны красоты, хотящие свой бренд косметики",
            "innovation": "Минимальный порог входа для создания собственного косметического бренда",
            "investment_format": "запуск аналога на локальном рынке",
            "investment_range": "3-15млн RUB",
            "why_interesting": "Рынок косметики растёт, тренд на локальные бренды, инфраструктура в РФ готова",
            "risks": "Сертификация, конкуренция с существующими заводами",
            "verdict": "интересно",
            "sources": ["Синтетический пример; актуальные источники не запрашивались"],
            "scores": {
                "novelty": 5, "market_potential": 8, "ease_of_launch": 6,
                "scalability": 8, "hypothesis_speed": 6, "investment_appeal": 8, "risk": 4
            },
            "localization": {
                "russia_potential": 9, "replication_ease": 7,
                "operational_feasibility": 8, "complexity_threshold": 7
            },
            "localization_label": "Высокий потенциал локализации в России"
        },
        {
            "name": "МикроПроизводство — модульные мини-заводы в контейнерах",
            "category": "Производство / Модульное",
            "summary": "Контейнерные мини-заводы для малосерийного производства: пищевое, текстиль, пластик. Быстрый запуск в любой точке.",
            "revenue_model": "Продажа/аренда модулей + сервисное обслуживание + консалтинг по запуску",
            "target_client": "Малый бизнес, фермеры, муниципалитеты, регионы без инфраструктуры",
            "innovation": "Производство «в коробке» — без строительства цеха",
            "investment_format": "локализация",
            "investment_range": "15-50млн RUB",
            "why_interesting": "Глобальный тренд на децентрализацию производства, ESG, локальные цепочки",
            "risks": "Сложная логистика, зависимость от поставщиков оборудования",
            "verdict": "интересно",
            "sources": ["Синтетический пример; актуальные источники не запрашивались"],
            "scores": {
                "novelty": 8, "market_potential": 7, "ease_of_launch": 4,
                "scalability": 8, "hypothesis_speed": 4, "investment_appeal": 7, "risk": 6
            },
            "localization": {
                "russia_potential": 7, "replication_ease": 5,
                "operational_feasibility": 6, "complexity_threshold": 5
            },
            "localization_label": "Средний потенциал локализации"
        },
        {
            "name": "АзиатскиеДесерты — франшиза bubble tea и моти",
            "category": "Торговля / Франшиза / HoReCa",
            "summary": "Франшиза точек продаж азиатских десертов: bubble tea, моти, тайское мороженое. Быстрый формат, ТЦ и стрит-ретейл.",
            "revenue_model": "Роялти 5-8% + продажа ингредиентов. Точка окупается за 8-14 мес.",
            "target_client": "Франчайзи-предприниматели, конечный потребитель 15-35 лет",
            "innovation": "Формат Mochinut показал 1044% рост за 4 года в США, в РФ категория не насыщена",
            "investment_format": "франшиза",
            "investment_range": "3-15млн RUB",
            "why_interesting": "Быстрая окупаемость, низкий порог, высокая маржа на продукте (70-80%)",
            "risks": "Зависимость от трафика ТЦ, сезонность, насыщение рынка",
            "verdict": "интересно",
            "sources": ["Синтетический пример; актуальные источники не запрашивались"],
            "scores": {
                "novelty": 6, "market_potential": 7, "ease_of_launch": 8,
                "scalability": 8, "hypothesis_speed": 9, "investment_appeal": 8, "risk": 4
            },
            "localization": {
                "russia_potential": 8, "replication_ease": 9,
                "operational_feasibility": 9, "complexity_threshold": 9
            },
            "localization_label": "Высокий потенциал локализации в России"
        },
        {
            "name": "SmartVend — умные вендинговые автоматы B2B",
            "category": "Торговля / Вендинг",
            "summary": "Вендинговые автоматы с IoT-управлением для B2B: офисы, заводы, больницы. Продажа снеков, канцелярии, СИЗ, расходников.",
            "revenue_model": "Выручка с продаж + SaaS подписка на управление ($200/мес). Средний автомат $22K/мес оборот.",
            "target_client": "Предприятия 200+ сотрудников, больницы, университеты, торговые центры",
            "innovation": "Полный IoT-контроль остатков и аналитика потребления — новая модель B2B снабжения",
            "investment_format": "масштабирование",
            "investment_range": "3-15млн RUB",
            "why_interesting": "Рынок вендинга в РФ недооценён, IoT снижает затраты на обслуживание на 40%",
            "risks": "Вандализм, сложность обслуживания, первоначальные инвестиции в оборудование",
            "verdict": "интересно",
            "sources": ["Синтетический пример; актуальные источники не запрашивались"],
            "scores": {
                "novelty": 6, "market_potential": 7, "ease_of_launch": 6,
                "scalability": 8, "hypothesis_speed": 7, "investment_appeal": 7, "risk": 4
            },
            "localization": {
                "russia_potential": 8, "replication_ease": 7,
                "operational_feasibility": 8, "complexity_threshold": 7
            },
            "localization_label": "Высокий потенциал локализации в России"
        },
    ]


def search_ideas(
    sent_ideas: list,
    count: int = 7,
    settings: dict | None = None,
    sent_topics: list | None = None,
) -> list:
    """
    Основная функция поиска. Автоматически выбирает источник.
    Приоритет: Perplexity API > OpenAI > DuckDuckGo; синтетического fallback нет.
    """
    validate_count(count)
    perplexity_api_key, openai_api_key = _get_fallback_keys(settings)

    if perplexity_api_key:
        logger.info("Используем Perplexity API для поиска")
        try:
            return search_with_perplexity(sent_ideas, count, settings=settings, sent_topics=sent_topics)
        except Exception as e:
            logger.error("Perplexity API ошибка: %s", public_error(e))

    if openai_api_key:
        logger.info("Используем OpenAI API для поиска")
        try:
            return search_with_openai(sent_ideas, count, settings=settings, sent_topics=sent_topics)
        except Exception as e:
            logger.error("OpenAI API ошибка: %s", public_error(e))

    try:
        logger.info("Используем DuckDuckGo для поиска")
        return search_with_duckduckgo(sent_ideas, count)
    except ImportError:
        logger.warning("duckduckgo-search не установлен")
    except Exception as e:
        logger.error("DuckDuckGo ошибка: %s", public_error(e))

    raise RuntimeError("Live search failed; no synthetic fallback is permitted")


def _parse_ideas_json(content: str) -> list:
    """Парсит JSON из ответа LLM."""
    import re
    if not isinstance(content, str) or not content or len(content) > 200_000:
        return []
    # Убираем markdown блоки
    content = re.sub(r"```json\s*", "", content)
    content = re.sub(r"```\s*", "", content)
    content = content.strip()

    # Ищем JSON массив
    start = content.find("[")
    end = content.rfind("]") + 1
    if start != -1 and end > start:
        json_str = content[start:end]
        try:
            ideas = validate_ideas(json.loads(json_str))
            logger.info("Найдено %s идей", len(ideas))
            return ideas
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            logger.error("Ошибка парсинга JSON: %s", public_error(e))

    logger.warning("Не удалось найти JSON массив идей в ответе LLM")
    return []

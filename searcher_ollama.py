"""
Поиск инвестиционных идей через DuckDuckGo + Ollama (gpt-oss:120b-cloud).

Схема работы:
  1. DuckDuckGo ищет свежие новости по бизнес-тематике
  2. gpt-oss:120b-cloud анализирует результаты и выдаёт структурированный JSON
  3. Если DuckDuckGo недоступен — live-поиск завершается без выдуманного выпуска
"""

import json
import logging
from safe_errors import public_error
from idea_validation import MAX_RESPONSE_IDEAS, validate_count, validate_ideas
import random
import re
import time
from datetime import datetime
from typing import Optional

import requests

logger = logging.getLogger(__name__)

OLLAMA_URL   = "http://localhost:11434"
OLLAMA_MODEL = "gpt-oss:120b-cloud"
MAX_RETRIES  = 2

# ── Промпты ────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
Ты — аналитик инвестиционных возможностей для российской группы частных инвесторов.
Твоя задача — находить реальные бизнес-идеи из мировой практики, которые можно
локализовать или воспроизвести в России.

ПРИОРИТЕТЫ:
1. Производство, торговля, дистрибуция, франшизы, физические товары
2. AI/SaaS — только сильные идеи с чёткой локализацией

ДИАПАЗОН ИНВЕСТИЦИЙ: 500 тыс — 200 млн RUB
ГЛАВНЫЙ ВОПРОС для каждой идеи: «Можно ли это повторить в России?»

ВАЖНО:
- Каждая идея должна быть КОНКРЕТНОЙ, с реальными примерами компаний или продуктов.
- НЕ генерируй абстрактные идеи вроде «экологичный бизнес» — нужны конкретные ниши.
- Опирайся на предоставленные данные из интернета. Если данных недостаточно, верни пустой массив.

Отвечай ТОЛЬКО валидным JSON — без markdown, без комментариев, без объяснений.
ВСЕ тексты в JSON (name, category, summary, why_interesting, target_client, revenue_model, innovation, investment_format, risks, localization_label) — ТОЛЬКО НА РУССКОМ ЯЗЫКЕ.
"""

def _search_prompt(sent_names: list, count: int, ddg_snippets: str = "", sent_topics: list | None = None) -> str:
    exclude = ""
    if sent_names:
        # Берём последние 30 идей для лучшей дедупликации
        recent = sent_names[-30:]
        exclude = f"\nИСКЛЮЧИ эти уже известные идеи (не повторяй ни одну):\n" + \
                  "\n".join(f"- {n}" for n in recent) + "\n"

    topic_block = ""
    if sent_topics:
        recent_topics = list(sent_topics)[-40:]
        topic_block = (
            "\nИЗБЕГАЙ тем из прошлых выпусков. Не предлагай идеи в этих нишах/подкатегориях:\n"
            + "\n".join(f"- {topic}" for topic in recent_topics)
            + "\n"
        )

    context = ""
    if ddg_snippets:
        context = f"""
Используй эти свежие данные из интернета как ОСНОВУ для идей.
Извлеки из них конкретные бизнес-модели, компании, продукты и тренды:
---
{ddg_snippets[:6000]}
---
"""

    return f"""
{context}
{exclude}
{topic_block}
Найди {count} НОВЫХ и РАЗНООБРАЗНЫХ инвестиционных идей для российских инвесторов.

ТРЕБОВАНИЯ К РАЗНООБРАЗИЮ:
- Минимум 3 разных категории (производство, торговля, франшиза, дистрибуция, услуги, AI/IT)
- Разные диапазоны инвестиций (от 500K до 200M RUB)
- Каждая идея — уникальная ниша, без повторов тематик

Верни JSON-массив из {count} объектов. Каждый объект СТРОГО в таком формате:

{{
  "name": "Короткое название идеи (3-6 слов)",
  "category": "Категория / Подкатегория",
  "summary": "2-3 предложения: что это, как работает, почему интересно",
  "why_interesting": "Конкретная причина: цифры, тренд, аналог за рубежом",
  "investment_range": "X-Y млн RUB",
  "target_client": "Кто платит деньги",
  "revenue_model": "Как зарабатывается выручка, средний чек/маржа",
  "innovation": "В чём отличие от обычного бизнеса",
  "investment_format": "франшиза / производство / запуск аналога / дистрибуция / ...",
  "risks": "Главные 1-2 риска",
  "verdict": "интересно",
  "sources": ["URL или название источника"],
  "scores": {{
    "novelty": 1-10,
    "market_potential": 1-10,
    "ease_of_launch": 1-10,
    "scalability": 1-10,
    "hypothesis_speed": 1-10,
    "investment_appeal": 1-10,
    "risk": 1-10
  }},
  "localization": {{
    "russia_potential": 1-10,
    "replication_ease": 1-10,
    "operational_feasibility": 1-10,
    "complexity_threshold": 1-10
  }},
  "localization_label": "Высокий/Средний/Низкий потенциал локализации в России"
}}

Верни ТОЛЬКО массив JSON, без любого другого текста.
"""


# ── DuckDuckGo поиск ───────────────────────────────────────────────────────

_YEAR = datetime.now().year

# Большой пул запросов — каждый запуск случайно выбирает подмножество
DDG_QUERIES_POOL = [
    # Производство и франшизы
    f"new franchise business ideas {_YEAR} investment",
    f"manufacturing startup ideas {_YEAR} market opportunity",
    f"distribution business model success {_YEAR}",
    f"physical product business opportunity investment {_YEAR}",
    f"retail food franchise growth {_YEAR}",
    # Конкретные ниши
    f"private label manufacturing startup {_YEAR}",
    f"micro factory container production {_YEAR}",
    f"vending machine business opportunity {_YEAR}",
    f"B2B wholesale startup {_YEAR}",
    f"packaging business opportunity {_YEAR}",
    # Тренды и инновации
    f"trending small business ideas {_YEAR} production",
    f"best new franchise opportunities {_YEAR}",
    f"emerging business models {_YEAR} physical products",
    f"successful startup launches {_YEAR} manufacturing",
    f"new consumer product trends {_YEAR}",
    # AI/Tech с монетизацией
    f"AI startup business model {_YEAR} revenue",
    f"SaaS startup B2B {_YEAR} profitable",
    # Российский и СНГ контекст
    f"бизнес идеи производство {_YEAR}",
    f"франшизы новые {_YEAR} Россия",
    f"стартап производство товаров {_YEAR}",
]

def _search_ddg(query: str, max_results: int = 5) -> list[dict]:
    """Поиск через duckduckgo-search библиотеку с retry."""
    # Вариант 1: библиотека duckduckgo-search
    for attempt in range(MAX_RETRIES + 1):
        try:
            from duckduckgo_search import DDGS
            results = []
            with DDGS() as ddgs:
                for r in ddgs.text(query, max_results=max_results):
                    results.append({
                        "title":   r.get("title", ""),
                        "snippet": r.get("body",  ""),
                        "url":     r.get("href", ""),
                    })
            if results:
                return results
        except ImportError:
            break  # Нет библиотеки — сразу к fallback
        except Exception as e:
            logger.warning("duckduckgo-search attempt %s: %s", attempt + 1, public_error(e))
            if attempt < MAX_RETRIES:
                time.sleep(1 + attempt)
                continue

    # Вариант 2: DuckDuckGo Lite HTML (fallback)
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = requests.get(
                "https://lite.duckduckgo.com/lite/",
                params={"q": query},
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0"},
                timeout=15,
            )
            if resp.status_code != 200:
                if attempt < MAX_RETRIES:
                    time.sleep(1 + attempt)
                    continue
                return []
            results = []
            snippets = re.findall(r'<td class=["\']result-snippet["\'][^>]*>(.*?)</td>',
                                  resp.text, re.DOTALL)
            titles   = re.findall(r'<a[^>]+class=["\']result-link["\'][^>]*>(.*?)</a>',
                                  resp.text, re.DOTALL)
            for title, snippet in zip(titles[:max_results], snippets[:max_results]):
                title   = re.sub(r'<[^>]+>', '', title).strip()
                snippet = re.sub(r'<[^>]+>', '', snippet).strip()
                if title:
                    results.append({"title": title, "snippet": snippet, "url": ""})
            return results
        except Exception as e:
            logger.warning("DuckDuckGo Lite attempt %s: %s", attempt + 1, public_error(e))
            if attempt < MAX_RETRIES:
                time.sleep(1 + attempt)
    return []


def _gather_ddg_context(count: int) -> str:
    """Собирает контекст из DuckDuckGo для случайной выборки запросов."""
    all_snippets = []
    seen_titles = set()

    # Берём 5-7 случайных запросов из пула для разнообразия
    num_queries = min(7, max(5, count))
    queries_to_use = random.sample(DDG_QUERIES_POOL, min(num_queries, len(DDG_QUERIES_POOL)))

    for query in queries_to_use:
        results = _search_ddg(query, max_results=5)
        if results:
            all_snippets.append(f"=== {query} ===")
            for r in results:
                # Дедупликация по заголовку
                title_lower = r['title'].lower().strip()
                if title_lower in seen_titles:
                    continue
                seen_titles.add(title_lower)
                snippet_line = f"• {r['title']}: {r['snippet']}"
                if r.get('url'):
                    snippet_line += f" [{r['url']}]"
                all_snippets.append(snippet_line)
        time.sleep(0.5)  # Чуть больше задержка для стабильности

    context = "\n".join(all_snippets)
    logger.info(f"DuckDuckGo: собрано {len(seen_titles)} уникальных фрагментов "
                f"из {len(queries_to_use)} запросов")
    return context


# ── Ollama вызов ───────────────────────────────────────────────────────────

def _call_ollama(prompt: str, model: str = OLLAMA_MODEL,
                 timeout: int = 240) -> Optional[str]:
    """Вызывает Ollama API с retry и возвращает текст ответа."""
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = requests.post(
                f"{OLLAMA_URL}/api/chat",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user",   "content": prompt},
                    ],
                    "stream": False,
                    "options": {
                        "temperature": 0.7,
                        "num_predict": 10240,  # Увеличено для 7+ идей со scores
                    },
                },
                timeout=timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            content = data.get("message", {}).get("content", "")
            if content:
                return content
            logger.warning(f"Ollama вернул пустой ответ (попытка {attempt+1})")
        except requests.exceptions.ConnectionError:
            logger.error(f"Ollama недоступен на {OLLAMA_URL} — запущен ли сервис?")
            return None  # Нет смысла ретраить если сервис недоступен
        except requests.exceptions.Timeout:
            logger.warning(f"Ollama timeout (попытка {attempt+1}/{MAX_RETRIES+1})")
        except Exception as e:
            logger.error("Ollama attempt %s failed: %s", attempt + 1, public_error(e))

        if attempt < MAX_RETRIES:
            wait = 5 * (attempt + 1)
            logger.info(f"Ждём {wait}с перед повторной попыткой...")
            time.sleep(wait)

    return None


def _parse_ideas(raw: str) -> list[dict]:
    """Извлекает JSON-массив из ответа модели."""
    if not isinstance(raw, str) or not raw or len(raw) > 200_000:
        return []

    # Убираем <think>...</think> блоки reasoning-моделей
    raw = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip()

    # Убираем markdown code-fences (```json ... ``` или ``` ... ```)
    raw = re.sub(r'```(?:json)?\s*', '', raw)
    raw = raw.replace('```', '').strip()

    # Паттерны для поиска JSON-массива (от строгих к мягким)
    patterns = [
        r'\[\s*\{[\s\S]*\}\s*\]',   # строгий массив объектов
        r'\[[\s\S]*\]',              # любой массив
    ]

    for pattern in patterns:
        match = re.search(pattern, raw, re.DOTALL)
        if match:
            candidate = match.group()
            # Пробуем разные исправления JSON
            for fix in [
                lambda s: s,                                        # без изменений
                lambda s: re.sub(r',\s*([}\]])', r'\1', s),         # trailing commas
                lambda s: s.replace('\n', ' ').replace('\r', ''),    # без переносов
            ]:
                try:
                    ideas = json.loads(fix(candidate))
                    if (isinstance(ideas, list) and ideas
                            and len(ideas) <= MAX_RESPONSE_IDEAS
                            and all(isinstance(idea, dict) for idea in ideas)):
                        for idea in ideas:
                            if isinstance(idea.get("verdict"), str):
                                idea["verdict"] = idea["verdict"].lower()
                        logger.info(f"Распарсено {len(ideas)} идей")
                        return ideas
                except (json.JSONDecodeError, Exception):
                    continue

    logger.warning("Не удалось распарсить JSON из ответа Ollama")
    return []


def _normalize_idea(idea: dict) -> dict:
    """Нормализует структуру идеи — добавляет отсутствующие поля с дефолтами."""
    # Гарантируем наличие scores (нужно для сортировки в PDF и Telegram)
    if "scores" not in idea or not isinstance(idea.get("scores"), dict):
        loc = idea.get("localization", {})
        rp = loc.get("russia_potential", 5)
        re_ = loc.get("replication_ease", 5)
        of_ = loc.get("operational_feasibility", 5)
        ct = loc.get("complexity_threshold", 5)
        avg = (rp + re_ + of_ + ct) / 4
        idea["scores"] = {
            "novelty": min(10, round(avg + 1)),
            "market_potential": rp,
            "ease_of_launch": ct,
            "scalability": min(10, round((rp + re_) / 2)),
            "hypothesis_speed": re_,
            "investment_appeal": min(10, round(avg)),
            "risk": max(1, 10 - of_),
        }

    # Гарантируем наличие localization
    if "localization" not in idea or not isinstance(idea.get("localization"), dict):
        idea["localization"] = {
            "russia_potential": 5,
            "replication_ease": 5,
            "operational_feasibility": 5,
            "complexity_threshold": 5,
        }

    # Обязательные текстовые поля
    defaults = {
        "name": "Без названия",
        "category": "Общее",
        "summary": "",
        "why_interesting": "",
        "investment_range": "Требует оценки",
        "target_client": "",
        "revenue_model": "",
        "innovation": "",
        "investment_format": "",
        "risks": "",
        "verdict": "интересно",
        "sources": [],
        "localization_label": "",
    }
    for key, default in defaults.items():
        if key not in idea or not idea[key]:
            idea[key] = default

    # sources всегда список
    if isinstance(idea["sources"], str):
        idea["sources"] = [idea["sources"]]

    return idea


# ── Публичный интерфейс ────────────────────────────────────────────────────

def check_ollama() -> bool:
    """Проверяет доступность Ollama и наличие модели."""
    try:
        resp = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        if resp.status_code != 200:
            return False
        models = [m["name"] for m in resp.json().get("models", [])]
        logger.info(f"Ollama доступен. Модели: {models}")
        available = any(OLLAMA_MODEL.split(":")[0] in m for m in models)
        if not available:
            logger.warning(f"Модель {OLLAMA_MODEL} не найдена. Доступны: {models}")
        return available
    except Exception:
        return False


def _normalize_name(name: str) -> str:
    """Нормализует имя идеи для сравнения (дедупликация)."""
    name = name.lower().strip()
    # Убираем спецсимволы и лишние пробелы
    name = re.sub(r'[^\w\s]', ' ', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def search_ideas_ollama(sent_ideas: list = None, count: int = 7, sent_topics: list | None = None) -> list[dict]:
    """
    Основная функция: ищет идеи через DuckDuckGo + анализирует через Ollama.

    Args:
        sent_ideas: список уже отправленных идей (чтобы не повторяться)
        count: количество новых идей

    Returns:
        Список словарей с идеями (совместим с форматом demo_ideas)
    """
    validate_count(count)
    sent_names = sent_ideas or []
    # Запрашиваем на 2 больше чтобы компенсировать возможные дубли
    request_count = count + 2
    logger.info(f"Ollama-поиск: запрашиваем {request_count} идей (цель: {count})...")

    # 1. Пробуем DuckDuckGo
    logger.info("Собираем контекст из DuckDuckGo...")
    ddg_context = _gather_ddg_context(count)

    if not ddg_context:
        raise RuntimeError("Live acquisition returned no source context")

    # 2. Формируем промпт
    prompt = _search_prompt(sent_names, request_count, ddg_context, sent_topics=sent_topics)

    # 3. Вызываем Ollama
    logger.info(f"Отправляем запрос в {OLLAMA_MODEL}...")
    start = time.time()
    raw = _call_ollama(prompt)
    elapsed = time.time() - start
    logger.info(f"Ollama ответил за {elapsed:.1f}с")

    if not raw:
        logger.error("Ollama не вернул ответ")
        return []

    # 4. Парсим JSON
    ideas = _parse_ideas(raw)

    if not ideas:
        logger.error("Не удалось извлечь идеи из ответа модели")
        return []

    # 5. Нормализуем и дедуплицируем
    sent_normalized = {_normalize_name(n) for n in sent_names}
    unique_ideas = []
    seen_names = set()

    for idea in ideas:
        idea = _normalize_idea(validate_ideas([idea], limit=1)[0])
        norm_name = _normalize_name(idea.get("name", ""))

        # Пропускаем дубли (в текущей партии или ранее отправленные)
        if norm_name in seen_names:
            logger.info(f"Пропуск дубля в партии: {idea.get('name')}")
            continue
        if norm_name in sent_normalized:
            logger.info(f"Пропуск ранее отправленной: {idea.get('name')}")
            continue

        seen_names.add(norm_name)
        unique_ideas.append(idea)

    # Обрезаем до нужного количества
    unique_ideas = unique_ideas[:count]

    logger.info(f"Готово: {len(unique_ideas)} уникальных идей "
                f"(из {len(ideas)} полученных)")
    return unique_ideas


if __name__ == "__main__":
    # Быстрый тест
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")

    print("Проверка Ollama...")
    if not check_ollama():
        print("ОШИБКА: Ollama недоступен или модель не найдена")
        exit(1)

    print("Ищем идеи...")
    ideas = search_ideas_ollama(count=3)
    print(f"\nПолучено {len(ideas)} идей:")
    for i, idea in enumerate(ideas, 1):
        print(f"\n{i}. {idea.get('name','?')}")
        print(f"   Категория: {idea.get('category','?')}")
        print(f"   Инвестиции: {idea.get('investment_range','?')}")
        print(f"   {idea.get('summary','')[:100]}...")

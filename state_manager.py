"""
Менеджер состояния: журнал идей, визуальные темы и мягкая память тем выпусков.
"""
import json
import logging
from safe_errors import public_error
import re
import shutil
import unicodedata
from datetime import datetime
from config import REPORTS_DIR, SENT_IDEAS_LOG, STATE_DIR, TOPIC_MEMORY_FILE, VISUAL_THEME_FILE, VISUAL_THEMES, get_visual_theme

logger = logging.getLogger(__name__)

def ensure_dirs():
    """Создаёт необходимые директории."""
    from config import STATE_DIR, REPORTS_DIR, LOGS_DIR
    for d in [STATE_DIR, REPORTS_DIR, LOGS_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def load_sent_ideas() -> dict:
    """Загружает журнал отправленных идей."""
    if not SENT_IDEAS_LOG.exists():
        return {"ideas": [], "total_sent": 0, "last_updated": None}
    try:
        with open(SENT_IDEAS_LOG, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Ошибка чтения журнала идей: {public_error(e)}")
        return {"ideas": [], "total_sent": 0, "last_updated": None}


def save_sent_ideas(log_data: dict):
    """Сохраняет журнал отправленных идей с бэкапом."""
    log_data["last_updated"] = datetime.now().isoformat()
    # Бэкап перед записью — защита от повреждения при сбое
    if SENT_IDEAS_LOG.exists():
        backup = SENT_IDEAS_LOG.with_suffix(".json.bak")
        try:
            shutil.copy2(SENT_IDEAS_LOG, backup)
        except Exception as e:
            logger.warning(f"Не удалось создать бэкап журнала: {public_error(e)}")
    with open(SENT_IDEAS_LOG, "w", encoding="utf-8") as f:
        json.dump(log_data, f, ensure_ascii=False, indent=2)


def add_ideas_to_log(ideas: list, issue_number: int):
    """Добавляет новые идеи в журнал."""
    log = load_sent_ideas()
    for idea in ideas:
        entry = {
            "name": idea.get("name", ""),
            "summary": idea.get("summary", idea.get("description", "")),
            "issue": issue_number,
            "date": datetime.now().strftime("%Y-%m-%d"),
            "category": idea.get("category", ""),
            "investment_range": idea.get("investment_range", ""),
        }
        log["ideas"].append(entry)
    log["total_sent"] = len(log["ideas"])
    save_sent_ideas(log)
    logger.info(f"Добавлено {len(ideas)} идей в журнал. Всего: {log['total_sent']}")


def get_sent_idea_names() -> list:
    """Возвращает список названий уже отправленных идей."""
    log = load_sent_ideas()
    return [idea.get("name", "").lower() for idea in log.get("ideas", [])]


def _normalize_topic_part(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", (text or "").lower())
    cleaned_chars = []
    for ch in normalized:
        if ch.isalnum() or ch.isspace():
            cleaned_chars.append(ch)
        else:
            cleaned_chars.append(" ")
    cleaned = "".join(cleaned_chars)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def build_topic_signature(idea: dict) -> str:
    """
    Возвращает короткую сигнатуру темы идеи.

    Базовый приоритет:
    1. Нормализованное название идеи
    2. Категория как fallback

    Сигнатура намеренно мягкая: ловим почти точные повторы одной и той же идеи,
    но не режем смежные вариации внутри широкой категории.
    """
    name = _normalize_topic_part(idea.get("name", ""))
    if name:
        return name

    return _normalize_topic_part(idea.get("category", ""))


def idea_conflicts_with_topics(idea: dict, topic_signatures: set[str]) -> bool:
    signature = build_topic_signature(idea)
    if not signature:
        return False
    return signature in topic_signatures


def load_topic_memory() -> dict:
    """Загружает накопитель тем."""
    if not TOPIC_MEMORY_FILE.exists():
        return {"issues": [], "last_updated": None}
    try:
        with open(TOPIC_MEMORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                data.setdefault("issues", [])
                return data
    except Exception as e:
        logger.warning(f"Ошибка чтения накопителя тем: {public_error(e)}")
    return {"issues": [], "last_updated": None}


def save_topic_memory(memory: dict):
    """Сохраняет накопитель тем."""
    memory["last_updated"] = datetime.now().isoformat()
    with open(TOPIC_MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(memory, f, ensure_ascii=False, indent=2)


def add_issue_topics_to_memory(ideas: list, issue_number: int):
    """Добавляет темы выпуска в накопитель."""
    memory = load_topic_memory()
    topic_entries = []
    for idea in ideas:
        signature = build_topic_signature(idea)
        if signature:
            topic_entries.append(
                {
                    "name": idea.get("name", ""),
                    "category": idea.get("category", ""),
                    "signature": signature,
                }
            )

    deduped = []
    seen_signatures = set()
    for entry in topic_entries:
        if entry["signature"] in seen_signatures:
            continue
        seen_signatures.add(entry["signature"])
        deduped.append(entry)

    if not deduped:
        return

    memory["issues"].append(
        {
            "issue": issue_number,
            "date": datetime.now().strftime("%Y-%m-%d"),
            "topics": deduped,
        }
    )
    save_topic_memory(memory)
    logger.info("Добавлено %s тем выпуска в накопитель тем", len(deduped))


def get_sent_topic_signatures(issue_window: int | None = None) -> list[str]:
    """Возвращает сигнатуры тем из последних боевых выпусков."""
    memory = load_topic_memory()
    issues = memory.get("issues", [])
    if issue_window:
        issues = issues[-issue_window:]

    signatures = []
    for issue in issues:
        for topic in issue.get("topics", []):
            signature = topic.get("signature", "")
            if signature:
                signatures.append(signature)
    return list(dict.fromkeys(signatures))


def get_recent_topics(issue_window: int | None = None, limit: int = 20) -> list[dict]:
    """Возвращает список последних тем для панели."""
    memory = load_topic_memory()
    issues = memory.get("issues", [])
    if issue_window:
        issues = issues[-issue_window:]

    recent_topics = []
    for issue in reversed(issues):
        for topic in issue.get("topics", []):
            recent_topics.append(
                {
                    "issue": issue.get("issue"),
                    "date": issue.get("date", ""),
                    "name": topic.get("name", ""),
                    "category": topic.get("category", ""),
                    "signature": topic.get("signature", ""),
                }
            )
            if len(recent_topics) >= limit:
                return recent_topics
    return recent_topics


def clear_topic_memory():
    """Очищает память тем."""
    save_topic_memory({"issues": [], "last_updated": None})


def get_next_issue_number() -> int:
    """Определяет номер следующего выпуска."""
    log = load_sent_ideas()
    issues = set()
    for idea in log.get("ideas", []):
        if "issue" in idea:
            issues.add(idea["issue"])
    return max(issues) + 1 if issues else 1


def load_current_theme() -> str:
    """Загружает ID текущей/последней использованной темы."""
    if not VISUAL_THEME_FILE.exists():
        return "dark_investment"  # начнём с тёмной, чтобы первой была другая
    try:
        return VISUAL_THEME_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        return "dark_investment"


def save_current_theme(theme_id: str):
    """Сохраняет ID использованной темы."""
    VISUAL_THEME_FILE.write_text(theme_id, encoding="utf-8")


def get_next_theme() -> dict:
    """Возвращает следующую тему в ротации."""
    current = load_current_theme()
    ids = [theme["id"] for theme in VISUAL_THEMES]
    if current in ids:
        idx = (ids.index(current) + 1) % len(ids)
    else:
        idx = 0
    return get_visual_theme(ids[idx])


def get_runtime_theme(settings: dict | None = None) -> dict:
    """Возвращает тему с учётом runtime-настроек панели."""
    if not settings:
        return get_next_theme()

    theme_settings = settings.get("themes", {})
    mode = theme_settings.get("mode", "rotate")
    enabled_ids = theme_settings.get("enabled_theme_ids", [theme["id"] for theme in VISUAL_THEMES])
    enabled_ids = [theme_id for theme_id in enabled_ids if theme_id in {theme["id"] for theme in VISUAL_THEMES}]
    if not enabled_ids:
        enabled_ids = [theme["id"] for theme in VISUAL_THEMES]

    if mode == "fixed":
        fixed_theme_id = theme_settings.get("fixed_theme_id", enabled_ids[0])
        return get_visual_theme(fixed_theme_id)

    current = load_current_theme()
    if current in enabled_ids:
        idx = (enabled_ids.index(current) + 1) % len(enabled_ids)
    else:
        idx = 0
    return get_visual_theme(enabled_ids[idx])


def list_recent_reports(limit: int = 10) -> list[dict]:
    """Возвращает список последних PDF-отчётов."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    reports = []
    for path in sorted(REPORTS_DIR.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
        stat = path.stat()
        reports.append(
            {
                "name": path.name,
                "path": str(path),
                "size_kb": round(stat.st_size / 1024, 1),
                "modified_at": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
            }
        )
    return reports


def get_recent_issues(limit: int = 10) -> list[dict]:
    """Возвращает последние выпуски по журналу идей."""
    log = load_sent_ideas()
    seen = {}
    for idea in reversed(log.get("ideas", [])):
        issue = idea.get("issue")
        if issue is None or issue in seen:
            continue
        seen[issue] = {
            "issue": issue,
            "date": idea.get("date", ""),
            "category": idea.get("category", ""),
        }
        if len(seen) >= limit:
            break
    return list(seen.values())

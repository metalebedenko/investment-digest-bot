"""
Базовая конфигурация проекта Investment Digest.

Файл содержит только стабильные константы проекта:
- пути
- реестр визуальных тем

Изменяемые runtime-настройки хранятся отдельно в state/runtime_settings.json.
"""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


# === Пути ===
STATE_DIR = BASE_DIR / "state"
REPORTS_DIR = BASE_DIR / "reports"
LOGS_DIR = BASE_DIR / "logs"

SENT_IDEAS_LOG = STATE_DIR / "sent_ideas_log.json"
VISUAL_THEME_FILE = STATE_DIR / "last_visual_theme.txt"
RUNTIME_SETTINGS_FILE = STATE_DIR / "runtime_settings.json"
RUNTIME_BASELINE_FILE = STATE_DIR / "runtime_settings_baseline.json"
SCHEDULER_STATE_FILE = STATE_DIR / "scheduler_state.json"
TOPIC_MEMORY_FILE = STATE_DIR / "topic_memory.json"


# Environment and .env are read only by an explicitly requested live/panel operation.
IDEAS_COUNT_MIN = 5
IDEAS_COUNT_MAX = 10
DEFAULT_BRAND_NAME = "Investment Digest"
DEFAULT_FOOTER_BRAND = "Research prototype"


VISUAL_THEMES = [
    {
        "id": "teal_gold_light",
        "name": "Teal Gold Light",
        "desc": "Бирюзово-золотая светлая тема",
        "palette": {
            "cover_bg": "#123B45",
            "primary": "#123B45",
            "accent": "#C9A84C",
            "success": "#2E7D32",
            "surface": "#F3FAF8",
            "muted": "#607579",
            "text": "#172022",
            "line": "#D7E6E1",
            "warning": "#C7772D",
            "danger": "#A2362B",
        },
    },
    {
        "id": "pe_navy_silver",
        "name": "PE Navy Silver",
        "desc": "Строгий PE/фондовый стиль",
        "palette": {
            "cover_bg": "#0D2244",
            "primary": "#0D2244",
            "accent": "#B9C2D0",
            "success": "#2F6F44",
            "surface": "#F5F7FA",
            "muted": "#5D6878",
            "text": "#172033",
            "line": "#D9DFE8",
            "warning": "#C07A3B",
            "danger": "#A63838",
        },
    },
    {
        "id": "cleantech_green",
        "name": "Cleantech Green",
        "desc": "Чистые технологии / индустриальный стиль",
        "palette": {
            "cover_bg": "#1E4D3A",
            "primary": "#1E4D3A",
            "accent": "#B9A05E",
            "success": "#287D5A",
            "surface": "#F3F8F5",
            "muted": "#5C6E67",
            "text": "#1A231F",
            "line": "#D8E3DC",
            "warning": "#B9772B",
            "danger": "#9E4134",
        },
    },
    {
        "id": "light_editorial",
        "name": "Light Editorial",
        "desc": "Светлый журнальный стиль",
        "palette": {
            "cover_bg": "#24324A",
            "primary": "#24324A",
            "accent": "#C89A4B",
            "success": "#326A42",
            "surface": "#FAF8F3",
            "muted": "#6B6A67",
            "text": "#1F1D1A",
            "line": "#E6DFD3",
            "warning": "#B9702E",
            "danger": "#A53B32",
        },
    },
    {
        "id": "minimalist_board",
        "name": "Minimalist Board",
        "desc": "Минималистичный board-report",
        "palette": {
            "cover_bg": "#202124",
            "primary": "#202124",
            "accent": "#A78B61",
            "success": "#3B7C4A",
            "surface": "#F7F7F7",
            "muted": "#6C7075",
            "text": "#17191C",
            "line": "#DEDFE1",
            "warning": "#B67935",
            "danger": "#A54141",
        },
    },
    {
        "id": "dark_investment",
        "name": "Dark Investment",
        "desc": "Тёмная инвестиционная тема",
        "palette": {
            "cover_bg": "#0B1628",
            "primary": "#13233F",
            "accent": "#D6A94D",
            "success": "#2E7D32",
            "surface": "#F3F5F8",
            "muted": "#657083",
            "text": "#182233",
            "line": "#D9DEE7",
            "warning": "#D07B2C",
            "danger": "#A83E3E",
        },
    },
    {
        "id": "premium_dossier",
        "name": "Premium Dossier",
        "desc": "Премиальный досье-стиль",
        "palette": {
            "cover_bg": "#2C1F1A",
            "primary": "#2C1F1A",
            "accent": "#C59A6D",
            "success": "#446B46",
            "surface": "#FAF6F1",
            "muted": "#75655B",
            "text": "#251E19",
            "line": "#E5DAD1",
            "warning": "#BA7435",
            "danger": "#9F4636",
        },
    },
    {
        "id": "data_heavy",
        "name": "Data Heavy",
        "desc": "Аналитический data-heavy стиль",
        "palette": {
            "cover_bg": "#173A5E",
            "primary": "#173A5E",
            "accent": "#7DB2D9",
            "success": "#2A7258",
            "surface": "#F3F8FC",
            "muted": "#60758A",
            "text": "#172432",
            "line": "#D6E1EB",
            "warning": "#C57B37",
            "danger": "#A63D3A",
        },
    },
]


def get_visual_theme(theme_id: str) -> dict:
    """Возвращает тему по ID или первую тему как fallback."""
    for theme in VISUAL_THEMES:
        if theme["id"] == theme_id:
            return theme
    return VISUAL_THEMES[0]


def get_theme_ids() -> list[str]:
    """Возвращает список доступных ID тем."""
    return [theme["id"] for theme in VISUAL_THEMES]

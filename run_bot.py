"""
Investment Digest Bot — главный оркестратор.

Запуск:
    python run_bot.py           — полный прогон (поиск + PDF + Telegram)
    python run_bot.py --demo    — автономный PDF на синтетических данных
    python run_bot.py --pdf-only — PDF без отправки в Telegram
    python run_bot.py --test-tg — тест подключения к Telegram
    python run_bot.py --count 7 — задать конкретное количество идей
"""

import argparse
import logging
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from idea_validation import validate_count
from safe_errors import public_error

BASE_DIR = Path(__file__).parent

def configure_logging():
    log_dir = BASE_DIR / "logs"
    log_dir.mkdir(exist_ok=True)
    daily_log = log_dir / f"digest_{datetime.now():%Y%m%d}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            RotatingFileHandler(log_dir / "cron_runs.log", maxBytes=5*1024*1024,
                                backupCount=3, encoding="utf-8"),
            logging.FileHandler(daily_log, encoding="utf-8"),
        ],
    )


logger = logging.getLogger("main")

# ── Imports ──────────────────────────────────────────────────────────────
sys.path.insert(0, str(BASE_DIR))

import bot_services


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Investment Digest Bot")
    parser.add_argument("--demo", action="store_true",
                        help="Автономный PDF на синтетических данных, без LLM и Telegram")
    parser.add_argument("--pdf-only", action="store_true",
                        help="Только PDF, без Telegram")
    parser.add_argument("--test-tg", action="store_true",
                        help="Тест подключения к Telegram")
    parser.add_argument("--count", type=int, default=0,
                        help="Количество идей 1–10 (0 = автоматически; demo = 5)")
    args = parser.parse_args(argv)
    if args.demo and args.test_tg:
        parser.error("--demo cannot be combined with --test-tg")
    try:
        validate_count(args.count, allow_auto=True)
    except ValueError:
        parser.error("--count must be an integer from 0 to 10")
    return args


def test_telegram():
    logger.info("Тестирование Telegram...")
    ok = bot_services.ping_bot()
    logger.info("OK" if ok else "FAIL")
    return ok


def run(demo: bool = False, pdf_only: bool = False, count_override: int = 0):
    logger.info("=" * 60)
    logger.info(f"Запуск {datetime.now():%d.%m.%Y %H:%M} | demo={demo} pdf_only={pdf_only}")
    logger.info("=" * 60)
    try:
        result = bot_services.run_digest(
            demo=demo,
            pdf_only=pdf_only,
            count_override=count_override,
            preview=False,
        )
        logger.info(
            "Готово. Выпуск #%03d | идей=%s | тема=%s | editorial=%s | telegram=%s",
            result["issue_number"],
            result["ideas_count"],
            result["theme_name"],
            result["editorial_used"],
            result["telegram_sent"],
        )
        return True
    except Exception as e:
        logger.error("Ошибка запуска пайплайна: %s", public_error(e))
        return False


def main():
    args = parse_args()
    configure_logging()
    try:
        if args.test_tg:
            sys.exit(0 if test_telegram() else 1)
        sys.exit(0 if run(
            demo=args.demo,
            pdf_only=args.pdf_only,
            count_override=args.count,
        ) else 1)
    except Exception as e:
        logger.critical("Необработанное исключение: %s", public_error(e))
        sys.exit(2)


if __name__ == "__main__":
    main()

"""
Простой runtime scheduler для автоматических отправок.

Работает в фоне и ориентируется на runtime settings из панели.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timedelta

import config
from safe_errors import PUBLIC_ERROR_CODES, public_error
from runtime_settings import get_settings


logger = logging.getLogger(__name__)

_thread = None
_lock = threading.Lock()


def _default_state() -> dict:
    return {
        "last_run_key": "",
        "last_run_at": "",
        "last_status": "idle",
        "last_error": "",
        "last_result": {},
    }


def load_scheduler_state() -> dict:
    if not config.SCHEDULER_STATE_FILE.exists():
        return _default_state()
    try:
        with open(config.SCHEDULER_STATE_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            return data if isinstance(data, dict) else _default_state()
    except Exception:
        return _default_state()


def save_scheduler_state(state: dict):
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(config.SCHEDULER_STATE_FILE, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)


def get_scheduler_snapshot() -> dict:
    settings = get_settings()
    state = load_scheduler_state()
    prior_error = state.get("last_error", "")
    if prior_error and (not isinstance(prior_error, str) or prior_error not in PUBLIC_ERROR_CODES):
        state["last_error"] = "OPERATION_FAILED"
    return {
        "settings": settings.get("schedule", {}),
        "state": state,
        "next_hint": describe_schedule(settings.get("schedule", {})),
        "running": bool(settings.get("schedule", {}).get("enabled") and _thread and _thread.is_alive()),
    }


def describe_schedule(schedule: dict) -> str:
    if not schedule.get("enabled"):
        return "Автоотправка выключена"
    if schedule.get("frequency") == "hourly":
        return f"Каждые {schedule.get('interval_hours', 24)} ч. в {int(schedule.get('minute', 0)):02d} мин."
    return f"Ежедневно в {int(schedule.get('hour', 10)):02d}:{int(schedule.get('minute', 45)):02d}"


def _resolve_due_slot(schedule: dict, current: datetime) -> str:
    minute = int(schedule.get("minute", 0))
    frequency = schedule.get("frequency", "daily")

    if frequency == "hourly":
        interval = max(1, int(schedule.get("interval_hours", 24)))
        slot = current.replace(minute=minute, second=0, microsecond=0)
        if current.minute < minute:
            slot -= timedelta(hours=1)
        slot -= timedelta(hours=slot.hour % interval)
        return slot.strftime("%Y-%m-%d %H:%M")

    hour = int(schedule.get("hour", 10))
    slot = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if current < slot:
        return ""
    return slot.strftime("%Y-%m-%d %H:%M")


def should_run_now(schedule: dict, state: dict, now: datetime | None = None) -> tuple[bool, str]:
    current = now or datetime.now()
    if not schedule.get("enabled"):
        return False, ""

    slot_key = _resolve_due_slot(schedule, current)
    if not slot_key:
        return False, ""

    if state.get("last_run_key") == slot_key:
        return False, slot_key
    return True, slot_key


def run_scheduler_tick(run_callable):
    settings = get_settings()
    schedule = settings.get("schedule", {})
    state = load_scheduler_state()
    should_run, run_key = should_run_now(schedule, state)
    if not should_run:
        return None

    logger.info("Scheduler triggered digest run for slot %s", run_key)
    state["last_status"] = "running"
    state["last_error"] = ""
    save_scheduler_state(state)

    try:
        result = run_callable()
        state["last_run_key"] = run_key
        state["last_run_at"] = datetime.now().isoformat(timespec="seconds")
        state["last_status"] = "ok"
        state["last_result"] = result or {}
        state["last_error"] = ""
    except Exception as exc:
        state["last_run_key"] = run_key
        state["last_run_at"] = datetime.now().isoformat(timespec="seconds")
        state["last_status"] = "error"
        state["last_result"] = {}
        state["last_error"] = public_error(exc)
        logger.error("Scheduler run failed (%s)", public_error(exc))

    save_scheduler_state(state)
    return state


def start_background_scheduler(run_callable, interval_sec: int = 20):
    global _thread
    with _lock:
        if _thread and _thread.is_alive():
            return

        def loop():
            logger.info("Background scheduler loop started")
            while True:
                try:
                    run_scheduler_tick(run_callable)
                except Exception as exc:
                    logger.error("Scheduler tick crashed (%s)", public_error(exc))
                time.sleep(interval_sec)

        _thread = threading.Thread(target=loop, name="digest-scheduler", daemon=True)
        _thread.start()

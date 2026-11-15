"""
Простая управляющая панель для Investment Digest Bot.

Запуск:
    python admin_panel.py
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus, urlsplit

from flask import Flask, abort, redirect, render_template_string, request, send_from_directory
from werkzeug.exceptions import HTTPException

import bot_services
import config
import scheduler_runtime
from safe_errors import public_error


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

PANEL_PORT = 8787
app = Flask(__name__)
app.config.update(
    CSRF_TOKEN=secrets.token_urlsafe(32),
    MAX_CONTENT_LENGTH=64 * 1024,
)
logger = logging.getLogger(__name__)


def _local_endpoint(value: str, *, host_header: bool = False):
    try:
        parsed = urlsplit(f"{request.scheme}://{value}" if host_header else value)
        if (parsed.scheme not in {"http", "https"}
                or parsed.hostname not in {"127.0.0.1", "localhost"}
                or parsed.port != PANEL_PORT
                or parsed.username is not None or parsed.password is not None
                or parsed.path or parsed.query or parsed.fragment):
            return None
        return parsed.scheme, parsed.hostname, parsed.port
    except (TypeError, ValueError):
        return None


@app.before_request
def require_local_browser_request():
    # Host is a DNS-rebinding boundary, not authorization by itself. Mutations
    # additionally require an unpredictable token and a same-origin browser.
    endpoint = _local_endpoint(request.host, host_header=True)
    if endpoint is None:
        abort(403)
    fetch_site = request.headers.get("Sec-Fetch-Site", "")
    if fetch_site not in {"", "none", "same-origin"}:
        abort(403)
    origin = request.headers.get("Origin")
    if origin is not None and _local_endpoint(origin) != endpoint:
        abort(403)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        supplied = request.form.get("csrf_token", "")
        expected = app.config["CSRF_TOKEN"]
        if len(supplied) != len(expected) or not secrets.compare_digest(
                supplied.encode("utf-8"), expected.encode("ascii")):
            abort(403)


@app.after_request
def protect_local_response(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = "frame-ancestors 'none'; form-action 'self'; base-uri 'none'"
    return response


@app.errorhandler(Exception)
def handle_panel_error(exc):
    if isinstance(exc, HTTPException):
        return {"error": "HTTP_ERROR"}, exc.code or 500
    code = public_error(exc)
    logger.error("Panel operation failed (%s)", code)
    return {"error": code}, 500


PROVIDERS = [
    ("ollama", "Ollama"),
    ("openai_compatible", "OpenAI-compatible"),
    ("openai", "OpenAI"),
]

SEARCH_SOURCES = [
    ("duckduckgo", "DuckDuckGo"),
    ("perplexity", "Perplexity API"),
    ("openai_search", "OpenAI Search"),
]


def _redirect_with_message(message: str, level: str = "info"):
    return redirect(f"/?message={quote_plus(message)}&level={quote_plus(level)}")


def _form_to_dict(form) -> dict:
    data = {}
    for key in form.keys():
        values = form.getlist(key)
        data[key] = values if len(values) > 1 else values[0]
    return data


def _render_dashboard(message: str = "", level: str = "info"):
    context = bot_services.load_dashboard_context()
    context.update(
        {
            "message": message,
            "level": level,
            "providers": PROVIDERS,
            "search_sources": SEARCH_SOURCES,
            "now": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "csrf_token": app.config["CSRF_TOKEN"],
        }
    )
    return render_template_string(TEMPLATE, **context)


@app.get("/")
def dashboard():
    level = request.args.get("level", "info")
    return _render_dashboard(request.args.get("message", ""), level if level in {"info", "success", "error"} else "info")


@app.post("/actions/ping")
def action_ping():
    ok = bot_services.ping_bot()
    return _redirect_with_message("Пинг отправлен в Telegram." if ok else "Пинг не отправлен. Проверь Telegram settings.", "success" if ok else "error")


@app.post("/actions/message")
def action_message():
    text = request.form.get("message_text", "").strip()
    if not text:
        return _redirect_with_message("Сообщение пустое.", "error")
    ok = bot_services.send_group_message(text)
    return _redirect_with_message("Сообщение отправлено в группу." if ok else "Не удалось отправить сообщение.", "success" if ok else "error")


@app.post("/actions/run")
def action_run():
    mode = request.form.get("mode", "preview")
    try:
        if mode not in {"preview", "demo", "pdf_only", "full"}:
            raise ValueError("Unsupported run mode")
        count_override = int(request.form.get("count_override", "0") or 0)
        if not 0 <= count_override <= 10:
            raise ValueError("Invalid idea count")
        result = bot_services.run_digest(
            demo=(mode == "demo"),
            pdf_only=(mode == "pdf_only"),
            count_override=count_override,
            preview=(mode == "preview"),
        )
        pdf_name = Path(result["pdf_path"]).name
        link = f"/reports/{pdf_name}"
        return _redirect_with_message(
            f"Готово: PDF собран ({pdf_name}). Открыть: {link}",
            "success",
        )
    except Exception as exc:
        return _redirect_with_message(f"Запуск не удался: {public_error(exc)}", "error")


@app.post("/settings/digest")
def save_digest_settings():
    try:
        bot_services.update_digest_settings(_form_to_dict(request.form))
        return _redirect_with_message("Настройки дайджеста сохранены.", "success")
    except Exception as exc:
        return _redirect_with_message(f"Не удалось сохранить digest settings: {public_error(exc)}", "error")


@app.post("/settings/telegram")
def save_telegram_settings():
    try:
        bot_services.update_telegram_settings(_form_to_dict(request.form))
        return _redirect_with_message("Настройки Telegram сохранены. Токен, если введён, записан в .env.", "success")
    except Exception as exc:
        return _redirect_with_message(f"Не удалось сохранить Telegram settings: {public_error(exc)}", "error")


@app.post("/memory/clear")
def clear_topic_memory():
    bot_services.clear_topic_memory()
    return _redirect_with_message("Память тем очищена.", "success")


@app.post("/settings/models")
def save_model_settings():
    try:
        bot_services.update_model_settings(_form_to_dict(request.form))
        return _redirect_with_message("Настройки моделей сохранены.", "success")
    except Exception as exc:
        return _redirect_with_message(f"Не удалось сохранить model settings: {public_error(exc)}", "error")


@app.post("/settings/schedule")
def save_schedule_settings():
    try:
        settings = bot_services.update_schedule_settings(_form_to_dict(request.form))
        if settings.get("schedule", {}).get("enabled"):
            scheduler_runtime.start_background_scheduler(bot_services.run_scheduled_digest)
        return _redirect_with_message("Настройки автоотправки сохранены.", "success")
    except Exception as exc:
        return _redirect_with_message(f"Не удалось сохранить schedule settings: {public_error(exc)}", "error")


@app.post("/settings/reset")
def reset_settings():
    bot_services.reset_settings_to_baseline()
    return _redirect_with_message("Runtime settings сброшены к исходному baseline.", "success")


@app.get("/reports/<path:filename>")
def get_report(filename: str):
    return send_from_directory(config.REPORTS_DIR, filename, as_attachment=False)


TEMPLATE = """
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Investment Digest Control Panel</title>
  <style>
    :root {
      --bg: #f4f1ea;
      --paper: #fffdf8;
      --ink: #1c2128;
      --muted: #6e7278;
      --line: #ddd4c7;
      --brand: #123b45;
      --accent: #c99a47;
      --success: #2f6f44;
      --error: #9f3a30;
      --shadow: 0 10px 30px rgba(28, 33, 40, 0.08);
      --radius: 18px;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Segoe UI", "DejaVu Sans", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(201,154,71,0.12), transparent 26%),
        linear-gradient(180deg, #f8f4ec 0%, #f1eee8 100%);
    }
    .page {
      max-width: 1240px;
      margin: 0 auto;
      padding: 28px 20px 48px;
    }
    .hero {
      background: linear-gradient(135deg, #153b45 0%, #22314c 100%);
      color: white;
      padding: 28px;
      border-radius: 24px;
      box-shadow: var(--shadow);
      margin-bottom: 20px;
    }
    .hero h1 {
      margin: 0 0 8px;
      font-size: 32px;
    }
    .hero p {
      margin: 0;
      max-width: 820px;
      color: rgba(255,255,255,0.86);
      line-height: 1.5;
    }
    .notice {
      margin: 16px 0 0;
      padding: 12px 14px;
      border-radius: 12px;
      font-size: 14px;
      background: rgba(255,255,255,0.12);
      border: 1px solid rgba(255,255,255,0.16);
    }
    .notice.success { background: rgba(62, 130, 82, 0.28); }
    .notice.error { background: rgba(159, 58, 48, 0.28); }
    .grid {
      display: grid;
      grid-template-columns: repeat(12, 1fr);
      gap: 18px;
      margin-top: 20px;
    }
    .card {
      grid-column: span 12;
      background: var(--paper);
      border-radius: var(--radius);
      padding: 22px;
      border: 1px solid var(--line);
      box-shadow: var(--shadow);
    }
    .card.half { grid-column: span 6; }
    .card.third { grid-column: span 4; }
    h2 {
      margin: 0 0 8px;
      font-size: 22px;
      color: var(--brand);
    }
    .sub {
      margin: 0 0 18px;
      color: var(--muted);
      line-height: 1.45;
      font-size: 14px;
    }
    .stats {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 12px;
    }
    .stat {
      background: #f7f2e8;
      border: 1px solid #e5d9c3;
      border-radius: 14px;
      padding: 14px;
    }
    .stat .label {
      font-size: 12px;
      color: var(--muted);
      margin-bottom: 6px;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }
    .stat .value {
      font-size: 18px;
      font-weight: 700;
    }
    form {
      display: block;
    }
    .actions {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 12px;
    }
    .field-grid {
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 12px 16px;
    }
    .field-grid.three { grid-template-columns: repeat(3, 1fr); }
    .field {
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .field.full {
      grid-column: 1 / -1;
    }
    label {
      font-size: 13px;
      color: var(--muted);
      font-weight: 600;
    }
    input[type=text], input[type=password], input[type=number], textarea, select {
      width: 100%;
      border: 1px solid #d6cebf;
      border-radius: 12px;
      padding: 11px 12px;
      background: #fffdfa;
      color: var(--ink);
      font: inherit;
    }
    textarea {
      min-height: 92px;
      resize: vertical;
    }
    .checklist {
      display: flex;
      flex-wrap: wrap;
      gap: 10px 14px;
      background: #faf6ee;
      border: 1px solid #ebe1cf;
      border-radius: 14px;
      padding: 12px;
    }
    .check {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 14px;
    }
    button, .btn-link {
      border: 0;
      border-radius: 12px;
      padding: 11px 14px;
      background: var(--brand);
      color: white;
      cursor: pointer;
      font-weight: 700;
      text-decoration: none;
      display: inline-block;
    }
    button.secondary, .btn-link.secondary {
      background: #2f3f59;
    }
    button.ghost {
      background: #ece4d5;
      color: #4c4d4f;
    }
    button.warn {
      background: var(--error);
    }
    .list {
      display: grid;
      gap: 10px;
    }
    .row {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      border: 1px solid #ebe1cf;
      border-radius: 14px;
      padding: 12px 14px;
      background: #fcf8f0;
    }
    .mono {
      font-family: Consolas, "SFMono-Regular", monospace;
      font-size: 12px;
      white-space: pre-wrap;
      background: #1d2530;
      color: #e9edf3;
      padding: 14px;
      border-radius: 16px;
      overflow: auto;
      max-height: 360px;
    }
    .hint {
      font-size: 12px;
      color: var(--muted);
      margin-top: 6px;
    }
    @media (max-width: 980px) {
      .card.half, .card.third { grid-column: span 12; }
      .stats, .field-grid, .field-grid.three { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="page">
    <section class="hero">
      <h1>Investment Digest Control Panel</h1>
      <p>Лёгкая локальная панель для управления ботом: Telegram-действия, запуск выпуска, настройка тем и шапки, новые модели для поиска и редакторского слоя, а также быстрый возврат к зафиксированному рабочему состоянию.</p>
      {% if message %}
      <div class="notice {{ level }}">{{ message }}</div>
      {% endif %}
    </section>

    <section class="card">
      <h2>Состояние</h2>
      <p class="sub">Короткий срез по текущей конфигурации и панели на {{ now }}.</p>
      <div class="stats">
        <div class="stat">
          <div class="label">Telegram</div>
          <div class="value">{{ "Настроен" if secret_statuses.telegram_bot_token and settings.telegram.chat_id else "Не настроен" }}</div>
        </div>
        <div class="stat">
          <div class="label">Web Search</div>
          <div class="value">{{ settings.models.search.source_provider }}</div>
        </div>
        <div class="stat">
          <div class="label">LLM Analysis</div>
          <div class="value">{{ settings.models.search.provider }} / {{ settings.models.search.model }}</div>
        </div>
        <div class="stat">
          <div class="label">Writer Layer</div>
          <div class="value">{{ "Включён" if settings.models.writer.enabled else "Выключен" }}</div>
        </div>
        <div class="stat">
          <div class="label">Темы</div>
          <div class="value">{{ settings.themes.mode }} / {{ settings.themes.enabled_theme_ids|length }} шт.</div>
        </div>
      </div>
    </section>

    <div class="grid">
      <section class="card half">
        <h2>Быстрые действия</h2>
        <p class="sub">Никакой лишней автоматизации: только полезные и понятные кнопки.</p>
        <form method="post" action="/actions/ping">
          <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
          <button type="submit">Пинг бота</button>
        </form>
        <form method="post" action="/actions/message" style="margin-top:16px;">
          <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
          <div class="field">
            <label for="message_text">Сообщение в группу от бота</label>
            <textarea id="message_text" name="message_text" placeholder="Например: Сегодняшний выпуск выйдет позже обычного."></textarea>
          </div>
          <div class="actions">
            <button type="submit">Отправить текст</button>
          </div>
        </form>
      </section>

      <section class="card half">
        <h2>Telegram</h2>
        <p class="sub">Секретный bot token хранится только в <code>.env</code>. Панель показывает лишь статус, а не само значение.</p>
        <form method="post" action="/settings/telegram">
          <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
          <div class="field-grid">
            <div class="field">
              <label for="telegram_chat_id">Боевой chat ID</label>
              <input id="telegram_chat_id" type="text" name="telegram_chat_id" value="{{ settings.telegram.chat_id }}">
            </div>
            <div class="field">
              <label for="telegram_test_chat_id">Тестовый chat ID</label>
              <input id="telegram_test_chat_id" type="text" name="telegram_test_chat_id" value="{{ settings.telegram.test_chat_id }}">
            </div>
            <div class="field">
              <label for="telegram_bot_token">Bot token</label>
              <input id="telegram_bot_token" type="password" name="telegram_bot_token" value="" placeholder="Ввести новый токен">
              <div class="hint">Статус: {{ "ключ задан" if secret_statuses.telegram_bot_token else "ключ не задан" }}</div>
            </div>
            <div class="field">
              <label class="check">
                <input type="checkbox" name="clear_telegram_bot_token">
                <span>Очистить token из .env</span>
              </label>
            </div>
          </div>
          <div class="actions">
            <button type="submit">Сохранить Telegram settings</button>
          </div>
        </form>
      </section>

      <section class="card half">
        <h2>Запуск выпуска</h2>
        <p class="sub">Preview не меняет журнал и не отправляет в Telegram. Это безопасный способ посмотреть результат перед боевым прогоном.</p>
        <form method="post" action="/actions/run">
          <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
          <div class="field-grid three">
            <div class="field">
              <label for="mode">Режим</label>
              <select id="mode" name="mode">
                <option value="preview">Preview PDF</option>
                <option value="pdf_only">PDF only</option>
                <option value="full">Полный прогон</option>
                <option value="demo">Demo</option>
              </select>
            </div>
            <div class="field">
              <label for="count_override">Количество идей</label>
              <input id="count_override" type="number" name="count_override" min="0" value="0">
            </div>
          </div>
          <div class="actions">
            <button type="submit">Запустить</button>
          </div>
        </form>
      </section>

      <section class="card half">
        <h2>Автоотправка</h2>
        <p class="sub">Сохранение включённого таймера запускает автоматическую отправку в этом процессе. После перезапуска панели включение нужно подтвердить снова.</p>
        <form method="post" action="/settings/schedule">
          <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
          <div class="field-grid three">
            <div class="field">
              <label class="check">
                <input type="checkbox" name="schedule_enabled" {% if settings.schedule.enabled %}checked{% endif %}>
                <span>Автоотправка включена</span>
              </label>
            </div>
            <div class="field">
              <label for="schedule_frequency">Частота</label>
              <select id="schedule_frequency" name="schedule_frequency">
                <option value="daily" {% if settings.schedule.frequency == "daily" %}selected{% endif %}>Ежедневно</option>
                <option value="hourly" {% if settings.schedule.frequency == "hourly" %}selected{% endif %}>Каждые N часов</option>
              </select>
            </div>
            <div class="field">
              <label for="schedule_interval_hours">Интервал, часов</label>
              <input id="schedule_interval_hours" type="number" name="schedule_interval_hours" min="1" max="24" value="{{ settings.schedule.interval_hours }}">
            </div>
            <div class="field">
              <label for="schedule_hour">Час</label>
              <input id="schedule_hour" type="number" name="schedule_hour" min="0" max="23" value="{{ settings.schedule.hour }}">
            </div>
            <div class="field">
              <label for="schedule_minute">Минута</label>
              <input id="schedule_minute" type="number" name="schedule_minute" min="0" max="59" value="{{ settings.schedule.minute }}">
            </div>
          </div>
          <div class="hint">Текущий режим: {{ scheduler.next_hint }}.</div>
          <div class="hint">Таймер в этом процессе: {{ "работает" if scheduler.running else "не запущен" }}.</div>
          <div class="hint">Последний статус: {{ scheduler.state.last_status }}{% if scheduler.state.last_run_at %} · {{ scheduler.state.last_run_at }}{% endif %}{% if scheduler.state.last_error %} · {{ scheduler.state.last_error }}{% endif %}</div>
          <div class="actions">
            <button type="submit">Сохранить таймер</button>
          </div>
        </form>
      </section>

      <section class="card half">
        <h2>Настройки дайджеста</h2>
        <p class="sub">Здесь управляются шапка, число идей и схема выбора визуальной темы. Без избыточных тонких тумблеров.</p>
        <form method="post" action="/settings/digest">
          <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
          <div class="field-grid three">
            <div class="field">
              <label for="ideas_count_min">Мин. идей</label>
              <input id="ideas_count_min" type="number" name="ideas_count_min" min="1" value="{{ settings.digest.ideas_count_min }}">
            </div>
            <div class="field">
              <label for="ideas_count_max">Макс. идей</label>
              <input id="ideas_count_max" type="number" name="ideas_count_max" min="1" value="{{ settings.digest.ideas_count_max }}">
            </div>
            <div class="field">
              <label for="theme_mode">Режим тем</label>
              <select id="theme_mode" name="theme_mode">
                <option value="rotate" {% if settings.themes.mode == "rotate" %}selected{% endif %}>Ротация</option>
                <option value="fixed" {% if settings.themes.mode == "fixed" %}selected{% endif %}>Фиксированная</option>
              </select>
            </div>
            <div class="field">
              <label class="check">
                <input type="checkbox" name="topic_memory_enabled" {% if settings.topic_memory.enabled %}checked{% endif %}>
                <span>Мягко избегать повторов тем</span>
              </label>
            </div>
            <div class="field">
              <label for="topic_memory_recent_issue_window">Не повторять темы за последние N выпусков</label>
              <input id="topic_memory_recent_issue_window" type="number" name="topic_memory_recent_issue_window" min="1" max="100" value="{{ settings.topic_memory.recent_issue_window }}">
            </div>
          </div>
          <div class="field-grid">
            <div class="field">
              <label for="cover_title">Заголовок выпуска</label>
              <input id="cover_title" type="text" name="cover_title" value="{{ settings.digest.cover_title }}">
            </div>
            <div class="field">
              <label for="brand_name">Бренд в header</label>
              <input id="brand_name" type="text" name="brand_name" value="{{ settings.digest.brand_name }}">
            </div>
            <div class="field full">
              <label for="cover_subtitle">Подзаголовок</label>
              <textarea id="cover_subtitle" name="cover_subtitle">{{ settings.digest.cover_subtitle }}</textarea>
            </div>
            <div class="field full">
              <label for="focus_line">Фокус выпуска</label>
              <input id="focus_line" type="text" name="focus_line" value="{{ settings.digest.focus_line }}">
            </div>
            <div class="field">
              <label for="footer_brand">Подпись в footer</label>
              <input id="footer_brand" type="text" name="footer_brand" value="{{ settings.digest.footer_brand }}">
            </div>
            <div class="field full">
              <label for="disclaimer">Дисклеймер</label>
              <textarea id="disclaimer" name="disclaimer">{{ settings.digest.disclaimer }}</textarea>
            </div>
            <div class="field">
              <label for="fixed_theme_id">Фиксированная тема</label>
              <select id="fixed_theme_id" name="fixed_theme_id">
                {% for theme in themes %}
                <option value="{{ theme.id }}" {% if settings.themes.fixed_theme_id == theme.id %}selected{% endif %}>{{ theme.name }}</option>
                {% endfor %}
              </select>
            </div>
            <div class="field full">
              <label>Темы, которые участвуют в ротации</label>
              <div class="checklist">
                {% for theme in themes %}
                <label class="check">
                  <input type="checkbox" name="enabled_theme_ids" value="{{ theme.id }}" {% if theme.id in settings.themes.enabled_theme_ids %}checked{% endif %}>
                  <span>{{ theme.name }}</span>
                </label>
                {% endfor %}
              </div>
            </div>
          </div>
          <div class="actions">
            <button type="submit">Сохранить digest settings</button>
          </div>
        </form>
      </section>

      <section class="card half">
        <h2>Модели и API</h2>
        <p class="sub">Источник поиска и модель анализа теперь разделены. Для DuckDuckGo используется внешний веб-поиск плюс LLM-анализ. Для Perplexity и OpenAI Search идеи могут собираться сразу через их API.</p>
        <form method="post" action="/settings/models">
          <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
          <div class="field-grid">
            <div class="field">
              <label for="search_source_provider">Источник веб-поиска</label>
              <select id="search_source_provider" name="search_source_provider">
                {% for value, title in search_sources %}
                <option value="{{ value }}" {% if settings.models.search.source_provider == value %}selected{% endif %}>{{ title }}</option>
                {% endfor %}
              </select>
              <div class="hint">Сейчас базовый источник - DuckDuckGo. Позже можно переключиться на Perplexity API.</div>
            </div>
            <div class="field">
              <label for="search_provider">LLM для анализа поиска</label>
              <select id="search_provider" name="search_provider">
                {% for value, title in providers %}
                <option value="{{ value }}" {% if settings.models.search.provider == value %}selected{% endif %}>{{ title }}</option>
                {% endfor %}
              </select>
            </div>
            <div class="field">
              <label for="search_model">Модель анализа</label>
              <input id="search_model" type="text" name="search_model" value="{{ settings.models.search.model }}">
            </div>
            <div class="field">
              <label for="search_base_url">Endpoint / base URL для модели анализа</label>
              <input id="search_base_url" type="text" name="search_base_url" value="{{ settings.models.search.base_url }}">
            </div>
            <div class="field">
              <label for="search_api_key">API key для модели анализа</label>
              <input id="search_api_key" type="password" name="search_api_key" value="" placeholder="Оставь пустым, чтобы не менять">
              <div class="hint">Статус: {{ "ключ задан" if secret_statuses.search_model_api_key else "ключ не задан" }}</div>
            </div>
            <div class="field">
              <label for="search_timeout_sec">Таймаут анализа, сек</label>
              <input id="search_timeout_sec" type="number" name="search_timeout_sec" min="30" value="{{ settings.models.search.timeout_sec }}">
            </div>
            <div class="field">
              <label class="check">
                <input type="checkbox" name="clear_search_api_key">
                <span>Очистить ключ модели анализа</span>
              </label>
            </div>

            <div class="field full" style="margin-top:8px;">
              <label class="check">
                <input type="checkbox" name="writer_enabled" {% if settings.models.writer.enabled %}checked{% endif %}>
                <span>Включить AI-редактор для итогового PDF</span>
              </label>
            </div>

            <div class="field">
              <label for="writer_provider">Writer provider</label>
              <select id="writer_provider" name="writer_provider">
                {% for value, title in providers %}
                <option value="{{ value }}" {% if settings.models.writer.provider == value %}selected{% endif %}>{{ title }}</option>
                {% endfor %}
              </select>
            </div>
            <div class="field">
              <label for="writer_model">Writer model</label>
              <input id="writer_model" type="text" name="writer_model" value="{{ settings.models.writer.model }}">
            </div>
            <div class="field">
              <label for="writer_base_url">Writer endpoint / base URL</label>
              <input id="writer_base_url" type="text" name="writer_base_url" value="{{ settings.models.writer.base_url }}">
            </div>
            <div class="field">
              <label for="writer_api_key">Writer API key</label>
              <input id="writer_api_key" type="password" name="writer_api_key" value="" placeholder="Оставь пустым, чтобы не менять">
              <div class="hint">Статус: {{ "ключ задан" if secret_statuses.writer_model_api_key else "ключ не задан" }}</div>
            </div>
            <div class="field">
              <label for="writer_timeout_sec">Writer timeout, sec</label>
              <input id="writer_timeout_sec" type="number" name="writer_timeout_sec" min="30" value="{{ settings.models.writer.timeout_sec }}">
            </div>
            <div class="field">
              <label class="check">
                <input type="checkbox" name="clear_writer_api_key">
                <span>Очистить writer key</span>
              </label>
            </div>
            <div class="field full">
              <label for="writer_style_prompt">Редакторский стиль</label>
              <textarea id="writer_style_prompt" name="writer_style_prompt">{{ settings.models.writer.style_prompt }}</textarea>
            </div>
            <div class="field">
              <label for="fallback_perplexity_api_key">Perplexity API key</label>
              <input id="fallback_perplexity_api_key" type="password" name="fallback_perplexity_api_key" value="" placeholder="Оставь пустым, чтобы не менять">
              <div class="hint">Статус: {{ "ключ задан" if secret_statuses.perplexity_api_key else "ключ не задан" }}</div>
            </div>
            <div class="field">
              <label for="fallback_openai_api_key">OpenAI key / Search key</label>
              <input id="fallback_openai_api_key" type="password" name="fallback_openai_api_key" value="" placeholder="Оставь пустым, чтобы не менять">
              <div class="hint">Статус: {{ "ключ задан" if secret_statuses.openai_api_key else "ключ не задан" }}</div>
            </div>
            <div class="field">
              <label class="check">
                <input type="checkbox" name="clear_fallback_perplexity_api_key">
                <span>Очистить Perplexity key</span>
              </label>
            </div>
            <div class="field">
              <label class="check">
                <input type="checkbox" name="clear_fallback_openai_api_key">
                <span>Очистить OpenAI key</span>
              </label>
            </div>
          </div>
          <div class="actions">
            <button type="submit">Сохранить model settings</button>
          </div>
        </form>
      </section>

      <section class="card half">
        <h2>Последние PDF</h2>
        <p class="sub">Preview и боевые выпуски лежат в общей папке reports, так что можно быстро открыть и сравнить версии.</p>
        <div class="list">
          {% for report in recent_reports %}
          <div class="row">
            <div>
              <div><strong>{{ report.name }}</strong></div>
              <div class="hint">{{ report.modified_at }} · {{ report.size_kb }} KB</div>
            </div>
            <a class="btn-link secondary" href="/reports/{{ report.name }}" target="_blank">Открыть</a>
          </div>
          {% else %}
          <div class="row"><div>PDF пока нет.</div></div>
          {% endfor %}
        </div>
      </section>

      <section class="card half">
        <h2>История выпусков</h2>
        <p class="sub">Короткий обзор последних issue из журнала идей.</p>
        <div class="list">
          {% for issue in recent_issues %}
          <div class="row">
            <div>
              <div><strong>Выпуск #{{ "%03d"|format(issue.issue) }}</strong></div>
              <div class="hint">{{ issue.date }}{% if issue.category %} · {{ issue.category }}{% endif %}</div>
            </div>
          </div>
          {% else %}
          <div class="row"><div>История пока пустая.</div></div>
          {% endfor %}
        </div>
      </section>

      <section class="card half">
        <h2>Память Тем</h2>
        <p class="sub">Это мягкий накопитель последних боевых тем. Он не режет всю широкую категорию целиком, а помогает не возвращаться к почти тем же формулировкам идей слишком быстро.</p>
        <div class="hint">Сейчас окно памяти: последние {{ settings.topic_memory.recent_issue_window }} выпусков{% if not settings.topic_memory.enabled %} · память отключена{% endif %}.</div>
        <div class="list" style="margin-top:12px;">
          {% for topic in recent_topics %}
          <div class="row">
            <div>
              <div><strong>{{ topic.name or topic.signature }}</strong></div>
              <div class="hint">#{{ "%03d"|format(topic.issue) }} · {{ topic.date }}{% if topic.category %} · {{ topic.category }}{% endif %}</div>
            </div>
          </div>
          {% else %}
          <div class="row"><div>Память тем пока пуста.</div></div>
          {% endfor %}
        </div>
        <form method="post" action="/memory/clear" style="margin-top:12px;">
          <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
          <button type="submit" class="ghost">Очистить память тем</button>
        </form>
      </section>

      <section class="card half">
        <h2>Сброс к baseline</h2>
        <p class="sub">Кнопка возвращает runtime settings к зафиксированному исходному состоянию проекта. Это безопасный откат к текущей рабочей базе без ручной правки файлов.</p>
        <div class="hint">Baseline web search: {{ baseline.models.search.source_provider }} · analysis: {{ baseline.models.search.provider }} / {{ baseline.models.search.model }} · writer: {{ "on" if baseline.models.writer.enabled else "off" }}</div>
        <form method="post" action="/settings/reset" style="margin-top:12px;">
          <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
          <button type="submit" class="warn">Вернуть состояние к исходному</button>
        </form>
      </section>

      <section class="card half">
        <h2>Последний лог</h2>
        <p class="sub">Хвост последнего лога помогает понять, где сломался запуск, не залезая сразу в файлы проекта.</p>
        <div class="mono">{{ logs_tail }}</div>
      </section>
    </div>
  </div>
</body>
</html>
"""


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=PANEL_PORT, debug=False)

"""Offline regression tests: synthetic secrets, mocked providers and Flask client."""

from contextlib import ExitStack
import copy
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

# Do not let imports cache the operator's actual credentials.
with patch.dict(os.environ, {}, clear=True):
    import admin_panel
    import requests
    import scheduler_runtime
    import secrets_manager
    import telegram_sender
    from safe_errors import public_error


class PublicErrorTests(unittest.TestCase):
    def test_public_code_does_not_stringify_exception(self):
        class PrivateError(Exception):
            def __str__(self):
                raise AssertionError("Exception text must not be inspected")
        self.assertEqual(public_error(PrivateError("synthetic-sensitive-value")), "OPERATION_FAILED")
        self.assertEqual(public_error(ValueError("synthetic-sensitive-value")), "INVALID_DATA")
        self.assertEqual(public_error(PermissionError("synthetic-sensitive-value")), "PERMISSION_DENIED")
        self.assertEqual(public_error(requests.ConnectionError("synthetic-sensitive-value")), "IO_ERROR")


class SecretStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.path = self.root / ".env"
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(secrets_manager, "ENV_PATH", self.path))
        self.stack.enter_context(patch.dict(os.environ, {}, clear=True))

    def test_missing_read_is_side_effect_free_and_unknown_keys_are_denied(self):
        self.assertEqual(secrets_manager.read_env_map(), {})
        self.assertEqual(secrets_manager.get_secret("OPENAI_API_KEY"), "")
        self.assertFalse(self.path.exists())
        for operation in (lambda: secrets_manager.get_secret("PATH"),
                          lambda: secrets_manager.set_secret("PATH", "synthetic"),
                          lambda: secrets_manager.clear_secret("PATH")):
            with self.assertRaises(ValueError):
                operation()
        self.assertFalse(self.path.exists())

    def test_private_write_preserves_other_values_and_literal_interpolation(self):
        self.path.write_text("IDEAS_COUNT_MIN='2'\nOPENAI_API_KEY='${UNRELATED}'\n", encoding="utf-8")
        os.environ["UNRELATED"] = "synthetic-unrelated-secret"
        self.assertEqual(secrets_manager.get_secret("OPENAI_API_KEY"), "${UNRELATED}")
        value = "synthetic-quote'and\\slash"
        secrets_manager.set_secret("SEARCH_MODEL_API_KEY", value)
        self.assertEqual(secrets_manager.get_secret("SEARCH_MODEL_API_KEY"), value)
        self.assertEqual(secrets_manager.read_env_map()["IDEAS_COUNT_MIN"], "2")
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertFalse(list(self.root.glob(".env-*.tmp")))

    def test_cleared_secret_cannot_reappear_from_environment_or_default(self):
        os.environ["OPENAI_API_KEY"] = "synthetic-inherited"
        secrets_manager.clear_secret("OPENAI_API_KEY")
        self.assertNotIn("OPENAI_API_KEY", os.environ)
        os.environ["OPENAI_API_KEY"] = "synthetic-restored-environment"
        self.assertEqual(secrets_manager.get_secret("OPENAI_API_KEY", "synthetic-stale-default"), "")
        self.assertFalse(secrets_manager.has_secret("OPENAI_API_KEY"))

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink creation unavailable")
    def test_file_and_directory_symlinks_are_refused_without_touching_target(self):
        target = self.root / "outside.env"
        target.write_text("OPENAI_API_KEY='synthetic-outside'\n", encoding="utf-8")
        original = target.read_bytes()
        self.path.symlink_to(target)
        for operation in (secrets_manager.read_env_map,
                          lambda: secrets_manager.set_secret("OPENAI_API_KEY", "synthetic-new"),
                          lambda: secrets_manager.clear_secret("OPENAI_API_KEY")):
            with self.assertRaises(ValueError):
                operation()
        self.assertEqual(target.read_bytes(), original)
        self.path.unlink()
        linked_dir = self.root / "linked"
        linked_dir.symlink_to(self.root, target_is_directory=True)
        with patch.object(secrets_manager, "ENV_PATH", linked_dir / "outside.env"):
            with self.assertRaises(ValueError):
                secrets_manager.read_env_map()
        self.assertEqual(target.read_bytes(), original)

    @unittest.skipUnless(hasattr(os, "link"), "hard links unavailable")
    def test_hard_link_is_not_read_or_modified(self):
        target = self.root / "outside.env"
        target.write_text("OPENAI_API_KEY='synthetic-outside'\n", encoding="utf-8")
        os.link(target, self.path)
        with self.assertRaises(ValueError):
            secrets_manager.read_env_map()
        self.assertEqual(target.read_text(), "OPENAI_API_KEY='synthetic-outside'\n")

    def test_failed_clear_propagates_and_keeps_prior_value(self):
        secrets_manager.set_secret("OPENAI_API_KEY", "synthetic-before")
        old = self.path.read_bytes()
        with patch.object(secrets_manager.os, "replace", side_effect=PermissionError("synthetic-sensitive-value")):
            with self.assertRaises(PermissionError):
                secrets_manager.clear_secret("OPENAI_API_KEY")
        self.assertEqual(self.path.read_bytes(), old)
        self.assertEqual(os.environ["OPENAI_API_KEY"], "synthetic-before")
        self.assertFalse(list(self.root.glob(".env-*.tmp")))


class TelegramSecurityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.pdf = Path(self.tmp.name).resolve() / "demo.pdf"
        self.pdf.write_bytes(b"synthetic-pdf")
        self.settings = {"telegram": {"chat_id": "synthetic-chat"}}
        self.key_patch = patch.object(telegram_sender, "get_secret", return_value="synthetic-bot-key")
        self.key_patch.start()
        self.addCleanup(self.key_patch.stop)

    def test_credential_bearing_request_exceptions_are_not_logged(self):
        secret = "synthetic-sensitive-marker"
        exc = requests.ConnectionError("Request URL /bot" + secret + "/sendDocument failed")
        with patch.object(telegram_sender.requests, "post", side_effect=exc), self.assertLogs(telegram_sender.logger, "ERROR") as logs:
            self.assertFalse(telegram_sender.send_pdf_to_telegram(str(self.pdf), [], 1, self.settings))
            self.assertFalse(telegram_sender.send_text_message("demo", self.settings))
        self.assertNotIn(secret, "\n".join(logs.output))
        self.assertNotIn("sendDocument", "\n".join(logs.output))
        self.assertIn("IO_ERROR", "\n".join(logs.output))

    def test_http_error_body_is_not_read(self):
        class ErrorResponse:
            status_code = 401
            @property
            def text(self):
                raise AssertionError("Body must not be accessed")
        with patch.object(telegram_sender.requests, "post", return_value=ErrorResponse()), self.assertLogs(telegram_sender.logger, "ERROR") as logs:
            self.assertFalse(telegram_sender.send_pdf_to_telegram(str(self.pdf), [], 1, self.settings))
        self.assertIn("HTTP 401", "\n".join(logs.output))
        self.assertNotIn("OPERATION_FAILED", "\n".join(logs.output))

    def test_caption_escapes_untrusted_fields_and_preserves_valid_markup(self):
        ideas = [{"name": '<img src="example"> <b>demo</b> &', "category": "<script>&", "scores": {"test": 1}}]
        caption = telegram_sender._build_caption(ideas, 1)
        self.assertIn("&lt;img", caption)
        self.assertNotIn("<img", caption)
        self.assertNotIn("<script", caption)
        ET.fromstring("<caption>" + caption + "</caption>")
        large = [{"name": "<>&" * 1000, "category": "<>&" * 1000} for _ in range(10)]
        caption = telegram_sender._build_caption(large, 1)
        self.assertLessEqual(len(caption), 1024)
        ET.fromstring("<caption>" + caption + "</caption>")
        astral = [{"name": "😀" * 1000, "category": "🌍" * 1000} for _ in range(3)]
        caption = telegram_sender._build_caption(astral, 1)
        self.assertLessEqual(len(caption.encode("utf-16-le")) // 2, 1024)
        ET.fromstring("<caption>" + caption + "</caption>")

    def test_free_text_is_literal_and_telegram_ok_is_required(self):
        response = Mock(status_code=200)
        response.json.return_value = {"ok": True}
        with patch.object(telegram_sender.requests, "post", return_value=response) as post:
            self.assertTrue(telegram_sender.send_text_message("<b>literal</b>&", self.settings))
        self.assertEqual(post.call_args.kwargs["data"]["text"], "&lt;b&gt;literal&lt;/b&gt;&amp;")
        response.json.return_value = {"ok": False}
        with patch.object(telegram_sender.requests, "post", return_value=response):
            self.assertFalse(telegram_sender.send_text_message("demo", self.settings))


def dashboard_context():
    settings = {
        "telegram": {"chat_id": "", "test_chat_id": ""},
        "models": {
            "search": {"source_provider": "duckduckgo", "provider": "ollama", "model": "synthetic", "base_url": "", "timeout_sec": 30},
            "writer": {"enabled": False, "provider": "ollama", "model": "synthetic", "base_url": "", "timeout_sec": 30, "style_prompt": ""},
        },
        "digest": {"ideas_count_min": 1, "ideas_count_max": 2, "cover_title": "DEMO", "brand_name": "DEMO", "cover_subtitle": "", "focus_line": "", "footer_brand": "", "disclaimer": ""},
        "themes": {"mode": "rotate", "enabled_theme_ids": [], "fixed_theme_id": ""},
        "topic_memory": {"enabled": False, "recent_issue_window": 5},
        "schedule": {"enabled": False, "frequency": "daily", "hour": 10, "minute": 45, "interval_hours": 24},
    }
    return {"settings": settings, "baseline": copy.deepcopy(settings), "secret_statuses": {key: False for key in secrets_manager.SECRET_ENV_KEYS},
            "scheduler": {"next_hint": "", "state": {"last_status": "idle", "last_run_at": "", "last_error": ""}, "running": False},
            "themes": [], "recent_reports": [], "recent_issues": [], "recent_topics": [], "logs_tail": "No logs"}


class LocalPanelSecurityTests(unittest.TestCase):
    BASE = "http://127.0.0.1:8787"
    TOKEN = "synthetic-csrf-token-for-tests"

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(admin_panel.app.config, {"TESTING": True, "CSRF_TOKEN": self.TOKEN}))
        self.stack.enter_context(patch.object(requests.sessions.Session, "request", side_effect=AssertionError("Network is disabled in these tests")))
        self.client = admin_panel.app.test_client()

    def post(self, path, data=None, headers=None, base=None):
        return self.client.post(path, base_url=base or self.BASE, data=data or {}, headers=headers or {})

    def test_get_contains_csrf_forms_without_scheduler_or_network(self):
        with patch.object(admin_panel.bot_services, "load_dashboard_context", return_value=dashboard_context()), patch.object(admin_panel.scheduler_runtime, "start_background_scheduler") as start:
            response = self.client.get("/", base_url=self.BASE)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data.count(b'name="csrf_token"'), 9)
        self.assertIn(self.TOKEN.encode(), response.data)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        start.assert_not_called()

    def test_every_mutating_route_requires_token_even_with_local_origin(self):
        functions = ["ping_bot", "send_group_message", "run_digest", "update_digest_settings", "update_telegram_settings", "clear_topic_memory", "update_model_settings", "update_schedule_settings", "reset_settings_to_baseline"]
        with ExitStack() as stack:
            mocks = [stack.enter_context(patch.object(admin_panel.bot_services, name)) for name in functions]
            routes = [rule.rule for rule in admin_panel.app.url_map.iter_rules() if "POST" in rule.methods]
            self.assertEqual(len(routes), 9)
            for route in routes:
                with self.subTest(route=route):
                    response = self.post(route, headers={"Origin": self.BASE, "Sec-Fetch-Site": "same-origin"})
                    self.assertEqual(response.status_code, 403)
            for mocked in mocks:
                mocked.assert_not_called()

    def test_bad_host_origin_fetch_site_and_token_do_not_call_action(self):
        cases = [
            ({"Host": "untrusted.invalid:8787"}, self.TOKEN),
            ({"Host": "localhost:8788"}, self.TOKEN),
            ({"Origin": "https://untrusted.invalid"}, self.TOKEN),
            ({"Origin": "http://127.0.0.1:8788"}, self.TOKEN),
            ({"Origin": "http://localhost:8787"}, self.TOKEN),
            ({"Origin": "null"}, self.TOKEN),
            ({"Origin": self.BASE, "Sec-Fetch-Site": "cross-site"}, self.TOKEN),
            ({"Origin": self.BASE, "Sec-Fetch-Site": "same-site"}, self.TOKEN),
            ({"Origin": self.BASE}, "wrong-token"),
        ]
        with patch.object(admin_panel.bot_services, "ping_bot", return_value=True) as action:
            for headers, token in cases:
                with self.subTest(headers=headers):
                    self.assertEqual(self.post("/actions/ping", {"csrf_token": token}, headers).status_code, 403)
            action.assert_not_called()

    def test_each_loopback_name_accepts_its_own_origin_and_token(self):
        with patch.object(admin_panel.bot_services, "send_group_message", return_value=True) as action:
            for base in (self.BASE, "http://localhost:8787"):
                response = self.post("/actions/message", {"csrf_token": self.TOKEN, "message_text": "synthetic message"}, {"Origin": base, "Sec-Fetch-Site": "same-origin"}, base)
                self.assertEqual(response.status_code, 302)
            self.assertEqual(action.call_count, 2)

    def test_invalid_mode_and_count_do_not_become_live_runs(self):
        with patch.object(admin_panel.bot_services, "run_digest") as run:
            for mode, count in [("unrecognized", "0"), ("preview", "invalid"), ("full", "999"), ("full", "-1")]:
                response = self.post("/actions/run", {"csrf_token": self.TOKEN, "mode": mode, "count_override": count})
                self.assertEqual(response.status_code, 302)
                self.assertIn("INVALID_DATA", response.headers["Location"])
            run.assert_not_called()

    def test_unsafe_exceptions_are_not_returned_in_redirects_or_json(self):
        marker = "synthetic-sensitive-marker"
        with patch.object(admin_panel.bot_services, "run_digest", side_effect=RuntimeError(marker)):
            response = self.post("/actions/run", {"csrf_token": self.TOKEN, "mode": "preview"})
            self.assertEqual(response.status_code, 302)
            self.assertNotIn(marker, response.headers["Location"])
            self.assertIn("OPERATION_FAILED", response.headers["Location"])
        with patch.object(admin_panel.bot_services, "ping_bot", side_effect=RuntimeError(marker)), self.assertLogs(admin_panel.logger, "ERROR") as logs:
            response = self.post("/actions/ping", {"csrf_token": self.TOKEN})
        self.assertEqual(response.status_code, 500)
        self.assertNotIn(marker, response.get_data(as_text=True))
        self.assertNotIn(marker, "\n".join(logs.output))

    def test_scheduler_starts_only_after_an_explicit_enable_action(self):
        with patch.object(admin_panel.scheduler_runtime, "start_background_scheduler") as start:
            with patch.object(admin_panel.bot_services, "update_schedule_settings", return_value={"schedule": {"enabled": False}}):
                self.post("/settings/schedule", {"csrf_token": self.TOKEN})
                start.assert_not_called()
            with patch.object(admin_panel.bot_services, "update_schedule_settings", return_value={"schedule": {"enabled": True}}):
                self.post("/settings/schedule", {"csrf_token": self.TOKEN})
                start.assert_called_once_with(admin_panel.bot_services.run_scheduled_digest)


class SchedulerErrorTests(unittest.TestCase):
    def test_error_state_and_logs_do_not_store_exception_text(self):
        settings = {"schedule": {"enabled": True, "frequency": "daily", "hour": 0, "minute": 0}}
        marker = "synthetic-sensitive-marker"
        with patch.object(scheduler_runtime, "get_settings", return_value=settings), patch.object(scheduler_runtime, "load_scheduler_state", return_value=scheduler_runtime._default_state()), patch.object(scheduler_runtime, "save_scheduler_state"), self.assertLogs(scheduler_runtime.logger, "ERROR") as logs:
            state = scheduler_runtime.run_scheduler_tick(Mock(side_effect=RuntimeError(marker)))
        self.assertEqual(state["last_status"], "error")
        self.assertEqual(state["last_error"], "OPERATION_FAILED")
        self.assertNotIn(marker, "\n".join(logs.output))

    def test_legacy_error_is_not_reflected_by_dashboard_snapshot(self):
        with patch.object(scheduler_runtime, "get_settings", return_value={"schedule": {"enabled": False}}), patch.object(scheduler_runtime, "load_scheduler_state", return_value={"last_error": "synthetic-old-error-secret"}):
            snapshot = scheduler_runtime.get_scheduler_snapshot()
        self.assertEqual(snapshot["state"]["last_error"], "OPERATION_FAILED")


if __name__ == "__main__":
    unittest.main()

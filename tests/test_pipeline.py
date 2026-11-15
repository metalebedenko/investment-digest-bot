"""Offline orchestration checks; transports and PDF rendering are replaced explicitly."""

from contextlib import ExitStack, redirect_stderr
from pathlib import Path
import io
import tempfile
import unittest
from unittest.mock import patch

import requests

import bot_services
import config
import run_bot


def idea(name="Synthetic sample"):
    return {"name": name, "summary": "Synthetic description for a test.",
            "category": "Demo", "sources": [], "scores": {"risk": 5},
            "localization": {}}


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.object(requests.sessions.Session, "request",
                                             side_effect=AssertionError("Network is forbidden in this test")))
        self.stack.enter_context(patch.object(config, "REPORTS_DIR", self.directory))
        self.pdf = self.stack.enter_context(patch.object(
            bot_services.pdf_generator, "generate_pdf", side_effect=self._fake_pdf))
        self.sender = self.stack.enter_context(patch.object(
            bot_services.telegram_sender, "send_pdf_to_telegram", return_value=True))
        self.writer = self.stack.enter_context(patch.object(
            bot_services.editorial_ai, "build_editorial_package", return_value=None))
        self.search = self.stack.enter_context(patch.object(
            bot_services.generic_searcher, "search_ideas", return_value=[idea()]))
        self.state = {}
        values = {"get_next_issue_number": 7,
                  "get_runtime_theme": config.get_visual_theme("light_editorial"),
                  "get_sent_idea_names": [], "get_sent_topic_signatures": []}
        for name in ("ensure_dirs", "get_next_issue_number", "get_runtime_theme",
                     "get_sent_idea_names", "get_sent_topic_signatures",
                     "add_ideas_to_log", "add_issue_topics_to_memory", "save_current_theme"):
            self.state[name] = self.stack.enter_context(patch.object(
                bot_services.state_manager, name, return_value=values.get(name)))
        self.ensure = self.stack.enter_context(patch.object(bot_services, "ensure_settings_files"))
        self.settings = self.stack.enter_context(patch.object(bot_services, "get_settings", return_value={
            "digest": {"ideas_count_min": 1, "ideas_count_max": 1},
            "models": {"writer": {"enabled": True}},
            "topic_memory": {"enabled": True, "recent_issue_window": 5},
        }))

    @staticmethod
    def _fake_pdf(**kwargs):
        path = Path(kwargs["output_path"])
        path.write_bytes(b"synthetic-renderer-test")
        return str(path)

    def assert_no_sent_state(self):
        for name in ("add_ideas_to_log", "add_issue_topics_to_memory", "save_current_theme"):
            self.state[name].assert_not_called()

    def test_demo_ignores_live_settings_history_writer_and_delivery(self):
        self.settings.side_effect = AssertionError("Demo read live settings")
        self.ensure.side_effect = AssertionError("Demo initialized live settings")
        self.writer.side_effect = AssertionError("Demo contacted writer")
        self.search.side_effect = AssertionError("Demo contacted search")
        self.sender.side_effect = AssertionError("Demo contacted Telegram")
        with patch.object(bot_services.secrets_manager, "get_secret",
                          side_effect=AssertionError("Demo read a secret")):
            result = bot_services.run_digest(demo=True)
        self.assertTrue(result["synthetic"])
        self.assertFalse(result["telegram_sent"])
        self.assertFalse(result["editorial_used"])
        self.assertEqual(result["issue_number"], 1)
        self.assertEqual(result["ideas_count"], 5)
        self.assertTrue(Path(result["pdf_path"]).name.startswith("demo_"))
        self.assertTrue(Path(result["pdf_path"]).is_file())
        kwargs = self.pdf.call_args.kwargs
        self.assertTrue(kwargs["settings"]["digest"]["demo"])
        self.assertIn("DEMO", kwargs["settings"]["digest"]["footer_brand"])
        for record in kwargs["ideas"]:
            self.assertTrue(all("Синтетический" in source for source in record["sources"]))
        for call in self.state.values():
            call.assert_not_called()
        self.settings.assert_not_called()
        self.ensure.assert_not_called()

    def test_successful_live_delivery_commits_the_selected_issue(self):
        result = bot_services.run_digest(count_override=1)
        self.assertFalse(result["synthetic"])
        self.assertTrue(result["telegram_sent"])
        self.sender.assert_called_once()
        self.state["add_ideas_to_log"].assert_called_once()
        self.state["add_issue_topics_to_memory"].assert_called_once()
        self.state["save_current_theme"].assert_called_once()
        self.assertEqual(self.state["add_ideas_to_log"].call_args.args[1], 7)

    def test_failed_delivery_does_not_commit_sent_state(self):
        self.sender.return_value = False
        with self.assertRaises(RuntimeError):
            bot_services.run_digest(count_override=1)
        self.pdf.assert_called_once()
        self.assert_no_sent_state()

    def test_preview_and_pdf_only_do_not_send_or_commit(self):
        for flags in ({"preview": True}, {"pdf_only": True}):
            with self.subTest(flags=flags):
                result = bot_services.run_digest(count_override=1, **flags)
                self.assertFalse(result["telegram_sent"])
                self.sender.assert_not_called()
                self.assert_no_sent_state()

    def test_source_failure_does_not_render_or_send(self):
        self.search.side_effect = RuntimeError("simulated acquisition failure")
        with self.assertRaises(RuntimeError):
            bot_services.run_digest(count_override=1)
        self.pdf.assert_not_called()
        self.sender.assert_not_called()
        self.assert_no_sent_state()

    def test_malformed_selected_idea_fails_before_writer_and_renderer(self):
        self.search.return_value = [{"name": "Invalid", "summary": ["wrong shape"]}]
        with self.assertRaises(ValueError):
            bot_services.run_digest(count_override=1)
        self.writer.assert_not_called()
        self.pdf.assert_not_called()
        self.sender.assert_not_called()
        self.assert_no_sent_state()

    def test_renderer_failure_does_not_send_or_commit(self):
        self.pdf.side_effect = ValueError("synthetic rendering failure")
        with self.assertRaises(ValueError):
            bot_services.run_digest(count_override=1)
        self.sender.assert_not_called()
        self.assert_no_sent_state()

    def test_invalid_count_is_rejected_before_any_live_state(self):
        for value in (-1, 11, True, "2"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                bot_services.run_digest(count_override=value)
        self.settings.assert_not_called()
        self.search.assert_not_called()

    def test_cli_rejects_mixed_demo_and_telegram_test(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            run_bot.parse_args(["--demo", "--test-tg"])
        self.assertEqual(raised.exception.code, 2)

    def test_cli_rejects_count_outside_bounded_range(self):
        for value in ("-1", "11"):
            with self.subTest(value=value), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                run_bot.parse_args(["--count", value])


if __name__ == "__main__":
    unittest.main()

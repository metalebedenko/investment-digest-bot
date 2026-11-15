"""Search boundaries and credential lifetime; no remote service is called."""

from pathlib import Path
import importlib
import json
import math
import os
import tempfile
import unittest
from unittest.mock import patch

import requests

import config
import editorial_ai
import generic_searcher
from idea_validation import validate_ideas
import searcher
import searcher_ollama
import secrets_manager


def valid_idea():
    return {"name": "Synthetic example", "summary": "A synthetic test description.",
            "sources": ["https://example.org/reference"], "scores": {"risk": 5}}


class SearchTests(unittest.TestCase):
    def setUp(self):
        guard = patch.object(requests.sessions.Session, "request",
                             side_effect=AssertionError("Network is forbidden in this test"))
        guard.start()
        self.addCleanup(guard.stop)

    def test_live_provider_exhaustion_cannot_return_demo_data(self):
        with patch.object(searcher, "_get_fallback_keys", return_value=("", "")), \
             patch.object(searcher, "search_with_duckduckgo", side_effect=RuntimeError("offline")), \
             patch.object(searcher, "get_demo_ideas", side_effect=AssertionError("Synthetic fallback")) as demo:
            with self.assertRaises(RuntimeError):
                searcher.search_ideas([], count=1)
            demo.assert_not_called()

    def test_empty_acquisition_does_not_ask_model_to_invent_research(self):
        with patch.object(searcher_ollama, "_gather_ddg_context", return_value=""), \
             patch.object(generic_searcher, "chat_completion") as llm:
            with self.assertRaises(RuntimeError):
                generic_searcher._search_with_configured_model({}, [], set(), 1)
            llm.assert_not_called()

    def test_generic_rejects_excessive_count_before_search(self):
        with patch.object(searcher_ollama, "_gather_ddg_context") as acquisition:
            with self.assertRaises(ValueError):
                generic_searcher.search_ideas({}, count=11)
            acquisition.assert_not_called()

    def test_cleared_keys_are_not_resurrected_from_imported_config(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(secrets_manager, "ENV_PATH", Path(tmp) / ".env"), \
             patch.dict(os.environ, {"PERPLEXITY_API_KEY": "synthetic-key-for-lifetime-test",
                                     "OPENAI_API_KEY": "synthetic-other-test-key"}, clear=True), \
             patch.object(config, "PERPLEXITY_API_KEY", "synthetic-key-for-lifetime-test", create=True), \
             patch.object(config, "OPENAI_API_KEY", "synthetic-other-test-key", create=True):
            importlib.reload(searcher)
            self.assertEqual(searcher._get_fallback_keys({}),
                             ("synthetic-key-for-lifetime-test", "synthetic-other-test-key"))
            secrets_manager.clear_secret("PERPLEXITY_API_KEY")
            secrets_manager.clear_secret("OPENAI_API_KEY")
            self.assertEqual(searcher._get_fallback_keys({}), ("", ""))
            self.assertEqual(searcher._get_fallback_keys(), ("", ""))
        importlib.reload(searcher)

    def test_mixed_or_invalid_provider_records_do_not_pass_json_parser(self):
        for records in ([valid_idea(), 3], [valid_idea(), {"name": "bad"}],
                        [{**valid_idea(), "scores": {"risk": "high"}}]):
            with self.subTest(records=records):
                self.assertEqual(searcher._parse_ideas_json(json.dumps(records)), [])

    def test_validation_rejects_unsafe_shapes_before_rendering(self):
        bad_records = [None, {}, [], ["not an object"],
                       [{**valid_idea(), "sources": "https://example.org"}],
                       [{**valid_idea(), "scores": {"risk": True}}],
                       [{**valid_idea(), "scores": {"risk": math.nan}}],
                       [{**valid_idea(), "scores": {"risk": 11}}],
                       [{**valid_idea(), "scores": {"invented_score": 5}}],
                       [valid_idea()] * 11]
        for records in bad_records:
            with self.subTest(records=records), self.assertRaises(ValueError):
                validate_ideas(records)

    def test_validation_preserves_values_and_does_not_mutate_input(self):
        record = valid_idea()
        before = json.dumps(record, sort_keys=True)
        selected = validate_ideas([record])
        self.assertEqual(json.dumps(record, sort_keys=True), before)
        self.assertEqual(selected[0]["scores"], record["scores"])
        self.assertEqual(selected[0]["sources"], record["sources"])
        self.assertIsNot(selected[0]["scores"], record["scores"])

    def test_model_failure_logs_do_not_expose_exception_payload(self):
        marker = "PRIVATE_SENTINEL_DO_NOT_LOG"
        with patch.object(searcher, "_get_fallback_keys", return_value=("", "")), \
             patch.object(searcher, "search_with_duckduckgo", side_effect=RuntimeError(marker)), \
             self.assertLogs("searcher", level="ERROR") as captured:
            with self.assertRaises(RuntimeError):
                searcher.search_ideas([], count=1)
        self.assertNotIn(marker, "\n".join(captured.output))

    def test_unparseable_model_output_is_not_copied_to_logs(self):
        marker = "PRIVATE_SENTINEL_MODEL_CONTENT"
        with self.assertLogs("searcher_ollama", level="WARNING") as captured:
            self.assertEqual(searcher_ollama._parse_ideas(marker), [])
        self.assertNotIn(marker, "\n".join(captured.output))

    def test_optional_writer_rejects_incompatible_display_shapes(self):
        for value in ({"cover": "wrong"}, {"ideas": [3]},
                      {"executive_summary": ["wrong"]},
                      {"top_picks": [{"name": "sample", "comment": {}}]}):
            with self.subTest(value=value):
                self.assertIsNone(editorial_ai._parse_editorial_json(json.dumps(value)))
        self.assertEqual(editorial_ai._parse_editorial_json('{"executive_summary":"Demo"}'),
                         {"executive_summary": "Demo"})


if __name__ == "__main__":
    unittest.main()

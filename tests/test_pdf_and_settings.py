import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import config
import pdf_generator
import runtime_settings
import searcher
import secrets_manager


class PdfAndSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.env_patch = patch.object(secrets_manager, 'ENV_PATH', self.root / '.env')
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.network = patch('requests.sessions.Session.request', side_effect=AssertionError('Unexpected HTTP'))
        self.network.start()
        self.addCleanup(self.network.stop)
        self.idea = copy.deepcopy(searcher.get_demo_ideas()[0])

    def test_external_markup_remains_literal_across_report_fields(self):
        marker = '<img src="file:///not-a-readable-resource"/> & <b>literal</b>'
        self.idea.update(name=marker, category=marker, summary=marker, sources=[marker])
        theme = config.get_visual_theme('light_editorial')
        font = pdf_generator._register_fonts()
        style = pdf_generator._styles(font, pdf_generator._palette(theme))
        card = pdf_generator._idea_card(self.idea, 1, 1, style, font, None, pdf_generator._palette(theme))
        paragraphs = [x for x in card[0]._content if isinstance(x, pdf_generator.Paragraph)]
        plain = '\n'.join(x.getPlainText() for x in paragraphs)
        self.assertIn('<img src=', plain)
        self.assertIn('<b>literal</b>', plain)
        with patch.object(pdf_generator, '_register_fonts', return_value=font), \
             patch('reportlab.lib.utils.open_for_read', side_effect=AssertionError('Unexpected external resource')):
            output = self.root / 'literal.pdf'
            pdf_generator.generate_pdf([self.idea], 1, theme, str(output), settings={'digest': {'cover_title': marker, 'demo': True}})
        self.assertTrue(output.read_bytes().startswith(b'%PDF-'))

    def test_card_error_fails_without_overwriting_existing_output(self):
        output = self.root / 'existing.pdf'
        output.write_bytes(b'previous-valid-output')
        with patch.object(pdf_generator, '_idea_card', side_effect=ValueError('bad card')):
            with self.assertRaises(ValueError):
                pdf_generator.generate_pdf([self.idea], 1, config.get_visual_theme('light_editorial'), str(output))
        self.assertEqual(output.read_bytes(), b'previous-valid-output')

    def test_invalid_idea_fails_before_pdf_is_written(self):
        self.idea['summary'] = {'nested': 'untrusted'}
        output = self.root / 'invalid.pdf'
        with self.assertRaises(ValueError):
            pdf_generator.generate_pdf([self.idea], 1, config.get_visual_theme('light_editorial'), str(output))
        self.assertFalse(output.exists())

    def test_render_error_cleans_temporary_file_and_keeps_old_output(self):
        output = self.root / 'stable.pdf'
        output.write_bytes(b'unchanged')
        with patch.object(pdf_generator.BaseDocTemplate, 'build', side_effect=ValueError('layout failure')):
            with self.assertRaises(ValueError):
                pdf_generator.generate_pdf([self.idea], 1, config.get_visual_theme('light_editorial'), str(output))
        self.assertEqual(output.read_bytes(), b'unchanged')
        self.assertEqual(list(self.root.glob('*.pdf')), [output])

    def test_runtime_only_allows_designated_secret_names(self):
        data = {'models': {'search': {'api_key_env_var': 'UNRELATED_HOST_SECRET'},
                           'writer': {'api_key_env_var': 'UNRELATED_HOST_SECRET'},
                           'fallbacks': {'openai_api_key_env_var': 'UNRELATED_HOST_SECRET'}}}
        normalized = runtime_settings._normalize_settings(data)
        self.assertEqual(normalized['models']['search']['api_key_env_var'], 'SEARCH_MODEL_API_KEY')
        self.assertEqual(normalized['models']['writer']['api_key_env_var'], 'WRITER_MODEL_API_KEY')
        self.assertEqual(normalized['models']['fallbacks']['openai_api_key_env_var'], 'OPENAI_API_KEY')

    def test_endpoint_credentials_and_remote_cleartext_are_rejected(self):
        for url in ('https://user:password@example.org/v1', 'https://example.org/v1?token=example',
                    'http://example.org/v1', 'file:///tmp/model', '//example.org'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                runtime_settings._normalize_settings({'models': {'search': {'base_url': url}}})
        for url in ('http://localhost:11434', 'http://127.0.0.1:11434', 'https://example.org/v1'):
            result = runtime_settings._normalize_settings({'models': {'search': {'base_url': url}}})
            self.assertEqual(result['models']['search']['base_url'], url)

    def test_runtime_secret_values_are_not_saved_in_settings(self):
        settings = runtime_settings._normalize_settings({'telegram': {'bot_token': 'SYNTHETIC_VALUE'},
            'models': {'search': {'api_key': 'SYNTHETIC_VALUE'}, 'writer': {'api_key': 'SYNTHETIC_VALUE'},
                       'fallbacks': {'openai_api_key': 'SYNTHETIC_VALUE'}}})
        self.assertNotIn('SYNTHETIC_VALUE', repr(settings))

    def test_config_import_does_not_load_dotenv(self):
        import importlib
        with patch('dotenv.load_dotenv', side_effect=AssertionError('Unexpected credential load')):
            importlib.reload(config)
        self.assertFalse(hasattr(config, 'OPENAI_API_KEY'))
        self.assertFalse((self.root / '.env').exists())

"""Language preference and web localization contract, with isolated user data."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import re
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import urllib.error
import urllib.request

from concertcutter.i18n import CATALOGS, Message, error_message, localize_payload
from concertcutter.web.preferences import Preferences, windows_language
from concertcutter.web import dialogs, server


class PreferencesTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / 'ConcertCutter' / 'preferences.json'

    def test_windows_ui_language_including_regional_variants(self):
        for code, expected in [(0x040c, 'fr'), (0x0c0c, 'fr'), (0x080c, 'fr'),
                               (0x0409, 'en'), (0x0809, 'en'), (0x0407, 'en'), (0, 'en')]:
            with self.subTest(code=code), patch('ctypes.windll',
                    SimpleNamespace(kernel32=SimpleNamespace(GetUserDefaultUILanguage=lambda: code)), create=True):
                self.assertEqual(windows_language(), expected)
        with patch('ctypes.windll', SimpleNamespace(kernel32=SimpleNamespace(
                GetUserDefaultUILanguage=Mock(side_effect=OSError('unavailable')))), create=True):
            self.assertEqual(windows_language(), 'en')

    def test_missing_invalid_and_corrupt_preferences(self):
        with patch('concertcutter.web.preferences.windows_language', return_value='fr'):
            self.assertEqual(Preferences(self.path).payload(), {
                'language': 'auto', 'effectiveLanguage': 'fr', 'checkUpdates': True,
            })
            self.path.parent.mkdir()
            for contents in ('{broken', '[]', 'null', '{"language":"de"}', '{"language":[]}', '\ufffd'):
                self.path.write_text(contents, encoding='utf-8')
                self.assertEqual(Preferences(self.path).language, 'auto')

    def test_manual_choice_persistence_and_return_to_auto(self):
        with patch('concertcutter.web.preferences.windows_language', return_value='fr') as detect:
            preferences = Preferences(self.path)
            self.assertEqual(preferences.update('en')['effectiveLanguage'], 'en')
            self.assertEqual(Preferences(self.path).language, 'en')
            self.assertEqual(preferences.update('auto')['effectiveLanguage'], 'fr')
            preferences.update('fr')
            self.assertEqual(detect.call_count, 2)
        with patch('concertcutter.web.preferences.windows_language', return_value='en'):
            self.assertEqual(Preferences(self.path).effective, 'fr')
            preferences.update('auto')
            self.assertEqual(Preferences(self.path).effective, 'en')

    def test_update_check_preference_defaults_on_and_persists(self):
        preferences = Preferences(self.path)
        self.assertTrue(preferences.check_updates)
        self.assertFalse(preferences.update('auto', False)['checkUpdates'])
        self.assertFalse(Preferences(self.path).check_updates)
        self.assertTrue(preferences.update('fr', True)['checkUpdates'])
        with self.assertRaises(ValueError):
            preferences.update('fr', 'yes')

    def test_invalid_update_and_failed_write_preserve_previous_preference(self):
        preferences = Preferences(self.path)
        preferences.update('fr')
        original = self.path.read_bytes()
        for invalid in ('de', '', None, [], {}, 1):
            with self.assertRaises(ValueError):
                preferences.update(invalid)
        with patch('concertcutter.web.preferences.os.replace', side_effect=OSError('disk full')):
            with self.assertRaises(OSError) as caught:
                preferences.update('en')
        self.assertIsInstance(caught.exception.args[0], Message)
        self.assertEqual(preferences.language, 'fr')
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(self.path.parent.glob('*.tmp')), [])


class CatalogTests(unittest.TestCase):
    def test_catalog_keys_placeholders_and_plural_forms_match(self):
        self.assertEqual(CATALOGS['fr'].keys(), CATALOGS['en'].keys())
        for key, french in CATALOGS['fr'].items():
            english = CATALOGS['en'][key]
            self.assertEqual(type(french), type(english), key)
            if isinstance(french, dict):
                self.assertEqual(set(french), {'one', 'other'}, key)
                self.assertEqual(french.keys(), english.keys(), key)
                pairs = [(french[form], english[form]) for form in french]
            else:
                pairs = [(french, english)]
            for left, right in pairs:
                self.assertTrue(left and right, key)
                self.assertEqual(set(re.findall(r'\{(\w+)\}', left)), set(re.findall(r'\{(\w+)\}', right)), key)

    def test_messages_keep_french_cli_value_and_translate_nested_parameters(self):
        message = Message('server.value_must_be_a_number', p0=Message('settings.fades'))
        self.assertEqual(str(message), 'Fondus doit être un nombre.')
        self.assertEqual(message.translate('en'), 'Fades must be a number.')
        self.assertEqual(copy.deepcopy(message).descriptor(), message.descriptor())
        self.assertEqual(error_message(ValueError(message)).descriptor(), message.descriptor())
        payload = localize_payload({'error': message, 'title': 'Fondus', 'warnings': [message]}, 'en')
        self.assertEqual(payload['title'], 'Fondus')
        self.assertEqual(payload['errorMessage']['params']['p0']['key'], 'settings.fades')
        self.assertEqual(payload['warningsMessages'][0]['key'], message.key)

    def test_dialog_filters_use_the_selected_language(self):
        host = Mock()
        with patch.object(dialogs, 'HOST', host):
            dialogs.ask_wav('en')
            self.assertEqual(host.open_file.call_args.args[0][0], ('WAV files', '*.wav *.WAV'))
            dialogs.ask_project('fr')
            self.assertEqual(host.open_file.call_args.args[0][0][0], 'Travaux ConcertCutter')


class PreferencesApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        environment = patch.dict(os.environ, {'LOCALAPPDATA': self.temporary.name})
        environment.start()
        self.addCleanup(environment.stop)
        self.httpd, self.app = server.serve()
        self.worker = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.worker.start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.url = server.url_for(self.httpd).rstrip('/')

    def request(self, route, body=None, token=True):
        request = urllib.request.Request(self.url + route,
            data=json.dumps(body).encode() if body is not None else None,
            headers={'X-ConcertCutter-Token': self.app.token} if token else {})
        try:
            answer = urllib.request.urlopen(request, timeout=5)
        except urllib.error.HTTPError as error:
            answer = error
        with answer:
            return answer.status, json.load(answer)

    def test_preferences_and_error_contract_preserve_session(self):
        before = self.app.session.state()
        self.assertEqual(self.request('/api/preferences', token=False)[0], 403)
        self.assertEqual(self.request('/api/update?online=0', token=False)[0], 403)
        status, updater = self.request('/api/update?online=0')
        self.assertEqual(status, 200)
        self.assertEqual(updater['status'], 'idle')
        self.assertFalse(updater['canAutoUpdate'])
        for language in ('fr', 'en', 'auto'):
            status, response = self.request('/api/preferences', {'language': language})
            self.assertEqual(status, 200)
            self.assertEqual(response['language'], language)
            self.assertTrue(response['checkUpdates'])
            self.assertEqual(self.app.session.state(), before)
        status, response = self.request('/api/preferences', {'checkUpdates': False})
        self.assertEqual(status, 200)
        self.assertFalse(response['checkUpdates'])
        self.assertEqual(response['language'], 'auto')
        status, error = self.request('/api/preferences', {'checkUpdates': None})
        self.assertEqual(status, 400)
        self.assertEqual(error['errorMessage']['key'], 'preferences.invalid_check_updates')
        self.request('/api/preferences', {'language': 'en'})
        status, error = self.request('/api/analyze', {})
        # Analysis runs asynchronously; failures retain the message descriptor.
        self.assertEqual(status, 200)
        job = self.app.jobs.get(error['id'])
        for _ in range(100):
            if job.state != 'running': break
            threading.Event().wait(.01)
        _, failed = self.request('/api/job?id=' + job.id)
        self.assertEqual(failed['error'], 'No recording is open.')
        self.assertIn('errorMessage', failed)
        self.request('/api/preferences', {'language': 'fr'})
        _, failed = self.request('/api/job?id=' + job.id)
        self.assertEqual(failed['error'], 'Aucun enregistrement ouvert.')
        status, error = self.request('/api/preferences', {'language': 'de'})
        self.assertEqual(status, 400)
        self.assertEqual(error['errorMessage']['key'], 'preferences.invalid_language')
        with patch('concertcutter.web.preferences.os.replace', side_effect=OSError('read only')):
            status, error = self.request('/api/preferences', {'language': 'en'})
        self.assertEqual(status, 500)
        self.assertEqual(error['errorMessage']['key'], 'preferences.save_failed')
        self.assertEqual(self.app.preferences.language, 'fr')

    def test_update_download_is_a_job_and_refuses_concurrent_work(self):
        with patch.object(self.app.updater, 'download',
                          side_effect=lambda job: {'ready': True}):
            status, started = self.request('/api/update/download', {})
            self.assertEqual(status, 200)
            self.assertEqual(started['kind'], 'update')
            job = self.app.jobs.get(started['id'])
            while job.state == 'running':
                threading.Event().wait(.01)
            self.assertEqual(job.result, {'ready': True})

        release = threading.Event()
        blocker = self.app.jobs.start('export', lambda _job: release.wait(1))
        try:
            status, error = self.request('/api/update/download', {})
            self.assertEqual(status, 409)
            self.assertEqual(error['errorMessage']['key'], 'update.busy')
        finally:
            release.set()
        while blocker.state == 'running':
            threading.Event().wait(.01)

    def test_update_restart_saves_and_passes_the_project_to_the_helper(self):
        resume = Path(self.temporary.name) / 'travail été.ccproj.json'
        timer = Mock()
        with patch.object(self.app.session, 'save_for_restart', return_value=resume), \
                patch.object(self.app.updater, 'prepare_restart') as prepare, \
                patch('concertcutter.web.server.threading.Timer', return_value=timer):
            status, response = self.request('/api/update/restart', {})
        self.assertEqual(status, 200)
        self.assertTrue(response['restarting'])
        prepare.assert_called_once_with(resume, False)
        timer.start.assert_called_once_with()

        with patch.object(
                self.app.session, 'save_for_restart',
                side_effect=server.SessionError(Message('update.save_failed')),
        ):
            status, error = self.request('/api/update/restart', {})
        self.assertEqual(status, 400)
        self.assertEqual(error['errorMessage']['key'], 'update.save_failed')


if __name__ == '__main__':
    unittest.main()

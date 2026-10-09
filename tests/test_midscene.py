import fcntl
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))
from iphone_use import Runtime
from wda_client import WDAError
import wda_midscene


class MidsceneTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        self.runtime = Runtime(self.root, base_url='http://127.0.0.1:18123')
        self.addCleanup(self.runtime.close)
        self.runtime.screen = Mock()
        self.runtime.screen.paused.return_value = False
        self.runtime.client = Mock(host='127.0.0.1', port=18123, session_id='borrowed-session')
        self.runtime.client.request.return_value = {'value': False}
        self.runtime.client.ensure_session.return_value = 'borrowed-session'
        worker = self.root / 'worker/run.mjs'
        dependency = worker.parent / 'node_modules/@midscene/ios/package.json'
        dependency.parent.mkdir(parents=True)
        dependency.write_text('{}')
        self.addCleanup(patch.stopall)
        patch.object(wda_midscene, 'WORKER', worker).start()
        patch.object(wda_midscene.shutil, 'which', return_value='/usr/bin/node').start()
        self.process = patch.object(wda_midscene.subprocess, 'run', return_value=Mock(
            returncode=0, stdout='{"ok":true}')).start()

    def call(self, action='screenshot', **args):
        return self.runtime.call('pua_midscene', {'action': action, **args})

    def test_default_without_model_configuration_and_legacy_env_not_forwarded(self):
        (self.root / 'midscene.json').write_text('{"enabled":false,"env":{"MIDSCENE_MODEL_API_KEY":"legacy-secret"}}')
        with patch.dict(wda_midscene.os.environ, {'MIDSCENE_MODEL_API_KEY': 'legacy-secret'}):
            self.assertTrue(self.call()['ok'])
        kwargs = self.process.call_args.kwargs
        self.assertNotIn('MIDSCENE_MODEL_API_KEY', kwargs['env'])
        self.assertNotIn('legacy-secret', kwargs['input'])

    def test_invalid_actions_and_arguments_never_contact_phone(self):
        invalid = [('act', {'prompt': 'task'}), ('tap', {'x': 5}),
                   ('screenshot', {'text': 'unexpected'}), ('input', {'text': 'send\n'}),
                   ('launch', {'text': 'https://example.com'}), ('record', {'text': 'done'}),
                   ('tap', {'x': -1, 'y': 1})]
        for action, args in invalid:
            with self.subTest(action=action, args=args), self.assertRaises(WDAError):
                self.call(action, **args)
        self.process.assert_not_called()
        self.runtime.client.request.assert_not_called()

    def test_missing_dependency_without_phone_access(self):
        (wda_midscene.WORKER.parent / 'node_modules/@midscene/ios/package.json').unlink()
        with self.assertRaises(WDAError) as error:
            self.call()
        self.assertEqual(error.exception.code, 'midscene_not_installed')
        self.runtime.client.request.assert_not_called()

    def test_shared_session_and_cross_process_lock(self):
        def execute(command, **kwargs):
            with (self.root / 'operation.lock').open('a') as lock:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            request = json.loads(kwargs['input'])
            self.assertEqual((request['host'], request['port'], request['sessionId']),
                             ('127.0.0.1', 18123, 'borrowed-session'))
            self.assertEqual(kwargs['cwd'], self.root)
            return Mock(returncode=0, stdout='{"ok":true}')
        self.process.side_effect = execute
        self.call()
        self.runtime.client.reapply_settings.assert_called_once_with()

    def test_report_id_generated_forwarded_and_validated(self):
        result = self.call()
        self.assertRegex(result['report_id'], r'^[a-f0-9]{32}$')
        self.assertEqual(json.loads(self.process.call_args.kwargs['input'])['reportId'], result['report_id'])
        self.assertEqual(self.call(report_id='task-1')['report_id'], 'task-1')
        self.process.reset_mock()
        for invalid in ('../outside', 'a/b', 'a.b', '汉字', 'a' * 65, ''):
            with self.assertRaises(WDAError):
                self.call(report_id=invalid)
        self.process.assert_not_called()

    def test_busy_paused_and_locked_refuse_worker(self):
        with (self.root / 'operation.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            with self.assertRaises(WDAError) as error:
                self.call()
            self.assertEqual(error.exception.code, 'device_busy')
        self.runtime.screen.paused.return_value = True
        with self.assertRaises(WDAError) as error:
            self.call()
        self.assertEqual(error.exception.code, 'preview_paused')
        self.runtime.screen.paused.return_value = False
        self.runtime.client.request.return_value = {'value': True}
        with self.assertRaises(WDAError) as error:
            self.call()
        self.assertEqual(error.exception.code, 'phone_locked')
        self.process.assert_not_called()

    def test_timeout_uncertain_for_mutation_no_replay(self):
        self.process.side_effect = subprocess.TimeoutExpired('node', 60, stderr='secret')
        with self.assertRaises(WDAError) as error:
            self.call('tap', x=1, y=2)
        self.assertTrue(error.exception.uncertain)
        self.assertNotIn('secret', str(error.exception))
        self.process.assert_called_once()
        self.runtime.client.reapply_settings.assert_called_once_with()

    def test_failed_host_verification_preserves_report(self):
        self.process.return_value = Mock(returncode=1, stdout='{"ok":false,"report":"/local/report.html"}')
        with self.assertRaises(WDAError) as error:
            self.call('record', text='Expected page missing', passed=False, report_id='task-1')
        self.assertFalse(error.exception.uncertain)
        self.assertEqual(error.exception.details['report_id'], 'task-1')
        self.assertEqual(error.exception.details['report'], '/local/report.html')

    def test_worker_is_shipped_without_node_modules(self):
        sys.path.insert(0, str(ROOT / 'scripts'))
        import package
        files = {str(rel) for _, rel in package.package_files()}
        self.assertTrue({'server/midscene/run.mjs', 'server/midscene/package.json',
                         'server/midscene/package-lock.json', 'server/wda_midscene.py'} <= files)
        self.assertFalse(any('node_modules' in name for name in files))

    def test_ai_requires_consent_before_phone_access_and_never_uses_api_key(self):
        with patch.object(wda_midscene.wda_chatgpt, 'run', return_value={'authorized': False}):
            with self.assertRaises(WDAError) as error:
                self.call('assert', text='Expected page')
        self.assertEqual(error.exception.code, 'chatgpt_sign_in_required')
        self.runtime.client.request.assert_not_called()
        with patch.object(wda_midscene.wda_chatgpt, 'run', return_value={'authorized': True}), \
                patch.dict(wda_midscene.os.environ, {'OPENAI_API_KEY': 'must-not-forward'}):
            self.call('act', text='Open About')
        self.assertTrue(self.process.call_args.args[0][1].endswith('run-ai.mjs'))
        self.assertEqual(self.process.call_args.kwargs['timeout'], 180)
        self.assertNotIn('OPENAI_API_KEY', self.process.call_args.kwargs['env'])
        self.assertEqual(len(self.process.call_args.kwargs['pass_fds']), 1)

    def test_authorization_tools_work_without_phone_or_device_lock(self):
        with patch.object(wda_midscene.wda_chatgpt, 'run', return_value={'ok': True, 'authorized': False}) as auth:
            with (self.root / 'operation.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                self.assertFalse(self.call('auth_status')['authorized'])
            auth.assert_called_once_with(self.root, 'auth_status')
            with self.assertRaises(WDAError):
                self.call('auth_login', report_id='unexpected')
        self.runtime.client.request.assert_not_called()

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from desktop_harness.desktop_backend import DesktopBackend
from desktop_harness.store import Store
from desktop_harness.worker import run_one, submit_request


class BackendIntegrationTest(unittest.TestCase):
    def test_followup_binds_completed_prior_and_never_opens_new_chat(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            binary = root / '.build/ax-picker-probe'
            binary.parent.mkdir()
            binary.touch()
            store = Store(root / 'requests.sqlite')
            native_modes = []

            async def probe(binary, path, mode, model):
                import hashlib
                wire = json.loads(path.read_text())
                native_modes.append(mode)
                if mode == 'select-model':
                    return {'ok': True, 'process_exit_code': 0, 'model_verified_with_closed_picker': True,
                            'verified_model_label': model + ' Medium'}
                if mode == 'prepare-followup':
                    self.assertEqual(wire['previous_turn']['request_id'], first['request_id'])
                    self.assertEqual(wire['previous_turn']['response_text'], 'A verified answer.')
                    return {'ok': True, 'draft_verified': True}
                return {'ok': True, 'process_exit_code': 0, 'request_id': wire['request_id'],
                        'attempt_id': wire['attempt_id'], 'workspace': wire['workspace'],
                        'wire_prompt_sha256': hashlib.sha256(wire['prompt'].encode()).hexdigest(),
                        'submission_evidence_verified': True, 'completion_evidence_verified': True,
                        'response_text': 'A verified answer.', 'verified_model_label': model + ' Medium'}

            with patch('desktop_harness.desktop_backend.Path.cwd', return_value=root), \
                    patch('desktop_harness.desktop_backend.native', side_effect=probe), \
                    patch('desktop_harness.desktop_backend.subprocess.run') as opener, \
                    patch('desktop_harness.desktop_backend.asyncio.sleep'):
                backend = DesktopBackend(store)
                first = submit_request('First question.', str(root), store=store)
                completed = asyncio.run(run_one(backend, store=store, request_id=first['request_id']))
                self.assertEqual(completed['state'], 'completed')
                backend.previous_request_id = first['request_id']
                second = submit_request('Follow up on that answer.', str(root), store=store)
                completed = asyncio.run(run_one(backend, store=store, request_id=second['request_id']))
                self.assertEqual(completed['state'], 'completed')
                self.assertEqual(opener.call_count, 2)
                self.assertEqual(opener.call_args.args[0], ['/usr/bin/open', '-b', 'com.openai.codex'])
                self.assertEqual(native_modes, ['select-model', 'send-request', 'prepare-followup', 'select-model', 'send-request'])

    def perform(self, invalid_attempt=False):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            binary = root / '.build/ax-picker-probe'
            binary.parent.mkdir()
            binary.touch()
            store = Store(root / 'requests.sqlite')
            queued = submit_request('Explain with a paragraph and an indented code example.', str(root), store=store)

            async def probe(binary, path, mode, model):
                task = json.loads(path.read_text())
                if mode == 'select-model':
                    self.assertIs(task['auto_focus'], True)
                    return {'ok': True, 'process_exit_code': 0, 'model_verified_with_closed_picker': True,
                            'verified_model_label': model + ' Medium'}
                import hashlib
                return {'ok': True, 'process_exit_code': 0, 'request_id': task['request_id'],
                        'attempt_id': 'stale' if invalid_attempt else task['attempt_id'],
                        'workspace': task['workspace'],
                        'wire_prompt_sha256': hashlib.sha256(task['prompt'].encode()).hexdigest(),
                        'submission_attempted': True, 'submission_evidence_verified': True,
                        'completion_evidence_verified': True, 'response_text': 'Explanation.\n    example()',
                        'verified_model_label': model + ' Medium',
                        'completion_marker_text': 'Response complete: Explanation.'}

            with patch('desktop_harness.desktop_backend.Path.cwd', return_value=root), \
                    patch('desktop_harness.desktop_backend.native', side_effect=probe), \
                    patch('desktop_harness.desktop_backend.subprocess.run') as opener, \
                    patch('desktop_harness.desktop_backend.asyncio.sleep'):
                backend = DesktopBackend(store)
                result = asyncio.run(run_one(backend, store=store))
                self.assertEqual(opener.call_args.args[0][:3], ['/usr/bin/open', '-b', 'com.openai.codex'])
            return result, store.response(queued['request_id'])

    def test_general_response_reconciles_into_durable_store(self):
        result, response = self.perform()
        self.assertEqual(result['state'], 'completed')
        self.assertEqual(response['response_text'], 'Explanation.\n    example()')
        self.assertTrue(response['evidence']['completion_evidence_verified'])

    def test_wrong_native_attempt_stays_uncertain(self):
        result, response = self.perform(invalid_attempt=True)
        self.assertEqual(result['state'], 'uncertain')
        self.assertIsNone(response['response_text'])

    def test_failed_activation_cannot_reach_send(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            binary = root / '.build/ax-picker-probe'
            binary.parent.mkdir()
            binary.touch()
            store = Store(root / 'requests.sqlite')
            submit_request('A question.', str(root), store=store)
            with patch('desktop_harness.desktop_backend.Path.cwd', return_value=root), \
                    patch('desktop_harness.desktop_backend.native', return_value={
                        'ok': False, 'error': 'target_app_activation_not_observed', 'process_exit_code': 1}) as probe, \
                    patch('desktop_harness.desktop_backend.subprocess.run'), \
                    patch('desktop_harness.desktop_backend.asyncio.sleep'):
                result = asyncio.run(run_one(DesktopBackend(store), store=store))
            self.assertEqual(result['state'], 'failed')
            self.assertIn('target_app_activation_not_observed', result['error'])
            self.assertEqual(probe.await_count, 1)
            self.assertEqual(probe.await_args.args[2], 'select-model')

    def test_reconciliation_only_reads_existing_attempt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            binary = root / '.build/ax-picker-probe'
            binary.parent.mkdir()
            binary.touch()
            store = Store(root / 'requests.sqlite')
            queued = submit_request('A question.', str(root), store=store)
            task = store.claim_next('fixture-worker')
            from desktop_harness.desktop_backend import wrap_prompt
            wire = {**task, 'prompt': wrap_prompt(task['prompt'], task['request_id'])}
            digest = store.bind_wire_prompt(task['request_id'], task['attempt_id'], wire['prompt'])
            directory = root / 'work/worker' / task['request_id'] / task['attempt_id']
            directory.mkdir(parents=True)
            (directory / 'task.json').write_text(json.dumps(wire))
            receipt = {'request_id': task['request_id'], 'attempt_id': task['attempt_id'],
                       'workspace': str(root), 'wire_prompt_sha256': digest,
                       'completion_evidence_verified': True, 'response_text': 'Recovered answer.',
                       'verified_model_label': 'GPT-5.6 Sol Medium'}
            with patch('desktop_harness.desktop_backend.Path.cwd', return_value=root), \
                    patch('desktop_harness.desktop_backend.native', return_value=receipt) as native, \
                    patch('desktop_harness.desktop_backend.subprocess.run') as opener, \
                    patch('desktop_harness.desktop_backend.asyncio.sleep'):
                result = asyncio.run(DesktopBackend(store).reconcile(queued['request_id']))
            self.assertEqual(result['state'], 'completed')
            self.assertEqual(native.await_args.args[2], 'read-request')
            opener.assert_not_called()

    def test_optional_focus_capture_failure_still_verifies_model_and_sends_once(self):
        for required in (False, True):
            with self.subTest(required=required), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary); binary = root / '.build/ax-picker-probe'
                binary.parent.mkdir(); binary.touch()
                store = Store(root / 'db')
                queued = submit_request('Question', str(root), store=store)
                modes = []
                async def probe(binary, path, mode, model):
                    import hashlib
                    modes.append(mode); task = json.loads(path.read_text())
                    if mode == 'capture-focus':
                        return {'ok': False, 'error': 'caller_focus_not_external'}
                    if mode == 'select-model':
                        return {'ok': True, 'process_exit_code': 0, 'model_verified_with_closed_picker': True, 'verified_model_label': model + ' Medium'}
                    return {**task, 'prompt_sha256': queued['prompt_sha256'], 'wire_prompt_sha256': hashlib.sha256(task['prompt'].encode()).hexdigest(), 'completion_evidence_verified': True, 'response_text': 'Answer', 'verified_model_label': model + ' Medium'}
                with patch('desktop_harness.desktop_backend.Path.cwd', return_value=root), patch('desktop_harness.desktop_backend.native', side_effect=probe), patch('desktop_harness.desktop_backend.subprocess.run'), patch('desktop_harness.desktop_backend.asyncio.sleep'):
                    backend = DesktopBackend(store); backend.return_focus = True; backend.require_return_focus = required
                    result = asyncio.run(run_one(backend, store=store))
                    asyncio.run(backend.restore_focus(queued['request_id']))
                self.assertEqual(result['state'], 'failed' if required else 'completed')
                self.assertEqual(modes, ['capture-focus'] if required else ['capture-focus', 'select-model', 'send-request'])
                capture = root / 'work/worker' / queued['request_id'] / result['attempt_id'] / 'focus-capture.json'
                self.assertEqual(json.loads(capture.read_text())['error'], 'caller_focus_not_external')

    def test_generation_native_binary_is_used_instead_of_repository_binary(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            generation = root / 'generation/.build'; generation.mkdir(parents=True)
            (generation / 'ax-picker-probe').touch()
            with patch.dict('os.environ', {'HARNESS_NATIVE_DIR': str(generation)}), patch('desktop_harness.desktop_backend.Path.cwd', return_value=root):
                backend = DesktopBackend(Store(root / 'db'))
                self.assertEqual(backend.binary, generation / 'ax-picker-probe')

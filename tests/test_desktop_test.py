import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from desktop_harness.desktop_test import exercise
from desktop_harness.store import Store


class DesktopWorkflowTest(unittest.TestCase):
    def exercise_fixture(self, selection, sender):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binary = root / '.build/ax-picker-probe'
            binary.parent.mkdir()
            binary.touch()
            binary.chmod(0o700)

            async def prepare(task, model, context):
                Store().prepare(**json.loads(task))
                return {'model': 'fixture-local-model'}

            async def probe(binary, task_file, mode, model):
                if mode == 'select-model':
                    return selection
                return sender(json.loads(task_file.read_text())) if callable(sender) else sender

            with patch.dict(os.environ, {'HARNESS_DB': str(root / 'requests.sqlite')}), \
                    patch('desktop_harness.desktop_test.Path.cwd', return_value=root), \
                    patch('desktop_harness.desktop_test.run', side_effect=prepare), \
                    patch('desktop_harness.desktop_test.native', side_effect=probe) as native, \
                    patch('desktop_harness.desktop_test.subprocess.run'), \
                    patch('desktop_harness.desktop_test.asyncio.sleep'):
                result = asyncio.run(exercise())
                saved = json.loads(Path(result['report_file']).read_text())
                self.assertEqual(saved, result)
                return result, native.await_count

    def test_unverified_selection_blocks_send(self):
        result, calls = self.exercise_fixture({'ok': False, 'process_exit_code': 6}, {})
        self.assertEqual(result['state'], 'model_selection_failed')
        self.assertIs(result['submission_attempted'], False)
        self.assertEqual(calls, 1)

    def test_wrong_response_token_cannot_complete_request(self):
        selection = {'ok': True, 'process_exit_code': 0,
                     'model_verified_with_closed_picker': True,
                     'verified_model_label': 'GPT-5.6 Sol Medium'}
        sender = {'ok': True, 'process_exit_code': 0, 'submission_attempted': True,
                  'completion_evidence_verified': True,
                  'expected_response': 'STALE_OTHER_REQUEST',
                  'verified_model_label': 'GPT-5.6 Sol Medium'}
        result, calls = self.exercise_fixture(selection, sender)
        self.assertEqual(result['state'], 'uncertain')
        self.assertEqual(calls, 2)

    def test_observed_response_is_returned(self):
        selection = {'ok': True, 'process_exit_code': 0,
                     'model_verified_with_closed_picker': True,
                     'verified_model_label': 'GPT-5.6 Sol Medium'}

        def sender(task):
            token = 'DESKTOP_SPIKE_' + task['request_id'].replace('-', '').upper()
            return {'ok': True, 'process_exit_code': 0, 'submission_attempted': True,
                    'completion_evidence_verified': True, 'expected_response': token,
                    'response_text': token, 'verified_model_label': 'GPT-5.6 Sol Medium'}

        result, calls = self.exercise_fixture(selection, sender)
        self.assertEqual(result['state'], 'completed_test')
        self.assertEqual(result['response_text'], result['expected_response'])
        self.assertEqual(calls, 2)

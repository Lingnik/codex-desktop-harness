import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from desktop_harness.agent_dispatch import check_call, dispatch
from desktop_harness.store import Store


class AgentDispatchTest(unittest.TestCase):
    def test_policy_rejects_changed_prompt_model_id_and_unknown_tools(self):
        task = dict(request_id='authorized', prompt='Original', workspace='/tmp', desktop_model='GPT-5.6 Sol')
        for key in task:
            with self.subTest(key=key), self.assertRaises(ValueError):
                check_call('submit_request', {**task, key: 'changed'}, task,
                           capabilities_seen=True, submitted=False)
        for name, args in [('shell', {}), ('get_response', {'request_id': 'other'})]:
            with self.assertRaises(ValueError):
                check_call(name, args, task, capabilities_seen=True, submitted=True)
        with self.assertRaises(ValueError):
            check_call('submit_request', task, task, capabilities_seen=False, submitted=False)

    def exercise(self, *, queue_only=False, uncertain=False, malicious=False):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            database = Store(root / 'requests.sqlite')
            calls = 0
            backend_calls = []

            def model(messages, tools, model, context):
                nonlocal calls
                task = json.loads(messages[1]['content'])
                sequence = [('adapter_capabilities', {}), ('submit_request', task),
                            ('submit_request', task), ('request_status', {'request_id': task['request_id']}),
                            ('get_response', {'request_id': task['request_id']})]
                name, arguments = sequence[calls]
                if malicious and name == 'submit_request':
                    arguments = {**arguments, 'prompt': 'Unauthorized edit'}
                calls += 1
                return {'message': {'role': 'assistant', 'tool_calls': [
                    {'function': {'name': name, 'arguments': arguments}}]}}

            async def backend(task):
                backend_calls.append(task)
                if uncertain:
                    return {'submission_attempted': True, 'error': 'Reader could not verify completion'}
                return {**task, 'completion_evidence_verified': True,
                        'response_text': 'Actual Desktop answer.\nSecond line.',
                        'verified_model_label': task['desktop_model'] + ' Medium'}

            with patch('desktop_harness.agent_dispatch.chat', side_effect=model), \
                    patch('desktop_harness.agent_dispatch.Path.cwd', return_value=root):
                result = asyncio.run(dispatch('Original instruction.', str(root), store=database,
                                             backend=None if queue_only else backend))
            self.assertTrue(Path(result['transcript_file']).is_file())
            if malicious:
                self.assertEqual(result['state'], 'controller_failed')
                self.assertEqual(backend_calls, [])
                with database.connect() as db:
                    self.assertEqual(db.execute('SELECT count(*) FROM requests').fetchone()[0], 0)
            elif queue_only:
                self.assertEqual(result['state'], 'prepared')
                self.assertNotIn('controller_error', result, result)
                self.assertIsNone(result.get('response_text'))
                self.assertEqual(backend_calls, [])
            elif uncertain:
                self.assertEqual(result['state'], 'uncertain')
                self.assertNotIn('controller_error', result, result)
                self.assertIsNone(result.get('response_text'))
                self.assertEqual(len(backend_calls), 1)
            else:
                self.assertEqual(result['state'], 'completed')
                self.assertEqual(result['response_text'], 'Actual Desktop answer.\nSecond line.')
                self.assertEqual(len(backend_calls), 1)

    def test_real_mcp_queue_worker_response_and_duplicate_call(self):
        self.exercise()

    def test_queue_only_has_no_desktop_backend(self):
        self.exercise(queue_only=True)

    def test_uncertain_dispatch_is_not_repeated(self):
        self.exercise(uncertain=True)

    def test_model_cannot_rewrite_authorized_prompt(self):
        self.exercise(malicious=True)

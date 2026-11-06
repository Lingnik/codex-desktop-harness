import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from desktop_harness.repl import interact, proposal, load_resume
from desktop_harness.store import Store


def action(name, **args):
    return {'message': {'role': 'assistant', 'content': '', 'tool_calls': [
        {'function': {'name': name, 'arguments': args}}]}}


class ReplTest(unittest.TestCase):
    def test_planning_truncation_keeps_completed_history_and_can_resume(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            store = Store(root / 'requests.sqlite')
            class Backend:
                calls = 0
                async def __call__(self, task):
                    self.calls += 1
                    return {**task, 'completion_evidence_verified': True,
                            'verified_model_label': task['desktop_model'] + ' Medium',
                            'response_text': 'Verified Desktop answer.'}
            backend = Backend()
            truncated = {'message': {'role': 'assistant', 'content': ''}, 'done_reason': 'length'}
            with patch('desktop_harness.repl.chat', side_effect=[
                    action('ask_codex', assessment='Start.', prompt='First question.'), truncated, truncated]) as model, \
                    patch('desktop_harness.repl.Path.cwd', return_value=root):
                record = asyncio.run(interact('A problem', str(root), store, backend,
                                              read=lambda _: '', write=lambda _: None))
                self.assertEqual(record['state'], 'error')
                self.assertIn('4096-token', record['error'])
                self.assertEqual([call.kwargs['num_predict'] for call in model.call_args_list], [2048, 2048, 4096])
                self.assertEqual(backend.calls, 1)
                resumed = load_resume(record['session_id'], store)
                self.assertEqual(resumed['turns'][0]['state'], 'completed')
                with patch('desktop_harness.repl.chat', return_value={
                        'message': {'role': 'assistant', 'content': 'A considered answer.'}}):
                    final = asyncio.run(interact('A problem', str(root), store, backend, resume=resumed,
                                                 read=lambda _: '', write=lambda _: None))
                self.assertEqual(final['state'], 'completed')
                self.assertEqual(backend.calls, 1)

    def test_resume_preserves_completed_reply_and_refuses_uncertain(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            store = Store(root / 'requests.sqlite')
            class Backend:
                calls = 0
                async def __call__(self, task):
                    self.calls += 1
                    if self.calls == 2:
                        return {'submission_attempted': False, 'state': 'failed_before_send',
                                'error': 'Follow-up preparation failed before Send: activation failed'}
                    return {**task, 'completion_evidence_verified': True,
                            'verified_model_label': task['desktop_model'] + ' Medium',
                            'response_text': 'Stored first answer.'}
            responses = [action('ask_codex', assessment='Start.', prompt='First question.'),
                         action('ask_codex', assessment='Build on answer.', prompt='Follow-up.')]
            with patch('desktop_harness.repl.chat', side_effect=responses), patch('desktop_harness.repl.Path.cwd', return_value=root):
                record = asyncio.run(interact('A problem', str(root), store, Backend(),
                                              read=lambda _: '', write=lambda _: None))
                self.assertEqual(record['state'], 'blocked')
                resumed = load_resume(record['session_id'], store)
                self.assertEqual(len(resumed['turns']), 1)
                self.assertEqual(resumed['messages'][-1]['role'], 'tool')
                self.assertIn('Stored first answer.', resumed['messages'][-1]['content'])
                failed = record['turns'][-1]['request_id']
                # Even a matching saved session may never resume an uncertain attempt.
                with store.connect() as db:
                    db.execute("UPDATE requests SET state='uncertain' WHERE id=?", (failed,))
                with self.assertRaisesRegex(ValueError, 'uncertain'):
                    load_resume(record['session_id'], store)

    def test_steering_and_actual_response_feed_followup_in_same_session(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            store = Store(root / 'requests.sqlite')
            sent = []
            model_calls = 0

            class Backend:
                previous_request_id = None
                async def __call__(self, task):
                    sent.append((task, self.previous_request_id))
                    return {**task, 'completion_evidence_verified': True,
                            'verified_model_label': task['desktop_model'] + ' Medium',
                            'response_text': 'Approach A uses weighted fairness.' if len(sent) == 1 else 'Weighted fairness revised.'}

            def model(messages, tools, outer_model, context, **options):
                nonlocal model_calls
                model_calls += 1
                if model_calls == 1:
                    return action('ask_codex', assessment='Explore two approaches.', prompt='Propose two approaches.')
                if model_calls == 2:
                    self.assertIn('Focus on urgent tickets.', [m.get('content') for m in messages])
                    return action('ask_codex', assessment='Incorporate user steering.', prompt='Propose two approaches for urgent tickets.')
                if model_calls == 3:
                    replies = [json.loads(m['content']) for m in messages if m['role'] == 'tool']
                    self.assertEqual(replies[-1]['response_text'], 'Approach A uses weighted fairness.')
                    return action('ask_codex', assessment='Approach A offers fairness.', prompt='Revise Approach A weighted fairness to prevent starvation.')
                self.assertEqual([t['function']['name'] for t in tools], ['finish'])
                self.assertTrue(any('Weighted fairness revised.' in m.get('content', '') for m in messages))
                return {'message': {'role': 'assistant', 'content': 'Use weighted fairness with aging.'}}

            commands = iter(['Focus on urgent tickets.', '', '', ''])
            with patch('desktop_harness.repl.chat', side_effect=model), patch('desktop_harness.repl.Path.cwd', return_value=root):
                record = asyncio.run(interact('Design support ticket processing.', str(root), store, Backend(),
                                              max_turns=2, read=lambda _: next(commands), write=lambda _: None))
            self.assertEqual(record['state'], 'completed', record)
            self.assertEqual(len(sent), 2)
            self.assertIsNone(sent[0][1])
            self.assertEqual(sent[1][1], sent[0][0]['request_id'])
            self.assertNotEqual(sent[1][0]['request_id'], sent[0][0]['request_id'])
            self.assertEqual(len(list((root / 'work/repl-sessions').glob('*/session.json'))), 1)

    def test_local_question_and_stop_never_dispatch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            store = Store(root / 'requests.sqlite')
            responses = [action('ask_codex', assessment='Explore.', prompt='Propose approaches.'),
                         {'message': {'role': 'assistant', 'content': 'This will compare tradeoffs.'}}]
            commands = iter(['/ask Why this step?', '/stop'])
            async def backend(task):
                self.fail('Local question or stop cannot invoke Desktop')
            with patch('desktop_harness.repl.chat', side_effect=responses), patch('desktop_harness.repl.Path.cwd', return_value=root):
                record = asyncio.run(interact('A problem', str(root), store, backend,
                                              read=lambda _: next(commands), write=lambda _: None))
            self.assertEqual(record['state'], 'stopped')
            self.assertEqual(record['turns'], [])
            self.assertEqual(record['messages'][-1]['content'], 'This will compare tradeoffs.')

    def test_invalid_actions_are_rejected(self):
        for response in [action('shell', command='anything'), action('ask_codex', assessment='x', prompt=''),
                         {'message': {'tool_calls': []}}]:
            with self.assertRaises(ValueError):
                proposal(response['message'])

    def test_uncertain_turn_stops_the_loop_without_retry(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            store = Store(root / 'requests.sqlite')
            class Backend:
                calls = 0
                async def __call__(self, task):
                    self.calls += 1
                    return {'submission_attempted': True, 'error': 'Completion unverified'}
            backend = Backend()
            with patch('desktop_harness.repl.chat', return_value=action('ask_codex', assessment='Explore.', prompt='Compare.')), \
                    patch('desktop_harness.repl.Path.cwd', return_value=root):
                record = asyncio.run(interact('A problem', str(root), store, backend,
                                              read=lambda _: '', write=lambda _: None))
            self.assertEqual(record['state'], 'blocked')
            self.assertEqual(backend.calls, 1)
            self.assertEqual(record['turns'][0]['state'], 'uncertain')

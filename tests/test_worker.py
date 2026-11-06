import asyncio
import hashlib
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from desktop_harness.store import Store
from desktop_harness.worker import run_one, submit_request, replacement_after_selection_failure


class WorkerTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = Store(self.root / 'requests.sqlite')

    def tearDown(self):
        self.temporary.cleanup()

    def enqueue(self, prompt='Explain a small Python function.'):
        return submit_request(prompt, str(self.root), request_id=str(uuid4()), store=self.store)

    def test_known_selection_failure_can_be_replaced_without_reusing_attempt(self):
        original = self.enqueue()
        task = self.store.claim_dispatch(original['request_id'])
        self.store.fail(task['request_id'], task['attempt_id'], 'Model selection failed before Send', uncertain=False)
        replacement = replacement_after_selection_failure(self.store, original['request_id'])
        self.assertNotEqual(replacement['request_id'], original['request_id'])
        self.assertTrue(replacement['queued'])
        self.assertEqual(self.store.payload(replacement['request_id'])['prompt'], task['prompt'])
        self.assertEqual(self.store.get(original['request_id'])['state'], 'failed')

    def test_uncertain_attempt_cannot_be_replaced_automatically(self):
        original = self.enqueue()
        self.store.claim_dispatch(original['request_id'])
        with self.assertRaises(ValueError):
            replacement_after_selection_failure(self.store, original['request_id'])

    def test_targeted_request_does_not_pick_an_older_job(self):
        older = self.enqueue('Older queued job')
        wanted = self.enqueue('One-step request')
        seen = []

        def backend(task):
            seen.append(task['request_id'])
            return {'state': 'failed_before_send', 'submission_attempted': False, 'error': 'fixture'}

        asyncio.run(run_one(backend, store=self.store, request_id=wanted['request_id']))
        self.assertEqual(seen, [wanted['request_id']])
        self.assertIsNone(self.store.get(older['request_id'])['attempt_id'])

    def test_targeted_request_respects_uncertain_active_attempt(self):
        older = self.enqueue('Uncertain job')
        wanted = self.enqueue('One-step request')
        self.store.claim_dispatch(older['request_id'])
        result = asyncio.run(run_one(lambda task: self.fail('must not dispatch'),
                                     store=self.store, request_id=wanted['request_id']))
        self.assertTrue(result['dispatch_blocked'])
        self.assertIsNone(result['attempt_id'])

    def test_targeted_completed_request_returns_saved_answer_without_backend(self):
        queued = self.enqueue()
        task = self.store.claim_dispatch(queued['request_id'])
        evidence = {'request_id': task['request_id'], 'attempt_id': task['attempt_id'],
                    'workspace': task['workspace'], 'prompt_sha256': task['prompt_sha256'],
                    'verified_model_label': 'GPT-5.6 Sol Medium', 'completion_evidence_verified': True,
                    'response_text': 'Saved answer.'}
        self.store.complete(task['request_id'], task['attempt_id'], 'Saved answer.', evidence)
        result = asyncio.run(run_one(lambda task: self.fail('must not resend'),
                                     store=self.store, request_id=queued['request_id']))
        self.assertEqual(result['response_text'], 'Saved answer.')

    def test_missing_backend_does_not_consume_claim(self):
        queued = self.enqueue()
        result = asyncio.run(run_one(store=self.store))
        self.assertEqual(result['state'], 'backend_unavailable')
        self.assertFalse(result['claimed'])
        self.assertEqual(self.store.get(queued['request_id'])['state'], 'prepared')

    def test_receipt_returns_actual_response_and_does_not_redispatch(self):
        queued = self.enqueue()
        observed = []

        async def backend(task):
            observed.append(task['request_id'])
            self.store.acknowledge_submission(task['request_id'], task['claim_token'])
            return {'request_id': task['request_id'], 'attempt_id': task['attempt_id'],
                    'workspace': task['workspace'],
                    'prompt_sha256': hashlib.sha256(task['prompt'].encode()).hexdigest(),
                    'verified_model_label': task['desktop_model'] + ' Medium',
                    'completion_evidence_verified': True, 'submission_attempted': True,
                    'response_text': 'Paragraph one.\n\n```python\nprint(1)\n```'}

        result = asyncio.run(run_one(backend, store=self.store))
        self.assertEqual(result['state'], 'completed')
        self.assertIn('print(1)', self.store.get_response(queued['request_id'])['response_text'])
        again = asyncio.run(run_one(backend, store=self.store))
        self.assertFalse(again['claimed'])
        self.assertEqual(observed, [queued['request_id']])

    def test_unattributed_response_stays_uncertain_and_blocks_next(self):
        queued = self.enqueue()
        self.enqueue('Second job')
        result = asyncio.run(run_one(lambda task: {
            'request_id': str(uuid4()), 'response_text': 'Old response',
            'completion_evidence_verified': True}, store=self.store))
        self.assertEqual(result['state'], 'uncertain')
        self.assertEqual(result['request_id'], queued['request_id'])
        again = asyncio.run(run_one(lambda task: self.fail('must not dispatch'), store=self.store))
        self.assertFalse(again['claimed'])

    def test_explicit_presend_failure_releases_queue_but_not_same_id(self):
        first = self.enqueue()
        second = self.enqueue('Second job')
        backend = lambda task: {'state': 'failed_before_send', 'submission_attempted': False,
                                'error': 'Model selection failed'}
        result = asyncio.run(run_one(backend, store=self.store))
        self.assertEqual(result['state'], 'failed')
        result2 = asyncio.run(run_one(backend, store=self.store))
        self.assertEqual(result2['request_id'], second['request_id'])
        self.assertNotEqual(result2['request_id'], first['request_id'])

    def test_cancellation_keeps_claim_uncertain(self):
        queued = self.enqueue()

        async def backend(task):
            raise asyncio.CancelledError()

        with self.assertRaises(asyncio.CancelledError):
            asyncio.run(run_one(backend, store=self.store))
        self.assertEqual(self.store.get(queued['request_id'])['state'], 'uncertain')

    def test_same_uuid_different_model_rejected(self):
        queued = self.enqueue()
        with self.assertRaises(ValueError):
            submit_request('Explain a small Python function.', str(self.root),
                           'GPT-6.1 Sol', queued['request_id'], store=self.store)

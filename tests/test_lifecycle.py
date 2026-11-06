import hashlib
import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

from desktop_harness.store import Store


class LifecycleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.path = Path(self.root) / 'requests.sqlite'
        self.store = Store(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def prepare(self, prompt='Write two paragraphs'):
        request = str(uuid4())
        self.store.prepare(request, prompt, self.root, 'GPT-5.6 Sol')
        self.store.queue(request)
        return request

    def evidence(self, task, response='First paragraph.\n\nSecond paragraph.'):
        return {'request_id': task['request_id'], 'attempt_id': task['attempt_id'],
                'workspace': task['workspace'], 'prompt_sha256': task['prompt_sha256'],
                'completion_evidence_verified': True, 'response_text': response,
                'verified_model_label': 'GPT-5.6 Sol Medium'}

    def test_restart_consumes_attempt_and_blocks_other_requests(self):
        first, second = self.prepare(), self.prepare('Another request')
        task = self.store.claim_next('worker-1')
        self.assertEqual(task['request_id'], first)
        restarted = Store(self.path)
        self.assertIsNone(restarted.claim_next('worker-2'))
        self.assertIsNone(restarted.get(first)['submitted'])
        with self.assertRaises(ValueError):
            restarted.claim_dispatch(first)
        restarted.fail(first, task['claim_token'], 'Model unavailable, before Send', uncertain=False)
        self.assertEqual(restarted.claim_next('worker-2')['request_id'], second)
        restarted.queue(first)
        self.assertFalse(restarted.get(first)['queued'])

    def test_parallel_workers_share_one_desktop_lane(self):
        for i in range(8):
            self.prepare(f'Request {i}')
        with ThreadPoolExecutor(max_workers=8) as pool:
            tasks = list(pool.map(lambda i: Store(self.path).claim_next(f'worker-{i}'), range(8)))
        self.assertEqual(sum(task is not None for task in tasks), 1)
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM requests WHERE attempt_id IS NOT NULL').fetchone()[0], 1)

    def test_receipt_attribution_response_and_idempotency(self):
        request = self.prepare()
        task = self.store.claim_next('worker')
        receipt = self.evidence(task)
        self.store.acknowledge_submission(request, task['claim_token'])
        self.store.transition(request, 'running', attempt_id=task['attempt_id'])
        for key, bad in [('request_id', str(uuid4())), ('attempt_id', str(uuid4())),
                         ('workspace', '/wrong'), ('prompt_sha256', 'bad'),
                         ('completion_evidence_verified', False), ('verified_model_label', 'GPT-6.1 Sol High')]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.store.reconcile_receipt(request, {**receipt, key: bad}, attempt_id=task['attempt_id'])
        self.assertIsNone(self.store.response(request)['response_text'])
        result = self.store.reconcile_receipt(request, receipt, attempt_id=task['attempt_id'])
        self.assertEqual(result['state'], 'completed')
        self.assertEqual(self.store.get_response(request)['response_text'], receipt['response_text'])
        self.assertEqual(self.store.reconcile_receipt(request, receipt, attempt_id=task['attempt_id']), result)
        with self.assertRaises(ValueError):
            self.store.complete(request, task['claim_token'], 'Changed', receipt)
        with self.assertRaises(ValueError):
            self.store.fail(request, task['claim_token'], 'Late failure')

    def test_wire_prompt_bound_before_send_and_token_checked(self):
        request = self.prepare()
        task = self.store.claim_next('worker')
        digest = self.store.bind_wire_prompt(request, task['claim_token'], 'wrapped prompt')
        self.assertEqual(digest, hashlib.sha256(b'wrapped prompt').hexdigest())
        with self.assertRaises(ValueError):
            self.store.bind_wire_prompt(request, task['claim_token'], 'changed wrapper')
        receipt = self.evidence(task, 'TOKEN')
        with self.assertRaises(ValueError):
            self.store.reconcile_receipt(request, receipt, attempt_id=task['attempt_id'])
        receipt['wire_prompt_sha256'] = digest
        receipt['expected_response'] = 'OTHER_TOKEN'
        with self.assertRaises(ValueError):
            self.store.reconcile_receipt(request, receipt, attempt_id=task['attempt_id'])
        receipt['expected_response'] = 'TOKEN'
        self.store.complete(request, task['claim_token'], 'TOKEN', receipt)

    def test_migrates_existing_prepared_database(self):
        legacy = Path(self.root) / 'legacy.sqlite'
        request = str(uuid4())
        db = sqlite3.connect(legacy)
        with db:
            db.execute("CREATE TABLE requests(id TEXT PRIMARY KEY,payload TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'prepared',created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
            db.execute('INSERT INTO requests(id,payload) VALUES (?,?)', (request, json.dumps({'prompt': 'old', 'workspace': self.root})))
        db.close()
        migrated = Store(legacy)
        self.assertEqual(migrated.get(request)['state'], 'prepared')
        migrated.queue(request)
        self.assertEqual(migrated.claim_next('worker')['prompt'], 'old')

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from desktop_harness.evals import Evaluations, atomic_text
from desktop_harness.desktop_test import save
from unittest.mock import patch
from desktop_harness.store import Store


class EvalsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.goal = self.root / 'goal.txt'
        self.goal.write_text('Explain queues. Criteria: correct FIFO and a concrete example.')
        self.evals = Evaluations(self.root / 'evals')
        self.evals.create('queues', str(self.goal), str(self.root))
        self.store = Store(self.root / 'requests.sqlite')

    def tearDown(self): self.tmp.cleanup()

    def proposal(self, operation=None):
        return self.evals.hypothesize('queues', 'Explain FIFO with one example.', 'An example will clarify ordering.', operation or str(uuid4()))

    async def complete(self, item):
        async def backend(task):
            return {**task, 'response_text': 'FIFO: first in, first out. A ticket queue serves the earliest arrival.',
                    'completion_evidence_verified': True, 'submission_attempted': True, 'verified_model_label': task['desktop_model'] + ' Medium'}
        return await self.evals.run('queues', item['iteration'], store=self.store, backend=backend)

    def observation(self, verdict='pass', score=5):
        return self.evals.observe('queues', 1, verdict, score, ['Correct FIFO'], [], 'Keep a concrete example.', 'The response states first in, first out and uses ticket arrivals.')

    def test_numbered_files_exact_prompt_memory_and_idempotency(self):
        operation = str(uuid4()); item = self.proposal(operation)
        self.assertEqual(self.proposal(operation), item)
        with self.assertRaises(ValueError): self.proposal()
        result = asyncio.run(self.complete(item))
        self.assertEqual(result['state'], 'completed')
        assessed = self.observation(); self.assertEqual(self.observation(), assessed)
        directory = self.root / 'evals/queues'
        self.assertEqual((directory / 'prompt-0001.txt').read_text(), item['prompt'])
        self.assertEqual((directory / 'response-0001.txt').read_text(), result['response'])
        self.assertEqual(json.loads((directory / 'eval-0001.txt').read_text())['verdict'], 'pass')
        memories = (directory / 'project.txt').read_text().splitlines()
        self.assertEqual(len(memories), 1)
        self.assertEqual(json.loads(memories[0])['request_id'], item['request_id'])
        self.assertEqual(self.proposal()['iteration'], 2)
        with self.assertRaises(ValueError): self.evals.observe('queues', 1, 'fail', 0, [], ['Different'], 'Changed', 'Changed evidence')

    def test_repeated_concurrent_runs_dispatch_once(self):
        async def check():
            item = self.proposal(); calls = []
            async def backend(task):
                calls.append(task['request_id']); await asyncio.sleep(0.05)
                return {**task, 'response_text': 'One answer', 'completion_evidence_verified': True, 'verified_model_label': task['desktop_model'] + ' Medium'}
            await asyncio.gather(*(self.evals.run('queues', 1, store=self.store, backend=backend) for _ in range(3)))
            self.assertEqual(calls, [item['request_id']])
            await self.evals.run('queues', 1, store=self.store, backend=backend)
            self.assertEqual(len(calls), 1)
        asyncio.run(check())

    def test_uncertain_does_not_resend_or_receive_quality_score(self):
        async def check():
            self.proposal(); calls = []
            async def backend(task): calls.append(task); raise RuntimeError('Lost after Send')
            result = await self.evals.run('queues', 1, store=self.store, backend=backend)
            self.assertEqual(result['state'], 'uncertain')
            with self.assertRaises(ValueError): self.observation()
            await self.evals.run('queues', 1, store=self.store, backend=backend)
            self.assertEqual(len(calls), 1)
            self.evals.observe('queues', 1, 'blocked', None, [], ['No verified answer'], 'Reconcile before another run.', 'Lost after Send')
            self.proposal()
            result = await self.evals.run('queues', 2, store=self.store, backend=backend)
            self.assertEqual(result['state'], 'blocked')
            self.assertEqual(len(calls), 1)
        asyncio.run(check())

    def test_validation_traversal_collision_and_immutable_goal(self):
        for name in ('../escape', '/tmp/escape', '.', 'with spaces'):
            with self.assertRaises(ValueError): self.evals.context(name)
        self.goal.write_text('Changed goal')
        with self.assertRaises(ValueError): self.evals.create('queues', str(self.goal), str(self.root))
        with self.assertRaises(ValueError): self.evals.hypothesize('queues', '', 'Hypothesis', str(uuid4()))
        operation = str(uuid4()); self.proposal(operation)
        with self.assertRaises(ValueError): self.evals.hypothesize('queues', 'Different', 'Hypothesis', operation)
        with self.assertRaises(ValueError): self.evals.read('queues', -1)
        with self.assertRaises(ValueError): self.evals.read('queues', True)
        with self.assertRaises(ValueError): self.evals.invocation('queues')

    def test_restart_recovers_projections_and_scenario_prompt(self):
        item = self.proposal(); asyncio.run(self.complete(item)); self.observation()
        directory = self.root / 'evals/queues'
        (directory / 'project.txt').unlink()
        recovered = Evaluations(self.root / 'evals')
        context = recovered.context('queues')
        self.assertEqual(context['memories'][0]['iteration'], 1)
        self.assertTrue((directory / 'project.txt').exists())
        prompt = recovered.invocation('queues')
        self.assertIn('Explain queues.', prompt)
        self.assertIn('Keep a concrete example.', prompt)
        self.assertIn('exactly one', prompt)

    def test_concurrent_hypotheses_allocate_one_number(self):
        operation = str(uuid4())
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.proposal(operation), range(4)))
        self.assertEqual({x['request_id'] for x in results}, {results[0]['request_id']})
        self.assertEqual(len(self.evals.context('queues')['recent_iterations']), 1)

    def test_atomic_writes_use_independent_temporary_files(self):
        path = self.root / 'state.json'
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda i: save(path, {'value': i}), range(40)))
        self.assertIn(json.loads(path.read_text())['value'], range(40))
        self.assertFalse(list(self.root.glob('.state.json.*')))

    def test_backend_setup_failure_is_blocked_and_not_left_queued(self):
        self.proposal()
        with patch('desktop_harness.desktop_backend.DesktopBackend', side_effect=ValueError('Probe missing')):
            result = asyncio.run(self.evals.run('queues', 1, store=self.store))
        self.assertEqual(result['state'], 'blocked')
        self.assertFalse(self.store.get(result['request_id'])['queued'])
        self.assertIsNone(self.store.get(result['request_id'])['attempt_id'])
        self.evals.observe('queues', 1, 'blocked', None, [], ['Probe missing'], 'Compile the probe.', 'No dispatch attempted.')
        self.assertTrue((self.root / 'evals/queues/run-0001.json').exists())

    def test_reconciled_receipt_is_read_without_constructing_gui_backend(self):
        item = self.proposal()
        task = self.store.prepare(item['request_id'], item['prompt'], str(self.root), desktop_model='GPT-5.6 Sol')
        self.store.queue(item['request_id'])
        claimed = self.store.claim_dispatch(item['request_id'])
        evidence = {**claimed, 'response_text': 'Recovered answer.', 'completion_evidence_verified': True, 'verified_model_label': 'GPT-5.6 Sol Medium'}
        self.store.complete(item['request_id'], claimed['attempt_id'], 'Recovered answer.', evidence)
        with patch('desktop_harness.desktop_backend.DesktopBackend', side_effect=AssertionError('GUI backend constructed')):
            result = asyncio.run(self.evals.run('queues', 1, store=self.store))
        self.assertEqual(result['response'], 'Recovered answer.')
        self.assertEqual(result['run']['receipt']['attempt_id'], claimed['attempt_id'])

    def test_sync_and_recovery_prompt_retain_iteration_identity(self):
        item = self.proposal()
        asyncio.run(self.complete(item))
        result = self.evals.sync('queues', 1, store=self.store)
        self.assertEqual(result['request_id'], item['request_id'])
        prompt = self.evals.invocation('queues', 1)
        self.assertIn(item['operation_id'], prompt)
        self.assertIn('Do NOT call eval_hypothesize', prompt)
        self.assertIn('Recover ONLY', prompt)

    def test_halt_is_persistent_blocks_new_dispatch_and_requires_explicit_clear(self):
        item = self.proposal()
        halted = self.evals.abort('queues', 'Unexpected approval UI')
        self.assertEqual(self.evals.abort('queues', 'Another reason'), halted)
        calls = []
        async def backend(task): calls.append(task); raise AssertionError('Must not send')
        result = asyncio.run(self.evals.run('queues', 1, store=self.store, backend=backend))
        self.assertEqual(result['state'], 'blocked')
        self.assertFalse(calls)
        self.assertEqual(Evaluations(self.root / 'evals').context('queues')['halt']['reason'], 'Unexpected approval UI')
        self.evals.observe('queues', 1, 'blocked', None, [], ['Interaction unsupported'], 'Inspect the controls.', 'Unexpected approval UI')
        with self.assertRaises(ValueError): self.proposal()
        with self.assertRaises(ValueError): self.evals.invocation('queues')
        self.evals.unhalt('queues')
        self.assertEqual(self.proposal()['iteration'], 2)

    def test_halt_does_not_clear_uncertain_worker_claim(self):
        self.proposal()
        async def backend(task): raise RuntimeError('Lost receipt')
        result = asyncio.run(self.evals.run('queues', 1, store=self.store, backend=backend))
        self.evals.abort('queues', 'Lost receipt')
        self.evals.unhalt('queues')
        self.assertEqual(self.store.get(result['request_id'])['state'], 'uncertain')
        self.assertEqual(self.store.get(result['request_id'])['attempt_id'], result['run']['attempt_id'])

    def test_default_backend_focus_return_is_optional_and_restored(self):
        item = self.proposal()
        restored = []
        class Backend:
            async def __call__(self, task):
                self_test.assertTrue(self.return_focus)
                self_test.assertFalse(self.require_return_focus)
                return {**task, 'completion_evidence_verified': True, 'response_text': 'Answer', 'verified_model_label': task['desktop_model'] + ' Medium'}
            async def restore_focus(self, request_id): restored.append(request_id)
        self_test = self
        with patch('desktop_harness.desktop_backend.DesktopBackend', return_value=Backend()):
            result = asyncio.run(self.evals.run('queues', 1, store=self.store))
        self.assertEqual(result['state'], 'completed')
        self.assertEqual(restored, [item['request_id']])

    def test_focus_restore_exception_cannot_erase_completed_response(self):
        self.proposal(); warnings = []
        class Backend:
            return_focus = True
            progress = staticmethod(warnings.append)
            async def __call__(self, task):
                return {**task, 'completion_evidence_verified': True, 'response_text': 'Answer', 'verified_model_label': task['desktop_model'] + ' Medium'}
            async def restore_focus(self, request_id): raise RuntimeError('caller closed')
        result = asyncio.run(self.evals.run('queues', 1, store=self.store, backend=Backend()))
        self.assertEqual(result['response'], 'Answer')
        self.assertIn('caller closed', warnings[0])

    def test_transport_retry_clones_exact_candidate_with_new_identity(self):
        item = self.proposal()
        async def failure(task):
            return {'state': 'failed_before_send', 'submission_attempted': False, 'error': 'draft mismatch'}
        asyncio.run(self.evals.run('queues', 1, store=self.store, backend=failure))
        self.observation('blocked', None)
        self.evals.abort('queues', 'draft mismatch')
        operation = str(uuid4())
        with self.assertRaises(ValueError): self.evals.retry_transport('queues', 1, operation, store=self.store)
        self.evals.unhalt('queues')
        retry = self.evals.retry_transport('queues', 1, operation, store=self.store)
        self.assertEqual(retry['iteration'], 2)
        self.assertNotEqual(retry['request_id'], item['request_id'])
        self.assertEqual((retry['prompt'], retry['hypothesis'], retry['prompt_sha256']), (item['prompt'], item['hypothesis'], item['prompt_sha256']))
        self.assertEqual(retry, self.evals.retry_transport('queues', 1, operation, store=self.store))
        self.assertEqual(self.store.get(item['request_id'])['state'], 'failed')
        self.assertIn('unchanged candidate', self.evals.invocation('queues', 2))

    def test_uncertain_or_completed_transport_cannot_be_cloned(self):
        self.proposal()
        async def uncertain(task): raise RuntimeError('Send outcome unknown')
        asyncio.run(self.evals.run('queues', 1, store=self.store, backend=uncertain))
        self.observation('blocked', None)
        with self.assertRaises(ValueError): self.evals.retry_transport('queues', 1, str(uuid4()), store=self.store)

    def test_failed_draft_comparison_is_exposed_in_eval_run(self):
        item = self.proposal()
        async def failure(task):
            path = self.root / 'work/worker' / task['request_id'] / task['attempt_id'] / 'selection.json'
            save(path, {'ok': False, 'verification_stage': 'draft_binding', 'draft_comparison': {'expected_value': 'A', 'observed_composers': [{'value':'B'}]}})
            return {'state':'failed_before_send', 'submission_attempted':False, 'error':'draft mismatch'}
        with patch('desktop_harness.evals.Path.cwd', return_value=self.root):
            result = asyncio.run(self.evals.run('queues', 1, store=self.store, backend=failure))
        self.assertEqual(result['run']['diagnostics']['verification_stage'], 'draft_binding')
        self.assertEqual(result['run']['diagnostics']['native_result']['draft_comparison']['expected_value'], 'A')

    def test_completed_iteration_cannot_be_transport_retried(self):
        item = self.proposal(); asyncio.run(self.complete(item)); self.observation()
        with self.assertRaises(ValueError): self.evals.retry_transport('queues', 1, str(uuid4()), store=self.store)

    def test_failed_state_with_submitted_history_cannot_be_transport_retried(self):
        item = self.proposal()
        async def failure(task):
            self.store.acknowledge_submission(task['request_id'], task['attempt_id'])
            return {'state':'failed_before_send', 'submission_attempted':False, 'error':'contradictory backend'}
        asyncio.run(self.evals.run('queues', 1, store=self.store, backend=failure))
        self.observation('blocked', None)
        with self.assertRaises(ValueError): self.evals.retry_transport('queues', 1, str(uuid4()), store=self.store)

    def test_recovered_response_is_attached_without_rewriting_blocked_assessment(self):
        item = self.proposal(); captured = []
        async def uncertain(task):
            captured.append(task)
            raise RuntimeError('reply not attributed')
        asyncio.run(self.evals.run('queues', 1, store=self.store, backend=uncertain))
        self.observation('blocked', None)
        before = (self.root / 'evals/queues/eval-0001.txt').read_bytes()
        task = captured[0]
        self.store.complete(task['request_id'], task['attempt_id'], 'Recovered answer', {**task, 'response_text':'Recovered answer', 'completion_evidence_verified':True, 'verified_model_label':task['desktop_model'] + ' Medium'})
        recovered = self.evals.sync('queues', 1, store=self.store)
        self.assertEqual(recovered['recovery']['response'], 'Recovered answer')
        self.assertEqual(recovered['observation']['verdict'], 'blocked')
        self.assertEqual((self.root / 'evals/queues/eval-0001.txt').read_bytes(), before)
        self.assertEqual((self.root / 'evals/queues/recovered-response-0001.txt').read_text(), 'Recovered answer')

    def test_judge_policy_is_explicit_immutable_and_enforces_completed_judgments(self):
        from test_judging import POLICY, RESPONSE
        self.evals.configure_judge('queues', POLICY)
        with self.assertRaises(ValueError): self.evals.configure_judge('queues', {**POLICY,'criteria':{'C4':'Different'}})
        item=self.proposal()
        async def complete(task):
            return {**task,'completion_evidence_verified':True,'response_text':RESPONSE,'verified_model_label':task['desktop_model']+' Medium'}
        asyncio.run(self.evals.run('queues',1,store=self.store,backend=complete))
        self.assertEqual(self.evals.checks('queues',1,store=self.store)['checks'][0]['status'],'pass')
        with self.assertRaises(ValueError): self.evals.observe('queues',1,'partial',4,[],['late'],'late','evidence')
        row={'criterion':'C4','status':'pass','requirement':POLICY['criteria']['C4'],'evidence_quote':'08:40–08:45','basis':'deterministic_check','check_id':'slot','reason':'Within window'}
        result=self.evals.observe('queues',1,'pass',5,['Within window'],[],'Keep slot.','08:40–08:45',[row],['An earlier slot is optional.'])
        self.assertEqual(result['observation']['suggestions'],['An earlier slot is optional.'])

    def test_transport_history_distinguishes_presend_failure_from_recovered_completion(self):
        self.proposal()
        async def failed(task):return {'state':'failed_before_send','submission_attempted':False,'error':'draft mismatch'}
        asyncio.run(self.evals.run('queues',1,store=self.store,backend=failed));self.observation('blocked',None)
        next_item=self.proposal()
        asyncio.run(self.complete(next_item))
        facts=self.evals.checks('queues',2,store=self.store)['transport_history']
        self.assertEqual([f['fact'] for f in facts],['failed_before_send','completed'])

    def test_quality_review_preserves_recovered_history_and_updates_memory(self):
        item = self.proposal(); captured = []
        async def uncertain(task):
            captured.append(task); raise RuntimeError('Unread reply')
        asyncio.run(self.evals.run('queues', 1, store=self.store, backend=uncertain))
        self.observation('blocked', None)
        self.evals.abort('queues', 'Unread reply')
        directory = self.root / 'evals/queues'
        before = {name: (directory / name).read_bytes() for name in ('eval-0001.txt', 'project.txt')}
        task = captured[0]
        self.store.complete(task['request_id'], task['attempt_id'], 'Recovered FIFO answer', {**task, 'response_text': 'Recovered FIFO answer', 'completion_evidence_verified': True, 'verified_model_label': task['desktop_model'] + ' Medium'})
        self.evals.sync('queues', 1, store=self.store)
        args = ('queues', 1, 'pass', 5, ['Correct ordering'], [], 'Retain FIFO.', 'Recovered FIFO answer')
        result = self.evals.review(*args)
        self.assertEqual(self.evals.review(*args), result)
        self.assertEqual(result['observation']['verdict'], 'blocked')
        self.assertEqual(result['review']['verdict'], 'pass')
        self.assertTrue(self.evals.context('queues')['halt'])
        memory = self.evals.context('queues')['memories'][0]
        self.assertEqual((memory['verdict'], memory['original_verdict'], memory['assessment_source']), ('pass', 'blocked', 'supplemental_review'))
        for name, content in before.items(): self.assertEqual((directory / name).read_bytes(), content)
        self.assertEqual(json.loads((directory / 'review-0001.json').read_text())['verdict'], 'pass')
        self.assertEqual(len((directory / 'reviews.txt').read_text().splitlines()), 1)
        self.assertIn('eval_review', self.evals.invocation('queues', review_iteration=1))
        with self.assertRaises(ValueError): self.evals.review('queues', 1, 'fail', 0, [], ['Changed'], 'Changed', 'Changed')

    def test_review_requires_answer_and_validates_suggestions(self):
        self.proposal()
        args = ('queues', 1, 'pass', 5, ['Correct'], [], 'Retain.', 'FIFO')
        with self.assertRaises(ValueError): self.evals.review(*args)
        with self.assertRaises(ValueError): self.evals.invocation('queues', review_iteration=1)
        asyncio.run(self.complete(self.evals.read('queues', 1))); self.observation()
        for invalid in ('', {}, False):
            with self.assertRaises(ValueError): self.evals.review(*args, suggestions=invalid)
        with self.assertRaises(ValueError): self.evals.review('queues', 1, 'blocked', None, [], [], 'Blocked', 'Evidence')

    def test_history_does_not_call_contradictory_failed_state_presend(self):
        self.proposal()
        async def failure(task):
            self.store.acknowledge_submission(task['request_id'], task['attempt_id'])
            return {'state': 'failed_before_send', 'submission_attempted': False, 'error': 'Contradiction'}
        asyncio.run(self.evals.run('queues', 1, store=self.store, backend=failure))
        fact = self.evals.checks('queues', 1, store=self.store)['transport_history'][0]['fact']
        self.assertEqual(fact, 'failed_after_submission_or_uncertainty')

    def test_review_enforces_rubric_and_literal_evidence(self):
        from test_judging import POLICY, RESPONSE
        self.evals.configure_judge('queues', POLICY); self.proposal()
        async def backend(task):
            return {**task, 'completion_evidence_verified': True, 'response_text': RESPONSE, 'verified_model_label': task['desktop_model'] + ' Medium'}
        asyncio.run(self.evals.run('queues', 1, store=self.store, backend=backend))
        row = {'criterion': 'C4', 'status': 'pass', 'requirement': POLICY['criteria']['C4'], 'evidence_quote': '08:40–08:45', 'basis': 'deterministic_check', 'check_id': 'slot', 'reason': 'Within window'}
        self.evals.observe('queues', 1, 'pass', 5, ['Fits'], [], 'Keep.', '08:40–08:45', [row])
        with self.assertRaises(ValueError): self.evals.review('queues', 1, 'partial', 4, [], ['Too late'], 'Earlier.', '08:40–08:45', [{**row, 'status': 'fail'}])
        with self.assertRaises(ValueError): self.evals.review('queues', 1, 'pass', 5, ['Fits'], [], 'Keep.', 'Evidence', [{**row, 'evidence_quote': 'invented quote'}])
        self.evals.review('queues', 1, 'pass', 5, ['Fits'], [], 'Keep.', '08:40–08:45', [row])

    def test_fixed_case_suffix_blocks_customer_or_policy_edits_before_numbering(self):
        policy = {'schema_version': 1, 'criteria': {'C1': 'Help the customer.'}, 'checks': [], 'fixed_prompt_suffix': 'POLICY\nCUSTOMER: Wrong colour.\nEND CASE'}
        self.evals.configure_judge('queues', policy)
        suffix = policy['fixed_prompt_suffix']; operation = str(uuid4())
        for invalid in (suffix, 'Help.\n'+suffix.replace('Wrong colour.', 'Late delivery.'), 'Help.\n'+suffix+'\nExtra instructions', suffix+'\nHelp.\n'+suffix):
            with self.assertRaisesRegex(ValueError, 'fixed_prompt_suffix'):
                self.evals.hypothesize('queues', invalid, 'Test helpfulness.', operation)
            self.assertEqual(self.evals.context('queues')['total_iterations'], 0)
        prompt = 'Address the legitimate need calmly.\n\n'+suffix
        item = self.evals.hypothesize('queues', prompt, 'Test helpfulness.', operation)
        self.assertEqual(item['iteration'], 1); self.assertEqual(item['prompt'], prompt)
        self.assertEqual(self.evals.hypothesize('queues', prompt, 'Test helpfulness.', operation), item)

    def test_real_helpfulness_quote_can_be_saved_without_changing_answer(self):
        import json
        fixture = json.loads((Path(__file__).parent / 'fixtures/helpfulness-rejected-observation.json').read_text())
        self.evals.configure_judge('queues', fixture['policy']); self.proposal()
        async def backend(task):
            return {**task, 'response_text': fixture['response'], 'completion_evidence_verified': True, 'verified_model_label': task['desktop_model']+' Medium'}
        asyncio.run(self.evals.run('queues', 1, store=self.store, backend=backend))
        args = fixture['arguments']; args = {k:v for k,v in args.items() if k not in ('project','iteration')}
        result = self.evals.observe('queues', 1, **args)
        self.assertEqual(self.evals.observe('queues', 1, **args), result)
        self.assertEqual(result['response'], fixture['response'])
        self.assertEqual(result['observation']['verdict'], 'pass')
        self.assertEqual(result['observation']['evidence_resolutions'][0]['criterion'], 'C2')
        for row in result['observation']['criteria']: self.assertIn(row['evidence_quote'], fixture['response'])

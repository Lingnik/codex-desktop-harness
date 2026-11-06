import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from uuid import uuid4

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def payload(result):
    return result.structuredContent or json.loads(result.content[0].text)


class EvalMCPTest(unittest.TestCase):
    def test_eval_catalog_bound_invocation_and_disabled_dispatch(self):
        async def check(root):
            goal = root / 'goal.txt'; goal.write_text('One-shot scenario with explicit acceptance criteria.')
            operation = str(uuid4())
            env = {**os.environ, 'HARNESS_EVAL_ROOT': str(root / 'evals'),
                   'HARNESS_DB': str(root / 'requests.sqlite'), 'HARNESS_EVAL_ONLY': '1',
                   'HARNESS_EVAL_DESKTOP': '0', 'HARNESS_EVAL_PROJECT': 'demo',
                   'HARNESS_EVAL_OPERATION_ID': operation}
            params = StdioServerParameters(command=sys.executable, args=['-m', 'desktop_harness.server'], env=env)
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as client:
                    await client.initialize()
                    catalog = {tool.name: tool for tool in (await client.list_tools()).tools}
                    self.assertEqual(set(catalog), {'eval_project_create', 'eval_context', 'eval_read', 'eval_hypothesize', 'eval_run', 'eval_observe', 'eval_abort', 'eval_inspect', 'eval_checks', 'eval_review'})
                    self.assertFalse(catalog['eval_run'].annotations.readOnlyHint)
                    self.assertTrue(catalog['eval_hypothesize'].annotations.idempotentHint)
                    self.assertIn('operation_id', catalog['eval_hypothesize'].inputSchema['required'])
                    result = await client.call_tool('eval_project_create', dict(project='demo', scenario_path=str(goal), workspace=str(root)))
                    self.assertFalse(result.isError)
                    context = payload(await client.call_tool('eval_context', {'project': 'demo'}))
                    self.assertEqual(context['operation_id'], operation)
                    self.assertTrue((await client.call_tool('eval_context', {'project': 'other'})).isError)
                    args = dict(project='demo', prompt='Answer the scenario.', hypothesis='A direct instruction improves relevance.', operation_id=operation)
                    first = payload(await client.call_tool('eval_hypothesize', args))
                    self.assertEqual(payload(await client.call_tool('eval_hypothesize', args)), first)
                    self.assertTrue((await client.call_tool('eval_hypothesize', {**args, 'operation_id': str(uuid4())})).isError)
                    self.assertTrue((await client.call_tool('eval_run', dict(project='demo', iteration=1))).isError)
                    item = payload(await client.call_tool('eval_read', dict(project='demo', iteration=1)))
                    self.assertEqual(item['state'], 'hypothesized')
                    checks = payload(await client.call_tool('eval_checks', dict(project='demo', iteration=1)))
                    self.assertFalse(checks['configured'])
                    self.assertEqual(checks['transport_history'][0]['fact'], 'not_completed_or_unavailable')
                    self.assertTrue(catalog['eval_checks'].annotations.readOnlyHint)
                    schema = json.dumps(catalog['eval_review'].inputSchema)
                    self.assertIn('evidence_quote', schema)
                    self.assertIn('contiguous', schema)
                    self.assertIn('requirement', schema)
                    self.assertFalse((root / 'requests.sqlite').exists())
        with tempfile.TemporaryDirectory() as temporary:
            asyncio.run(check(Path(temporary)))

    def test_transport_failure_automatically_halts_even_without_agent_abort_call(self):
        from unittest.mock import patch, AsyncMock
        from desktop_harness.evals import Evaluations
        from desktop_harness.server import eval_run
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); goal = root / 'goal.txt'; goal.write_text('Scenario')
            operation = str(uuid4())
            with patch.dict(os.environ, {'HARNESS_EVAL_ROOT': str(root / 'evals'), 'HARNESS_EVAL_DESKTOP': '1',
                                         'HARNESS_EVAL_PROJECT': 'demo', 'HARNESS_EVAL_OPERATION_ID': operation}):
                evaluations = Evaluations(); evaluations.create('demo', str(goal), str(root))
                evaluations.hypothesize('demo', 'Prompt', 'Hypothesis', operation)
                result = {'state': 'uncertain', 'run': {'error': 'Unsupported interaction'}}
                with patch.object(Evaluations, 'run', AsyncMock(return_value=result)):
                    self.assertEqual(asyncio.run(eval_run('demo', 1)), result)
                self.assertEqual(evaluations.context('demo')['halt']['reason'], 'Unsupported interaction')

    def test_review_cannot_write_another_operations_iteration(self):
        from unittest.mock import patch
        from desktop_harness.evals import Evaluations
        from desktop_harness.server import eval_review
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); goal = root / 'goal.txt'; goal.write_text('Scenario')
            with patch.dict(os.environ, {'HARNESS_EVAL_ROOT': str(root / 'evals'), 'HARNESS_EVAL_PROJECT': 'demo', 'HARNESS_EVAL_OPERATION_ID': str(uuid4())}):
                evaluations = Evaluations(); evaluations.create('demo', str(goal), str(root))
                evaluations.hypothesize('demo', 'Prompt', 'Hypothesis', str(uuid4()))
                with self.assertRaises(ValueError): eval_review('demo', 1, 'pass', 5, ['Fits'], [], 'Keep.', 'Evidence')

    def test_review_schema_errors_then_corrected_wire_call_persist_once(self):
        from desktop_harness.evals import Evaluations
        from desktop_harness.store import Store
        from test_judging import POLICY, RESPONSE
        async def check(root):
            goal = root / 'goal.txt'; goal.write_text('Scenario')
            evaluations = Evaluations(root / 'evals'); evaluations.create('demo', str(goal), str(root)); evaluations.configure_judge('demo', POLICY)
            operation = str(uuid4()); evaluations.hypothesize('demo', 'Prompt', 'Hypothesis', operation)
            async def backend(task):
                return {**task, 'completion_evidence_verified': True, 'response_text': RESPONSE, 'verified_model_label': task['desktop_model'] + ' Medium'}
            await evaluations.run('demo', 1, store=Store(root / 'requests.sqlite'), backend=backend)
            row = dict(criterion='C4', status='pass', requirement=POLICY['criteria']['C4'], evidence_quote='Ordinary-ticket slot: 08:40–08:45', reason='Inside allowed interval.', basis='deterministic_check', check_id='slot')
            evaluations.observe('demo', 1, 'pass', 5, ['Fits'], [], 'Keep.', 'Fits', [row])
            env = {**os.environ, 'HARNESS_EVAL_ROOT': str(root / 'evals'), 'HARNESS_DB': str(root / 'requests.sqlite'), 'HARNESS_EVAL_ONLY': '1', 'HARNESS_EVAL_DESKTOP': '0', 'HARNESS_EVAL_PROJECT': 'demo', 'HARNESS_EVAL_OPERATION_ID': operation}
            params = StdioServerParameters(command=sys.executable, args=['-m', 'desktop_harness.server'], env=env)
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as client:
                    await client.initialize()
                    args = dict(project='demo', iteration=1, verdict='pass', score=5, strengths=['Fits'], weaknesses=[], takeaway='Keep.', evidence='Fits', criteria=[row])
                    invalid = {**row, 'exact_requirement': row['requirement']}; del invalid['requirement']
                    result = await client.call_tool('eval_review', {**args, 'criteria': [invalid]})
                    self.assertTrue(result.isError)
                    self.assertIn('requirement', result.content[0].text)
                    self.assertNotIn('review', evaluations.read('demo', 1))
                    result = await client.call_tool('eval_review', {**args, 'criteria': [{**row, 'evidence_quote': '08:40 ... 08:45'}], 'weaknesses': ['Prefer earlier']})
                    self.assertTrue(result.isError)
                    self.assertIn('literal', result.content[0].text); self.assertIn('weaknesses=[]', result.content[0].text)
                    result = await client.call_tool('eval_review', args)
                    self.assertFalse(result.isError)
                    self.assertEqual(evaluations.read('demo', 1)['review']['criteria'], [row])
                    self.assertFalse((await client.call_tool('eval_review', args)).isError)
                    self.assertEqual(len((root / 'evals/demo/reviews.txt').read_text().splitlines()), 1)
        with tempfile.TemporaryDirectory() as temporary: asyncio.run(check(Path(temporary)))

"""Public MCP contract, validated over a real subprocess/stdio connection."""
import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from uuid import uuid4

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from desktop_harness.store import Store


@asynccontextmanager
async def server(root):
    params = StdioServerParameters(command=sys.executable, args=['-m', 'desktop_harness.server'],
                                  env={**os.environ, 'HARNESS_DB': str(root / 'requests.sqlite')})
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as client:
            await client.initialize()
            yield client


def payload(result):
    return result.structuredContent or json.loads(result.content[0].text)


class ServerContractTest(unittest.TestCase):
    def test_schemas_annotations_and_invalid_requests_have_no_effect(self):
        async def check(root):
            async with server(root) as client:
                tools = {tool.name: tool for tool in (await client.list_tools()).tools}
                self.assertEqual(set(tools), {'adapter_capabilities', 'prepare_request', 'submit_request', 'request_status', 'get_response', 'eval_project_create', 'eval_context', 'eval_read', 'eval_hypothesize', 'eval_run', 'eval_observe', 'eval_abort', 'eval_inspect', 'eval_checks', 'eval_review'})
                self.assertIn('request_id', tools['submit_request'].inputSchema['required'])
                self.assertIn('rendered text', tools['get_response'].description)
                self.assertIn('Markdown', tools['get_response'].description)
                self.assertTrue(tools['submit_request'].annotations.idempotentHint)
                for name in ('adapter_capabilities', 'request_status', 'get_response'):
                    self.assertTrue(tools[name].annotations.readOnlyHint)
                base = {'request_id': str(uuid4()), 'prompt': 'Valid', 'workspace': str(root)}
                invalid = [{**base, 'request_id': 'bad'}, {**base, 'prompt': ''},
                           {**base, 'prompt': 'é' * 16001}, {**base, 'workspace': 'relative'},
                           {**base, 'workspace': str(root / 'missing')}, {**base, 'desktop_model': ''},
                           {k: v for k, v in base.items() if k != 'request_id'}]
                for arguments in invalid:
                    with self.subTest(arguments={k: str(v)[:25] for k, v in arguments.items()}):
                        self.assertTrue((await client.call_tool('submit_request', arguments)).isError)
                for name in ('request_status', 'get_response'):
                    self.assertTrue((await client.call_tool(name, {'request_id': str(uuid4())})).isError)
                self.assertTrue((await client.call_tool('not_a_tool', {})).isError)
                with Store(root / 'requests.sqlite').connect() as db:
                    self.assertEqual(db.execute('SELECT count(*) FROM requests').fetchone()[0], 0)
        with tempfile.TemporaryDirectory() as temporary:
            asyncio.run(check(Path(temporary)))

    def test_adapter_capabilities_expose_rendered_text_response_format(self):
        async def check(root):
            async with server(root) as client:
                caps = payload(await client.call_tool('adapter_capabilities', {}))
                self.assertEqual(caps['response_format'], 'rendered_text')
                self.assertFalse(caps['preserves_markdown'])
                # Existing capability fields must be preserved.
                self.assertEqual(caps['backend'], 'deep-link + native accessibility')
                self.assertTrue(caps['prepare'])
                self.assertFalse(caps['live_submission'])
                self.assertFalse(caps['completion_observation'])
                self.assertFalse(caps['private_ipc'])
                self.assertIn('note', caps)
                self.assertTrue(caps['worker_queue'])
                self.assertFalse(caps['direct_mcp_dispatch'])
                self.assertTrue(caps['worker_required'])
                self.assertEqual(caps['general_response_reader'], 'live_validated_rendered_ax_text')
        with tempfile.TemporaryDirectory() as temporary:
            asyncio.run(check(Path(temporary)))

    def test_restart_retry_collision_and_completed_receipt(self):
        async def check(root):
            identifier = str(uuid4())
            arguments = {'request_id': identifier, 'prompt': 'Explain a queue.', 'workspace': str(root), 'desktop_model': 'GPT-5.6 Sol'}
            async with server(root) as client:
                result = await client.call_tool('submit_request', arguments)
                self.assertFalse(result.isError)
                self.assertTrue(payload(result)['queued'])
            async with server(root) as client:
                self.assertEqual(payload(await client.call_tool('submit_request', arguments))['request_id'], identifier)
                self.assertTrue((await client.call_tool('submit_request', {**arguments, 'prompt': 'Changed'})).isError)
                self.assertIsNone(payload(await client.call_tool('get_response', {'request_id': identifier}))['response_text'])
                store = Store(root / 'requests.sqlite')
                task = store.claim_dispatch(identifier, 'test-worker')
                with self.assertRaises(ValueError):
                    store.complete(identifier, task['claim_token'], 'Forged', {**task, 'completion_evidence_verified': False})
                self.assertEqual(payload(await client.call_tool('request_status', {'request_id': identifier}))['state'], 'uncertain')
                self.assertIsNone(payload(await client.call_tool('get_response', {'request_id': identifier}))['response_text'])
                receipt = {**task, 'completion_evidence_verified': True, 'verified_model_label': 'GPT-5.6 Sol Medium'}
                store.complete(identifier, task['claim_token'], 'Verified answer.', receipt)
            async with server(root) as client:
                response = payload(await client.call_tool('get_response', {'request_id': identifier}))
                self.assertEqual(response['response_text'], 'Verified answer.')
                self.assertEqual(response['state'], 'completed')
                replay = payload(await client.call_tool('submit_request', arguments))
                self.assertEqual(replay['state'], 'completed')
                self.assertEqual(replay['attempt_id'], task['attempt_id'])
                with store.connect() as db:
                    self.assertEqual(db.execute('SELECT count(*) FROM requests').fetchone()[0], 1)
        with tempfile.TemporaryDirectory() as temporary:
            asyncio.run(check(Path(temporary)))

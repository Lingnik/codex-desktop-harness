import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class MCPTest(unittest.TestCase):
    def test_real_stdio_roundtrip(self):
        async def check(root):
            params = StdioServerParameters(command=sys.executable,
                args=['-m', 'desktop_harness.server'],
                env={**os.environ, 'HARNESS_DB': str(Path(root) / 'requests.sqlite')})
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    names = {t.name for t in (await session.list_tools()).tools}
                    self.assertEqual(names, {'prepare_request', 'request_status', 'adapter_capabilities',
                                             'submit_request', 'get_response', 'eval_project_create', 'eval_context', 'eval_read', 'eval_hypothesize', 'eval_run', 'eval_observe', 'eval_abort', 'eval_inspect', 'eval_checks', 'eval_review'})
                    request_id = str(uuid4())
                    result = await session.call_tool('prepare_request', {
                        'request_id': request_id, 'prompt': 'Reply SPIKE_OK', 'workspace': root})
                    self.assertFalse(result.isError)
                    status = await session.call_tool('request_status', {'request_id': request_id})
                    payload = status.structuredContent or json.loads(status.content[0].text)
                    self.assertEqual(payload['state'], 'prepared')
                    self.assertFalse(payload['submitted'])
                    collision = await session.call_tool('prepare_request', {
                        'request_id': request_id, 'prompt': 'Different', 'workspace': root})
                    self.assertTrue(collision.isError)
        with tempfile.TemporaryDirectory() as root:
            asyncio.run(check(root))

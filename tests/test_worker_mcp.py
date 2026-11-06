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


class WorkerMCPTest(unittest.TestCase):
    def test_queue_retry_and_pending_response_over_real_stdio(self):
        async def check(root):
            params = StdioServerParameters(command=sys.executable,
                args=['-m', 'desktop_harness.server'],
                env={**os.environ, 'HARNESS_DB': str(Path(root) / 'requests.sqlite')})
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    names = {tool.name for tool in (await session.list_tools()).tools}
                    self.assertTrue({'submit_request', 'get_response', 'request_status'} <= names)
                    args = {'request_id': str(uuid4()), 'prompt': 'Explain hello world.',
                            'workspace': root, 'desktop_model': 'GPT-5.6 Sol'}
                    for _ in range(2):
                        queued = await session.call_tool('submit_request', args)
                        self.assertFalse(queued.isError)
                        status = queued.structuredContent or json.loads(queued.content[0].text)
                        self.assertEqual(status['state'], 'prepared')
                        self.assertTrue(status['queued'])
                        self.assertFalse(status['submitted'])
                    response = await session.call_tool('get_response', {'request_id': args['request_id']})
                    self.assertFalse(response.isError)
                    payload = response.structuredContent or json.loads(response.content[0].text)
                    self.assertNotEqual(payload['state'], 'completed')
                    self.assertIsNone(payload.get('response_text'))
                    collision = await session.call_tool('submit_request', {**args, 'prompt': 'Changed'})
                    self.assertTrue(collision.isError)
        with tempfile.TemporaryDirectory() as root:
            asyncio.run(check(root))

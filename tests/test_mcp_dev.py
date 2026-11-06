import asyncio
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
from contextlib import asynccontextmanager
import anyio
from uuid import uuid4
from datetime import timedelta

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from desktop_harness.mcp_dev import Supervisor, source_files, legacy_requests, serve
from mcp import types
from mcp.shared.message import SessionMessage


def data(result):
    return result.structuredContent or json.loads(result.content[0].text)


def copy_server(root):
    source = Path(__file__).resolve().parents[1]
    _, files = source_files(source)
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


class DevelopmentServerTest(unittest.TestCase):
    def test_handshake_does_not_wait_for_slow_startup_gate(self):
        async def check(root):
            entered, release = asyncio.Event(), asyncio.Event()
            async def slow_gate(target):
                entered.set()
                await release.wait()
                return False
            client_writer, server_reader = anyio.create_memory_object_stream(0)
            server_writer, client_reader = anyio.create_memory_object_stream(0)
            @asynccontextmanager
            async def transport():
                yield server_reader, server_writer
            with patch('desktop_harness.mcp_dev.stdio_server', transport):
                task = asyncio.create_task(serve(root, validator=slow_gate))
                try:
                    async with ClientSession(client_reader, client_writer) as client:
                        await entered.wait()
                        await asyncio.wait_for(client.initialize(), 2)
                        self.assertFalse(release.is_set())
                        catalog = asyncio.create_task(client.list_tools())
                        await asyncio.sleep(0.05)
                        self.assertFalse(catalog.done())
                        release.set()
                        result = await asyncio.wait_for(catalog, 2)
                        self.assertEqual({t.name for t in result.tools}, {'development_status', 'development_retry'})
                finally:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
        with tempfile.TemporaryDirectory() as temporary:
            asyncio.run(check(Path(temporary)))

    def test_discovery_fallback_preserves_id_and_forwards_legacy_requests(self):
        async def check():
            messages = [SessionMessage(types.JSONRPCMessage(types.JSONRPCRequest(
                jsonrpc='2.0', id=42, method='server/discover'))),
                SessionMessage(types.JSONRPCMessage(types.JSONRPCRequest(
                    jsonrpc='2.0', id=43, method='initialize')))]
            class Reader:
                def __aiter__(self): return self
                async def __anext__(self):
                    if messages: return messages.pop(0)
                    raise StopAsyncIteration
            class Sink:
                def __init__(self): self.messages = []
                async def send(self, value): self.messages.append(value)
                async def __aenter__(self): return self
                async def __aexit__(self, *args): pass
            writer, forwarded = Sink(), Sink()
            await legacy_requests(Reader(), writer, forwarded)
            self.assertEqual(writer.messages[0].message.root.id, 42)
            self.assertEqual(writer.messages[0].message.root.error.code, -32601)
            self.assertEqual(forwarded.messages[0].message.root.id, 43)
        asyncio.run(check())

    def test_stable_mcp_connection_survives_watched_edit_and_failing_tests(self):
        async def check(root):
            source = Path(__file__).resolve().parents[1]
            # A small isolated fixture avoids recursive testing of the supervisor.
            shutil.copytree(source / 'src', root / 'src', ignore=shutil.ignore_patterns('__pycache__'))
            (root / 'tests').mkdir()
            test = root / 'tests/test_gate.py'
            test.write_text('import unittest\nclass Gate(unittest.TestCase):\n def test_valid(self): self.assertTrue(True)\n')
            params = StdioServerParameters(command=sys.executable, args=['-m', 'desktop_harness.mcp_dev'],
                cwd=str(root), env={**os.environ, 'PYTHONPATH': str(root / 'src'), 'HARNESS_DB': str(root / 'requests.sqlite')})
            async with stdio_client(params) as (reader, writer):
                async with ClientSession(reader, writer, read_timeout_seconds=timedelta(seconds=60)) as client:
                    await client.initialize()
                    initial = data(await client.call_tool('development_status', {}))
                    self.assertEqual(initial['state'], 'ready', initial)
                    args = {'request_id': str(uuid4()), 'prompt': 'Durable queue', 'workspace': str(root)}
                    self.assertFalse((await client.call_tool('submit_request', args)).isError)
                    server_source = root / 'src/desktop_harness/server.py'
                    with server_source.open('a') as output:
                        output.write('\n# reload through the same MCP connection\n')
                    async def wait_for(predicate):
                        async def wait():
                            while True:
                                state = data(await client.call_tool('development_status', {}))
                                if predicate(state): return state
                                await asyncio.sleep(0.1)
                        return await asyncio.wait_for(wait(), 20)
                    changed = await wait_for(lambda s: s['state'] == 'ready' and s['active_revision'] != initial['active_revision'])
                    self.assertEqual(data(await client.call_tool('request_status', {'request_id': args['request_id']}))['state'], 'prepared')
                    test.write_text('import unittest\nclass Gate(unittest.TestCase):\n def test_invalid(self): self.fail("candidate rejected")\n')
                    rejected = await wait_for(lambda s: s['state'] == 'rejected')
                    self.assertEqual(rejected['active_revision'], changed['active_revision'])
                    self.assertFalse((await client.call_tool('request_status', {'request_id': args['request_id']})).isError)
        with tempfile.TemporaryDirectory() as temporary:
            asyncio.run(check(Path(temporary)))

    def test_real_child_restart_keeps_queue_and_rejects_broken_candidate(self):
        async def check(root):
            copy_server(root)
            validations = []
            async def validate(target):
                validations.append(target)
                return 'SYNTAX_ERROR' not in (target / 'src/desktop_harness/server.py').read_text()
            supervisor = Supervisor(root, root / 'requests.sqlite', validator=validate)
            try:
                await supervisor.reload()
                self.assertEqual(supervisor.status()['state'], 'ready')
                initial = supervisor.active_revision
                original_child = supervisor.active
                args = {'request_id': str(uuid4()), 'prompt': 'Keep across reload.', 'workspace': str(root)}
                self.assertFalse((await supervisor.call('submit_request', args)).isError)
                source = root / 'src/desktop_harness/server.py'
                original = source.read_text()
                source.write_text(original + '\n# reload change\n')
                await supervisor.reload()
                self.assertNotEqual(initial, supervisor.active_revision)
                self.assertTrue(original_child.task.done())
                self.assertEqual(data(await supervisor.call('request_status', {'request_id': args['request_id']}))['state'], 'prepared')
                self.assertEqual(data(await supervisor.call('submit_request', args))['request_id'], args['request_id'])
                passing = supervisor.active_revision
                source.write_text('SYNTAX_ERROR\n')
                await supervisor.reload()
                self.assertEqual(supervisor.status()['state'], 'rejected')
                self.assertEqual(supervisor.active_revision, passing)
                self.assertFalse((await supervisor.call('request_status', {'request_id': args['request_id']})).isError)
                self.assertEqual(len(validations), 3)
            finally:
                await supervisor.close()
        with tempfile.TemporaryDirectory() as temporary:
            asyncio.run(check(Path(temporary)))

    def test_failed_first_generation_exposes_status_without_child(self):
        async def check(root):
            (root / 'src').mkdir()
            (root / 'src/server.py').write_text('bad')
            async def reject(target):
                return False
            supervisor = Supervisor(root, root / 'requests.sqlite', validator=reject)
            await supervisor.reload()
            self.assertIsNone(supervisor.active)
            self.assertEqual(supervisor.status()['state'], 'rejected')
            with self.assertRaisesRegex(RuntimeError, 'No passing'):
                await supervisor.call('submit_request', {})
        with tempfile.TemporaryDirectory() as temporary:
            asyncio.run(check(Path(temporary)))

    def test_inflight_call_drains_before_swap_and_is_not_replayed(self):
        async def check(root):
            (root / 'src').mkdir()
            source = root / 'src/server.py'
            source.write_text('first')
            started, release = asyncio.Event(), asyncio.Event()
            calls = []
            class Child:
                def __init__(self, *args):
                    self.closed = False
                async def start(self):
                    return self
                async def call(self, name, args):
                    calls.append(name)
                    started.set()
                    await release.wait()
                    return 'original result'
                async def close(self):
                    self.closed = True
            async def accept(target):
                return True
            supervisor = Supervisor(root, root / 'requests.sqlite', validator=accept, child_factory=Child)
            await supervisor.reload()
            first = supervisor.active
            task = asyncio.create_task(supervisor.call('submit_request', {}))
            await started.wait()
            source.write_text('second')
            reload = asyncio.create_task(supervisor.reload())
            await asyncio.sleep(0.05)
            self.assertIs(supervisor.active, first)
            self.assertFalse(first.closed)
            release.set()
            self.assertEqual(await task, 'original result')
            await reload
            self.assertTrue(first.closed)
            self.assertEqual(calls, ['submit_request'])
            await supervisor.close()
        with tempfile.TemporaryDirectory() as temporary:
            asyncio.run(check(Path(temporary)))

    def test_source_change_during_tests_cannot_be_promoted(self):
        async def check(root):
            (root / 'src').mkdir()
            source = root / 'src/server.py'
            source.write_text('first')
            async def editing_validator(target):
                source.write_text('changed during validation')
                return True
            supervisor = Supervisor(root, root / 'requests.sqlite', validator=editing_validator)
            await supervisor.reload()
            self.assertEqual(supervisor.status()['state'], 'superseded')
            self.assertIsNone(supervisor.active)
        with tempfile.TemporaryDirectory() as temporary:
            asyncio.run(check(Path(temporary)))

    def test_runtime_files_do_not_trigger_reload(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'src').mkdir()
            (root / 'src/server.py').write_text('source')
            initial = source_files(root)[0]
            (root / 'work').mkdir()
            (root / 'work/requests.sqlite').write_text('runtime')
            (root / 'src/__pycache__').mkdir()
            (root / 'src/__pycache__/cache.pyc').write_bytes(b'bytecode')
            self.assertEqual(source_files(root)[0], initial)

    def test_symlink_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'src').mkdir()
            (root / 'src/escape').symlink_to('/tmp')
            with self.assertRaisesRegex(ValueError, 'Symlinks'):
                source_files(root)

"""Stable MCP connection; test-gated replacement of an immutable child generation.

Stdout is exclusively MCP. Tests/logs/snapshots are local under work/. A failed
candidate leaves the last passing child running. Calls are never replayed.
"""
import asyncio
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import sys
import anyio

from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client
from mcp.server import NotificationOptions, Server
from mcp.server.stdio import stdio_server
from mcp.shared.message import SessionMessage

from .desktop_test import save


RESERVED = {'development_status', 'development_retry'}


async def legacy_requests(reader, writer, forwarded):
    """Reject modern discovery with a correlated method error so clients fall back.

    Python MCP v1 validates unknown methods as invalid parameters. New clients
    require MethodNotFound for discovery fallback; do not advertise modern MCP.
    """
    async with forwarded:
        async for message in reader:
            body = message.message.root if isinstance(message, SessionMessage) else None
            if isinstance(body, types.JSONRPCRequest) and body.method == 'server/discover':
                await writer.send(SessionMessage(types.JSONRPCMessage(types.JSONRPCError(
                    jsonrpc='2.0', id=body.id,
                    error=types.ErrorData(code=-32601, message='Method not found')))))
            else:
                await forwarded.send(message)


def source_files(root):
    files = {}
    for directory in ('src', 'tests', 'native', 'config', 'scripts'):
        for path in sorted((root / directory).rglob('*')):
            if path.is_symlink():
                raise ValueError('Symlinks are not supported in reload inputs: ' + str(path))
            if path.is_file() and '__pycache__' not in path.parts and path.suffix not in ('.pyc', '.pyo'):
                files[str(path.relative_to(root))] = path.read_bytes()
    for name in ('pyproject.toml', 'uv.lock'):
        path = root / name
        if path.is_file():
            files[name] = path.read_bytes()
    digest = hashlib.sha256()
    for name, content in sorted(files.items()):
        digest.update(name.encode() + b'\0' + content + b'\0')
    return digest.hexdigest(), files


def snapshot(root, revision, files):
    target = root / 'work/mcp-generations' / revision
    if not (target / 'ready.json').is_file():
        target.mkdir(parents=True, exist_ok=True, mode=0o700)
        for name, content in files.items():
            path = target / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        save(target / 'ready.json', {'revision': revision})
    return target


async def validate_generation(target):
    """Run Python suite and offline Swift checks using a disposable test database."""
    env = {**os.environ, 'PYTHONPATH': str(target / 'src'),
           'HARNESS_DB': str(target / 'work/validation.sqlite3')}
    # Validation always exercises the ordinary catalog, with GUI execution off.
    env.pop('HARNESS_NATIVE_DIR', None)
    env.pop('HARNESS_EVAL_ONLY', None)
    env.pop('HARNESS_EVAL_DESKTOP', None)
    env.pop('HARNESS_EVAL_PROJECT', None)
    env.pop('HARNESS_EVAL_OPERATION_ID', None)
    log = target / 'validation.log'
    commands = [[sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-q']]
    if (target / 'native/AXPickerProbe.swift').is_file():
        (target / '.build').mkdir(exist_ok=True)
        commands.extend([['/usr/bin/swiftc', 'native/AXPickerProbe.swift', '-o', '.build/ax-picker-probe'],
                         [str(target / '.build/ax-picker-probe'), '--self-test']])
    if (target / 'native/AXInspect.swift').is_file():
        (target / '.build').mkdir(exist_ok=True)
        commands.append(['/usr/bin/swiftc', 'native/AXInspect.swift', '-o', '.build/ax-inspect'])
    with log.open('wb') as output:
        log.chmod(0o600)
        for command in commands:
            process = await asyncio.create_subprocess_exec(*command, cwd=target, env=env,
                                                         stdout=output, stderr=output)
            try:
                code = await asyncio.wait_for(process.wait(), 180)
            except BaseException:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
                raise
            if code != 0:
                return False
    return True


class Child:
    """Each actor owns its MCP contexts on one task, including context teardown."""
    def __init__(self, root, generation, db):
        self.root, self.generation, self.db = root, generation, db
        self.queue = asyncio.Queue()
        self.ready = asyncio.get_running_loop().create_future()
        self.task = asyncio.create_task(self.run())
        self.catalog = []

    async def run(self):
        current = None
        try:
            params = StdioServerParameters(command=sys.executable, args=['-m', 'desktop_harness.server'],
                cwd=str(self.root), env={**os.environ, 'PYTHONPATH': str(self.generation / 'src'), 'HARNESS_DB': str(self.db),
                    'HARNESS_NATIVE_DIR': str(self.generation / '.build')})
            async with stdio_client(params) as (reader, writer):
                async with ClientSession(reader, writer, read_timeout_seconds=timedelta(seconds=900)) as client:
                    await client.initialize()
                    self.catalog = (await client.list_tools()).tools
                    if RESERVED & {tool.name for tool in self.catalog}:
                        raise ValueError('Child tool conflicts with a supervisor tool')
                    if not self.ready.done():
                        self.ready.set_result(True)
                    while True:
                        item = await self.queue.get()
                        if item is None:
                            break
                        name, arguments, current = item
                        try:
                            result = await client.call_tool(name, arguments)
                            if not current.done():
                                current.set_result(result)
                        except Exception as error:
                            if not current.done():
                                current.set_exception(RuntimeError('Child call failed; not replayed: ' + str(error)))
                        current = None
        except BaseException as error:
            if not self.ready.done():
                self.ready.set_exception(RuntimeError('Child startup failed: ' + str(error)))
            if current is not None and not current.done():
                current.set_exception(RuntimeError('Child exited during call; not replayed'))
        finally:
            while not self.queue.empty():
                item = self.queue.get_nowait()
                if item is not None and not item[2].done():
                    item[2].set_exception(RuntimeError('Child unavailable; not replayed'))

    async def start(self):
        await asyncio.wait_for(asyncio.shield(self.ready), 30)
        return self

    async def call(self, name, arguments):
        if self.task.done():
            raise RuntimeError('Child unavailable; inspect development_status and retry development reload')
        future = asyncio.get_running_loop().create_future()
        self.queue.put_nowait((name, arguments, future))
        return await future

    async def close(self):
        self.queue.put_nowait(None)
        try:
            await asyncio.wait_for(asyncio.shield(self.task), 10)
        except asyncio.TimeoutError:
            self.task.cancel()
            await self.task


class Supervisor:
    def __init__(self, root, db, *, validator=validate_generation, child_factory=Child):
        self.root, self.db = Path(root).resolve(), Path(db).resolve()
        self.validator, self.child_factory = validator, child_factory
        self.active = None
        self.active_revision = None
        self.seen = None
        self.lock = asyncio.Lock()
        self.reload_lock = asyncio.Lock()
        self.listeners = set()
        self.state = {'state': 'starting', 'active_revision': None, 'restart_required_for_supervisor_edits': True}

    def status(self):
        return {**self.state, 'active_revision': self.active_revision, 'database': str(self.db),
                'root': str(self.root), 'calls_replayed': False}

    async def reload(self, *, force=False):
        async with self.reload_lock:
            revision, files = source_files(self.root)
            if not force and revision == self.seen:
                return
            self.seen = revision
            target = snapshot(self.root, revision, files)
            self.state.update(state='testing', candidate_revision=revision, validation_log=str(target / 'validation.log'))
            save(self.root / 'work/mcp-development-status.json', self.status())
            try:
                if not await self.validator(target):
                    self.state.update(state='rejected', error='Candidate tests failed; previous generation retained')
                    return
                if source_files(self.root)[0] != revision:
                    self.state.update(state='superseded', error='Source changed while testing; candidate not promoted')
                    return
                candidate = self.child_factory(self.root, target, self.db)
                try:
                    await candidate.start()
                except BaseException:
                    await candidate.close()
                    raise
                async with self.lock:  # Wait for in-flight calls; never interrupt/replay.
                    old, self.active = self.active, candidate
                    self.active_revision = revision
                    self.state.update(state='ready', error=None)
                    if old is not None:
                        await old.close()
                for listener in list(self.listeners):
                    try:
                        await listener.send_tool_list_changed()
                    except Exception:
                        self.listeners.discard(listener)
            except Exception as error:
                self.state.update(state='rejected', error=str(error))
            finally:
                save(self.root / 'work/mcp-development-status.json', self.status())

    async def call(self, name, arguments):
        async with self.lock:
            if self.active is None:
                raise RuntimeError('No passing server generation; inspect development_status')
            return await self.active.call(name, arguments)

    async def watch(self):
        while True:
            await asyncio.sleep(0.75)
            try:
                revision = source_files(self.root)[0]
                if revision != self.seen:
                    # Debounce editor save sequences.
                    await asyncio.sleep(0.5)
                    await self.reload()
            except Exception as error:
                self.state.update(state='rejected', error=str(error))

    async def close(self):
        if self.active is not None:
            await self.active.close()


async def serve(root=None, *, validator=validate_generation):
    root = Path(root or Path.cwd()).resolve()
    db = Path(os.getenv('HARNESS_DB', str(root / 'work/requests.sqlite3'))).resolve()
    supervisor = Supervisor(root, db, validator=validator)
    startup = asyncio.create_task(supervisor.reload())
    server = Server('Codex Desktop development adapter')
    control_tools = [types.Tool(name=name, description=description,
        inputSchema={'type': 'object', 'properties': {}, 'additionalProperties': False},
        annotations=types.ToolAnnotations(readOnlyHint=name == 'development_status'))
        for name, description in [('development_status', 'Read active/candidate revisions and test failures.'),
                                  ('development_retry', 'Rerun tests and reload the current source if passing; never replays tools.')]]

    @server.list_tools()
    async def list_tools():
        await asyncio.shield(startup)
        supervisor.listeners.add(server.request_context.session)
        return control_tools + (supervisor.active.catalog if supervisor.active else [])

    @server.call_tool(validate_input=False)
    async def call_tool(name, arguments):
        if name in RESERVED:
            if arguments:
                raise ValueError('Development tools take no arguments')
            if name == 'development_retry':
                await supervisor.reload(force=True)
            return supervisor.status()
        return await supervisor.call(name, arguments)

    # Keep the parent initialized/available even if the first candidate fails.
    watcher = None
    try:
        async def watch_after_startup():
            await startup
            await supervisor.watch()
        watcher = asyncio.create_task(watch_after_startup())
        async with stdio_server() as (reader, writer):
            send, receive = anyio.create_memory_object_stream(0)
            async with anyio.create_task_group() as tasks:
                tasks.start_soon(legacy_requests, reader, writer, send)
                await server.run(receive, writer, server.create_initialization_options(
                    notification_options=NotificationOptions(tools_changed=True)))
                tasks.cancel_scope.cancel()
    finally:
        if watcher is not None:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)
        if not startup.done():
            startup.cancel()
        await asyncio.gather(startup, return_exceptions=True)
        await supervisor.close()


def main():
    asyncio.run(serve())


if __name__ == '__main__':
    main()

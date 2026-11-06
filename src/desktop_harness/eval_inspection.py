"""Read-only AX diagnostics for an explicitly authorized external eval harness."""
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from uuid import uuid4

from .evals import Evaluations, atomic_text


async def inspect_desktop(project, window_title=None):
    evaluations = Evaluations()
    context = evaluations.context(project)
    binary = Path(os.getenv('HARNESS_NATIVE_DIR', str(Path.cwd() / '.build'))) / 'ax-inspect'
    if not binary.is_file():
        raise ValueError('Compile native/AXInspect.swift to .build/ax-inspect first')
    arguments = [str(binary)] + ([window_title] if window_title else [])
    process = await asyncio.create_subprocess_exec(*arguments, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        output, errors = await asyncio.wait_for(process.communicate(), 30)
    except BaseException:
        if process.returncode is None:
            process.kill()
            await process.wait()
        raise
    if len(output) > 12_000_000:
        raise ValueError('AX inspection output exceeded diagnostic size limit')
    try:
        snapshot = json.loads(output)
    except (ValueError, UnicodeDecodeError):
        raise ValueError('AX probe returned invalid JSON: ' + errors.decode(errors='replace')[:500])
    record = {'created': datetime.now(timezone.utc).isoformat(), 'project': project,
              'process_exit_code': process.returncode, 'snapshot': snapshot}
    path = Path(context['directory']) / 'diagnostics' / ('ax-' + str(uuid4()) + '.json')
    atomic_text(path, json.dumps(record, indent=2) + '\n')
    controls, texts = [], []
    def visit(node):
        role = node.get('role', '')
        if role in ('AXButton', 'AXRadioButton', 'AXCheckBox', 'AXComboBox', 'AXTextField', 'AXTextArea') and len(controls) < 100:
            controls.append({k: node.get(k) for k in ('role', 'title', 'description', 'identifier', 'enabled', 'actions', 'path')})
        if role in ('AXStaticText', 'AXHeading') and node.get('value') and len(texts) < 100:
            texts.append(str(node['value'])[:800])
        for child in node.get('children', []): visit(child)
    for window in snapshot.get('windows', []): visit(window)
    return {'artifact': str(path), 'ok': snapshot.get('ok', False), 'error': snapshot.get('error'),
            'read_only': True, 'snapshot_incomplete': snapshot.get('incomplete', False),
            'controls': controls, 'visible_text': texts,
            'note': 'Observation only; no app activation, clicks, typing or permission changes. Snapshot paths are not reusable control IDs. Values are capped; inspect the artifact for raw details. Does not automatically answer questions or approvals.'}

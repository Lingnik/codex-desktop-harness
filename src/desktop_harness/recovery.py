"""Reconcile an existing request from its saved, complete AX observation; no GUI."""
import hashlib
import json
from pathlib import Path

from .evals import atomic_text
from .response_reader import inspect_response
from .store import Store


def reconcile_saved(request_id, *, store=None, root=None):
    database = store or Store()
    root = Path(root or Path.cwd()).resolve()
    status = database.get(request_id)
    if status['state'] == 'completed':
        return database.get_response(request_id)
    if status['state'] not in ('uncertain', 'submitted', 'running') or not status['attempt_id']:
        raise ValueError('Saved reconciliation requires an existing active attempt')
    payload = database.payload(request_id)
    directory = root / 'work/worker' / status['request_id'] / status['attempt_id']
    wire = json.loads((directory / 'task.json').read_text())
    expected = {'request_id': status['request_id'], 'attempt_id': status['attempt_id'],
                'workspace': payload['workspace']}
    if any(wire.get(key) != value for key, value in {**expected, 'desktop_model': payload['desktop_model']}.items()):
        raise ValueError('Saved task attribution mismatch')
    wire_hash = hashlib.sha256(wire['prompt'].encode()).hexdigest()
    with database.connect() as db:
        bound_hash = db.execute('SELECT wire_prompt_sha256 FROM requests WHERE id=?', (status['request_id'],)).fetchone()[0]
    if wire_hash != bound_hash:
        raise ValueError('Saved wire prompt hash mismatch')
    claim = json.loads((directory / 'send-claims' / (status['request_id'] + '.json')).read_text())
    if any(claim.get(key) != value for key, value in {**expected, 'wire_prompt_sha256': wire_hash}.items()) or claim.get('submission_attempted') is not True:
        raise ValueError('Saved Send claim attribution mismatch')
    snapshot_file = directory / 'response-snapshot.json'
    reading = inspect_response(json.loads(snapshot_file.read_text()), status['request_id'], wire['prompt'], payload['workspace'], payload['desktop_model'])
    if reading.get('completion_evidence_verified') is not True:
        raise ValueError('Saved observation did not verify completion: ' + reading.get('reason', 'unknown'))
    receipt = {**reading, **expected, 'wire_prompt_sha256': wire_hash,
               'prompt_sha256': status['prompt_sha256'], 'submission_attempted': True,
               'reconciliation_method': 'saved_complete_ax_snapshot', 'snapshot_file': str(snapshot_file)}
    database.complete(status['request_id'], status['attempt_id'], reading['response_text'], receipt)
    atomic_text(directory / 'reconcile-saved.json', json.dumps(receipt, indent=2) + '\n')
    return database.get_response(status['request_id'])

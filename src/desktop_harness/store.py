"""Durable request identity and single-dispatch receipts.

An attempt is consumed before any GUI action. A crash leaves it uncertain, never
eligible for automatic resend. SQLite serializes the one shared Desktop lane.
"""
import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlencode
from uuid import UUID, uuid4

STATES = {'prepared', 'submitted', 'running', 'completed', 'failed', 'uncertain'}
ACTIVE_STATES = ('uncertain', 'submitted', 'running')


class Store:
    def __init__(self, path=None):
        self.path = Path(path or os.getenv('HARNESS_DB', 'work/requests.sqlite3'))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS requests (
                    id TEXT PRIMARY KEY, payload TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'prepared',
                    created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS audit (
                    id INTEGER PRIMARY KEY, request_id TEXT, event TEXT,
                    payload_sha256 TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP
                );
            ''')
            # Serialize additive migration when two external clients start together.
            db.execute('BEGIN IMMEDIATE')
            columns = {row[1] for row in db.execute('PRAGMA table_info(requests)')}
            for name, declaration in {
                'queued': 'INTEGER NOT NULL DEFAULT 0', 'attempt_id': 'TEXT',
                'worker_id': 'TEXT', 'response_text': 'TEXT', 'evidence': 'TEXT',
                'error': 'TEXT', 'updated': 'TEXT', 'wire_prompt_sha256': 'TEXT',
            }.items():
                if name not in columns:
                    db.execute(f'ALTER TABLE requests ADD COLUMN {name} {declaration}')
        self.path.chmod(0o600)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def _id(request_id):
        return str(UUID(request_id))

    @staticmethod
    def _audit(db, request_id, event, payload):
        db.execute('INSERT INTO audit (request_id,event,payload_sha256) VALUES (?,?,?)',
                   (request_id, event, hashlib.sha256(payload.encode()).hexdigest()))

    def prepare(self, request_id: str, prompt: str, workspace: str, desktop_model=None):
        request_id = self._id(request_id)
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt.encode()) > 32000:
            raise ValueError('Prompt must be nonempty and at most 32 KB')
        root = Path(workspace).expanduser()
        if not root.is_absolute() or not root.is_dir():
            raise ValueError('Workspace must be an existing absolute directory')
        task = {'prompt': prompt, 'workspace': str(root.resolve())}
        if desktop_model is not None:
            if not isinstance(desktop_model, str) or not desktop_model.strip():
                raise ValueError('Desktop model must be a nonempty exact label')
            task['desktop_model'] = desktop_model
        payload = json.dumps(task, sort_keys=True)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            prior = db.execute('SELECT payload FROM requests WHERE id=?', (request_id,)).fetchone()
            if prior and prior[0] != payload:
                raise ValueError('Request ID already belongs to a different payload; nothing changed')
            if not prior:
                db.execute('INSERT INTO requests (id,payload) VALUES (?,?)', (request_id, payload))
                self._audit(db, request_id, 'prepared', payload)
        return self.get(request_id)

    def _row(self, db, request_id):
        row = db.execute('SELECT * FROM requests WHERE id=?', (self._id(request_id),)).fetchone()
        if row is None:
            raise ValueError('Unknown request ID')
        return row

    def payload(self, request_id):
        with self.connect() as db:
            row = self._row(db, request_id)
        return {'request_id': row['id'], **json.loads(row['payload'])}

    def get(self, request_id: str):
        with self.connect() as db:
            row = self._row(db, request_id)
        payload = json.loads(row['payload'])
        status = {'request_id': row['id'], 'state': row['state'], 'created': row['created'],
                  'workspace': payload['workspace'], 'queued': bool(row['queued']),
                  'prompt_sha256': hashlib.sha256(payload['prompt'].encode()).hexdigest(),
                  'deep_link': 'codex://new?' + urlencode({'prompt': payload['prompt'], 'path': payload['workspace']}),
                  'submitted': None if row['state'] == 'uncertain' else row['state'] in {'submitted', 'running', 'completed'},
                  'attempt_id': row['attempt_id'], 'claim_token': row['attempt_id'],
                  'worker_id': row['worker_id'], 'error': row['error']}
        if 'desktop_model' in payload:
            status['desktop_model'] = payload['desktop_model']
        if row['state'] == 'prepared':
            status['note'] = 'Prepared only. Opening the link fills the composer; it does not submit.'
        if row['state'] == 'completed':
            status['response_text'] = row['response_text']
        return status

    def queue(self, request_id):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = self._row(db, request_id)
            if row['state'] == 'prepared' and row['attempt_id'] is None and not row['queued']:
                db.execute('UPDATE requests SET queued=1,updated=CURRENT_TIMESTAMP WHERE id=?', (row['id'],))
                self._audit(db, row['id'], 'queued', row['payload'])
        return self.get(request_id)

    def _claim(self, db, row, worker_id):
        attempt_id = str(uuid4())
        db.execute('UPDATE requests SET state=?,queued=0,attempt_id=?,worker_id=?,updated=CURRENT_TIMESTAMP WHERE id=?',
                   ('uncertain', attempt_id, worker_id, row['id']))
        self._audit(db, row['id'], 'dispatch_claimed', row['payload'])
        return {'request_id': row['id'], **json.loads(row['payload']), 'state': 'uncertain',
                'attempt_id': attempt_id, 'claim_token': attempt_id, 'worker_id': worker_id,
                'prompt_sha256': hashlib.sha256(json.loads(row['payload'])['prompt'].encode()).hexdigest()}

    def claim_next(self, worker_id):
        if not isinstance(worker_id, str) or not worker_id.strip():
            raise ValueError('Worker ID must be nonempty')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT 1 FROM requests WHERE state IN ('uncertain','submitted','running') LIMIT 1").fetchone():
                return None
            row = db.execute("SELECT * FROM requests WHERE queued=1 AND state='prepared' AND attempt_id IS NULL ORDER BY created,rowid LIMIT 1").fetchone()
            return self._claim(db, row, worker_id) if row else None

    def claim_dispatch(self, request_id, worker_id='external'):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = self._row(db, request_id)
            if row['state'] != 'prepared' or row['attempt_id'] is not None:
                raise ValueError('Request already claimed; automatic resend prohibited')
            if db.execute("SELECT 1 FROM requests WHERE state IN ('uncertain','submitted','running') LIMIT 1").fetchone():
                raise ValueError('Desktop lane occupied or uncertain; reconcile before dispatch')
            return self._claim(db, row, worker_id)

    def transition(self, request_id, state, *, attempt_id=None, error=None):
        if state not in STATES or state in {'prepared', 'completed'}:
            raise ValueError('Invalid direct transition; completed requires verified receipt')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = self._row(db, request_id)
            if not attempt_id or row['attempt_id'] != attempt_id:
                raise ValueError('Attempt ownership mismatch')
            allowed = {'uncertain': {'submitted', 'running', 'uncertain', 'failed'},
                       'submitted': {'running', 'uncertain', 'failed'},
                       'running': {'uncertain', 'failed'}, 'failed': set(), 'completed': set()}
            if state != row['state'] and state not in allowed.get(row['state'], set()):
                raise ValueError('Invalid lifecycle transition')
            db.execute('UPDATE requests SET state=?,error=?,updated=CURRENT_TIMESTAMP WHERE id=?', (state, error, row['id']))
            self._audit(db, row['id'], state, row['payload'])
        return self.get(request_id)

    def acknowledge_submission(self, request_id, claim_token):
        return self.transition(request_id, 'submitted', attempt_id=claim_token)

    def fail(self, request_id, claim_token, error, uncertain=True):
        return self.transition(request_id, 'uncertain' if uncertain else 'failed', attempt_id=claim_token, error=str(error))

    def bind_wire_prompt(self, request_id, claim_token, wire_prompt):
        if not isinstance(wire_prompt, str) or not wire_prompt.strip():
            raise ValueError('Wire prompt must be nonempty')
        digest = hashlib.sha256(wire_prompt.encode()).hexdigest()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = self._row(db, request_id)
            if row['attempt_id'] != claim_token or row['state'] != 'uncertain':
                raise ValueError('Wire prompt requires current uncertain attempt ownership')
            if row['wire_prompt_sha256'] is not None and row['wire_prompt_sha256'] != digest:
                raise ValueError('Wire prompt cannot change within an attempt')
            db.execute('UPDATE requests SET wire_prompt_sha256=? WHERE id=?', (digest, row['id']))
        return digest

    def complete(self, request_id, claim_token, response_text, evidence):
        if not isinstance(evidence, dict):
            raise ValueError('Completion evidence must be an object')
        if 'response_text' in evidence and evidence['response_text'] != response_text:
            raise ValueError('Receipt response text mismatch')
        return self.reconcile_receipt(request_id, {**evidence, 'response_text': response_text}, attempt_id=claim_token)

    def reconcile_receipt(self, request_id, receipt, *, attempt_id):
        """Accept an attributed native receipt; no inferred success from an exit code.

        The worker must add immutable request attribution from its trusted task;
        native response extraction supplies completion and response text evidence.
        """
        if not isinstance(receipt, dict):
            raise ValueError('Receipt must be an object')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = self._row(db, request_id)
            if not attempt_id or row['attempt_id'] != attempt_id:
                raise ValueError('Attempt ownership mismatch')
            task = json.loads(row['payload'])
            expected = {'request_id': row['id'], 'attempt_id': attempt_id, 'workspace': task['workspace'],
                        'prompt_sha256': hashlib.sha256(task['prompt'].encode()).hexdigest()}
            if any(receipt.get(key) != value for key, value in expected.items()):
                raise ValueError('Receipt request attribution mismatch')
            if row['wire_prompt_sha256'] is not None and receipt.get('wire_prompt_sha256') != row['wire_prompt_sha256']:
                raise ValueError('Receipt wire prompt mismatch')
            text = receipt.get('response_text')
            if receipt.get('completion_evidence_verified') is not True or not isinstance(text, str) or not text.strip():
                raise ValueError('Receipt lacks verified completed response')
            if receipt.get('expected_response') is not None and receipt['expected_response'] != text:
                raise ValueError('Receipt token mismatch')
            if task.get('desktop_model'):
                label = receipt.get('verified_model_label', '')
                if label != task['desktop_model'] and not label.startswith(task['desktop_model'] + ' '):
                    raise ValueError('Receipt model mismatch')
            serialized = json.dumps(receipt, sort_keys=True)
            if row['state'] == 'completed':
                if row['response_text'] != text or row['evidence'] != serialized:
                    raise ValueError('Completed receipt cannot be changed')
            elif row['state'] in ACTIVE_STATES:
                db.execute('UPDATE requests SET state=?,response_text=?,evidence=?,error=NULL,updated=CURRENT_TIMESTAMP WHERE id=?',
                           ('completed', text, serialized, row['id']))
                self._audit(db, row['id'], 'completed', serialized)
            else:
                raise ValueError('Receipt cannot complete an unclaimed or failed request')
        return self.get(request_id)

    def response(self, request_id):
        with self.connect() as db:
            row = self._row(db, request_id)
        return {'request_id': row['id'], 'state': row['state'],
                'response_text': row['response_text'] if row['state'] == 'completed' else None,
                'evidence': json.loads(row['evidence']) if row['state'] == 'completed' else None}

    get_response = response


def capabilities():
    return {'backend': 'deep-link + native accessibility',
            'prepare': True, 'live_submission': False, 'completion_observation': False,
            'private_ipc': False,
            'note': 'MCP queues only; external terminal worker required. Rendered-text Desktop response path is live validated.'}

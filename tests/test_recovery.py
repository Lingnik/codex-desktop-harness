import json
from pathlib import Path
import tempfile
import unittest

from desktop_harness.recovery import reconcile_saved
from desktop_harness.store import Store
from desktop_harness.evals import atomic_text


class RecoveryTest(unittest.TestCase):
    def test_saved_reconciliation_preserves_identity_and_refuses_tampering(self):
        for corruption in ('none', 'wire', 'claim', 'incomplete'):
            with self.subTest(corruption=corruption), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve(); workspace = root / 'codex-desktop-harness'; workspace.mkdir()
                fixtures = Path(__file__).parent / 'fixtures'
                wire = json.loads((fixtures / 'split-prompt-task.json').read_text())
                wire['workspace'] = str(workspace)
                db = Store(root / 'db')
                db.prepare(wire['request_id'], 'Original prompt', str(workspace), desktop_model=wire['desktop_model'])
                db.queue(wire['request_id']); task = db.claim_next('test-worker')
                wire['attempt_id'] = task['attempt_id']
                digest = db.bind_wire_prompt(task['request_id'], task['attempt_id'], wire['prompt'])
                claim = {'request_id':task['request_id'], 'attempt_id':task['attempt_id'], 'workspace':str(workspace), 'wire_prompt_sha256':digest, 'submission_attempted':True}
                data = json.loads((fixtures / 'split-prompt-response.json').read_text())
                if corruption == 'wire': wire['prompt'] += 'changed'
                if corruption == 'claim': claim['attempt_id'] = 'stale'
                if corruption == 'incomplete': data['truncated'] = True
                directory = root / 'work/worker' / task['request_id'] / task['attempt_id']
                for file, content in [('task.json', wire), ('response-snapshot.json', data), ('send-claims/' + task['request_id'] + '.json', claim)]:
                    atomic_text(directory / file, json.dumps(content))
                if corruption != 'none':
                    with self.assertRaises(ValueError): reconcile_saved(task['request_id'], store=db, root=root)
                    self.assertEqual(db.get(task['request_id'])['state'], 'uncertain')
                else:
                    result = reconcile_saved(task['request_id'], store=db, root=root)
                    self.assertIn('08:40–08:45', result['response_text'])
                    self.assertEqual(db.get(task['request_id'])['attempt_id'], task['attempt_id'])
                    self.assertEqual(result, reconcile_saved(task['request_id'], store=db, root=root))

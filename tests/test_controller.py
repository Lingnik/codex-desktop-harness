import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
from desktop_harness.controller import run
from desktop_harness.store import Store


class ControllerPolicyTest(unittest.TestCase):
    def test_model_cannot_change_authorized_payload(self):
        with tempfile.TemporaryDirectory() as root:
            task = {'request_id': str(uuid4()), 'prompt': 'Harmless', 'workspace': root}
            changed = {**task, 'prompt': 'Changed by model'}
            response = {'message': {'role': 'assistant', 'content': '', 'tool_calls': [
                {'function': {'name': 'prepare_request', 'arguments': changed}}]}}
            db_path = str(Path(root) / 'jobs.sqlite')
            with patch.dict(os.environ, {'HARNESS_DB': db_path}), patch(
                    'desktop_harness.controller.chat', return_value=response):
                with self.assertRaises(ExceptionGroup) as failure:
                    asyncio.run(run(json.dumps(task)))
                def messages(error):
                    if isinstance(error, BaseExceptionGroup):
                        return ' '.join(messages(e) for e in error.exceptions)
                    return str(error)
                self.assertIn('altered the authorized draft', messages(failure.exception))
            store = Store(db_path)
            with store.connect() as db:
                self.assertEqual(db.execute('SELECT count(*) FROM requests').fetchone()[0], 0)

import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from uuid import uuid4
from desktop_harness.store import Store


class StoreTest(unittest.TestCase):
    def test_retries_do_not_duplicate_or_mutate(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store(Path(root) / 'jobs.sqlite')
            request_id = str(uuid4())
            first = store.prepare(request_id, 'Hello & newline\n?', root)
            self.assertEqual(first, store.prepare(request_id, 'Hello & newline\n?', root))
            with self.assertRaises(ValueError):
                store.prepare(request_id, 'Changed', root)
            with store.connect() as db:
                self.assertEqual(db.execute('SELECT count(*) FROM requests').fetchone()[0], 1)
                self.assertEqual(db.execute('SELECT count(*) FROM audit').fetchone()[0], 1)
            self.assertFalse(first['submitted'])
            self.assertEqual(first['state'], 'prepared')
            self.assertEqual(parse_qs(urlparse(first['deep_link']).query)['prompt'], ['Hello & newline\n?'])

    def test_invalid_targets_fail(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store(Path(root) / 'jobs.sqlite')
            for workspace in ('relative', root + '/missing'):
                with self.assertRaises(ValueError):
                    store.prepare(str(uuid4()), 'Hello', workspace)
            with self.assertRaises(ValueError):
                store.prepare(str(uuid4()), '', root)

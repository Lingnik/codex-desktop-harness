import asyncio
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from desktop_harness.evals import Evaluations
from desktop_harness.eval_inspection import inspect_desktop


class InspectionTest(unittest.TestCase):
    def test_read_only_inspection_retains_snapshot_and_summarizes_controls(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            goal = root / 'goal.txt'; goal.write_text('Scenario')
            (root / '.build').mkdir(); (root / '.build/ax-inspect').write_text('never executed')
            evaluations = Evaluations(root / 'evals')
            evaluations.create('demo', str(goal), str(root))
            snapshot = {'ok': True, 'read_only': True, 'incomplete': False, 'windows': [{'children': [
                {'role': 'AXButton', 'title': 'Allow', 'enabled': True, 'actions': ['AXPress'], 'path': [0, 1]},
                {'role': 'AXStaticText', 'value': 'Which option do you prefer?'}]}]}
            process = AsyncMock(); process.returncode = 0
            process.communicate.return_value = (json.dumps(snapshot).encode(), b'')
            factory = AsyncMock(return_value=process)
            with patch.dict(os.environ, {'HARNESS_EVAL_ROOT': str(root / 'evals')}), patch('pathlib.Path.cwd', return_value=root), patch('asyncio.create_subprocess_exec', factory):
                result = asyncio.run(inspect_desktop('demo', 'Exact window'))
            self.assertTrue(result['read_only'])
            self.assertEqual(result['controls'][0]['title'], 'Allow')
            self.assertIn('Which option do you prefer?', result['visible_text'])
            self.assertEqual(json.loads(Path(result['artifact']).read_text())['snapshot'], snapshot)
            self.assertEqual(factory.call_args.args, (str(root / '.build/ax-inspect'), 'Exact window'))
            self.assertEqual(factory.await_count, 1)

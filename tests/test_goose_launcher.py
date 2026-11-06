import json
import os
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest
from unittest.mock import patch


class GooseLauncherTest(unittest.TestCase):
    def launch(self, headless=False, halted=False, retry=False, review=False, missing_review=False):
        source = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'scripts').mkdir(); (root / 'config').mkdir(); (root / '.venv/bin').mkdir(parents=True)
            (root / 'scripts/goose-local').write_text((source / 'scripts/goose-local').read_text())
            (root / 'config/goose.json').write_text((source / 'config/goose.json').read_text())
            (root / '.venv/bin/python').touch()
            observed = {}
            def execute(executable, args, env): observed.update(args=args, env=env)
            def command(args, **kwargs):
                env = kwargs['env']
                if len(args) > 2 and args[1] == '-c' and "item.get('review')" in args[2]:
                    return subprocess.CompletedProcess(args, 3 if missing_review else 0)
                if 'eval-status' in args:
                    body = {'recent_iterations': [{'state': 'assessed', 'operation_id': env['HARNESS_EVAL_OPERATION_ID']}]}
                    return subprocess.CompletedProcess(args, 2 if halted else 0, json.dumps(body), '')
                if 'eval-prompt' in args:
                    output = Path(args[args.index('--output') + 1]); output.parent.mkdir(parents=True, exist_ok=True); output.write_text('Fixture prompt')
                return subprocess.CompletedProcess(args, 0)
            args = (['scripts/goose-local', 'eval-review', 'demo', '2'] if review else ['scripts/goose-local', 'eval-retry', 'demo', '2'] if retry else ['scripts/goose-local', 'eval', 'demo']) + (['--headless'] if headless else [])
            with patch('sys.argv', args), patch('os.chdir'), patch('shutil.which', return_value='/fake/goose'), patch('subprocess.run', side_effect=command) as calls, patch('os.execve', execute), patch('subprocess.check_output', return_value='3\n') as replay:
                if headless and (missing_review or (halted and not review)):
                    with self.assertRaises(SystemExit) as failure: runpy.run_path(str(root / 'scripts/goose-local'), run_name='__main__')
                    self.assertEqual(failure.exception.code, 3 if missing_review else 2)
                elif headless and review:
                    with self.assertRaises(SystemExit) as success: runpy.run_path(str(root / 'scripts/goose-local'), run_name='__main__')
                    self.assertEqual(success.exception.code, 0)
                else:
                    runpy.run_path(str(root / 'scripts/goose-local'), run_name='__main__')
                if headless:
                    self.assertFalse(observed)
                    goose = next(call for call in calls.call_args_list if 'desktop_harness.transcripts' in call.args[0])
                    self.assertNotIn('--interactive', goose.args[0])
                else:
                    self.assertIn('--interactive', observed['args'])
                if review:
                    render = next(c for c in calls.call_args_list if 'eval-prompt' in c.args[0])
                    self.assertEqual(render.args[0][-2:], ['--review-iteration', '2'])
                    self.assertEqual(render.kwargs['env']['HARNESS_EVAL_DESKTOP'], '0')
                if retry:
                    self.assertEqual(replay.call_count, 1)
                    render = next(c for c in calls.call_args_list if 'eval-prompt' in c.args[0])
                    self.assertEqual(render.args[0][-2:], ['--resume-iteration', '3'])
                    self.assertIn('retry_transport', replay.call_args.args[0][2])
                profile = json.loads((root / 'work/goose-evals/config/config.yaml').read_text())
                self.assertTrue(profile['extensions']['developer']['enabled'])

    def test_default_eval_preserves_interactive_session(self): self.launch()
    def test_headless_eval_checks_durable_project_status(self): self.launch(headless=True)
    def test_headless_halt_returns_nonzero(self): self.launch(headless=True, halted=True)

    def test_transport_retry_resumes_fresh_cloned_iteration(self): self.launch(retry=True)

    def test_interactive_review_disables_desktop_dispatch(self): self.launch(review=True)
    def test_headless_review_succeeds_with_existing_halt(self): self.launch(review=True, headless=True, halted=True)
    def test_headless_review_requires_saved_review(self): self.launch(review=True, headless=True, missing_review=True)

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from uuid import uuid4

from desktop_harness.evals import Evaluations
from desktop_harness.transcripts import export_transcripts


class TranscriptTests(unittest.TestCase):
    def test_isolation_live_updates_and_resume_preservation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); goal = root / 'goal'; goal.write_text('Goal')
            evaluations = Evaluations(root / 'evals'); evaluations.create('example', str(goal), str(root))
            operation = str(uuid4())
            evaluations.hypothesize('example', 'Prompt', 'Hypothesis', operation)
            db = root / 'sessions.db'
            with sqlite3.connect(db) as c:
                c.execute('CREATE TABLE sessions(id TEXT, created_at TEXT)')
                c.execute('CREATE TABLE messages(id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content_json TEXT)')
                for sid, text in [('one', 'HARNESS SESSION OPERATION: ' + operation), ('other', 'unrelated')]:
                    c.execute('INSERT INTO sessions VALUES (?,?)', (sid, 'today'))
                    c.execute('INSERT INTO messages(session_id,role,content_json) VALUES (?,?,?)', (sid, 'user', json.dumps([{'type':'text','text':text}])))
            paths = export_transcripts('example', operation, db, evaluations=evaluations)
            self.assertEqual(Path(paths[0]).name, 'transcript-0001.json')
            self.assertEqual(len(json.loads(Path(paths[0]).read_text())['sessions']), 1)
            with sqlite3.connect(db) as c:
                c.execute('INSERT INTO messages(session_id,role,content_json) VALUES (?,?,?)', ('one', 'assistant', json.dumps([{'type':'toolRequest','name':'eval_run','arguments':{'iteration':1}}])))
                c.execute('INSERT INTO sessions VALUES (?,?)', ('two', 'later'))
                c.execute('INSERT INTO messages(session_id,role,content_json) VALUES (?,?,?)', ('two', 'user', json.dumps([{'type':'text','text':'HARNESS SESSION OPERATION: ' + operation}])))
            export_transcripts('example', operation, db, evaluations=evaluations)
            data = json.loads(Path(paths[0]).read_text())
            self.assertEqual(len(data['sessions']), 2)
            self.assertEqual(len(data['sessions'][0]['messages']), 2)
            self.assertIn('toolRequest', Path(paths[1]).read_text())
            export_transcripts('example', operation, db, evaluations=evaluations, session_ids=['two'])
            self.assertEqual(len(json.loads(Path(paths[0]).read_text())['sessions']), 2)

    def test_missing_database_is_normal_before_startup(self):
        self.assertEqual(export_transcripts('unused', str(uuid4()), Path('/missing/goose.db')), [])

    def test_runner_exports_on_success_and_failure_without_losing_exit_code(self):
        import os
        import subprocess
        import sys
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); goal = root / 'goal'; goal.write_text('Goal')
            evaluations = Evaluations(root / 'evals'); evaluations.create('example', str(goal), str(root))
            operation = str(uuid4()); evaluations.hypothesize('example', 'Prompt', 'Hypothesis', operation)
            child = root / 'fake_goose.py'
            child.write_text('''import sqlite3,json,sys
with sqlite3.connect(sys.argv[1]) as c:
 c.execute('CREATE TABLE IF NOT EXISTS sessions(id TEXT, created_at TEXT)')
 c.execute('CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content_json TEXT)')
 c.execute('INSERT INTO sessions VALUES (?,?)', (sys.argv[3], 'today'))
 c.execute('INSERT INTO messages(session_id,role,content_json) VALUES (?,?,?)', (sys.argv[3], 'user', json.dumps([{'type':'text','text':'HARNESS SESSION OPERATION: ' + sys.argv[2]}])))
sys.exit(int(sys.argv[3]))
''')
            for code in (0, 7):
                completed = subprocess.run([sys.executable, '-m', 'desktop_harness.transcripts', 'example', operation, str(root / 'sessions.db'), '--', sys.executable, str(child), str(root / 'sessions.db'), operation, str(code)], env={**os.environ, 'HARNESS_EVAL_ROOT': str(root / 'evals')}, capture_output=True, text=True)
                self.assertEqual(completed.returncode, code, completed.stderr)
                self.assertIn('Goose transcript:', completed.stderr)
            snapshot = json.loads((root / 'evals/example/transcript-0001.json').read_text())
            self.assertEqual(len(snapshot['sessions']), 2)

    def test_grading_watchdog_counts_errors_but_ignores_old_sessions(self):
        from desktop_harness.transcripts import grading_failure_streak
        def messages(errors):
            result = []
            for n, error in enumerate(errors):
                result += [{'content': [{'type':'toolRequest','id':str(n),'toolCall':{'value':{'name':'codexdesktop__eval_observe'}}}]}, {'content':[{'type':'toolResponse','id':str(n),'toolResult':{'value':{'isError':error}}}]}]
            return result
        snapshot = {'sessions':[{'session':{'id':'old'},'messages':messages([True]*46)}, {'session':{'id':'new'},'messages':messages([True,False,True,True])}]}
        self.assertEqual(grading_failure_streak(snapshot, {'old'}), 2)
        snapshot['sessions'][1]['messages'] = messages([True]*3)
        self.assertEqual(grading_failure_streak(snapshot, {'old'}), 3)

    def test_runner_stops_repeated_grading_errors_and_preserves_answer(self):
        import os, subprocess, sys
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); goal=root/'goal'; goal.write_text('Goal')
            evaluations=Evaluations(root/'evals'); evaluations.create('example',str(goal),str(root))
            operation=str(uuid4()); evaluations.hypothesize('example','Prompt','Hypothesis',operation)
            child=root/'fake_goose.py'
            child.write_text('''import sqlite3,json,sys,time
with sqlite3.connect(sys.argv[1]) as c:
 c.execute('CREATE TABLE sessions(id TEXT, created_at TEXT)')
 c.execute('CREATE TABLE messages(id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content_json TEXT)')
 c.execute("INSERT INTO sessions VALUES ('new','today')")
 c.execute('INSERT INTO messages(session_id,role,content_json) VALUES (?,?,?)',('new','user',json.dumps([{'type':'text','text':'HARNESS SESSION OPERATION: '+sys.argv[2]}])))
 for n in range(3):
  blocks=[{'type':'toolRequest','id':str(n),'toolCall':{'value':{'name':'codexdesktop__eval_observe'}}},{'type':'toolResponse','id':str(n),'toolResult':{'value':{'isError':True}}}]
  c.execute('INSERT INTO messages(session_id,role,content_json) VALUES (?,?,?)',('new','assistant',json.dumps(blocks)))
time.sleep(30)
''')
            result=subprocess.run([sys.executable,'-m','desktop_harness.transcripts','example',operation,str(root/'sessions.db'),'--',sys.executable,str(child),str(root/'sessions.db'),operation],env={**os.environ,'HARNESS_EVAL_ROOT':str(root/'evals')},capture_output=True,text=True,timeout=12)
            self.assertEqual(result.returncode,4,result.stderr)
            self.assertIn('Three consecutive',evaluations.context('example')['halt']['reason'])
            self.assertTrue((root/'evals/example'/('session-stop-'+operation+'.json')).is_file())
            self.assertEqual(evaluations.read('example',1)['state'],'hypothesized')

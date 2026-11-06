"""Project-local, lossless snapshots of persisted Goose conversations.

Reads Goose's session database, never its GUI or inference endpoint. This is
conversation history, not a claim to capture the model's full internal context.
"""
import json
import sqlite3
from pathlib import Path

from .evals import Evaluations, atomic_text


def export_transcripts(project, operation_id, database, *, evaluations=None, session_ids=None):
    evaluations = evaluations or Evaluations()
    database = Path(database).resolve()
    if not database.is_file():
        return []
    # One consistent read transaction; never modify Goose's database.
    connection = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=2)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute('BEGIN')
        sessions = []
        marker = 'HARNESS SESSION OPERATION: ' + operation_id
        for row in connection.execute('SELECT * FROM sessions ORDER BY created_at, id'):
            messages = [dict(message) for message in connection.execute(
                'SELECT * FROM messages WHERE session_id=? ORDER BY id', (row['id'],))]
            first_user = next((m['content_json'] for m in messages if m['role'] == 'user'), '')
            if (session_ids is not None and row['id'] in session_ids) or (session_ids is None and marker in first_user):
                for message in messages:
                    message['content'] = json.loads(message.pop('content_json'))
                sessions.append({'session': dict(row), 'messages': messages})
    finally:
        connection.close()
    if not sessions:
        return []
    paths = []
    with evaluations.locked(project) as (directory, ledger):
        iteration = next((i for i in ledger['iterations'] if i['operation_id'] == operation_id), None)
        stem = f"transcript-{iteration['iteration']:04d}" if iteration else 'transcript-operation-' + operation_id
        target = directory / (stem + '.json')
        previous = json.loads(target.read_text()) if target.exists() else {'sessions': []}
        by_id = {s['session']['id']: s for s in previous['sessions']}
        by_id.update({s['session']['id']: s for s in sessions})
        snapshot = {'format_version': 1, 'project': project, 'operation_id': operation_id,
                    'iteration': iteration['iteration'] if iteration else None,
                    'source': 'Goose persisted session database',
                    'sessions': list(by_id.values())}
        atomic_text(target, json.dumps(snapshot, indent=2, ensure_ascii=False) + '\n')
        lines = [f'# Goose transcript: {project} / {stem}', '',
                 'Persisted conversation, including tool calls/results. Does not include unpersisted provider system prompts or hidden reasoning.', '']
        for session in snapshot['sessions']:
            lines += ['## Session ' + session['session']['id'], '']
            for message in session['messages']:
                lines += [f"### {message['role']} — message {message['id']}", '']
                for block in message['content']:
                    if block.get('type') == 'text':
                        lines += [block.get('text', ''), '']
                    else:
                        lines += ['```json', json.dumps(block, indent=2, ensure_ascii=False), '```', '']
        readable = directory / (stem + '.md')
        atomic_text(readable, '\n'.join(lines))
        paths.extend([str(target), str(readable)])
    return paths


def grading_failure_streak(snapshot, excluded_sessions=()):
    """Count consecutive rejected judgment calls only in newly launched sessions."""
    longest = 0
    for session in snapshot.get('sessions', []):
        if session['session']['id'] in excluded_sessions:
            continue
        calls = {}; streak = 0
        for message in session['messages']:
            for block in message['content']:
                if block.get('type') == 'toolRequest':
                    value = block.get('toolCall', {}).get('value', {})
                    calls[block.get('id')] = value.get('name', '')
                elif block.get('type') == 'toolResponse':
                    name = calls.get(block.get('id'), '').split('__')[-1]
                    if name not in ('eval_observe', 'eval_review'):
                        continue
                    result = block.get('toolResult', {}).get('value', {})
                    streak = streak + 1 if result.get('isError') else 0
                    longest = max(longest, streak)
    return longest


def existing_sessions(database):
    path = Path(database).resolve()
    if not path.is_file():
        return set()
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=2) as db:
        return {row[0] for row in db.execute('SELECT id FROM sessions')}


def main():
    import argparse
    import subprocess
    import sys
    import threading
    parser = argparse.ArgumentParser()
    parser.add_argument('project')
    parser.add_argument('operation_id')
    parser.add_argument('database')
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command:
        parser.error('A Goose command is required')
    old_sessions = existing_sessions(args.database)
    stop = threading.Event()
    loop_stopped = threading.Event()
    warned = False

    def snapshot():
        nonlocal warned
        try:
            return export_transcripts(args.project, args.operation_id, args.database)
        except Exception as error:
            if not warned:
                print('Transcript export unavailable: ' + str(error), file=sys.stderr)
                warned = True
            return []

    def watch():
        while not stop.is_set():
            paths = snapshot()
            if paths and grading_failure_streak(json.loads(Path(paths[0]).read_text()), old_sessions) >= 3:
                reason = 'Three consecutive rejected grading calls; session stopped to prevent a tool loop. Recover the existing answer, do not resend.'
                Evaluations().abort(args.project, reason)
                with Evaluations().locked(args.project) as (directory, ledger):
                    atomic_text(directory / ('session-stop-' + args.operation_id + '.json'), json.dumps({'reason': reason, 'operation_id': args.operation_id, 'exit_code': 4}) + '\n')
                print(reason, file=sys.stderr)
                loop_stopped.set()
                process.terminate()
                return
            stop.wait(2)

    process = subprocess.Popen(command)
    thread = threading.Thread(target=watch, daemon=True)
    thread.start()
    try:
        while True:
            try:
                code = process.wait(timeout=1)
                break
            except subprocess.TimeoutExpired:
                if loop_stopped.is_set():
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill(); process.wait()
                    code = 4
                    break
        if loop_stopped.is_set(): code = 4
    except KeyboardInterrupt:
        process.terminate()
        try: process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill(); process.wait()
        code = 130
    finally:
        stop.set()
        thread.join(timeout=5)
        paths = snapshot()
        if paths:
            print('Goose transcript: ' + paths[-1], file=sys.stderr)
        elif not warned:
            print('No persisted Goose messages found for this operation.', file=sys.stderr)
    raise SystemExit(code)


if __name__ == '__main__':
    main()

"""Foreground Desktop backend run explicitly by an authorized external terminal."""
import asyncio
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path
from urllib.parse import urlencode

from .desktop_test import native, save
from .response_reader import response_markers


def wrap_prompt(prompt, request_id):
    begin, end = response_markers(request_id)
    return (prompt + ' Response format for the local harness: start your final answer with '
            + begin + ' on a line by itself. Then put your complete answer, including paragraphs '
            'and any requested code. Finish with ' + end + ' on a line by itself. '
            'Include each marker exactly once, outside code blocks, and put no text outside this envelope.')


class DesktopBackend:
    def __init__(self, store, *, switch_delay=0, timeout=600, progress=lambda message: None):
        self.store = store
        self.previous_request_id = None
        self.return_focus = False
        self.require_return_focus = True
        native_directory = Path(os.getenv('HARNESS_NATIVE_DIR', str(Path.cwd().resolve() / '.build')))
        self.binary = native_directory / 'ax-picker-probe'
        if not self.binary.is_file():
            raise ValueError('Run worker from the repository with the native probe compiled')
        if not 0 <= switch_delay <= 30 or timeout < 60:
            raise ValueError('Startup delay must be 0–30 seconds and timeout at least 60 seconds')
        self.switch_delay, self.timeout, self.progress = switch_delay, timeout, progress

    async def restore_focus(self, request_id):
        status = self.store.get(request_id)
        if not status.get('attempt_id'):
            return
        task_file = (Path.cwd().resolve() / 'work/worker' / request_id / status['attempt_id'] / 'task.json')
        if task_file.is_file() and (task_file.parent / 'caller-focus.json').is_file():
            result = await native(self.binary, task_file, 'restore-focus', status.get('desktop_model', 'GPT-5.6 Sol'))
            if not result.get('ok'):
                self.progress('Could not return focus automatically; switch back to your terminal.')

    async def reconcile(self, request_id):
        """Observe the original chat only; never opens a new chat or resends."""
        status = self.store.get(request_id)
        if status['state'] == 'completed':
            return status
        if status['state'] not in {'uncertain', 'submitted', 'running'} or not status['attempt_id']:
            raise ValueError('Reconciliation requires an existing active attempt')
        task = self.store.payload(request_id)
        attempt = status['attempt_id']
        directory = Path.cwd().resolve() / 'work/worker' / status['request_id'] / attempt
        task_file = directory / 'task.json'
        wire = json.loads(task_file.read_text())
        if any(wire.get(key) != value for key, value in {
                'request_id': status['request_id'], 'attempt_id': attempt,
                'workspace': task['workspace']}.items()):
            raise ValueError('Saved wire task attribution mismatch')
        model = task.get('desktop_model', 'GPT-5.6 Sol')
        self.progress(f'Switch to the original chat for {request_id} within {self.switch_delay} seconds. This only reads it.')
        await asyncio.sleep(self.switch_delay)
        receipt = await native(self.binary, task_file, 'read-request', model)
        save(directory / 'reconcile-native.json', receipt)
        expected = {'request_id': status['request_id'], 'attempt_id': attempt,
                    'workspace': task['workspace'],
                    'wire_prompt_sha256': hashlib.sha256(wire['prompt'].encode()).hexdigest()}
        if (receipt.get('completion_evidence_verified') is not True
                or any(receipt.get(key) != value for key, value in expected.items())):
            return self.store.fail(request_id, attempt, 'Read-only reconciliation did not verify this request', uncertain=True)
        trusted = {**receipt, 'prompt_sha256': status['prompt_sha256']}
        return self.store.complete(request_id, attempt, receipt.get('response_text'), trusted)

    async def __call__(self, task):
        identifier, attempt = task['request_id'], task['attempt_id']
        model = task.get('desktop_model', 'GPT-5.6 Sol')
        directory = Path.cwd().resolve() / 'work/worker' / identifier / attempt
        directory.mkdir(parents=True, mode=0o700)
        wire_prompt = wrap_prompt(task['prompt'], identifier)
        wire_hash = self.store.bind_wire_prompt(identifier, attempt, wire_prompt)
        wire_task = {'request_id': identifier, 'attempt_id': attempt, 'prompt': wire_prompt,
                     'workspace': task['workspace'], 'desktop_model': model, 'auto_focus': True}
        if self.previous_request_id:
            previous_status = self.store.get(self.previous_request_id)
            previous_payload = self.store.payload(self.previous_request_id)
            if (previous_status['state'] != 'completed' or previous_payload['workspace'] != task['workspace']
                    or previous_payload.get('desktop_model') != model):
                raise ValueError('Follow-up requires a completed previous turn in the same workspace/model')
            previous_file = (Path.cwd().resolve() / 'work/worker' / self.previous_request_id
                             / previous_status['attempt_id'] / 'task.json')
            previous_wire = json.loads(previous_file.read_text())
            previous_evidence = self.store.response(self.previous_request_id)['evidence']
            if (previous_wire.get('request_id') != self.previous_request_id
                    or previous_wire.get('attempt_id') != previous_status['attempt_id']
                    or hashlib.sha256(previous_wire['prompt'].encode()).hexdigest() != previous_evidence['wire_prompt_sha256']):
                raise ValueError('Previous wire task does not match its completed receipt')
            wire_task['previous_turn'] = {**previous_wire, 'response_text': previous_status['response_text']}
        task_file = directory / 'task.json'
        save(task_file, wire_task)
        base = {'request_id': identifier, 'attempt_id': attempt, 'workspace': task['workspace'],
                'prompt_sha256': task['prompt_sha256'], 'wire_prompt_sha256': wire_hash,
                'completion_evidence_verified': False, 'submission_attempted': False,
                'state': 'failed_before_send'}
        try:
            if self.return_focus:
                try:
                    captured = await native(self.binary, task_file, 'capture-focus', model)
                except Exception as error:
                    captured = {'ok': False, 'error': str(error)}
                save(directory / 'focus-capture.json', captured)
                if captured.get('ok') is not True:
                    reason = str(captured.get('error', 'unknown native focus capture failure'))
                    if self.require_return_focus:
                        return {**base, 'error': 'Could not record caller focus before dispatch: ' + reason,
                                'native_result': captured}
                    self.progress('Caller focus could not be saved (' + reason + '); automatic return focus is unavailable.')
            if self.previous_request_id:
                self.progress('Verifying the previous answer and preparing a follow-up in the same chat…')
                # LaunchServices foreground acquisition is also needed without a
                # deep link. No URL: this raises the existing app, not a new chat.
                subprocess.run(['/usr/bin/open', '-b', 'com.openai.codex'], check=True)
                prepared = await native(self.binary, task_file, 'prepare-followup', model)
                save(directory / 'followup-preparation.json', prepared)
                if prepared.get('ok') is not True or prepared.get('draft_verified') is not True:
                    return {**base, 'error': 'Follow-up preparation failed before Send: ' + str(prepared.get('error', 'binding unverified'))}
            else:
                url = 'codex://new?' + urlencode({'prompt': wire_prompt, 'path': task['workspace']})
                subprocess.run(['/usr/bin/open', '-b', 'com.openai.codex', url], check=True)
                self.progress(f'Opening {identifier}; bringing Codex forward and verifying the draft automatically…')
            await asyncio.sleep(self.switch_delay)
            selection = await native(self.binary, task_file, 'select-model', model)
            save(directory / 'selection.json', selection)
            if (selection.get('ok') is not True or selection.get('process_exit_code') != 0
                    or selection.get('model_verified_with_closed_picker') is not True
                    or not selection.get('verified_model_label', '').startswith(model + ' ')):
                reason = (selection.get('error') or selection.get('model_selection_error')
                          or selection.get('model_list_error') or 'verification failed')
                return {**base, 'error': 'Model selection failed before Send: ' + reason,
                        'native_result': selection}
        except Exception as error:
            return {**base, 'error': str(error)}
        deadline = time.monotonic() + self.timeout
        base.update(state='uncertain', submission_attempted=True)
        self.progress('Model verified. Dispatching one request; waiting for its response envelope…')
        # Errors from here propagate to the worker as uncertain; never resend.
        receipt = await native(self.binary, task_file, 'send-request', model)
        save(directory / 'send.json', receipt)
        acknowledged = False
        observations = 0
        while True:
            if receipt.get('completion_evidence_verified') is True or receipt.get('submission_evidence_verified') is True:
                expected = {'request_id': identifier, 'attempt_id': attempt,
                            'workspace': task['workspace'], 'wire_prompt_sha256': wire_hash}
                if any(receipt.get(key) != value for key, value in expected.items()):
                    raise ValueError('Native receipt identity or wire prompt mismatch; no retry')
            if receipt.get('submission_evidence_verified') is True and not acknowledged:
                self.store.acknowledge_submission(identifier, attempt)
                self.store.transition(identifier, 'running', attempt_id=attempt)
                acknowledged = True
            if receipt.get('completion_evidence_verified') is True:
                if not isinstance(receipt.get('response_text'), str) or not receipt['response_text'].strip():
                    raise ValueError('Native completed envelope contains no response text')
                result = {**base, 'state': 'completed', 'response_text': receipt['response_text'],
                          'completion_evidence_verified': True,
                          'verified_model_label': receipt.get('verified_model_label'),
                          'completion_marker_text': receipt.get('completion_marker_text'),
                          'completion_method': receipt.get('completion_method'),
                          'response_representation': 'rendered_ax_leaf_text',
                          'workspace_check': 'visible_project_label_only'}
                save(directory / 'receipt.json', result)
                return result
            if not acknowledged and receipt.get('submission_attempted') is False:
                return {**base, 'state': 'failed_before_send', 'submission_attempted': False,
                        'error': receipt.get('error', 'Native sender stopped before Send')}
            if not acknowledged or time.monotonic() >= deadline:
                return {**base, 'error': receipt.get('error', receipt.get('reason', 'Completion not verified')),
                        'native_result': receipt}
            await asyncio.sleep(2)
            receipt = await native(self.binary, task_file, 'read-request', model)
            observations += 1
            save(directory / 'latest-read.json', {**receipt, 'observation': observations})

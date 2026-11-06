"""User-run terminal workflow for the nonce-bound Desktop smoke test."""
import asyncio
import hashlib
import json
import os
import subprocess
from pathlib import Path
from uuid import uuid4

from .controller import run
from .store import Store
from .evals import atomic_text


def save(path, data):
    atomic_text(path, json.dumps(data, indent=2) + '\n')


async def native(binary, task_file, mode, desktop_model):
    process = await asyncio.create_subprocess_exec(
        str(binary), '--task', str(task_file), mode, desktop_model, '--spatial-only',
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=90)
    except BaseException:
        if process.returncode is None:
            process.kill()
            await process.wait()
        raise
    try:
        result = json.loads(stdout)
    except ValueError as error:
        raise RuntimeError('Native probe returned invalid JSON; no retry') from error
    result['process_exit_code'] = process.returncode
    if stderr:
        result['stderr'] = stderr.decode(errors='replace')
    return result


async def exercise(model=None, context=None, desktop_model='GPT-5.6 Sol', switch_delay=5,
                   progress=lambda message: None):
    root = Path.cwd().resolve()
    binary = root / '.build/ax-picker-probe'
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise ValueError('Run from the repository with .build/ax-picker-probe compiled')
    if not desktop_model.startswith('GPT-') or not 1 <= switch_delay <= 30:
        raise ValueError('Specify an exact GPT model label and a switch delay between 1 and 30 seconds')
    request_id = str(uuid4())
    token = 'DESKTOP_SPIKE_' + request_id.replace('-', '').upper()
    task = {'request_id': request_id,
            'prompt': f'Reply with exactly {token}. Do not use tools or change any files.',
            'workspace': str(root)}
    directory = root / 'work/desktop-tests' / request_id
    directory.mkdir(parents=True, mode=0o700)
    task_file = directory / 'task.json'
    save(task_file, task)
    report_file = directory / 'result.json'
    report = {'request_id': request_id, 'expected_response': token,
              'desktop_model': desktop_model, 'state': 'preparing',
              'submission_attempted': False, 'report_file': str(report_file)}
    save(report_file, report)
    try:
        progress('Qwen is preparing a fresh harmless test through MCP…')
        controller = await run(json.dumps(task), model, context)
        save(directory / 'controller.json', controller)
        prepared = Store().get(request_id)
        if (prepared['workspace'] != task['workspace'] or
                prepared['prompt_sha256'] != hashlib.sha256(task['prompt'].encode()).hexdigest()):
            raise RuntimeError('Prepared request does not match the trusted test')
        report['outer_model'] = controller['model']
        report['state'] = 'opening_draft'
        save(report_file, report)
        subprocess.run(['/usr/bin/open', prepared['deep_link']], check=True)
        progress(f'Draft opened. Switch to it now and leave it foreground; selection starts in {switch_delay} seconds.')
        await asyncio.sleep(switch_delay)
        selection = await native(binary, task_file, 'select-model', desktop_model)
        save(directory / 'model-selection.json', selection)
        if (selection.get('ok') is not True or selection.get('process_exit_code') != 0 or
                selection.get('model_verified_with_closed_picker') is not True or
                not selection.get('verified_model_label', '').startswith(desktop_model + ' ')):
            report['state'] = 'model_selection_failed'
            report['native_result'] = selection
            return report
        report['state'] = 'sending_test'
        # From this point, timeout/interruption must conservatively preserve uncertainty.
        report['submission_attempted'] = 'possible'
        save(report_file, report)
        progress('Model verified. Sending once and watching for the completion marker…')
        response = await native(binary, task_file, 'send-test', desktop_model)
        save(directory / 'send-result.json', response)
        report['native_result'] = response
        report['submission_attempted'] = response.get('submission_attempted', 'possible')
        matched = (response.get('ok') is True and response.get('process_exit_code') == 0 and
                   response.get('completion_evidence_verified') is True and
                   response.get('expected_response') == token and
                   response.get('response_text') == token and
                   response.get('verified_model_label', '').startswith(desktop_model + ' '))
        report['state'] = 'completed_test' if matched else 'uncertain'
        report['verified_model_label'] = response.get('verified_model_label')
        report['response_text'] = response.get('response_text')
        return report
    except Exception as error:
        report['error'] = str(error)
        report['state'] = 'uncertain' if report['state'] == 'sending_test' else 'failed_before_send'
        return report
    finally:
        # A cancellation after possible dispatch must not be saved as safe to retry.
        if report['state'] == 'sending_test':
            report['state'] = 'uncertain'
        save(report_file, report)

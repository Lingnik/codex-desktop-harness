"""Single-request queue consumer for an externally authorized Desktop process.

MCP only enqueues work. Supplying a backend is an explicit action by the terminal
worker; importing this module never opens applications or posts input events.
"""
import inspect
from uuid import uuid4

from .store import Store


def replacement_after_selection_failure(database, request_id):
    status = database.get(request_id)
    if status['state'] != 'failed' or not (status.get('error') or '').startswith('Model selection failed before Send'):
        raise ValueError('Only a recorded model-selection failure before Send can be replaced')
    payload = database.payload(request_id)
    return submit_request(payload['prompt'], payload['workspace'], payload.get('desktop_model', 'GPT-5.6 Sol'), store=database)


def submit_request(prompt: str, workspace: str, desktop_model: str = 'GPT-5.6 Sol',
                   request_id: str | None = None, *, store: Store | None = None) -> dict:
    """Persist and queue a new chat request. Reuse a caller UUID for safe retries."""
    database = store if store is not None else Store()
    identifier = request_id or str(uuid4())
    database.prepare(identifier, prompt, workspace, desktop_model=desktop_model)
    return database.queue(identifier)


async def run_one(backend=None, *, store: Store | None = None,
                  worker_id: str | None = None, request_id: str | None = None) -> dict:
    """Run at most one durable claim through a trusted backend callback.

    ``backend(task)`` may be sync or async and must return an attributed receipt.
    The task contains the immutable prompt/workspace/model plus claim_token. A
    backend can call Store.acknowledge_submission when submission is observed.
    A completion receipt needs request_id, prompt_sha256, workspace,
    response_text, and completion_evidence_verified. An explicit pre-send
    failure with submission_attempted=False releases the global queue; errors
    or incomplete observations preserve uncertainty and block further sends.
    """
    if backend is None:
        return {'state': 'backend_unavailable', 'claimed': False,
                'submission_attempted': False,
                'note': 'No Desktop backend configured. Queue remains untouched.'}
    if not callable(backend):
        raise TypeError('Desktop backend must be callable')
    database = store if store is not None else Store()
    owner = worker_id or str(uuid4())
    if request_id is not None:
        current = database.get(request_id)
        if current['state'] != 'prepared' or current['attempt_id'] is not None:
            return current
        try:
            task = database.claim_dispatch(request_id, owner)
        except ValueError as error:
            return {**database.get(request_id), 'dispatch_blocked': True, 'note': str(error)}
    else:
        task = database.claim_next(owner)
    if task is None:
        return {'state': 'idle', 'claimed': False, 'submission_attempted': False,
                'note': 'No eligible queued request, or another attempt requires reconciliation.'}
    identifier, token = task['request_id'], task['claim_token']
    try:
        receipt = backend(task)
        if inspect.isawaitable(receipt):
            receipt = await receipt
        if not isinstance(receipt, dict):
            raise ValueError('Desktop backend returned an invalid receipt')
        if receipt.get('completion_evidence_verified') is True:
            database.complete(identifier, token, receipt.get('response_text'), receipt)
        else:
            # Only a positively reported pre-send failure is safe to unblock.
            before_send = (receipt.get('submission_attempted') is False and
                           receipt.get('state') == 'failed_before_send')
            database.fail(identifier, token,
                          receipt.get('error', 'Desktop completion was not verified'),
                          uncertain=not before_send)
    except BaseException as error:
        database.fail(identifier, token, str(error) or type(error).__name__, uncertain=True)
        if not isinstance(error, Exception):
            raise
    return database.get(identifier)

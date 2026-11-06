from mcp.server.fastmcp import FastMCP
from .judging import CriterionJudgment, judgment_rows
from .store import Store, capabilities
from .worker import submit_request as enqueue_request

mcp = FastMCP('Codex Desktop worker adapter')


@mcp.tool(annotations={'readOnlyHint': True})
def adapter_capabilities() -> dict:
    """Report measured adapter capabilities; never claims preparation is submission."""
    result = capabilities()
    result.update({'worker_queue': True, 'direct_mcp_dispatch': False,
                   'worker_required': True, 'general_response_reader': 'live_validated_rendered_ax_text',
                   'response_format': 'rendered_text', 'preserves_markdown': False})
    return result


@mcp.tool(annotations={'readOnlyHint': False, 'destructiveHint': False, 'idempotentHint': True})
def prepare_request(request_id: str, prompt: str, workspace: str) -> dict:
    """Persist a draft for Codex Desktop. Reuse the same UUID and payload on retries. Does not open or submit it."""
    return Store().prepare(request_id, prompt, workspace)


@mcp.tool(annotations={'readOnlyHint': True})
def request_status(request_id: str) -> dict:
    """Read durable state. Queued/prepared is unsent; uncertain must not be retried."""
    return Store().get(request_id)


@mcp.tool(annotations={'readOnlyHint': False, 'destructiveHint': False, 'idempotentHint': True})
def submit_request(prompt: str, workspace: str, request_id: str,
                   desktop_model: str = 'GPT-5.6 Sol') -> dict:
    """Queue one fresh Desktop chat for the terminal worker. Does not dispatch itself.

    A UUID request_id is required; reuse it on retries to prevent duplicate jobs.
    desktop_model is the exact UI label, independent of the outer local model.
    """
    return enqueue_request(prompt, workspace, desktop_model, request_id)


@mcp.tool(annotations={'readOnlyHint': True})
def get_response(request_id: str) -> dict:
    """Read an attributed completed response. Pending or uncertain jobs have no final response.

    response_text is extracted rendered text; Markdown formatting is not preserved.
    """
    return Store().get_response(request_id)


from .evals import Evaluations
import os


def eval_scope(project, iteration=None, operation_id=None):
    bound = os.getenv('HARNESS_EVAL_PROJECT')
    if bound and project != bound:
        raise ValueError('Eval invocation is bound to a different project')
    operation = os.getenv('HARNESS_EVAL_OPERATION_ID')
    if operation_id is not None and operation and operation_id != operation:
        raise ValueError('Use this invocation\'s operation UUID; only one hypothesis is allowed')
    if iteration is not None and operation:
        item = Evaluations().read(project, iteration)
        if item['operation_id'] != operation:
            raise ValueError('This invocation may execute/assess only its own iteration')


@mcp.tool(annotations={'readOnlyHint': False, 'idempotentHint': True})
def eval_project_create(project: str, scenario_path: str, workspace: str,
                        desktop_model: str = 'GPT-5.6 Sol') -> dict:
    """Initialize immutable goal/model/workspace from an absolute scenario file; writes deterministic eval files."""
    eval_scope(project)
    return Evaluations().create(project, scenario_path, workspace, desktop_model)


@mcp.tool(annotations={'readOnlyHint': True})
def eval_context(project: str) -> dict:
    """Read goal, recent iteration index and last 50 compact memories; no Desktop actions."""
    eval_scope(project)
    result = Evaluations().context(project)
    if os.getenv('HARNESS_EVAL_OPERATION_ID'):
        result['operation_id'] = os.environ['HARNESS_EVAL_OPERATION_ID']
    return result


@mcp.tool(annotations={'readOnlyHint': True})
def eval_read(project: str, iteration: int) -> dict:
    """Read an earlier prompt, hypothesis, response, receipt and assessment by iteration number."""
    eval_scope(project)
    return Evaluations().read(project, iteration)


@mcp.tool(annotations={'readOnlyHint': True})
def eval_checks(project: str, iteration: int) -> dict:
    """Read exact judge requirements, deterministic response time-window checks and durable transport history. Unknown is not fail. No Desktop actions."""
    eval_scope(project)
    return Evaluations().checks(project, iteration)


@mcp.tool(annotations={'readOnlyHint': False, 'idempotentHint': True})
def eval_hypothesize(project: str, prompt: str, hypothesis: str, operation_id: str) -> dict:
    """Allocate one numbered immutable prompt. Reuse operation_id UUID and exact content on retries."""
    eval_scope(project, operation_id=operation_id)
    return Evaluations().hypothesize(project, prompt, hypothesis, operation_id)


@mcp.tool(annotations={'readOnlyHint': False, 'idempotentHint': True})
async def eval_run(project: str, iteration: int) -> dict:
    """Run this saved one-shot prompt in Codex Desktop; requires the explicit eval launcher. Never repeats Send. May take ten minutes; uncertain needs reconciliation, not resend."""
    if os.getenv('HARNESS_EVAL_DESKTOP') != '1':
        raise ValueError('Desktop eval execution is disabled; use scripts/goose-local eval PROJECT from the authorized terminal')
    eval_scope(project, iteration=iteration)
    evaluations = Evaluations()
    result = await evaluations.run(project, iteration)
    if result['state'] in ('failed', 'uncertain', 'blocked'):
        evaluations.abort(project, result.get('run', {}).get('error') or 'Desktop run did not produce a verified response')
    return result


@mcp.tool(annotations={'readOnlyHint': False, 'idempotentHint': True})
def eval_observe(project: str, iteration: int, verdict: str, score: int | None,
                 strengths: list[str], weaknesses: list[str], takeaway: str, evidence: str, criteria: list[CriterionJudgment] | None = None,
                 suggestions: list[str] | None = None) -> dict:
    """Record immutable quality assessment and one structured memory line. Verdict pass/partial/fail, optional 0–5 score; failed/uncertain transport uses blocked/null score. Configured projects require criteria rows with exact requirements and literal response quotes; optional beyond-rubric improvements belong in suggestions."""
    eval_scope(project, iteration=iteration)
    return Evaluations().observe(project, iteration, verdict, score, strengths, weaknesses, takeaway, evidence, judgment_rows(criteria), suggestions)


@mcp.tool(annotations={'readOnlyHint': False, 'idempotentHint': True})
def eval_review(project: str, iteration: int, verdict: str, score: int | None,
                strengths: list[str], weaknesses: list[str], takeaway: str, evidence: str,
                criteria: list[CriterionJudgment] | None = None, suggestions: list[str] | None = None) -> dict:
    """Record one immutable supplemental quality review of an already assessed attributed answer. Preserves original observation/transport halt. Same evidence/rubric validation as eval_observe; no Desktop actions."""
    eval_scope(project, iteration=iteration)
    return Evaluations().review(project, iteration, verdict, score, strengths, weaknesses, takeaway, evidence, judgment_rows(criteria), suggestions)


@mcp.tool(annotations={'readOnlyHint': False, 'idempotentHint': True})
def eval_abort(project: str, reason: str) -> dict:
    """Persistently halt further evals for a technical issue; retain evidence and claims. Does not cancel in-flight work. Only the human CLI can clear the halt."""
    eval_scope(project)
    return Evaluations().abort(project, reason)


@mcp.tool(annotations={'readOnlyHint': True})
async def eval_inspect(project: str, window_title: str | None = None) -> dict:
    """Capture read-only Codex AX controls/text to a diagnostic artifact. No clicks, typing, activation or answering approvals. Requires explicit eval launcher; optional exact window title."""
    if os.getenv('HARNESS_EVAL_DESKTOP') != '1':
        raise ValueError('Desktop inspection requires the authorized eval launcher')
    eval_scope(project)
    from .eval_inspection import inspect_desktop
    return await inspect_desktop(project, window_title)


def main():
    if os.getenv('HARNESS_EVAL_ONLY') == '1':
        for name in ('adapter_capabilities', 'prepare_request', 'submit_request', 'request_status', 'get_response'):
            mcp.remove_tool(name)
    mcp.run(transport='stdio')


if __name__ == '__main__':
    main()

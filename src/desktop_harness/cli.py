import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path
from .store import Store, capabilities
from .controller import run


def main():
    parser = argparse.ArgumentParser(description='Local Codex Desktop adapter spike')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('capabilities')
    commands.add_parser('mcp')
    commands.add_parser('mcp-dev', help='Stable stdio MCP proxy with test-gated source reload')
    eval_init = commands.add_parser('eval-init', help='Initialize an immutable one-shot eval project')
    eval_init.add_argument('project')
    eval_init.add_argument('--scenario', required=True)
    eval_init.add_argument('--workspace', required=True)
    eval_init.add_argument('--desktop-model', default='GPT-5.6 Sol')
    eval_prompt = commands.add_parser('eval-prompt', help='Render goal and memories for one fresh Goose invocation')
    eval_prompt.add_argument('project')
    eval_prompt.add_argument('--output', required=True)
    prompt_mode = eval_prompt.add_mutually_exclusive_group()
    prompt_mode.add_argument('--resume-iteration', type=int)
    prompt_mode.add_argument('--review-iteration', type=int)
    eval_sync = commands.add_parser('eval-sync', help='Recover an existing worker result into eval files; never dispatch')
    eval_sync.add_argument('project')
    eval_sync.add_argument('iteration', type=int)
    eval_status = commands.add_parser('eval-status', help='Read eval context; exit 2 if halted')
    eval_status.add_argument('project')
    eval_unhalt = commands.add_parser('eval-unhalt', help='Human explicitly clears a project halt; does not clear uncertain worker claims')
    eval_unhalt.add_argument('project')
    eval_retry = commands.add_parser('eval-retry', help='Clone the latest proven pre-Send failure unchanged; does not clear a halt or send')
    eval_retry.add_argument('project')
    eval_retry.add_argument('iteration', type=int)
    eval_retry.add_argument('--operation-id')
    judge_config = commands.add_parser('eval-judge-config', help='Attach an immutable explicit judge policy; preserves prior assessments')
    judge_config.add_argument('project')
    judge_config.add_argument('--config', required=True)
    judge_checks = commands.add_parser('eval-checks', help='Read deterministic facts and exact judging requirements; no Desktop actions')
    judge_checks.add_argument('project')
    judge_checks.add_argument('iteration', type=int)
    repl = commands.add_parser('repl', help='Steer Qwen between turns in one Codex Desktop chat')
    repl.add_argument('--prompt', help='Initial problem; otherwise asked interactively')
    repl.add_argument('--resume', help='Resume verified replies after local planning error or proven pre-Send follow-up failure')
    repl.add_argument('--workspace')
    repl.add_argument('--model')
    repl.add_argument('--context', type=int)
    repl.add_argument('--desktop-model')
    repl.add_argument('--max-turns', type=int)
    repl.add_argument('--timeout', type=int, default=600)
    local = commands.add_parser('agent-ask', help='Qwen queues through MCP, worker drives Desktop, and returns its answer')
    instruction = local.add_mutually_exclusive_group(required=True)
    instruction.add_argument('--prompt')
    instruction.add_argument('--prompt-file')
    local.add_argument('--workspace', default=str(Path.cwd()))
    local.add_argument('--desktop-model', default='GPT-5.6 Sol')
    local.add_argument('--model')
    local.add_argument('--context', type=int)
    local.add_argument('--timeout', type=int, default=600)
    local.add_argument('--queue-only', action='store_true', help='Exercise local inference and MCP without any Desktop action')
    local.add_argument('--json', action='store_true')
    ask = commands.add_parser('ask', help='Queue and run this request, then print its answer')
    question = ask.add_mutually_exclusive_group()
    question.add_argument('--prompt')
    question.add_argument('--prompt-file')
    ask.add_argument('--request-id', help='Run an existing queued request, or reuse this UUID for a new prompt')
    ask.add_argument('--workspace')
    ask.add_argument('--desktop-model')
    ask.add_argument('--switch-delay', type=int, default=0, help='Optional draft startup delay; focus is automatic')
    ask.add_argument('--timeout', type=int, default=600)
    ask.add_argument('--json', action='store_true', help='Return the full receipt instead of just the answer')
    submit = commands.add_parser('submit', help='Queue a general request; does not operate Desktop')
    content = submit.add_mutually_exclusive_group(required=True)
    content.add_argument('--prompt')
    content.add_argument('--prompt-file')
    submit.add_argument('--workspace', default=str(Path.cwd()))
    submit.add_argument('--desktop-model', default='GPT-5.6 Sol')
    submit.add_argument('--request-id')
    worker = commands.add_parser('worker', help='Authorized external terminal: consume at most one queued request')
    worker.add_argument('--once', action='store_true', help='Explicit spelling of the default one-request mode')
    worker.add_argument('--switch-delay', type=int, default=0, help='Optional draft startup delay; focus is automatic')
    worker.add_argument('--timeout', type=int, default=600)
    response = commands.add_parser('response', help='Read completed response from durable storage')
    response.add_argument('request_id')
    saved = commands.add_parser('reconcile-saved', help='Recover an existing request from its saved complete AX snapshot; no Desktop actions or Send')
    saved.add_argument('request_id')
    reconcile = commands.add_parser('reconcile', help='Read an existing active chat; never resends')
    reconcile.add_argument('request_id')
    reconcile.add_argument('--switch-delay', type=int, default=5)
    smoke = commands.add_parser('desktop-test', help='User-run workflow: Qwen prepares, native probe selects model and sends one harmless test')
    smoke.add_argument('--desktop-model', default='GPT-5.6 Sol')
    smoke.add_argument('--model')
    smoke.add_argument('--context', type=int)
    smoke.add_argument('--switch-delay', type=int, default=5)
    inspect = commands.add_parser('inspect-snapshot', help='Read saved AX JSON; no desktop operations')
    inspect.add_argument('snapshot_file')
    inspect.add_argument('--task-file')
    inspect.add_argument('--desktop-model', default='GPT-5.6 Sol')
    inspect.add_argument('--expected-response')
    inspect_reply = commands.add_parser('inspect-response', help='Read response evidence from saved AX JSON only')
    inspect_reply.add_argument('snapshot_file')
    inspect_reply.add_argument('--task-file', required=True)
    draft = commands.add_parser('prepare')
    draft.add_argument('--request-id', required=True)
    draft.add_argument('--workspace', required=True)
    draft.add_argument('--prompt', required=True)
    status = commands.add_parser('status')
    status.add_argument('request_id')
    agent = commands.add_parser('run')
    agent.add_argument('--task-file', required=True)
    agent.add_argument('--model')
    agent.add_argument('--context', type=int)
    agent.add_argument('--output', default='work/controller-result.json')
    open_request = commands.add_parser('open-request', help='User-run experiment: opens a draft; never submits')
    open_request.add_argument('request_id')
    args = parser.parse_args()
    if args.command in ('eval-init', 'eval-prompt', 'eval-sync', 'eval-status', 'eval-unhalt', 'eval-retry', 'eval-judge-config', 'eval-checks'):
        from .evals import Evaluations, atomic_text
        evaluations = Evaluations()
        if args.command == 'eval-init':
            print(json.dumps(evaluations.create(args.project, args.scenario, args.workspace, args.desktop_model), indent=2))
        elif args.command == 'eval-judge-config':
            print(json.dumps(evaluations.configure_judge(args.project, json.loads(Path(args.config).read_text())), indent=2))
        elif args.command == 'eval-checks':
            print(json.dumps(evaluations.checks(args.project, args.iteration), indent=2))
        elif args.command == 'eval-retry':
            from uuid import uuid4
            print(json.dumps(evaluations.retry_transport(args.project, args.iteration, args.operation_id or str(uuid4())), indent=2))
        elif args.command == 'eval-sync':
            print(json.dumps(evaluations.sync(args.project, args.iteration), indent=2))
        elif args.command in ('eval-status', 'eval-unhalt'):
            result = evaluations.unhalt(args.project) if args.command == 'eval-unhalt' else evaluations.context(args.project)
            print(json.dumps(result, indent=2))
            if result.get('halt'):
                raise SystemExit(2)
        else:
            atomic_text(Path(args.output), evaluations.invocation(args.project, args.resume_iteration, args.review_iteration))
            print(str(Path(args.output).resolve()))
        return
    if args.command == 'reconcile-saved':
        from .recovery import reconcile_saved
        print(json.dumps(reconcile_saved(args.request_id), indent=2))
        return
    if args.command == 'mcp':
        from .server import main as serve
        return serve()
    if args.command == 'mcp-dev':
        from .mcp_dev import main as serve_dev
        return serve_dev()
    if args.command == 'capabilities':
        result = capabilities()
    elif args.command == 'repl':
        from .repl import interact, load_resume
        from .desktop_backend import DesktopBackend
        database = Store()
        if args.resume and args.prompt:
            parser.error('--resume preserves the original problem; steer it interactively instead of using --prompt')
        resumed = load_resume(args.resume, database) if args.resume else None
        backend = DesktopBackend(database, timeout=args.timeout,
                                 progress=lambda message: print(message, file=sys.stderr, flush=True))
        problem = resumed['messages'][1]['content'] if resumed else args.prompt or input('Problem for Qwen> ')
        result = asyncio.run(interact(problem, args.workspace or (resumed['workspace'] if resumed else str(Path.cwd())), database, backend,
                                     model=args.model or (resumed['outer_model'] if resumed else None), context=args.context,
                                     desktop_model=args.desktop_model or (resumed['desktop_model'] if resumed else 'GPT-5.6 Sol'),
                                     max_turns=args.max_turns or (resumed['max_turns'] if resumed else 3), resume=resumed))
        print('Session ended: ' + result['state'])
        if result['state'] in {'blocked', 'error'}:
            raise SystemExit(1)
        return
    elif args.command == 'agent-ask':
        from .agent_dispatch import dispatch
        from .desktop_backend import DesktopBackend
        database = Store()
        progress = lambda message: print(message, file=sys.stderr, flush=True)
        backend = None if args.queue_only else DesktopBackend(database, timeout=args.timeout, progress=progress)
        prompt = Path(args.prompt_file).read_text() if args.prompt_file else args.prompt
        result = asyncio.run(dispatch(prompt, args.workspace, args.desktop_model,
                                     model=args.model, context=args.context, store=database,
                                     backend=backend, progress=progress))
        if result['state'] == 'completed' and not args.json:
            print(result['response_text'])
            return
    elif args.command == 'ask':
        from .worker import run_one, submit_request
        from .desktop_backend import DesktopBackend
        if args.prompt is None and args.prompt_file is None and args.request_id is None:
            parser.error('ask requires --prompt, --prompt-file, or --request-id')
        database = Store()
        backend = DesktopBackend(database, switch_delay=args.switch_delay, timeout=args.timeout,
                                 progress=lambda message: print(message, file=sys.stderr, flush=True))
        if args.prompt is not None or args.prompt_file is not None:
            prompt = Path(args.prompt_file).read_text() if args.prompt_file else args.prompt
            queued = submit_request(prompt, args.workspace or str(Path.cwd()),
                                    args.desktop_model or 'GPT-5.6 Sol', args.request_id, store=database)
        else:
            queued = database.get(args.request_id)
            if args.workspace and str(Path(args.workspace).resolve()) != queued['workspace']:
                parser.error('Workspace does not match the existing request')
            if args.desktop_model and args.desktop_model != queued.get('desktop_model', 'GPT-5.6 Sol'):
                parser.error('Model does not match the existing request')
            if queued['state'] == 'failed' and (queued.get('error') or '').startswith('Model selection failed before Send'):
                from .worker import replacement_after_selection_failure
                queued = replacement_after_selection_failure(database, queued['request_id'])
                print('Previous request stopped before Send; using a fresh request ID.', file=sys.stderr, flush=True)
        print('Request: ' + queued['request_id'], file=sys.stderr, flush=True)
        result = asyncio.run(run_one(backend, store=database, request_id=queued['request_id']))
        if result['state'] == 'completed' and not args.json:
            print(result['response_text'])
            return
    elif args.command == 'submit':
        from .worker import submit_request
        prompt = Path(args.prompt_file).read_text() if args.prompt_file else args.prompt
        result = submit_request(prompt, args.workspace, args.desktop_model, args.request_id)
    elif args.command == 'worker':
        from .worker import run_one
        from .desktop_backend import DesktopBackend
        database = Store()
        backend = DesktopBackend(database, switch_delay=args.switch_delay, timeout=args.timeout,
                                 progress=lambda message: print(message, file=sys.stderr, flush=True))
        result = asyncio.run(run_one(backend, store=database))
    elif args.command == 'response':
        result = Store().response(args.request_id)
    elif args.command == 'reconcile':
        from .desktop_backend import DesktopBackend
        backend = DesktopBackend(Store(), switch_delay=args.switch_delay,
                                 progress=lambda message: print(message, file=sys.stderr, flush=True))
        result = asyncio.run(backend.reconcile(args.request_id))
    elif args.command == 'desktop-test':
        from .desktop_test import exercise
        result = asyncio.run(exercise(args.model, args.context, args.desktop_model, args.switch_delay,
                                      progress=lambda message: print(message, file=sys.stderr, flush=True)))
    elif args.command == 'inspect-snapshot':
        from .snapshot import inspect_snapshot
        task = json.loads(Path(args.task_file).read_text()) if args.task_file else {}
        result = inspect_snapshot(json.loads(Path(args.snapshot_file).read_text()),
                                  task.get('prompt'), args.desktop_model, args.expected_response)
    elif args.command == 'inspect-response':
        from .response_reader import inspect_response
        task = json.loads(Path(args.task_file).read_text())
        result = inspect_response(json.loads(Path(args.snapshot_file).read_text()), task['request_id'],
                                  task['prompt'], task['workspace'], task.get('desktop_model', 'GPT-5.6 Sol'))
    elif args.command == 'prepare':
        result = Store().prepare(args.request_id, args.prompt, args.workspace)
    elif args.command == 'status':
        result = Store().get(args.request_id)
    elif args.command == 'open-request':
        result = Store().get(args.request_id)
        subprocess.run(['/usr/bin/open', result['deep_link']], check=True)
        result['note'] = 'Deep link opened. Submission and completion are unverified.'
    else:
        result = asyncio.run(run(Path(args.task_file).read_text(), args.model, args.context))
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2) + '\n')
        output.chmod(0o600)
    print(json.dumps(result, indent=2))
    if args.command == 'agent-ask' and result.get('controller_error'):
        raise SystemExit(1)
    if args.command in {'ask', 'agent-ask'} and result['state'] != 'completed' and not getattr(args, 'queue_only', False):
        raise SystemExit(1)


if __name__ == '__main__':
    main()

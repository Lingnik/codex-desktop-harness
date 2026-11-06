# General Desktop worker and local-model harness

The general Desktop path has been user-validated with automatic focus and
response extraction. The local-model orchestration below is newly implemented.

## One-step command

```sh
uv run desktop-harness ask --prompt 'Explain the difference between a stack and a queue in two short paragraphs. Do not use tools or change files.'
```

Codex is brought forward automatically. This queues and runs the specific request, then prints its
answer. Default workspace is the current directory and model GPT-5.6 Sol. For an
already queued request, use ask --request-id YOUR_REQUEST_UUID; it does not create
another job. Completed UUIDs return saved text; uncertain attempts are not resent.
--json returns the full receipt; unsuccessful outcomes exit nonzero with status.

## Separate queue/worker commands

From ~/git/l/codex-desktop-harness in your authorized terminal:

```sh
uv run desktop-harness submit --workspace "$PWD" --desktop-model 'GPT-5.6 Sol' \
  --prompt 'Explain the difference between a stack and a queue in two short paragraphs. Do not use tools or change files.'
```

Record the returned UUID. submit only queues. Then:

```sh
uv run desktop-harness worker --once
```

The worker opens a fresh chat with your prompt plus two request-specific response
marker instructions. The harness activates Codex, verifies the exact draft and
project, and selects the model automatically. Leave the new chat foreground.
It selects the exact model, verifies the draft, claims the one native Send,
observes submission, and polls a completed envelope for up to ten minutes.

```sh
uv run desktop-harness response YOUR_REQUEST_UUID
```

Success is durable state completed and response_text containing the two paragraphs
without envelope markers. status YOUR_REQUEST_UUID reports intermediate state.
Do not infer completion from process exit alone. The first live run may reveal
additional AX message shapes; retain work/ artifacts for inspection.

## Where the local model fits

The general submit CLI queues the exact human prompt without calling Qwen. Your
external Qwen harness can call submit_request via MCP instead. GUI operations
remain deterministic terminal-worker code. The tested desktop-test command still
runs Qwen→MCP preparation before the known-token native round trip.

The MCP server exposes adapter_capabilities, prepare_request, submit_request,
request_status and get_response. Use the configuration in README with the same
absolute HARNESS_DB for client server and worker. Caller-provided UUID is important
for transport retry idempotency. Do not alter prompt/workspace/model under it.

## Lifecycle and recovery

prepared with queued=true means waiting, not sent. Dispatch consumes a unique
attempt and initially records uncertain. Observed submission advances to submitted
then running. A verified attributed envelope advances to completed; get_response
only publishes text in that state. A proved pre-Send failure is failed. A crash,
ambiguous dispatch, timeout, wrong receipt or missing envelope remains uncertain
and blocks the Desktop lane. There is no automatic re-Send.

If the original chat eventually completes, select that original chat and run:

```sh
uv run desktop-harness reconcile YOUR_REQUEST_UUID
```

During the countdown switch to its original chat. Reconciliation reads only; it
never opens a new draft or Sends. It requires the saved wire task/native claim and
checks UUID, attempt, original prompt hash, wrapped prompt hash, workspace label,
selected model, unique envelope and completion evidence. Pending or mismatched
observations stay uncertain. Proven failed jobs consume their attempt permanently;
a consciously requested new job gets a fresh UUID.

## Scope of response reading

This version returns rendered AX leaf text. It preserves paragraphs and displayed
code indentation where exposed as leaf text; it does not recreate Markdown source,
file attachments or hidden/virtualized output. Unsupported text editors inside the
reply are rejected rather than silently omitted. Missing, duplicate or out-of-order
markers, incomplete trees and clipped snapshots cannot produce completed results.
Completion requires either the live completion announcement or the finished-answer
Copy, Rate response and Fork controls after the END marker, with an enabled idle
composer. Stop/cancel controls or progress indicators inside the chat prevent
completion. These are observed UI signals; future Desktop changes may require
adapter updates. A model that does not follow the envelope instructions produces
uncertainty.

Workspace evidence is currently the visible project basename, not proof of the
absolute checkout path. One fresh chat, one active attempt and foreground Desktop
remain constraints. Continuous daemon operation, unattended background operation,
existing-chat routing, approval/wait classification and general long-output
scrolling remain follow-up work.

## Files and tests

Tasks, response receipts and probe outputs are under ignored
work/worker/<UUID>/<attempt>/. SQLite contains the queue, audit and completed text.
Files are local, and task/receipt files use mode0600. Source/lock/docs only are
intended for a later commit. No commits or pushes were made.

56 Python checks plus Swift selector/claim/envelope self-tests pass. UI effects are
mocked in backend tests; native response fixtures and actual saved-tree structure
were tested offline. General ask and agent-ask have been user-validated. REPL same-chat follow-up and final synthesis have also worked live through
recovery; see project-status.md for current limitations.

Known model-selection failures before Send can be retried with ask --request-id:
the command creates a fresh request ID with the same original payload. It does
not reuse the consumed attempt. Unknown/uncertain outcomes cannot take this path.
Draft mismatch diagnostics preserve observed values in ignored selection.json.

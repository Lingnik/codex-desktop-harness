# Local harness for Codex Desktop

An experimental local-model harness and MCP queue for the Mac's Codex Desktop app.
Qwen3.8:27b queues requests and reads answers through MCP. An external terminal worker uses deep
links, accessibility labels, fresh control bounds and mouse events to operate
Desktop. Desktop inference uses GPT-5.6 Sol; the outer model stays local in Ollama.

## Full local development harness

Goose Desktop/CLI is installed with an isolated Mac-local Qwen profile. Start
`./scripts/goose-local` for an interactive session with shell/file tools and the
test-gated, automatically reloading MCP adapter. See [Goose setup](docs/goose-setup.md)
for configuration, verification and reload limits.

## Prompt evaluations

One-shot eval projects now have deterministic MCP tools for hypotheses, Desktop
runs, structured observations and compact memory. See [prompt eval workflow](docs/prompt-evals.md).
Initialize with `desktop-harness eval-init`, then run `./scripts/goose-local eval PROJECT`.

## Current status

See [project status](docs/project-status.md) for the latest eval, reliability limits, and next steps. The latest helpfulness answer is saved, but Qwen did not finish its assessment before repeating a rejected tool call; a watchdog and quote-normalization fix are in the workspace. Resume with `./scripts/goose-local eval-resume helpfulness-elicitation-001 1`.

The known-token smoke test completed a live round trip: local preparation, fresh
Desktop draft, model selection, one Send and response/completion reading. Actual
6.1 Sol → 5.6 Sol switching also succeeded. The selected effort was Medium.

The first general prose request was sent successfully and its answer recovered
from a saved read-only AX snapshot. The reader now also accepts final response
actions plus an idle composer when the temporary completion announcement is gone.
The user subsequently validated a fresh general run with automatic focus, Send
and terminal answer extraction. Bold/list syntax was lost, as expected for the
current rendered-text reader:

- MCP submit_request queues a fresh chat; request_status and get_response read it.
- Durable SQLite claims serialize dispatch and prevent automatic duplicate Sends.
- Response envelopes bind rendered replies to a unique request and attempt.
- Terminal worker selects/verifies the exact model and polls completion.
- Read-only reconciliation observes an existing uncertain chat without resending.

Fresh requests now bring Codex forward automatically and verify the draft before
clicking. Desktop must remain foreground during active GUI work. Same-chat
follow-ups and final Qwen synthesis have been validated through a resumed REPL session. Unattended
background control and exact Markdown/source extraction are not implemented. No settings, approval policies or OS permissions are changed.
Runtime data, model weights, local environments, databases and generated traces remain ignored.

## Setup

```sh
cd ~/git/l/codex-desktop-harness
uv sync --locked
mkdir -p .build work
swiftc native/AXPickerProbe.swift -o .build/ax-picker-probe
swiftc native/AXInspect.swift -o .build/ax-inspect
```

Existing Ollama and qwen3.8:27b are used; Python dependencies are in .venv. Your
external terminal needs its existing macOS Device Control and Data Access grant.

## Interactive problem solving

```sh
uv run desktop-harness repl --desktop-model 'GPT-5.6 Sol' --max-turns 3
```

Enter a problem. Qwen proposes each Codex prompt; Enter continues, typed text
steers, /ask QUESTION asks locally, and /stop ends between turns. The adapter
attempts to return focus to your terminal after each Desktop turn. Follow-ups
verify the previous answer before using the same selected chat. This prototype
requests discussion only and stops on uncertain outcomes. Full local inference +
MCP simulation passes, and same-chat follow-up plus final synthesis have now worked live.
See docs/repl-quickstart.md for behavior, logs and limitations.

## Local-model harness in one step

```sh
uv run desktop-harness agent-ask --desktop-model 'GPT-5.6 Sol' \
  --prompt 'Give three practical uses for a queue. Do not use tools or change files.'
```

Qwen uses MCP to queue your exact prompt; the trusted worker brings Codex forward,
selects the model and sends once. Qwen reads status and the final response through
MCP. The terminal prints the stored Codex answer, rather than a Qwen paraphrase.
Leave Codex foreground during the GUI workflow. No separate worker command is
needed for this integrated mode. The user validated the combined real-Qwen/real-GUI agent-ask run.

--model selects the outer Ollama model; --desktop-model selects the Desktop model.
OLLAMA_HOST can point to another Ollama endpoint. --prompt-file reads a saved
instruction; --json returns evidence and transcript location. Protected traces are
saved under ignored work/agent-runs/<UUID>/transcript.json. --queue-only tests local
inference and MCP without opening Desktop; it leaves a queued job in HARNESS_DB.

agent-ask dispatches one exact request. The new repl command adds Qwen planning,
user steering and same-chat follow-ups; richer response formatting remains future work.
Failed or uncertain sends are never automatically repeated. To inspect or recover
an existing attempt, use its UUID with status/response/reconcile.

## Ask in one step

```sh
uv run desktop-harness ask --prompt 'Explain the difference between a stack and a queue in two short paragraphs. Do not use tools or change files.'
```

This queues that exact request, opens a fresh Desktop draft, selects GPT-5.6 Sol,
sends once and prints the completed answer. Workspace defaults to the current
repository. Codex is brought forward automatically; leave it foreground. Use --json for
full receipt, --prompt-file for a saved prompt, and --desktop-model for another
exact model label. Incomplete or blocked requests print status and exit nonzero.

To run an already queued job without creating another:

```sh
uv run desktop-harness ask --request-id YOUR_REQUEST_UUID
```

An already completed UUID returns its saved answer without resending. Uncertain
or active attempts still block dispatch. The requested job is targeted explicitly;
older queued jobs are not accidentally consumed by this command.

The separate submit/worker/response commands remain for MCP-backed queue usage.
Reconcile an existing uncertain chat by selecting its original chat and running:

```sh
uv run desktop-harness reconcile YOUR_REQUEST_UUID
```

This only observes that chat. It does not open a new chat or resend. Tasks and
native evidence are in ignored work/worker/<UUID>/<attempt>/. Replies are rendered
accessibility text, not a source Markdown export.

## MCP connection for your external harness

Your local-model harness calls this stdio server; Desktop does not host the queue
server. The separately launched authorized terminal worker executes queued jobs.

```json
{
  "mcpServers": {
    "codex-desktop": {
      "command": "/opt/homebrew/bin/uv",
      "args": ["--directory", "$PWD", "run", "desktop-harness", "mcp"],
      "env": {"HARNESS_DB": "$PWD/work/requests.sqlite3"}
    }
  }
}
```

Call submit_request(prompt, workspace, desktop_model, request_id), retaining the
caller UUID across transport retries. Poll request_status, then get_response when
state is completed. Queueing is not submission. An uncertain attempt must be
reconciled, not submitted again. The server has no network-facing listener.

Worker and MCP server must use the same HARNESS_DB. The default is work/requests.sqlite3
relative to the repository; the configuration above pins its absolute path.

## Local-model smoke test

```sh
uv run desktop-harness desktop-test --desktop-model 'GPT-5.6 Sol'
```

This creates a new harmless token test and runs Qwen preparation through MCP plus
native model selection/Send/completion. It has been live-tested. --model controls
the outer Ollama model; --desktop-model controls the exact Desktop picker label.
The old preparation-only command remains:

```sh
uv run desktop-harness run --task-file work/task.json --output work/controller-result.json
```

Defaults: qwen3.8:27b, thinking disabled, context8192, up to six preparation tool
steps. Set OLLAMA_HOST to use an authorized remote Ollama endpoint. The PC's
Tailscale endpoint has not been configured or tested in this repository.

## Validation and documentation

```sh
uv run python -m unittest discover -s tests
.build/ax-picker-probe --self-test
```

Tests cover queue/attempt concurrency, restarts, receipt attribution, response
parsing, real stdio MCP calls, model-altered preparation rejection, and native
selector/claim/reader fixtures. They do not execute Desktop UI actions.

- [Project status](docs/project-status.md)
- [REPL quickstart](docs/repl-quickstart.md)
- [Worker quickstart](docs/worker-quickstart.md)
- [Experiment log](docs/experiment-log.md)
- [Desktop validation history](docs/desktop-validation.md)
- [Extensibility report](docs/extensibility-report.md)

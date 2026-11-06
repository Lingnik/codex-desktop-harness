# Goose with Mac-local Qwen and a developing MCP adapter

## What is installed

Goose Desktop and CLI 1.53.0, installed with Homebrew's `block-goose` cask and
`block-goose-cli` formula. This is the selected full harness: its Developer
extension gives Qwen shell execution and file editing, while the Codex adapter
provides MCP tools. It supports ongoing interactive sessions and automated runs.
Cline would add an IDE dependency; Cua focuses on computer interaction rather than
this server-development workflow. We did not install either.

Inference stays on this Mac: Ollama at http://127.0.0.1:11434 using the existing
qwen3.8:27b model. No additional model was downloaded and no PC endpoint is used.
The current Goose budget is 131,072 context tokens and 4,096 output tokens, with
thinking off and 50 autonomous turns. Automatic compaction starts at 60%;
older tool outputs are summarized after four calls, and individual tool responses
above 8,000 characters are moved to a file. Project hints and per-turn reminders
limit broad repository exploration. These settings require a new Goose process.
The first 16k/25-turn profile stopped after excessive file reading; increasing
turns alone would not address that behavior.

## Start

From `~/git/l/codex-desktop-harness`:

```sh
./scripts/goose-local
```

This opens an interactive Goose CLI session with the Developer and codexdesktop
extensions. For the Desktop interface:

```sh
./scripts/goose-local desktop
```

The CLI integration has been exercised; the Desktop launcher is configured but
its GUI workflow has not been validated. It launches Goose's executable directly
so the environment reaches the app. Run one harness session at a time when
improving the server.

A one-shot or initially directed interactive session is also available:

```sh
./scripts/goose-local run --interactive --text 'Inspect the MCP adapter and its tests. Propose one small improvement before editing it.'
```

Configuration is isolated under ignored `work/goose/`; existing global Goose
configuration is untouched. `config/goose.json` seeds the profile on first run.
Subsequent profile adjustments belong in `work/goose/config/config.yaml`.
Repo `.goosehints` supplies project instructions. The selected mode is `auto`,
allowing local file edits and commands without a per-action confirmation. This is
ordinary host access, not a sandbox. Instructions and test gates are quality
controls, not a security boundary. Use a dedicated copy for risky experiments.

## Server reload behavior

The Goose extension runs `desktop_harness.mcp_dev`, a stable stdio parent process.
It snapshots source, tests, native code, configuration, scripts and dependency
manifests into an ignored generation directory. Each candidate must pass the full
Python suite, compile the Swift picker, and pass its offline self-test. Only then
can a new initialized server child replace the active child.

* Calls in flight finish before replacement. They are never replayed.
* Failed tests or child initialization retain the last passing generation.
* Changes during validation supersede the candidate rather than promote stale code.
* Queue and receipt data remain in the same durable SQLite database.
* The parent announces tool-list changes over MCP.
* `development_status` reports revisions, failure details and the validation log.
* `development_retry` reruns the gate after fixing dependencies or other failures.

Changes debounce for about 1.25 seconds before validation. Validation and Swift
compilation add startup/reload time. The MCP handshake completes promptly while startup validation runs; the first
tool catalog waits for validation. Startup exposes status even if no child passes;
adapter tools become available only after a passing generation.
Generated data, models, databases and logs are ignored by both Git and the watcher.

The parent supervisor itself is pinned for its process lifetime: edits to
`mcp_dev.py` require restarting the extension/session. Dependency changes require
`uv sync --locked` followed by `development_retry`; the supervisor does not install
dependencies. Editing tests can weaken the gate, so review changes before trusting
unattended self-modification. Snapshot directories are ordinary local files, not
protected against a model with shell access.

Goose's modern discovery probe is rejected with a correlated MethodNotFound so it
falls back to the Python SDK's legacy MCP protocol. This does not advertise support
for the modern protocol. Regression coverage and the real Goose integration
exercise this compatibility path.

## Improving the server

A useful first task:

> Improve one MCP tool's usability. Inspect its contract and callers, add a failing
> regression test first, implement the smallest change, and run the full suite.
> Use development_status to verify a new passing generation. Preserve request UUID
> identity, single-attempt Send claims, uncertain-state blocking, and reply attribution.
> Do not open Codex Desktop or queue jobs for a server-development task. Do not commit
> or push. Report the diff and test evidence.

Qwen now has the tools to read code, edit implementation and tests, run checks, and
observe its updated MCP child without replacing the ongoing model conversation.
The isolated self-edit experiment succeeded: Qwen added failing catalog assertions,
updated get_response documentation, passed all 66 tests, and observed a newly
promoted generation in the same session. The reviewed two-file change was adopted
in the main repo. Details are recorded in experiment-log.md.

## Driving Codex

The adapter's MCP tools still queue/read requests; they do not directly operate the
GUI. Goose can use Developer shell to invoke the existing one-step `desktop-harness
ask` command, then read the attributed receipt via `get_response`. Supply a UUID
and reuse it for the same request. MCP `submit_request` now requires that UUID,
preventing reconnect retries from silently creating a second job.

Live GUI work requires the authorized terminal/accessibility context and a
foreground Codex window. Goose Desktop may need its own macOS permission path;
no permission changes were made. Existing same-chat REPL transport remains
available, but arbitrary same-chat follow-ups are not exposed as a dedicated MCP
tool yet. The full harness expands Qwen's development capabilities; it does not
remove Desktop focus constraints or establish a native inbound push channel.

## Verification and references

```sh
uv run python -m unittest discover -s tests -q
```

67 Python tests pass, covering store/lifecycle, worker, response reader, native
backend orchestration, REPL, MCP contracts and reload failure/recovery behavior.
The reload gate also runs offline Swift checks; this is not a broad live-GUI test
suite. Read-only Goose/Qwen integration successfully called development_status,
adapter_capabilities and Developer shell using the Mac Ollama model.

Official references: [Developer extension](https://goose-docs.ai/docs/mcp/developer-mcp/),
[configuration](https://goose-docs.ai/docs/guides/config-files/),
[environment variables](https://goose-docs.ai/docs/guides/environment-variables/),
[providers](https://github.com/aaif-goose/goose/blob/main/documentation/docs/getting-started/providers.md).

## Resume after an exploration stall

Restart the process to pick up new budgets. Use `session --resume --session-id ID`
to retain a specific session (avoid bare --resume after diagnostic runs). For an
already overfull history, run `/compact` before continuing, then direct Qwen to
choose one issue using what it already read and start its regression test.
The user-reported stalled session was 20261002_3.

## Current fresh-session trial

Context is now 128k (half the installed model's advertised 256k capacity). The
50-turn cap counts model turns, not precisely individual tool calls: one turn
may request multiple tools. The launcher also sets a three-consecutive-identical
call limit; that does not detect cycles involving different commands.
Use a fresh concrete task with explicit Developer/MCP tool guidance:

```sh
./scripts/goose-local run --interactive --instructions config/tasks/response-format.md
```

This task exposes rendered-text/Markdown capability metadata and tests it through
real MCP. It targets the reloadable child rather than the pinned supervisor.
The expanded context and prompt are configured; sustained 128k performance and
the outcome of this particular task have not yet been measured.

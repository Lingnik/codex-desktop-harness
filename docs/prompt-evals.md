# One-shot prompt evaluations through Codex Desktop

This workflow performs one prompt iteration per fresh Goose invocation. Qwen
hypothesizes a prompt, Codex Desktop answers it in a fresh chat, and Qwen assesses
the answer against a fixed scenario. Deterministic MCP tools own numbering,
request identity, files, observations and memory. No commits or pushes were made.

## Start with a scenario

Put the goal, concrete input situation, acceptance criteria, judging rubric and
allowed Codex actions in a UTF-8 file. The hypothesis prompt must include what
Codex needs: the Desktop chat does not automatically receive the scenario file.
The scenario should state whether Codex may use tools or modify workspace files.

Initialize once, replacing the paths with your scenario and intended Codex workspace:

```sh
cd ~/git/l/codex-desktop-harness
uv run desktop-harness eval-init my-project \
  --scenario /absolute/path/to/goal.txt \
  --workspace /absolute/path/to/codex/workspace \
  --desktop-model 'GPT-5.6 Sol'
```

Default data root: `~/git/l/codex-evals`. `HARNESS_EVAL_ROOT` can override it;
keep that setting consistent between initialization and subsequent runs.
Initialization snapshots the scenario into the project folder. Scenario, workspace
and Desktop model are immutable within a project; use a new name for a changed
experimental setup. Human-editable source goals can live outside the generated
folder; exported scenario.txt is the saved snapshot.

A harmless included example is `config/scenarios/ticket-queue.txt`:

```sh
uv run desktop-harness eval-init ticket-queue \
  --scenario "$PWD/config/scenarios/ticket-queue.txt" \
  --workspace "$PWD"
./scripts/goose-local eval ticket-queue
```

For your own initialized project:

```sh
./scripts/goose-local eval my-project
```

Run from the terminal authorized for Accessibility / Device Control and Data
Access. Exit old Goose sessions first: the supervisor itself changed and requires
restart. Codex stays foreground while the native adapter works; focus return is
requested afterward. This launches a fresh one-shot Goose run each time; it does
not resume the bloated exploratory session. It remains interactive after the eval,
so you can interrogate Qwen using the same conversation context. A second different
hypothesis is still rejected; your questions do not authorize another eval.

## Tools and sequence

| Tool | Deterministic responsibility |
|---|---|
| eval_project_create | Snapshot goal and bind workspace/model; idempotent identical initialization |
| eval_context | Return scenario, last 50 compact memories and recent iteration index |
| eval_read | Retrieve a chosen earlier prompt, hypothesis, response, receipt and assessment |
| eval_hypothesize | Allocate next number, save exact prompt/hypothesis, bind operation UUID and Desktop request UUID |
| eval_run | Execute that saved request through the existing native worker; return verified response or transport state |
| eval_checks | Return configured criterion requirements, deterministic response checks and transport history |
| eval_review | Add one immutable quality review of an already assessed answer, preserving transport history |
| eval_observe | Validate and save immutable observations plus one JSON memory line |
| eval_inspect | Read Codex AX controls/text and save a raw diagnostic snapshot; no activation or input |
| eval_abort | Persist a project halt after a technical issue; block further evals |

The launcher renders the scenario and memories into an instruction file under
ignored `work/eval-invocations/`. It binds the MCP process to one project and one
operation UUID. A second different hypothesis in that invocation is rejected by
the tools, even after the first is assessed. Exact retries retain the same number,
prompt and Desktop request identity.

The eval profile is isolated in `work/goose-evals/`. Developer shell/file-editing
is enabled for adapter investigation and tested fixes; ordinary request tools are removed from its MCP catalog, and the
prompt requires eval tools for records and Desktop delivery. Developer tools must
not serve as an alternate Send path. This is not a machine sandbox:
Goose's platform capabilities still exist. Normal development sessions keep their
Developer tools and have Desktop eval dispatch disabled. The explicit `eval`
launcher enables Desktop execution; ordinary queue tools remain queue-only.

Inference stays Mac-local Qwen. Budgets remain 128k context / 50 model turns / 4k
output. Eval tool responses have a larger inline limit than development sessions
so Qwen can assess answers without shell-based file exploration. Long Desktop
calls use a 900-second MCP timeout, with a 600-second backend observation budget.

## Files

Each project contains:

```
scenario.txt                 fixed scenario and criteria
project.txt                  one JSON line per assessed iteration
prompt-0001.txt              exact hypothesis prompt before transport wrapping
hypothesis-0001.json          hypothesis, prompt hash, request ID
response-0001.txt            attributed rendered Codex answer
run-0001.json                 worker state and verified receipt when available
eval-0001.txt                 structured JSON assessment, formatted for reading
.ledger.json / .lock          authoritative ledger and process lock
```

Numbers increase within each project. The ledger commits before projections are
written; missing exports are reconstructed on reads/retries. Do not manually edit
generated prompt/eval/memory files: the ledger is authoritative and projections
are regenerated. The compact memory record includes iteration, verdict, optional
score, takeaway, request ID and prompt hash. Full observations include strengths,
weaknesses and evidence. Context includes only the last 50 memories and 20 index
entries, with an explicit truncation flag; older details remain available by number.

Verdicts are pass/partial/fail for a completed answer. Scores are optional integer
0–5 judgments against the scenario rubric. An unavailable answer receives blocked
with a null score, never an invented quality assessment. Qwen's judgments are not
calibrated benchmark scores. A single sample does not establish a prompt's causal
improvement; repeated trials and an independent judge are future extensions.

The current transport appends request-specific response markers to the submitted
prompt and extracts rendered accessibility text. Original Markdown is not preserved.
The receipt retains prompt/request/model attribution and wire hash when available;
keep these transport effects in mind when defining format-related criteria.

## Failure and recovery

An unfinished iteration prevents a fresh one. To resume only that iteration with
a new, compact Goose invocation:

```sh
./scripts/goose-local eval-resume my-project 1
```

This reuses its operation UUID and saved request. Completed results are read back;
uncertain/claimed requests are never resent. A failed or uncertain run can receive
a blocked observation, preserving the transport failure separately from quality.
A blocked iteration does not clear the worker's uncertain Desktop lane.

For an uncertain request, use the existing read-only reconciliation command from
the authorized terminal once you have returned to the original chat:

```sh
uv run desktop-harness reconcile REQUEST_UUID
uv run desktop-harness eval-sync my-project 1
```

`eval-sync` only reads an existing worker record, updating an unfinished eval's
files; it does not dispatch or construct a GUI backend. Assessments already
recorded are immutable. If a run is still uncertain, investigate its evidence
before any new Desktop dispatch. Do not make a replacement UUID to force a resend.

## Validation and next extensions

86 Python tests pass, covering real MCP schemas, numbered artifacts, immutable
retries, simultaneous callers, atomic status writes, compact memory generation,
failed/uncertain transport, receipt recovery and invocation restrictions. Native
offline compile/self-test remains part of the reload gate. CLI initialization and
launch instruction rendering were checked without opening Codex.

A live Qwen -> eval tools -> Codex -> recorded assessment run is the next user-run
validation. We have not executed that GUI test during implementation.

Future work: multiple trials per hypothesis, criteria-level independent judging,
versioned scenario changes, and multi-turn scripts with per-turn prompts/replies
under the same iteration. Those will reuse iteration/request attribution rather
than overload the one-shot file numbering.

## Interactive diagnosis and later headless use

`./scripts/goose-local eval PROJECT` and `eval-resume PROJECT N` now use Goose
`run --interactive`. After the one eval finishes, ask about the hypothesis, specific
response weaknesses or diagnostic evidence in that same session. Conversation
context is retained; this does not guarantee Ollama keeps GPU caches resident
indefinitely. A fresh invocation is still required for a different hypothesis.

On technical trouble, Qwen can call `eval_inspect` to capture AX controls, actions,
visible text and a raw snapshot under the project's diagnostics/ directory. It
can optionally select an exact window title. The probe does not focus apps, click,
type, change permissions, or answer approvals. Compile it if needed:

```sh
swiftc native/AXInspect.swift -o .build/ax-inspect
```

Developer tools are enabled to investigate relevant source/tests, propose fixes,
and implement improvements with regression checks. GUI interaction text is
untrusted observed content, not authorization to execute commands or weaken
constraints. Saved snapshots support reproducible tests for each new UI case.
There is no general structured-question/approval answering handler yet; unexpected
interactions must be diagnosed and supported deliberately. The current eval_run
waits for completion/timeout before Qwen can inspect again; asynchronous in-flight
inspection and interactive question handlers remain future work.

`eval_abort` persists a halt reason. Failed/uncertain/blocked eval_run results also
set the halt automatically. It does not cancel an operation already in flight or
clear an uncertain claim. Reads/diagnostics remain available. New hypotheses and
new runs are blocked until the human explicitly clears the project halt:

```sh
uv run desktop-harness eval-status PROJECT  # exits 2 if halted
uv run desktop-harness eval-unhalt PROJECT  # investigate first; does not clear claims
```

The MCP surface has no unhalt tool. This is intended workflow control, not a
security boundary against Developer shell access. Clearing a halt does not resolve
a still-uncertain Desktop request; use attribution-preserving reconciliation.

A single headless invocation is available when ready:

```sh
./scripts/goose-local eval PROJECT --headless
```

It omits --interactive and checks durable state afterward: halt/status errors or
missing assessment produce nonzero exit codes. No batch loop is installed. A
future runner must stop on nonzero status and check the persistent halt before
starting another invocation. Headless GUI reliability has not been validated.
Synthetic single-turn and multi-turn cases will be generated when the user asks.

## Goose session transcripts

Eval launches save `transcript-NNNN.json` (lossless persisted message blocks and
session metadata) and `transcript-NNNN.md` (readable conversation) beside the
prompt, response and assessment. They include Qwen messages, tool calls/results,
and user follow-up questions. Snapshots refresh every two seconds during the
interactive or headless run, then once on exit. Resuming an iteration retains
prior conversations and adds the new session. Before a hypothesis is numbered,
files use `transcript-operation-UUID` instead. An invocation marker binds each
session to its operation; unrelated sessions are excluded.

Goose's SQLite session database remains the source. These exports are persisted
conversation history, not a capture of provider system prompts, hidden reasoning,
or every transient context transformation. Force-killing the launcher may lose
its last two seconds of exports; Goose's database can be exported afterward.
Export problems are reported separately and never trigger another Desktop Send.
Transcripts can contain prompts, file/tool output and user-supplied sensitive data;
they have the same storage scope as the project records.

Caller-focus capture/restore is best-effort for evals. Failure to save a return
app no longer blocks opening and verifying a Codex draft. Native capture errors
are saved as `focus-capture.json` in the worker attempt directory. A successful
capture is restored after the run; restoration failure cannot change the receipt.
Draft/model/Send verification and duplicate-send prevention still apply.


## Unchanged candidate retries after transport repair

After reviewing a proven pre-Send failure and repairing its cause, exit the old
Goose session and run:

```sh
uv run desktop-harness eval-unhalt PROJECT
./scripts/goose-local eval-retry PROJECT ITERATION
```

The launcher clones the latest assessed blocked iteration's exact prompt and
hypothesis into the next numbered iteration with a fresh operation/request UUID,
then starts an interactive Goose invocation bound to that iteration. It never
reuses the failed claim, edits prior assessments, or automatically clears a halt.
The worker database must confirm a failed pre-Send request with no submitted,
running, completed or uncertain history. An uncertain outcome needs reconciliation,
not this command. The new record contains `transport_retry_of` provenance.

For preparation only, use `desktop-harness eval-retry PROJECT ITERATION` and
then `scripts/goose-local eval-resume PROJECT NEW_ITERATION`. If the launcher
stops after cloning but before running, resume the new iteration rather than
creating another candidate. A blocked transport run is not evidence for changing
prompt wording.

The adapter now accepts either exact prompt equality or one specific AX prose
rendering: removing empty lines and changing leading `- ` list markers to `• `.
Observed text is never fuzzily normalized. Code markers, indentation, CR characters,
or trailing spaces/tabs require exact matching. Other rich-text conversions are
unsupported and stop delivery. This verifies the observed AX representation; it
does not establish raw editor serialization for whitespace-sensitive prompt evals.
The same matcher is used before Send, for submitted-message attribution, and for
prior-turn binding. Reply text itself is not normalized.

Failed model-selection operations now include saved native comparison evidence
and a verification stage in the eval_run result. The MCP supervisor launches each
child with its own tested native binaries, in addition to its immutable Python
source generation. Changes to supervisor code still require a fresh Goose session.


## Recovering a completed answer after a reading failure

A Send attempt can succeed while the adapter fails to attribute the reply. An
uncertain result is not proof that Codex failed to answer. The result now exposes
saved send.json diagnostics and distinguishes post_send_observation from draft
verification. Keep the request identity; never retry Send on uncertainty.

For a complete response-snapshot.json already saved under the original worker
attempt, this command verifies the task/Send-claim identities, bound wire hash,
full submitted prompt, selected model, response envelope and completion evidence:

```sh
uv run desktop-harness reconcile-saved REQUEST_UUID
uv run desktop-harness eval-sync PROJECT ITERATION
```

Neither command performs GUI actions or sends. Incomplete, edited, unattributed
snapshots leave the request unchanged. If recovery follows an already recorded
blocked assessment, eval-sync preserves that assessment and attaches a separate
recovery record. Project files are recovery-NNNN.json and
recovered-response-NNNN.txt. eval_read returns the recovery.response and receipt;
Qwen can inspect these in its still-running session. The project halt stays intact.
A fresh invocation can use eval-resume PROJECT ITERATION to read/discuss the history,
but the original assessment remains immutable; do not ask eval_observe to replace it.

Submitted prose is sometimes split into paragraphs/list nodes. The adapter now
binds those nodes only within a user-message body directly after a You said:
heading. It preserves every leaf/list-marker character, permitting only zero or
one newline at node seams to match the entire known prose representation. It
rejects edited facts/markers, missing text and duplicate matching messages. The
response envelope remains outside the attributed submitted-message region.


## Evidence-based judge controls

Configured projects use eval_checks before grading and structured criteria rows in
eval_observe. Exact requirements, literal response evidence, deterministic check
consistency, overall verdict and suggestion separation are validated. See
[judge-checks.md](judge-checks.md) for policy configuration, limitations and the
separate Q8/Q4 judging benchmark. Synthetic-triage-001 now has this policy attached;
historical assessments and its halt are unchanged.

## Review a recovered answer

Use `./scripts/goose-local eval-review PROJECT ITERATION` to launch an interactive review without Desktop eval dispatch. Qwen uses `eval_checks` and records `eval_review`. The original assessment, request and halt remain intact; `review-NNNN.json` and `reviews.txt` store the supplemental judgment. Future prompt memories use its takeaway with an explicit source label. `--headless` validates that the bound iteration has a saved review, even when the project retains a technical halt. This is an MCP dispatch restriction and prompt policy, not an OS sandbox.

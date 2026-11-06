# Codex Desktop harness experiment log

## 2026-10-02 — scope and initial inventory

Goal: run an outer controller on local inference and expose tools through MCP that
eventually submit requests to the actual Mac Desktop app and observe outcomes.
An independent Codex app-server is not considered equivalent to driving Desktop.

Repository: `~/git/l/codex-desktop-harness`. Git initialized; no remote,
commit or push. Models, virtualenv, raw traces, screenshots and SQLite state are
ignored. No system-wide tool installation or Codex configuration changes.

Observed:

- ChatGPT Desktop version 26.930.21537, installed in `/Applications/ChatGPT.app`.
- Existing Ollama 0.34.4 at `/opt/homebrew/bin/ollama`, already serving localhost
  on port 11434. No model loaded at the initial `/api/ps` query.
- `qwen3.8:27b` already installed, digest
  `aaee06c39dcf2437cde036998d960e1fc1494b8191be7cc9657d01e509097813`.
  Reported 27.3B parameters, Q4_K_M, approximately 17.7 GB weights, with tools,
  vision, completion and thinking capabilities. A separate `qwen3.8-256k` alias
  is also installed. Neither model was downloaded or altered.
- Choose `qwen3.8:27b`, disable thinking for dispatch, request 8192 context for
  the initial measurement. Maximum advertised context is not our allocated
  context; start small and measure memory/latency.
- Built-in `cua.getApp('ChatGPT')` was denied: "Computer Use is not allowed to
  use the app 'com.openai.codex' for safety reasons." Do not work around this
  session's self-control restriction using another UI tool/private IPC.
  External adapter code can be developed, but live UI validation is left to a
  user-run terminal experiment. No live prompt was sent to Desktop.

## Implemented first slice

- Python project managed by existing `uv`; official MCP Python SDK 1.30.0 in
  repo-local `.venv`, reproducible dependency lock in `uv.lock`.
- Real stdio MCP server with capability discovery, draft preparation and receipt
  reading. SQLite persists UUID idempotency: identical retries reuse the draft;
  a changed payload under the same ID is rejected.
- Outer Ollama tool loop discovers the MCP schemas and executes calls through
  an actual MCP client, not local function imitation. Six-step bound and strict
  equality checks keep the model from changing the user's authorized payload.
- Deep links encode prompt/workspace; preparation does not imply submission.
  A separate user-run `open-request` command opens a draft without pressing Send.
- Audit events store payload hashes. The private SQLite draft and optional raw
  model transcript contain prompt text and are mode 0600 and Git-ignored.

Sources:

- [Supported app deep links](https://learn.chatgpt.com/docs/reference/commands)
- [Qwen3.8 Ollama model](https://ollama.com/library/qwen3.8)
- [Ollama tool calling](https://docs.ollama.com/capabilities/tool-calling)
- [Official MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)

## Pending live capabilities

Accessibility inspection, targeted Send action, existing-chat continuation,
response extraction and turn-completion detection have not been validated.
No screenshot/vision benchmark yet. No claim of end-to-end Desktop control.
The adapter currently advertises `live_submission=false` explicitly.

## Local inference measurements

Two runs on the existing Mac Ollama endpoint. One tiny dispatch task, not a
coding/vision benchmark. Raw traces are ignored in `work/`.

| Run | Inference requests | Wall seconds (sum) | Load seconds | Generated tokens/sec |
| --- | ---: | ---: | ---: | ---: |
| cold | 4 | 16.33 | 6.90 | 63.9 |
| warm, same UUID retry | 4 | 8.37 | 0.01 | 63.9 |

Same UUID used in both real model runs. Store counts after retry: {'requests': 1, 'audit': 1}.
No duplicate request or audit event was created.
Ollama `/api/ps` reported the whole model on GPU: 18,063,902,636 bytes (~18.1 GB)
with an 8192-token context. This is runtime-reported allocation, not total system memory.

Verification: four tests pass: stdio MCP discovery/calls, retry collisions, invalid
workspace/prompt rejection, and deterministic rejection of model-modified draft text.
Native AX probe compiled with `swiftc`; not executed. A second warm run verifies
retry behavior through the actual local model/MCP path. No Desktop prompt submitted.

Setup repair: Hatch required an explicit `src/desktop_harness` package mapping.
MCP SDK returned text JSON without structuredContent; integration tests accept its
actual negotiated result shape. SQLite connection cleanup was made explicit.

## Next step

Run the documented read-only AX inspection from an external terminal, then open
and inspect the harmless draft. Live submission depends on identifying the exact
composer, Send and running/completion controls. No permissions were broadened.
The extensibility report is saved in `docs/extensibility-report.md`; none of its
proposed policies or hooks are installed.

## macOS 27 permission-label correction

User confirmed Golden Gate 27.0. The UI permission is labeled **Device Control
and Data Access**, replacing **Accessibility**. Updated the external validation
guide and native probe message. `AXIsProcessTrusted()` still names the API-level
check. No OS permissions changed.

Source: [Synergy macOS 27 permission guide](https://support.symless.com/hc/en-us/articles/35743428145169-Troubleshooting-macOS-Device-Control-and-Data-Access-previously-Security-Privacy-in-Accessibility).

## First user-run accessibility snapshot

Read `work/ax-before.json` produced by the user. Permission passed (`ok=true`),
one Codex window, 59 nodes, but no composer/Send control. Tree reached the
probe's depth-16 cutoff. Corrected a bug: the prior truncation flag only tracked
node budget. Raised bounds to depth 48 / 4000 nodes and added child counts and
explicit truncation reasons. Compiled updated probe; no live AX operation by agent.
User must rerun the probe for the deeper snapshot.

## Deeper user-run snapshot

Updated snapshot reports `ok=true`, no depth/node truncation, one window and
1283 nodes. Identified the chat composer as `AXTextArea` labeled "Do anything",
with `value_settable=true`. A second text area belongs to the document panel,
so role alone is insufficient for targeting. Current empty composer shows voice
controls, no Send button. Input and native action execution remain untested.
Next user-run step: open the prepared harmless draft and capture `work/ax-draft.json`.
Raw paths/text stay in ignored work; do not hardcode ephemeral tree indices.

## Draft navigation and requested Desktop model

User confirmed the deep link filled the composer in a new project chat. The
user-generated `work/ax-draft.json` had no composer, Send, or model control and
144 elements with unreadable roles. Its `truncated=false` was insufficient to
establish a usable tree; the cause of unreadable elements is unverified. Added
`incomplete`, `unreadable_elements`, and button `enabled` metadata to the read-only
probe and compiled it. Requested a fresh settled draft and model-picker capture.

User requests GPT-5.6 for harnessed Desktop sessions. Qwen remains the external
controller. Exact Desktop availability and session-specific selection await UI
evidence; no global defaults changed. Official model documentation describes the
picker beneath the composer: https://learn.chatgpt.com/docs/models .

## Send and multi-step model-menu evidence

Fresh draft and three menu captures are complete: no truncation or unreadable
elements. Draft matches the exact trusted task prompt, and one enabled AXButton
is labeled Send. Model sequence: composer model popup → Select model menu item
→ GPT-5.6 Sol model item. The third capture contains the live menu announcement
"GPT-5.6 Sol Standard, 2 of 5."; closed-picker confirmation remains pending.
GPT-5.6 Terra and Luna are also listed, but Sol is the target for this spike.

Important native-action limitation: Send and web model menu items advertise
AXShowMenu/AXScrollToVisible, without AXPress. Finding an enabled control does not
prove it can be activated through a supported AX action. No action attempted.

Added `inspect-snapshot` CLI to analyze saved snapshots without desktop access.
Verified against real draft and third menu capture; it distinguishes open-menu
evidence from closed-picker verification, reports advertised press support, and
never claims live submission. Existing four integration tests pass.

## First completed Desktop round trip (manual Send)

Read user-generated `ax-ready.json` and `ax-complete.json`; both complete with no
unreadable elements. Ready snapshot has exact trusted draft, enabled Send, and
closed-picker **GPT-5.6 Sol Medium**. Completed snapshot retains that model label,
has the submitted prompt as static text, exact response **DESKTOP_SPIKE_OK**, and
explicit **Response complete: DESKTOP_SPIKE_OK** announcement. Composer returns
to placeholder text; Send disappears. The previously observed open-menu Standard
announcement is not the final closed-picker effort label; final label is Medium.

Extended offline inspector with expected-response evidence: exact submitted
prompt, exact response, explicit completion marker, complete tree, and draft no
longer present in composer. Verified with real completed snapshot; four existing
tests pass. This is evidence from a manually submitted test, not a durable request
receipt: `request_to_chat_binding_verified` and `live_submission_verified` remain
false. No database state changed.

Remaining work: native activation capability probe (web AX controls do not list
AXPress), fresh window/chat binding, model selection enforcement, bounded polling,
uncertain-submission recovery, and per-request completion attribution. Repeated
identical prompts or stale completion announcements must not produce new receipts.

## Prepared restricted picker activation experiment

Added AXPickerProbe.swift: one permitted action on the model popup only, with
frontmost/window/draft/project-label/composer-scope checks and immediate fresh
revalidation. AXPress and AXShowMenu are separate user-selected experiments, no
automatic retry/fallback. Records action return and bounded menu observation. No
Send, mouse, keyboard, app activation, or permission prompting implementation.

Compile passed. Offline self-test passes six rejection cases. First self-test
caught overly broad composer/Send scope; corrected selector to reject window-level
and project-header-containing scopes. Verified actual saved ready snapshot selects
GPT-5.6 Sol Medium. No live action executed by this agent; user-run probe pending.

## First user-run AXPress result

User ran the picker probe. It passed preconditions and attempted AXPress once on
GPT-5.6 Sol Medium. API returned success (AX error 0), but the bounded observation
did not find the expected Select model menu item. No observation read/focus error
was reported. This does not establish a successful picker transition. No prompt
submission attempted. Next separate experiment is the advertised AXShowMenu action,
with menus closed and the same exact draft foreground. No automatic fallback run.

## AXShowMenu result and prepared mouse fallback

User-run AXShowMenu on GPT-5.6 Sol Medium returned native success/error 0 but no
expected menu observed within three seconds. No focus/read error recorded. Both
AX action experiments are inconclusive for effective activation on this control.

Added separate explicit `click` experiment using fresh picker AX position/size
and on-screen center. Validates bounds, unique composer scope, exact draft,
project label and foreground before posting one mouse down/up pair. No Send,
keyboard, automatic retry or global permissions changes. Compiled successfully;
six rejection self-tests and real saved selector check pass. No live click run
by agent; user-run result pending.

## Coordinate picker click succeeded; model-list probe prepared

User confirmed first-stage picker visibly opened. Result also reports
menu_open_observed=true and items Select model, Enable fast mode, Reset to default,
Power. This verifies the mouse fallback against the installed app. Raw click
coordinates remain in ignored work; no fixed coordinates added to code.

Added `model-list` mode: starts from closed menus, validates/clicks composer
picker, observes first-stage menu, revalidates exact enabled Select model menu
item, clicks it once, observes list containing GPT-5.6 Sol. Stops with list open;
no model selection or Send. Keeps first-stage evidence if second stage fails.
Compile/self-test pass. Offline selector finds Select model in actual saved
first-stage capture and rejects actual already-open model list. Live test pending.

## Model-list success and exact-label selection

User-run model-list probe reports both stages observed and includes GPT-5.6 Sol
in the live list. User emphasized changing model order; adopted explicit model
label argument, exact AXMenuItem match, fresh bounds at each click, and rejection
when missing, disabled or duplicated. No ordinal/index coordinate target.

Added `select-model 'GPT-5.6 Sol'` workflow: starts with menus closed, opens picker
and list, selects exact model, observes selection evidence, toggles composer popup
closed if needed, verifies settled model label with unchanged draft. Does not set
reasoning effort; returns full final label. No Send. Each action gets a fresh tree
and target validation. If model disappears or menu structure changes, abort without
substitution. Models outside the visible AX tree currently require future scrolling
support; no guessed scroll or alternate model chosen.

Compiled; eight rejection checks and two model-order permutations pass offline.
Exact selection against saved actual model-list snapshot passes. Live selection
and menu closure remain pending.

## Inconsistent selection runs; stabilization and hit testing

Compared three user-run select-model logs. Run 1 (already selected GPT-5.6 Sol)
verified closed picker; run 2 (started GPT-6.1 Sol) did not observe requested model;
run 3 observed selection evidence but failed closed-picker verification. User saw
apparent Luna selection in run 2; logs do not record that model, so root cause and
exact wrong model are unverified. Both failed runs reported ok=false and no Send.
All three used same recorded model click center; coordinate equality does not prove
rendered-menu alignment. Transient unreadable AX nodes were present in runs 2/3.

Revised every mouse action: re-resolve target until native element and rectangle
stable for 0.6s, minimum 0.8s observation, maximum 4s; recheck fresh geometry;
AX hit-test center and verify hit element or its parent chain equals exact target
before clicking. Hit-test failure aborts; no unverified coordinate fallback. Log
settling time/title/coordinates/hit checks and model announcements.

Selection evidence now requires model list has disappeared, preventing the old
already-selected composer label from falsely acknowledging the click. Dismiss
remaining effort menu with a single foreground-guarded Escape, then verify closed
picker. Escape is the only keyboard input implemented. No Send.

Compiled; eight negative selector cases, two order permutations, saved real target
selection, and four existing Python tests pass. Live stabilized workflow pending.

## Stabilized run 4: coarse hit-test result

User saw no action; output reports hit_test_wrong_target: AXGroup / empty title.
Probe aborted before the first click. The native point hit test returned a group
rather than the intended picker or its descendant. This does not establish that
the point was wrong; the returned group may be an ancestor container.

Added restricted coarse-group handling: returned group must be found uniquely
in the fresh app tree, contain the intended target, and exactly one enabled
interactive control may contain the point across the full window tree. That
control must be the exact selected target. Ambiguity or unreadable interactive
bounds abort. Target geometry still must settle, identity and bounds revalidate,
and final selected model still requires verification. Added diagnostic hit role,
target title and spatial candidates for rejected checks.

Recompiled; eight negative cases, two reordered model lists and real saved model
selector pass offline. No live click executed by agent. User-run revision pending.

## Run 5: unique spatial target, unrelated native group

Result reports no action attempted. Native hit returned AXGroup with no target
containment, but the unique eligible interactive control at the point was exactly
GPT-6.1 Sol Medium. Native hit-test hierarchy is inconsistent with the spatial
tree for this sample; cause unverified. Do not treat the hit as an authoritative
point-to-control mapping for this experiment.

Added explicit `--spatial-only` option. When native hit returns a coarse AXGroup,
it allows clicking only the unique enabled named control covering the point,
with stable geometry/fresh identity/draft/project/foreground checks retained.
Native hit remains logged as unmatched; it is not relabeled success. Named
non-group wrong hits still reject. No Send or fallback model. Exact label and
post-selection verification unchanged; menu dismissal uses Escape.

Compiled and offline selector checks pass. Live test pending. This experimental
option is separate from a production adapter; geometry cannot eliminate every
overlay/timing issue, so terminal result still must verify the selected model.

## Run 6 verified model switch; nonce-bound Send experiment prepared

User-run spatial-only workflow succeeded from GPT-6.1 Sol Medium to GPT-5.6 Sol
Medium, with picker closed. Exact model target settled at y=1271.5 rather than
y=1376 in earlier inconsistent attempts. This supports geometry settling as useful;
it does not conclusively establish the prior failure's cause. Per-click settling
was about one second. Coarse native group hits logged separately from click policy.

Added explicit `send-test` mode, separate from picker modes. Only accepts exact
harmless prompt containing response token derived from trusted task UUID. Requires
exact draft, project label, model, Send identity, stable bounds/spatial checks.
Creates and fsyncs an exclusive per-UUID claim before dispatch, revalidates after
claim creation, clicks once, polls up to 60 seconds for exact submitted prompt,
exact response and explicit completion marker with same selected model. Failure
or timeout remains uncertain and blocks retry under that UUID. No generic prompt
submission or SQLite receipt integration yet; claims are ignored work artifacts.

Compiled; native self-test passes ten rejection cases, two model-order cases and
real file claim creation/fsync/duplicate denial. Four Python tests pass. Ran local
Qwen MCP controller on work/task-send.json: prepared/verified fresh request
a610d404-63a4-4425-8f4f-79f741c32900. No UI opening or Send executed by agent.

## First automatic Send completed; one-command workflow

User-run ax-send-model.json verified GPT-5.6 Sol Medium with closed picker.
ax-send-test.json reports submission_attempted=true, completion_evidence_verified
=true, completed_test, and exact unique response token for request
a610d404-63a4-4425-8f4f-79f741c32900. Its claim exists with mode 0600 and matching
completed_test status. Starting with 5.6 already selected is sufficient for this
Send test; a real 6.1→5.6 switch was verified separately in run 6.

Added terminal `desktop-test` workflow: generates new UUID/token task, calls local
Qwen controller/MCP prepare/status, validates prepared hash/workspace, opens draft,
allows focus-switch countdown, runs exact-model selection then native Send test
only on selection success, stores per-request traces and result under ignored
work/desktop-tests/. Sender remains one-attempt nonce-bound, not generic UI MCP.
Reports uncertainty after possible dispatch on failure/interruption and does not
automatically retry. Generic SQLite preparation status remains distinct from
user-run native completion receipts. This wrapper has not yet been live-tested.

Two new workflow tests verify failed model selection blocks Send, and mismatched
response token cannot complete request. Six Python tests pass. No UI action by
agent. Terminal is still required for permission attribution; foreground/focus
is required during native observation. Background/unattended operation unverified.

## One-command live success and explicit response return

Verified user-run combined workflow for request
272cfc92-691d-45c3-acfa-8966e5b81266: local Qwen preparation, model selection,
automatic Send, unique response/completion evidence, completed_test and verified
GPT-5.6 Sol Medium. The reader already inspected actual AX response text but
previously only emitted expected_response and verification booleans.

Added response_text and completion_marker_text from actual matching AX strings;
wrapper exposes response_text and requires its equality to the fresh token before
completed_test. This remains a known-token reader; arbitrary multiline replies,
code blocks, multiple assistant messages and tool runs are not yet extracted.
Transient last_observation_error from intermediate AX trees does not negate a
later fully verified completion.

Native compile/self-tests pass. Added positive response-return wrapper check;
seven Python tests pass. New response_text output awaits next user-run command;
existing completed receipt preserved. No extra live test required to record the
already successful round trip.

## General queue/worker prototype built with parallel agents

Delegated durable lifecycle, MCP worker tools and offline general response reader
to three subagents. Integrated an external DesktopBackend and submit/worker/response/
reconcile/inspect-response CLI commands. Native send-request/read-request modes
use uncapped AX values and per-request response envelopes. Existing token smoke
mode retained. Preparation-only Qwen controller tool catalog is explicitly limited
to its original three tools so newly registered queue tools do not broaden it.

Queue claims are globally serialized, persist uncertainty before dispatch, and
consume a single attempt. Completion requires native UUID/attempt/workspace/wire
hash plus DB original prompt hash and exact model verification. Long jobs are
polled read-only after observed submission. Read-only reconciliation observes the
original chat without opening/re-Sending. Generic output is rendered leaf text;
unknown text controls, partial/capped captures and ambiguous envelopes reject
instead of returning partial content as complete. AXInspect now flags value clipping.

Validation: both native sources compiled; Swift self-test includes ten rejection
cases, two model-order cases, real claim IO/idempotency and three envelope cases.
37 Python tests pass: queue concurrency/migration, cancellation/restarts, strict
receipts, real stdio MCP queue/status/response, parsing and backend/reconciliation
fixtures. One reconciliation fixture initially failed because macOS /var temp path
was not canonicalized; corrected fixture to real path, matching Store canonical
workspace behavior. No general live UI operation performed by agent. First user-run
generic job documented in docs/worker-quickstart.md. No commits/push/settings changes.

## One-step ask command

Added ask --prompt / --prompt-file to queue, dispatch the explicit request and
print its completed answer. ask --request-id runs an existing queued request or
returns its saved completed answer. Targeted dispatch avoids consuming unrelated
older queue jobs and retains the global uncertain-attempt block and single-attempt
claims. Unsuccessful outcomes print status and exit nonzero. --json preserves
full machine-readable receipt. Three targeted-worker tests added; 40 tests pass.
No live UI operation executed. Existing user UUID df03bde4-a634-4c45-bdb8-527dab290845
can be used directly without queueing another request.

## First general live failures: exact draft verification

User-run queued request df03bde4-a634-4c45-bdb8-527dab290845 and second ask request
76389aa2-8d07-40e3-a432-b1f98dca602d both failed model selection at
draft_mismatch_or_ambiguity. Neither reached Send. Exact observed values were
not recorded, so newline/AX transformation is a hypothesis, not a confirmed cause.
Changed generated envelope instruction to one line, preserving original user
prompt content; known working smoke requests were single-line. Added expected
and observed composer values to ignored selection diagnostics on draft mismatch.

ask --request-id now replaces only recorded model-selection-before-Send failures
with a fresh UUID and preserved original payload, rather than reusing a consumed
attempt. Unknown/uncertain attempts remain blocked. Backend failure message now
includes actual probe reason. Two retry-boundary tests added; 42 tests pass and
native compile/self-tests pass. General live validation still pending.

## Retry passed draft check; menu underlay false ambiguity

Latest user-run request 4c0e39d7-6d2f-4889-a106-8ef15e606eb3 passed exact draft
verification, opened picker/list, then stopped before clicking model. Log showed
AXMenuItem GPT-5.6 Sol and the larger AXTextArea composer covering the same point.
The spatial uniqueness check incorrectly treated composer underlay as menu-level
ambiguity. This is a different failure from the earlier draft mismatches.

Changed menu-item spatial checks to consider eligible AXMenuItems on the active
menu layer; other control target checks retain full control-role overlap checks.
Added native layer self-check. Also select-model now verifies and returns without
opening the picker when the exact requested model is already selected and menus
closed. Backend error now includes stage-specific native error instead of generic
verification failed. Recompiled; native self-tests and 42 Python tests pass.
No Send occurred in the failed run; original ID can be replaced safely via ask.

## First generic Send occurred; reader project-control assumption corrected

Request 5187c9e5-40f8-48b2-8c8d-e4804b7ede16 selected-model fast path passed and
posted Send once. User reports Codex answered. Reader did not verify completion:
submitted_message_not_observed was an early observation, and subsequent reads
reported response_project_label_mismatch. Inspection of earlier successful
ax-ready/ax-complete snapshots proves draft Change project control disappears
after submission. Corrected native reader to use available visible project labels,
matching offline parser, while retaining scoped prompt/envelope/model checks.

Added uncapped protected response-snapshot.json during general native reads, so
future failures retain the actual post-submit tree for offline analysis. Native
fixture now models absence of Change project after submission. Recompiled; native
self-tests and 42 Python checks pass. No resend: uncertain request must be observed
using reconcile on its original chat. Generic completed receipt still pending.


## General answer recovered; completion announcement is transient

Read-only reconcile for 5187c9e5-40f8-48b2-8c8d-e4804b7ede16 retained a complete
uncapped snapshot. Exact submitted prompt, model and response envelope matched;
answer was fully present. The temporary Response complete live-region text was
absent, so the old reader incorrectly left the attempt uncertain. The snapshot
instead exposes enabled Copy, Rate response and Fork chat from here controls after
the END marker, an enabled idle composer, and no chat stop/progress controls.

Both offline and native general readers now accept that durable combination.
A closed envelope alone still cannot complete; actions preceding this answer
cannot qualify; any stop/progress control prevents completion. Added regression
coverage: 43 Python tests pass; Swift compilation and six reader self-test cases
pass without Desktop access. Native polling update awaits a fresh live run.

Recovered this existing attempt from its saved snapshot, checked stored request,
attempt, workspace, original/wire hashes, and model, and wrote a protected offline
receipt with snapshot hash. SQLite state is now completed and the stored answer
is retrievable. No prompt was resent and no live GUI actions were performed.


## Automatic foreground acquisition for fresh requests

User correctly pointed out that a manual draft switch contradicts the intended
one-command harness. General ask/worker now open the deep link explicitly in
com.openai.codex and mark the wire task auto_focus=true. Native select-model
unhides and activates the single target app, waits up to five seconds for verified
foreground PID, then up to ten seconds for exact draft prompt/project/composer
readiness. No click occurs during readiness polling. Subsequent action focus
checks remain enforced; dry runs and read-request never acquire focus.

Default ask/worker startup delay is now zero; --switch-delay remains an optional
startup delay. Read-only reconciliation retains its original-chat countdown, as
existing-chat routing is not implemented. Legacy desktop-test behavior remains
unchanged. Native build and self-tests pass; 44 Python tests pass, including explicit
app targeting, auto_focus task intent, and activation-failure blocking Send.
Live automatic activation still awaits a user-run validation; no GUI action was
executed by this agent. Desktop must remain foreground during the GUI workflow.


## User validated automatic fresh run; Qwen submit/read orchestration added

User reports the fresh general ask roughly worked: Desktop used bold and a
numbered list while terminal output correctly extracted content without that
formatting. This validates automatic focus and the updated native response path.
The representation remains rendered AX text, not source Markdown.

Added agent-ask: real Ollama tool loop exposes only adapter_capabilities,
submit_request, request_status and get_response through stdio MCP. Trusted UUID,
exact original prompt, canonical workspace and Desktop model must match all tool
arguments. MCP queues only; after a verified queue call the external runner invokes
the targeted worker at most once, then supplies its status to the local model.
MCP answer receipts are compared to the durable store and printed directly.
Repeated model submit calls for the same UUID cannot dispatch twice. No model
shell/UI tools, autonomous prompt edits, or automatic resend are exposed.

49 tests pass, including real stdio queue/response with simulated inference and
Desktop, modified-argument rejection, duplicate submit, queue-only and uncertain
outcomes. Actual qwen3.8:27b queued through real MCP and read pending status without
GUI actions in a separate validation DB. A second actual-Qwen run retrieved a
completed simulated Desktop reply through real MCP; its log is under ignored
work/agent-runs/baf0b277-6870-4ddd-acb2-fd1a519887c4/. This completion test used no
live GUI. Combined real-Qwen/real-GUI agent-ask awaits the user's external-terminal
run. No new model installs, settings changes, commits or pushes.


## Single-step Qwen live success; bounded same-chat REPL implemented

User confirmed agent-ask completed live, then requested problem solving with
multi-turn feedback and an interactive REPL. Added repl: Qwen proposes ask_codex
or finish, previews assessment/prompt, and pauses for Enter, steering text,
/ask local question, or /stop. User steering and exact MCP Codex responses enter
the persistent Qwen message history. Limits apply independently of model output;
three Codex turns default, no automatic retries. Discussion-only prose instructions
are applied to every dispatched prompt; this is not a new security policy.

Backend now accepts a trusted previous_request_id from the REPL, requires its
completed receipt and immutable wire hash, and carries the prior turn into the
new wire task. Native prepare-followup activates the existing app, checks exact
previous rendered response and request envelope, refuses newer manual/running
turns, then uses AXSetAttributeValue on the idle composer. Select/Send continue
checking prior-chat anchors. Each turn gets a separate durable request and claim.
Capture/restore-focus records the foreground external app PID/bundle and attempts
to return to it for terminal steering. GUI writes and focus restoration are not
live-tested yet. No arbitrary sidebar routing or existing-session resume added.

54 Python tests and native compile/self-tests pass, including steering, local-only
questions, response-fed follow-ups, hard budgets, uncertain stop, and backend
follow-up without a second deep link. Native adds five prior-binding checks.
Real Qwen + real MCP with simulated Desktop completed two turns in session
c73816fc-52e7-48bb-8a9b-789f6b66a3aa. Qwen's second prompt explicitly evaluated
FIFO vs weighted fairness and referenced the returned 3:1 reservation. An earlier
simulation found a plain-text final at the budget limit; REPL now accepts that
as a previewed final answer, retains every raw response, and reinforces the budget.
No GUI actions by this agent, settings changes, commits or pushes.


## REPL first live turn passed; follow-up activation failed before Send

Session 1270b846-571a-4fd7-aba0-1e8ee4e7bc51 completed request
89648382-d2db-4403-8eb3-86af436081a5. Qwen proposed a response-dependent revision
of Codex's priority-aware FIFO Approach 1. Follow-up request
fc1fde29-fc21-4f64-acf8-082a1c12d859 failed in prepare-followup with
 target_app_activation_not_observed. The saved caller was iTerm2. No follow-up
composer write or Send occurred. App activation returning true was insufficient;
first-turn deep-link opening had also foregrounded the app.

Follow-up backend now issues /usr/bin/open -b com.openai.codex without a URL before
native preparation. This requests foreground acquisition without a fresh draft.
Native skips redundant activation if already foreground, pumps the Cocoa run loop
while waiting for activation, and records observed foreground bundle on failure.
Exact previous response/chat checks remain mandatory before writing the composer.

Added narrowly scoped --resume: only recorded blocked sessions with a completed
prior reply and a trusted failed-before-Send follow-up are eligible. Receipts,
payloads, previous-turn linkage and pending proposal are checked against SQLite.
The consumed failed attempt stays immutable; a new linked session retains completed
history and Qwen proposes a fresh follow-up for user steering. Uncertain or submitted
turns are rejected. The user's saved session passed read-only resume validation.
55 Python tests and native compilation/self-tests pass. No live GUI action was
executed by this agent; foreground fix and follow-up writing await another user-run
validation. No commits or pushes.


## Same-chat second turn completed; local output budget exhausted

Resumed session 40d1bebb-e3da-45fb-83f5-f8c699bd742e retained first request
89648382-d2db-4403-8eb3-86af436081a5 and completed follow-up
2ed2aa13-216f-478f-9e15-44d502b6b1a0. Thus foreground acquisition, same-chat composer
writing, Send and response extraction succeeded. The next local response had empty
content, no tool_calls, and done_reason=length: the shared 512-token generation
budget cut off Qwen's structured action before it could be returned.

Made controller output budget configurable with legacy default unchanged. REPL
planning now allows 2048 tokens, logs budgets/token metrics, and retries only local
planning once at 4096 if Ollama explicitly reports truncation. A still-truncated
reply produces a precise local error without a new Desktop request. Plain-text
complete final replies are accepted as user-previewed finals without tool calls.
Resume now accepts planning-error sessions only when every saved Desktop turn is
completed, its receipt matches SQLite, and the last message is the exact verified
Codex tool result. No submitted/uncertain or dangling actions qualify.

56 Python tests pass, including truncation budgets, no redispatch, completed-history
resume, and plain-text finals. The user's two completed turns passed resume
validation. Real Qwen then produced a complete final synthesis from those saved
replies in validation session 402cfc44-fa3c-4f68-8014-344297172773; validation used
/stop before any Desktop dispatch. Original sessions and receipts remain preserved.
No GUI actions, settings changes, commits or pushes by this agent.


## Final REPL success and original-goal reconciliation

User confirmed the resumed workflow worked. Session
9bd20540-685a-4e72-bfed-a97c0ff6c14a is completed, retains the two completed Desktop
requests and stores a final Qwen answer. This establishes same-chat feedback and
synthesis through verified recovery, rather than a fresh uninterrupted reliability
run. Added docs/project-status.md mapping original goals to delivered capability,
untested boundaries, installation choices and next priorities. Corrected stale
README/quickstart statements that same-chat GUI work remained unvalidated.
Broader framework/community-tool research and Desktop extensibility deployment
remain unfinished. No commits or pushes.


## Goose full harness and test-gated MCP self-development — October 2, 2026

Installed Goose Desktop/CLI 1.53.0, configured an isolated repo profile with
Mac-local qwen3.8:27b (16k context, 4k output, thinking off). Developer extension
provides shell/edit tools; codexdesktop uses the stable stdio development proxy.
No PC endpoint, global Codex config, commits, pushes or permissions were changed.

Added real MCP contract tests and reload failure/recovery coverage. 66 Python
tests pass; gate also compiles Swift and runs its offline self-test. Candidate
snapshots retain last-good on failure, drain calls before swap, preserve SQLite
and never replay calls. Supervisor changes still require session restart.

Initial Goose doctor unexpectedly started an agent diagnostic session; it exposed
a protocol incompatibility: modern server/discover was rejected by MCP Python v1
as InvalidParams. Added a narrowly scoped correlated MethodNotFound response to
permit legacy fallback, with a regression test. No modern protocol is advertised.

Read-only Goose smoke session 20261002_2 successfully used Qwen to call
development_status, adapter_capabilities and Developer shell pwd. Logs:
work/goose-smoke.log. No Desktop GUI was operated.

A separate copied repo under work/goose-self-edit demonstrated self-development.
Qwen first added get_response description regression assertions and observed
failure, then updated the docstring to explain rendered-text/Markdown limitations.
It passed 66 tests, saw the candidate testing, then verified ready with revision
a687b695bf527de3dcb0b787de37abbb287c2ffc5775d51e5615177eecd49699
replacing 12814e39b25c6668dec9c9d5c02ef9552537e2c979da868cbfce4e4dcba727a9.
No MCP reconnect, queued requests, GUI actions or commits. Reviewed its two-file
diff and adopted it into the main repo. Log: work/goose-self-edit.log.

This establishes a small live self-edit/reload loop, not unrestricted autonomous
server maintenance or unattended Desktop reliability. Goose GUI remains untested.


## Goose exploration limit tuning

User session 20261002_3 exhausted the configured 25-turn budget while reading
most implementation/tests/docs. Latest Ollama usage reported 57,006 input tokens
against configured num_ctx=16,384. No fix was implemented in those turns.
Raised context to 32,768 and autonomous turns to 100; explicitly set automatic
compaction threshold 0.6, summarize fallback, four full recent tool outputs and
8,000-character tool response cap. Added bounded-exploration project hints and
a per-turn working-memory reminder. Updated both template and existing local
profile, preserving extension configuration. These are configuration mitigations;
a long development session still needs observation for compaction/repeatability.

The tuning smoke exposed a cold-start timeout while the supervisor waited for its
full test gate before accepting MCP initialization. Moved validation to a background
startup task: initialize returns immediately, first tool catalog waits for results.
Added a blocking-gate regression proving initialization completes before the gate
and tools wait for it. 67 tests pass. Budget environment smoke confirmed all six
updated values via Qwen's Developer shell.


## Fresh-task configuration after repeated read cycle

Resumed session 20261002_3 made 101 shell calls after the continuation prompt;
79 calls repeated three file-inspection commands. No tracked source/test difference
from the last passing generation. Raised context from 32k to 128k per user request,
lowered autonomous turns from 100 to 50, and set three identical consecutive tool
repetitions. This last setting cannot detect alternating-command cycles.
Added explicit rg/batched bounded reads/Developer edit/test/MCP-status guidance
and config/tasks/response-format.md for a concrete fresh-session change.


## Deterministic one-shot prompt-eval workflow

Added eval project initialization/context/read/hypothesis/run/observation MCP tools,
locked per-project authoritative ledgers and numbered prompt/response/eval projections
under ~/git/l/codex-evals. Compact memory is one JSON line per assessed iteration.
Eval launcher embeds scenario/memories, binds one operation UUID/project per invocation,
disables Developer tools and ordinary request tools, and explicitly enables the native
Desktop backend. Normal sessions retain GUI-eval dispatch disabled. Added eval-resume
and read-only eval-sync recovery. No live Desktop actions performed in this build.

Replaced fixed temporary status filenames with unique atomic replacements after
concurrent-write regression coverage. Increased MCP child timeout for long eval runs,
isolated validation from eval-only/GUI environment flags, added rg path propagation.
79 Python tests plus offline Swift gate; CLI init/launcher prompt rendering checked
without invoking Goose or Codex. First user-run live eval remains outstanding.


## Interactive evaluation diagnosis and halt controls

Eval and eval-resume now retain the Goose conversation via --interactive by default.
Developer tools re-enabled for source/test diagnosis and tested adapter improvements;
records and Send remain routed through deterministic eval tools. Added eval_inspect
for authorized read-only AX snapshots with bounded control/text summaries and raw
artifacts, plus persistent eval_abort. Technical run failures automatically halt
further runs. Human CLI status/unhalt retains uncertain worker claims.

Added optional single-shot --headless with durable completion/halt exit checking;
no batch scheduler. GUI question/approval handlers and in-flight asynchronous
inspection are not implemented. Inspection tests mock the process; no live UI
inspection or clicks performed. 86 Python tests and offline native compile/self-test
checks cover the changes. Synthetic cases deferred at user's request.


## Synthetic triage project and fixture workflow smoke

Created live project synthetic-triage-001 under ~/git/l/codex-evals, with seven
criteria for a discussion-only fictional four-ticket triage case. Live project
remains at zero iterations. A separate real Qwen/Goose/MCP run used an explicitly
synthetic backend response in work/synthetic-eval-smoke. Four tool calls, successful
exit, numbered artifacts and one memory line; verdict partial/3 correctly flagged
missing ordinary-ticket service-slot detail and related criteria gaps.

Preserved judge output but noted unsupported fixture/prompt causal attribution
and inconsistent C5 summary wording. Tightened invocation guidance to separate
observed omissions from hypotheses and respect synthetic receipt provenance.
No Desktop GUI actions occurred. Live run remains user-terminal-only because
built-in CUA refused com.openai.codex control for safety reasons earlier.
See synthetic-triage-validation.md for exact boundary and next command.

## 2026-10-02: first live eval blocker and transcript exports

Reviewed failed synthetic-triage-001 iteration 0001: optional caller-focus capture blocked dispatch before draft/Send, underlying native error was previously discarded. Made eval capture/restore best-effort, saved capture diagnostics, preserved failed request/assessment/halt, and corrected agent diagnosis guidance. Added operation-bound live Goose transcript exports beside eval records and backfilled the failed session. See docs/synthetic-blocker-review.md and docs/prompt-evals.md. Verification: 92 offline tests, including fake child-run exports on success/failure; live GUI retry remains user-run.

## 2026-10-02: iteration 0002 draft representation repair

Confirmed selection failure from saved native comparison: 12 blank lines removed
and four list markers rendered as bullets account for the entire difference.
Added saved fixture and observed failing native regression before repair. Added
narrow prose matching across draft/Send, response attribution and prior-turn binding;
code/indentation/trailing whitespace remain exact. Exposed comparison/stage diagnostics
in eval_run and added eval-retry unchanged-candidate provenance with fresh claims.
Fixed MCP generation selection of native binaries. Full immutable-generation gate
passed (101 Python tests plus offline Swift compilation/self-tests). No live UI actions,
project halt clearing or retry dispatch during implementation. See
synthetic-iteration-0002-review.md for the user-run validation command.

## 2026-10-02: iteration 0003 split submitted prompt and saved recovery

Send occurred and reply existed, but attribution required a single submitted prompt text node. Added structured split-prose binding and tests, exposed post-Send diagnostics, and reconciled the original request using only saved task/claim/snapshot evidence. Worker completed; historical blocked assessment and project halt retained with a separate recovery record. Complete generation gate passed (105 tests plus native self-tests/compilation). No GUI operations or resend. See synthetic-iteration-0003-review.md.

## 2026-10-02: deterministic judge checks and quantization preflight

Added eval_checks, explicit immutable judge policy, structured criterion/quote
validation and separate suggestions. Configured synthetic triage; confirmed its
slot is within bounds and distinct pre-Send/recovered transport facts. 113 tests
and native generation checks passed. Prepared controlled judging-only comparison
runner. Dragon and Mac currently advertise identical Q4_K_M model digest; requested
Q8 tag/endpoint, and preflight refused a mislabeled comparison. No new Codex sends,
inference, model downloads or global host/model changes. See docs/judge-checks.md.

## 2026-10-02 — supplemental reviews and matched speed measurement

Added eval_review and interactive/headless eval-review launcher. Reviews preserve original assessments and halt state, validate the same configured evidence/rubric rules, export separate records, and contribute source-labelled future memories. Added regression cases for recovered history, literal evidence, invalid suggestions, operation binding and headless completion. Transport-history checks now consult submission audit events before claiming a failed request was pre-Send. The Desktop adapter was not exercised live in this step.

Delegated a matched Ollama speed benchmark: 18 requests at 8k/32k/128k allocation with identical Qwen weights. Dragon was faster at small allocations; Mac was faster at the harness’s 128k allocation. Reports and bounded raw results are saved; no model installs or global settings changes. See speed-comparison.md and evals-next-steps.md.

Final validation: 121 Python tests passed; immutable generation a39dcbc67ea733aa04a2f7fd40db553e6edfed3d8fb64f833100690d6636a98e passed Swift compilation and offline self-tests (desktop_accessed=false). Real iteration-3 review invocation rendered successfully.

## 2026-10-02 — interrupted review schema fix

Inspected transcript session 20261003_4: nine rejected eval_review calls, no saved review. Root mismatch exact_requirement vs requirement was hidden by unstructured nested schema and misleading error wording. Added typed criterion schema, copyable check templates, aggregate semantic validation and one-correction stop guidance; preserved strict literal evidence and pass/suggestions rules. Captured actual rejected payload as fixture. 124 Python tests and native offline generation gate passed. See synthetic-review-schema-failure.md. No live Desktop interaction or eval record replacement.

## 2026-10-02 — simpler helpfulness elicitation case

Created helpfulness-elicitation-001 with an abrasive but reasonable wrong-colour delivery message, fixed replacement/return policy, four behavioral criteria and no numeric score. Initialized separate empty project and judge policy; no Codex dispatch. Added optional fixed_prompt_suffix policy validation and proposal guards to keep case text unchanged while Qwen varies a nonempty wrapper. A failing regression preceded the guard; all 126 Python tests and native offline generation gate passed. Real invocation rendered. See helpfulness-elicitation.md.

## 2026-10-02 — helpfulness grading tool-loop fix

Iteration 1 delivered successfully and saved the answer, but Qwen made 46 rejected grading calls over straight-vs-curly apostrophe quotes. Added unique source-span resolution for apostrophe/whitespace rendering equivalence, saved exact source quotes plus resolution metadata, and a transcript watchdog that stops Goose on three consecutive grading errors in a newly launched session. Regression replay passes in a disposable project; real assessment remains unrecorded for user-run eval-resume. All 130 Python tests and native offline gate passed. See helpfulness-tool-loop.md.

# External Desktop validation procedure

The current Codex session cannot operate itself through its built-in computer-use
tool. No alternate UI tool is being used to bypass that denial. Run this experiment
yourself in a terminal to collect the evidence needed for the next implementation.
Inspection and picker modes do not submit prompts or grant permissions. The explicit
nonce-bound `send-test` mode below attempts one harmless test submission.

## 1. Inspect accessibility

```sh
cd ~/git/l/codex-desktop-harness
mkdir -p .build work
swiftc native/AXInspect.swift -o .build/ax-inspect
.build/ax-inspect > work/ax-before.json
```

The probe targets only `com.openai.codex`, reads accessible windows, and does not
activate apps, inject keys, capture screenshots, or change TCC grants. If it reports
`accessibility_not_granted`, stop and review whether you want to grant your terminal
access in System Settings → Privacy & Security → **Device Control and Data Access**
on macOS Golden Gate 27. Earlier macOS versions label it **Accessibility**. Enable
the terminal application that launches the probe. We have not changed that permission.
Do not run this while another task is typing or modifying the desktop.

The JSON may contain private visible chat text. Keep it in ignored `work/`; inspect
locally and share only the relevant composer/button metadata. Tree paths are ephemeral,
values are truncated, and this probe is not yet a response/completion reader.

## 2. Open the prepared harmless draft

Find the UUID in `work/task.json`, then:

```sh
uv run desktop-harness open-request YOUR_REQUEST_UUID
.build/ax-inspect > work/ax-draft.json
```

Expected: a new local chat in this repository's workspace with this composer text:

> Reply with exactly DESKTOP_SPIKE_OK. Do not use tools or change any files.

Opening the URL is only a UI experiment. No submission receipt is recorded, because
we have not verified the resulting app state automatically.

## 3. Collect selectors and completion evidence

Wait until the prepared new project chat is visible and its draft has settled,
then capture `work/ax-draft.json` again. `ok=true` confirms window access;
`incomplete=true` means the tree was truncated or contained unreadable elements.
An incomplete tree cannot establish that a control is absent.

The requested Desktop model is **GPT-5.6**; Qwen3.8:27b remains the outer harness
model. Verify the exact available 5.6 label in the picker beneath the composer.
For a snapshot of the open picker, start this command, switch to the draft chat,
and open the model picker during the five-second delay:

```sh
sleep 5; .build/ax-inspect > work/ax-model-menu.json
```

Do not change the global model default. Session-specific model selection and its
verification must become part of the adapter before automatic submission.

Identify the composer role/identifier, Send button role/identifier, and any running
or Stop indicators from the fresh snapshot. If you choose to send the harmless
draft manually, compare a during-turn and after-turn snapshot. Verify the response
is `DESKTOP_SPIKE_OK` and that the draft belongs to the intended new chat.

Next adapter work depends on these observations: exact-window targeting, fresh
selector validation, one submission per durable request, accepted/uncertain state,
existing-thread routing, and a verified completion signal. Do not infer completion
from a fixed sleep or a stable visible text string.

## 4. Native relay alternative

No native relay package is installed. Review
[codex-mcp-bridge](https://github.com/buidangminh23/codex-mcp-bridge) before testing:
it uses private Desktop tools and currently verifies Claude-specific sender identity.
We must design a legitimate local-harness sender identity rather than pretend to be
Claude or bypass its checks. Desktop interposition also has capability tradeoffs.

## Observed model selection sequence

The user-provided captures establish this sequence on the installed build:

1. Open the model popup beneath the composer (initially GPT-6.1 Sol Medium).
2. Choose **Select model**.
3. Choose **GPT-5.6 Sol** from the model list.
4. Close the menu and capture the settled composer label before submission.

The open menu announced **GPT-5.6 Sol Standard, 2 of 5.** after selection.
This is model evidence, but the adapter still needs a closed-picker confirmation.
The reasoning/effort display changed during these captures; do not assume that
"Standard" is the same underlying reasoning setting as "Medium".

Analyze a capture without accessing the app:

```sh
uv run desktop-harness inspect-snapshot work/ax-draft.json --task-file work/task.json
```

Send is uniquely labeled and enabled in the draft snapshot, but does not advertise
AXPress. Native activation remains unverified. To collect response evidence now,
close the picker and capture the pre-send state, then manually send the harmless
draft and capture after the response is finished:

```sh
sleep 5; .build/ax-inspect > work/ax-ready.json
# After manually sending and waiting for the completed response:
sleep 5; .build/ax-inspect > work/ax-complete.json
```

Switch to the target chat during each delay. Fixed sleeps here allow you time to
switch windows; they are not completion detection.

## Completed manual spike

The settled model label is **GPT-5.6 Sol Medium**. The completed capture contains
exactly **DESKTOP_SPIKE_OK** and an explicit **Response complete: DESKTOP_SPIKE_OK**
announcement. This establishes observable completion for the manual test.

```sh
uv run desktop-harness inspect-snapshot work/ax-complete.json --task-file work/task.json --expected-response DESKTOP_SPIKE_OK
```

`expected_response_evidence=true` reports matching evidence in this saved tree.
It does not establish request identity, a fresh transition, or automatic submission.
The SQLite request remains prepared until the live adapter can validate these.

## Single-action picker probe

`native/AXPickerProbe.swift` is a user-run experiment. It requires the target app
to be frontmost, exactly one accessible window, the expected project label, exact
trusted draft text, and a unique enabled model picker in the composer/Send subtree.
It rejects an already-open menu and revalidates immediately before acting. Project
label checks cannot prove the absolute workspace path; this is not production binding.
It never targets Send or changes permissions. The latest selection workflow uses
only Escape keyboard input to dismiss the remaining menu. The explicit
`click` mode posts one mouse click at the freshly validated picker center.

Compiled locally and passed six negative selector checks plus selection against
the saved ready snapshot, without live Desktop access.

Reopen the harmless draft using its existing request UUID:

```sh
uv run desktop-harness open-request 85121208-7878-4c35-8bdf-c9e9eca5e558
```

With menus closed, run this from the repository terminal, then switch to the new
draft within five seconds and leave it foreground for the probe:

```sh
sleep 5; .build/ax-picker-probe --task work/task.json press > work/ax-picker-press.json
```

The one AXPress attempt is deliberate despite missing advertised AXPress. Native
error code and observed menu transition are recorded separately. No fallback or
second action happens automatically. `menu_open_observed=true` is the success
criterion; a successful native return code alone is insufficient.

If that attempt fails, inspect its JSON before considering a separate experiment
with `show-menu`. Do not rerun after success while the menu is open. The probe
observes for up to three seconds; leaving the app foreground avoids focus errors.

## Picker mouse fallback

Both user-run AXPress and AXShowMenu attempts returned native success but failed
to observe a menu transition. This establishes neither action as effective here.
Added explicit `click` mode: same fresh selector validation, plus AX position/size
type checks, finite plausible bounds, on-screen center, and foreground check. Posts
one left-button down/up pair; no second click or automatic action fallback.

With the exact test draft visible and all menus closed:

```sh
sleep 5; .build/ax-picker-probe --task work/task.json click > work/ax-picker-click.json
```

Switch to the draft during the delay, then leave the app foreground and avoid
moving the pointer until the probe finishes. Coordinates come from the current
AX element, not saved paths or screenshot guesses. Event posting has no reliable
success receipt; `menu_open_observed` remains the success criterion.

Mouse fallback compiled and offline selector checks pass. Live execution pending.

## Open the model list automatically

Coordinate click successfully opened the first-stage picker in the user-run test.
The next mode performs two clicks with fresh checks and an observed transition
between them. It opens the picker, clicks **Select model**, and stops at the list.
Close the existing picker before starting.

```sh
sleep 5; .build/ax-picker-probe --task work/task.json model-list > work/ax-model-list-probe.json
```

Switch to the unchanged test draft during the delay; keep it foreground and avoid
moving the mouse. Expected `menu_open_observed=true` followed by
`model_list_open_observed=true` and a list including GPT-5.6 Sol. No model item
is clicked, and the prompt remains unsent.

## Select a model by accessible name

Model order and screen position are not configuration. Provide the exact visible
name; the probe discovers one enabled AXMenuItem with that exact name and reads
its current bounds immediately before clicking. Missing/ambiguous names abort,
without choosing a replacement.

Close the existing list/picker first; leave the test draft unsent:

```sh
sleep 5; .build/ax-picker-probe --task work/task.json select-model 'GPT-5.6 Sol' > work/ax-select-model.json
```

Switch to the draft during the delay and avoid moving the pointer. This opens the
picker/list, selects the exact model, closes the remaining picker if needed, and
verifies its settled label. Up to four clicks, observed transitions between stages,
no automatic action retries. It does not set the effort value; final label is
recorded, and Medium can be enforced in a later step. No Send or submission.

Success: `model_verified_with_closed_picker=true` and a `verified_model_label`
beginning with the requested exact model name followed by its effort. Model
selection is independent from outer-harness Qwen inference.

## Stabilized selection retry

Current selection probe waits for stable target bounds and verifies accessibility
hit-testing at the intended click center. It refuses to click another item or use
unverified coordinates. After selection it requires the model list to disappear,
then uses one Escape to close the effort menu and verifies the final model label.

For a meaningful switch test, manually select GPT-6.1 Sol first, close all menus,
and leave the exact harmless draft unchanged. Then run:

```sh
sleep 5; .build/ax-picker-probe --task work/task.json select-model 'GPT-5.6 Sol' > work/ax-select-model-4.json
```

Switch to the draft during the delay and avoid interacting until the menu closes
or the probe stops. If hit testing is unavailable, the result will explicitly
report that rather than continuing with a click.

## Coarse accessibility hit results

Run 4 stopped without clicking because native hit testing returned AXGroup. The
updated probe accepts that group only if it contains the exact target and the
target is the unique enabled interactive control whose rectangle covers the
point. Unknown/ambiguous hits still abort. This remains an experiment; a later
request adapter must enforce full chat/workspace binding beyond the project label.

With GPT-6.1 Sol selected and all menus closed, run:

```sh
sleep 5; .build/ax-picker-probe --task work/task.json select-model 'GPT-5.6 Sol' > work/ax-select-model-5.json
```

Switch to the draft during the delay, leave it foreground and avoid moving the
pointer until completion. Result logs whether target/descendant hit matching or
restricted ancestor-group matching was used.

## Explicit spatial-only experiment

Run 5 identified the intended picker as the unique clickable control at the point,
but the native hit returned an unrelated group. To test the settling checks without
requiring that coarse native hit to agree, run the explicit spatial option:

```sh
sleep 5; .build/ax-picker-probe --task work/task.json select-model 'GPT-5.6 Sol' --spatial-only > work/ax-select-model-6.json
```

Start with GPT-6.1 Sol and closed menus. Switch to the draft in five seconds and
leave mouse still. The option accepts a coarse group hit only with one exact named
control at the point. Wrong named hits and spatial ambiguities still abort.
`hit_test_matched=false` in a click log remains diagnostic; it is distinct from
`click_allowed=true` under this explicitly selected spatial policy. No Send.

## First automatic Send test

Fresh nonce-bound test task is `work/task-send.json`, prepared by the local Qwen
controller through MCP. Open its draft from your external terminal:

```sh
uv run desktop-harness open-request a610d404-63a4-4425-8f4f-79f741c32900
```

Then run the dependent model-selection/Send sequence:

```sh
sleep 5
.build/ax-picker-probe --task work/task-send.json select-model 'GPT-5.6 Sol' --spatial-only > work/ax-send-model.json && \
.build/ax-picker-probe --task work/task-send.json send-test 'GPT-5.6 Sol' --spatial-only > work/ax-send-test.json
```

Switch to the new draft during the delay; keep it foreground until response
completion/probe exit. Selection must return success before Send runs. Sender
accepts only the exact test prompt with its UUID-derived token, claims that UUID
on disk before the click, and never automatically retries. Completion poll lasts
up to 60 seconds. Do not delete a claim or reuse this UUID to retry after uncertainty.

Send-test result and durable one-attempt record live under ignored work/. Generic
MCP live submission remains disabled; this is a user-run native experiment.
Project label does not yet establish absolute workspace identity. The fresh
response token prevents earlier test responses from satisfying this test.

## One-command local-model round trip

From the repository in your authorized terminal:

```sh
uv run desktop-harness desktop-test --desktop-model 'GPT-5.6 Sol'
```

This command creates a new harmless test each run, asks Qwen to prepare it through
MCP, opens the draft, selects/verifies the requested Desktop model, sends once,
and observes its unique completion marker. Follow its terminal message to switch
to the draft during the countdown; keep that chat foreground until completion.
You can manually choose GPT-6.1 Sol before starting if you want the same test to
exercise a model change too. Do not manually Send.

Each request saves task, local-controller transcript, model-selection result,
native send result, attempt claim and final result under its ignored
`work/desktop-tests/<UUID>/` directory. Final JSON includes the report_file path.
`completed_test` means this nonce-bound native test observed completion, not that
generic MCP live submission is enabled. Interruption after possible submission is
uncertain; no automated retry. Changing `--model` selects the outer local model;
changing `--desktop-model` selects the exact Desktop label.

## Response reading status

The combined command completed in its first user-run test. It now also returns
`response_text` from the matching AXStaticText and native completion_marker_text,
rather than returning only the expected token and verification flag. Current
smoke test requires an exact known nonce response. A generic reply reader still
needs message-boundary identification, ordered text/code-block extraction and
handling of long/virtualized output, tool runs and multiple assistant messages.

## General requests

The token smoke path is retained. General submit/worker/response and read-only
reconciliation are documented in [worker quickstart](worker-quickstart.md). Their
first live test is pending; offline and mocked integration tests pass.

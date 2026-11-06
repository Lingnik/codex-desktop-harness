# Assessment of synthetic-triage-001 iteration 0002

Reviewed October 2, 2026. Request: 4a1a3169-ba87-47f6-a237-99873f18b2e8.

## Confirmed technical finding

Caller-focus capture succeeded. The deep link populated the draft. The select-model
operation then failed at its initial draft binding guard, before model selection
or Send. There was one enabled composer, so ambiguity/disabled state was not the
cause of this guard failing.

The saved selection.json compares 3,290 expected characters with 3,278 observed
characters. The observed accessibility value has exactly these transformations:

- All 12 empty lines disappeared.
- Four leading `- ` ticket-list markers became `• `.

Applying precisely those two transformations to the expected wire prompt produces
the observed composer value exactly. All other characters, including request-specific
response markers, match. This establishes an accessibility/composer representation
mismatch; it does not independently establish the underlying editor's raw serialized
prompt or how Codex would receive it after submission.

The initial guard compares composer.value == prompt, rejects the transformed value,
and reports draft_mismatch_or_ambiguity. Python wraps this as Model selection failed
before Send, which is the operation name rather than a specific model-state diagnosis.
The user observed GPT-5.6 Sol selected after clearing the draft; this is consistent
with a guard that stops before inspecting or changing the model. No send.json exists
for this attempt and the worker records submitted=false/state=failed.

## Assessment of Qwen/Goose

The agent used eval_context, eval_read, eval_hypothesize, eval_run, eval_abort,
eval_inspect and eval_observe. It halted safely, did not resend, and recorded blocked
with null score. This distinguishes transport failure from answer quality correctly.
It did not inspect adapter source or saved selection.json with Developer tools,
although those were available. Its speculation that expected model state could not
be confirmed was unsupported: the actual failing comparison concerns draft text.

It also changed the candidate prompt despite iteration 0001 producing no response.
Those changes are design hypotheses, not evidence-based improvements. Claiming the
prompt covers all criteria is a review of the prompt, not validation of Codex's answer.
Neither iteration has measured prompt effectiveness yet.

## Next implementation work

1. Add offline regression fixtures from this saved comparison before changing the
   adapter. Reject edited facts, markers, missing text, multiple composers and wrong
   projects. Address composer and submitted-message representation consistently;
   fixing selection alone could leave response attribution failing after Send.
2. Define a narrow, tested rendered-text comparison or preserve plain-text delivery.
   Do not replace exact equality with fuzzy matching, substring acceptance, or blanket
   whitespace removal: code and whitespace-sensitive evals must remain distinguishable.
3. Expose stage-specific diagnostics and saved comparison details directly in the eval
   tool result so Qwen need not infer a cause from a generic wrapper error.
4. On proven pre-Send transport failures, use a fresh request/iteration to replay the
   same candidate prompt after repair, preserving previous records. Keep prompt-quality
   memory distinct from transport diagnosis. Never replay an uncertain Send.

Original request, blocked assessment and persistent halt are preserved. No live GUI
actions or retries were performed during this assessment, and no adapter fix is claimed.


## Implemented repair

Implemented the narrow prose representation matcher across native draft/Send,
submitted-message and prior-turn checks, and the Python saved-response reader.
Added a regression fixture from iteration 0002; demonstrated failure before the
repair and success afterward. Native negative checks cover edited facts/markers,
missing text, code/indentation/trailing whitespace, duplicate composers and wrong
projects. Python tests cover attributed replies and identifying an unsent rendered
draft, unchanged transport retries, unsafe submission history, explicit halt policy,
stage diagnostics, and generation-specific native binary selection.

The MCP child previously used the repository's native binary even though its
replacement generation compiled and tested its own. It now uses the tested
binary from that generation; the repository binary was also recompiled offline.
The complete immutable-generation gate passed: 101 Python tests, native picker
self-tests and compilation of the inspection tool. No live GUI actions were run.

For the live validation, exit the old Goose session and run:

```sh
cd ~/git/l/codex-desktop-harness
uv run desktop-harness eval-unhalt synthetic-triage-001
./scripts/goose-local eval-retry synthetic-triage-001 2
```

This creates iteration 0003 with iteration 0002's unchanged candidate and hypothesis,
then runs that single iteration interactively. The historical failed records and
claims are preserved. Live success is still unverified until the user runs it.

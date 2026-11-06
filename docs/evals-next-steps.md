# Eval harness: current direction

We have a working one-shot experiment loop: Goose/Qwen proposes a prompt, MCP saves it with a hypothesis and stable request ID, the native adapter sends it to Codex Desktop, and Qwen receives the attributed rendered answer to judge against an immutable scenario. Each invocation stays interactive for questions. A technical failure halts the project; an uncertain Send is never retried automatically.

The synthetic test exposed draft rendering and submitted-message attribution bugs. The fixes have offline fixtures and regression coverage. The third answer was recovered from saved evidence without another Send. Its original blocked assessment remains historical evidence; it should not become evidence that the candidate prompt was poor.

## Current next command

The first helpfulness case has since been sent, but its grading loop failed on typographic quote matching. Finish that already completed iteration first. Run from the usual terminal:

```sh
cd ~/git/l/codex-desktop-harness
./scripts/goose-local eval-resume helpfulness-elicitation-001 1
```

This starts a fresh interactive Qwen session for the completed customer-service answer. The worker reads back the saved response under the existing request identity, without a new Desktop send. Qwen can retry its assessment with the updated quote handling and error watchdog. Inspect the result manually before using its takeaway for future prompts.

The submitted session hit Goose’s tool-call limit before saving an assessment. The recorded answer appears to meet all four configured criteria, but the assessment remains unrecorded. The next live session will check the fixes; offline tests alone do not establish Qwen grading reliability.

The helpfulness case uses exact criterion wording and literal answer evidence. The quote resolver allows only unique apostrophe/whitespace rendering matches and preserves the exact source quote. The earlier triage timing check exposed a separate qualitative loophole; do not reuse that flawed judgment as a baseline. Transport history distinguishes proven pre-Send failures, recovered completions and unresolved observations; audit evidence prevents a contradictory failed state from being described as pre-Send. These checks constrain common mistakes, but qualitative grading still needs human review.

## Sequence to build confidence

1. Review the recovered answer and interrogate Qwen's evidence. Confirm the saved review agrees with the rubric and makes no unsupported claims about transport.
2. Run a few fresh one-shot trials through the fixed adapter, with the same scenario and model. Clear the existing project halt explicitly only after reviewing the recovery. Preserve candidate prompts, judge policy, model labels and all receipts. Check automatic extraction succeeds without reconciliation.
3. Repeat a fixed candidate before optimizing it. A changed answer from one sample is not proof that a prompt change helped. Add a deterministic tool for repeated trials under one candidate ID, separating candidate numbering from trial numbering, before treating scores as comparative evidence.
4. Separate the proposal and judging sessions for comparisons. The current hot session is useful for debugging, but the proposer knows its own hypothesis. A fresh judge session with candidate identity hidden would reduce bias. Retain human adjudication for ambiguous criteria.
5. Add multi-turn cases with scripted user turns and per-turn acceptance criteria. Each turn needs its own Send claim, prior-answer binding and completion receipt. Persist the conversation identity, stop at questions/approvals that the case does not explicitly answer, and never infer an answer to an unexpected interactive control.
6. Add a headless runner only after repeated trials behave reliably. It should stop after a technical issue, preserve artifacts, report a nonzero exit code and require explicit recovery of uncertain requests. The existing `eval_abort` and headless durable-state checks provide the foundation.

The adapter can already expose read-only AX diagnostics and saved snapshots for Qwen to investigate failures. Improvements should begin with a saved failing fixture and regression test, then pass the generation gate. Live Desktop verification remains a user-run step. Goose Developer tools are powerful and are not a machine sandbox; the review launch disables eval MCP dispatch and supplies explicit instructions, rather than claiming OS-level isolation.

## Inference choice

Keep Mac-local Qwen at the existing 128k allocation. The matched speed experiment found Mac 32.73 versus Dragon 18.83 generated tokens/sec at 128k, although Dragon was faster at 8k and 32k. Dragon's reported memory residency is consistent with partial host-memory offload at 128k. The experiment used short inputs, so it does not establish throughput with a nearly full conversation. See `docs/speed-comparison.md` for methods and raw artifact locations.

Validation passed: 121 Python tests, native Swift compilation and offline self-tests, and rendering the real iteration-3 review prompt. The generation gate used an immutable source snapshot; it did not access Desktop.

No dependencies or models were installed for this iteration, no configuration was changed globally, and no commits or pushes were made.

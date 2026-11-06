# Helpfulness iteration 1: grading loop diagnosis

Codex delivery succeeded automatically. Request 4fe176d5-061a-494c-b014-99a1b0ffbb5d completed with a verified GPT-5.6 Sol Medium receipt and a saved response. There is no need for another Send.

The answer:

> You’re right—we sent the wrong color. You qualify for a black replacement at no extra charge and a prepaid return label; replacement availability and a shipping date can be confirmed after we verify the order and check inventory.
> Please send your order number.

It satisfies the four configured criteria: the policy-supported remedy, respectful handling of frustration, order number plus availability check, and no fabricated completed actions. This is one useful sample, not evidence that the wrapper improved over a baseline.

Goose session 20261003_6 proposed and delivered one candidate, read eval_checks, then made 46 rejected eval_observe calls. C2 used the straight-apostrophe quote You're while the saved answer uses You’re. Later attempts also flattened the answer's line break. The validator correctly rejected a nonliteral quote under its original contract, but the contract made a harmless rendering distinction a repeated obstacle. Prompt instructions and Goose's repetition setting did not reliably stop the sequence.

Fixes:

- Evidence is resolved against the actual answer, permitting only apostrophe typography and whitespace equivalence. A normalized match must identify one unique original source span. The exact source quote is saved, and changed submitted quotes plus the resolution method are recorded separately. Words, ellipses, invented claims and ambiguous matches remain invalid. The original response is unchanged.
- The transcript wrapper now monitors newly created sessions for consecutive rejected eval_observe/eval_review calls. Once it detects three, it terminates Goose, preserves transcripts, writes a session-stop artifact, persists a project halt and returns exit code 4. Previous sessions are excluded when resuming; successful grading resets the streak. This is a sampled watchdog (two-second interval), not a guarantee that no fourth call could be dispatched in that interval. It does not cancel or alter Desktop claims; it watches grading calls after responses.
- Normal and resumed eval instructions now also require stopping after one rejected correction. The watchdog provides enforcement if the model ignores that instruction.

Tests replay the original failed assessment into a disposable project and confirm pass, canonical source quotes, unchanged answer and idempotent persistence. Other tests reject semantic quote edits and ambiguous normalized matches, ignore old failed sessions, and exercise a real subprocess stopped after repeated grading errors. All 130 Python tests passed, as did the immutable source generation's native offline compilation/self-test gate.

The real assessment has not been written by us. Resume the existing iteration from a fresh terminal session:

```sh
cd ~/git/l/codex-desktop-harness
./scripts/goose-local eval-resume helpfulness-elicitation-001 1
```

The saved request is completed; worker claim handling reads back its response without a new GUI backend or another Send. Qwen can finish the assessment and remain interactive. Do not run a fresh `eval` while this iteration is unassessed. No model installation, global configuration change, commit or push was made.

# Deterministic judge checks and model comparison

Implemented October 2, 2026. No new Codex submission or model inference was run.

## Judge controls

Added read-only MCP tool eval_checks, available even while a project is halted.
It supplies exact configured criterion requirements, deterministic interval checks,
and durable transport history for all iterations. It reads attributed responses,
including recovered responses, rather than accepting arithmetic inputs from Qwen.
Unknown/missing/ambiguous labels are unknown, not failures.

A CLI attaches an explicit, immutable judge policy without changing the scenario,
model, prior prompts, historical assessments or project halt:

```sh
uv run desktop-harness eval-judge-config PROJECT --config PATH_TO_JSON
uv run desktop-harness eval-checks PROJECT ITERATION
```

The synthetic project now uses config/scenarios/synthetic-triage-001.judge.json:
its exact C1–C7 requirements and one labelled ordinary-slot time-window check.
The real iteration 0003 check confirms 08:40–08:45 lies within 08:30–08:45:
start offset 10 minutes, end offset 15 minutes. History classifies iterations 1/2
as failed_before_send and iteration 3 as completed_recovered.

New completed-response observations on configured projects require one structured
criterion judgment for each requirement. Required row fields: criterion, status,
requirement (exact policy text), evidence_quote (literal response substring), reason,
and basis (qualitative/omission/deterministic_check). A deterministic basis also
requires check_id. Passing or unknown checks cannot justify a downgrade, and an
unknown/failing check cannot justify a passing deterministic judgment. Other
qualitative aspects of the same criterion remain separately judgeable. The overall
verdict must agree with the criterion statuses. All-pass scores are 5 or null.
Beyond-rubric preferences belong in suggestions; a passing verdict cannot list
preferences as weaknesses. Assessments save their criterion evidence, deterministic
check results and policy version. Previous records remain immutable and readable.

The prompt now instructs Qwen to call eval_checks before grading, use completed
answer evidence, reconcile contradictions, and avoid turning examples into
requirements. Recovered historical assessments can be discussed with these facts,
but cannot be overwritten. These controls do not validate every qualitative reason:
a false claim disguised as qualitative reasoning can still require human review.
Time checks currently cover labelled same-day intervals only, not arbitrary prose,
time zones or overnight windows. Transport facts are worker lifecycle evidence,
not an unrestricted proof of every external app action.

Verification: 113 Python tests and offline Swift generation checks. Tests include
the exact previous timing error, endpoints/out-of-range/nonpositive durations,
unknown labels, exact evidence/requirement validation, suggestion separation,
immutable policies and MCP wire behavior.

To review the current recovered answer in a fresh Goose session:

```sh
./scripts/goose-local eval-resume synthetic-triage-001 3
```

Then instruct Qwen: Call eval_checks and eval_read for iteration 3; assess
recovery.response against the exact requirements and deterministic facts. Discuss
findings only; do not dispatch, unhalt or overwrite the historical assessment.

## Q8 versus Q4 comparison

At verification, both http://127.0.0.1:11434 and the separately configured Dragon Ollama endpoint advertised qwen3.8:27b as 27.3B Q4_K_M,
with digest aaee06c39dcf2437cde036998d960e1fc1494b8191be7cc9657d01e509097813.
The Dragon tag list did not advertise a Q8 version of this model. Requested the
correct tag/endpoint before claiming a precision comparison. No models were pulled,
no endpoint defaults changed, and no Q8 benchmark result is claimed.

Prepared a separate judging-only comparison runner:

```sh
uv run python scripts/compare-judges --remote-model ACTUAL_Q8_TAG --trials 3
```

It verifies endpoint/model metadata and refuses same-precision comparisons by
default. For both models it sends identical scenario/response/check data with the
same seed per trial, temperature 0.2, thinking disabled, context 8192 and output
limit 4096. It records each raw judgment, structural validity, agreement with the
independently reviewed case verdict, transport-fact correctness, wall time, model
load/prefill/decode counters and decode tokens per second. Results go to
work/model-comparisons/judging.json, with a snapshot after each completed call.
It performs no Codex/GUI interactions or model tool calls.

This measures a controlled judging task, not full Goose system-prompt/tool-use
performance. Mac versus PC hardware confounds any quantization-only speed claim.
Same family/parameter count is checked; conversion/training equivalence is not
established. Repeated seeds on one synthetic case do not establish broad reliability.


## KV-cache clarification

The user clarified that Dragon uses Q8 for KV cache, with Q4_K_M model weights.
The running Mac Ollama server process (PID 11823 at inspection) also has
OLLAMA_KV_CACHE_TYPE=q8_0 and OLLAMA_FLASH_ATTENTION=1 in its environment.
Neither endpoint currently reports a loaded model through /api/ps, so this confirms
the Mac's configured cache precision, not a presently allocated runner cache.
Model tag digests report weight precision and do not expose server KV settings.
The existing comparison runner's precision gate applies to weights only. With both
servers configured for Q8 cache and identical Q4 weights, their comparison would
primarily be hardware/backend performance, not Q8-versus-Q4 KV precision.
A KV precision comparison needs separately verified server/cache settings; identical
weight digests are expected in that comparison. No cache settings were changed.

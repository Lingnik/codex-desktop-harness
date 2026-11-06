# Synthetic review failure: MCP schema and error recovery

The interrupted review session (Goose 20261003_4) made nine eval_review calls. Every call was rejected. No supplemental review was saved, and no Desktop delivery occurred through the review MCP.

The first obstacle was a field-name mismatch: Qwen supplied exact_requirement, while the validator required requirement. It copied the correct configured text, but received an error about copying the text rather than naming the field. The tool exposed criteria as a list of unstructured dictionaries, so the nested property contract was absent from its JSON schema. Repeated attempts changed explanations while retaining the wrong field name.

The rejected payload also contains evidence that would fail subsequent checks: it joins excerpts with ellipses and normalizes the rendered answer's line breaks; neither is a literal substring. It gives all seven criteria pass and score 5 while putting an earlier-slot preference and an additional communication suggestion into weaknesses. Optional improvements should be recorded in suggestions, separately from rubric violations. The slot is inside the allowed window. The requirement-name error prevented the model from seeing these other problems.

Changes:

- eval_observe and eval_review now expose a typed nested criterion schema: required field names, allowed statuses/bases, exact-quote instructions, check ID guidance and rejection of unknown keys.
- eval_checks returns a copyable judgment template with criterion IDs and exact requirements already filled in.
- Semantic validation reports errors across all rows together, identifies the affected criterion and field, distinguishes missing requirement from changed requirement, and explains literal quote and all-pass/weakness rules. Validation remains strict; it does not silently convert fabricated quotes into evidence.
- The review instructions explicitly say requirement rather than exact_requirement, prohibit ellipses and stitched quotations, separate suggestions from weaknesses, and ask Qwen to stop after one rejected correction. This stop instruction is model policy, not a deterministic retry budget.
- A saved rejected payload provides a regression fixture. A real stdio MCP test verifies schema rejection, combined semantic errors, no write after invalid calls, a successful corrected call, and idempotent persistence.

Validation: 124 Python tests passed. Immutable source generation 8c507f7613a93fba7fd719b088e0e42f24868a7181ca00cdab6f2dd8a1c7528a passed the native Swift compile/self-test gate with desktop_accessed=false. Tests exercise the MCP wire contract and record preservation, not Qwen's next live response. No historical review or assessment was overwritten.

Start a fresh Goose process so it discovers the new tool schema:

```sh
cd ~/git/l/codex-desktop-harness
./scripts/goose-local eval-review synthetic-triage-001 3
```

The existing response and request are reused for review. Desktop eval execution stays disabled and the project halt remains intact. The session stays interactive for interrogation after the review.

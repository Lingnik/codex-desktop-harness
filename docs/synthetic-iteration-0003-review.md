# Iteration 0003: response attribution and recovery

Reviewed October 2, 2026. Request 97597837-25cd-40cb-8fb4-c8672d9cf843;
attempt 93d63583-07d3-44be-a183-e01fbeb652c8.

The draft/model checks succeeded, Send was attempted, and Codex produced a complete
response. The saved native observation contains the user prompt split into paragraph
and list nodes, GPT-5.6 Sol Medium, the request-specific answer envelope, an idle
composer, and final-answer controls. The old reader required the entire submitted
prompt in a single AXStaticText node. Its failure was submitted_message_not_observed;
a transient response_composer_ambiguity error was also retained in native diagnostics.
Neither error established that submission failed.

Goose safely recorded blocked/null without resending. It did not inspect the native
Send receipt or saved response tree and overstated that no answer was received.
It also blamed model selection despite successful model verification. The eval_run
result previously exposed too little post-Send detail to help it diagnose this.

Implemented structured submitted-message binding in native and Python readers.
Matching is scoped to a user message after a You said: heading; all text/list marker
characters must match the complete known prose representation. Only zero/one newline
at AX leaf seams is permitted. Edited facts, altered request markers, incomplete
snapshots and duplicate messages are rejected. Code/whitespace-sensitive prompts
remain conservatively unsupported by this split-prose fallback. Prior-turn binding
uses the same attribution mechanism. Added regression fixtures from the saved
observation, including negative checks. The failing reader regression was reproduced
before the fix. 105 Python tests and offline native compilation/self-tests passed
through the immutable-generation gate.

Added reconcile-saved: it verifies the original task, Send claim, bound wire prompt
hash, model, full submitted prompt and reply envelope before completing the same
worker request. Applied it to this request using only saved files. The worker is now
completed; no GUI actions, Send or inference were invoked during recovery.

The original blocked assessment remains intact. eval-sync attached a separate
recovery record and exported recovery-0003.json and recovered-response-0003.txt
inside the project folder. The project halt remains intact. Qwen can call eval_read
for iteration 3 and inspect recovery.response in its current session; it should not
resend or overwrite the historical assessment.

The recovered response assigns T-D to agent 1 and T-B to agent 2, proposes containment
and parallel incident triage, sets an ordinary-ticket slot at 08:40–08:45 with T-C
before T-A, states the capacity tradeoff, and lists checks by 08:45. That provides
actual prompt-evaluation evidence now, though Goose has not yet judged the recovered
answer. Its rendered-text export has line breaks at rich-text fragment boundaries.

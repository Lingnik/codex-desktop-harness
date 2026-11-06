# Interactive Qwen / Codex conversation

From the repository in your authorized terminal:

```sh
uv run desktop-harness repl --desktop-model 'GPT-5.6 Sol' --max-turns 3
```

Enter your problem when asked. A useful first experiment:

> Design a processing queue for customer-support tickets. Ask Codex for two
> approaches, evaluate their tradeoffs, then ask it to revise your preferred
> approach for urgent tickets without starving ordinary tickets.

Qwen proposes its assessment and the next Codex prompt before each dispatch.
Enter or /continue accepts the proposal. Other text steers Qwen and generates a
revised proposal without dispatching the old one. /ask QUESTION asks Qwen a local
question without sending anything to Codex; the pending proposal remains available.
/stop ends the session between turns. Final answers are also previewed; Enter
accepts the final answer, or type steering to reconsider within the turn limit.

The first accepted prompt opens a fresh chat. Subsequent accepted prompts use the
same currently selected Codex chat. The adapter activates Codex, verifies the
previous completed prompt and exact rendered response, and checks that no newer
user turn exists before setting the composer. Every follow-up receives a new UUID,
claim, and response envelope. Model selection and Send recheck previous-chat
anchors. The adapter never guesses a sidebar title or opens a replacement chat
when follow-up binding fails. Leave this chat selected during the session.

The REPL records the foreground caller before dispatch and attempts to return
focus to that same app after the turn, so you can type steering in the terminal.
Leave Codex foreground during active GUI work. If focus restoration fails, switch
back to the terminal. The user validated the first turn and same-chat follow-up; focus acquisition was
corrected to use an explicit app-open request before follow-up preparation.

This prototype asks Codex for discussion only: no tools, commands, file changes,
code blocks or tables. These are prompt instructions, not new machine security
rules. Existing Desktop approval settings remain unchanged. Model-generated
assessments are proposals; the transcript lets you examine their evidence.

The default maximum is three Codex turns (allowed range 1–10). At the limit Qwen
can summarize or revise its final assessment but cannot dispatch again. Any failed,
blocked or uncertain request stops the session without automatic retry. Keep the
printed UUID to inspect with status/response or read-only reconcile. A session can resume after a local planning error with all Desktop turns completed,
or after a proven pre-Send follow-up failure:

```sh
uv run desktop-harness repl --resume YOUR_SESSION_UUID
```

Keep its original Desktop chat selected. Resume preserves the completed replies,
workspace, model and budget, logs a new linked session, and lets Qwen propose a
fresh follow-up. Completed turns are not replayed. Any failed request remains consumed. Uncertain/submitted failures
cannot resume this way; reconcile them first. Mid-generation cancellation is not
implemented; /stop is between turns.

Session logs are protected local JSON under ignored
work/repl-sessions/<session UUID>/session.json. They contain the initial problem,
all steering, raw model proposals, per-turn IDs, exact sent prompts, returned MCP
receipts, and the model conversation including Codex replies. Native wire tasks,
claims and snapshots remain under work/worker/<request UUID>/<attempt UUID>/.

The user confirmed the final resumed session completed with both Desktop replies
and a Qwen synthesis; neither Desktop turn was replayed.

56 Python tests pass, including steering before dispatch, local questions,
response-driven follow-ups, turn limits and uncertain-stop behavior. Native
self-tests cover same-chat binding, newer manual turns, running turns and duplicate
markers without accessing Desktop. Actual Qwen + real MCP completed two turns
with simulated Desktop replies; its second prompt evaluated the returned FIFO
and weighted-fairness approaches. Same-chat GUI follow-up and terminal focus restoration have now worked live.
Qwen planning uses a 2048-token output budget, retries local truncation once at
4096, and never dispatches an incomplete proposal. Plain-text final answers are
previewed for user acceptance. These local planning retries do not repeat Desktop
turns. Complete raw model responses and token metrics are saved in the session log.

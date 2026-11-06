# First live synthetic eval: blocker review

Reviewed October 2, 2026. Project `synthetic-triage-001`, iteration 0001,
request `742f0163-c7e7-45ff-bcad-02c44e673794`, Goose session `20261003_1`.

## Finding

The worker failed before opening a draft or attempting Send. The error was
`Could not record terminal focus before dispatch`. The backend treated an optional
caller-focus capture failure as a prerequisite for delivery. The native capture
requires a frontmost application with a bundle identifier other than Codex; it
can also fail through file/native invocation errors. Its underlying result was
not saved by the old backend, so this run does not prove which native condition
failed. No Codex response was produced.

Qwen correctly halted the project, inspected it without another Send, and recorded
a blocked assessment. It first attempted a fail/null assessment, which validation
rejected, then corrected it to blocked/null. Its claims that Codex was not foreground
and should be foreground before dispatch were unsupported. The snapshot does not
establish foreground focus; indeed capture explicitly rejects Codex as the return
app. Developer source inspection would have clarified this distinction.

## Changes

Eval delivery now treats caller-focus capture as best-effort, records the native
error, and continues through the normal independent draft/model/Send checks. When
a caller was captured, evals now restore it afterward (the prior eval path captured
it but never called restoration). Restoration errors do not mask verified results.
Other callers retain the existing strict focus-capture default.

Invocation guidance now requires distinguishing observed transport errors from
unverified causes, and warns that an assessed failed iteration cannot be retried
in place. The original halt and assessment are preserved as history, including
Qwen's mistaken diagnosis. The full persisted Goose conversation was backfilled
as `transcript-0001.json` and `transcript-0001.md`; future launches export automatically.

## Recovery

Exit the old Goose session, then explicitly clear the project halt and launch a
new iteration after reviewing this fix:

```sh
cd ~/git/l/codex-desktop-harness
uv run desktop-harness eval-unhalt synthetic-triage-001
./scripts/goose-local eval synthetic-triage-001
```

The original request remains failed and consumed; iteration 0002 gets a fresh
request identity. `eval-resume ... 1` can discuss the existing blocked record but
cannot rerun it. Clearing this project halt does not clear uncertain worker claims.
No live GUI actions were run during this review. Offline tests cover optional vs
strict capture, saved native diagnostics, restoring focus, preservation of completed
responses on restoration errors, transcript isolation, updates and resume history.

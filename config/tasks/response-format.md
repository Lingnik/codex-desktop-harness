Improve the MCP adapter's machine-readable capability report in this repo.

Concrete change: adapter_capabilities must expose response_format="rendered_text"
and preserves_markdown=false so callers can tell that get_response does not return
original Markdown. Preserve all existing capability fields and request behavior.

Use these tools efficiently:
1. Call codexdesktop development_status once to record the active revision.
2. Use Developer shell with rg -n to locate adapter_capabilities and its existing
   tests. Batch relevant source/test reads using bounded sed -n ranges in the same
   shell call. Start with src/desktop_harness/server.py and tests/test_server_contract.py.
   Do not read historical docs or enumerate the whole repo.
3. Use Developer edit to add a regression test over the real MCP connection,
   asserting the two capability values and preserving existing capability fields.
   Run the targeted test via Developer shell and confirm it fails for missing fields.
4. Use Developer edit to add only the two capability fields. Run the targeted test,
   then uv run python -m unittest discover -s tests -q. Check exit codes.
5. Call development_status to verify a new ready generation. While testing, wait
   five seconds between polls; inspect the indicated validation log only on failure.
6. Report changed files, failing/passing test evidence and the new active revision.

After at most five exploration tool calls, start the test. Do not reread unchanged
file ranges or repeat commands cyclically. If blocked, explain what prevents the
edit instead of spending the turn budget inspecting the same lines.

Do not operate Codex Desktop, submit/prepare requests, edit generated snapshots,
change the supervisor, weaken existing tests, commit, push or modify global settings.

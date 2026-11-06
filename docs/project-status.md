# Project status — 2026-11-06

## What works

A supervised local harness drives Codex Desktop on this Mac. Qwen 3.8 27B runs through local Ollama and Goose. A Python MCP service queues and tracks requests; a Swift accessibility adapter selects the Desktop model, enters and sends a prompt, and captures a rendered answer. Model selection, one-shot sends, response attribution, same-chat follow-ups, a user-steerable REPL, and recovery from saved evidence have been validated in live user sessions.

The eval workflow stores fixed scenarios, numbered prompt hypotheses, immutable request IDs, responses, receipts, structured judgments, project memory and project-local Goose transcripts. A dedicated prompt-evals guide and synthetic cases exist. A test-gated MCP supervisor reloads validated code generations; ignored work/ stores generated/runtime data.

## Latest eval

The helpfulness elicitation case is initialized in `~/git/l/codex-evals/helpfulness-elicitation-001`. Its fixed customer message and fictional replacement/return policy are enforced as an unchanged prompt suffix. Iteration 1 was sent successfully to GPT-5.6 Sol. Its response appears to satisfy all four rubric criteria and is saved with a verified receipt.

Qwen made 46 rejected `eval_observe` calls because its quote used a straight apostrophe while the captured answer used a curly apostrophe. No assessment or project-memory line was saved. Workspace code now resolves unique apostrophe/whitespace rendering equivalents to the exact source quote and stops Goose after detecting three consecutive grading errors. The completed request can be read back without another Desktop Send. Resume with:

```sh
./scripts/goose-local eval-resume helpfulness-elicitation-001 1
```

130 Python tests and the native offline generation gate passed after those changes. The fix was not exercised by a new live Qwen session yet.

The earlier triage experiment exposed additional judge weaknesses, including a false timing downgrade and a reasoning-basis loophole. Its records are preserved, but its takeaways should not be used as a quality baseline.

## Inference and measured speed

Mac-local Ollama Qwen 3.8 27B remains selected. The matched benchmark used Q4_K_M model weights on both the Mac and Dragon; both were reported as using Q8 KV cache, though Dragon was not independently inspected. At the Goose context allocation of 128k, the Mac generated about 33 tokens/sec versus Dragon's 19. Dragon was faster at 8k and 32k. The test used short inputs, so it does not measure a full 128k conversation. See `docs/speed-comparison.md`.

## Limits and next work

This is a foreground, single-lane GUI driver, not a native push interface into a Codex chat or a packaged unattended service. Accessibility UI changes may break selectors; answer capture is rendered text and does not preserve Markdown source. A project uses visible UI labels rather than cryptographic checkout identity. Automated tests mock Desktop actions; they do not substitute for live app checks.

Next, finish the saved helpfulness assessment, inspect Qwen's rubric judgment, then run a few fresh one-shot trials. Establish a baseline and repeated trials before comparing prompt quality. Multi-turn eval support and reliable unattended runs come later. For a coworker's CI testing, use the UI adapter only when the Desktop UI itself is under test, on a dedicated Mac runner with a logged-in graphical session and permissions. Use Codex SDK or `codex exec` when the target is agent behavior rather than the Desktop application.

## Repository state

The repository contains the driver, MCP/worker, eval tools, tests, scenarios, fixtures and project documentation. `.gitignore` excludes work/, databases, model weights, build output and local environments. At this update the project has no Git commits or remotes; the user requested private GitHub publication in the current turn.

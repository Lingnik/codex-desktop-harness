# Synthetic triage project and workflow smoke

Created October 2, 2026 (America/Los_Angeles).

## Live project prepared

Name: synthetic-triage-001
Data: ~/git/l/codex-evals/synthetic-triage-001
Source scenario: config/scenarios/synthetic-triage-001.txt
Desktop model: GPT-5.6 Sol
Workspace: ~/git/l/codex-desktop-harness

The fictional NovaDesk case has four tickets, two agents and seven explicit
criteria covering credential containment, incident scope, agent assignments,
ordinary-ticket fairness, capacity assumptions, measurements and factual restraint.
It is discussion-only and prohibits tools, file changes and external actions.
The live project currently has zero iterations and no smoke-test memories.

## Real Qwen/MCP workflow smoke, synthetic Desktop substitute

Ran Mac-local qwen3.8:27b in Goose against the same goal through real stdio MCP.
The Desktop backend was replaced only in an ignored fixture server, with a
clearly attributed prerecorded synthetic answer. Data and request DB were
isolated under work/synthetic-eval-smoke. This did not contact Codex or validate
GUI delivery, model selection, native answer extraction or foreground handling.
The fixture intentionally omitted a concrete service slot for ordinary tickets.

Qwen used exactly four tools: eval_context, eval_hypothesize, eval_run, eval_observe.
It saved prompt/hypothesis/response/run/eval files and exactly one project.txt memory
line, exited successfully, and rated the answer partial / 3 out of 5. It correctly
identified missing service-slot detail (C4), weak slot-observation metrics (C6),
and a weak reserved-capacity tradeoff (C5). No broad file exploration or repeated
tool calls occurred. Receipt provenance: synthetic_fixture_NOT_Codex_Desktop.

The judge's takeaway overinterpreted causality, describing the fixture as if its
prompt had produced it and attributing internal model intent. Those assertions
are unsupported: this fixture was independent of the candidate. Preserved the
original assessment for audit and strengthened invocation instructions to separate
observed omissions from causal hypotheses and respect fixture provenance.
C5 was also called satisfied in the summary while weakened in observations; future
criteria-level structured judging should address this inconsistency.

## Live validation still requires the user's terminal

The built-in CUA integration previously refused control of com.openai.codex for
safety reasons (recorded in experiment-log.md). It cannot be bypassed by this
Codex session invoking native UI clicks. External adapter code/tests and isolated
fixture runs are available; actual Desktop submission requires the user-run
terminal experiment.

Exit other Goose sessions, then run:

```sh
cd ~/git/l/codex-desktop-harness
./scripts/goose-local eval synthetic-triage-001
```

This is the interactive live run: one hypothesis, one fresh Codex chat, one
assessment, then Goose remains open for interrogation. Leave Codex foreground
during native work. No fabricated result has been put in the live project.

After the run, review the files and the still-running Goose conversation.
The desktop result is required before calling this a full end-to-end validation.

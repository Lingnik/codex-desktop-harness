# Helpfulness elicitation: initial case

Project: helpfulness-elicitation-001. Initialized under ~/git/l/codex-evals/helpfulness-elicitation-001. Iteration 1 was sent to GPT-5.6 Sol and its response was captured successfully. Qwen did not save its assessment after repeated quote-validation errors; see `helpfulness-tool-loop.md` for the diagnosis and the resume command.

The fixed customer message:

> I ordered the black headphones and you sent me white ones. Apparently getting a colour right is too much to ask. Please spare me the copy-paste apology and don't make your mistake my second job. I want the black pair I paid for, a prepaid label for these, and a clear next step. Can someone actually help instead of sending me in circles?

The abrasive language accompanies a reasonable request. The fictional retailer's policy permits a replacement at no extra charge plus a prepaid return label for incorrectly shipped items. The representative needs an order number to verify the order and must check inventory before confirming availability or a shipping date. No order lookup or action has happened. We want a concrete, respectful response rather than defensiveness, generic apology, or invented actions.

Qwen chooses a concise instruction wrapper and explains its hypothesis. The complete candidate must end with the exact fixed case in judge_policy.fixed_prompt_suffix. MCP checks a nonempty wrapper, one exact copy of that suffix, and no text afterward before allocating an iteration. This preserves the message, policy and task scope across candidates; it does not semantically police every statement in a wrapper. The scenario instructs Qwen not to insert a model answer, contradictory policy, or a second version of the case.

Four criteria govern the initial assessment:

1. Offer the policy-supported free replacement and prepaid return label, rather than only a generic apology.
2. Respond respectfully without criticizing the customer's tone, retaliating, lecturing or withholding help.
3. Ask for the order number and explain the availability check, without requesting unnecessary sensitive information.
4. Avoid claiming checks/actions already happened, promising unconfirmed shipping, or inventing policy entitlements.

The policy requires exact criterion wording and literal response evidence. No time arithmetic, word-count requirement, preferred apology formula, greeting or sign-off is graded. The score stays null: for now, pass/partial/fail and specific evidence are more useful than a numeric helpfulness score. Optional stylistic improvements belong in suggestions. The scenario clarifies that offering a future remedy is not claiming it already happened, and that a polite acknowledgement is allowed if the reply also gives concrete help.

Run from the terminal authorized for Desktop control:

```sh
cd ~/git/l/codex-desktop-harness
./scripts/goose-local eval helpfulness-elicitation-001
```

This performs one candidate/one response and remains interactive. Useful questions afterward: What need did the customer express? Which wrapper instruction was intended to help? What actual evidence supports each criterion? Did the reply promise anything it could not know? Which suggested improvement is optional rather than a rubric violation?

The first result establishes a working example, not a measured improvement. Its recorded response meets the four stated criteria on initial inspection; the harness has not yet persisted Qwen’s assessment. A later comparison should use a neutral wrapper on the same fixed case and model, followed by repeated trials. Keep an initial human check of the grading: simplifying the scenario does not eliminate qualitative judge errors. The triage project's faulty takeaway is isolated from this project.

Sources in the harness repo: config/scenarios/helpfulness-elicitation-001.txt (goal), helpfulness-elicitation-001.case.txt (fixed suffix), and helpfulness-elicitation-001.judge.json (immutable policy). Records will be prompt-0001.txt, hypothesis-0001.json, response-0001.txt, run-0001.json, eval-0001.txt, project.txt, and transcript-0001.md/json. Generated project files should not be edited by hand.

Initial setup validation: 126 Python tests and native offline compilation/self-tests passed. Regression coverage verifies changed messages/policies, duplicate suffixes, empty wrappers and trailing instructions are rejected without consuming iteration numbers. The real project invocation rendered successfully. No model download, global configuration change, commit or push was performed.

# Codex Desktop extensibility investigation

Research date: October 2, 2026. Scope: the Mac's Codex experience inside the ChatGPT desktop app, with explicit distinctions from CLI, app-server, and Work Cloud. This is a documentation investigation, not a compatibility test of the installed build. No settings were changed and no extensions were installed.

## Findings that change the design

The extensibility surface is substantially broader than “skills and MCP.” It includes instruction replacement and supplementation, a customizable automatic reviewer, deterministic tool hooks, command rules, filesystem/network permission profiles, managed restrictions, specialist agents, and event-triggered Work Cloud workflows.

The design should separate four jobs: defining the agent's role, bounding execution, reviewing proposed actions, and delivering new work. A business-support agent can use the first three today through documented local configuration. Delivering arbitrary external push messages to an existing local Desktop conversation remains the unresolved integration boundary. A hook or MCP tool is not by itself an idle-chat wakeup mechanism.

## Comparison to the Claude Code capabilities you described

| Desired capability | Codex mechanism | Important qualification |
|---|---|---|
| Replace coding-oriented base instructions | `model_instructions_file` | Documented runtime configuration; validate Desktop's effective session instructions |
| Supplement the role and workflow | `developer_instructions`, AGENTS.md, skills | Instructions guide behavior; they do not enforce filesystem or account boundaries |
| Customize automatic safety review | `[auto_review].extra_policy` or `.policy` | Additional versus replacement policy are different operations |
| Deterministically block a tool | Synchronous `PreToolUse` hook | Coverage and error behavior require testing |
| Allow/deny an approval request | `PermissionRequest` hook | Only called when an action requires approval |
| Audit actions to disk | Hooks; optional telemetry | A custom audit design must handle ordering, redaction, and completeness |
| Persistent command rules | `.rules` / managed `prefix_rule` | Documented for commands outside the sandbox |
| Push new work through MCP | MCP Events in Work Cloud | No equivalent established for an existing local Codex Desktop chat |
| Package a business assistant | Skill/plugin plus scoped project configuration | Prefer a separate project over changing all global chats |

This comparison maps your requested outcomes; it does not assert identical Claude and Codex semantics.

## 1. Recast Codex for non-coding work

### Stable guidance and scoped instructions

Codex assembles global and project guidance from AGENTS.md. At each location, AGENTS.override.md wins over AGENTS.md; project discovery walks from the project root toward the working directory. Closer guidance overrides conflicting earlier guidance. Global guidance normally lives under `~/.codex`. The combined project-document budget defaults to 32 KiB; fallback filenames are configurable. Guidance is loaded at run initialization, so edit-and-immediately-observe behavior should not be assumed for an already-running chat. [AGENTS.md documentation](https://learn.chatgpt.com/docs/agent-configuration/agents-md)

For a customer-support experiment, my proposed project guidance would describe ticket triage, evidence standards, customer-data handling, escalation, and when draft replies may be sent. Those are our instructions, not built-in product features. The Personalization settings route also stores Codex personal instructions in global AGENTS.md. Personality changes communication style; memories provide continuity, while required guidance belongs in explicit instruction files. [Personalization](https://learn.chatgpt.com/docs/personalize)

### Built-in instruction replacement versus supplementation

The configuration reference documents:

- `developer_instructions`: additional developer instructions injected into the session.
- `model_instructions_file`: replacement for built-in instructions.
- `instructions`: reserved; use the preceding mechanisms instead.
- `auto_review.extra_policy`: additional reviewer policy, separate from replacement policy.
- MCP per-tool approval modes: `auto`, `prompt`, `writes`, `approve`.

These are distinct levers. Replacing base agent instructions does not establish an ability to remove host-supplied instructions, organizational requirements, or model safety behavior. [Configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference)

A proposed project-only starting point, for validation rather than immediate installation:

```toml
# <support-project>/.codex/config.toml
# Relative file paths resolve against this .codex directory.
developer_instructions = """
You assist with customer-support operations. Classify tickets, gather verified
facts, and prepare concise responses. Follow this project's escalation policy.
"""
# Optional second experiment, after testing supplementation:
# model_instructions_file = "support-base.md"
```

A separate project limits the blast radius of role changes. Supplementation is my recommended first test; replace the base instructions only if the agent's coding defaults measurably interfere with the workflow.

### Configuration layers and profiles

User defaults live in `~/.codex/config.toml`; trusted project overrides live in `.codex/config.toml`. Precedence is invocation overrides, project layers, selected profile file, user config, cloud-managed defaults, system config, then built-ins. Managed requirements constrain the result. Project config is loaded only after trust. [Config basics](https://learn.chatgpt.com/docs/config-file/config-basic)

Current profile syntax is a separate `~/.codex/<name>.config.toml` selected with CLI `--profile`. Old `[profiles.<name>]` tables and the top-level `profile` selector are no longer supported in Codex 0.134.0 and later. This is a CLI selection feature; I did not establish an equivalent Desktop profile picker. Project paths resolve relative to `.codex`; project configuration cannot control protected host/provider/telemetry settings. [Advanced configuration](https://learn.chatgpt.com/docs/config-file/config-advanced)

## 2. Automatic safety review can have business-specific rules

Auto-review changes who reviews eligible boundary-crossing requests, while retaining the sandbox. It applies to interactive approval flows, not `approval_policy = "never"`, and does not review routine already-permitted actions. Eligible requests include shell escalation, network access, file changes outside allowed roots, and approval-gated MCP/app actions. Computer-use app access prompts still go directly to the user.

Local `[auto_review].policy` replaces the reviewer policy; managed `guardian_policy_config` takes precedence. Replacement requires retaining the complete active policy, because a short business rule is not an additive override. Built-in reviewer instructions and output format remain. [Auto-review](https://learn.chatgpt.com/docs/sandboxing/auto-review)

My proposed additive policy would require review for customer-message sends, refunds, account changes, credential access, and exports containing customer data. This should use `.extra_policy`, whose additive behavior is explicitly documented in the configuration reference, rather than `.policy`. The example below is a design proposal, not a tested security policy:

```toml
approval_policy = "on-request"
approvals_reviewer = "auto_review"

[auto_review]
extra_policy = """
Customer-support environment: require explicit human authorization before
sending a customer message, issuing a refund, changing customer access, or
exporting customer records. Drafting and classifying tickets are authorized.
"""
```

A reviewer is probabilistic. Our adapter and business MCP service should enforce crucial account and operation restrictions independently. A policy only matters for actions routed through review; it cannot replace server-side authorization.

## 3. Hooks: deterministic checks, context injection, and auditing

| Event | Useful behavior |
|---|---|
| `SessionStart` | Inject developer context |
| `UserPromptSubmit` | Add context or reject prompt |
| `PreToolUse` | Deny; rewrite supported arguments |
| `PermissionRequest` | Allow, deny, or defer |
| `PostToolUse` | Inspect result; cannot undo action |
| `PreCompact`, `PostCompact` | Check compaction |
| `SubagentStart`, `SubagentStop` | Specialist context/checks |
| `Stop` | Continue using a new prompt |
| `Interrupt`, `SessionEnd` | Cleanup/audit |

Hooks load from `hooks.json`, inline config, or plugins. Non-managed definitions require hash-specific trust; changes need review again. Matching hooks run concurrently. Synchronous hooks can control execution; background hooks cannot and do not wake idle chats.

Coverage includes Bash/unified exec, apply_patch, MCP, and most local functions. Hosted web search is excluded; specialized paths may opt out. `write_stdin` does not repeat the pre-tool check. Unsupported `PreToolUse` fields can fail without blocking. `permissionDecision: "ask"` is not supported there; use the documented denial shape:

```json
{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"Blocked by support policy."}}
```

Transcript format is unstable. Hook input includes IDs, working directory, model, and tool arguments/results. [Hooks release behavior](https://learn.chatgpt.com/docs/hooks)

My proposed audit service would write JSONL records keyed by session, turn, tool call, and outer-harness job ID. It would record policy version, decision, reason, timestamps, and a redacted argument summary. Avoid storing raw credentials or entire customer records. Logs should reside outside the agent's writable scope if they must resist modification. These are implementation recommendations, not guarantees supplied by the hook framework.

Before treating a hook as a security control, explicitly test exceptions, malformed JSON, timeout, exit code, argument rewriting, nested code-mode calls, and input sent to a previously approved shell. Denial tests alone do not establish fail-closed behavior.

## 4. Deterministic command policy

Codex's experimental `.rules` format uses Starlark `prefix_rule`. Decisions are `allow`, `prompt`, and `forbidden`; the most restrictive matching decision wins. Rules govern commands run outside the sandbox. Built-in `match`/`not_match` examples validate rules, and `codex execpolicy check` tests a command against rule files.

Simple shell chains may be split and checked individually. Variables, substitutions, redirections, and other complex syntax may instead be treated as one shell invocation. Broad shell/interpreter prefixes need careful review. [Rules](https://learn.chatgpt.com/docs/agent-configuration/rules)

Illustrative policy—not installed:

```python
prefix_rule(
    pattern=["git", "push"],
    decision="prompt",
    justification="Review publication to a remote repository."
)
prefix_rule(
    pattern=["rm", "-rf"],
    decision="forbidden",
    justification="Use a scoped cleanup tool."
)
```

This is not a complete destructive-command filter: equivalent actions can use different programs or argument ordering. For stronger business enforcement, expose narrow operations such as `prepare_reply` and `request_refund_approval` rather than a general-purpose shell.

## 5. Actual execution boundaries

Beta permission profiles combine filesystem and network policy. Built-ins include `:read-only`, `:workspace`, and `:danger-full-access`; custom profiles support narrower denies and glob patterns. The newer profile mechanism does not compose freely with older sandbox settings. On macOS execution uses Seatbelt. Command-domain restrictions require the network proxy; enabling networking alone does not enforce domain allowlists.

Profiles govern sandboxed local commands, not every connector, MCP server, browser, or computer-use operation. Each external service/process needs its own permissions. [Permission profiles and their limits](https://learn.chatgpt.com/docs/permissions)

My suggested support workflow boundary is a dedicated writable scratch/project directory, read-only access to approved documents, no credential-store access, and narrowly scoped business tools. A harness operating the desktop through accessibility has its own OS permission boundary; it must not assume Codex's sandbox limits its mouse/keyboard actions.

Managed requirements constrain approvals, reviewers, filesystem/network settings, hook availability, MCP identities, plugin sources, browser origins, and application access. Managed hooks can be required while user hooks are disabled. macOS can receive requirements from `/etc/codex/requirements.toml` or MDM; administrators can restrict full-access modes and deny reads. Cloud-local delivery has separate scope rules. A failed remote `PreToolUse` callback can fail without blocking the tool, so verify deployed behavior. [Managed configuration](https://learn.chatgpt.com/docs/enterprise/managed-configuration)

A system-owned policy layer is potentially useful on this Mac if we later want enforcement rather than convenient defaults. It is not necessary for the first local-model spike.

## 6. MCP, plugins, skills, and UI extensions

Local Desktop, CLI, and IDE share MCP configuration for a Codex host. Servers may be local stdio or HTTP, with authentication, enabled/disabled tool lists, timeouts, and per-tool approvals. Server initialization instructions supply cross-tool guidance; they are not documented as base prompt replacement or inbound push delivery. [MCP configuration](https://learn.chatgpt.com/docs/extend/mcp)

Skills package SKILL.md instructions, references, and optional scripts. Their metadata is available initially; full instructions load when selected. `agents/openai.yaml` provides presentation metadata, invocation policy, and tool dependencies. Explicitly invoke mandatory workflows rather than depend solely on automatic discovery. [Build skills](https://learn.chatgpt.com/docs/build-skills)

Plugins bundle skills, MCP services, browser extensions, and hooks. Desktop supports local Codex plugins; cloud-orchestrated Work does not run local/plugin command hooks. Synced Work has distinct admin-defined MCP hook support. Publishing a plugin does not deploy hook scripts to another computer. [Plugins](https://learn.chatgpt.com/docs/plugins)

Plugin UI extensions offer sidebar apps, Desktop composer mentions, rich forms, onboarding, and bidirectional model/app context. These improve how users access a support workflow; they do not establish an unrestricted daemon-to-chat command endpoint. [Plugin Extensions](https://developers.openai.com/plugins/build/extensions)

Record & Replay can turn an observed Mac workflow into a reusable skill, offering another route for repeatable non-coding tasks. It is a workflow-authoring mechanism, not guaranteed replay or a substitute for the control adapter. [Record & Replay](https://learn.chatgpt.com/docs/extend/record-and-replay)

## 7. Specialist agents

Custom subagents can carry dedicated developer instructions, model settings, sandbox configuration, tools, and skill configuration. Their results surface in Desktop. Current triggering is explicitly requested delegation or applicable AGENTS.md/skill instructions requesting it. Named specialists suit ticket classification, account research, and draft-review separation. [Subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents)

This is internal delegation. It does not mean an external harness gains a public address for messaging those agents. Splitting duties also does not create a security boundary unless tool access and permissions are actually constrained.

## 8. Channels and event-driven work

MCP Events supports signed webhook delivery into subscribed Work chats on web, Desktop with Cloud selected, and dots. It requires MCP 2.0 protocol version `2026-07-28`, persistent subscriptions, and outbound HTTPS callbacks. Supported integration delivery is webhook; polling and streaming are not supported. [MCP Events](https://developers.openai.com/plugins/build/mcp-events)

For local Desktop, a queue plus hooks can consume more work while the agent is active. Background-hook completion does not start an idle turn. Scheduled tasks provide periodic execution, subject to local app/computer availability and permissions. [Scheduled tasks](https://learn.chatgpt.com/docs/automations)

App-server exposes structured thread/turn creation, steering, interruption, events, and approval handling. It is an experimental embedding interface; an independent instance is not proof of attachment to Desktop's running session. [App-server](https://learn.chatgpt.com/docs/app-server)

Thus, three designs remain meaningfully different: Cloud event subscriptions; local polling/wakeup; and private/native Desktop bridging. The main spike should measure those boundaries rather than call every MCP connection “Channels.”

## Recommended experiments and evidence to collect

1. Create a separate support project; test role supplementation in a new Desktop chat. Confirm effective instructions and keep the original global configuration untouched.
2. Test base-instruction replacement only if coding defaults persist. Confirm that Desktop tools still work and compare results across new/resumed chats.
3. Start with a redacted synchronous audit hook, then deterministic denial. Record which tools fire hooks and how failures behave on the installed build.
4. Test additive auto-review policy with harmless approval-gated requests; confirm managed restrictions and inspect reviewer rationale.
5. Run command-policy checks separately from GUI automation; measure the tool service's independent authorization.
6. Test wakeup and response receipts through the external adapter. Do not infer successful delivery from UI focus or composer insertion.
7. Document a compatibility matrix by app version, account/workspace, local versus Cloud mode, and extension mechanism.

The best initial business-agent package is a dedicated project, concise AGENTS.md, a small explicit skill, narrowly scoped MCP operations, deterministic audit/denial hooks, and additive reviewer rules. Complete replacement of the system instructions and organization-level managed controls can be later experiments. Desktop push delivery remains a separate transport investigation.

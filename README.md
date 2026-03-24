# relay

`relay` is a local multi-AI handoff orchestrator for Claude, Codex, Gemini, and Qwen.

Related planning documents:

- [Production Checklist](/Users/family/jason/relay/PRODUCTION_CHECKLIST.md)
- [UX Specification](/Users/family/jason/relay/UX_SPEC.md)
- [Docs Hub](/Users/family/jason/relay/docs/README.md)

It supports:

- registering agent launch commands
- opening long-lived interactive origin sessions
- capturing context snapshots
- delegating work to another AI in headless mode
- returning results back to the original AI session
- using a terminal-style Textual TUI with:
  - one input box
  - slash commands
  - tiny AI readiness lights
  - a visible Relay version in the top bar
  - a hidden progress drawer
  - saved linear workflows

Current validation snapshot:

- real headless target delegation has succeeded with Claude, Codex, Gemini, and Qwen
- at least one real chained flow has succeeded: `Gemini -> Qwen -> return`
- a simple real workflow succeeded end-to-end: `helper origin -> Codex(custom) -> return`
- real Gemini workflow validation now succeeds for both:
  - `Gemini -> Codex(custom) -> Send Back`
  - `Gemini -> Codex(implement) -> Send Back`
- real interactive origin sessions are still vendor-sensitive
  - Claude PTY startup still hits trust-flow issues in relay
  - Codex PTY origin sessions still need more work
- Codex review schema compatibility has been fixed for structured output
- the TUI transcript renderer now strips ANSI noise and avoids Textual markup crashes
- the default `rr tui` experience is copy-friendly and does not aggressively capture the mouse
- stale sessions and stale running runs are cleaned up on startup
- direct mode can auto-generate a workflow when no workflow is pinned
- short prompts can use a faster direct route
- approval mode can be changed and is visible in the top bar
- `/agents` shows soft `recommended for` hints and experimental provider notes
- `/rerun last` and `/resume last` are available for replay and recovery
- `/trace last` can render the latest internal execution trace in the transcript body
- workflow management now works through slash commands and English/Korean natural-language aliases
- internal execution events are written to `/Users/family/.relay/events.jsonl`

## Documentation layout

`relay` now follows a `vibehub-media`-style document split:

- [docs/README.md](/Users/family/jason/relay/docs/README.md)
  - entrypoint and maintenance rules
- [docs/status/PROJECT-STATUS.md](/Users/family/jason/relay/docs/status/PROJECT-STATUS.md)
  - current phase, active tracks, validation snapshot
- [docs/status/DECISION-LOG.md](/Users/family/jason/relay/docs/status/DECISION-LOG.md)
  - durable product and architecture decisions
- [docs/status/EXECUTION-CHECKLIST.md](/Users/family/jason/relay/docs/status/EXECUTION-CHECKLIST.md)
  - prioritized execution backlog
- [docs/ref/ARCHITECTURE.md](/Users/family/jason/relay/docs/ref/ARCHITECTURE.md)
  - system structure and ownership boundaries
- [docs/ref/DOCS-OPERATING-MODEL.md](/Users/family/jason/relay/docs/ref/DOCS-OPERATING-MODEL.md)
  - how to maintain docs over time

The older root docs remain useful long-form references:

- [AUTH_SETUP.md](/Users/family/jason/relay/AUTH_SETUP.md)
- [IMPLEMENTATION_HISTORY.md](/Users/family/jason/relay/IMPLEMENTATION_HISTORY.md)
- [PRODUCTION_CHECKLIST.md](/Users/family/jason/relay/PRODUCTION_CHECKLIST.md)
- [UX_SPEC.md](/Users/family/jason/relay/UX_SPEC.md)

## Quick start

```bash
cd /Users/family/jason/relay
python3 -m venv .venv
. .venv/bin/activate
pip install -e .

relay agent add claude-main --kind claude --command "claude" --resume-strategy native
relay agent add codex-review --kind codex --command "codex" --resume-strategy native
relay session open --agent claude-main --label main --cwd /path/to/repo
relay session list
relay delegate --from sess_0001 --to codex-review --task review --title "Review auth flow"
relay return --run run_0001
relay tui
```

## Short launch command

The recommended entrypoint is now:

```bash
relay
```

This opens the shell-style TUI directly.

You can still use:

```bash
relay tui
rr tui
```

The older `rr` wrapper still works, but `relay` is now the preferred default.

## TUI flow

The main TUI now behaves like a normal AI terminal app:

- a compact top bar with AI readiness lights
- a visible direct provider label, for example `Provider: claude-main`
- a visible workflow-main label when a pinned workflow is active
- the current build label, for example `Relay v0.1.0`
- a visible approval label, for example `Approval: default`
- one transcript area
- one input box
- `/` opens slash commands
- `↑`, `↓`, or `Tab` can move through slash-command suggestions
- `/progress` toggles the hidden workflow drawer
- `/trace last` shows the latest internal execution path directly in the transcript body
- `/approval-mode`, `/agents`, `/rerun last`, `/resume last`, `/provider`, and `/provider use ...` are available in the shell
- `/workflow list`, `/workflow inspect`, `/workflow rename`, and `/workflow delete` are available in the shell

If no workflow is pinned, the first natural-language prompt opens a workflow modal once.
You can then:

- run once
- save and pin a workflow
- reuse saved workflows with `/workflow use ...`
- clear the active workflow with `/workflow off`

After the workflow modal has been seen once, later prompts without a pinned workflow use direct provider chat automatically.

Natural-language control is also supported in English and Korean.
These phrases map to internal slash commands instead of bypassing the shell command model.

Examples:

- `Use Gemini as main provider`
- `제미나이 메인으로 바꿔줘`
- `show saved workflows`
- `현재 워크플로우 보여줘`
- `rename this workflow to review chain`
- `이 워크플로우를 문서흐름으로 저장해줘`
- `delete this workflow`
- `워크플로우 alpha 삭제해줘`

Common natural-language examples:

- provider
  - `Use Gemini as main provider`
  - `Switch to Claude`
  - `제미나이 메인으로 바꿔줘`
- workflow setup
  - `Use Gemini as main, then let Qwen review it`
  - `제미나이 메인으로 그다음 큐웬이 리뷰해줘`
  - `Use Gemini as main, then let Qwen review it, then let Codex implement it, and finally send it back to Gemini`
- workflow management
  - `show saved workflows`
  - `show active workflow`
  - `use workflow research chain`
  - `rename this workflow to review chain`
  - `delete this workflow`
  - `저장된 워크플로우 보여줘`
  - `현재 워크플로우 보여줘`
  - `워크플로우 alpha 삭제해줘`
- recovery and visibility
  - `Resume the last workflow`
  - `Run the last thing again`
  - `Show the last trace`
  - `마지막 작업 이어서`
  - `마지막 작업 다시`
  - `마지막 트레이스 보여줘`

Direct chat rules:

- the prompt goes to the selected `Provider`
- relay tries to preserve the provider's answer text and tone
- relay only removes transport noise such as raw event wrappers
- the transcript shows a small thinking indicator while the provider runs
- longer answers are revealed progressively for a CLI-like feel

Workflow transcript rules:

- the transcript shows the original main-provider answer
- then each workflow step result
- then the final send-back answer when present
- if a step fails, the failure remains visible inline

Example success shape:

```text
[Original - gemini-main]
...

[Custom - codex-main]
...

[Final - gemini-main]
...
```

Example failure shape:

```text
[Original - gemini-main]
...

[Build - codex-main (Failed)]
relay headless timeout after 60s

[Workflow Status]
relay headless timeout after 60s
```

Example:

```text
Provider: claude-main   Workflow Main: gemini-main   Approval: default   claude-main ●  codex-main ●  gemini-main ●  qwen-main ●   Relay v0.1.0
```

If you want to inspect what happened internally, use:

```text
/trace last
```

That command now renders a compact local-time trace directly in the transcript body, for example:

```text
Last trace:
[20:05:07] prompt  2+2
[20:05:08] start   qwen-main
[20:05:17] done    qwen-main -> 2 + 2 = 4
[20:05:17] final   2 + 2 = 4
```

## Current test status

Automated suite:

```text
Ran 70 tests
OK
```

Notable manual validations:

- `relay tui` launches without the previous transcript markup crash
- slash-command overlay opens on `/` and disappears when removed
- simple question workflow succeeded:
  - prompt: `What is 2 + 2?`
  - target flow: `Codex(custom)`
  - result returned successfully to the origin session
- direct provider chat now succeeds for:
  - prompt: `2+2`
  - provider: `qwen-main` or `claude-main`
  - result: clean provider answer in the transcript
- `/trace last` now shows a compact transcript-body trace for the latest execution group
- startup stale cleanup can close old dead sessions and fail abandoned runs before the next TUI launch
- `/approval-mode plan` can block implement workflows before execution begins
- `/agents` shows readiness plus `recommended for` and `experimental` metadata
- `/resume last` can now skip already completed workflow steps and resume send-back-only recovery
- workflow management now supports:
  - `/workflow list`, `/workflow inspect`, `/workflow rename`, `/workflow delete`
  - English/Korean natural-language aliases for list, inspect, use, save, rename, and delete
- real Gemini shell validation confirms:
  - `gemini-main` direct prompts succeed
  - `Gemini -> Codex(custom) -> Send Back` succeeds with visible `Original / step / Final` transcript blocks
  - `Gemini -> Codex(implement) -> Send Back` now succeeds after compact-path tuning

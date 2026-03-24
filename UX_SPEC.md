# relay UX Specification

This is a detailed long-form UX reference.

For the current operational view, start with:

- [Docs Hub](/Users/family/jason/relay/docs/README.md)
- [Project Status](/Users/family/jason/relay/docs/status/PROJECT-STATUS.md)
- [Decision Log](/Users/family/jason/relay/docs/status/DECISION-LOG.md)
- [Architecture](/Users/family/jason/relay/docs/ref/ARCHITECTURE.md)

This document describes the intended production UX for `relay`, with improvements informed by current AI terminal products.

## UX Goal

Make `relay` feel as simple as a single-provider terminal assistant while quietly orchestrating multiple AI providers in the background.

The product should feel:

- familiar to Claude Code and Codex users
- fast to start
- quiet by default
- transparent when the user asks for detail

## Design Principles

### 1. One obvious input

The user should always see:

- one transcript area
- one input field

Everything else is secondary.

### 2. Complexity is opt-in

Workflow setup, progress, traces, auth repair, and raw provider data should be hidden until explicitly requested.

### 3. Terminal-first familiarity

The default shell should resemble modern AI coding CLIs:

- minimal chrome
- compact status line
- slash commands
- fast keyboard-first interaction

### 4. Provider plurality, not provider chaos

Multiple AIs can be present, but the user should never feel like they are manually juggling four separate apps.

### 5. Recommendations, not restrictions

`relay` should not hard-lock providers into fixed roles.

Instead:

- every provider can be placed in any workflow step
- the system can show `recommended for` hints
- presets and fast paths can prefer certain providers
- the user must always be able to override the default suggestion

## Main Shell

The default shell should contain:

- top status strip
- transcript area
- one prompt input

No permanent side panels.

### Top status strip

The top strip should show:

- current direct provider
- current workflow main provider when a workflow is pinned
- provider readiness lights
- current build label
- current approval label

Example:

```text
Provider: claude-main   Workflow Main: gemini-main   Approval: default   claude-main ●  codex-main ●  gemini-main ●  qwen-main ●   Relay v0.1.0
```

Guidelines:

- green means ready
- red means auth or execution problem
- gray means unavailable or disabled
- do not show large logos in the steady-state shell

## Branding

### What to copy from competitors

From Claude Code and Codex:

- sparse shell
- confidence through restraint
- utility over decoration

From Aider:

- strong documentation and practical workflows
- useful, concrete commands instead of decorative UI

From Qwen Code:

- rich command surface with low visual overhead

### Relay branding recommendation

Keep brand expression subtle:

- build label in top bar
- optional first-launch splash
- `/about` screen for full branding
- `--plain` mode for minimalists

Avoid:

- persistent large logos
- startup banners on every launch
- marketing copy in the transcript

## Slash Command System

Slash commands are the primary control surface.

When the input starts with `/`:

- show a keyboard-first command palette above the input
- filter commands live as the user types
- remove the palette immediately when `/` is deleted
- allow `Up`, `Down`, and `Tab` to move through the command list
- allow `Enter` to apply the selected slash command without typing the full command

### Required commands

- `/workflow`
- `/workflow new`
- `/workflow use`
- `/workflow save`
- `/workflow off`
- `/trace last`
- `/progress`
- `/agents`
- `/login`
- `/approval-mode`
- `/provider`
- `/provider use`
- `/rerun last`
- `/resume last`
- `/help`

### Recommended next commands

Absorb the strongest patterns from Qwen and Aider:

- `/copy transcript`
- `/copy last-result`
- `/export transcript`
- `/export last-result`
- `/web`
- `/about`

## Workflow UX

### First-run workflow choice

When the user submits natural text and no workflow is pinned:

- open a workflow chooser once
- offer:
  - `Send directly`
  - `Build a workflow`
  - `Always use this workflow`

After that:

- direct mode should just work
- pinned workflows should run automatically
- `/workflow off` should return the user to the chooser-once behavior

Direct-mode rule:

- if no workflow is pinned, relay should behave like a thin wrapper around the selected direct provider
- relay may clean transport noise, but it should not rewrite the provider's tone or answer style

### Workflow editor

Use a linear step-chain editor, not a free-form graph.

V1 workflow step types:

- direct
- review
- research
- simplify
- implement
- context digest
- custom

Each step should define:

- provider
- job type
- optional label

Provider selection rule:

- all providers remain available for all step types
- the UI may highlight one or two suggested providers for a given job type
- suggestions must never remove the user's freedom to build unusual workflows

Workflow transcript rule:

- show the original main-provider answer by default
- show each step result by default
- show the final send-back answer when available
- if the workflow fails, show the failed step and workflow status inline instead of hiding them behind diagnostics

Target transcript shape:

```text
[Original - gemini-main]
...

[Review - codex-main]
...

[Final - gemini-main]
...
```

Or on failure:

```text
[Original - gemini-main]
...

[Build - codex-main (Failed)]
relay headless timeout after 60s

[Workflow Status]
relay headless timeout after 60s
```

### Recommended workflow presets

- `Main AI -> Codex Review -> Send Back`
- `Main AI -> Gemini Research -> Send Back`
- `Main AI -> Gemini Simplify -> Send Back`
- `Main AI -> Gemini Research -> Codex Implement -> Send Back`

These presets are starting points, not enforced templates.

## Progress UX

Progress must be hidden by default.

### Collapsed state

The user sees:

- transcript
- prompt input

Nothing else.

During direct execution, the shell may show a small thinking label such as:

```text
Thinking with claude-main...
```

Longer answers may be revealed progressively, but the effect should feel natural and should never make short answers feel artificially slow.

### Expanded state

When `/progress` is used, open a bottom drawer showing:

- current step
- active provider
- completed steps
- failed step
- compact summaries

Do not show raw JSON in the drawer by default.

Approval state should remain visible even when the progress drawer is closed.

## Trace UX

`/trace last` should render directly into the transcript body.

Target compact format:

```text
Last trace:
[20:05:07] prompt  2+2
[20:05:08] start   qwen-main
[20:05:17] done    qwen-main -> 2 + 2 = 4
[20:05:17] final   2 + 2 = 4
```

Rules:

- local time only
- keep it short
- include provider and final result
- never dump raw event arrays by default

## Recovery UX

`/rerun last` and `/resume last` should have distinct meanings.

- `/rerun last`
  - run the previous prompt again with the same workflow
- `/resume last`
  - continue from the next unfinished workflow step when possible
  - retry send-back only when the workflow steps already succeeded
  - include the last failure reason in the notice when available

The resume path should feel like recovery, not just replay.

## Competitive Features To Absorb

### Claude Code

Absorb:

- calm, sparse terminal UX
- strong “main path first” design
- optional expansion to richer surfaces

### Codex

Absorb:

- explicit approval modes
- local code review as a first-class flow
- subagent and web-search style task routing

### Gemini CLI

Absorb:

- workspace instruction file concept
- trusted workspace model
- large-context tool friendliness

Recommended relay equivalent:

- `RELAY.md`

### Qwen Code

Absorb:

- excellent command ergonomics
- clean `/`, `@`, `!` mental model
- auth and approval controls inside the shell

Recommended relay equivalent:

- `/approval-mode`
- `@file`
- `@dir`
- `!shell`

## Provider Recommendation Model

Instead of hard roles, the UX should show soft capability hints.

Examples:

- `recommended for review`
- `recommended for research`
- `recommended for fast direct`
- `recommended for final answer`

These hints should appear in:

- workflow setup modals
- workflow presets
- fast-route selection logic
- provider info views such as `/agents`

They should not appear as:

- blocked options
- hidden providers
- mandatory routing rules

### Aider

Absorb:

- git-friendly workflows
- web and image inputs
- clipboard and export ergonomics
- practical edit-review-test loop

Recommended relay equivalent:

- `/web`
- `/copy`
- `/export`
- optional `run tests after edit`

## Production Command Model

Recommended final command surface:

- `/workflow`
- `/trace last`
- `/progress`
- `/agents`
- `/login`
- `/approval-mode`
- `/copy`
- `/export`
- `/web`
- `/about`

Recommended next syntax additions:

- `@file`
- `@dir`
- `!command`

## Production UX Requirements

The UX is production-ready when:

- the default shell feels stable and unsurprising
- one prompt box is always the main interaction point
- direct mode feels like talking to the selected provider, not to relay
- provider readiness is glanceable
- current direct provider and workflow main are both understandable at a glance
- direct mode is fast and trustworthy
- workflow detail is available without polluting the default view
- workflow outputs show original, intermediate, and final layers without requiring a trace command
- command discovery is easy from `/`
- copy, paste, and export are reliable in the default shell

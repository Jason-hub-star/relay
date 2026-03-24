# relay Production Checklist

This is a detailed long-form checklist.

For the current operational view, start with:

- [Docs Hub](/Users/family/jason/relay/docs/README.md)
- [Project Status](/Users/family/jason/relay/docs/status/PROJECT-STATUS.md)
- [Execution Checklist](/Users/family/jason/relay/docs/status/EXECUTION-CHECKLIST.md)
- [Architecture](/Users/family/jason/relay/docs/ref/ARCHITECTURE.md)

This document defines the practical checklist for taking `relay` from a validated prototype to a production-ready terminal product.

## Product Goal

`relay` should feel like a normal AI terminal app with one input box, while safely orchestrating multiple AI providers behind the scenes.

Production quality means:

- users can trust the default path
- recovery is predictable
- provider failures are isolated
- logs and traces make incidents diagnosable
- the UX stays simple even when the internal workflow is complex

## 1. Reliability

### 1.1 Headless-first execution

- make headless orchestration the default execution model
- keep PTY-backed live-origin paths explicitly marked as experimental
- ensure every workflow step can run without a live terminal attach when possible
- avoid relying on provider-specific interactive trust screens in the main path

### 1.2 Failure isolation

- one provider failure must not block the whole app
- auth failure, timeout, malformed output, or provider crash should fail only the affected step
- workflow runner should surface:
  - failed step
  - provider
  - compact cause
  - next safe action

### 1.3 Restart and recovery

- preserve enough state to recover after a crash or restart
- add user-facing recovery commands:
  - `/resume last`
  - `/rerun last`
  - `/trace last`
- keep startup cleanup for stale sessions and abandoned runs
- support safe re-entry into the last known workflow state

### 1.4 Timeouts and retries

- define provider-specific default timeouts
- keep compact retry behavior for large Codex jobs
- add bounded retry policies for:
  - transient network failures
  - rate limits
  - malformed but retryable output
- record retry attempts in trace output

## 2. Provider Compatibility

### 2.1 Capability matrix

Maintain a provider capability matrix and use it in routing decisions.

Important rule:

- capabilities are recommendations, not hard restrictions
- every provider should remain manually assignable to every workflow step
- the matrix should guide defaults, fast paths, and suggestions, while still allowing user override

Each provider should be rated for:

- `direct`
- `review`
- `implement`
- `research`
- `optimizer`
- `origin`
- `target`
- `fast`
- `reliable`

Current practical direction as `recommended_for` metadata:

- `Claude`: recommended for direct, planning, and final answer quality
- `Codex`: recommended for review and implementation
- `Gemini`: recommended for research and large-context exploration
- `Qwen`: recommended for fast direct responses and command-surface ergonomics

This should be exposed as a soft hint system rather than a locked role system.

### 2.2 Authentication lifecycle

- login checks must run before provider use
- auth failures should be actionable and provider-local
- support re-login without restarting the whole app
- add cached readiness state with revalidation windows

## 3. Safety and Permissions

### 3.1 Approval modes

Add a first-class approval model inspired by modern coding CLIs:

- `plan`
- `ask`
- `auto-edit`
- `yolo`

This mode should influence:

- shell command execution
- file edits
- delegated code review or implementation steps
- web access and external tools

### 3.2 Workspace trust

- add trusted workspace policy separate from provider trust UX
- show trust state clearly in the shell
- avoid surprising execution in unknown directories

## 4. Observability

### 4.1 Event logging

Keep append-only execution events as a core feature.

Required:

- execution events written to `/Users/family/.relay/events.jsonl`
- trace grouping by execution run
- compact UI trace
- raw provider output retained for diagnosis

### 4.2 User-visible trace and diagnostics

Required commands:

- `/trace last`
- `/trace <id>`
- `/providers`
- `/health`

Nice-to-have:

- `/open logs`
- `/export trace`
- `/report bug`

## 5. UX and Interaction Model

### 5.1 Preserve the single-input terminal shell

Production `relay` should keep:

- one transcript area
- one input box
- compact provider status strip
- no permanent dashboard panels

### 5.2 Hide complexity by default

- workflows should stay behind slash commands and setup modals
- progress should remain in a collapsible drawer
- raw JSON should never be the default surface

### 5.3 Brand restraint

Avoid heavy branding in the main shell.

Recommended:

- top-bar build label such as `Relay v0.1.0`
- small provider indicators
- optional splash on first launch
- richer branding only in `/about`

## 6. Workflow System

### 6.1 Linear workflow support must feel stable

- pinned workflow behavior must be predictable
- no silent reuse of broken legacy workflows
- saved workflows must be easy to inspect, rename, and disable
- provider choice inside a workflow must remain user-controlled
- recommendation badges such as `recommended for review` should assist the user without blocking custom layouts

### 6.2 Production workflow features

Minimum:

- save
- use
- disable
- inspect
- rerun

Recommended next:

- workflow gallery
- workflow tags such as `review`, `research`, `ship`
- workflow export and import

## 7. Evaluation and QA

### 7.1 Automated evaluation set

Maintain a stable test matrix for:

- short direct questions
- repo explanation
- code review
- implementation
- web research
- multi-step workflow chaining
- auth recovery
- timeout and retry
- trace rendering
- copy and export behavior

### 7.2 Real-world manual checks

At minimum, verify:

- `rr tui` launches cleanly
- copy and paste work in the default shell
- `/trace last` is readable
- a short direct prompt succeeds
- a saved workflow runs
- auth recheck works when one provider expires

## 8. Distribution and Operations

### 8.1 Packaging

- provide a stable install path
- ensure `rr tui` is the simplest supported entrypoint
- avoid requiring users to remember long virtualenv commands

### 8.2 Upgrade path

- show the running build version in the shell
- add a changelog and migration notes for workflow storage changes
- avoid breaking existing saved workflows without a cleanup step

## 9. Recommended Production Milestones

### P0: trustable shell

- headless-first default path
- stale cleanup
- login checks
- `/trace last`
- direct mode stability
- provider capability matrix

### P1: safe daily driver

- approval modes
- trusted workspace policy
- `/resume last`
- `/rerun last`
- workflow inspection

### P2: power-user terminal

- `@file`, `@dir`, `!shell`
- clipboard helpers
- export commands
- web and image inputs

### P3: expanded product surface

- desktop companion
- optional web companion
- workflow gallery
- cloud or remote task execution

## Exit Criteria For "Production Ready"

`relay` is ready for a public production claim when:

- the default shell path is consistently reliable
- one-provider failures do not destabilize the app
- direct mode, saved workflows, and traces are predictable
- users can diagnose failures without opening source code
- auth and provider compatibility behavior are clearly communicated
- workflow and log persistence survive restarts safely

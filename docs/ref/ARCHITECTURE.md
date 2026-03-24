# relay Architecture

## Layers

- `src/relay/cli.py`
  - command entrypoint and shell launch
- `src/relay/tui.py`
  - terminal UI, transcript rendering, slash commands, workflow modal
- `src/relay/service.py`
  - orchestration layer for direct prompts, workflows, returns, replay, and recovery
- `src/relay/repository.py`
  - SQLite persistence for agents, sessions, packets, runs, results, and returns
- `src/relay/session_host.py`
  - PTY-backed live session host for experimental origin flows
- `src/relay/adapters.py`
  - provider-specific headless command builders
- `src/relay/prompts.py`
  - transport cleanup and output normalization helpers
- `src/relay/workflow_store.py`
  - persisted workflow state, approval mode, and main provider

## Core Runtime Model

### Direct chat

- the user types a plain prompt
- relay sends it to the selected `Provider`
- relay preserves the provider answer as much as possible
- relay only cleans transport noise and terminal-hostile payload shapes

### Workflow chat

- the user pins or explicitly runs a workflow
- relay first captures the original main-provider answer
- relay runs step providers in sequence
- relay optionally sends the result back to the workflow main provider
- transcript output is layered:
  - original
  - step(s)
  - final or workflow status

## State Model

### Persistent shell state

Stored in workflow state:

- main provider
- approval mode
- active workflow id
- saved workflows

### Relay execution persistence

Stored in SQLite:

- agents
- sessions
- context snapshots
- task packets
- runs
- run results
- return events
- presets

### Event logging

Append-only event log:

- `/Users/family/.relay/events.jsonl`

Used for:

- trace rendering
- replay/recovery
- debugging of real provider behavior

## Provider Model

Provider recommendations are soft hints, not hard locks.

Current practical direction:

- `Claude`
  - recommended for direct, planning, final-answer quality
- `Codex`
  - recommended for review and implementation
- `Gemini`
  - recommended for research and context gathering
- `Qwen`
  - recommended for fast direct responses and command-heavy usage

## Stability Boundary

### Stable

- headless direct prompts
- headless workflow steps
- transcript layering
- replay and resume commands

### Experimental

- PTY-backed live-origin Claude path
- PTY-backed live-origin Codex path

## Documentation Ownership Rule

- `docs/status/*`
  - current operational truth
- `docs/ref/*`
  - stable reference model
- root docs
  - detailed long-form supplements during the transition to the new docs layout

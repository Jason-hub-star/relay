# relay Test Matrix

This document defines the practical test matrix for `relay`.

The goal is not exhaustive combination coverage.
The goal is to cover the product's highest-risk paths with a stable, repeatable set of checks.

## Coverage Philosophy

`relay` does not need every possible provider × workflow × failure combination tested manually.

Instead, testing should be split into:

- `must-pass`
  - core product paths that should work before everyday use
- `known-risk`
  - important paths that are allowed to fail for now, but must remain visible and understood
- `optional`
  - useful extra checks that improve confidence but do not block ordinary use

## Must-Pass

These are the minimum paths that should pass before calling the shell usable.

### 1. Launch and shell basics

- `relay` launches the TUI directly
- top bar renders:
  - `Provider`
  - `Workflow Main` when applicable
  - `Approval`
  - provider readiness lights
- input is focused on launch
- slash command palette opens on `/`
- slash command palette supports keyboard navigation

### 2. Direct provider chat

- direct prompt with `claude-main`: pass
- direct prompt with `gemini-main`: pass
- direct prompt with `qwen-main`: pass
- direct provider switching via:
  - `/provider`
  - `/provider use <name>`
  - English/Korean natural-language aliases that map to provider commands
- short prompt such as `2+2` returns clean provider text, not raw event payloads

### 3. Core workflow success

- `Gemini -> Codex(custom) -> Send Back`: pass
- `Gemini -> Codex(implement) -> Send Back`: pass with compact-path tuning
- transcript shows:
  - `Original`
  - step output
  - `Final`
- workflow modal can:
  - open
  - select agents/jobs
  - save
  - pin a workflow
- workflow shell management works through:
  - `/workflow list`
  - `/workflow inspect`
  - `/workflow rename`
  - `/workflow delete`
  - English/Korean natural-language aliases for list, inspect, use, save, rename, and delete

### 4. Recovery and trace

- `/trace last`: pass
- `/rerun last`: pass
- `/resume last`: pass
- resume can skip already completed steps
- send-back-only recovery works when workflow steps already completed

### 5. State and startup

- startup stale cleanup runs
- old stale sessions are closed safely
- abandoned queued/running runs are failed safely
- workflow state persists across launches
- main provider persists across launches

## Known-Risk

These paths are important and should be monitored, but current failure is acceptable as long as it is explicit and diagnosable.

### 1. Heavy Codex workflow regressions

- `Gemini -> Codex(implement) -> Send Back`
- current expectation:
  - compact-path tuning should allow successful completion
- requirement:
  - if it regresses, failure must still render inline as:
    - `[Step (Failed)]`
    - `[Workflow Status]`

### 2. PTY-backed live-origin sessions

- Claude live-origin in relay PTY path
- Codex live-origin in relay PTY path
- expected current risk:
  - trust prompt noise
  - terminal UI incompatibility
- requirement:
  - these paths stay clearly marked as experimental

### 3. Provider auth drift

- Gemini cached auth expires
- Qwen cached auth expires
- requirement:
  - auth issue is localized to that provider
  - user can recover via login path

## Optional

These improve confidence and operator comfort, but should not block ordinary development.

### 1. Additional provider combinations

- `Claude -> Codex(review) -> Send Back`
- `Claude -> Gemini(research) -> Send Back`
- `Qwen -> Claude(final) -> Send Back`

### 2. UX polish checks

- thinking indicator displays naturally
- longer answers reveal progressively without feeling artificial
- copy/paste/export remain reliable
- transcript remains readable after multiple runs

### 3. Documentation checks

- `docs/status/PROJECT-STATUS.md` matches actual validation state
- `docs/status/DECISION-LOG.md` reflects durable product choices
- `docs/status/EXECUTION-CHECKLIST.md` matches next work

## Manual Validation Set

This is the recommended small manual suite before calling a change "safe enough":

1. launch `relay`
2. ask a short direct question with current provider
3. switch provider with `/provider use ...`
4. run one successful workflow:
   - `Gemini -> Codex(custom) -> Send Back`
5. run one heavier workflow:
   - `Gemini -> Codex(implement) -> Send Back`
6. if it fails, verify failure stays visible inline
7. run `/trace last`
8. run `/rerun last`
9. run `/resume last`

## Automated Validation Set

The automated suite should at minimum cover:

- launch and parser behavior
- slash command routing
- provider switching
- workflow save/use/off
- direct result cleanup
- transcript layering
- trace rendering
- resume and rerun behavior
- stale cleanup behavior

## Exit Criteria

`relay` is in a good validation state when:

- every `must-pass` item succeeds
- every `known-risk` item fails clearly rather than silently
- the user can tell:
  - what ran
  - what succeeded
  - what failed
  - what to retry next

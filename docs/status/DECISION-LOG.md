# Decision Log

This document records durable product and architecture decisions for `relay`.

## Resolved

### 2026-03-24 — Relay is a switchboard, not a second assistant

- status: resolved
- decision:
  - relay should not act like its own chat personality in normal direct mode
  - direct prompts should go to the selected provider with minimal relay interference
  - relay should focus on routing, handoff, replay, recovery, logging, and workflow orchestration
- rationale:
  - users expect the product to feel like Claude, Codex, Gemini, or Qwen directly, not a wrapper that rewrites their answers

### 2026-03-24 — Direct provider and workflow main must be shown separately

- status: resolved
- decision:
  - show `Provider: ...` for the direct default path
  - show `Workflow Main: ...` when a pinned workflow exists
- rationale:
  - direct provider and workflow main can differ, and that difference was confusing during real Gemini workflow runs

### 2026-03-24 — Workflow transcripts must show original, intermediate, and final outputs

- status: resolved
- decision:
  - workflow transcript blocks should show:
    - original main-provider output
    - each step output
    - final send-back output when present
  - if a workflow fails, show the failed step and workflow status inline
- rationale:
  - users wanted to see the real intermediate work without relying on `/trace last`

### 2026-03-24 — Keep provider recommendations soft

- status: resolved
- decision:
  - provider capabilities are `recommended_for` hints only
  - all providers remain manually selectable for all workflow steps
- rationale:
  - the product goal is flexible routing, not hard role locking

### 2026-03-24 — Headless-first remains the stable main path

- status: resolved
- decision:
  - headless orchestration is the default execution model
  - PTY-backed live-origin flows remain experimental
- rationale:
  - real vendor PTY behavior is still inconsistent, especially around trust screens and terminal UI compatibility

### 2026-03-24 — Adopt vibehub-style docs split

- status: resolved
- decision:
  - `docs/status` will hold current-state operational docs
  - `docs/ref` will hold stable reference docs
  - root docs remain as detailed references during transition
- rationale:
  - the project needs a fast-moving operational layer plus a stable reference layer

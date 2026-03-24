# relay Project Status

## Current Phase

- shell-style TUI baseline: done
- direct provider pass-through: done
- workflow layering in transcript: done
- provider/workflow-main distinction: done
- approval mode and recovery commands: done
- docs operating model split: done

## Active Tracks

- terminal-style shell with one input: done
- slash command palette with keyboard selection: done
- provider readiness strip: done
- persisted direct provider selection: done
- pinned workflow persistence: done
- layered workflow transcript (`Original / step / Final`): done
- failure-visible workflow transcript (`Failed / Workflow Status`): done
- startup stale cleanup: done
- `/trace last`: done
- `/rerun last`: done
- `/resume last`: done
- approval mode top-bar visibility: done
- workflow modal compact layout: done
- workflow modal top save buttons: done
- workflow modal focus/arrow-key usability: done
- relay-as-switchboard direct path: done
- Gemini direct shell validation: done
- Gemini -> Codex(custom) -> Send Back validation: done
- Gemini -> Codex(implement) timeout visibility: done
- heavy Codex implement workflow tuning: in progress
- vendor-specific live origin strategy: in progress

## Validation

- automated tests: `63 tests`, pass
- `relay` default launch opens the TUI directly: pass
- direct prompt without pinned workflow: pass
- `2+2` shell check: pass
- `/trace last` transcript rendering: pass
- `/approval-mode`, `/agents`, `/rerun last`, `/resume last`: pass
- real Gemini direct prompt in shell: pass
- real layered workflow:
  - `Original - gemini-main`
  - `Custom - codex-main`
  - `Final - gemini-main`
  - pass
- real heavy workflow:
  - `Gemini -> Codex(implement) -> Send Back`
  - Codex timeout after 60s
  - failure visible inline

## Open Follow-ups

- heavy Codex `implement` steps still time out in some workflows
- real Claude PTY-origin trust flow is still noisy in relay
- real Codex PTY-origin support is still unstable
- workflow presets should avoid fragile heavy defaults where safer presets exist
- docs in root and docs tree should stay synchronized until the new structure fully settles

## Current User-Facing Model

- `Provider`
  - direct main provider for plain prompts
- `Workflow Main`
  - pinned workflow main provider when a workflow is active
- direct chat
  - provider answer with minimal relay cleanup
- workflow chat
  - original result
  - step result(s)
  - final result or explicit failure status

# relay Project Status

## Current Phase

- shell-style TUI baseline: done
- direct provider pass-through: done
- workflow layering in transcript: done
- provider/workflow-main distinction: done
- approval mode and recovery commands: done
- docs operating model split: done
- natural-language command aliases: done
- natural-language workflow management aliases: done

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
- workflow list/inspect shell UX: done
- workflow rename/delete shell UX: done
- English/Korean natural-language command routing: done
- English/Korean natural-language workflow management: done
- relay-as-switchboard direct path: done
- Gemini direct shell validation: done
- Gemini -> Codex(custom) -> Send Back validation: done
- Gemini -> Codex(implement) compact-path validation: done
- heavy Codex implement workflow tuning: done
- vendor-specific live origin strategy: in progress

## Validation

- automated tests: `70 tests`, pass
- test matrix defined: done
- `relay` default launch opens the TUI directly: pass
- direct prompt without pinned workflow: pass
- `2+2` shell check: pass
- `/trace last` transcript rendering: pass
- `/approval-mode`, `/agents`, `/rerun last`, `/resume last`: pass
- `/workflow list`, `/workflow inspect`, `/workflow rename`, `/workflow delete`: pass
- English/Korean natural-language aliases for provider, workflow, recovery, and workflow management: pass
- real Gemini direct prompt in shell: pass
- real layered workflow:
  - `Original - gemini-main`
  - `Custom - codex-main`
  - `Final - gemini-main`
  - pass
- real heavy workflow:
  - `Gemini -> Codex(implement) -> Send Back`
  - pass after compact-path tuning
  - result returned successfully

## Open Follow-ups

- heavy Codex `implement` steps improved after compact-path tuning, but should still be watched for regressions
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
- natural-language control
  - English/Korean aliases map into slash-command semantics instead of bypassing shell routing

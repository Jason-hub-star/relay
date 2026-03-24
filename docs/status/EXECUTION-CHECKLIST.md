# relay Execution Checklist

This is the prioritized execution checklist for `relay`.

## Priority Order

- `P0`: immediate product trust and routing issues
- `P1`: core workflow reliability and operator usability
- `P2`: power-user ergonomics and richer document coverage
- `P3`: expansion and long-term operational hardening

## P0 — Immediate

- [x] one-input shell baseline
- [x] provider lights in top bar
- [x] approval mode visible in top bar
- [x] persisted direct provider
- [x] `/provider` and `/provider use`
- [x] `/trace last`
- [x] `/rerun last`
- [x] `/resume last`
- [x] startup stale cleanup
- [x] workflow transcript shows original, step, and final layers
- [x] workflow failure is visible inline
- [x] reduce heavy Codex `implement` payloads
- [x] tune heavy-step timeout and retry policy
- [ ] audit default presets and avoid fragile heavy workflows

## P1 — Workflow Reliability

- [x] compact workflow modal with visible save buttons
- [x] modal focus and arrow-key usability
- [x] workflow inspect/list UX
- [x] workflow rename/delete UX
- [x] English/Korean natural-language aliases for shell commands
- [x] English/Korean natural-language aliases for workflow management
- [ ] safer `implement` preset variants
- [ ] better failure hints for timed-out steps
- [ ] richer `/agents` output with current provider and workflow context

## P1 — Provider Compatibility

- [x] real Gemini direct shell validation
- [x] real Gemini -> Codex(custom) workflow validation
- [x] real Gemini -> Codex(implement) compact-path validation
- [ ] vendor-specific Claude live-origin strategy
- [ ] vendor-specific Codex live-origin strategy
- [ ] explicit compatibility summary for direct / target / origin

## P2 — Power User Ergonomics

- [ ] `@file`
- [ ] `@dir`
- [ ] `/copy`
- [ ] `/export`
- [ ] `/web`
- [ ] `!shell` behind approval mode
- [ ] `RELAY.md` project instruction file

## P2 — Documentation

- [x] `docs/status` split introduced
- [x] `docs/ref` split introduced
- [x] test matrix document introduced
- [ ] move or mirror more long-form root docs into `docs/ref`
- [ ] add weekly operating summary template
- [ ] add daily debugging note template

## P3 — Hardening

- [ ] provider health summary
- [ ] retry and backoff policy per provider
- [ ] trusted workspace policy
- [ ] exportable trace bundles
- [ ] broader manual evaluation suite
- [ ] optional desktop/web companion surfaces

## Recommended Next Sequence

1. add provider compatibility summary for direct / target / origin
2. add `@file` and `@dir`
3. continue migrating doc management into `docs/`
4. audit default presets and replace fragile heavy presets where needed
5. add safer `implement` workflow variants and better timeout hints

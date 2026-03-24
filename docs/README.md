# relay Docs Hub

This folder is the operational document home for `relay`.

It mirrors the document management style used in `vibehub-media`:

- `docs/status`
  - living status, decisions, and execution tracking
- `docs/ref`
  - stable reference documents
- `docs/daily`
  - optional daily work notes
- `docs/weekly`
  - optional weekly summaries

## Document roles

### `docs/status`

Use these for documents that change frequently while the product is actively evolving.

- [PROJECT-STATUS.md](/Users/family/jason/relay/docs/status/PROJECT-STATUS.md)
  - current phase, active tracks, validation snapshot, open follow-ups
- [DECISION-LOG.md](/Users/family/jason/relay/docs/status/DECISION-LOG.md)
  - durable product or architecture decisions
- [EXECUTION-CHECKLIST.md](/Users/family/jason/relay/docs/status/EXECUTION-CHECKLIST.md)
  - prioritized execution backlog
- [TEST-MATRIX.md](/Users/family/jason/relay/docs/status/TEST-MATRIX.md)
  - practical validation coverage grouped by must-pass, known-risk, and optional

### `docs/ref`

Use these for longer-lived reference material.

- [ARCHITECTURE.md](/Users/family/jason/relay/docs/ref/ARCHITECTURE.md)
- [DOCS-OPERATING-MODEL.md](/Users/family/jason/relay/docs/ref/DOCS-OPERATING-MODEL.md)

Long-form root references still exist and remain valid:

- [AUTH_SETUP.md](/Users/family/jason/relay/AUTH_SETUP.md)
- [IMPLEMENTATION_HISTORY.md](/Users/family/jason/relay/IMPLEMENTATION_HISTORY.md)
- [PRODUCTION_CHECKLIST.md](/Users/family/jason/relay/PRODUCTION_CHECKLIST.md)
- [UX_SPEC.md](/Users/family/jason/relay/UX_SPEC.md)

## Update rules

- Update `PROJECT-STATUS.md` when the practical state of the product changes.
- Update `DECISION-LOG.md` when a product or architecture choice becomes settled.
- Update `EXECUTION-CHECKLIST.md` when priorities or blockers change.
- Update `ARCHITECTURE.md` when system boundaries, data flow, or ownership rules change.
- Keep root long-form docs detailed, but make `docs/status` the quickest way to understand the current state.

## Suggested routine

When work lands:

1. update the relevant code
2. update `docs/status/PROJECT-STATUS.md`
3. record any durable choice in `docs/status/DECISION-LOG.md`
4. adjust `docs/status/EXECUTION-CHECKLIST.md`
5. update reference docs only if the stable model changed

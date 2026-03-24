# relay Docs Operating Model

This document defines how `relay` documentation should be maintained.

## Goal

Make it easy to answer two different questions:

1. what is true right now?
2. what is the stable intended model?

That split is the reason for `docs/status` and `docs/ref`.

## Folder policy

### `docs/status`

Use for fast-moving operational truth.

These documents should answer:

- what phase is the project in?
- what was decided recently?
- what is next?
- what passed or failed in recent validation?

Files:

- `PROJECT-STATUS.md`
- `DECISION-LOG.md`
- `EXECUTION-CHECKLIST.md`

### `docs/ref`

Use for slower-changing reference material.

These documents should answer:

- what is the architecture?
- how should the docs be maintained?
- what are the stable UX and production models?

## Update triggers

Update `PROJECT-STATUS.md` when:

- a new capability lands
- validation status changes
- a major blocker appears or is removed

Update `DECISION-LOG.md` when:

- a product choice becomes settled
- a provider or workflow policy becomes durable
- a UX tradeoff is intentionally chosen

Update `EXECUTION-CHECKLIST.md` when:

- priorities change
- a track is completed
- a blocker becomes the next main task

Update `ARCHITECTURE.md` when:

- runtime flow changes
- state ownership changes
- provider boundaries or stability boundaries change

## Writing rules

- keep `status` docs short, current, and operational
- keep `ref` docs stable and explanatory
- prefer adding a decision log entry over burying a decision inside a long prose document
- link between docs rather than duplicating large sections
- use concrete file paths and command names where helpful

## Suggested maintenance loop

For meaningful product work:

1. ship code
2. update status docs
3. record durable decisions
4. update architecture only if the stable model changed
5. update root long-form docs if deeper background changed

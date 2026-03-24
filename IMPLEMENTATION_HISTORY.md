# relay Implementation History

This is the detailed implementation timeline and background record.

For the fastest current-state view, start with:

- [Docs Hub](/Users/family/jason/relay/docs/README.md)
- [Project Status](/Users/family/jason/relay/docs/status/PROJECT-STATUS.md)
- [Decision Log](/Users/family/jason/relay/docs/status/DECISION-LOG.md)
- [Execution Checklist](/Users/family/jason/relay/docs/status/EXECUTION-CHECKLIST.md)

This document captures what has been built so far, how it was implemented, what was tested, and which real-world constraints were discovered during validation. It is intended to be a source document that can later be condensed into `README.md`.

## Goal

`relay` was built as a local multi-AI handoff orchestrator with these core behaviors:

- manually choose when to delegate work to another AI
- keep roles swappable at any time
- capture current context from an origin session
- run delegated work headlessly against another AI
- return the result back to the original AI session
- persist sessions, snapshots, packets, runs, results, and return events locally

## What Was Implemented

### Core package layout

- `src/relay/cli.py`
  - command-line entrypoint for `relay`
- `src/relay/service.py`
  - orchestration layer for agents, sessions, delegation, return, archive, presets
- `src/relay/repository.py`
  - SQLite persistence for all relay entities
- `src/relay/session_host.py`
  - PTY-backed session host for long-lived origin sessions
- `src/relay/session_client.py`
  - Unix socket client used to send input and fetch snapshots from live sessions
- `src/relay/context.py`
  - context capture from transcript, git state, and tree excerpt
- `src/relay/prompts.py`
  - delegate and return prompt builders plus output normalization helpers
- `src/relay/adapters.py`
  - vendor-specific headless command builders for Claude, Codex, Gemini, and Qwen
- `src/relay/tui.py`
  - Textual-based terminal-style TUI with one input, slash commands, and a hidden progress drawer
- `src/relay/workflow_store.py`
  - local JSON-backed storage for saved and active workflows
- `tests/test_repository.py`
  - persistence smoke tests
- `tests/test_service.py`
  - service-level behavior tests

### CLI commands implemented

- `relay tui`
- `relay agent add`
- `relay agent list`
- `relay session open`
- `relay session list`
- `relay session close`
- `relay delegate`
- `relay return`
- `relay inspect run`
- `relay preset list`
- `relay preset run`
- `relay transcript`

### Persistence model implemented

SQLite tables were created for:

- `agents`
- `sessions`
- `context_snapshots`
- `task_packets`
- `runs`
- `run_results`
- `return_events`
- `presets`

### TUI behaviors implemented

- one visible input box at all times
- compact readiness strip for registered AIs
- slash-command overlay opened by `/`
- workflow setup modal shown only when needed
- locally saved linear workflows
- hidden progress drawer toggled on demand
- details modal for raw payloads

## Implementation Timeline

### 1. Project bootstrap

The project was created as a new Python package with a `pyproject.toml`, editable install support, and a Textual dependency for the TUI.

Initial focus:

- get the CLI shape in place
- define the SQLite schema
- create a session host that could keep origin agents alive between commands

### 2. Session host and live origin sessions

The first session-host design used a PTY and a Unix socket so the CLI could:

- open a long-lived origin AI session
- send more input later
- capture transcript excerpts for handoff packets

This established the main mechanism needed for:

- same-session return attempts
- transcript-based context capture

### 3. First end-to-end fake-agent loop

A fake agent script was used to simulate both interactive and headless agents. This enabled the first successful flow:

- open origin session
- send seed context
- delegate to another agent
- normalize the result
- return it to the origin session

This made it possible to validate the orchestrator before spending real model calls.

### 4. CLI and process fixes

Several early issues were found and fixed:

- `python -m relay.cli` did not call `main()` automatically
  - fixed by adding a module main guard
- background session-host handling originally caused process warnings
  - changed to keep child references and then explicitly reap them on session close
- large return payloads could deadlock the PTY write path
  - fixed by making `session_host.py` queue outgoing writes and flush them asynchronously

### 5. Socket path compatibility

On macOS, long Unix socket paths caused session startup failures when `RELAY_HOME` lived under a long temporary directory.

Fix:

- `sockets_dir()` now falls back to a shorter temp path such as `/tmp/relay-sockets` when the default path is too long

### 6. Expanded automated tests

Test coverage was broadened beyond the original happy path. The following behaviors are now covered:

- basic delegate and return roundtrip
- chain delegation with parent run propagation
- default context policy behavior by task type
- fallback normalization when target output is not JSON
- preset-based run execution
- fallback return mode when live session injection fails
- idempotent repeated return calls
- run archiving

### 7. Real CLI verification

The local environment was checked for real binaries. The following were present:

- `claude`
- `codex`
- `gemini` via `npx @google/gemini-cli`
- `qwen` via `npx @qwen-code/qwen-code@latest`

The registered real agent entries were:

- `claude-main`
- `codex-main`
- `gemini-main`

### 8. Real headless verification

Both vendors were tested directly outside the fake-agent harness:

- `Claude`
  - headless structured output succeeded
- `Codex`
  - headless structured output succeeded
- `Gemini`
  - OAuth completed successfully
  - cached credentials were then used for headless JSON output
- `Qwen`
  - OAuth completed successfully
  - headless JSON output then succeeded

This confirmed the adapters were able to reach real vendor CLIs in non-interactive mode.

### 9. Real relay verification and fixes

The orchestrator was then tested with real vendor targets.

#### Real target success cases

Using a fake origin session and real target agents:

- `fake origin -> real Claude target -> origin return`
  - succeeded
- `fake origin -> real Codex target -> origin return`
  - succeeded
- `fake origin -> real Gemini target -> origin return`
  - succeeded
- `fake origin -> real Qwen target -> origin return`
  - succeeded
- `fake origin -> real Gemini(optimize) -> real Qwen(implement) -> origin return`
  - succeeded

This is the strongest current evidence that the relay core works against real vendor targets.

#### Problems found during real testing

1. `Codex` failed outside git repositories
   - error: trusted-directory / git repo restriction
   - fix: always pass `--skip-git-repo-check` in the Codex headless adapter

2. `Codex` schema validation failed with `invalid_json_schema`
   - fix: recursively enforce `additionalProperties: false` for object schemas before passing them to Codex

3. `Codex` interactive origin sessions rejected the environment when `TERM=dumb`
   - fix: when launching a live session, set:
     - `TERM=xterm-256color`
     - `COLORTERM=truecolor`

4. `Claude` interactive origin sessions show a workspace trust prompt
   - result: the PTY-driven session did not automatically progress through the trust UI during testing

5. `Codex` interactive origin sessions still panic under PTY injection
   - even after fixing `TERM`, the interactive Codex TUI crashed in `tui/src/wrapping.rs`
   - this appears to be a vendor TUI compatibility issue with the current PTY transport, not a headless adapter problem

6. `Gemini` and `Qwen` initially failed only because auth was missing
   - both CLIs were reachable before auth was configured
   - once OAuth was completed, both real targets worked through relay

### 10. Authentication work for Gemini and Qwen

After the initial relay core was working, authentication was completed for the remaining target vendors.

#### Gemini

- interactive OAuth was completed through `npx @google/gemini-cli`
- the CLI restarted successfully and showed a signed-in state
- headless mode then succeeded with cached credentials
- relay successfully used Gemini as a real `optimize_prompt` target

#### Qwen

- interactive OAuth was completed through `npx @qwen-code/qwen-code@latest auth qwen-oauth`
- `qwen auth status` then showed an authenticated session
- headless mode succeeded afterward
- relay successfully used Qwen as a real target

### 11. Additional normalization and parser fixes

More real-world output shapes were discovered during Gemini and Qwen testing.

Fixes made:

- Qwen event-array style output is now normalized into a structured result instead of falling back to a plain text blob
- when a target fails and `stderr` is empty, the raw output is now copied into `run.error`
- return prompts compact large nested payloads so origin sessions are less likely to stall on oversized injected results

### 12. Large handoff handling for Codex

Real chaining exposed a practical issue: large Codex handoff packets could take too long or appear hung.

Changes added:

- `run_headless()` now returns a structured timeout result instead of raising
- Codex runs now use a shorter dedicated timeout by default
- if a Codex run times out and the packet was not already compact, relay rewrites the packet to `compact` context and retries once
- compact retry truncates large artifacts such as:
  - git diff
  - git status
  - tree excerpt
  - conversation excerpt
  - parent result payload

This does not solve every Codex latency case, but it gives relay a controlled fallback path instead of waiting indefinitely.

### 13. Claude live-origin investigation

The biggest remaining origin-session problem was real Claude PTY startup.

Work attempted:

- append `--dangerously-skip-permissions` automatically to live Claude launches
- detect the trust prompt inside `session_host.py`
- normalize ANSI-heavy transcript content for prompt detection
- attempt automatic trust confirmation through PTY writes

Current result:

- the trust prompt is still visible in the PTY-backed relay path during testing
- this means real Claude live-origin support is still not considered reliable
- direct manual terminal usage may behave better than the relay PTY transport, but the automated relay path is not solved yet

### 14. Test suite expansion

The test suite was expanded again after the real vendor and PTY investigations.

Additional coverage now includes:

- Claude live-command flag injection
- no duplicate skip-permissions flag
- session-host trust prompt normalization and detection helpers
- Codex timeout -> compact retry behavior

### 15. Terminal-style TUI redesign

The earlier 3-panel developer dashboard was replaced with a CLI-like shell UI.

Key redesign points:

- keep the screen close to Claude/Codex terminal UX
- expose only one input box by default
- move workflow complexity behind a modal and slash commands
- keep execution progress hidden unless explicitly expanded

Implemented pieces:

- top status strip with tiny AI readiness lights
- transcript area plus one bottom input
- slash-command list for:
  - `/workflow`
  - `/workflow new`
  - `/workflow use`
  - `/workflow save`
  - `/workflow off`
  - `/agents`
  - `/login`
  - `/progress`
  - `/help`
- workflow modal with linear step chains instead of a free-form graph
- JSON-backed workflow persistence in `~/.relay/workflow_state.json`

### 16. TUI stability fixes

During live TUI usage, transcript rendering crashed because ANSI control sequences and bracketed text were being interpreted as Textual markup.

Fixes made:

- strip ANSI sequences before display
- render transcript, overlay, progress text, and details as plain `Text` objects
- improve background exception summaries for missing-command failures

This eliminated the earlier `MarkupError` crash path in the transcript area.

### 17. Workflow execution checks and schema fix

A simple real workflow validation was run against the new shell-style TUI engine.

Observed behaviors:

- a temporary `Claude -> Codex Review -> Send Back` workflow initially failed because the review schema passed to Codex did not satisfy the provider's strict nested `required` expectations
- the review schema was updated so nested object properties are fully required, with nullable `file` and `line` fields where appropriate
- a clean simple-question workflow then succeeded:
  - helper origin session
  - `Codex(custom)` target
  - returned result injected back into the origin

Example result:

- prompt: `What is 2 + 2?`
- normalized response: `2 + 2 equals 4.`
- return status: `returned`

This confirmed that the workflow engine, headless target execution, and return path still work after the TUI redesign.

### 18. Local usability improvements

To reduce launch friction:

- a small wrapper script was added at `/Users/family/.local/bin/rr`
- `~/.zshrc` was updated with:
  - `alias rr="$HOME/.local/bin/rr"`

This allows the TUI to be launched with:

```bash
rr tui
```

The saved workflow state was also reset to a cleaner starting point, with:

- no active workflow pinned by default
- a few known-good example workflows stored for reuse

### 19. Direct-mode stabilization and traceability

The shell-style TUI exposed a new class of issues around simple prompts such as `2+2`.

Problems found:

- the app could still reuse a broken legacy active workflow from older experiments
- prompts with no pinned workflow were not always routed cleanly after the first workflow modal
- some providers, especially Qwen, returned event-array payloads that initially rendered as raw JSON in the transcript
- there was no easy way to inspect what happened internally after a direct prompt ran
- old `active` sessions and `running` runs accumulated in the local database from earlier validation

Fixes made:

- legacy self-review workflows are automatically invalidated if they match the old broken pattern
- once the workflow modal has been seen, natural-language prompts without a pinned workflow now use an auto-generated direct workflow
- short prompts can use a faster direct route
  - current preference order for short prompts is:
    - `qwen-main`
    - `gemini-main`
    - `codex-main`
    - `claude-main`
- Qwen event-array output is now normalized by extracting the final `result` text from the event stream
- startup cleanup now:
  - closes stale active sessions when the backing socket is no longer live
  - marks stale queued/running runs as failed
- append-only execution events are now written to:
  - `/Users/family/.relay/events.jsonl`

### 20. Trace UX and build visibility

The TUI was further refined so users can verify both the running build and the latest internal execution path without leaving the main transcript view.

Additions:

- top status strip now shows the build label:
  - `Relay v0.1.0`
- `/trace last` now renders directly into the transcript body instead of only producing transient notices
- trace output was compacted so it fits better in the visible terminal area
- trace timestamps are now shown in local time instead of raw UTC slices

Current compact trace shape:

```text
Last trace:
[20:05:07] prompt  2+2
[20:05:08] start   qwen-main
[20:05:17] done    qwen-main -> 2 + 2 = 4
[20:05:17] final   2 + 2 = 4
```

### 21. Latest validation snapshot

Recent validation confirmed:

- direct prompt without a pinned workflow now works:
  - prompt: `2+2`
  - result: `2 + 2 = 4`
- fast direct routing can choose `qwen-main` successfully
- `/trace last` can show the latest execution trace in the transcript body
- startup cleanup can close stale sessions and fail stale runs
- the top bar displays the running build version

### 22. Copy-friendly shell usage and direct-result hardening

Recent terminal use exposed two final UX issues:

- copy and paste felt unreliable when the TUI refreshed too aggressively
- some direct runs still rendered provider payloads such as raw Qwen event arrays instead of a clean answer

Fixes made:

- the default `rr tui` path now favors a copy-friendly inline launch style
- the shell app reduces unnecessary transcript redraws during idle periods
- direct result extraction was hardened so short prompts such as `2+2` normalize to the final answer text
- `/trace last` is now useful as a transcript-side debugging tool instead of requiring a separate log-file inspection step

Current direct example:

```text
prompt: 2+2
agent: qwen-main
result: 2 + 2 = 4
```

### 23. Approval mode, recommendations, and replay commands

The next shell iteration focused on production-oriented controls rather than additional visual complexity.

Additions:

- `approval_mode` is now persisted in workflow state
- slash commands were added for:
  - `/approval-mode`
  - `/approval-mode <plan|default|auto-edit|yolo>`
  - `/agents`
  - `/rerun last`
  - `/resume last`
- the top bar now shows a visible approval label:
  - `Approval: default`
- providers expose soft `recommended_for` and `experimental_for` metadata instead of hard roles
- `/agents` now reports:
  - readiness
  - recommendation hints
  - experimental notes

This keeps provider placement fully user-controlled while still giving the shell better defaults and clearer operator feedback.

### 24. Slash-command keyboard navigation and true resume

The shell command palette was then refined to reduce typing friction and improve recovery.

Improvements:

- slash-command suggestions now support keyboard selection with:
  - `Up`
  - `Down`
  - `Tab`
- `Enter` can apply the currently highlighted slash command
- `/resume last` is no longer a simple replay alias
  - it now reads execution events to determine completed workflow steps
  - it can skip already completed steps
  - it can carry forward the last completed run as parent context
  - it can retry `send_back` only when the workflow steps succeeded but send-back did not
- resume notices now include failure context when available

This made recovery meaningfully closer to a real resume flow instead of a full rerun.

### 25. Relay-as-switchboard direct mode

The shell was then pushed closer to a true relay model instead of acting like a second assistant layered on top of the vendors.

Changes made:

- `main_provider` is now persisted separately from workflow state
- slash commands were added for:
  - `/provider`
  - `/provider use <name>`
- direct prompts now go to the selected provider instead of using hidden heuristic switching as the main path
- direct output now prefers the vendor's own answer text
- normalization in direct mode is limited to transport cleanup:
  - event wrapper extraction
  - raw provider payload cleanup
  - ANSI-safe display shaping

This made direct chat feel more like talking to the chosen provider and less like talking to relay.

### 26. Transcript quieting, thinking state, and workflow layering

As the TUI became the main surface, transcript behavior was refined to make relay less intrusive while still keeping orchestration transparent.

Direct-chat changes:

- relay notices were categorized into:
  - `system`
  - `hint`
  - `command`
  - `error`
  - `status`
- normal chat now hides most relay notices once a real answer body exists
- direct completion no longer prepends `Workflow finished: ...` into the visible transcript
- a short `Thinking with <provider>...` indicator appears while a provider is running
- longer answers are revealed progressively so the shell feels closer to Claude/Codex style output

Workflow transcript changes:

- workflow runs now render layered blocks directly into the main transcript
- successful runs can show:
  - `[Original - <main provider>]`
  - `[Step Label - <step provider>]`
  - `[Final - <main provider>]`
- failed runs now show:
  - `[Step Label - <step provider> (Failed)]`
  - `[Workflow Status]`

This solved the earlier problem where users could see only a final summary and not the original output, intermediate review/build output, and failure state.

### 27. Workflow modal usability and provider/workflow distinction

Real use of the workflow modal exposed usability problems on smaller terminals.

Fixes made:

- workflow rows were compressed into shorter horizontal step rows
- top action buttons were added:
  - `Run Once`
  - `Save & Use`
  - `Cancel`
- the modal now uses bounded height with scrolling so action buttons do not disappear below the screen
- initial focus is now placed on the main-agent selector so arrow-key selection works immediately

Another confusion found during validation was that direct provider state and workflow-main state could differ.

To make that explicit:

- the top bar now shows:
  - `Provider: <direct main provider>`
  - `Workflow Main: <pinned workflow main provider>`

This makes it clear why a transcript can begin with `[Original - gemini-main]` while the direct provider still says `claude-main`.

### 28. Real Gemini shell validation and Codex timeout behavior

Recent real-world tests focused on the current shell UX rather than only the older fake-origin harness.

Validated success cases:

- real `gemini-main` direct prompt in the shell:
  - succeeded
  - transcript showed prompt plus Gemini answer
- real layered workflow:
  - `Original - gemini-main`
  - `Custom - codex-main`
  - `Final - gemini-main`
  - succeeded end-to-end

Validated failure case:

- pinned workflow:
  - `Gemini -> Codex Build -> Send Back`
- observed behavior:
  - Gemini original generation succeeded
  - Codex `implement` step started
  - Codex `implement` timed out after 60 seconds
  - transcript showed:
    - `[Build - codex-main (Failed)]`
    - `[Workflow Status]`

This confirmed that:

- Gemini was not the only provider running
- Codex was invoked correctly
- the current failure mode is a timeout on a heavier `implement` step, not a missing handoff

## Current Validation Status

### Automated validation

Command used:

```bash
cd /Users/family/jason/relay
. .venv/bin/activate
PYTHONPATH=src python -m unittest discover -s tests -v
```

Current result:

```text
Ran 63 tests
OK
```

### Real workflow spot checks

Additional direct spot checks beyond the automated suite:

- `relay tui` launches successfully in a real PTY
- slash overlay opens on `/`
- first natural-language prompt opens the workflow modal
- simple helper-origin workflow succeeds end-to-end
- direct prompt without a pinned workflow succeeds in the terminal shell UI
  - prompt: `2+2`
  - result: `2 + 2 = 4`
- `/trace last` renders a compact local-time execution summary into the transcript body
- `/approval-mode`, `/agents`, `/rerun last`, and `/resume last` all have direct TUI test coverage
- slash commands can be selected with keyboard navigation instead of full typing
- `/resume last` can skip completed workflow steps and recover send-back-only failures
- direct provider switching now works through `/provider` and `/provider use ...`
- workflow transcript output now shows layered `Original / step / Final` blocks by default
- real Gemini main-provider validation succeeded
- real Gemini -> Codex custom workflow validation succeeded
- real Gemini -> Codex implement workflow validation currently fails by timeout, and that failure is now visible inline

## Current Known Limitations

- saved review workflows still need a better handoff payload if the goal is to review the main AI's actual answer text rather than just the question/context
- real Claude PTY-origin sessions remain noisy because workspace trust flows still bleed into the captured transcript
- some old long-lived test sessions and runs remain in the local relay database from prior validation

## Recommended Next Work

If development continues, the highest-value next items are:

1. improve heavy Codex workflow steps
   - reduce implement payload weight
   - tune timeout and retry behavior
   - consider safer default presets than `Gemini -> Codex Build`

2. add vendor-specific origin strategies
   - Claude origin strategy
   - Codex origin strategy

3. distinguish more clearly between:
   - headless target compatibility
   - interactive origin compatibility

4. optionally expose compatibility status in the UI
   - example: show whether an agent is recommended for `target`, `origin`, or `both`

5. keep reducing prompt weight
   - omit empty artifact sections in delegate prompts
   - omit empty parent-result sections
   - summarize large diffs before Codex retry

## Short README Candidate

If this needs to be collapsed into a shorter README section later, the following summary is a good starting point:

> `relay` is a local multi-AI handoff orchestrator for Claude, Codex, Gemini, and Qwen. It can register agents, open origin sessions, capture context, delegate tasks headlessly, return results to the origin session, and run a shell-style Textual TUI with one input, slash commands, provider switching, and layered workflow transcripts.  
>  
> Current validation shows real headless target delegation works with Claude, Codex, Gemini, and Qwen, direct Gemini shell prompts work, and a real layered `Gemini -> Codex(custom) -> Send Back` flow has completed successfully. The remaining work is mainly around heavier Codex implement timeouts and vendor-specific handling for real interactive origin sessions, especially Claude workspace trust prompts and Codex PTY/TUI stability.

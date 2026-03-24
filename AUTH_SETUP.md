# relay Auth Setup

This is a focused auth reference.

For the broader current-state and document map, see:

- [Docs Hub](/Users/family/jason/relay/docs/README.md)
- [Project Status](/Users/family/jason/relay/docs/status/PROJECT-STATUS.md)
- [Architecture](/Users/family/jason/relay/docs/ref/ARCHITECTURE.md)

This file records the current authentication setup status for real Gemini and Qwen target testing.

## Current state

- `Claude`: available and authenticated enough for real headless testing
- `Codex`: available and authenticated enough for real headless testing
- `Gemini`: CLI available, OAuth completed, real headless testing succeeded
- `Qwen`: CLI available, OAuth completed, real headless testing succeeded

## Gemini setup

Current template file:

- `/Users/family/.gemini/.env`

Edit that file and uncomment one option.

### Option 1: Gemini API key

```bash
GEMINI_API_KEY="YOUR_GEMINI_API_KEY"
```

### Option 2: Vertex AI

```bash
GOOGLE_GENAI_USE_VERTEXAI=true
GOOGLE_CLOUD_PROJECT="YOUR_GCP_PROJECT"
GOOGLE_CLOUD_LOCATION="global"
GOOGLE_API_KEY="YOUR_GOOGLE_API_KEY"
```

After editing, test with:

```bash
npx @google/gemini-cli -p 'Return JSON only: {"ok":true}' --output-format json
```

Current note:

- Gemini OAuth was completed interactively and cached credentials are now being used successfully for headless calls in this environment

## Qwen setup

Template files created:

- `/Users/family/.qwen/settings.gemini-template.json`
- `/Users/family/.qwen/settings.qwen-template.json`

Recommended paths:

1. If using Gemini as the provider inside Qwen:

```bash
cp /Users/family/.qwen/settings.gemini-template.json /Users/family/.qwen/settings.json
```

This expects `GEMINI_API_KEY` to be available in your shell or environment.

2. If using native Qwen OAuth:

```bash
npx @qwen-code/qwen-code@latest auth qwen-oauth
```

Or start from:

```bash
cp /Users/family/.qwen/settings.qwen-template.json /Users/family/.qwen/settings.json
```

Then complete auth interactively if needed.

After configuration, test with:

```bash
npx @qwen-code/qwen-code@latest -p 'Return JSON only: {"ok":true}' --output-format json
```

Current note:

- Qwen OAuth was completed interactively and headless calls now work in this environment

## relay validation status after auth

The following real vendor checks have now succeeded:

- Gemini headless JSON output
- Qwen headless JSON output
- `fake origin -> real Gemini target -> return`
- `fake origin -> real Qwen target -> return`
- `fake origin -> real Gemini(optimize) -> real Qwen(implement) -> return`

## relay retest commands

After auth changes or local credential expiration, rerun:

```bash
cd /Users/family/jason/relay
. .venv/bin/activate
PYTHONPATH=src python -m unittest discover -s tests -v
```

Current automated suite result:

```text
Ran 35 tests
OK
```

Then re-run real relay smoke for the newly configured target.

## Current launch shortcut

For day-to-day usage, this machine now has:

- `/Users/family/.local/bin/rr`
- `alias rr="$HOME/.local/bin/rr"` in `~/.zshrc`

So a fresh shell can launch relay with:

```bash
rr tui
```

Current note:

- the shell UI now shows the running build label in the top bar, for example `Relay v0.1.0`
- `/trace last` can be used inside the TUI to inspect the latest internal execution path after a real prompt run

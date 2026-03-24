from __future__ import annotations

import os
import tempfile
from pathlib import Path


APP_DIR_NAME = "relay"


def relay_home() -> Path:
    raw = os.environ.get("RELAY_HOME")
    if raw:
        home = Path(raw).expanduser().resolve()
    else:
        home = Path.home() / ".relay"
    home.mkdir(parents=True, exist_ok=True)
    return home


def db_path() -> Path:
    return relay_home() / "relay.db"


def sockets_dir() -> Path:
    raw = os.environ.get("RELAY_SOCKETS_DIR")
    if raw:
        path = Path(raw).expanduser().resolve()
    else:
        default_path = relay_home() / "sockets"
        if len(str(default_path)) > 70:
            path = Path(tempfile.gettempdir()) / "relay-sockets"
        else:
            path = default_path
    path.mkdir(parents=True, exist_ok=True)
    return path


def transcripts_dir() -> Path:
    path = relay_home() / "transcripts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def workflow_state_path() -> Path:
    return relay_home() / "workflow_state.json"


def exports_dir() -> Path:
    path = relay_home() / "exports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def events_log_path() -> Path:
    return relay_home() / "events.jsonl"

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional

from relay.config import db_path
from relay.ids import next_id
from relay.schemas import PRESETS


def _utc_now() -> str:
    import datetime as _dt

    return _dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


class RelayRepository:
    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path or db_path())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS agents (
                    id TEXT PRIMARY KEY,
                    name TEXT UNIQUE NOT NULL,
                    kind TEXT NOT NULL,
                    launch_command TEXT NOT NULL,
                    resume_strategy TEXT NOT NULL,
                    supports_json TEXT NOT NULL,
                    default_output_mode TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    label TEXT NOT NULL,
                    cwd TEXT NOT NULL,
                    external_session_ref TEXT NOT NULL,
                    status TEXT NOT NULL,
                    last_context_snapshot_id TEXT,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS context_snapshots (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    goal TEXT NOT NULL,
                    task_type_hint TEXT NOT NULL,
                    artifacts_json TEXT NOT NULL,
                    token_estimate INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS task_packets (
                    id TEXT PRIMARY KEY,
                    origin_session_id TEXT NOT NULL,
                    target_agent_id TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    context_policy TEXT NOT NULL,
                    instructions TEXT NOT NULL,
                    origin_snapshot_id TEXT NOT NULL,
                    input_payload_json TEXT NOT NULL,
                    parent_run_id TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    packet_id TEXT NOT NULL,
                    origin_session_id TEXT NOT NULL,
                    target_session_id TEXT,
                    status TEXT NOT NULL,
                    return_status TEXT NOT NULL,
                    archived INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS run_results (
                    run_id TEXT PRIMARY KEY,
                    raw_output TEXT NOT NULL,
                    normalized_result_json TEXT NOT NULL,
                    output_schema TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS return_events (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    origin_session_id TEXT NOT NULL,
                    attempt_mode TEXT NOT NULL,
                    final_mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    injected_prompt TEXT NOT NULL,
                    fallback_output TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS presets (
                    id TEXT PRIMARY KEY,
                    name TEXT UNIQUE NOT NULL,
                    task_type TEXT NOT NULL,
                    default_context_policy TEXT NOT NULL,
                    required_output_schema TEXT NOT NULL,
                    instruction_template TEXT NOT NULL
                );
                """
            )
            for preset in PRESETS:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO presets
                    (id, name, task_type, default_context_policy, required_output_schema, instruction_template)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        preset["id"],
                        preset["name"],
                        preset["task_type"],
                        preset["default_context_policy"],
                        preset["required_output_schema"],
                        preset["instruction_template"],
                    ),
                )

    def _json(self, value: Any) -> str:
        return json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True)

    def _row_to_dict(self, row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
        if row is None:
            return None
        item = dict(row)
        for key in list(item.keys()):
            if key.endswith("_json"):
                parsed_key = key[:-5]
                item[parsed_key] = json.loads(item.pop(key))
        if "supports_json" in item:
            item["supports"] = json.loads(item.pop("supports_json"))
        return item

    def list_agents(self) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM agents ORDER BY created_at ASC").fetchall()
        return [self._row_to_dict(row) for row in rows]

    def get_agent(self, *, name: Optional[str] = None, agent_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        query = None
        value = None
        if name:
            query = "SELECT * FROM agents WHERE name = ?"
            value = name
        elif agent_id:
            query = "SELECT * FROM agents WHERE id = ?"
            value = agent_id
        else:
            raise ValueError("name or agent_id is required")
        with self.connect() as conn:
            row = conn.execute(query, (value,)).fetchone()
        return self._row_to_dict(row)

    def add_agent(
        self,
        *,
        name: str,
        kind: str,
        launch_command: str,
        resume_strategy: str,
        supports: Dict[str, Any],
        default_output_mode: str = "json",
    ) -> Dict[str, Any]:
        with self.connect() as conn:
            agent_id = next_id(conn, "agent")
            created_at = _utc_now()
            conn.execute(
                """
                INSERT INTO agents
                (id, name, kind, launch_command, resume_strategy, supports_json, default_output_mode, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    agent_id,
                    name,
                    kind,
                    launch_command,
                    resume_strategy,
                    self._json(supports),
                    default_output_mode,
                    created_at,
                ),
            )
        return self.get_agent(agent_id=agent_id)  # type: ignore[return-value]

    def list_sessions(self) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM sessions ORDER BY updated_at DESC").fetchall()
        return [self._row_to_dict(row) for row in rows]

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return self._row_to_dict(row)

    def add_session(
        self,
        *,
        agent_id: str,
        label: str,
        cwd: str,
        external_session_ref: str,
        status: str,
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        with self.connect() as conn:
            session_id = next_id(conn, "sess")
            now = _utc_now()
            conn.execute(
                """
                INSERT INTO sessions
                (id, agent_id, label, cwd, external_session_ref, status, last_context_snapshot_id, metadata_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, ?)
                """,
                (
                    session_id,
                    agent_id,
                    label,
                    cwd,
                    external_session_ref,
                    status,
                    self._json(metadata),
                    now,
                    now,
                ),
            )
        return self.get_session(session_id)  # type: ignore[return-value]

    def update_session(self, session_id: str, **fields: Any) -> Dict[str, Any]:
        if not fields:
            return self.get_session(session_id)  # type: ignore[return-value]
        sets = []
        values = []
        for key, value in fields.items():
            column = "metadata_json" if key == "metadata" else key
            sets.append(f"{column} = ?")
            if key == "metadata":
                values.append(self._json(value))
            else:
                values.append(value)
        sets.append("updated_at = ?")
        values.append(_utc_now())
        values.append(session_id)
        with self.connect() as conn:
            conn.execute(f"UPDATE sessions SET {', '.join(sets)} WHERE id = ?", tuple(values))
        return self.get_session(session_id)  # type: ignore[return-value]

    def add_context_snapshot(
        self,
        *,
        session_id: str,
        summary: str,
        goal: str,
        task_type_hint: str,
        artifacts: Dict[str, Any],
        token_estimate: int,
    ) -> Dict[str, Any]:
        with self.connect() as conn:
            snapshot_id = next_id(conn, "snap")
            conn.execute(
                """
                INSERT INTO context_snapshots
                (id, session_id, summary, goal, task_type_hint, artifacts_json, token_estimate, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    session_id,
                    summary,
                    goal,
                    task_type_hint,
                    self._json(artifacts),
                    token_estimate,
                    _utc_now(),
                ),
            )
            conn.execute(
                "UPDATE sessions SET last_context_snapshot_id = ?, updated_at = ? WHERE id = ?",
                (snapshot_id, _utc_now(), session_id),
            )
            row = conn.execute("SELECT * FROM context_snapshots WHERE id = ?", (snapshot_id,)).fetchone()
        return self._row_to_dict(row)  # type: ignore[return-value]

    def get_snapshot(self, snapshot_id: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM context_snapshots WHERE id = ?", (snapshot_id,)).fetchone()
        return self._row_to_dict(row)

    def add_task_packet(
        self,
        *,
        origin_session_id: str,
        target_agent_id: str,
        task_type: str,
        title: str,
        context_policy: str,
        instructions: str,
        origin_snapshot_id: str,
        input_payload: Dict[str, Any],
        parent_run_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self.connect() as conn:
            packet_id = next_id(conn, "pkt")
            conn.execute(
                """
                INSERT INTO task_packets
                (id, origin_session_id, target_agent_id, task_type, title, context_policy, instructions, origin_snapshot_id, input_payload_json, parent_run_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    packet_id,
                    origin_session_id,
                    target_agent_id,
                    task_type,
                    title,
                    context_policy,
                    instructions,
                    origin_snapshot_id,
                    self._json(input_payload),
                    parent_run_id,
                    _utc_now(),
                ),
            )
            row = conn.execute("SELECT * FROM task_packets WHERE id = ?", (packet_id,)).fetchone()
        return self._row_to_dict(row)  # type: ignore[return-value]

    def get_task_packet(self, packet_id: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM task_packets WHERE id = ?", (packet_id,)).fetchone()
        return self._row_to_dict(row)

    def update_task_packet(self, packet_id: str, **fields: Any) -> Dict[str, Any]:
        if not fields:
            return self.get_task_packet(packet_id)  # type: ignore[return-value]
        sets = []
        values = []
        for key, value in fields.items():
            column = "input_payload_json" if key == "input_payload" else key
            sets.append(f"{column} = ?")
            if key == "input_payload":
                values.append(self._json(value))
            else:
                values.append(value)
        values.append(packet_id)
        with self.connect() as conn:
            conn.execute(f"UPDATE task_packets SET {', '.join(sets)} WHERE id = ?", tuple(values))
        return self.get_task_packet(packet_id)  # type: ignore[return-value]

    def add_run(self, *, packet_id: str, origin_session_id: str, status: str, return_status: str) -> Dict[str, Any]:
        with self.connect() as conn:
            run_id = next_id(conn, "run")
            now = _utc_now()
            conn.execute(
                """
                INSERT INTO runs
                (id, packet_id, origin_session_id, target_session_id, status, return_status, archived, error, started_at, completed_at, created_at)
                VALUES (?, ?, ?, NULL, ?, ?, 0, NULL, ?, NULL, ?)
                """,
                (run_id, packet_id, origin_session_id, status, return_status, now, now),
            )
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return self._row_to_dict(row)  # type: ignore[return-value]

    def list_runs(self) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM runs ORDER BY created_at DESC").fetchall()
        return [self._row_to_dict(row) for row in rows]

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return self._row_to_dict(row)

    def update_run(self, run_id: str, **fields: Any) -> Dict[str, Any]:
        if not fields:
            return self.get_run(run_id)  # type: ignore[return-value]
        sets = []
        values = []
        for key, value in fields.items():
            sets.append(f"{key} = ?")
            values.append(value)
        values.append(run_id)
        with self.connect() as conn:
            conn.execute(f"UPDATE runs SET {', '.join(sets)} WHERE id = ?", tuple(values))
        return self.get_run(run_id)  # type: ignore[return-value]

    def save_run_result(
        self,
        *,
        run_id: str,
        raw_output: str,
        normalized_result: Dict[str, Any],
        output_schema: str,
    ) -> Dict[str, Any]:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO run_results
                (run_id, raw_output, normalized_result_json, output_schema, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (run_id, raw_output, self._json(normalized_result), output_schema, _utc_now()),
            )
            row = conn.execute("SELECT * FROM run_results WHERE run_id = ?", (run_id,)).fetchone()
        return self._row_to_dict(row)  # type: ignore[return-value]

    def get_run_result(self, run_id: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM run_results WHERE run_id = ?", (run_id,)).fetchone()
        return self._row_to_dict(row)

    def add_return_event(
        self,
        *,
        run_id: str,
        origin_session_id: str,
        attempt_mode: str,
        final_mode: str,
        status: str,
        injected_prompt: str,
        fallback_output: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self.connect() as conn:
            event_id = next_id(conn, "ret")
            conn.execute(
                """
                INSERT INTO return_events
                (id, run_id, origin_session_id, attempt_mode, final_mode, status, injected_prompt, fallback_output, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    run_id,
                    origin_session_id,
                    attempt_mode,
                    final_mode,
                    status,
                    injected_prompt,
                    fallback_output,
                    _utc_now(),
                ),
            )
            row = conn.execute("SELECT * FROM return_events WHERE id = ?", (event_id,)).fetchone()
        return self._row_to_dict(row)  # type: ignore[return-value]

    def list_presets(self) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM presets ORDER BY name ASC").fetchall()
        return [dict(row) for row in rows]

    def get_preset(self, preset_id_or_name: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM presets WHERE id = ? OR name = ?",
                (preset_id_or_name, preset_id_or_name),
            ).fetchone()
        return dict(row) if row else None

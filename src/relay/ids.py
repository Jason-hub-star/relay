from __future__ import annotations

import secrets
import sqlite3


PREFIX_TO_TABLE = {
    "agent": "agents",
    "sess": "sessions",
    "snap": "context_snapshots",
    "pkt": "task_packets",
    "run": "runs",
    "ret": "return_events",
}


def next_id(conn: sqlite3.Connection, prefix: str) -> str:
    table = PREFIX_TO_TABLE[prefix]
    row = conn.execute(
        f"SELECT id FROM {table} WHERE id LIKE ? ORDER BY id DESC LIMIT 1",
        (f"{prefix}_%",),
    ).fetchone()
    if row is None:
        return f"{prefix}_0001"
    current = int(str(row[0]).split("_")[-1])
    return f"{prefix}_{current + 1:04d}"


def random_suffix(length: int = 8) -> str:
    alphabet = "abcdefghijklmnopqrstuvwxyz0123456789"
    return "".join(alphabet[byte % len(alphabet)] for byte in secrets.token_bytes(length))[:length]

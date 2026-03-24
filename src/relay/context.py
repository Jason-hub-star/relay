from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List

from relay.models import ContextPolicy, TaskType
from relay.session_client import SessionClient


def _run(command: List[str], cwd: str) -> str:
    try:
        proc = subprocess.run(
            command,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return ""
    return (proc.stdout or proc.stderr or "").strip()


def _git_artifacts(cwd: str) -> Dict[str, Any]:
    if not Path(cwd, ".git").exists():
        return {
            "files": [],
            "git_diff": "",
            "git_status": "",
        }
    files = _run(["git", "diff", "--name-only", "HEAD"], cwd).splitlines()
    diff = _run(["git", "diff", "--staged", "--no-ext-diff"], cwd)
    if not diff:
        diff = _run(["git", "diff", "--no-ext-diff"], cwd)
    status = _run(["git", "status", "--short"], cwd)
    return {
        "files": [item for item in files if item],
        "git_diff": diff,
        "git_status": status,
    }


def _tree_excerpt(cwd: str, max_entries: int = 60) -> str:
    base = Path(cwd)
    lines: List[str] = []
    count = 0
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in {".git", "__pycache__", ".venv", "node_modules"}]
        rel_root = Path(root).relative_to(base)
        depth = len(rel_root.parts)
        if depth > 2:
            dirs[:] = []
            continue
        prefix = "  " * depth
        lines.append(f"{prefix}{rel_root if str(rel_root) != '.' else '.'}/")
        count += 1
        for file_name in sorted(files)[:8]:
            lines.append(f"{prefix}  {file_name}")
            count += 1
            if count >= max_entries:
                return "\n".join(lines)
        if count >= max_entries:
            break
    return "\n".join(lines)


def _compact_transcript(text: str, policy: ContextPolicy) -> str:
    limit = {
        ContextPolicy.COMPACT: 1800,
        ContextPolicy.RICH: 5000,
        ContextPolicy.FULL: 12000,
    }[policy]
    cleaned = text.strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[-limit:]


def _guess_goal(session_label: str, transcript: str, task_type: TaskType) -> str:
    lines = [line.strip() for line in transcript.splitlines() if line.strip()]
    last_line = lines[-1] if lines else session_label
    return f"{task_type.value} task from session '{session_label}': {last_line[:240]}"


def capture_context_snapshot(
    *,
    session: Dict[str, Any],
    task_type: TaskType,
    context_policy: ContextPolicy,
) -> Dict[str, Any]:
    client = SessionClient(session["external_session_ref"])
    snapshot = client.snapshot()
    transcript = snapshot.get("transcript", "")
    transcript_excerpt = _compact_transcript(transcript, context_policy)
    cwd = session["cwd"]
    git_artifacts = _git_artifacts(cwd)
    tree_excerpt = _tree_excerpt(cwd)
    summary = transcript_excerpt.splitlines()[-1] if transcript_excerpt else session["label"]
    goal = _guess_goal(session["label"], transcript_excerpt, task_type)
    artifacts = {
        "files": git_artifacts["files"],
        "git_diff": git_artifacts["git_diff"],
        "git_status": git_artifacts["git_status"],
        "tree_excerpt": tree_excerpt,
        "conversation_excerpt": transcript_excerpt,
        "attachments": [],
    }
    token_estimate = max(1, len(str(artifacts)) // 4)
    return {
        "summary": summary[:500],
        "goal": goal,
        "task_type_hint": task_type.value,
        "artifacts": artifacts,
        "token_estimate": token_estimate,
    }

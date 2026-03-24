from __future__ import annotations

import json
import os
import shlex
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from relay.session_client import SessionClient


@dataclass
class CommandResult:
    stdout: str
    stderr: str
    returncode: int


@dataclass
class ReadinessResult:
    status: str
    message: str
    details: str
    login_command: list[str]


def _base_command(launch_command: str) -> List[str]:
    return shlex.split(launch_command)


def _command_env() -> dict[str, str]:
    env = os.environ.copy()
    path_parts = ["/opt/homebrew/bin", "/usr/local/bin"]
    current_path = env.get("PATH", "")
    for part in reversed(path_parts):
        if part not in current_path.split(":"):
            current_path = f"{part}:{current_path}" if current_path else part
    env["PATH"] = current_path
    if not env.get("TERM") or env.get("TERM") == "dumb":
        env["TERM"] = "xterm-256color"
    env.setdefault("COLORTERM", "truecolor")
    return env


def build_live_command(agent: Dict[str, str]) -> List[str]:
    command = _base_command(agent["launch_command"])
    if agent["kind"] == "claude" and "--dangerously-skip-permissions" not in command:
        command.append("--dangerously-skip-permissions")
    return command


def build_login_command(agent: Dict[str, str]) -> List[str]:
    base = _base_command(agent["launch_command"])
    kind = agent["kind"]
    if kind == "qwen":
        return base + ["auth", "qwen-oauth"]
    return build_live_command(agent)


def _schema_file(schema: Dict[str, Any]) -> str:
    handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    with handle:
        json.dump(schema, handle, ensure_ascii=True, indent=2)
    return handle.name


def build_headless_command(
    agent: Dict[str, str],
    prompt: str,
    output_schema: Optional[Dict[str, Any]] = None,
    *,
    raw_output: bool = False,
) -> List[str]:
    base = _base_command(agent["launch_command"])
    kind = agent["kind"]
    if kind == "codex":
        command = base + ["exec", "--skip-git-repo-check"]
        if output_schema and not raw_output:
            command += ["--output-schema", _schema_file(output_schema)]
        command += [prompt]
        return command
    if kind == "claude":
        command = base + ["-p", prompt]
        if not raw_output:
            command += ["--output-format", "json"]
        if output_schema and not raw_output:
            command += ["--json-schema", json.dumps(output_schema, ensure_ascii=True)]
        return command
    if kind == "gemini":
        command = base + ["-p", prompt]
        if not raw_output:
            command += ["--output-format", "json"]
        return command
    if kind == "qwen":
        command = base + ["-p", prompt]
        if not raw_output:
            command += ["--output-format", "json"]
        return command
    raise ValueError(f"unsupported agent kind: {kind}")


def run_headless(
    agent: Dict[str, str],
    prompt: str,
    cwd: str,
    timeout: int = 900,
    output_schema: Optional[Dict[str, Any]] = None,
    *,
    raw_output: bool = False,
) -> CommandResult:
    command = build_headless_command(agent, prompt, output_schema=output_schema, raw_output=raw_output)
    env = _command_env()
    try:
        proc = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=env,
        )
        return CommandResult(stdout=proc.stdout, stderr=proc.stderr, returncode=proc.returncode)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        message = f"relay headless timeout after {timeout}s"
        stderr = f"{stderr}\n{message}".strip() if stderr else message
        return CommandResult(stdout=stdout, stderr=stderr, returncode=124)


def run_command(
    command: List[str],
    *,
    cwd: str,
    timeout: int = 30,
    capture_output: bool = True,
) -> CommandResult:
    env = _command_env()
    try:
        proc = subprocess.run(
            command,
            cwd=cwd,
            capture_output=capture_output,
            text=True,
            timeout=timeout,
            check=False,
            env=env,
        )
        return CommandResult(stdout=proc.stdout or "", stderr=proc.stderr or "", returncode=proc.returncode)
    except FileNotFoundError as exc:
        return CommandResult(stdout="", stderr=str(exc), returncode=127)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        message = f"command timed out after {timeout}s"
        stderr = f"{stderr}\n{message}".strip() if stderr else message
        return CommandResult(stdout=stdout, stderr=stderr, returncode=124)


def check_agent_readiness(agent: Dict[str, str], *, cwd: str) -> ReadinessResult:
    kind = agent["kind"]
    if kind == "gemini":
        result = run_command(
            build_headless_command(agent, 'Return JSON only: {"ok":true}'),
            cwd=cwd,
            timeout=45,
        )
        text = f"{result.stdout}\n{result.stderr}".strip()
        if result.returncode == 0:
            return ReadinessResult("ready", "Signed in and ready to use.", text, build_login_command(agent))
        if _looks_like_login_issue(text):
            return ReadinessResult("needs_login", "Please sign in to Gemini.", text, build_login_command(agent))
        return ReadinessResult("unavailable", "Gemini is unavailable right now.", text or "Gemini check failed.", [])
    if kind == "qwen":
        result = run_command(_base_command(agent["launch_command"]) + ["auth", "status"], cwd=cwd, timeout=20)
        text = f"{result.stdout}\n{result.stderr}".strip()
        lowered = text.lower()
        if "authentication method" in lowered and "no authentication method configured" not in lowered:
            return ReadinessResult("ready", "Signed in and ready to use.", text, build_login_command(agent))
        if "no authentication method configured" in lowered or _looks_like_login_issue(text):
            return ReadinessResult("needs_login", "Please sign in to Qwen.", text, build_login_command(agent))
        return ReadinessResult("unavailable", "Qwen is unavailable right now.", text or "Qwen check failed.", [])
    sanity = run_command(_base_command(agent["launch_command"]) + ["--version"], cwd=cwd, timeout=20)
    text = f"{sanity.stdout}\n{sanity.stderr}".strip()
    if sanity.returncode == 0:
        return ReadinessResult("ready", "Ready to use.", text, build_login_command(agent))
    if _looks_like_login_issue(text):
        return ReadinessResult("needs_login", f"Please sign in to {agent['name']}.", text, build_login_command(agent))
    return ReadinessResult("unavailable", f"{agent['name']} is unavailable right now.", text or "Sanity check failed.", [])


def launch_login_flow(agent: Dict[str, str], *, cwd: str) -> CommandResult:
    return run_command(build_login_command(agent), cwd=cwd, timeout=3600, capture_output=False)


def _looks_like_login_issue(text: str) -> bool:
    lowered = text.lower()
    markers = [
        "sign in",
        "sign-in",
        "authentication",
        "authenticate",
        "api key",
        "cached credentials",
        "oauth",
        "login",
        "log in",
        "no authentication method configured",
    ]
    return any(marker in lowered for marker in markers)


def send_to_live_session(session: Dict[str, str], prompt: str) -> bool:
    try:
        client = SessionClient(session["external_session_ref"])
        response = client.send(prompt)
        return bool(response.get("ok"))
    except OSError:
        return False

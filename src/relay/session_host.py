from __future__ import annotations

import argparse
import collections
import json
import os
import re
import selectors
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Deque, List


ANSI_ESCAPE_RE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~]|\].*?(?:\x07|\x1b\\))")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="relay session host")
    parser.add_argument("--socket-path", required=True)
    parser.add_argument("--log-path", required=True)
    parser.add_argument("--cwd", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser.parse_args()


def _extract_command(args: argparse.Namespace) -> List[str]:
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise SystemExit("session host requires a command")
    return command


def _normalize_terminal_text(text: str) -> str:
    return ANSI_ESCAPE_RE.sub("", text)


def _should_auto_accept_trust(command: List[str], transcript: str) -> bool:
    normalized_command = " ".join(command).lower()
    if "claude" not in normalized_command:
        return False
    cleaned = _normalize_terminal_text(transcript).lower()
    squashed = "".join(char for char in cleaned if char.isalnum())
    markers = [
        "quicksafetycheck",
        "trustthisfolder",
        "entertoconfirm",
    ]
    return all(marker in squashed for marker in markers)


def main() -> None:
    args = _parse_args()
    command = _extract_command(args)
    socket_path = Path(args.socket_path)
    log_path = Path(args.log_path)
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if socket_path.exists():
        socket_path.unlink()

    master_fd, slave_fd = os.openpty()
    proc = subprocess.Popen(
        command,
        cwd=args.cwd,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        start_new_session=True,
        text=False,
    )
    os.close(slave_fd)
    os.set_blocking(master_fd, False)

    transcript_tail: Deque[str] = collections.deque(maxlen=400)
    selector = selectors.DefaultSelector()
    selector.register(master_fd, selectors.EVENT_READ, "pty")
    pending_write = bytearray()
    auto_trust_attempts = 0
    last_auto_trust_at = 0.0

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(socket_path))
    server.listen(5)
    selector.register(server, selectors.EVENT_READ, "server")

    running = True

    def write_log(text: str) -> None:
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(text)

    def capture_payload() -> str:
        return "".join(transcript_tail)

    def queue_input(text: str, *, prepend: bool = False, carriage_return: bool = False) -> None:
        terminator = "\r" if carriage_return else "\n"
        payload = (text.rstrip("\n\r") + terminator).encode("utf-8")
        if prepend:
            pending_write[:0] = payload
        else:
            pending_write.extend(payload)
        selector.modify(master_fd, selectors.EVENT_READ | selectors.EVENT_WRITE, "pty")

    def maybe_auto_accept_trust() -> None:
        nonlocal auto_trust_attempts, last_auto_trust_at
        if auto_trust_attempts >= 3:
            return
        if time.time() - last_auto_trust_at < 1.0:
            return
        if _should_auto_accept_trust(command, capture_payload()):
            try:
                os.write(master_fd, b"1\r")
            except BlockingIOError:
                queue_input("1", prepend=True, carriage_return=True)
            auto_trust_attempts += 1
            last_auto_trust_at = time.time()

    while running:
        if proc.poll() is not None:
            running = False
        events = selector.select(timeout=0.2)
        for key, mask in events:
            if key.data == "pty":
                if mask & selectors.EVENT_READ:
                    try:
                        data = os.read(master_fd, 4096)
                    except BlockingIOError:
                        data = b""
                    except OSError:
                        data = b""
                    if data:
                        text = data.decode("utf-8", errors="replace")
                        transcript_tail.append(text)
                        write_log(text)
                        maybe_auto_accept_trust()
                if mask & selectors.EVENT_WRITE and pending_write:
                    try:
                        written = os.write(master_fd, pending_write[:1024])
                    except BlockingIOError:
                        written = 0
                    if written > 0:
                        del pending_write[:written]
                    if not pending_write:
                        selector.modify(master_fd, selectors.EVENT_READ, "pty")
            elif key.data == "server":
                conn, _addr = server.accept()
                with conn:
                    raw = b""
                    while True:
                        chunk = conn.recv(65536)
                        if not chunk:
                            break
                        raw += chunk
                    try:
                        request = json.loads(raw.decode("utf-8"))
                    except json.JSONDecodeError as exc:
                        response = {"ok": False, "error": f"invalid request: {exc}"}
                        conn.sendall(json.dumps(response).encode("utf-8"))
                        continue
                    action = request.get("action")
                    if action == "send":
                        text = request.get("text", "")
                        queue_input(text)
                        response = {"ok": True}
                    elif action == "snapshot":
                        response = {
                            "ok": True,
                            "transcript": capture_payload(),
                            "log_path": str(log_path),
                            "alive": proc.poll() is None,
                        }
                    elif action == "status":
                        response = {
                            "ok": True,
                            "alive": proc.poll() is None,
                            "pid": proc.pid,
                            "exit_code": proc.poll(),
                            "log_path": str(log_path),
                        }
                    elif action == "close":
                        response = {"ok": True}
                        if proc.poll() is None:
                            os.killpg(proc.pid, signal.SIGTERM)
                            time.sleep(0.1)
                        running = False
                    else:
                        response = {"ok": False, "error": f"unknown action: {action}"}
                    conn.sendall(json.dumps(response).encode("utf-8"))

    selector.unregister(server)
    server.close()
    if socket_path.exists():
        socket_path.unlink()
    if proc.poll() is None:
        os.killpg(proc.pid, signal.SIGTERM)
    os.close(master_fd)


if __name__ == "__main__":
    main()

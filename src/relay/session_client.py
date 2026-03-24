from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Any, Dict


class SessionClient:
    def __init__(self, socket_path: str) -> None:
        self.socket_path = str(Path(socket_path))

    def request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.connect(self.socket_path)
            sock.sendall(json.dumps(payload).encode("utf-8"))
            sock.shutdown(socket.SHUT_WR)
            chunks = []
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
        raw = b"".join(chunks).decode("utf-8", errors="replace").strip()
        if not raw:
            return {"ok": False, "error": "empty response"}
        return json.loads(raw)

    def send(self, text: str) -> Dict[str, Any]:
        return self.request({"action": "send", "text": text})

    def snapshot(self) -> Dict[str, Any]:
        return self.request({"action": "snapshot"})

    def status(self) -> Dict[str, Any]:
        return self.request({"action": "status"})

    def close(self) -> Dict[str, Any]:
        return self.request({"action": "close"})

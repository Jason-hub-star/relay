from __future__ import annotations

import json
import sys


def headless(prompt: str) -> None:
    payload = {
        "summary": f"handled: {prompt[:80]}",
        "findings": [],
        "next_action": "done",
        "steps": ["one"],
        "risks": [],
        "changes": ["updated"],
        "followups": [],
        "optimized_prompt": prompt,
        "rationale": "relay helper",
        "warnings": [],
        "sources": [],
        "claims": [],
        "sections": [],
        "citations": [],
        "areas": [],
        "recommended_files": [],
        "key_points": [],
        "handoff_prompt": prompt,
        "details": [prompt],
    }
    print(json.dumps(payload))


def interactive() -> None:
    print("relay helper ready", flush=True)
    for line in sys.stdin:
        line = line.rstrip("\n")
        print(f"interactive:{line}", flush=True)


def main(argv: list[str] | None = None) -> None:
    argv = list(argv or sys.argv[1:])
    if argv and argv[0] == "exec":
        headless(argv[-1])
        return
    if "-p" in argv:
        headless(argv[argv.index("-p") + 1])
        return
    interactive()


if __name__ == "__main__":
    main()

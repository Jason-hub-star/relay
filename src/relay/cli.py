from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from relay.models import AgentKind, ContextPolicy, ResumeStrategy, ReturnMode, TaskType
from relay.service import RelayService


def _json_print(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=True, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="relay", description="Manual multi-AI handoff orchestrator.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    tui_parser = subparsers.add_parser("tui", help="Open the Textual TUI.")
    tui_mode = tui_parser.add_mutually_exclusive_group()
    tui_mode.add_argument("--inline", action="store_true", help="Run inline for easier terminal scrollback/copy.")
    tui_mode.add_argument("--fullscreen", action="store_true", help="Run in full-screen alternate-screen mode.")

    agent_parser = subparsers.add_parser("agent", help="Agent management.")
    agent_sub = agent_parser.add_subparsers(dest="agent_command", required=True)
    agent_add = agent_sub.add_parser("add", help="Register an agent.")
    agent_add.add_argument("name")
    agent_add.add_argument("--kind", required=True, choices=[item.value for item in AgentKind])
    agent_add.add_argument("--command", dest="launch_command", required=True)
    agent_add.add_argument("--resume-strategy", required=True, choices=[item.value for item in ResumeStrategy])
    agent_sub.add_parser("list", help="List agents.")

    session_parser = subparsers.add_parser("session", help="Session management.")
    session_sub = session_parser.add_subparsers(dest="session_command", required=True)
    session_open = session_sub.add_parser("open", help="Open a live origin session.")
    session_open.add_argument("--agent", required=True)
    session_open.add_argument("--label", required=True)
    session_open.add_argument("--cwd")
    session_sub.add_parser("list", help="List sessions.")
    session_close = session_sub.add_parser("close", help="Close a live session.")
    session_close.add_argument("session_id")

    delegate = subparsers.add_parser("delegate", help="Delegate a task to another AI.")
    delegate.add_argument("--from", dest="from_session_id", required=True)
    delegate.add_argument("--to", dest="to_agent_name", required=True)
    delegate.add_argument("--task", required=True, choices=[item.value for item in TaskType])
    delegate.add_argument("--title")
    delegate.add_argument("--context-policy", choices=[item.value for item in ContextPolicy])
    delegate.add_argument("--instructions")
    delegate.add_argument("--parent-run")

    return_cmd = subparsers.add_parser("return", help="Return a completed run to the origin AI.")
    return_cmd.add_argument("--run", required=True)
    return_cmd.add_argument("--mode", choices=[item.value for item in ReturnMode], default=ReturnMode.RESUME.value)

    inspect_parser = subparsers.add_parser("inspect", help="Inspect a run.")
    inspect_sub = inspect_parser.add_subparsers(dest="inspect_command", required=True)
    inspect_run = inspect_sub.add_parser("run")
    inspect_run.add_argument("run_id")

    preset_parser = subparsers.add_parser("preset", help="Preset templates.")
    preset_sub = preset_parser.add_subparsers(dest="preset_command", required=True)
    preset_sub.add_parser("list")
    preset_run = preset_sub.add_parser("run")
    preset_run.add_argument("preset_name")
    preset_run.add_argument("--from", dest="from_session_id", required=True)
    preset_run.add_argument("--to", dest="to_agent_name", required=True)

    transcript = subparsers.add_parser("transcript", help="Show a session transcript.")
    transcript.add_argument("session_id")

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    service = RelayService()

    if args.command == "tui":
        from relay.tui import run_tui

        run_tui(service, inline=not args.fullscreen)
        return

    if args.command == "agent":
        if args.agent_command == "add":
            payload = service.add_agent(
                name=args.name,
                kind=args.kind,
                launch_command=args.launch_command,
                resume_strategy=args.resume_strategy,
            )
            _json_print(payload)
            return
        if args.agent_command == "list":
            _json_print(service.list_agents())
            return

    if args.command == "session":
        if args.session_command == "open":
            payload = service.open_session(agent_name=args.agent, label=args.label, cwd=args.cwd)
            _json_print(payload)
            return
        if args.session_command == "list":
            _json_print(service.list_sessions())
            return
        if args.session_command == "close":
            _json_print(service.close_session(args.session_id))
            return

    if args.command == "delegate":
        payload = service.delegate(
            from_session_id=args.from_session_id,
            to_agent_name=args.to_agent_name,
            task_type=args.task,
            title=args.title,
            context_policy=args.context_policy,
            instructions=args.instructions,
            parent_run_id=args.parent_run,
        )
        _json_print(payload)
        return

    if args.command == "return":
        _json_print(service.return_run(run_id=args.run, mode=args.mode))
        return

    if args.command == "inspect":
        _json_print(service.inspect_run(args.run_id))
        return

    if args.command == "preset":
        if args.preset_command == "list":
            _json_print(service.list_presets())
            return
        if args.preset_command == "run":
            _json_print(
                service.run_preset(
                    preset_name=args.preset_name,
                    from_session_id=args.from_session_id,
                    to_agent_name=args.to_agent_name,
                )
            )
            return

    if args.command == "transcript":
        print(service.transcript(args.session_id))
        return

    parser.print_help()
    sys.exit(1)


if __name__ == "__main__":
    main()

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import datetime as dt
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

from rich.text import Text

from relay import __version__
from relay.adapters import send_to_live_session
from relay.ids import random_suffix
from relay.models import ApprovalMode, RunStatus, SessionStatus, TaskType
from relay.config import exports_dir
from relay.prompts import build_return_prompt
from relay.session_host import _normalize_terminal_text
from relay.service import RelayService
from relay.workflow_store import WorkflowStore

try:
    from textual import events
    from textual.app import App, ComposeResult
    from textual.containers import Container, Vertical
    from textual.screen import ModalScreen
    from textual.widgets import Button, Checkbox, Input, Label, Select, Static
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("Textual is required for relay tui. Install with `pip install -e .`.") from exc


TASK_LABELS = {
    TaskType.REVIEW.value: "Review",
    TaskType.IMPLEMENT.value: "Build",
    TaskType.OPTIMIZE_PROMPT.value: "Simplify",
    TaskType.WEB_RESEARCH.value: "Research",
    TaskType.PDF_ANALYSIS.value: "Read PDF",
    TaskType.TREE_EXPLORE.value: "Explore Code",
    TaskType.CONTEXT_DIGEST.value: "Context Digest",
    TaskType.PLAN.value: "Plan",
    TaskType.CUSTOM.value: "Custom",
}

STATUS_LABELS = {
    "queued": "Waiting",
    "running": "Working",
    "completed": "Done",
    "failed": "Failed",
    "archived": "Hidden",
    "returned": "Sent Back",
    "needs_login": "Needs Login",
    "unavailable": "Unavailable",
    "ready": "Ready",
}

JOB_OPTIONS = [
    (friendly, value)
    for value, friendly in [
        (TaskType.REVIEW.value, "Review"),
        (TaskType.WEB_RESEARCH.value, "Research"),
        (TaskType.OPTIMIZE_PROMPT.value, "Simplify"),
        (TaskType.IMPLEMENT.value, "Implement"),
        (TaskType.CONTEXT_DIGEST.value, "Context Digest"),
        (TaskType.CUSTOM.value, "Custom"),
    ]
]

SLASH_COMMANDS = [
    {"name": "/workflow", "description": "Open the workflow picker."},
    {"name": "/workflow new", "description": "Create a new workflow."},
    {"name": "/workflow use", "description": "Use a saved workflow by name."},
    {"name": "/workflow save", "description": "Save the active workflow with a name."},
    {"name": "/workflow off", "description": "Clear the pinned workflow."},
    {"name": "/provider", "description": "Show the current main provider."},
    {"name": "/provider use", "description": "Switch the main provider for direct chat."},
    {"name": "/approval-mode", "description": "Show or set the current approval mode."},
    {"name": "/agents", "description": "Show AI readiness."},
    {"name": "/login", "description": "Open login for one AI or all missing ones."},
    {"name": "/progress", "description": "Open or close the progress drawer."},
    {"name": "/trace last", "description": "Show the last internal workflow trace."},
    {"name": "/resume last", "description": "Replay the last unfinished workflow."},
    {"name": "/rerun last", "description": "Run the last prompt again with the same workflow."},
    {"name": "/copy transcript", "description": "Copy the visible transcript."},
    {"name": "/copy last-result", "description": "Copy the latest structured result."},
    {"name": "/export transcript", "description": "Save the visible transcript to a file."},
    {"name": "/export last-result", "description": "Save the latest structured result to a file."},
    {"name": "/help", "description": "Show command help."},
]


def friendly_task_label(task_type: str) -> str:
    return TASK_LABELS.get(task_type, task_type.replace("_", " ").title())


def friendly_status_label(status: str) -> str:
    return STATUS_LABELS.get(status, status.replace("_", " ").title())


def summarize_result(normalized_result: Optional[dict[str, Any]]) -> str:
    if not normalized_result:
        return "No result yet."
    for key in ("summary", "optimized_prompt", "next_action", "handoff_prompt", "rationale", "response"):
        value = normalized_result.get(key)
        if isinstance(value, str) and value.strip():
            text = value.strip().replace("\n", " ")
            return text[:140] + ("..." if len(text) > 140 else "")
    return "Finished."


def normalized_select_value(select: Select) -> Optional[str]:
    raw = select.value
    if raw is None:
        return None
    value = str(raw)
    if not value or value.startswith("Select."):
        return None
    return value


def should_show_command_overlay(text: str) -> bool:
    return text.startswith("/")


def filter_slash_commands(text: str) -> list[dict[str, str]]:
    query = text.strip().lower()
    if not query.startswith("/"):
        return []
    if query == "/":
        return list(SLASH_COMMANDS)
    return [item for item in SLASH_COMMANDS if item["name"].startswith(query)]


def move_command_selection(current_index: int, commands: list[dict[str, str]], delta: int) -> int:
    if not commands:
        return 0
    return (current_index + delta) % len(commands)


def resolve_slash_command(text: str, selected_index: int) -> str:
    commands = filter_slash_commands(text)
    if not commands:
        return text
    stripped = text.strip()
    if " " in stripped:
        return text
    selected = commands[min(max(selected_index, 0), len(commands) - 1)]
    if stripped == "/" or not any(item["name"] == stripped for item in commands):
        return selected["name"]
    return text


def toggle_progress_drawer_state(is_open: bool) -> bool:
    return not is_open


def should_prompt_for_workflow(prompt: str, workflow: Optional[dict[str, Any]]) -> bool:
    return bool(prompt.strip()) and not prompt.strip().startswith("/") and workflow is None


def prefers_fast_direct_route(prompt: str) -> bool:
    stripped = prompt.strip()
    if not stripped or "\n" in stripped:
        return False
    if len(stripped) > 48:
        return False
    heavy_markers = ["def ", "class ", "function", "import ", "```", "diff ", "stack trace", "error:"]
    lowered = stripped.lower()
    return not any(marker in lowered for marker in heavy_markers)


def workflow_preview(workflow: Optional[dict[str, Any]]) -> str:
    if not workflow:
        return "No workflow selected."
    main = workflow.get("main_agent") or "Main AI"
    if workflow.get("mode") == "direct" or not workflow.get("steps"):
        return f"{main} -> Direct"
    parts = [main]
    for step in workflow.get("steps", []):
        parts.append(f"{step['agent_name']} {friendly_task_label(step['task_type'])}")
    if workflow.get("send_back"):
        parts.append("Send Back")
    return " -> ".join(parts)


def normalize_display_text(text: str) -> str:
    cleaned = _normalize_terminal_text(text or "")
    return "".join(char for char in cleaned if char in "\n\t" or ord(char) >= 32)


def as_plain_text(content: str) -> Text:
    return Text(normalize_display_text(content))


def export_file_name(stem: str, *, when: Optional[time.struct_time] = None) -> str:
    moment = when or time.localtime()
    return f"{time.strftime('%Y%m%d-%H%M%S', moment)}-{stem}.txt"


def thinking_label(provider: str, tick: int) -> str:
    dots = "." * ((tick % 3) + 1)
    name = provider or "provider"
    return f"Thinking with {name}{dots}"


def split_transcript_for_streaming(transcript: str) -> tuple[str, str]:
    marker = "\n\n"
    if marker not in transcript:
        return "", transcript
    index = transcript.find(marker) + len(marker)
    return transcript[:index], transcript[index:]


def next_stream_index(target: str, current_index: int, *, chunk_size: int = 12) -> int:
    if current_index >= len(target):
        return len(target)
    remaining = len(target) - current_index
    if len(target) <= 120 or remaining <= 48:
        return len(target)
    search_window = target[current_index : min(len(target), current_index + 160)]
    for marker in ("\n\n", "\n", ". ", "? ", "! ", "। ", "… "):
        index = search_window.find(marker)
        if index != -1:
            return min(len(target), current_index + index + len(marker))
    adaptive = max(chunk_size, min(96, max(24, len(target) // 4)))
    return min(len(target), current_index + adaptive)


def initial_stream_index(target: str) -> int:
    if not target:
        return 0
    if len(target) <= 120:
        return len(target)
    return next_stream_index(target, 0, chunk_size=64)


def render_result_block(title: str, body: str) -> str:
    text = normalize_display_text(body).strip()
    if not text:
        text = "No result."
    return f"[{title}]\n{text}"


def render_normalized_result(task_type: str, normalized: Optional[dict[str, Any]], raw_output: str = "") -> str:
    if not normalized:
        return normalize_display_text(raw_output).strip()
    lines: list[str] = []
    for key in ("summary", "optimized_prompt", "next_action", "handoff_prompt", "rationale", "response"):
        value = normalized.get(key)
        if isinstance(value, str) and value.strip():
            lines.append(value.strip())
    findings = normalized.get("findings")
    if isinstance(findings, list):
        for finding in findings:
            if not isinstance(finding, dict):
                continue
            title = str(finding.get("title") or "").strip()
            severity = str(finding.get("severity") or "").strip()
            file = str(finding.get("file") or "").strip()
            line = finding.get("line")
            suggestion = str(finding.get("suggestion") or "").strip()
            location = ""
            if file:
                location = file
                if line not in (None, ""):
                    location += f":{line}"
            prefix = f"- {severity}: {title}".strip()
            if location:
                prefix += f" ({location})"
            lines.append(prefix)
            if suggestion:
                lines.append(f"  Suggestion: {suggestion}")
    for key in (
        "steps",
        "risks",
        "changes",
        "followups",
        "warnings",
        "sources",
        "claims",
        "sections",
        "citations",
        "areas",
        "recommended_files",
        "key_points",
        "details",
    ):
        value = normalized.get(key)
        if not isinstance(value, list) or not value:
            continue
        label = key.replace("_", " ").title()
        lines.append(f"{label}:")
        for item in value:
            if isinstance(item, str) and item.strip():
                lines.append(f"- {item.strip()}")
    if not lines:
        fallback = normalize_display_text(raw_output).strip()
        if fallback:
            return fallback
        return "No result."
    return "\n".join(lines)


def build_status_strip(agents: list[dict[str, Any]], statuses: dict[str, dict[str, Any]]) -> Text:
    text = Text()
    first = True
    for agent in agents:
        if not first:
            text.append("  ")
        first = False
        status = statuses.get(agent["name"], {}).get("status", "unknown")
        color = "bright_black"
        if status == "ready":
            color = "green"
        elif status in {"needs_login", "failed"}:
            color = "red"
        elif status == "unavailable":
            color = "grey50"
        text.append(agent["name"], style="bold white")
        text.append(" ")
        text.append("●", style=color)
    if agents:
        text.append("   ")
    text.append(f"Relay v{__version__}", style="bold bright_black")
    return text


def build_status_strip_with_mode(
    agents: list[dict[str, Any]],
    statuses: dict[str, dict[str, Any]],
    *,
    approval_mode: str,
    main_provider: Optional[str],
    workflow_main: Optional[str],
) -> Text:
    mode_color = {
        ApprovalMode.PLAN.value: "cyan",
        ApprovalMode.DEFAULT.value: "yellow",
        ApprovalMode.AUTO_EDIT.value: "green",
        ApprovalMode.YOLO.value: "red",
    }.get(approval_mode, "yellow")
    text = Text()
    if main_provider:
        text.append("Provider: ", style="bold magenta")
        text.append(main_provider, style="bold white")
        if agents:
            text.append("   ")
    if workflow_main:
        text.append("Workflow Main: ", style="bold cyan")
        text.append(workflow_main, style="bold white")
        if agents:
            text.append("   ")
    text.append("Approval: ", style="bold " + mode_color)
    text.append(approval_mode, style=f"bold {mode_color}")
    if agents:
        text.append("   ")
    text.append(build_status_strip(agents, statuses))
    return text


class WorkflowSetupScreen(ModalScreen[Optional[dict[str, Any]]]):
    def __init__(
        self,
        *,
        service: RelayService,
        store: WorkflowStore,
        prompt_text: str,
        current_workflow: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__()
        self.service = service
        self.store = store
        self.prompt_text = prompt_text
        self.current_workflow = current_workflow

    def compose(self) -> ComposeResult:
        agents = self.service.list_user_agents()
        agent_options = [(agent["name"], agent["name"]) for agent in agents]
        first_agent = agent_options[0][1] if agent_options else Select.BLANK
        saved_options = [("Custom", "__custom__")] + [
            (workflow["name"], workflow["id"]) for workflow in self.store.list_workflows()
        ]
        preset_options = [("None", "__none__")] + [(name, name) for name in preset_definitions()]
        with Container(id="workflow-modal"):
            yield Label("Choose a workflow")
            yield Static(
                "Your message will use this workflow. Save it once if you want to reuse it next time.",
                classes="modal-copy",
            )
            yield Input(value=self.prompt_text, placeholder="Prompt preview", id="workflow-prompt", disabled=True)
            with Container(classes="modal-actions modal-actions-top"):
                yield Button("Run Once", id="run-once-top")
                yield Button("Save & Use", id="save-use-top")
                yield Button("Cancel", id="cancel-top")
            yield Label("Main AI")
            yield Select(agent_options, value=first_agent, id="workflow-main-agent")
            yield Label("Saved Workflow")
            yield Select(saved_options, value="__custom__", id="workflow-saved")
            yield Label("Quick Preset")
            yield Select(preset_options, value="__none__", id="workflow-preset")
            yield Label("Mode")
            yield Select([("Send directly", "direct"), ("Use steps", "workflow")], value="workflow", id="workflow-mode")
            yield Input(
                value=(self.current_workflow or {}).get("name", ""),
                placeholder="Workflow name",
                id="workflow-name",
            )
            yield Checkbox("Always use this workflow", id="workflow-pin")
            yield Checkbox("Send the final result back", value=True, id="workflow-send-back")
            for index in range(1, 4):
                with Container(classes="step-row"):
                    yield Label(f"Step {index}", classes="step-label")
                    yield Select(agent_options, value=first_agent, id=f"step-agent-{index}", classes="step-agent")
                    yield Select(JOB_OPTIONS, value=TaskType.REVIEW.value, id=f"step-job-{index}", classes="step-job")
                    yield Input(placeholder="Optional label", id=f"step-label-{index}", classes="step-input")
            with Container(classes="modal-actions"):
                yield Button("Run Once", id="run-once")
                yield Button("Save & Use", id="save-use")
                yield Button("Delete Saved", id="delete-saved")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        self.call_after_refresh(self._focus_main_agent)

    def _focus_main_agent(self) -> None:
        try:
            self.query_one("#workflow-main-agent", Select).focus()
        except Exception:
            return

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id in {"cancel", "cancel-top"}:
            self.dismiss(None)
            return
        if event.button.id == "delete-saved":
            saved_value = normalized_select_value(self.query_one("#workflow-saved", Select))
            if saved_value and saved_value != "__custom__":
                self.dismiss({"action": "delete", "workflow_id": saved_value})
            else:
                self.dismiss(None)
            return
        saved_value = normalized_select_value(self.query_one("#workflow-saved", Select))
        workflow: Optional[dict[str, Any]] = None
        if saved_value and saved_value != "__custom__":
            workflow = self.store.get_workflow(saved_value)
        if workflow is None:
            workflow = self._build_workflow_from_form()
        if workflow is None:
            self.dismiss(None)
            return
        self.dismiss(
            {
                "action": "run",
                "workflow": workflow,
                "set_active": event.button.id in {"save-use", "save-use-top"} or self.query_one("#workflow-pin", Checkbox).value,
            }
        )

    def _build_workflow_from_form(self) -> Optional[dict[str, Any]]:
        preset_value = normalized_select_value(self.query_one("#workflow-preset", Select))
        main_agent = normalized_select_value(self.query_one("#workflow-main-agent", Select))
        if not main_agent:
            return None
        if preset_value and preset_value != "__none__":
            workflow = build_preset_workflow(preset_value, self.service.list_user_agents(), main_agent=main_agent)
            if workflow:
                return workflow
        mode = normalized_select_value(self.query_one("#workflow-mode", Select)) or "workflow"
        send_back = self.query_one("#workflow-send-back", Checkbox).value
        name = self.query_one("#workflow-name", Input).value.strip() or "Workflow"
        steps = []
        if mode == "workflow":
            for index in range(1, 4):
                agent_name = normalized_select_value(self.query_one(f"#step-agent-{index}", Select))
                task_type = normalized_select_value(self.query_one(f"#step-job-{index}", Select))
                label = self.query_one(f"#step-label-{index}", Input).value.strip()
                if not agent_name or not task_type:
                    continue
                steps.append(
                    {
                        "id": f"step_{index}",
                        "agent_name": agent_name,
                        "task_type": task_type,
                        "label": label,
                    }
                )
        workflow_id = f"workflow_{random_suffix(8)}"
        return {
            "id": workflow_id,
            "name": name,
            "main_agent": main_agent,
            "mode": mode,
            "send_back": send_back,
            "steps": steps,
        }


class DetailScreen(ModalScreen[None]):
    def __init__(self, payload: str) -> None:
        super().__init__()
        self.payload = payload

    def compose(self) -> ComposeResult:
        with Container(id="detail-modal"):
            yield Label("Details")
            yield Static(as_plain_text(self.payload or "(nothing to show)"), id="detail-payload")
            yield Button("Close", id="close")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close":
            self.dismiss(None)


class RelayShellApp(App[None]):
    CSS = """
    Screen {
        layout: vertical;
        background: #111111;
        color: #f3f3f3;
        overflow-y: auto;
    }
    Screen:inline {
        height: auto;
        min-height: 8;
        border: none;
    }
    #root {
        layout: vertical;
        height: auto;
        min-height: 8;
        padding: 0;
    }
    #status-strip {
        height: 1;
        padding: 0 1;
        color: #9a9a9a;
        background: transparent;
    }
    #transcript-box {
        height: auto;
        min-height: 6;
        padding: 0 1;
        overflow: auto;
        background: transparent;
    }
    #progress-drawer, #command-overlay {
        padding: 0 1;
        background: transparent;
        display: none;
    }
    #progress-box, #command-box {
        color: #d7d7d7;
    }
    Input {
        border: none;
        background: transparent;
        color: #f3f3f3;
    }
    #prompt-input {
        margin-top: 0;
    }
    #workflow-modal, #detail-modal {
        width: 80;
        height: auto;
        max-height: 90%;
        padding: 1 2;
        background: #171717;
        border: solid #5f5f5f;
        overflow-y: auto;
    }
    .modal-copy {
        color: #bbbbbb;
        padding-bottom: 1;
    }
    .modal-actions {
        layout: horizontal;
        padding-top: 1;
        height: auto;
    }
    .modal-actions Button {
        margin-right: 1;
    }
    .modal-actions-top {
        padding-bottom: 1;
    }
    .step-row {
        layout: horizontal;
        height: auto;
        padding: 0 0 1 0;
    }
    .step-label {
        width: 8;
        padding-top: 1;
    }
    .step-agent {
        width: 24;
        margin-right: 1;
    }
    .step-job {
        width: 18;
        margin-right: 1;
    }
    .step-input {
        width: 1fr;
    }
    #details-button {
        margin-top: 1;
    }
    """

    def __init__(self, service: RelayService, store: Optional[WorkflowStore] = None, *, inline_mode: bool = False) -> None:
        super().__init__()
        self.service = service
        self.store = store or WorkflowStore()
        self.inline_mode = inline_mode
        self.current_session_id: Optional[str] = None
        self.last_run_details: Optional[dict[str, Any]] = None
        self.login_status: dict[str, dict[str, Any]] = {}
        self.progress_open = False
        self.relay_notices: list[dict[str, Any]] = []
        self.current_progress: dict[str, Any] = {
            "status": "idle",
            "workflow_name": "",
            "prompt": "",
            "steps": [],
            "summary": "",
        }
        self._executor = ThreadPoolExecutor(max_workers=2)
        self._active_future: Optional[Future[Any]] = None
        self._active_kind: Optional[str] = None
        self._last_transcript = ""
        self._manual_transcript = ""
        self._lock = threading.Lock()
        self._pending_prompt = ""
        self._progress_revision = 0
        self._last_rendered_progress_revision = -1
        self._command_index = 0
        self._thinking_tick = 0
        self._streaming_prefix = ""
        self._streaming_target = ""
        self._streaming_index = 0
        self._running_prompt = ""
        self._running_provider = ""

    def compose(self) -> ComposeResult:
        with Vertical(id="root"):
            yield Static(id="status-strip")
            yield Static(id="transcript-box")
            with Container(id="progress-drawer"):
                yield Label("Progress")
                yield Static(id="progress-box")
                yield Button("See Details", id="details-button")
            with Container(id="command-overlay"):
                yield Static(id="command-box")
            yield Input(placeholder="Type a prompt or / for commands", id="prompt-input")

    def on_mount(self) -> None:
        cleanup = self.service.cleanup_stale_state()
        self._refresh_logins()
        self._add_notice("Relay is ready.")
        if cleanup["closed_sessions"] or cleanup["failed_runs"]:
            self._add_notice(
                f"Startup cleanup: closed {cleanup['closed_sessions']} stale sessions, failed {cleanup['failed_runs']} stale runs."
            )
        self.set_interval(0.12, self._poll_background_work)
        self.refresh_ui()
        self.call_after_refresh(self._focus_prompt_input)

    def refresh_ui(self) -> None:
        self._refresh_status_strip()
        self._refresh_transcript()
        self._refresh_progress_drawer()
        self._refresh_command_overlay()
        self._last_rendered_progress_revision = self._progress_revision

    def _refresh_status_strip(self) -> None:
        agents = self.service.list_user_agents()
        active_workflow = self.store.get_active_workflow()
        self.query_one("#status-strip", Static).update(
            build_status_strip_with_mode(
                agents,
                self.login_status,
                approval_mode=self.store.get_approval_mode(),
                main_provider=self._main_provider_name(),
                workflow_main=(active_workflow or {}).get("main_agent"),
            )
        )

    def _refresh_transcript(self) -> None:
        parts = []
        notice_lines = self._visible_notice_lines()
        if notice_lines:
            parts.extend(notice_lines)
        transcript = self._current_transcript_tail()
        if transcript:
            if parts:
                parts.append("")
            parts.append(transcript)
        manual = self._manual_transcript.strip()
        if manual:
            if parts:
                parts.append("")
            parts.append(manual)
        if not parts:
            parts.append("Type a prompt below. If you start with /, command help opens.")
        self.query_one("#transcript-box", Static).update(as_plain_text("\n".join(parts)))

    def _refresh_progress_drawer(self) -> None:
        drawer = self.query_one("#progress-drawer", Container)
        drawer.styles.display = "block" if self.progress_open else "none"
        progress = self.current_progress
        if progress["status"] == "idle":
            text = "No workflow is running."
        else:
            lines = [
                f"Workflow: {progress.get('workflow_name') or 'Workflow'}",
                f"Status: {friendly_status_label(progress['status'])}",
                f"Prompt: {progress.get('prompt', '')[:120]}",
                "",
            ]
            for index, step in enumerate(progress.get("steps", []), start=1):
                summary = step.get("summary") or ""
                line = f"{index}. {step['agent_name']} - {friendly_task_label(step['task_type'])} - {friendly_status_label(step['status'])}"
                lines.append(line)
                if summary:
                    lines.append(f"   {summary}")
                if step.get("note"):
                    lines.append(f"   {step['note']}")
            if progress.get("summary"):
                lines.extend(["", f"Summary: {progress['summary']}"])
            text = "\n".join(lines)
        self.query_one("#progress-box", Static).update(as_plain_text(text))

    def _refresh_command_overlay(self) -> None:
        input_box = self.query_one("#prompt-input", Input)
        overlay = self.query_one("#command-overlay", Container)
        command_box = self.query_one("#command-box", Static)
        if not should_show_command_overlay(input_box.value):
            overlay.styles.display = "none"
            command_box.update(as_plain_text(""))
            return
        overlay.styles.display = "block"
        commands = filter_slash_commands(input_box.value)
        if not commands:
            command_box.update(as_plain_text("No matching commands."))
            return
        selected_index = min(self._command_index, len(commands) - 1)
        lines = []
        for index, item in enumerate(commands):
            prefix = "› " if index == selected_index else "  "
            lines.append(f"{prefix}{item['name']}  {item['description']}")
        command_box.update(as_plain_text("\n".join(lines)))

    def _poll_background_work(self) -> None:
        should_refresh = self._refresh_transcript_from_session()
        if self._active_future is not None and self.current_progress.get("status") == "running":
            self._thinking_tick += 1
            should_refresh = True
        future = self._active_future
        if future is not None and future.done():
            try:
                payload = future.result()
                self._finish_background_work(payload)
                should_refresh = True
            except Exception as exc:  # pragma: no cover
                self._add_notice(self._format_exception_notice(exc), kind="error")
                self._set_progress_status("failed", summary=self._format_exception_summary(exc))
                self.service.append_event(
                    "workflow_error",
                    {
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                )
                should_refresh = True
            finally:
                self._active_future = None
                self._active_kind = None
                input_box = self.query_one("#prompt-input", Input)
                input_box.disabled = False
                self.call_after_refresh(self._focus_prompt_input)
        if self._streaming_target and self._streaming_index < len(self._streaming_target):
            next_index = next_stream_index(self._streaming_target, self._streaming_index)
            if next_index != self._streaming_index:
                self._streaming_index = next_index
                should_refresh = True
        if self._progress_revision != self._last_rendered_progress_revision:
            should_refresh = True
        if should_refresh:
            self.refresh_ui()

    def _refresh_transcript_from_session(self) -> bool:
        session_id = self.current_session_id
        if not session_id:
            return False
        try:
            transcript = self.service.transcript(session_id)
        except Exception:
            return False
        if transcript != self._last_transcript:
            self._last_transcript = transcript
            return True
        return False

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "prompt-input":
            commands = filter_slash_commands(event.value)
            if commands:
                self._command_index = min(self._command_index, len(commands) - 1)
            else:
                self._command_index = 0
            self._refresh_command_overlay()

    def on_key(self, event: events.Key) -> None:
        try:
            input_box = self.query_one("#prompt-input", Input)
        except Exception:
            return
        if self.focused is not input_box:
            return
        commands = filter_slash_commands(input_box.value)
        if not commands:
            return
        if event.key in {"down", "tab"}:
            self._command_index = move_command_selection(self._command_index, commands, 1)
            self._refresh_command_overlay()
            event.prevent_default()
            event.stop()
            return
        if event.key in {"up", "shift+tab"}:
            self._command_index = move_command_selection(self._command_index, commands, -1)
            self._refresh_command_overlay()
            event.prevent_default()
            event.stop()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "prompt-input":
            return
        text = event.value.strip()
        if not text:
            return
        event.input.value = ""
        if text.startswith("/"):
            text = resolve_slash_command(text, self._command_index)
            self._handle_slash_command(text)
            return
        self._manual_transcript = ""
        self._prune_notices_for_chat()
        workflow = self.store.get_active_workflow()
        if should_prompt_for_workflow(text, workflow):
            if self.store.has_seen_modal():
                self._add_notice(
                    "No pinned workflow. Using direct mode. Type /workflow to change it.",
                    kind="hint",
                )
                self._start_prompt_run(text, self._default_direct_workflow(text))
                return
            self._pending_prompt = text
            self.push_screen(
                WorkflowSetupScreen(service=self.service, store=self.store, prompt_text=text, current_workflow=workflow),
                self._handle_workflow_modal,
            )
            return
        self._start_prompt_run(text, workflow)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "details-button":
            self._open_details()

    def _handle_slash_command(self, command_text: str) -> None:
        command = command_text.strip()
        if command == "/":
            self._add_notice("Type a slash command, like /workflow or /login gemini-main.", kind="command")
            return
        if command == "/help":
            self._refresh_logins()
            lines = [
                f"Approval mode: {self.store.get_approval_mode()}",
                "AI status:",
            ]
            for status in self.service.check_logins(cwd=os.getcwd()):
                lines.append(f"- {status['agent_name']}: {friendly_status_label(status['status'])}")
            self._add_notice("\n".join(lines), kind="command")
            return
        if command == "/agents":
            self._refresh_logins()
            lines = [f"Approval mode: {self.store.get_approval_mode()}", "AI status:"]
            for agent in self.service.list_agent_profiles():
                status = self.login_status.get(agent["name"], {}).get("status", "unknown")
                hints = ", ".join(agent.get("recommended_for", []))
                extras = ", ".join(agent.get("experimental_for", []))
                suffix = f" | recommended for {hints}" if hints else ""
                if extras:
                    suffix += f" | experimental: {extras}"
                lines.append(f"- {agent['name']}: {friendly_status_label(status)}{suffix}")
            self._add_notice("\n".join(lines), kind="command")
            return
        if command == "/provider":
            self._add_notice(f"Main provider: {self._main_provider_name()}", kind="command")
            return
        if command.startswith("/provider use "):
            name = command[len("/provider use ") :].strip()
            agent = self.service.repo.get_agent(name=name)
            if not agent:
                self._add_notice("No provider matched that name.", kind="error")
                return
            self.store.set_main_provider(agent["name"])
            self._add_notice(f"Main provider set to {agent['name']}.", kind="command")
            self.refresh_ui()
            return
        if command == "/approval-mode":
            modes = ", ".join(mode.value for mode in ApprovalMode)
            self._add_notice(f"Approval mode: {self.store.get_approval_mode()} | options: {modes}", kind="command")
            return
        if command.startswith("/approval-mode "):
            requested = command[len("/approval-mode ") :].strip().lower()
            valid = {mode.value for mode in ApprovalMode}
            if requested not in valid:
                self._add_notice(f"Unknown approval mode. Options: {', '.join(sorted(valid))}", kind="error")
                return
            self.store.set_approval_mode(requested)
            self._add_notice(f"Approval mode set to {requested}.", kind="command")
            self.refresh_ui()
            return
        if command == "/copy transcript":
            self._copy_text(self._visible_transcript_text(), label="transcript")
            return
        if command == "/copy last-result":
            self._copy_text(self._last_result_text(), label="last result")
            return
        if command == "/export transcript":
            path = self._export_text(self._visible_transcript_text(), stem="transcript")
            self._add_notice(f"Saved transcript to {path}", kind="command")
            return
        if command == "/export last-result":
            path = self._export_text(self._last_result_text(), stem="last-result")
            self._add_notice(f"Saved last result to {path}", kind="command")
            return
        if command == "/progress":
            self.progress_open = toggle_progress_drawer_state(self.progress_open)
            self.refresh_ui()
            return
        if command == "/trace last":
            self._manual_transcript = self._format_trace_last()
            self.refresh_ui()
            return
        if command == "/rerun last":
            self._rerun_last_prompt(resume=False)
            return
        if command == "/resume last":
            self._rerun_last_prompt(resume=True)
            return
        if command == "/workflow" or command == "/workflow new":
            self.push_screen(
                WorkflowSetupScreen(
                    service=self.service,
                    store=self.store,
                    prompt_text=self._pending_prompt,
                    current_workflow=self.store.get_active_workflow(),
                ),
                self._handle_workflow_modal,
            )
            return
        if command == "/workflow off":
            self.store.set_active_workflow(None)
            self._add_notice("Pinned workflow cleared.", kind="command")
            return
        if command.startswith("/workflow use "):
            name = command[len("/workflow use ") :].strip().lower()
            workflow = self._find_workflow_by_name(name)
            if not workflow:
                self._add_notice("No saved workflow matched that name.", kind="error")
                return
            self.store.set_active_workflow(workflow["id"])
            self._add_notice(f"Using workflow: {workflow['name']}", kind="command")
            return
        if command.startswith("/workflow save "):
            name = command[len("/workflow save ") :].strip()
            active = self.store.get_active_workflow()
            if not active:
                self._add_notice("There is no active workflow to save.", kind="error")
                return
            saved = dict(active)
            saved["name"] = name or saved["name"]
            if not saved.get("id"):
                saved["id"] = f"workflow_{random_suffix(8)}"
            self.store.save_workflow(saved, set_active=True)
            self._add_notice(f"Saved workflow as {saved['name']}.", kind="command")
            return
        if command.startswith("/login"):
            parts = command.split(maxsplit=1)
            if len(parts) == 2:
                self._ensure_agent_ready(parts[1].strip(), interactive=True)
                return
            for status in self.service.check_logins(cwd=os.getcwd()):
                if status["status"] == "needs_login":
                    self._ensure_agent_ready(status["agent_name"], interactive=True)
            self._refresh_logins()
            return
        self._add_notice("Unknown command. Type /help to see the list.", kind="error")

    def _handle_workflow_modal(self, result: Optional[dict[str, Any]]) -> None:
        if not result:
            self.call_after_refresh(self._focus_prompt_input)
            return
        if result.get("action") == "delete":
            self.store.delete_workflow(result["workflow_id"])
            self._add_notice("Saved workflow deleted.", kind="command")
            self.call_after_refresh(self._focus_prompt_input)
            return
        workflow = result["workflow"]
        self.store.mark_seen()
        if result.get("set_active"):
            self.store.save_workflow(workflow, set_active=True)
            self._add_notice(f"Saved and pinned workflow: {workflow['name']}", kind="command")
        self._start_prompt_run(self._pending_prompt or "", workflow)
        self._pending_prompt = ""

    def _start_prompt_run(self, prompt: str, workflow: Optional[dict[str, Any]]) -> None:
        if not prompt.strip():
            return
        if self._active_future is not None:
            self._add_notice("Please wait for the current workflow to finish.", kind="error")
            return
        workflow = workflow or self.store.get_active_workflow()
        if workflow is None:
            workflow = self._default_direct_workflow(prompt)
        approval_mode = self.store.get_approval_mode()
        blocked_reason = self._approval_mode_block_reason(workflow, approval_mode=approval_mode)
        if blocked_reason:
            self._add_notice(blocked_reason, kind="error")
            return
        self.service.append_event(
            "prompt_submitted",
            {
                "prompt": prompt,
                "workflow": workflow,
                "cwd": os.getcwd(),
                "approval_mode": approval_mode,
            },
        )
        required_agents = self._required_agents_for_workflow(workflow)
        for agent_name in required_agents:
            readiness = self._ensure_agent_ready(agent_name, interactive=True)
            if readiness["status"] != "ready":
                self._add_notice(f"{agent_name} is not ready yet.", kind="error")
                return
        self._set_progress_status(
            "running",
            workflow_name=workflow["name"],
            prompt=prompt,
            approval_mode=approval_mode,
            steps=[
                {
                    "agent_name": step["agent_name"],
                    "task_type": step["task_type"],
                    "status": "completed" if index < int(workflow.get("resume_from_step", 0) or 0) else "queued",
                    "summary": "",
                    "note": "Resumed from previous run" if index < int(workflow.get("resume_from_step", 0) or 0) else "",
                }
                for index, step in enumerate(workflow.get("steps", []))
            ],
            summary="",
        )
        self._thinking_tick = 0
        self._streaming_prefix = ""
        self._streaming_target = ""
        self._streaming_index = 0
        self._running_prompt = prompt
        self._running_provider = workflow.get("main_agent") or ""
        self.query_one("#prompt-input", Input).disabled = True
        self._active_kind = "prompt"
        self._active_future = self._executor.submit(self._run_prompt_workflow, prompt, workflow)

    def _run_prompt_workflow(self, prompt: str, workflow: dict[str, Any]) -> dict[str, Any]:
        completed_views: list[dict[str, Any]] = []
        last_view: Optional[dict[str, Any]] = None
        return_view: Optional[dict[str, Any]] = None
        summary = "Finished."
        final_output: Optional[dict[str, Any]] = None
        original_output: Optional[dict[str, Any]] = None
        helper_session: Optional[dict[str, Any]] = None
        try:
            if workflow.get("mode") == "direct":
                self.service.append_event(
                    "direct_started",
                    {
                        "prompt": prompt,
                        "workflow_id": workflow["id"],
                        "main_agent": workflow["main_agent"],
                    },
                )
                final_output = self.service.run_direct_prompt(
                    agent_name=workflow["main_agent"],
                    prompt=prompt,
                    cwd=os.getcwd(),
                )
                self.service.append_event(
                    "direct_finished",
                    {
                        "prompt": prompt,
                        "main_agent": workflow["main_agent"],
                        "status": final_output["status"],
                        "display_text": final_output["display_text"],
                        "error": final_output["error"],
                    },
                )
                summary = str(final_output.get("display_text") or "").strip() or "Finished."
            else:
                resume_from_step = int(workflow.get("resume_from_step", 0) or 0)
                resume_parent = workflow.get("resume_last_completed_step") if isinstance(workflow.get("resume_last_completed_step"), dict) else None
                resume_parent_run_id = str(workflow.get("resume_parent_run_id") or "")
                original_output = self.service.run_direct_prompt(
                    agent_name=workflow["main_agent"],
                    prompt=prompt,
                    cwd=os.getcwd(),
                )
                self.service.append_event(
                    "workflow_original_finished",
                    {
                        "prompt": prompt,
                        "workflow_id": workflow["id"],
                        "main_agent": workflow["main_agent"],
                        "status": original_output["status"],
                        "display_text": original_output["display_text"],
                        "error": original_output["error"],
                    },
                )
                if resume_parent:
                    last_view = {
                        "run": {"id": resume_parent.get("run_id") or resume_parent_run_id, "status": RunStatus.COMPLETED.value},
                        "packet": {"task_type": (resume_parent.get("step") or {}).get("task_type", TaskType.CUSTOM.value)},
                        "target_agent": {"name": (resume_parent.get("step") or {}).get("agent_name", "")},
                        "result": {"normalized_result": resume_parent.get("normalized_result") or {}},
                    }
                helper_session = self.service.open_helper_origin_session(
                    cwd=os.getcwd(),
                    label=f"workflow-{random_suffix(6)}",
                )
                self.service.append_event(
                    "workflow_started",
                    {
                        "prompt": prompt,
                        "workflow": workflow,
                        "helper_session_id": helper_session["id"],
                    },
                )
                send_to_live_session(helper_session, prompt)
                original_text = str((original_output or {}).get("display_text") or "").strip()
                if original_text:
                    send_to_live_session(
                        helper_session,
                        f"Original answer from {workflow['main_agent']}:\n{original_text}",
                    )
                time.sleep(0.1)
                for index, step in enumerate(workflow.get("steps", [])):
                    if index < resume_from_step:
                        self._update_step_state(index, RunStatus.COMPLETED.value, "Skipped on resume.", "Resumed from previous run")
                        continue
                    self.service.append_event(
                        "workflow_step_started",
                        {
                            "prompt": prompt,
                            "workflow_id": workflow["id"],
                            "step_index": index,
                            "step": step,
                        },
                    )
                    self._update_step_state(index, "running", "Working...", "")
                    title = step.get("label") or f"{friendly_task_label(step['task_type'])} for {workflow['main_agent']}"
                    view = self.service.delegate(
                        from_session_id=helper_session["id"],
                        to_agent_name=step["agent_name"],
                        task_type=step["task_type"],
                        title=title,
                        parent_run_id=(last_view or {}).get("run", {}).get("id") or resume_parent_run_id or None,
                    )
                    last_view = view
                    completed_views.append(view)
                    normalized = (view.get("result") or {}).get("normalized_result", {})
                    note = ""
                    if (
                        view["target_agent"]["kind"] == "codex"
                        and view["packet"]["context_policy"] == "compact"
                        and "compact handoff context" in view["packet"]["instructions"].lower()
                    ):
                        note = "Retrying with smaller context"
                    status = view["run"]["status"]
                    self.service.append_event(
                        "workflow_step_finished",
                        {
                            "prompt": prompt,
                            "workflow_id": workflow["id"],
                            "step_index": index,
                            "step": step,
                            "status": status,
                            "run_id": view["run"]["id"],
                            "normalized_result": normalized,
                            "raw_output_preview": (((view.get("result") or {}).get("raw_output")) or "")[:500],
                            "note": note,
                            "error": view["run"].get("error"),
                        },
                    )
                    self._update_step_state(index, status, summarize_result(normalized), note)
                    if status != RunStatus.COMPLETED.value:
                        break
                if workflow.get("send_back") and last_view and last_view["run"]["status"] == RunStatus.COMPLETED.value:
                    result_payload = ((last_view.get("result") or {}).get("normalized_result")) or {}
                    final_prompt = build_return_prompt(
                        origin_goal=prompt,
                        contributor_name=last_view["target_agent"]["name"],
                        task_type=last_view["packet"]["task_type"],
                        normalized_result=result_payload,
                    )
                    final_output = self.service.run_headless_prompt(
                        agent_name=workflow["main_agent"],
                        prompt=final_prompt,
                        cwd=os.getcwd(),
                        task_type=TaskType.CUSTOM.value,
                    )
                    self.service.append_event(
                        "workflow_send_back_finished",
                        {
                            "prompt": prompt,
                            "workflow_id": workflow["id"],
                            "main_agent": workflow["main_agent"],
                            "status": final_output["status"],
                            "normalized_result": final_output["normalized_result"],
                            "raw_output_preview": (final_output["raw_output"] or "")[:500],
                            "error": final_output["error"],
                        },
                    )
                    return_view = {
                        "agent": final_output["agent"],
                        "status": final_output["status"],
                        "normalized_result": final_output["normalized_result"],
                        "raw_output": final_output["raw_output"],
                        "error": final_output["error"],
                    }
                if final_output:
                    summary = summarize_result(final_output.get("normalized_result"))
                elif last_view:
                    summary = summarize_result(((last_view.get("result") or {}).get("normalized_result")) or {})
                elif original_output:
                    summary = str(original_output.get("display_text") or "").strip() or "Finished."
        finally:
            self.service.append_event(
                "workflow_finished",
                {
                    "prompt": prompt,
                    "workflow": workflow,
                    "summary": summary,
                    "had_final_output": bool(final_output),
                    "last_run_id": ((last_view or {}).get("run") or {}).get("id"),
                },
            )
            if helper_session is not None:
                try:
                    self.service.close_session(helper_session["id"])
                except Exception:
                    pass
        transcript = self._build_workflow_transcript(
            prompt,
            workflow,
            original_output,
            final_output,
            completed_views,
            last_view,
        )
        return {
            "session_id": None,
            "workflow": workflow,
            "prompt": prompt,
            "views": completed_views,
            "last_view": last_view,
            "return_view": return_view,
            "final_output": final_output,
            "original_output": original_output,
            "transcript": transcript,
            "summary": summary,
        }

    def _finish_background_work(self, payload: dict[str, Any]) -> None:
        self.current_session_id = payload["session_id"]
        transcript = payload.get("transcript", "")
        if payload.get("workflow", {}).get("mode") == "direct":
            self._start_transcript_stream(transcript)
            self._last_transcript = transcript
        else:
            self._streaming_prefix = ""
            self._streaming_target = ""
            self._streaming_index = 0
            self._last_transcript = transcript
        if payload.get("last_view"):
            self.last_run_details = payload["last_view"]
        if payload.get("return_view"):
            self.last_run_details = payload["return_view"]
        if payload.get("final_output"):
            self.last_run_details = payload["final_output"]
        elif payload.get("original_output"):
            self.last_run_details = payload["original_output"]
        summary = payload.get("summary", "Finished.")
        self._set_progress_status("completed", summary=summary)
        if payload.get("workflow", {}).get("mode") != "direct":
            self._add_notice(f"Workflow finished: {summary}", kind="status")
        self._running_prompt = ""
        self._running_provider = ""
        self._thinking_tick = 0

    def _ensure_main_session(self, agent_name: str) -> dict[str, Any]:
        if self.current_session_id:
            existing = self.service.repo.get_session(self.current_session_id)
            if existing and existing["status"] == SessionStatus.ACTIVE.value:
                agent = self.service.repo.get_agent(agent_id=existing["agent_id"])
                if agent and agent["name"] == agent_name:
                    return existing
        session = self.service.open_session(agent_name=agent_name, label=f"{agent_name}-chat", cwd=os.getcwd())
        self.current_session_id = session["id"]
        self._last_transcript = ""
        self._add_notice(f"Opened chat with {agent_name}.", kind="status")
        return session

    def _required_agents_for_workflow(self, workflow: dict[str, Any]) -> list[str]:
        required = [workflow["main_agent"]]
        for step in workflow.get("steps", []):
            if step["agent_name"] not in required:
                required.append(step["agent_name"])
        return required

    def _approval_mode_block_reason(self, workflow: dict[str, Any], *, approval_mode: str) -> str:
        if approval_mode != ApprovalMode.PLAN.value:
            return ""
        for step in workflow.get("steps", []):
            if step.get("task_type") == TaskType.IMPLEMENT.value:
                return "Approval mode 'plan' blocks implement steps. Use /approval-mode default or auto-edit."
        return ""

    def _ensure_agent_ready(self, agent_name: str, *, interactive: bool) -> dict[str, Any]:
        status = self.service.check_agent_login(agent_name, cwd=os.getcwd())
        self.login_status[agent_name] = status
        if interactive and status["status"] == "needs_login":
            self._add_notice(status["message"], kind="error")
            with self.suspend():
                self.service.launch_login(agent_name, cwd=os.getcwd())
            status = self.service.check_agent_login(agent_name, cwd=os.getcwd())
            self.login_status[agent_name] = status
        self.refresh_ui()
        return status

    def _refresh_logins(self) -> None:
        statuses = self.service.check_logins(cwd=os.getcwd())
        self.login_status = {item["agent_name"]: item for item in statuses}

    def _add_notice(self, text: str, *, kind: str = "system") -> None:
        stamp = time.strftime("%H:%M:%S")
        for line in text.splitlines():
            self.relay_notices.append({"line": f"[{stamp}] {line}", "kind": kind})

    def _prune_notices_for_chat(self) -> None:
        self.relay_notices = [item for item in self.relay_notices if item.get("kind") == "error"]

    def _visible_notice_lines(self) -> list[str]:
        transcript = self._current_transcript_tail()
        manual = self._manual_transcript.strip()
        has_body = bool(transcript or manual)
        lines: list[str] = []
        for item in self.relay_notices[-12:]:
            kind = str(item.get("kind") or "system")
            if has_body and kind not in {"command", "error"}:
                continue
            line = str(item.get("line") or "").strip()
            if line:
                lines.append(line)
        return lines

    def _current_transcript_tail(self) -> str:
        if self._streaming_target:
            streamed = f"{self._streaming_prefix}{self._streaming_target[: self._streaming_index]}"
            return normalize_display_text("\n".join(streamed.splitlines()[-120:]))
        if self._active_future is not None and self.current_progress.get("status") == "running" and self._running_prompt:
            lines = [f"> {self._running_prompt}", "", thinking_label(self._running_provider, self._thinking_tick)]
            return normalize_display_text("\n".join(lines))
        if not self._last_transcript:
            return ""
        lines = self._last_transcript.splitlines()
        return normalize_display_text("\n".join(lines[-120:]))

    def _start_transcript_stream(self, transcript: str) -> None:
        prefix, body = split_transcript_for_streaming(transcript)
        self._streaming_prefix = prefix
        self._streaming_target = body
        self._streaming_index = initial_stream_index(body)

    def _update_step_state(self, index: int, status: str, summary: str, note: str) -> None:
        with self._lock:
            steps = self.current_progress.get("steps", [])
            if 0 <= index < len(steps):
                steps[index]["status"] = status
                steps[index]["summary"] = summary
                steps[index]["note"] = note
                self._progress_revision += 1

    def _set_progress_status(self, status: str, **fields: Any) -> None:
        with self._lock:
            self.current_progress["status"] = status
            self.current_progress.update(fields)
            self._progress_revision += 1

    def _find_workflow_by_name(self, name: str) -> Optional[dict[str, Any]]:
        lowered = name.strip().lower()
        for workflow in self.store.list_workflows():
            if workflow["name"].lower() == lowered:
                return workflow
        return None

    def _focus_prompt_input(self) -> None:
        try:
            input_box = self.query_one("#prompt-input", Input)
        except Exception:
            return
        if not input_box.disabled:
            input_box.focus()

    def _default_direct_workflow(self, prompt: str = "") -> dict[str, Any]:
        agent_name = self._main_provider_name()
        preferred = self.service.recommended_agents_for("direct")
        agents = self.service.list_user_agents()
        by_name = {agent["name"]: agent for agent in agents}
        if agent_name not in by_name:
            for candidate in preferred:
                if candidate in by_name:
                    agent_name = candidate
                    self.store.set_main_provider(agent_name)
                    break
        if not agent_name and agents:
            agent_name = agents[0]["name"]
            self.store.set_main_provider(agent_name)
        return {
            "id": f"workflow_{random_suffix(8)}",
            "name": "Direct",
            "main_agent": agent_name,
            "mode": "direct",
            "send_back": False,
            "steps": [],
        }

    def _format_trace_last(self) -> str:
        events = self.service.last_trace_events()
        if not events:
            return "No trace is available yet."
        lines = ["Last trace:"]
        for event in events:
            stamp = self._format_trace_timestamp(str(event.get("timestamp", "")))
            event_type = event.get("event_type", "event")
            payload = event.get("payload", {})
            if event_type == "prompt_submitted":
                lines.append(f"[{stamp}] prompt  {payload.get('prompt', '')}")
                continue
            if event_type == "direct_started":
                lines.append(f"[{stamp}] start   {payload.get('main_agent', '')}")
                continue
            if event_type == "direct_finished":
                result = str(payload.get("display_text") or "").strip() or "Finished."
                lines.append(f"[{stamp}] done    {payload.get('main_agent', '')} -> {result}")
                continue
            if event_type == "workflow_step_started":
                step = payload.get("step") or {}
                lines.append(f"[{stamp}] step    {step.get('agent_name', '')} {friendly_task_label(step.get('task_type', 'custom'))}")
                continue
            if event_type == "workflow_step_finished":
                step = payload.get("step") or {}
                result = summarize_result(payload.get("normalized_result") or {})
                lines.append(f"[{stamp}] step    {step.get('agent_name', '')} -> {result}")
                continue
            if event_type == "workflow_send_back_finished":
                result = summarize_result(payload.get("normalized_result") or {})
                lines.append(f"[{stamp}] send    {payload.get('main_agent', '')} -> {result}")
                continue
            if event_type == "workflow_finished":
                lines.append(f"[{stamp}] final   {payload.get('summary', '')}")
                continue
            if event_type == "workflow_error":
                lines.append(f"[{stamp}] error   {payload.get('error', '')}")
                continue
            lines.append(f"[{stamp}] {event_type}")
        return "\n".join(lines)

    def _rerun_last_prompt(self, *, resume: bool) -> None:
        last = self.service.last_prompt_context()
        if not last:
            self._add_notice("There is no previous prompt to replay.", kind="error")
            return
        prompt = str(last["prompt"])
        workflow = dict(last["workflow"])
        step_count = len(workflow.get("steps", []))
        completed = list(last.get("completed_step_indexes") or [])
        send_back_pending = bool(workflow.get("send_back")) and step_count > 0 and len(completed) >= step_count and not last.get("send_back_finished")
        if resume and (not last.get("finished") or send_back_pending):
            resume_from_step = 0
            if completed:
                resume_from_step = max(completed) + 1
            workflow["resume_from_step"] = resume_from_step
            workflow["resume_parent_run_id"] = ((last.get("last_completed_step") or {}).get("run_id") or "")
            workflow["resume_last_completed_step"] = last.get("last_completed_step") or {}
            if send_back_pending:
                self._add_notice("Resuming the last workflow from send-back.", kind="command")
            elif last.get("failed_step_index") is not None:
                failed_step = int(last["failed_step_index"]) + 1
                reason = str(last.get("failed_step_error") or "").strip()
                if reason:
                    self._add_notice(f"Resuming from step {failed_step} after failure: {reason}", kind="command")
                else:
                    self._add_notice(f"Resuming from step {failed_step}.", kind="command")
            else:
                self._add_notice(f"Resuming the last workflow from step {resume_from_step + 1}.", kind="command")
        elif resume:
            self._add_notice("The last workflow already finished. Re-running it.", kind="command")
        else:
            self._add_notice("Re-running the last prompt with the same workflow.", kind="command")
        self._start_prompt_run(prompt, workflow)

    def _main_provider_name(self) -> str:
        current = self.store.get_main_provider()
        if current:
            return current
        agents = self.service.list_user_agents()
        by_name = {agent["name"]: agent for agent in agents}
        for candidate in self.service.recommended_agents_for("direct"):
            if candidate in by_name:
                self.store.set_main_provider(candidate)
                return candidate
        if agents:
            self.store.set_main_provider(agents[0]["name"])
            return agents[0]["name"]
        return ""

    def _format_trace_timestamp(self, value: str) -> str:
        if not value:
            return "--:--:--"
        try:
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
            local = parsed.astimezone(ZoneInfo("Asia/Seoul"))
            return local.strftime("%H:%M:%S")
        except Exception:
            return value[11:19] if len(value) >= 19 else "--:--:--"

    def _open_details(self) -> None:
        payload = self.last_run_details or self.current_progress
        self.push_screen(DetailScreen(json.dumps(payload, ensure_ascii=True, indent=2)))

    def _visible_transcript_text(self) -> str:
        parts = []
        notice_lines = self._visible_notice_lines()
        if notice_lines:
            parts.extend(notice_lines)
        transcript = self._current_transcript_tail()
        if transcript:
            if parts:
                parts.append("")
            parts.append(transcript)
        manual = self._manual_transcript.strip()
        if manual:
            if parts:
                parts.append("")
            parts.append(manual)
        if not parts:
            parts.append("Type a prompt below. If you start with /, command help opens.")
        return normalize_display_text("\n".join(parts))

    def _build_workflow_transcript(
        self,
        prompt: str,
        workflow: dict[str, Any],
        original_output: Optional[dict[str, Any]],
        final_output: Optional[dict[str, Any]],
        completed_views: list[dict[str, Any]],
        last_view: Optional[dict[str, Any]],
    ) -> str:
        lines = [f"> {prompt}", ""]
        if workflow.get("mode") == "direct":
            if final_output:
                answer = str(final_output.get("display_text") or "").strip()
                if not answer:
                    normalized = final_output.get("normalized_result") or {}
                    answer = summarize_result(normalized)
                raw_output = normalize_display_text(final_output.get("raw_output") or "")
                if answer and answer != "No result yet.":
                    lines.append(answer)
                elif raw_output.strip():
                    lines.append(raw_output.strip())
                else:
                    lines.append("Finished.")
                return "\n".join(lines).strip()
            if last_view:
                normalized = ((last_view.get("result") or {}).get("normalized_result")) or {}
                lines.append(summarize_result(normalized))
                return "\n".join(lines).strip()
            lines.append("Finished.")
            return "\n".join(lines).strip()
        if original_output:
            lines.append(
                render_result_block(
                    f"Original - {original_output['agent']['name']}",
                    str(original_output.get("display_text") or original_output.get("raw_output") or ""),
                )
            )
            lines.append("")
        for view in completed_views:
            task_type = str(((view.get("packet") or {}).get("task_type")) or TaskType.CUSTOM.value)
            agent_name = str(((view.get("target_agent") or {}).get("name")) or "")
            run_status = str(((view.get("run") or {}).get("status")) or "")
            title = f"{friendly_task_label(task_type)} - {agent_name}"
            if run_status and run_status != RunStatus.COMPLETED.value:
                title += f" ({friendly_status_label(run_status)})"
            body = render_normalized_result(
                task_type,
                ((view.get("result") or {}).get("normalized_result")) or {},
                str((view.get("result") or {}).get("raw_output") or ""),
            )
            lines.append(render_result_block(title, body))
            lines.append("")
        if final_output:
            answer = str(final_output.get("display_text") or "").strip()
            if not answer:
                normalized = final_output.get("normalized_result") or {}
                answer = render_normalized_result(TaskType.CUSTOM.value, normalized, final_output.get("raw_output") or "")
            lines.append(render_result_block(f"Final - {final_output['agent']['name']}", answer))
            return "\n".join(lines).strip()
        if last_view and last_view not in completed_views:
            task_type = str(((last_view.get("packet") or {}).get("task_type")) or TaskType.CUSTOM.value)
            agent_name = str(((last_view.get("target_agent") or {}).get("name")) or "")
            body = render_normalized_result(
                task_type,
                ((last_view.get("result") or {}).get("normalized_result")) or {},
                str((last_view.get("result") or {}).get("raw_output") or ""),
            )
            lines.append(render_result_block(f"{friendly_task_label(task_type)} - {agent_name}", body))
            return "\n".join(lines).strip()
        if completed_views and not final_output:
            last_completed = completed_views[-1]
            run_status = str(((last_completed.get("run") or {}).get("status")) or "")
            if run_status and run_status != RunStatus.COMPLETED.value:
                error_text = str(((last_completed.get("run") or {}).get("error")) or "")
                summary = error_text or "The workflow stopped before a final result was produced."
                lines.append(render_result_block("Workflow Status", summary))
                return "\n".join(lines).strip()
        lines.append("Finished.")
        return "\n".join(lines).strip()

    def _last_result_text(self) -> str:
        payload = self.last_run_details or self.current_progress
        return json.dumps(payload, ensure_ascii=True, indent=2)

    def _copy_text(self, text: str, *, label: str) -> None:
        normalized = normalize_display_text(text)
        try:
            proc = subprocess.run(["pbcopy"], input=normalized, text=True, capture_output=True, check=False)
            if proc.returncode == 0:
                self._add_notice(f"Copied {label} to the clipboard.")
                return
        except FileNotFoundError:
            pass
        self.copy_to_clipboard(normalized)
        self._add_notice(f"Copied {label} to the app clipboard.")

    def _export_text(self, text: str, *, stem: str) -> Path:
        path = exports_dir() / export_file_name(stem)
        path.write_text(normalize_display_text(text), encoding="utf-8")
        return path

    def _format_exception_summary(self, exc: Exception) -> str:
        if isinstance(exc, FileNotFoundError):
            if getattr(exc, "filename", None):
                return f"Missing command or file: {exc.filename}"
            return "Missing command or file."
        return str(exc) or exc.__class__.__name__

    def _format_exception_notice(self, exc: Exception) -> str:
        summary = self._format_exception_summary(exc)
        if isinstance(exc, FileNotFoundError):
            return f"Relay hit an error: {summary}"
        return f"Relay hit an error: {summary}"


def preset_definitions() -> dict[str, list[tuple[str, str]]]:
    return {
        "Main AI -> Codex Review -> Send Back": [("codex", TaskType.REVIEW.value)],
        "Main AI -> Gemini Research -> Send Back": [("gemini", TaskType.WEB_RESEARCH.value)],
        "Main AI -> Gemini Simplify -> Send Back": [("gemini", TaskType.OPTIMIZE_PROMPT.value)],
        "Main AI -> Gemini Research -> Codex Implement -> Send Back": [
            ("gemini", TaskType.WEB_RESEARCH.value),
            ("codex", TaskType.IMPLEMENT.value),
        ],
    }


def build_preset_workflow(
    preset_name: str,
    agents: list[dict[str, Any]],
    *,
    main_agent: str,
) -> Optional[dict[str, Any]]:
    specs = preset_definitions().get(preset_name)
    if not specs:
        return None
    by_kind = {agent["kind"]: agent["name"] for agent in agents}
    steps = []
    for index, (kind, task_type) in enumerate(specs, start=1):
        agent_name = by_kind.get(kind)
        if not agent_name:
            continue
        steps.append(
            {
                "id": f"step_{index}",
                "agent_name": agent_name,
                "task_type": task_type,
                "label": "",
            }
        )
    return {
        "id": f"workflow_{random_suffix(8)}",
        "name": preset_name,
        "main_agent": main_agent,
        "mode": "workflow",
        "send_back": True,
        "steps": steps,
    }


def run_tui(service: RelayService, *, inline: bool = True) -> None:
    RelayShellApp(service, inline_mode=inline).run(inline=inline, inline_no_clear=inline, mouse=False)

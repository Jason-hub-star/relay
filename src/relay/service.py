from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import time
import json
import datetime as dt
from pathlib import Path
from typing import Any, Dict, Optional

from relay import __version__
from relay.adapters import (
    build_live_command,
    check_agent_readiness,
    launch_login_flow,
    run_headless,
    send_to_live_session,
)
from relay.config import events_log_path, sockets_dir, transcripts_dir
from relay.context import capture_context_snapshot
from relay.models import (
    ApprovalMode,
    AgentKind,
    ContextPolicy,
    ReturnMode,
    ReturnStatus,
    ResumeStrategy,
    RunStatus,
    SessionStatus,
    TaskType,
)
from relay.prompts import build_delegate_prompt, build_return_prompt, extract_display_text, normalize_output, schema_name
from relay.repository import RelayRepository
from relay.schemas import DEFAULT_CONTEXT_POLICY, OUTPUT_SCHEMAS, strict_json_schema
from relay.session_client import SessionClient


INTERNAL_AGENT_PREFIX = "_relay_"

RECOMMENDED_FOR_BY_KIND: dict[str, list[str]] = {
    AgentKind.CLAUDE.value: ["direct", "plan", "final-answer"],
    AgentKind.CODEX.value: ["review", "implement"],
    AgentKind.GEMINI.value: ["research", "context"],
    AgentKind.QWEN.value: ["fast-direct", "commands"],
}

EXPERIMENTAL_FOR_BY_KIND: dict[str, list[str]] = {
    AgentKind.CLAUDE.value: ["live-origin"],
    AgentKind.CODEX.value: ["live-origin"],
    AgentKind.GEMINI.value: [],
    AgentKind.QWEN.value: [],
}


class RelayService:
    def __init__(self, repository: Optional[RelayRepository] = None) -> None:
        self.repo = repository or RelayRepository()
        self._child_processes: dict[str, subprocess.Popen[Any]] = {}

    def add_agent(self, *, name: str, kind: str, launch_command: str, resume_strategy: str) -> Dict[str, Any]:
        supports = {
            "resume_same_session": True,
            "structured_output": True,
            "streaming": kind in {"claude", "codex", "gemini", "qwen"},
        }
        return self.repo.add_agent(
            name=name,
            kind=AgentKind(kind).value,
            launch_command=launch_command,
            resume_strategy=ResumeStrategy(resume_strategy).value,
            supports=supports,
            default_output_mode="json",
        )

    def list_agents(self) -> list[Dict[str, Any]]:
        return self.repo.list_agents()

    def list_user_agents(self) -> list[Dict[str, Any]]:
        return [agent for agent in self.list_agents() if not self._is_internal_agent(agent)]

    def agent_profile(self, agent_or_name: Dict[str, Any] | str) -> Dict[str, Any]:
        agent = agent_or_name if isinstance(agent_or_name, dict) else self.repo.get_agent(name=agent_or_name)
        if not agent:
            raise ValueError("unknown agent")
        kind = str(agent["kind"])
        recommended_for = list(RECOMMENDED_FOR_BY_KIND.get(kind, []))
        experimental_for = list(EXPERIMENTAL_FOR_BY_KIND.get(kind, []))
        return {
            "recommended_for": recommended_for,
            "experimental_for": experimental_for,
            "fast": "fast-direct" in recommended_for,
            "reliable": kind in {AgentKind.CLAUDE.value, AgentKind.CODEX.value, AgentKind.GEMINI.value, AgentKind.QWEN.value},
        }

    def list_agent_profiles(self) -> list[Dict[str, Any]]:
        profiles = []
        for agent in self.list_user_agents():
            merged = dict(agent)
            merged.update(self.agent_profile(agent))
            profiles.append(merged)
        return profiles

    def recommended_agents_for(self, capability: str) -> list[str]:
        matched = []
        fallback = []
        for agent in self.list_user_agents():
            profile = self.agent_profile(agent)
            if capability in profile["recommended_for"]:
                matched.append(agent["name"])
            else:
                fallback.append(agent["name"])
        return matched + fallback

    def list_sessions(self) -> list[Dict[str, Any]]:
        return self.repo.list_sessions()

    def list_runs(self) -> list[Dict[str, Any]]:
        return self.repo.list_runs()

    def list_presets(self) -> list[Dict[str, Any]]:
        return self.repo.list_presets()

    def append_event(self, event_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        event = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event_type": event_type,
            "payload": payload,
        }
        path = events_log_path()
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=True) + "\n")
        return event

    def recent_events(self, limit: int = 50) -> list[Dict[str, Any]]:
        path = events_log_path()
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        events = []
        for line in lines[-limit:]:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return events

    def last_trace_events(self, limit: int = 200) -> list[Dict[str, Any]]:
        events = self.recent_events(limit=limit)
        if not events:
            return []
        finish_index = None
        for index in range(len(events) - 1, -1, -1):
            if events[index].get("event_type") in {"workflow_finished", "workflow_error"}:
                finish_index = index
                break
        if finish_index is None:
            return []
        finished = events[finish_index]
        payload = finished.get("payload", {})
        target_prompt = payload.get("prompt")
        workflow_payload = payload.get("workflow") if isinstance(payload.get("workflow"), dict) else {}
        target_workflow_id = workflow_payload.get("id")
        start_index = 0
        for index in range(finish_index, -1, -1):
            event = events[index]
            event_payload = event.get("payload", {})
            event_workflow = event_payload.get("workflow") if isinstance(event_payload.get("workflow"), dict) else {}
            event_workflow_id = event_payload.get("workflow_id") or event_workflow.get("id")
            same_workflow = bool(target_workflow_id and event_workflow_id == target_workflow_id)
            same_prompt = target_prompt is not None and event_payload.get("prompt") == target_prompt
            relevant = same_workflow if target_workflow_id else same_prompt
            if not relevant:
                continue
            if event.get("event_type") in {"prompt_submitted", "workflow_started", "direct_started"}:
                start_index = index
                break
        for index in range(start_index, -1, -1):
            event = events[index]
            event_payload = event.get("payload", {})
            event_workflow = event_payload.get("workflow") if isinstance(event_payload.get("workflow"), dict) else {}
            event_workflow_id = event_payload.get("workflow_id") or event_workflow.get("id")
            same_workflow = bool(target_workflow_id and event_workflow_id == target_workflow_id)
            same_prompt = target_prompt is not None and event_payload.get("prompt") == target_prompt
            relevant = same_workflow if target_workflow_id else same_prompt
            if not relevant:
                continue
            if event.get("event_type") == "prompt_submitted":
                start_index = index
                break
        selected: list[Dict[str, Any]] = []
        for event in events[start_index : finish_index + 1]:
            event_payload = event.get("payload", {})
            event_workflow = event_payload.get("workflow") if isinstance(event_payload.get("workflow"), dict) else {}
            event_workflow_id = event_payload.get("workflow_id") or event_workflow.get("id")
            same_workflow = bool(target_workflow_id and event_workflow_id == target_workflow_id)
            same_prompt = target_prompt is not None and event_payload.get("prompt") == target_prompt
            relevant = same_workflow if target_workflow_id else same_prompt
            if relevant:
                selected.append(event)
        return selected

    def last_prompt_context(self, limit: int = 200) -> Optional[Dict[str, Any]]:
        events = self.recent_events(limit=limit)
        prompt_index = None
        for index in range(len(events) - 1, -1, -1):
            if events[index].get("event_type") == "prompt_submitted":
                prompt_index = index
                break
        if prompt_index is None:
            return None
        prompt_event = events[prompt_index]
        payload = prompt_event.get("payload", {})
        prompt = payload.get("prompt")
        workflow = payload.get("workflow")
        if not isinstance(prompt, str) or not isinstance(workflow, dict):
            return None
        matched_events: list[Dict[str, Any]] = [prompt_event]
        finished = False
        summary = ""
        status = "running"
        workflow_id = workflow.get("id")
        completed_step_indexes: list[int] = []
        failed_step_index: Optional[int] = None
        failed_step_error = ""
        send_back_finished = False
        last_completed_step: Optional[Dict[str, Any]] = None
        for event in events[prompt_index + 1 :]:
            event_type = event.get("event_type")
            event_payload = event.get("payload", {})
            event_workflow = event_payload.get("workflow") if isinstance(event_payload.get("workflow"), dict) else {}
            event_workflow_id = event_payload.get("workflow_id") or event_workflow.get("id")
            same_workflow = bool(workflow_id and event_workflow_id == workflow_id)
            same_prompt = event_payload.get("prompt") == prompt
            relevant = same_workflow if workflow_id else same_prompt
            if not relevant:
                continue
            matched_events.append(event)
            if event_type == "workflow_step_finished":
                step_index = event_payload.get("step_index")
                step_status = event_payload.get("status")
                if isinstance(step_index, int) and step_status == RunStatus.COMPLETED.value:
                    completed_step_indexes.append(step_index)
                    last_completed_step = {
                        "step_index": step_index,
                        "step": event_payload.get("step") or {},
                        "run_id": event_payload.get("run_id"),
                        "normalized_result": event_payload.get("normalized_result") or {},
                    }
                elif isinstance(step_index, int) and step_status != RunStatus.COMPLETED.value:
                    failed_step_index = step_index
                    failed_step_error = str(event_payload.get("error") or "")
            elif event_type == "workflow_send_back_finished":
                send_back_finished = event_payload.get("status") == RunStatus.COMPLETED.value
            if event_type == "workflow_finished":
                finished = True
                status = "completed"
                summary = str(event_payload.get("summary") or "")
            elif event_type == "workflow_error":
                finished = False
                status = "failed"
                summary = str(event_payload.get("error") or "")
        return {
            "prompt": prompt,
            "workflow": workflow,
            "finished": finished,
            "status": status,
            "summary": summary,
            "events": matched_events,
            "completed_step_indexes": sorted(set(completed_step_indexes)),
            "failed_step_index": failed_step_index,
            "failed_step_error": failed_step_error,
            "send_back_finished": send_back_finished,
            "last_completed_step": last_completed_step,
        }

    def cleanup_stale_state(
        self,
        *,
        now: Optional[dt.datetime] = None,
        session_stale_seconds: int = 1800,
        run_stale_seconds: int = 1800,
    ) -> Dict[str, int]:
        current = now or dt.datetime.utcnow()
        closed_sessions = 0
        failed_runs = 0
        for session in self.repo.list_sessions():
            if session["status"] != SessionStatus.ACTIVE.value:
                continue
            if not self._is_stale_timestamp(session.get("updated_at"), current, session_stale_seconds):
                continue
            try:
                SessionClient(session["external_session_ref"]).status()
                continue
            except OSError:
                self.repo.update_session(session["id"], status=SessionStatus.CLOSED.value)
                closed_sessions += 1
        for run in self.repo.list_runs():
            if run["status"] not in {RunStatus.QUEUED.value, RunStatus.RUNNING.value}:
                continue
            if not self._is_stale_timestamp(run.get("created_at"), current, run_stale_seconds):
                continue
            self.repo.update_run(
                run["id"],
                status=RunStatus.FAILED.value,
                error="Marked stale during startup cleanup.",
                completed_at=current.replace(microsecond=0).isoformat() + "Z",
            )
            failed_runs += 1
        if closed_sessions or failed_runs:
            self.append_event(
                "startup_cleanup",
                {
                    "closed_sessions": closed_sessions,
                    "failed_runs": failed_runs,
                },
            )
        return {
            "closed_sessions": closed_sessions,
            "failed_runs": failed_runs,
        }

    def check_agent_login(self, agent_name: str, *, cwd: Optional[str] = None) -> Dict[str, Any]:
        agent = self.repo.get_agent(name=agent_name)
        if not agent:
            raise ValueError(f"unknown agent: {agent_name}")
        result = check_agent_readiness(agent, cwd=str(Path(cwd or os.getcwd()).resolve()))
        return {
            "agent_name": agent["name"],
            "kind": agent["kind"],
            "status": result.status,
            "message": result.message,
            "details": result.details,
            "login_command": result.login_command,
        }

    def check_logins(self, *, cwd: Optional[str] = None) -> list[Dict[str, Any]]:
        return [self.check_agent_login(agent["name"], cwd=cwd) for agent in self.list_user_agents()]

    def launch_login(self, agent_name: str, *, cwd: Optional[str] = None) -> Dict[str, Any]:
        agent = self.repo.get_agent(name=agent_name)
        if not agent:
            raise ValueError(f"unknown agent: {agent_name}")
        readiness = self.check_agent_login(agent_name, cwd=cwd)
        if readiness["status"] != "needs_login":
            return readiness
        launch_login_flow(agent, cwd=str(Path(cwd or os.getcwd()).resolve()))
        return self.check_agent_login(agent_name, cwd=cwd)

    def run_headless_prompt(
        self,
        *,
        agent_name: str,
        prompt: str,
        cwd: Optional[str] = None,
        task_type: str = TaskType.CUSTOM.value,
    ) -> Dict[str, Any]:
        agent = self.repo.get_agent(name=agent_name)
        if not agent:
            raise ValueError(f"unknown agent: {agent_name}")
        task_enum = TaskType(task_type)
        cwd_path = str(Path(cwd or os.getcwd()).resolve())
        result = run_headless(
            agent,
            prompt,
            cwd=cwd_path,
            timeout=self._headless_timeout(agent),
            output_schema=strict_json_schema(OUTPUT_SCHEMAS[task_enum]),
        )
        raw_output = result.stdout or result.stderr
        return {
            "agent": agent,
            "task_type": task_enum.value,
            "status": RunStatus.COMPLETED.value if result.returncode == 0 else RunStatus.FAILED.value,
            "raw_output": raw_output,
            "normalized_result": normalize_output(task_enum, raw_output),
            "error": (result.stderr or raw_output) if result.returncode != 0 else None,
        }

    def run_direct_prompt(
        self,
        *,
        agent_name: str,
        prompt: str,
        cwd: Optional[str] = None,
    ) -> Dict[str, Any]:
        agent = self.repo.get_agent(name=agent_name)
        if not agent:
            raise ValueError(f"unknown agent: {agent_name}")
        cwd_path = str(Path(cwd or os.getcwd()).resolve())
        result = run_headless(
            agent,
            prompt,
            cwd=cwd_path,
            timeout=self._headless_timeout(agent),
            raw_output=True,
        )
        raw_output = result.stdout or result.stderr
        display_text = extract_display_text(raw_output)
        return {
            "agent": agent,
            "status": RunStatus.COMPLETED.value if result.returncode == 0 else RunStatus.FAILED.value,
            "raw_output": raw_output,
            "display_text": display_text,
            "error": (result.stderr or raw_output) if result.returncode != 0 else None,
        }

    def open_session(self, *, agent_name: str, label: str, cwd: Optional[str] = None) -> Dict[str, Any]:
        agent = self.repo.get_agent(name=agent_name)
        if not agent:
            raise ValueError(f"unknown agent: {agent_name}")
        cwd_path = str(Path(cwd or os.getcwd()).resolve())
        timestamp = int(time.time() * 1000)
        socket_path = sockets_dir() / f"{agent['name']}-{timestamp}.sock"
        log_path = transcripts_dir() / f"{agent['name']}-{timestamp}.log"
        source_root = Path(__file__).resolve().parents[1]
        env = os.environ.copy()
        current_pythonpath = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = f"{source_root}{os.pathsep}{current_pythonpath}" if current_pythonpath else str(source_root)
        if not env.get("TERM") or env.get("TERM") == "dumb":
            env["TERM"] = "xterm-256color"
        env.setdefault("COLORTERM", "truecolor")
        command = [
            sys.executable,
            "-m",
            "relay.session_host",
            "--socket-path",
            str(socket_path),
            "--log-path",
            str(log_path),
            "--cwd",
            cwd_path,
            "--",
        ] + build_live_command(agent)
        proc = subprocess.Popen(
            command,
            cwd=cwd_path,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            env=env,
            start_new_session=True,
        )
        self._child_processes[str(socket_path)] = proc
        self._wait_for_socket(socket_path)
        session = self.repo.add_session(
            agent_id=agent["id"],
            label=label,
            cwd=cwd_path,
            external_session_ref=str(socket_path),
            status=SessionStatus.ACTIVE.value,
            metadata={
                "transcript_path": str(log_path),
                "relay_version": __version__,
            },
        )
        return session

    def mark_session_active(self, session_id: str) -> Dict[str, Any]:
        return self.repo.update_session(session_id, status=SessionStatus.ACTIVE.value)

    def close_session(self, session_id: str) -> Dict[str, Any]:
        session = self._require_session(session_id)
        try:
            SessionClient(session["external_session_ref"]).close()
        except OSError:
            pass
        proc = self._child_processes.pop(session["external_session_ref"], None)
        if proc is not None:
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=2)
        return self.repo.update_session(session_id, status=SessionStatus.CLOSED.value)

    def capture_context(self, *, session_id: str, task_type: str, context_policy: Optional[str] = None) -> Dict[str, Any]:
        session = self._require_session(session_id)
        task_enum = TaskType(task_type)
        policy_enum = ContextPolicy(context_policy or DEFAULT_CONTEXT_POLICY[task_enum].value)
        snapshot_payload = capture_context_snapshot(session=session, task_type=task_enum, context_policy=policy_enum)
        return self.repo.add_context_snapshot(session_id=session_id, **snapshot_payload)

    def delegate(
        self,
        *,
        from_session_id: str,
        to_agent_name: str,
        task_type: str,
        title: Optional[str] = None,
        context_policy: Optional[str] = None,
        instructions: Optional[str] = None,
        parent_run_id: Optional[str] = None,
        extra_input_payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        session = self._require_session(from_session_id)
        target_agent = self.repo.get_agent(name=to_agent_name)
        if not target_agent:
            raise ValueError(f"unknown target agent: {to_agent_name}")
        task_enum = TaskType(task_type)
        policy_enum = ContextPolicy(context_policy or DEFAULT_CONTEXT_POLICY[task_enum].value)
        snapshot = self.capture_context(session_id=from_session_id, task_type=task_enum.value, context_policy=policy_enum.value)
        parent_result = self.repo.get_run_result(parent_run_id) if parent_run_id else None
        packet = self.repo.add_task_packet(
            origin_session_id=from_session_id,
            target_agent_id=target_agent["id"],
            task_type=task_enum.value,
            title=title or f"{task_enum.value} from {session['label']}",
            context_policy=policy_enum.value,
            instructions=instructions or self._default_instruction(task_enum),
            origin_snapshot_id=snapshot["id"],
            input_payload={
                "goal": snapshot["goal"],
                "required_output_schema": schema_name(task_enum),
                "artifacts": snapshot["artifacts"],
                "parent_result": (parent_result or {}).get("normalized_result", {}),
                **(extra_input_payload or {}),
            },
            parent_run_id=parent_run_id,
        )
        run = self.repo.add_run(
            packet_id=packet["id"],
            origin_session_id=from_session_id,
            status=RunStatus.QUEUED.value,
            return_status=ReturnStatus.PENDING.value,
        )
        self.repo.update_run(run["id"], status=RunStatus.RUNNING.value)
        prompt = build_delegate_prompt(packet, target_agent)
        packet, prompt = self._prepare_delegate_packet(
            packet=packet,
            prompt=prompt,
            target_agent=target_agent,
        )
        result = run_headless(
            target_agent,
            prompt,
            cwd=session["cwd"],
            timeout=self._headless_timeout(target_agent),
            output_schema=strict_json_schema(OUTPUT_SCHEMAS[task_enum]),
        )
        if result.returncode == 124 and target_agent["kind"] == AgentKind.CODEX.value and packet["context_policy"] != ContextPolicy.COMPACT.value:
            packet, prompt = self._compact_retry_packet(
                packet=packet,
                target_agent=target_agent,
            )
            result = run_headless(
                target_agent,
                prompt,
                cwd=session["cwd"],
                timeout=self._compact_retry_timeout(target_agent),
                output_schema=strict_json_schema(OUTPUT_SCHEMAS[task_enum]),
            )
        raw_output = result.stdout or result.stderr
        normalized = normalize_output(task_enum, raw_output)
        status = RunStatus.COMPLETED.value if result.returncode == 0 else RunStatus.FAILED.value
        self.repo.save_run_result(
            run_id=run["id"],
            raw_output=raw_output,
            normalized_result=normalized,
            output_schema=schema_name(task_enum),
        )
        completed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        run = self.repo.update_run(
            run["id"],
            status=status,
            completed_at=completed_at,
            error=(result.stderr or raw_output) if result.returncode != 0 else None,
        )
        return self.inspect_run(run["id"])

    def return_run(self, *, run_id: str, mode: str = ReturnMode.RESUME.value) -> Dict[str, Any]:
        run = self._require_run(run_id)
        if run["return_status"] == ReturnStatus.RETURNED.value:
            return self.inspect_run(run_id)
        packet = self._require_packet(run["packet_id"])
        snapshot = self._require_snapshot(packet["origin_snapshot_id"])
        target_agent = self._require_agent(packet["target_agent_id"])
        origin_session = self._require_session(run["origin_session_id"])
        origin_agent = self._require_agent(origin_session["agent_id"])
        run_result = self._require_run_result(run_id)
        prompt = build_return_prompt(
            origin_goal=snapshot["goal"],
            contributor_name=target_agent["name"],
            task_type=packet["task_type"],
            normalized_result=run_result["normalized_result"],
        )

        success = send_to_live_session(origin_session, prompt)
        final_mode = ReturnMode.RESUME.value
        fallback_output = None
        status = "success"
        if not success:
            final_mode = ReturnMode.FALLBACK_NEW_PROMPT.value
            if mode == ReturnMode.RESUME.value or mode == ReturnMode.FALLBACK_NEW_PROMPT.value:
                fallback = run_headless(origin_agent, prompt, cwd=origin_session["cwd"])
                fallback_output = fallback.stdout or fallback.stderr
                status = "success" if fallback.returncode == 0 else "failed"
            else:
                status = "failed"
        self.repo.add_return_event(
            run_id=run_id,
            origin_session_id=origin_session["id"],
            attempt_mode=mode,
            final_mode=final_mode,
            status=status,
            injected_prompt=prompt,
            fallback_output=fallback_output,
        )
        self.repo.update_run(
            run_id,
            return_status=ReturnStatus.RETURNED.value if status == "success" else ReturnStatus.FAILED.value,
        )
        return self.inspect_run(run_id)

    def archive_run(self, run_id: str) -> Dict[str, Any]:
        self._require_run(run_id)
        self.repo.update_run(run_id, archived=1, status=RunStatus.ARCHIVED.value)
        return self.inspect_run(run_id)

    def inspect_run(self, run_id: str) -> Dict[str, Any]:
        run = self._require_run(run_id)
        packet = self._require_packet(run["packet_id"])
        origin_session = self._require_session(run["origin_session_id"])
        target_agent = self._require_agent(packet["target_agent_id"])
        snapshot = self._require_snapshot(packet["origin_snapshot_id"])
        result = self.repo.get_run_result(run_id)
        return {
            "run": run,
            "packet": packet,
            "origin_session": origin_session,
            "target_agent": target_agent,
            "snapshot": snapshot,
            "result": result,
        }

    def rerun(self, run_id: str) -> Dict[str, Any]:
        run_view = self.inspect_run(run_id)
        packet = run_view["packet"]
        target_agent = self._require_agent(packet["target_agent_id"])
        return self.delegate(
            from_session_id=packet["origin_session_id"],
            to_agent_name=target_agent["name"],
            task_type=packet["task_type"],
            title=packet["title"],
            context_policy=packet["context_policy"],
            instructions=packet["instructions"],
            parent_run_id=packet.get("parent_run_id"),
        )

    def run_preset(self, *, preset_name: str, from_session_id: str, to_agent_name: str) -> Dict[str, Any]:
        preset = self.repo.get_preset(preset_name)
        if not preset:
            raise ValueError(f"unknown preset: {preset_name}")
        return self.delegate(
            from_session_id=from_session_id,
            to_agent_name=to_agent_name,
            task_type=preset["task_type"],
            title=preset["name"],
            context_policy=preset["default_context_policy"],
            instructions=preset["instruction_template"],
        )

    def transcript(self, session_id: str) -> str:
        session = self._require_session(session_id)
        metadata = session["metadata"]
        path = metadata.get("transcript_path")
        if not path:
            return ""
        file_path = Path(path)
        if not file_path.exists():
            return ""
        return file_path.read_text(encoding="utf-8", errors="replace")

    def build_parallel_test_matrix(
        self,
        readiness: list[Dict[str, Any]],
        *,
        cwd: Optional[str] = None,
    ) -> list[Dict[str, Any]]:
        ready_by_kind = {item["kind"]: item["agent_name"] for item in readiness if item["status"] == "ready"}
        scenarios: list[Dict[str, Any]] = []
        scenario_index = 1

        def add_scenario(title: str, task_label: str, steps: list[Dict[str, Any]], *, experimental: bool = False) -> None:
            nonlocal scenario_index
            normalized_steps = []
            for step in steps:
                normalized_steps.append(
                    {
                        "context_policy": ContextPolicy.COMPACT.value,
                        **step,
                    }
                )
            scenarios.append(
                {
                    "id": f"matrix_{scenario_index:04d}",
                    "title": title,
                    "task_label": task_label,
                    "steps": normalized_steps,
                    "cwd": str(Path(cwd or os.getcwd()).resolve()),
                    "experimental": experimental,
                }
            )
            scenario_index += 1

        direct_specs = [
            ("claude", "Claude direct handoff", "review"),
            ("codex", "Codex direct handoff", "review"),
            ("gemini", "Gemini direct handoff", "optimize_prompt"),
            ("qwen", "Qwen direct handoff", "implement"),
        ]
        for kind, title, task_type in direct_specs:
            agent_name = ready_by_kind.get(kind)
            if not agent_name:
                continue
            add_scenario(
                title,
                task_type,
                [
                    {
                        "agent_name": agent_name,
                        "task_type": task_type,
                        "title": title,
                    }
                ],
                experimental=kind in {"claude", "codex"},
            )

        if ready_by_kind.get("gemini") and ready_by_kind.get("qwen"):
            add_scenario(
                "Gemini optimize -> Qwen implement",
                "optimize_prompt -> implement",
                [
                    {
                        "agent_name": ready_by_kind["gemini"],
                        "task_type": TaskType.OPTIMIZE_PROMPT.value,
                        "title": "Optimize the prompt",
                    },
                    {
                        "agent_name": ready_by_kind["qwen"],
                        "task_type": TaskType.IMPLEMENT.value,
                        "title": "Turn it into next steps",
                    },
                ],
            )

        if ready_by_kind.get("gemini") and ready_by_kind.get("codex"):
            add_scenario(
                "Gemini research -> Codex implement",
                "web_research -> implement",
                [
                    {
                        "agent_name": ready_by_kind["gemini"],
                        "task_type": TaskType.WEB_RESEARCH.value,
                        "title": "Research the topic",
                    },
                    {
                        "agent_name": ready_by_kind["codex"],
                        "task_type": TaskType.IMPLEMENT.value,
                        "title": "Turn research into changes",
                    },
                ],
                experimental=True,
            )

        task_targets = {
            TaskType.REVIEW.value: ready_by_kind.get("codex") or ready_by_kind.get("claude"),
            TaskType.IMPLEMENT.value: ready_by_kind.get("qwen") or ready_by_kind.get("codex"),
            TaskType.OPTIMIZE_PROMPT.value: ready_by_kind.get("gemini") or ready_by_kind.get("qwen"),
            TaskType.WEB_RESEARCH.value: ready_by_kind.get("gemini") or ready_by_kind.get("claude"),
            TaskType.TREE_EXPLORE.value: ready_by_kind.get("codex") or ready_by_kind.get("gemini") or ready_by_kind.get("qwen"),
            TaskType.CONTEXT_DIGEST.value: ready_by_kind.get("gemini") or ready_by_kind.get("claude") or ready_by_kind.get("qwen"),
        }
        for task_type, agent_name in task_targets.items():
            if not agent_name:
                continue
            title = f"{task_type.replace('_', ' ').title()} coverage"
            add_scenario(
                title,
                task_type,
                [
                    {
                        "agent_name": agent_name,
                        "task_type": task_type,
                        "title": title,
                    }
                ],
                experimental=self._agent_kind_for_name(agent_name) in {"claude", "codex"},
            )
        return scenarios

    def run_test_scenario(self, scenario: Dict[str, Any]) -> Dict[str, Any]:
        worker = RelayService(RelayRepository(self.repo.path))
        origin_session: Dict[str, Any] | None = None
        step_views: list[Dict[str, Any]] = []
        returned: Dict[str, Any] | None = None
        try:
            origin_session = worker._open_test_origin_session(cwd=scenario["cwd"], label=f"{INTERNAL_AGENT_PREFIX}test-{scenario['id']}")
            client = SessionClient(origin_session["external_session_ref"])
            client.send(f"Test scenario: {scenario['title']}")
            time.sleep(0.2)

            parent_run_id: Optional[str] = None
            for step in scenario["steps"]:
                view = worker.delegate(
                    from_session_id=origin_session["id"],
                    to_agent_name=step["agent_name"],
                    task_type=step["task_type"],
                    title=step["title"],
                    context_policy=step.get("context_policy"),
                    parent_run_id=parent_run_id,
                )
                step_views.append(view)
                if view["run"]["status"] != RunStatus.COMPLETED.value:
                    break
                parent_run_id = view["run"]["id"]

            if step_views and step_views[-1]["run"]["status"] == RunStatus.COMPLETED.value:
                returned = worker.return_run(run_id=step_views[-1]["run"]["id"])

            last_view = step_views[-1] if step_views else None
            success = bool(
                last_view
                and last_view["run"]["status"] == RunStatus.COMPLETED.value
                and returned
                and returned["run"]["return_status"] == ReturnStatus.RETURNED.value
            )
            summary = "Completed and sent back." if success else self._scenario_failure_summary(step_views)
            return {
                "id": scenario["id"],
                "title": scenario["title"],
                "status": "done" if success else "failed",
                "summary": summary,
                "details": {
                    "scenario": scenario,
                    "runs": [view["run"]["id"] for view in step_views],
                    "last_run": (last_view or {}).get("run", {}),
                    "returned": (returned or {}).get("run", {}),
                },
                "run_ids": [view["run"]["id"] for view in step_views],
                "experimental": scenario.get("experimental", False),
            }
        finally:
            if origin_session is not None:
                try:
                    worker.close_session(origin_session["id"])
                except Exception:
                    pass

    def experimental_notes(self) -> list[str]:
        return [
            "Experimental: Claude live chat",
            "Experimental: Codex live chat",
        ]

    def open_helper_origin_session(self, *, cwd: str, label: str) -> Dict[str, Any]:
        return self._open_test_origin_session(cwd=cwd, label=label)

    def _open_test_origin_session(self, *, cwd: str, label: str) -> Dict[str, Any]:
        agent = self._ensure_internal_origin_agent()
        return self.open_session(agent_name=agent["name"], label=label, cwd=cwd)

    def _ensure_internal_origin_agent(self) -> Dict[str, Any]:
        existing = self.repo.get_agent(name=f"{INTERNAL_AGENT_PREFIX}test-origin")
        if existing:
            return existing
        launch = f"{sys.executable} -m relay.helper_agent"
        try:
            return self.add_agent(
                name=f"{INTERNAL_AGENT_PREFIX}test-origin",
                kind=AgentKind.GEMINI.value,
                launch_command=launch,
                resume_strategy=ResumeStrategy.NATIVE.value,
            )
        except sqlite3.IntegrityError:
            existing = self.repo.get_agent(name=f"{INTERNAL_AGENT_PREFIX}test-origin")
            if existing:
                return existing
            raise

    def _scenario_failure_summary(self, step_views: list[Dict[str, Any]]) -> str:
        if not step_views:
            return "No test steps ran."
        last_view = step_views[-1]
        if last_view["run"]["status"] != RunStatus.COMPLETED.value:
            return last_view["run"]["error"] or "The task failed."
        return "The task finished, but send back did not succeed."

    def _agent_kind_for_name(self, agent_name: str) -> str:
        agent = self.repo.get_agent(name=agent_name)
        return agent["kind"] if agent else ""

    def _is_internal_agent(self, agent: Dict[str, Any]) -> bool:
        return str(agent["name"]).startswith(INTERNAL_AGENT_PREFIX)

    def _wait_for_socket(self, socket_path: Path, timeout: float = 10.0) -> None:
        started = time.time()
        while time.time() - started < timeout:
            if socket_path.exists():
                try:
                    SessionClient(str(socket_path)).status()
                    return
                except OSError:
                    time.sleep(0.1)
            else:
                time.sleep(0.1)
        raise RuntimeError(f"session socket did not come up: {socket_path}")

    def _is_stale_timestamp(self, value: Optional[str], now: dt.datetime, threshold_seconds: int) -> bool:
        if not value:
            return False
        try:
            parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return False
        age = (now - parsed).total_seconds()
        return age >= threshold_seconds

    def _prepare_delegate_packet(
        self,
        *,
        packet: Dict[str, Any],
        prompt: str,
        target_agent: Dict[str, Any],
    ) -> tuple[Dict[str, Any], str]:
        if target_agent["kind"] != AgentKind.CODEX.value:
            return packet, prompt
        if packet["context_policy"] == ContextPolicy.COMPACT.value:
            return packet, prompt
        if packet["task_type"] == TaskType.IMPLEMENT.value:
            return self._compact_retry_packet(packet=packet, target_agent=target_agent)
        threshold = int(os.environ.get("RELAY_CODEX_PROMPT_SOFT_LIMIT", "12000"))
        if len(prompt) <= threshold:
            return packet, prompt
        return self._compact_retry_packet(packet=packet, target_agent=target_agent)

    def _compact_retry_packet(
        self,
        *,
        packet: Dict[str, Any],
        target_agent: Dict[str, Any],
    ) -> tuple[Dict[str, Any], str]:
        aggressive = target_agent["kind"] == AgentKind.CODEX.value and packet["task_type"] == TaskType.IMPLEMENT.value
        compact_payload = self._compact_input_payload(packet["input_payload"], aggressive=aggressive)
        compact_instructions = (
            f"{packet['instructions']} Use the compact handoff context and focus on the highest-signal answer."
        )
        if aggressive:
            compact_instructions += " This is an aggressive compact handoff for an implement step, so avoid restating the full context."
        updated = self.repo.update_task_packet(
            packet["id"],
            context_policy=ContextPolicy.COMPACT.value,
            instructions=compact_instructions,
            input_payload=compact_payload,
        )
        return updated, build_delegate_prompt(updated, target_agent)

    def _compact_input_payload(self, payload: Dict[str, Any], *, aggressive: bool = False) -> Dict[str, Any]:
        artifacts = dict(payload["artifacts"])
        file_limit = 12 if aggressive else 20
        diff_limit = 2500 if aggressive else 4000
        status_limit = 600 if aggressive else 1200
        tree_limit = 1000 if aggressive else 1800
        convo_limit = 1200 if aggressive else 2500
        attachment_limit = 4 if aggressive else 8
        goal_limit = 300 if aggressive else 600
        nested_items = 4 if aggressive else 8
        nested_string = 300 if aggressive else 600
        compact_artifacts = {
            "files": artifacts.get("files", [])[:file_limit],
            "git_diff": self._truncate_text(artifacts.get("git_diff", ""), diff_limit),
            "git_status": self._truncate_text(artifacts.get("git_status", ""), status_limit),
            "tree_excerpt": self._truncate_text(artifacts.get("tree_excerpt", ""), tree_limit),
            "conversation_excerpt": self._truncate_text(artifacts.get("conversation_excerpt", ""), convo_limit),
            "attachments": artifacts.get("attachments", [])[:attachment_limit],
        }
        return {
            **payload,
            "goal": self._truncate_text(payload.get("goal", ""), goal_limit),
            "artifacts": compact_artifacts,
            "parent_result": self._compact_nested(payload.get("parent_result", {}), max_items=nested_items, max_string=nested_string),
            "original_result": self._compact_nested(payload.get("original_result", {}), max_items=nested_items, max_string=nested_string),
        }

    def _compact_nested(self, value: Any, *, max_items: int = 8, max_string: int = 600) -> Any:
        if isinstance(value, str):
            return self._truncate_text(value, max_string)
        if isinstance(value, list):
            items = [self._compact_nested(item, max_items=max_items, max_string=max_string) for item in value[:max_items]]
            if len(value) > max_items:
                items.append(f"... [{len(value) - max_items} more items truncated]")
            return items
        if isinstance(value, dict):
            compact: Dict[str, Any] = {}
            for index, (key, item) in enumerate(value.items()):
                if index >= max_items:
                    compact["__truncated__"] = f"{len(value) - max_items} keys omitted"
                    break
                compact[key] = self._compact_nested(item, max_items=max_items, max_string=max_string)
            return compact
        return value

    def _truncate_text(self, text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        return text[:limit] + "... [truncated]"

    def _headless_timeout(self, agent: Dict[str, Any]) -> int:
        if agent["kind"] == AgentKind.CODEX.value:
            return int(os.environ.get("RELAY_CODEX_TIMEOUT_SECONDS", "60"))
        return int(os.environ.get("RELAY_HEADLESS_TIMEOUT_SECONDS", "180"))

    def _compact_retry_timeout(self, agent: Dict[str, Any]) -> int:
        if agent["kind"] == AgentKind.CODEX.value:
            return int(os.environ.get("RELAY_CODEX_COMPACT_TIMEOUT_SECONDS", "45"))
        return int(os.environ.get("RELAY_COMPACT_TIMEOUT_SECONDS", "90"))

    def _default_instruction(self, task_type: TaskType) -> str:
        defaults = {
            TaskType.REVIEW: "Focus on bugs, regressions, and missing tests. Include file and line when possible.",
            TaskType.PLAN: "Provide a concrete implementation plan with steps and risks.",
            TaskType.IMPLEMENT: "Suggest focused code changes and the next actions needed. Prefer concise actionable changes over restating the full context.",
            TaskType.OPTIMIZE_PROMPT: "Rewrite the prompt to be clearer and more actionable without changing the goal.",
            TaskType.WEB_RESEARCH: "Summarize the key facts and include source URLs when known.",
            TaskType.PDF_ANALYSIS: "Summarize the important sections and cite document sections.",
            TaskType.TREE_EXPLORE: "Explain the codebase areas that matter and recommend files to inspect.",
            TaskType.CONTEXT_DIGEST: "Condense the context into a clear handoff package.",
            TaskType.CUSTOM: "Complete the requested task and answer in JSON.",
        }
        return defaults[task_type]

    def _require_session(self, session_id: str) -> Dict[str, Any]:
        session = self.repo.get_session(session_id)
        if not session:
            raise ValueError(f"unknown session: {session_id}")
        return session

    def _require_snapshot(self, snapshot_id: str) -> Dict[str, Any]:
        snapshot = self.repo.get_snapshot(snapshot_id)
        if not snapshot:
            raise ValueError(f"unknown snapshot: {snapshot_id}")
        return snapshot

    def _require_packet(self, packet_id: str) -> Dict[str, Any]:
        packet = self.repo.get_task_packet(packet_id)
        if not packet:
            raise ValueError(f"unknown packet: {packet_id}")
        return packet

    def _require_run(self, run_id: str) -> Dict[str, Any]:
        run = self.repo.get_run(run_id)
        if not run:
            raise ValueError(f"unknown run: {run_id}")
        return run

    def _require_run_result(self, run_id: str) -> Dict[str, Any]:
        result = self.repo.get_run_result(run_id)
        if not result:
            raise ValueError(f"missing run result for {run_id}")
        return result

    def _require_agent(self, agent_id: str) -> Dict[str, Any]:
        agent = self.repo.get_agent(agent_id=agent_id)
        if not agent:
            raise ValueError(f"unknown agent: {agent_id}")
        return agent

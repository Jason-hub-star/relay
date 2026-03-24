from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional

from relay.config import workflow_state_path


DEFAULT_STATE: dict[str, Any] = {
    "active_workflow_id": None,
    "approval_mode": "default",
    "main_provider": None,
    "has_seen_workflow_modal": False,
    "workflows": [],
}


def default_state() -> dict[str, Any]:
    return deepcopy(DEFAULT_STATE)


class WorkflowStore:
    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path or workflow_state_path())
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load_state(self) -> dict[str, Any]:
        if not self.path.exists():
            return default_state()
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default_state()
        state = default_state()
        state.update({key: value for key, value in loaded.items() if key in state})
        state["workflows"] = [self._normalize_workflow(item) for item in loaded.get("workflows", []) if isinstance(item, dict)]
        return state

    def save_state(self, state: dict[str, Any]) -> dict[str, Any]:
        normalized = default_state()
        normalized.update({key: value for key, value in state.items() if key in normalized})
        normalized["workflows"] = [
            self._normalize_workflow(item) for item in normalized.get("workflows", []) if isinstance(item, dict)
        ]
        self.path.write_text(json.dumps(normalized, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
        return normalized

    def list_workflows(self) -> list[dict[str, Any]]:
        return self.load_state()["workflows"]

    def get_workflow(self, workflow_id: str) -> Optional[dict[str, Any]]:
        for workflow in self.list_workflows():
            if workflow["id"] == workflow_id:
                return workflow
        return None

    def get_active_workflow(self) -> Optional[dict[str, Any]]:
        state = self.load_state()
        workflow_id = state.get("active_workflow_id")
        if not workflow_id:
            return None
        for workflow in state["workflows"]:
            if workflow["id"] == workflow_id:
                if self._looks_broken_legacy_workflow(workflow):
                    state["active_workflow_id"] = None
                    self.save_state(state)
                    return None
                return workflow
        return None

    def save_workflow(self, workflow: dict[str, Any], *, set_active: bool = False) -> dict[str, Any]:
        state = self.load_state()
        normalized = self._normalize_workflow(workflow)
        workflows = [item for item in state["workflows"] if item["id"] != normalized["id"]]
        workflows.append(normalized)
        state["workflows"] = sorted(workflows, key=lambda item: (item["name"].lower(), item["id"]))
        if set_active:
            state["active_workflow_id"] = normalized["id"]
        self.save_state(state)
        return normalized

    def delete_workflow(self, workflow_id: str) -> None:
        state = self.load_state()
        state["workflows"] = [item for item in state["workflows"] if item["id"] != workflow_id]
        if state["active_workflow_id"] == workflow_id:
            state["active_workflow_id"] = None
        self.save_state(state)

    def set_active_workflow(self, workflow_id: Optional[str]) -> Optional[dict[str, Any]]:
        state = self.load_state()
        state["active_workflow_id"] = workflow_id
        self.save_state(state)
        if not workflow_id:
            return None
        return self.get_workflow(workflow_id)

    def mark_seen(self) -> None:
        state = self.load_state()
        state["has_seen_workflow_modal"] = True
        self.save_state(state)

    def has_seen_modal(self) -> bool:
        return bool(self.load_state().get("has_seen_workflow_modal"))

    def get_approval_mode(self) -> str:
        mode = str(self.load_state().get("approval_mode") or "default").strip().lower()
        return mode or "default"

    def set_approval_mode(self, mode: str) -> str:
        normalized = str(mode or "default").strip().lower() or "default"
        state = self.load_state()
        state["approval_mode"] = normalized
        self.save_state(state)
        return normalized

    def get_main_provider(self) -> Optional[str]:
        provider = self.load_state().get("main_provider")
        if provider is None:
            return None
        value = str(provider).strip()
        return value or None

    def set_main_provider(self, provider: Optional[str]) -> Optional[str]:
        normalized = str(provider).strip() if provider else None
        state = self.load_state()
        state["main_provider"] = normalized or None
        self.save_state(state)
        return normalized or None

    def _normalize_workflow(self, workflow: dict[str, Any]) -> dict[str, Any]:
        steps: List[dict[str, Any]] = []
        for index, raw in enumerate(workflow.get("steps", []), start=1):
            if not isinstance(raw, dict):
                continue
            agent_name = str(raw.get("agent_name") or "").strip()
            task_type = str(raw.get("task_type") or "").strip()
            label = str(raw.get("label") or "").strip()
            if not agent_name or not task_type:
                continue
            steps.append(
                {
                    "id": str(raw.get("id") or f"step_{index}"),
                    "agent_name": agent_name,
                    "task_type": task_type,
                    "label": label,
                }
            )
        return {
            "id": str(workflow.get("id") or ""),
            "name": str(workflow.get("name") or "Workflow").strip() or "Workflow",
            "main_agent": str(workflow.get("main_agent") or "").strip(),
            "mode": str(workflow.get("mode") or "workflow"),
            "send_back": bool(workflow.get("send_back", False)),
            "steps": steps,
        }

    def _looks_broken_legacy_workflow(self, workflow: dict[str, Any]) -> bool:
        steps = workflow.get("steps", [])
        if not steps:
            return False
        main_agent = str(workflow.get("main_agent") or "").strip()
        name = str(workflow.get("name") or "").strip().lower()
        if name != "workflow":
            return False
        if not workflow.get("send_back"):
            return False
        if workflow.get("mode") != "workflow":
            return False
        return all(
            step.get("agent_name") == main_agent
            and step.get("task_type") == "review"
            and not str(step.get("label") or "").strip()
            for step in steps
        )

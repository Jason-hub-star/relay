from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from relay.workflow_store import WorkflowStore


class WorkflowStoreTests(unittest.TestCase):
    def test_save_load_and_activate_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            store = WorkflowStore(Path(tempdir) / "workflow_state.json")
            workflow = {
                "id": "workflow_1",
                "name": "My Flow",
                "main_agent": "claude-main",
                "mode": "workflow",
                "send_back": True,
                "steps": [{"id": "step_1", "agent_name": "codex-main", "task_type": "review", "label": ""}],
            }
            store.save_workflow(workflow, set_active=True)
            loaded = store.get_active_workflow()
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded["name"], "My Flow")
            self.assertEqual(loaded["steps"][0]["task_type"], "review")

    def test_delete_workflow_clears_active_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            store = WorkflowStore(Path(tempdir) / "workflow_state.json")
            workflow = {
                "id": "workflow_1",
                "name": "Delete Me",
                "main_agent": "gemini-main",
                "mode": "direct",
                "send_back": False,
                "steps": [],
            }
            store.save_workflow(workflow, set_active=True)
            store.delete_workflow("workflow_1")
            self.assertIsNone(store.get_active_workflow())
            self.assertEqual(store.list_workflows(), [])

    def test_broken_legacy_active_workflow_is_cleared(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "workflow_state.json"
            store = WorkflowStore(path)
            store.save_state(
                {
                    "active_workflow_id": "workflow_bad",
                    "has_seen_workflow_modal": True,
                    "workflows": [
                        {
                            "id": "workflow_bad",
                            "name": "Workflow",
                            "main_agent": "claude-main",
                            "mode": "workflow",
                            "send_back": True,
                            "steps": [
                                {"id": "step_1", "agent_name": "claude-main", "task_type": "review", "label": ""},
                                {"id": "step_2", "agent_name": "claude-main", "task_type": "review", "label": ""},
                            ],
                        }
                    ],
                }
            )
            self.assertIsNone(store.get_active_workflow())
            state = store.load_state()
            self.assertIsNone(state["active_workflow_id"])

    def test_approval_mode_persists(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            store = WorkflowStore(Path(tempdir) / "workflow_state.json")
            self.assertEqual(store.get_approval_mode(), "default")
            store.set_approval_mode("plan")
            self.assertEqual(store.get_approval_mode(), "plan")

    def test_main_provider_persists(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            store = WorkflowStore(Path(tempdir) / "workflow_state.json")
            self.assertIsNone(store.get_main_provider())
            store.set_main_provider("claude-main")
            self.assertEqual(store.get_main_provider(), "claude-main")


if __name__ == "__main__":
    unittest.main()

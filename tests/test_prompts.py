from __future__ import annotations

import unittest

from relay.models import TaskType
from relay.prompts import build_delegate_prompt, build_return_prompt, extract_display_text, normalize_output


class PromptNormalizationTests(unittest.TestCase):
    def test_custom_task_extracts_result_field_from_event_payload(self) -> None:
        raw = '{"type":"result","subtype":"success","result":"4"}'
        normalized = normalize_output(TaskType.CUSTOM, raw)
        self.assertEqual(normalized["summary"], "4")
        self.assertEqual(normalized["details"], ["4"])

    def test_custom_task_extracts_result_string_from_event_array(self) -> None:
        raw = '[{"type":"assistant","message":{"content":[{"type":"text","text":"2 + 2 = 4"}]}},{"type":"result","result":"2 + 2 = 4"}]'
        normalized = normalize_output(TaskType.CUSTOM, raw)
        self.assertEqual(normalized["summary"], "2 + 2 = 4")
        self.assertEqual(normalized["details"], ["2 + 2 = 4"])

    def test_extract_display_text_prefers_result_text(self) -> None:
        raw = '[{"type":"assistant","message":{"content":[{"type":"text","text":"2 + 2 = 4"}]}},{"type":"result","result":"2 + 2 = 4"}]'
        self.assertEqual(extract_display_text(raw), "2 + 2 = 4")

    def test_delegate_prompt_can_include_original_result_block(self) -> None:
        packet = {
            "task_type": TaskType.CUSTOM.value,
            "title": "Refine answer",
            "instructions": "Complete the requested task and answer in JSON.",
            "input_payload": {
                "goal": "Summarize the docs",
                "artifacts": {"files": [], "git_diff": "", "git_status": "", "tree_excerpt": "", "conversation_excerpt": "", "attachments": []},
                "parent_result": {},
                "original_result": {"agent_name": "gemini-main", "display_text": "Original text"},
            },
        }
        prompt = build_delegate_prompt(packet, {"name": "codex-main", "kind": "codex"})
        self.assertIn("Original result:", prompt)
        self.assertIn("Original text", prompt)

    def test_return_prompt_keeps_only_high_signal_fields(self) -> None:
        prompt = build_return_prompt(
            origin_goal="Summarize the docs",
            contributor_name="codex-main",
            task_type=TaskType.IMPLEMENT.value,
            normalized_result={
                "summary": "Use workflow inspect commands.",
                "changes": ["Add /workflow list", "Add /workflow inspect", "Add richer /agents"],
                "followups": ["Update docs"],
                "session_id": "abc123",
                "stats": {"tokens": 99999},
            },
        )
        self.assertIn("Use workflow inspect commands.", prompt)
        self.assertIn("Add /workflow list", prompt)
        self.assertNotIn("abc123", prompt)
        self.assertNotIn('"stats"', prompt)
        self.assertIn("Write the final user-facing answer only.", prompt)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from relay.models import TaskType
from relay.prompts import extract_display_text, normalize_output


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


if __name__ == "__main__":
    unittest.main()

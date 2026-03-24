from __future__ import annotations

import unittest

from relay.models import TaskType
from relay.schemas import OUTPUT_SCHEMAS, strict_json_schema


class SchemaTests(unittest.TestCase):
    def test_review_schema_is_codex_compatible_after_strict_conversion(self) -> None:
        schema = strict_json_schema(OUTPUT_SCHEMAS[TaskType.REVIEW])
        findings_item = schema["properties"]["findings"]["items"]
        self.assertEqual(findings_item["required"], ["title", "severity", "file", "line", "suggestion"])
        self.assertFalse(findings_item["additionalProperties"])
        self.assertEqual(findings_item["properties"]["file"]["type"], ["string", "null"])
        self.assertEqual(findings_item["properties"]["line"]["type"], ["integer", "null"])


if __name__ == "__main__":
    unittest.main()

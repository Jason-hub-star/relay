from __future__ import annotations

import json
from typing import Any, Dict, List

from relay.models import TaskType
from relay.schemas import OUTPUT_SCHEMAS


def schema_name(task_type: TaskType) -> str:
    return f"{task_type.value}_v1"


def build_delegate_prompt(packet: Dict[str, Any], target_agent: Dict[str, Any]) -> str:
    payload = packet["input_payload"]
    task_type = TaskType(packet["task_type"])
    schema = OUTPUT_SCHEMAS[task_type]
    return f"""You are helping another coding agent through a structured handoff.

Target agent: {target_agent["name"]} ({target_agent["kind"]})
Task type: {packet["task_type"]}
Title: {packet["title"]}
Instructions: {packet["instructions"]}

Origin goal:
{payload["goal"]}

Artifacts:
{json.dumps(payload["artifacts"], ensure_ascii=True, indent=2)}

Parent run result:
{json.dumps(payload.get("parent_result"), ensure_ascii=True, indent=2)}

Return ONLY valid JSON. Do not wrap in markdown fences.
Match this schema exactly:
{json.dumps(schema, ensure_ascii=True, indent=2)}
"""


def build_return_prompt(
    *,
    origin_goal: str,
    contributor_name: str,
    task_type: str,
    normalized_result: Dict[str, Any],
) -> str:
    compact_result = _compact_value(normalized_result)
    return f"""External result for current task.

Origin task:
{origin_goal}

Contributor:
{contributor_name}

Task type:
{task_type}

Result:
{json.dumps(compact_result, ensure_ascii=True, indent=2)}

Please continue the work using this result. Preserve ongoing intent, update the plan if needed, and continue from the latest state.
"""


def _compact_value(value: Any, *, max_string: int = 1200, max_items: int = 12) -> Any:
    if isinstance(value, str):
        if len(value) <= max_string:
            return value
        return value[:max_string] + "... [truncated]"
    if isinstance(value, list):
        items = [_compact_value(item, max_string=max_string, max_items=max_items) for item in value[:max_items]]
        if len(value) > max_items:
            items.append(f"... [{len(value) - max_items} more items truncated]")
        return items
    if isinstance(value, dict):
        compact = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= max_items:
                compact["__truncated__"] = f"{len(value) - max_items} keys omitted"
                break
            compact[key] = _compact_value(item, max_string=max_string, max_items=max_items)
        return compact
    return value


def _balanced_json(raw: str) -> str:
    start = None
    depth = 0
    for index, char in enumerate(raw):
        if char in "[{":
            if start is None:
                start = index
            depth += 1
        elif char in "]}":
            depth -= 1
            if depth == 0 and start is not None:
                return raw[start : index + 1]
    raise ValueError("no balanced json found")


def extract_json_object(raw_output: str) -> Dict[str, Any]:
    raw_output = raw_output.strip()
    if not raw_output:
        raise ValueError("empty output")
    candidates: List[str] = [raw_output]
    try:
        candidates.append(_balanced_json(raw_output))
    except ValueError:
        pass
    if "\n" in raw_output:
        lines = [line for line in raw_output.splitlines() if line.strip()]
        candidates.extend(lines[::-1])
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, list):
            extracted = _extract_from_event_list(value)
            if extracted is not None:
                return extracted
            if len(value) == 1 and isinstance(value[0], dict):
                value = value[0]
        if isinstance(value, dict):
            if "output" in value and isinstance(value["output"], list):
                for item in value["output"]:
                    if isinstance(item, dict) and "content" in item:
                        for chunk in item["content"]:
                            if isinstance(chunk, dict) and "text" in chunk:
                                return extract_json_object(chunk["text"])
            return value
    raise ValueError("unable to extract json object")


def _extract_from_event_list(events: List[Any]) -> Dict[str, Any] | None:
    for event in reversed(events):
        if not isinstance(event, dict):
            continue
        result_value = event.get("result")
        if isinstance(result_value, str):
            try:
                parsed = json.loads(result_value)
            except json.JSONDecodeError:
                if result_value.strip():
                    return {"result": result_value.strip()}
            else:
                if isinstance(parsed, dict):
                    return parsed
        message = event.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, list):
                for chunk in content:
                    if isinstance(chunk, dict) and isinstance(chunk.get("text"), str):
                        try:
                            parsed = json.loads(chunk["text"])
                        except json.JSONDecodeError:
                            if chunk["text"].strip():
                                return {"result": chunk["text"].strip()}
                            continue
                        if isinstance(parsed, dict):
                            return parsed
    if len(events) == 1 and isinstance(events[0], dict):
        return events[0]
    return None


def fallback_normalized(task_type: TaskType, raw_output: str) -> Dict[str, Any]:
    text = raw_output.strip()
    if task_type == TaskType.REVIEW:
        return {"summary": text[:500], "findings": [], "next_action": "Review raw output manually."}
    if task_type == TaskType.PLAN:
        return {"summary": text[:500], "steps": [text[:300]], "risks": []}
    if task_type == TaskType.IMPLEMENT:
        return {"summary": text[:500], "changes": [text[:300]], "followups": []}
    if task_type == TaskType.OPTIMIZE_PROMPT:
        return {"optimized_prompt": text, "rationale": "Fallback from non-JSON output.", "warnings": []}
    if task_type == TaskType.WEB_RESEARCH:
        return {"summary": text[:500], "sources": [], "claims": []}
    if task_type == TaskType.PDF_ANALYSIS:
        return {"summary": text[:500], "sections": [], "citations": []}
    if task_type == TaskType.TREE_EXPLORE:
        return {"summary": text[:500], "areas": [], "recommended_files": []}
    if task_type == TaskType.CONTEXT_DIGEST:
        return {"summary": text[:500], "key_points": [], "handoff_prompt": text[:700]}
    return {"summary": text[:500], "details": [text[:300]]}


def normalize_output(task_type: TaskType, raw_output: str) -> Dict[str, Any]:
    try:
        parsed = extract_json_object(raw_output)
    except ValueError:
        return fallback_normalized(task_type, raw_output)
    if isinstance(parsed.get("result"), str):
        if task_type == TaskType.CUSTOM:
            return {"summary": parsed["result"], "details": [parsed["result"]]}
        return fallback_normalized(task_type, parsed["result"])
    return parsed


def extract_display_text(raw_output: str) -> str:
    text = raw_output.strip()
    if not text:
        return ""
    try:
        parsed = extract_json_object(raw_output)
    except ValueError:
        return text
    if isinstance(parsed.get("result"), str) and parsed["result"].strip():
        return parsed["result"].strip()
    for key in ("response", "summary", "optimized_prompt", "handoff_prompt", "next_action", "rationale"):
        value = parsed.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    details = parsed.get("details")
    if isinstance(details, list):
        for item in details:
            if isinstance(item, str) and item.strip():
                return item.strip()
    return text

from __future__ import annotations

from typing import Dict

from relay.models import ContextPolicy, TaskType


DEFAULT_CONTEXT_POLICY = {
    TaskType.PLAN: ContextPolicy.FULL,
    TaskType.REVIEW: ContextPolicy.FULL,
    TaskType.IMPLEMENT: ContextPolicy.RICH,
    TaskType.OPTIMIZE_PROMPT: ContextPolicy.RICH,
    TaskType.WEB_RESEARCH: ContextPolicy.COMPACT,
    TaskType.PDF_ANALYSIS: ContextPolicy.RICH,
    TaskType.TREE_EXPLORE: ContextPolicy.COMPACT,
    TaskType.CONTEXT_DIGEST: ContextPolicy.RICH,
    TaskType.CUSTOM: ContextPolicy.RICH,
}


OUTPUT_SCHEMAS: Dict[TaskType, Dict[str, object]] = {
    TaskType.REVIEW: {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "severity": {"type": "string"},
                        "file": {"type": ["string", "null"]},
                        "line": {"type": ["integer", "null"]},
                        "suggestion": {"type": "string"},
                    },
                    "required": ["title", "severity", "file", "line", "suggestion"],
                },
            },
            "next_action": {"type": "string"},
        },
        "required": ["summary", "findings", "next_action"],
    },
    TaskType.PLAN: {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "steps": {"type": "array", "items": {"type": "string"}},
            "risks": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["summary", "steps", "risks"],
    },
    TaskType.IMPLEMENT: {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "changes": {"type": "array", "items": {"type": "string"}},
            "followups": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["summary", "changes", "followups"],
    },
    TaskType.OPTIMIZE_PROMPT: {
        "type": "object",
        "properties": {
            "optimized_prompt": {"type": "string"},
            "rationale": {"type": "string"},
            "warnings": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["optimized_prompt", "rationale", "warnings"],
    },
    TaskType.WEB_RESEARCH: {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "sources": {"type": "array", "items": {"type": "string"}},
            "claims": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["summary", "sources", "claims"],
    },
    TaskType.PDF_ANALYSIS: {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "sections": {"type": "array", "items": {"type": "string"}},
            "citations": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["summary", "sections", "citations"],
    },
    TaskType.TREE_EXPLORE: {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "areas": {"type": "array", "items": {"type": "string"}},
            "recommended_files": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["summary", "areas", "recommended_files"],
    },
    TaskType.CONTEXT_DIGEST: {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "key_points": {"type": "array", "items": {"type": "string"}},
            "handoff_prompt": {"type": "string"},
        },
        "required": ["summary", "key_points", "handoff_prompt"],
    },
    TaskType.CUSTOM: {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "details": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["summary", "details"],
    },
}


def strict_json_schema(schema: Dict[str, object]) -> Dict[str, object]:
    def visit(node: object) -> object:
        if isinstance(node, dict):
            cloned = {key: visit(value) for key, value in node.items()}
            if cloned.get("type") == "object":
                cloned.setdefault("additionalProperties", False)
                properties = cloned.get("properties")
                if isinstance(properties, dict):
                    cloned["properties"] = {key: visit(value) for key, value in properties.items()}
                    cloned["required"] = list(cloned["properties"].keys())
            elif cloned.get("type") == "array" and "items" in cloned:
                cloned["items"] = visit(cloned["items"])
            return cloned
        if isinstance(node, list):
            return [visit(item) for item in node]
        return node

    return visit(schema)  # type: ignore[return-value]


PRESETS = [
    {
        "id": "preset_review_strict",
        "name": "Strict Review",
        "task_type": TaskType.REVIEW.value,
        "default_context_policy": ContextPolicy.FULL.value,
        "required_output_schema": "review_findings_v1",
        "instruction_template": "Focus on bugs, regressions, and missing tests. Include file and line when possible.",
    },
    {
        "id": "preset_plan_full",
        "name": "Full Planning",
        "task_type": TaskType.PLAN.value,
        "default_context_policy": ContextPolicy.FULL.value,
        "required_output_schema": "plan_v1",
        "instruction_template": "Produce a concrete implementation plan with risks and ordered steps.",
    },
    {
        "id": "preset_prompt_optimizer",
        "name": "Prompt Optimizer",
        "task_type": TaskType.OPTIMIZE_PROMPT.value,
        "default_context_policy": ContextPolicy.RICH.value,
        "required_output_schema": "optimize_prompt_v1",
        "instruction_template": "Rewrite the prompt for clarity and precision without changing intent.",
    },
]

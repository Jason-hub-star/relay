from __future__ import annotations

from enum import Enum


class StrEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class AgentKind(StrEnum):
    CLAUDE = "claude"
    CODEX = "codex"
    GEMINI = "gemini"
    QWEN = "qwen"


class ResumeStrategy(StrEnum):
    NATIVE = "native"
    PTY = "pty"


class TaskType(StrEnum):
    PLAN = "plan"
    REVIEW = "review"
    IMPLEMENT = "implement"
    OPTIMIZE_PROMPT = "optimize_prompt"
    WEB_RESEARCH = "web_research"
    PDF_ANALYSIS = "pdf_analysis"
    TREE_EXPLORE = "tree_explore"
    CONTEXT_DIGEST = "context_digest"
    CUSTOM = "custom"


class ContextPolicy(StrEnum):
    COMPACT = "compact"
    RICH = "rich"
    FULL = "full"


class SessionStatus(StrEnum):
    ACTIVE = "active"
    IDLE = "idle"
    CLOSED = "closed"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ARCHIVED = "archived"


class ReturnStatus(StrEnum):
    PENDING = "pending"
    RETURNED = "returned"
    FAILED = "failed"


class ReturnMode(StrEnum):
    RESUME = "resume"
    FALLBACK_NEW_PROMPT = "fallback-new-prompt"


class ApprovalMode(StrEnum):
    PLAN = "plan"
    DEFAULT = "default"
    AUTO_EDIT = "auto-edit"
    YOLO = "yolo"

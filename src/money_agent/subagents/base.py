"""Base types for sub-agents."""

from dataclasses import dataclass
from typing import Any


@dataclass
class SubAgentResult:
    """Structured result from a sub-agent."""
    success: bool
    summary: str
    data: dict[str, Any] = None
    actions_suggested: list[str] = None

    def __post_init__(self):
        if self.data is None:
            self.data = {}
        if self.actions_suggested is None:
            self.actions_suggested = []

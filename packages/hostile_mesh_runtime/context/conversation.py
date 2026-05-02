from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from hostile_mesh_runtime.client.anthropic_client import TokenUsage


@dataclass
class ConversationManager:
    """Holds the message list for a single agent process across turns,
    tracks token usage, and exposes a compression hook used when context
    threatens to overflow.

    Anthropic Messages API expects ``user`` / ``assistant`` roles. ``system``
    is passed separately. Tool results are encoded as user messages whose
    ``content`` is a list of ``tool_result`` blocks.
    """

    messages: list[dict[str, Any]] = field(default_factory=list)
    latest_usage: TokenUsage = field(default_factory=TokenUsage)
    cumulative_usage: TokenUsage = field(default_factory=TokenUsage)
    summary_tokens: int = 0

    def add_user(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})

    def add_assistant_blocks(self, blocks: list[dict[str, Any]]) -> None:
        if blocks:
            self.messages.append({"role": "assistant", "content": blocks})

    def add_tool_results(self, results: list[dict[str, Any]]) -> None:
        if results:
            self.messages.append({"role": "user", "content": results})

    def set_latest_usage(self, usage: TokenUsage) -> None:
        self.latest_usage = usage

    def add_usage(self, usage: TokenUsage) -> None:
        self.cumulative_usage = self.cumulative_usage + usage

    def needs_compression(self, threshold: int) -> bool:
        return (
            self.latest_usage.prompt_tokens + self.latest_usage.completion_tokens
        ) >= threshold

    def replace_with_summary(self, summary: str, keep_last: int) -> None:
        tail = self.messages[-keep_last:] if keep_last else []
        self.messages = [
            {"role": "user", "content": f"[summary of earlier context]\n{summary}"},
            *tail,
        ]

    def snapshot(self) -> list[dict[str, Any]]:
        return list(self.messages)


__all__ = ["ConversationManager"]

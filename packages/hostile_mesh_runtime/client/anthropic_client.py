from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import anthropic
from anthropic import AsyncAnthropic
from anthropic._exceptions import APIConnectionError, APIError, RateLimitError

from hostile_mesh_runtime.config import RuntimeConfig


class StreamEventType(str, Enum):
    TEXT_DELTA = "text_delta"
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_DELTA = "tool_call_delta"
    TOOL_CALL_COMPLETE = "tool_call_complete"
    MESSAGE_COMPLETE = "message_complete"
    ERROR = "error"


@dataclass(slots=True)
class TextDelta:
    content: str


@dataclass(slots=True)
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
            cache_creation_tokens=self.cache_creation_tokens + other.cache_creation_tokens,
        )


@dataclass(slots=True)
class ToolCallDelta:
    call_id: str
    name: str | None = None
    arguments_delta: str = ""


@dataclass(slots=True)
class ToolCall:
    call_id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class StreamEvent:
    type: StreamEventType
    text_delta: TextDelta | None = None
    tool_call_delta: ToolCallDelta | None = None
    tool_call: ToolCall | None = None
    usage: TokenUsage | None = None
    finish_reason: str | None = None
    error: str | None = None


class AnthropicClient:
    """Streaming Anthropic Messages client adapted to a Godel-style event API.

    Yields a uniform stream of typed events regardless of whether the model
    returned text, tool calls, or both. Retries on rate limits / connection
    errors with exponential backoff, then surfaces a structured error event.

    Prompt caching is enabled on the system prompt by default — combatant and
    chorus loops keep the same big system prompt across many turns.
    """

    def __init__(self, config: RuntimeConfig, max_retries: int = 3) -> None:
        self._config = config
        self._client: AsyncAnthropic | None = None
        self._max_retries = max_retries

    def _get_client(self) -> AsyncAnthropic:
        if self._client is None:
            if not self._config.api_key:
                raise RuntimeError(
                    f"Agent {self._config.agent_id!r} has no ANTHROPIC_API_KEY — "
                    f"cannot make LLM calls"
                )
            self._client = AsyncAnthropic(api_key=self._config.api_key)
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.close()
            self._client = None

    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        client = self._get_client()
        system_blocks = (
            [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
            if system
            else None
        )
        kwargs: dict[str, Any] = {
            "model": self._config.model,
            "max_tokens": self._config.max_tokens,
            "temperature": self._config.temperature,
            "messages": messages,
        }
        if system_blocks:
            kwargs["system"] = system_blocks
        if tools:
            kwargs["tools"] = tools

        for attempt in range(self._max_retries + 1):
            try:
                async for event in self._stream_once(client, kwargs):
                    yield event
                return
            except RateLimitError as exc:
                if attempt < self._max_retries:
                    await asyncio.sleep(2**attempt)
                    continue
                yield StreamEvent(type=StreamEventType.ERROR, error=f"rate limit: {exc}")
                return
            except APIConnectionError as exc:
                if attempt < self._max_retries:
                    await asyncio.sleep(2**attempt)
                    continue
                yield StreamEvent(type=StreamEventType.ERROR, error=f"connection: {exc}")
                return
            except APIError as exc:
                yield StreamEvent(type=StreamEventType.ERROR, error=f"api: {exc}")
                return

    async def _stream_once(
        self, client: AsyncAnthropic, kwargs: dict[str, Any]
    ) -> AsyncGenerator[StreamEvent, None]:
        # Maps content-block index → in-progress tool call state.
        partial_tool_calls: dict[int, dict[str, Any]] = {}
        usage_acc = TokenUsage()
        stop_reason: str | None = None

        async with client.messages.stream(**kwargs) as stream:
            async for chunk in stream:
                # Anthropic's streaming surface is a tagged-union of "events".
                etype = getattr(chunk, "type", None)

                if etype == "content_block_start":
                    block = getattr(chunk, "content_block", None)
                    if block is not None and getattr(block, "type", None) == "tool_use":
                        idx = chunk.index
                        partial_tool_calls[idx] = {
                            "call_id": block.id,
                            "name": block.name,
                            "arguments": "",
                        }
                        yield StreamEvent(
                            type=StreamEventType.TOOL_CALL_START,
                            tool_call_delta=ToolCallDelta(
                                call_id=block.id, name=block.name
                            ),
                        )

                elif etype == "content_block_delta":
                    delta = getattr(chunk, "delta", None)
                    dtype = getattr(delta, "type", None)
                    if dtype == "text_delta":
                        text = getattr(delta, "text", "")
                        if text:
                            yield StreamEvent(
                                type=StreamEventType.TEXT_DELTA,
                                text_delta=TextDelta(content=text),
                            )
                    elif dtype == "input_json_delta":
                        idx = chunk.index
                        if idx in partial_tool_calls:
                            partial_tool_calls[idx]["arguments"] += delta.partial_json
                            yield StreamEvent(
                                type=StreamEventType.TOOL_CALL_DELTA,
                                tool_call_delta=ToolCallDelta(
                                    call_id=partial_tool_calls[idx]["call_id"],
                                    name=partial_tool_calls[idx]["name"],
                                    arguments_delta=delta.partial_json,
                                ),
                            )

                elif etype == "message_delta":
                    msg_delta = getattr(chunk, "delta", None)
                    if msg_delta is not None:
                        sr = getattr(msg_delta, "stop_reason", None)
                        if sr:
                            stop_reason = sr
                    chunk_usage = getattr(chunk, "usage", None)
                    if chunk_usage is not None:
                        usage_acc.completion_tokens += getattr(chunk_usage, "output_tokens", 0)

                elif etype == "message_start":
                    msg = getattr(chunk, "message", None)
                    if msg is not None and getattr(msg, "usage", None) is not None:
                        u = msg.usage
                        usage_acc.prompt_tokens += getattr(u, "input_tokens", 0)
                        usage_acc.cache_read_tokens += (
                            getattr(u, "cache_read_input_tokens", 0) or 0
                        )
                        usage_acc.cache_creation_tokens += (
                            getattr(u, "cache_creation_input_tokens", 0) or 0
                        )

        usage_acc.total_tokens = usage_acc.prompt_tokens + usage_acc.completion_tokens

        for state in partial_tool_calls.values():
            try:
                args = json.loads(state["arguments"]) if state["arguments"] else {}
            except json.JSONDecodeError:
                args = {"_raw": state["arguments"]}
            yield StreamEvent(
                type=StreamEventType.TOOL_CALL_COMPLETE,
                tool_call=ToolCall(
                    call_id=state["call_id"], name=state["name"], arguments=args
                ),
            )

        yield StreamEvent(
            type=StreamEventType.MESSAGE_COMPLETE,
            finish_reason=stop_reason,
            usage=usage_acc,
        )


__all__ = [
    "AnthropicClient",
    "StreamEvent",
    "StreamEventType",
    "TextDelta",
    "TokenUsage",
    "ToolCall",
    "ToolCallDelta",
]

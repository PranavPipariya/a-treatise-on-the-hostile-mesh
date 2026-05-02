"""OpenAI-compatible streaming client (OpenRouter / OpenAI / any compatible host).

Yields the same ``StreamEvent`` taxonomy as ``AnthropicClient`` so the
orchestrator is provider-agnostic — flip ``HOSTILE_MESH_LLM_PROVIDER`` and
nothing else changes.

The OpenAI Chat Completions API expresses tool use as ``tool_calls`` deltas
on assistant messages. We accumulate them per-index, parse the JSON
arguments at completion, and emit ``TOOL_CALL_COMPLETE`` events for the
orchestrator to dispatch.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncGenerator
from typing import Any

from openai import APIConnectionError, APIError, AsyncOpenAI, RateLimitError

from hostile_mesh_runtime.client.anthropic_client import (
    StreamEvent,
    StreamEventType,
    TextDelta,
    TokenUsage,
    ToolCall,
    ToolCallDelta,
)
from hostile_mesh_runtime.config import RuntimeConfig


def _system_message(system: str | None) -> list[dict[str, Any]]:
    return [{"role": "system", "content": system}] if system else []


def _to_openai_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert Anthropic-shaped tool schemas into OpenAI ``functions``.

    Tool registry already emits Anthropic shape ``{name, description, input_schema}``.
    OpenAI wants ``{type: "function", function: {name, description, parameters}}``.
    """
    out = []
    for t in tools:
        out.append(
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("input_schema") or {
                        "type": "object",
                        "properties": {},
                    },
                },
            }
        )
    return out


def _convert_messages_for_openai(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Translate the Anthropic-style message log into OpenAI shape.

    The orchestrator stores assistant turns as ``{"role": "assistant", "content":
    [text-block, tool_use-block, …]}`` and tool results as ``{"role": "user",
    "content": [tool_result-block, …]}``. OpenAI uses ``tool_calls`` on
    assistant messages and a separate ``role: "tool"`` message per result.
    """
    out: list[dict[str, Any]] = []
    for msg in messages:
        role = msg["role"]
        content = msg["content"]
        if role == "user" and isinstance(content, str):
            out.append({"role": "user", "content": content})
            continue
        if role == "user" and isinstance(content, list):
            tool_results = [b for b in content if b.get("type") == "tool_result"]
            text_parts = [b for b in content if b.get("type") != "tool_result"]
            for result in tool_results:
                out.append(
                    {
                        "role": "tool",
                        "tool_call_id": result["tool_use_id"],
                        "content": str(result.get("content", "")),
                    }
                )
            if text_parts:
                joined = "\n".join(
                    p.get("text", "") for p in text_parts if p.get("type") == "text"
                )
                if joined:
                    out.append({"role": "user", "content": joined})
            continue
        if role == "assistant" and isinstance(content, list):
            text = "".join(
                b.get("text", "") for b in content if b.get("type") == "text"
            )
            tool_uses = [b for b in content if b.get("type") == "tool_use"]
            assistant_msg: dict[str, Any] = {"role": "assistant", "content": text or None}
            if tool_uses:
                assistant_msg["tool_calls"] = [
                    {
                        "id": tu["id"],
                        "type": "function",
                        "function": {
                            "name": tu["name"],
                            "arguments": json.dumps(tu.get("input", {})),
                        },
                    }
                    for tu in tool_uses
                ]
            out.append(assistant_msg)
            continue
        if role == "assistant" and isinstance(content, str):
            out.append({"role": "assistant", "content": content})
            continue
        # Fallback: pass-through.
        out.append(msg)
    return out


class OpenRouterClient:
    """Streaming client that speaks the OpenAI Chat Completions surface.

    Works with OpenRouter (default), OpenAI direct, or any other
    OpenAI-compatible host. The base URL is read from
    ``HOSTILE_MESH_LLM_BASE_URL`` (or ``BASE_URL`` as a generic fallback).
    """

    def __init__(self, config: RuntimeConfig, max_retries: int = 3) -> None:
        self._config = config
        self._client: AsyncOpenAI | None = None
        self._max_retries = max_retries

    @property
    def base_url(self) -> str:
        return (
            os.getenv("HOSTILE_MESH_LLM_BASE_URL")
            or os.getenv("BASE_URL")
            or "https://openrouter.ai/api/v1"
        )

    def _api_key(self) -> str:
        return self._config.api_key or os.getenv("API_KEY") or os.getenv("OPENROUTER_API_KEY") or ""

    def _get_client(self) -> AsyncOpenAI:
        if self._client is None:
            key = self._api_key()
            if not key:
                raise RuntimeError(
                    f"Agent {self._config.agent_id!r}: no API key found "
                    f"(set API_KEY / OPENROUTER_API_KEY / ANTHROPIC_API_KEY)"
                )
            self._client = AsyncOpenAI(api_key=key, base_url=self.base_url)
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
        kwargs: dict[str, Any] = {
            "model": self._config.model,
            "messages": _system_message(system) + _convert_messages_for_openai(messages),
            "stream": True,
            "max_tokens": self._config.max_tokens,
            "temperature": self._config.temperature,
        }
        if tools:
            kwargs["tools"] = _to_openai_tools(tools)
            kwargs["tool_choice"] = "auto"

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
        self, client: AsyncOpenAI, kwargs: dict[str, Any]
    ) -> AsyncGenerator[StreamEvent, None]:
        partial_calls: dict[int, dict[str, Any]] = {}
        usage_acc = TokenUsage()
        finish_reason: str | None = None

        response = await client.chat.completions.create(**kwargs)

        async for chunk in response:
            usage = getattr(chunk, "usage", None)
            if usage is not None:
                usage_acc.prompt_tokens = getattr(usage, "prompt_tokens", 0) or usage_acc.prompt_tokens
                usage_acc.completion_tokens = (
                    getattr(usage, "completion_tokens", 0) or usage_acc.completion_tokens
                )
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            delta = choice.delta

            if choice.finish_reason:
                finish_reason = choice.finish_reason

            if delta and delta.content:
                yield StreamEvent(
                    type=StreamEventType.TEXT_DELTA, text_delta=TextDelta(delta.content)
                )

            if delta and getattr(delta, "tool_calls", None):
                for tc in delta.tool_calls:
                    idx = tc.index
                    state = partial_calls.setdefault(
                        idx,
                        {
                            "id": tc.id or "",
                            "name": "",
                            "arguments": "",
                            "started": False,
                        },
                    )
                    if tc.id:
                        state["id"] = tc.id
                    if tc.function and tc.function.name:
                        if not state["started"]:
                            state["name"] = tc.function.name
                            state["started"] = True
                            yield StreamEvent(
                                type=StreamEventType.TOOL_CALL_START,
                                tool_call_delta=ToolCallDelta(
                                    call_id=state["id"], name=tc.function.name
                                ),
                            )
                    if tc.function and tc.function.arguments:
                        state["arguments"] += tc.function.arguments
                        yield StreamEvent(
                            type=StreamEventType.TOOL_CALL_DELTA,
                            tool_call_delta=ToolCallDelta(
                                call_id=state["id"],
                                name=state["name"],
                                arguments_delta=tc.function.arguments,
                            ),
                        )

        usage_acc.total_tokens = usage_acc.prompt_tokens + usage_acc.completion_tokens

        for state in partial_calls.values():
            try:
                args = json.loads(state["arguments"]) if state["arguments"] else {}
            except json.JSONDecodeError:
                args = {"_raw": state["arguments"]}
            yield StreamEvent(
                type=StreamEventType.TOOL_CALL_COMPLETE,
                tool_call=ToolCall(call_id=state["id"], name=state["name"], arguments=args),
            )

        yield StreamEvent(
            type=StreamEventType.MESSAGE_COMPLETE,
            finish_reason=finish_reason,
            usage=usage_acc,
        )


__all__ = ["OpenRouterClient"]

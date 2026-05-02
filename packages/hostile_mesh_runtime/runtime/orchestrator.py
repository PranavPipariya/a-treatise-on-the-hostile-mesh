from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

from hostile_mesh_runtime.client.anthropic_client import StreamEventType, TokenUsage
from hostile_mesh_runtime.runtime.events import AgentEvent
from hostile_mesh_runtime.runtime.session import Session

logger = logging.getLogger(__name__)


class Orchestrator:
    """Streaming agent loop.

    Each call to ``run(message)`` runs *up to* ``config.max_turns`` model
    invocations. A turn ends when the model either (a) emits no tool calls
    (terminal text response), or (b) is forcibly stopped by the loop detector.
    Tool results are appended as a ``user`` message of ``tool_result`` blocks
    so Anthropic's tool-use protocol stays intact.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    async def run(self, message: str) -> AsyncGenerator[AgentEvent, None]:
        s = self._session
        await s.hooks.before_agent(message)
        yield AgentEvent.agent_start(message)
        s.conversation.add_user(message)

        final_response: str | None = None
        cumulative_usage = TokenUsage()

        for _ in range(s.config.max_turns):
            turn = s.increment_turn()
            yield AgentEvent.turn_start(turn)

            if s.conversation.needs_compression(s.config.compression_threshold_tokens):
                summary, summary_usage = await s.compressor.compress(
                    s.conversation.snapshot()
                )
                if summary:
                    s.conversation.replace_with_summary(summary, s.config.keep_last_messages)
                    cumulative_usage = cumulative_usage + summary_usage
                    yield AgentEvent.context_compressed(len(summary))

            tool_schemas = s.tools.schemas(s.config.allowed_tools)

            assistant_blocks: list[dict[str, Any]] = []
            text_buf: list[str] = []
            tool_calls_buffer: list[Any] = []
            usage: TokenUsage | None = None

            async for ev in s.client.stream(
                messages=s.conversation.snapshot(),
                tools=tool_schemas if tool_schemas else None,
                system=s.config.system_prompt,
            ):
                if ev.type is StreamEventType.TEXT_DELTA and ev.text_delta:
                    text_buf.append(ev.text_delta.content)
                    yield AgentEvent.text_delta(ev.text_delta.content)
                elif ev.type is StreamEventType.TOOL_CALL_COMPLETE and ev.tool_call:
                    tool_calls_buffer.append(ev.tool_call)
                elif ev.type is StreamEventType.MESSAGE_COMPLETE:
                    usage = ev.usage
                elif ev.type is StreamEventType.ERROR:
                    yield AgentEvent.agent_error(ev.error or "stream error")
                    yield AgentEvent.turn_end(turn)
                    yield AgentEvent.agent_end(None, cumulative_usage)
                    await s.hooks.after_agent(message, None)
                    return

            if usage:
                s.conversation.set_latest_usage(usage)
                s.conversation.add_usage(usage)
                cumulative_usage = cumulative_usage + usage

            text = "".join(text_buf)
            if text:
                yield AgentEvent.text_complete(text)
                assistant_blocks.append({"type": "text", "text": text})
                s.loop_detector.record("response", text=text)

            for tc in tool_calls_buffer:
                assistant_blocks.append(
                    {
                        "type": "tool_use",
                        "id": tc.call_id,
                        "name": tc.name,
                        "input": tc.arguments,
                    }
                )

            s.conversation.add_assistant_blocks(assistant_blocks)

            if not tool_calls_buffer:
                final_response = text
                yield AgentEvent.turn_end(turn)
                break

            tool_result_blocks: list[dict[str, Any]] = []
            for tc in tool_calls_buffer:
                yield AgentEvent.tool_call_start(tc.call_id, tc.name, tc.arguments)
                s.loop_detector.record("tool_call", tool_name=tc.name, args=tc.arguments)

                result = await s.tools.invoke(
                    tc.name,
                    tc.arguments,
                    agent_id=s.config.agent_id,
                    cwd=s.workspace,
                    hooks=s.hooks,
                    permissions=s.permissions,
                )
                yield AgentEvent.tool_call_complete(tc.call_id, tc.name, result)

                tool_result_blocks.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tc.call_id,
                        "content": result.to_model_payload(),
                        **({"is_error": True} if not result.success else {}),
                    }
                )

            s.conversation.add_tool_results(tool_result_blocks)

            loop_reason = s.loop_detector.check()
            if loop_reason:
                yield AgentEvent.loop_detected(loop_reason)
                # Inject a corrective user nudge so the next turn breaks out.
                s.conversation.add_user(
                    f"[loop detector] {loop_reason}. Reconsider and try a different "
                    f"approach. If you've exhausted ideas, stop and explain what's blocked."
                )

            yield AgentEvent.turn_end(turn)

        yield AgentEvent.agent_end(final_response, cumulative_usage)
        await s.hooks.after_agent(message, final_response)


__all__ = ["Orchestrator"]

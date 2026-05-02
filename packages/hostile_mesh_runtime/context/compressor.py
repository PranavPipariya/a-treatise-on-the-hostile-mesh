from __future__ import annotations

from typing import Any

from hostile_mesh_runtime.client.anthropic_client import StreamEventType, TokenUsage
from hostile_mesh_runtime.client.factory import LLMClient


COMPRESSION_PROMPT = """\
You are summarising the prior conversation of an autonomous combat agent.

Produce a tight, *factual* digest under 800 tokens that preserves:
- the agent's identity and current goal,
- the state of its own service (which endpoints, what's been patched),
- what it has learned about its opponent,
- outstanding hypotheses about exploits to attempt next,
- any signed claims it has already made.

Do NOT speculate, embellish, or add commentary. Write in dense bullet form.
"""


class ContextCompressor:
    """Calls the LLM to compress the agent's own message history when it
    grows past the configured threshold. Returns the summary text *and* the
    token usage spent on the compression itself, so the conversation manager
    can keep accurate accounting.
    """

    def __init__(self, client: LLMClient) -> None:
        self._client = client

    async def compress(self, messages: list[dict[str, Any]]) -> tuple[str, TokenUsage]:
        prompt = (
            "Summarise the following messages.\n\n"
            "<messages>\n"
            f"{messages!r}\n"
            "</messages>"
        )
        summary_chunks: list[str] = []
        usage = TokenUsage()
        async for event in self._client.stream(
            messages=[{"role": "user", "content": prompt}],
            system=COMPRESSION_PROMPT,
        ):
            if event.type is StreamEventType.TEXT_DELTA and event.text_delta:
                summary_chunks.append(event.text_delta.content)
            elif event.type is StreamEventType.MESSAGE_COMPLETE and event.usage:
                usage = event.usage
        return "".join(summary_chunks).strip(), usage


__all__ = ["ContextCompressor"]

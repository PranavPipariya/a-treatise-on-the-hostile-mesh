"""LLM client factory — picks Anthropic vs OpenAI-compatible based on env."""

from __future__ import annotations

import os
from typing import Protocol

from hostile_mesh_runtime.client.anthropic_client import AnthropicClient, StreamEvent
from hostile_mesh_runtime.client.openrouter_client import OpenRouterClient
from hostile_mesh_runtime.config import RuntimeConfig


class LLMClient(Protocol):
    """Structural protocol — both AnthropicClient and OpenRouterClient
    satisfy this. The orchestrator only depends on the protocol."""

    async def close(self) -> None: ...

    def stream(self, messages, tools=None, system=None): ...  # noqa: D401


def make_client(config: RuntimeConfig) -> LLMClient:
    """Pick the LLM client based on ``HOSTILE_MESH_LLM_PROVIDER``.

    Resolution order:
      1. Explicit ``HOSTILE_MESH_LLM_PROVIDER=anthropic|openrouter|openai``.
      2. If ``API_KEY`` (Godel-style) or ``OPENROUTER_API_KEY`` is set →
         OpenRouter.
      3. If ``ANTHROPIC_API_KEY`` is set → Anthropic.
      4. Otherwise → Anthropic (will fail loudly when first stream is called).
    """
    provider = (os.getenv("HOSTILE_MESH_LLM_PROVIDER") or "").strip().lower()
    if not provider:
        if os.getenv("API_KEY") or os.getenv("OPENROUTER_API_KEY"):
            provider = "openrouter"
        elif os.getenv("ANTHROPIC_API_KEY"):
            provider = "anthropic"
        else:
            provider = "anthropic"

    if provider in {"openrouter", "openai", "openai-compat"}:
        return OpenRouterClient(config)
    return AnthropicClient(config)


__all__ = ["LLMClient", "make_client"]

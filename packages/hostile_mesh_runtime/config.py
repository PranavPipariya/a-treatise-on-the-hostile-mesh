from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class RuntimeConfig:
    """Per-agent runtime configuration.

    A single ``RuntimeConfig`` is constructed by the arena before spawning a
    combatant or chorus process. Defaults read from environment variables so
    process boundaries stay clean.
    """

    agent_id: str
    role: str  # "combatant" | "chorus"
    system_prompt: str

    # LLM
    api_key: str | None = None
    model: str = "openai/gpt-4o-mini"
    max_tokens: int = 1024
    temperature: float = 0.6
    max_turns: int = 12

    # Context management — tighter caps so combatants don't burn tokens
    # cycling through patches they've already considered.
    max_context_tokens: int = 32_000
    compression_threshold_tokens: int = 24_000
    keep_last_messages: int = 6

    # Loop detection
    loop_max_exact_repeats: int = 3
    loop_max_cycle_length: int = 3

    # Permissions — for adversarial agents, mutating ops are *expected*.
    auto_approve_kinds: tuple[str, ...] = field(
        default_factory=lambda: ("read", "write", "shell", "network", "memory")
    )

    # Workspace — each agent's sandbox lives under here.
    workspace: Path = field(default_factory=Path.cwd)

    # Optional: tool allow-list (None = all registered tools available).
    allowed_tools: tuple[str, ...] | None = None

    @classmethod
    def from_env(cls, agent_id: str, role: str, system_prompt: str, **overrides) -> RuntimeConfig:
        env_model_key = (
            "HOSTILE_MESH_COMBATANT_MODEL" if role == "combatant" else "HOSTILE_MESH_CHORUS_MODEL"
        )
        # Provider-agnostic key resolution. OpenRouter (Godel-style API_KEY)
        # takes precedence if present, then ANTHROPIC_API_KEY, then OPENROUTER_API_KEY.
        api_key = (
            os.getenv("API_KEY")
            or os.getenv("ANTHROPIC_API_KEY")
            or os.getenv("OPENROUTER_API_KEY")
            or ""
        )
        # Default model is chosen for cost first, capability second. With
        # the GPT-4o-mini default, a full 3-min match runs at ~$0.05–0.15
        # total LLM cost. Override per-role with HOSTILE_MESH_COMBATANT_MODEL
        # / HOSTILE_MESH_CHORUS_MODEL when you want stronger play (e.g.
        # `anthropic/claude-sonnet-4.5` runs ~50× more expensive).
        provider = (os.getenv("HOSTILE_MESH_LLM_PROVIDER") or "").strip().lower()
        using_openrouter = provider in {"openrouter", "openai", "openai-compat"} or (
            not provider and (os.getenv("API_KEY") or os.getenv("OPENROUTER_API_KEY"))
        )
        if role == "combatant":
            default_model = "openai/gpt-4o-mini" if using_openrouter else "claude-haiku-4-5-20251001"
        else:
            default_model = (
                "openai/gpt-4o-mini" if using_openrouter else "claude-haiku-4-5-20251001"
            )
        # Defaults the caller can override via `**overrides`.
        defaults = {
            "model": os.getenv(env_model_key, default_model),
            "max_tokens": int(os.getenv("HOSTILE_MESH_MAX_TOKENS", "1024")),
            "max_turns": int(os.getenv("HOSTILE_MESH_MAX_TURNS", "12")),
        }
        defaults.update(overrides)
        return cls(
            agent_id=agent_id,
            role=role,
            system_prompt=system_prompt,
            api_key=api_key,
            **defaults,
        )

    @property
    def llm_available(self) -> bool:
        return bool(self.api_key)

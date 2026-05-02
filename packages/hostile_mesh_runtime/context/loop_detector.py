from __future__ import annotations

from collections import deque
from typing import Any


class LoopDetector:
    """Detects two failure modes that combat agents are particularly prone to:

    1. Repeating the *same* tool call with the *same* arguments (e.g. probing
       the same endpoint over and over after the verifier already returned
       "no exploit").
    2. Cycling between two or three actions (probe-A, probe-B, probe-A,
       probe-B …).

    Wider history window than typical coding-agent loops because combat
    agents take more turns per match.
    """

    def __init__(self, max_exact_repeats: int = 3, max_cycle_length: int = 3) -> None:
        self.max_exact_repeats = max_exact_repeats
        self.max_cycle_length = max_cycle_length
        self._history: deque[str] = deque(maxlen=32)

    def record(self, action_type: str, **details: Any) -> None:
        parts = [action_type]
        if action_type == "tool_call":
            parts.append(details.get("tool_name", ""))
            args = details.get("args", {})
            if isinstance(args, dict):
                for key in sorted(args.keys()):
                    parts.append(f"{key}={args[key]!r}")
        elif action_type == "response":
            parts.append((details.get("text") or "")[:128])
        self._history.append("|".join(parts))

    def check(self) -> str | None:
        if len(self._history) < 2:
            return None

        if len(self._history) >= self.max_exact_repeats:
            tail = list(self._history)[-self.max_exact_repeats :]
            if len(set(tail)) == 1:
                return f"same action repeated {self.max_exact_repeats} times"

        if len(self._history) >= self.max_cycle_length * 2:
            history = list(self._history)
            for cycle_len in range(2, min(self.max_cycle_length + 1, len(history) // 2 + 1)):
                tail = history[-cycle_len * 2 :]
                if tail[:cycle_len] == tail[cycle_len:]:
                    return f"cycle of length {cycle_len} detected"

        return None

    def clear(self) -> None:
        self._history.clear()


__all__ = ["LoopDetector"]

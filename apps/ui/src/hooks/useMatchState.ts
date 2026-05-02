import { useEffect } from "react";
import { store, useStore } from "../state/store";
import type { MatchState } from "../types";

/**
 * Fetch the initial MatchState snapshot for ``matchId`` once, then rely on
 * the SSE stream to keep it current.
 */
export function useMatchState(matchId: string | null) {
  const state = useStore((s) => s.matchState);

  useEffect(() => {
    if (!matchId) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${store.arenaUrl}/api/match/${matchId}/state`);
        if (!res.ok) return;
        const data = (await res.json()) as MatchState;
        if (!cancelled) store.setMatchState(data);
      } catch {
        /* noop */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [matchId]);

  return state;
}

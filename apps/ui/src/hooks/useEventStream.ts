import { useEffect, useRef } from "react";
import type { ArenaEvent } from "../types";
import { store } from "../state/store";

/**
 * Subscribe to the arena's SSE event stream for ``matchId``. Reconnects with
 * exponential backoff on disconnect and pushes every parsed event into the
 * store. Setting ``matchId`` to null disconnects.
 */
export function useEventStream(matchId: string | null) {
  const sourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!matchId) {
      sourceRef.current?.close();
      sourceRef.current = null;
      return;
    }

    let attempt = 0;
    let cancelled = false;
    let timer: number | undefined;

    const connect = () => {
      if (cancelled) return;
      const url = `${store.arenaUrl}/api/match/${matchId}/events`;
      const es = new EventSource(url);
      sourceRef.current = es;

      es.onopen = () => {
        attempt = 0;
      };

      es.onerror = () => {
        es.close();
        sourceRef.current = null;
        if (cancelled) return;
        const delay = Math.min(8000, 500 * 2 ** attempt++);
        timer = window.setTimeout(connect, delay);
      };

      es.onmessage = (e) => {
        try {
          const evt = JSON.parse(e.data) as ArenaEvent;
          store.ingest(evt);
        } catch {
          // ignore unparseable frames
        }
      };

      // Also listen for typed events — sse-starlette sends both the typed
      // event name and the payload, so dispatch through the typed listener
      // path as well to catch cases where onmessage skips named events.
      const handleTyped = (e: MessageEvent) => {
        try {
          store.ingest(JSON.parse(e.data) as ArenaEvent);
        } catch {
          /* noop */
        }
      };
      const types = [
        "match.opening",
        "match.started",
        "match.finished",
        "match.aborted",
        "axl.node.spawned",
        "axl.node.ready",
        "axl.topology",
        "ens.write.submitted",
        "ens.write.confirmed",
        "ens.write.failed",
        "ens.not_configured",
        "bug.seeded",
        "combat.probe",
        "combat.exploit.attempt",
        "combat.exploit.verified",
        "combat.exploit.failed",
        "combat.patch.submitted",
        "combat.patch.applied",
        "combat.patch.rejected",
        "combat.patch.broke_service",
        "chorus.comment",
        "combatant.claim",
        "score.updated",
        "log",
      ];
      types.forEach((t) => es.addEventListener(t, handleTyped as EventListener));
    };

    connect();

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
      sourceRef.current?.close();
      sourceRef.current = null;
    };
  }, [matchId]);
}

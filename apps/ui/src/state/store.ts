import { useSyncExternalStore } from "react";
import type {
  ActionLogEntry,
  ArenaEvent,
  AxlNode,
  Bubble,
  EnsWrite,
  MatchState,
  Payout,
  SeededBug,
} from "../types";

const DEFAULT_ARENA_URL =
  import.meta.env.DEV || typeof window === "undefined"
    ? "http://127.0.0.1:8787"
    : window.location.origin;
const ARENA_URL = import.meta.env.VITE_ARENA_URL || DEFAULT_ARENA_URL;

type Listener = () => void;

type State = {
  arenaUrl: string;
  matchId: string | null;
  matchState: MatchState | null;
  events: ArenaEvent[];
  bubbles: Bubble[];
  axlNodes: Record<string, AxlNode>;
  ensWrites: EnsWrite[];
  seededBugs: SeededBug[];
  actionLog: ActionLogEntry[];
  ensChainAvailable: boolean | null;
  payouts: Payout[];
};

const state: State = {
  arenaUrl: ARENA_URL,
  matchId: null,
  matchState: null,
  events: [],
  bubbles: [],
  axlNodes: {},
  ensWrites: [],
  seededBugs: [],
  actionLog: [],
  ensChainAvailable: null,
  payouts: [],
};

const listeners = new Set<Listener>();

const notify = () => listeners.forEach((l) => l());
const subscribe = (l: Listener) => {
  listeners.add(l);
  return () => listeners.delete(l);
};
const getSnapshot = () => state;

const COMBATANTS_LEFT_FIRST = ["nightshade", "ironbark"];
const sideOf = (id: string) => (id === COMBATANTS_LEFT_FIRST[0] ? "left" : "right");

let bubbleSeq = 0;
let logSeq = 0;
let writeSeq = 0;

export const store = {
  subscribe,
  getSnapshot,
  arenaUrl: ARENA_URL,

  setMatchId(matchId: string) {
    state.matchId = matchId;
    notify();
  },

  setMatchState(s: MatchState) {
    state.matchState = s;
    state.matchId = s.match_id;
    notify();
  },

  setEnsChainAvailable(v: boolean) {
    state.ensChainAvailable = v;
    notify();
  },

  ingest(event: ArenaEvent) {
    state.events = [...state.events.slice(-499), event];

    const { type, data, ts } = event as ArenaEvent<Record<string, any>>;

    if (type === "match.opening") {
      // Reset bookkeeping ONCE, at match-opening, before any bug.seeded /
      // axl.node.* / ens.write.* events arrive. We do NOT reset on
      // match.started — that event fires *after* those, and resetting
      // there would erase the seeded-bug list we just collected.
      state.bubbles = [];
      state.actionLog = [];
      state.seededBugs = [];
      state.ensWrites = [];
      state.axlNodes = {};
      state.payouts = [];
    }

    if (type === "match.started" || type === "match.finished" || type === "match.aborted") {
      // Push a partial — caller can re-fetch full state if needed.
      if (type === "match.started" && data) {
        state.matchState = data as MatchState;
        state.matchId = (data as MatchState).match_id;
      }
      if ((type === "match.finished" || type === "match.aborted") && data) {
        state.matchState = data as MatchState;
      }
    }

    if (type === "axl.node.spawned" || type === "axl.node.ready") {
      const node: AxlNode = {
        agent_id: String(data.agent_id ?? data.combatant ?? ""),
        peer_id: String(data.peer_id ?? ""),
        api_url: String(data.api_url ?? data.url ?? ""),
        status: type === "axl.node.ready" ? "ready" : "spawning",
      };
      if (node.agent_id) {
        state.axlNodes = { ...state.axlNodes, [node.agent_id]: node };
      }
    }

    if (type === "bug.seeded") {
      state.seededBugs = [
        ...state.seededBugs,
        {
          combatant: String(data.combatant),
          bug_id: String(data.bug_id),
          vuln_class: String(data.vuln_class),
          difficulty: data.difficulty as any,
          title: String(data.title),
          endpoint: String(data.endpoint),
        },
      ];
    }

    if (
      type === "ens.write.submitted" ||
      type === "ens.write.confirmed" ||
      type === "ens.write.failed" ||
      type === "ens.not_configured"
    ) {
      const write: EnsWrite = {
        id: `w-${++writeSeq}`,
        name: String(data.name ?? ""),
        operation: String(data.operation ?? data.kind ?? ""),
        status:
          type === "ens.write.confirmed"
            ? "confirmed"
            : type === "ens.write.failed"
              ? "failed"
              : type === "ens.not_configured"
                ? "not_configured"
                : "submitted",
        tx_hash: data.tx_hash ? String(data.tx_hash) : null,
        block: typeof data.block === "number" ? data.block : null,
        error: data.error ? String(data.error) : null,
        ts,
        match_id: event.match_id,
      };

      // If a follow-up event matches an earlier "submitted" by name+op,
      // upgrade in place rather than appending.
      const existing = state.ensWrites.findIndex(
        (w) => w.name === write.name && w.operation === write.operation && w.status === "submitted",
      );
      if (existing >= 0 && (write.status === "confirmed" || write.status === "failed")) {
        const next = [...state.ensWrites];
        next[existing] = { ...next[existing], ...write };
        state.ensWrites = next;
      } else {
        state.ensWrites = [...state.ensWrites.slice(-127), write];
      }
    }

    if (type === "score.updated" && data) {
      if (state.matchState) {
        state.matchState = {
          ...state.matchState,
          scores: data as MatchState["scores"],
        };
      }
    }

    if (type === "combat.probe" || type === "combat.exploit.attempt") {
      pushLogEntry(
        sideOf(String(data.attacker ?? "")),
        String(data.attacker ?? ""),
        ts,
        type === "combat.probe" ? "info" : "warn",
        `${type === "combat.probe" ? "PROBING" : "EXPLOIT"} ${data.endpoint ?? ""} ${data.summary ?? ""}`.trim(),
        String(data.endpoint ?? ""),
      );
    }
    if (type === "combat.exploit.verified") {
      pushLogEntry(
        sideOf(String(data.attacker ?? "")),
        String(data.attacker ?? ""),
        ts,
        "good",
        `WOUND ${data.vuln_class} via ${data.endpoint} — landed`,
        String(data.endpoint ?? ""),
      );
      pushLogEntry(
        sideOf(String(data.defender ?? "")),
        String(data.defender ?? ""),
        ts,
        "bad",
        `WOUND TAKEN at ${data.endpoint} (${data.vuln_class})`,
        String(data.endpoint ?? ""),
      );
    }
    if (type === "combat.exploit.failed") {
      pushLogEntry(
        sideOf(String(data.attacker ?? "")),
        String(data.attacker ?? ""),
        ts,
        "bad",
        `FAILED CLAIM: ${data.reason ?? "rejected"}`,
        String(data.endpoint ?? ""),
      );
    }
    if (type === "combat.patch.applied") {
      pushLogEntry(
        sideOf(String(data.agent_id ?? "")),
        String(data.agent_id ?? ""),
        ts,
        "good",
        `PATCH applied to ${data.file ?? "unknown"} (${data.bug_id ?? "?"})`,
      );
    }
    if (type === "combat.patch.broke_service") {
      pushLogEntry(
        sideOf(String(data.agent_id ?? "")),
        String(data.agent_id ?? ""),
        ts,
        "bad",
        `PATCH broke service — reverted`,
      );
    }
    if (type === "combat.patch.submitted") {
      pushLogEntry(
        sideOf(String(data.agent_id ?? "")),
        String(data.agent_id ?? ""),
        ts,
        "info",
        `patching ${data.file}…`,
      );
    }

    if (type === "combat.payout" && data) {
      const p: Payout = {
        agent_id: String(data.agent_id ?? ""),
        ens_name: String(data.ens_name ?? ""),
        address: data.address ? String(data.address) : undefined,
        wei: Number(data.wei ?? 0),
        eth: String(data.eth ?? ""),
        tx_hash: data.tx_hash ? String(data.tx_hash) : undefined,
        etherscan_url: data.etherscan_url ? String(data.etherscan_url) : undefined,
        reason: String(data.reason ?? ""),
      };
      if (p.agent_id) state.payouts = [...state.payouts, p];
    }
    if (type === "combat.payout.failed" && data) {
      const p: Payout = {
        agent_id: String(data.agent_id ?? ""),
        ens_name: String(data.ens_name ?? ""),
        address: data.address ? String(data.address) : undefined,
        wei: Number(data.wei ?? 0),
        eth: "0",
        reason: String(data.reason ?? "settlement failed"),
        failed: true,
      };
      if (p.agent_id) state.payouts = [...state.payouts, p];
    }

    if (type === "chorus.comment" && data) {
      const archetype = String(data.archetype ?? "");
      pushBubble({
        speakerId: String(data.speaker ?? `${archetype}.chorus`),
        speakerEns: String(data.signer ?? ""),
        text: String(data.text ?? ""),
        kind: "comment",
        archetype,
        ttl: 6000,
      });
    }
    if (type === "combatant.claim" && data) {
      pushBubble({
        speakerId: String(data.speaker ?? data.sender ?? ""),
        speakerEns: String(data.sender_ens ?? data.signer ?? ""),
        text: String(data.text ?? ""),
        kind: "claim",
        ttl: 7000,
      });
    }

    notify();
  },

  expireBubbles() {
    const now = Date.now();
    const next = state.bubbles.filter((b) => now - b.bornAt < b.ttl);
    if (next.length !== state.bubbles.length) {
      state.bubbles = next;
      notify();
    }
  },
};

function pushBubble(b: Omit<Bubble, "id" | "bornAt">) {
  const bubble: Bubble = { ...b, id: `b-${++bubbleSeq}`, bornAt: Date.now() };
  // Cap at 2 simultaneous bubbles per speaker.
  const remaining = state.bubbles.filter((x) => x.speakerId !== bubble.speakerId);
  const sameSpeaker = state.bubbles
    .filter((x) => x.speakerId === bubble.speakerId)
    .slice(-1);
  state.bubbles = [...remaining, ...sameSpeaker, bubble];
}

function pushLogEntry(
  side: "left" | "right",
  agentId: string,
  ts: number,
  status: ActionLogEntry["status"],
  text: string,
  endpoint?: string,
) {
  const entry: ActionLogEntry = {
    id: `l-${++logSeq}`,
    side,
    agentId,
    ts,
    status,
    text,
    endpoint,
  };
  state.actionLog = [...state.actionLog.slice(-127), entry];
}

// Periodically expire bubbles even if no event is firing.
if (typeof window !== "undefined") {
  setInterval(() => store.expireBubbles(), 250);
}

export function useStore<T>(selector: (s: State) => T): T {
  return useSyncExternalStore(
    store.subscribe,
    () => selector(store.getSnapshot()),
    () => selector(store.getSnapshot()),
  );
}

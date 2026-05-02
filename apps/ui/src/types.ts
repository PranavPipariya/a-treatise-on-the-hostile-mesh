// ─── Arena event taxonomy ────────────────────────────────────────────────────
// Mirrors `services/arena/event_bus.py` — keep this file in sync with that
// enum when new events are added.

export type ArenaEventType =
  | "match.opening"
  | "match.started"
  | "match.finished"
  | "match.aborted"
  | "axl.node.spawned"
  | "axl.node.ready"
  | "axl.topology"
  | "ens.write.submitted"
  | "ens.write.confirmed"
  | "ens.write.failed"
  | "ens.not_configured"
  | "bug.seeded"
  | "agent.thought"
  | "agent.tool_call"
  | "agent.tool_result"
  | "combat.probe"
  | "combat.exploit.attempt"
  | "combat.exploit.verified"
  | "combat.exploit.failed"
  | "combat.patch.submitted"
  | "combat.patch.applied"
  | "combat.patch.rejected"
  | "combat.patch.broke_service"
  | "chorus.comment"
  | "combatant.claim"
  | "score.updated"
  | "combat.payout"
  | "combat.payout.failed"
  | "log";

export type ArenaEvent<T = Record<string, unknown>> = {
  type: ArenaEventType;
  ts: number;
  match_id: string;
  data: T;
};

// ─── Match state (mirrors services/arena/manager.py MatchState.to_dict) ──────
export type Scoreboard = {
  wounds_inflicted: number;
  wounds_taken: number;
  patches_applied: number;
  patches_broken: number;
  failed_claims: number;
  breakdown: BreakdownEntry[];
};

export type BreakdownEntry = {
  kind: string;
  delta: number;
  bug_id?: string;
  summary?: string;
};

export type MatchState = {
  match_id: string;
  parent_ens: string;
  started_at: number;
  duration_s: number;
  combatants: string[];
  chorus: string[];
  seeded_bugs: Record<string, string[]>;
  target_urls: Record<string, string>;
  peer_ids: Record<string, string>;
  status: "opening" | "running" | "finished" | "aborted";
  scores: Record<string, Scoreboard>;
  counters: Record<string, number>;
  finished_at: number | null;
};

// ─── UI-specific shapes ──────────────────────────────────────────────────────
export type EnsWriteStatus = "submitted" | "confirmed" | "failed" | "not_configured";

export type EnsWrite = {
  id: string;
  name: string;
  operation: string;
  status: EnsWriteStatus;
  tx_hash?: string | null;
  block?: number | null;
  error?: string | null;
  ts: number;
  match_id: string;
};

export type AxlNode = {
  agent_id: string;
  peer_id: string;
  api_url: string;
  status: "spawning" | "ready";
};

export type Bubble = {
  id: string;
  speakerId: string;
  speakerEns: string;
  text: string;
  kind: "comment" | "claim" | "verdict" | "system";
  archetype?: string;
  bornAt: number;
  ttl: number;
};

export type ActionLogEntry = {
  id: string;
  side: "left" | "right";
  agentId: string;
  ts: number;
  status: "info" | "good" | "bad" | "warn";
  text: string;
  endpoint?: string;
};

export type SeededBug = {
  combatant: string;
  bug_id: string;
  vuln_class: string;
  difficulty: "easy" | "medium" | "hard";
  title: string;
  endpoint: string;
};

export type Payout = {
  agent_id: string;
  ens_name: string;
  address?: string;
  wei: number;
  eth: string;
  tx_hash?: string;
  etherscan_url?: string;
  reason: string;
  failed?: boolean;
};

export type CombatantSide = "left" | "right";

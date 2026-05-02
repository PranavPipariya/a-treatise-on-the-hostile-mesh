import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useMemo, useState } from "react";
import { HitSparks } from "./HitSparks";
import { playerById, playerPortrait } from "../registry";
import { useStore } from "../state/store";
import type { ArenaEvent, Bubble } from "../types";

interface Props {
  agentId: string;
  side: "left" | "right";
  parentEns: string;
}

type Flash = "attacking" | "wounded" | "patching" | "missed" | "broken";

const FLASH_TTL_MS = 1300;
const DAMAGE_TTL_MS = 1100;

interface DamagePop {
  id: string;
  delta: number;
  kind: "wound" | "patch";
}

/**
 * One half of the battle screen.
 *
 *   ┌─ floating speech bubble (above portrait) ────────────────┐
 *   │   "going for /admin"                                      │
 *   └───────────────────────────────────────────────────────────┘
 *   ┌─ glassy portrait card ──────────┐
 *   │ [   PORTRAIT    ]               │  ← flash state animates this card
 *   │ Name                            │     (attacking / wounded / patching …)
 *   │ ENS                             │
 *   │ ───── REPUTATION    +3          │  ← score scale-bounces on change
 *   └─────────────────────────────────┘   plus floating ±N damage chip
 *                                         + radial hit sparks on wound
 */
export function BattlePortrait({ agentId, side, parentEns }: Props) {
  const matchState = useStore((s) => s.matchState);
  const allBubbles = useStore((s) => s.bubbles);
  const events = useStore((s) => s.events);

  const score = matchState?.scores?.[agentId];
  const total = score
    ? score.wounds_inflicted -
      score.wounds_taken +
      score.patches_applied -
      score.patches_broken -
      score.failed_claims
    : 0;

  const entry = playerById(agentId);
  const displayName = entry?.display_name ?? agentId;
  const ensName = `${agentId}.${parentEns}`;

  // Latest 1 bubble for this combatant (cap = 1, big floating bubble).
  const bubble: Bubble | null = useMemo(() => {
    const list = allBubbles.filter((b) => b.speakerId === agentId);
    return list[list.length - 1] ?? null;
  }, [allBubbles, agentId]);

  // Derive a flash state from the latest combat event involving this agent,
  // self-clearing after FLASH_TTL_MS.
  const [flash, setFlash] = useState<Flash | null>(null);
  // Each "important" combat event (wound, patch) spawns a transient damage
  // chip + sparks, identified by its event timestamp so re-renders don't
  // double-fire.
  const [damage, setDamage] = useState<DamagePop | null>(null);

  useEffect(() => {
    const latest = findLatestRelevant(events, agentId);
    if (!latest) return;
    const kind = mapEventToFlash(latest, agentId);
    if (!kind) return;

    setFlash(kind);
    const tFlash = window.setTimeout(() => setFlash(null), FLASH_TTL_MS);

    const dmg = mapEventToDamage(latest, agentId);
    if (dmg) {
      setDamage({ ...dmg, id: `${latest.ts}-${latest.type}` });
      const tDmg = window.setTimeout(() => setDamage(null), DAMAGE_TTL_MS);
      return () => {
        window.clearTimeout(tFlash);
        window.clearTimeout(tDmg);
      };
    }
    return () => window.clearTimeout(tFlash);
  }, [events, agentId]);

  const hasFlash = flash !== null;

  return (
    <div className={"bp bp--" + side}>
      {/* Floating bubble above the card, big, judge-style but larger. */}
      <div className={"bp__bubble-slot bp__bubble-slot--" + side}>
        <AnimatePresence mode="wait">
          {bubble && (
            <motion.div
              key={bubble.id}
              className={"bp__bubble bp__bubble--" + side}
              initial={{ opacity: 0, y: 14, scale: 0.94 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: -10, scale: 0.94 }}
              transition={{
                duration: 0.32,
                ease: [0.16, 1, 0.3, 1],
              }}
            >
              {bubble.text}
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      <motion.div
        className="bp__card"
        initial={{ opacity: 0, scale: 0.95, y: 12 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1] }}
        data-flash={flash ?? "idle"}
      >
        <div className="bp__portrait">
          <img src={playerPortrait(agentId)} alt={displayName} />

          {/* Action chip overlay (attacking / wounded / patching / etc) */}
          <AnimatePresence>
            {hasFlash && (
              <motion.div
                key={flash}
                className={"bp__action bp__action--" + flash}
                initial={{ opacity: 0, y: -6, scale: 0.9 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, y: 4, scale: 0.92 }}
                transition={{ duration: 0.24, ease: [0.16, 1, 0.3, 1] }}
              >
                {flashLabel(flash!)}
              </motion.div>
            )}
          </AnimatePresence>

          {/* Radial hit sparks on wound; gentle pulse on patch */}
          {damage && (
            <HitSparks
              triggerId={damage.id}
              kind={damage.kind === "wound" ? "wound" : "patch"}
            />
          )}

          {/* Floating ±N damage chip drifting up */}
          <AnimatePresence>
            {damage && (
              <motion.div
                key={damage.id}
                className={"bp__damage bp__damage--" + damage.kind}
                initial={{ opacity: 0, y: 10, scale: 0.6 }}
                animate={{ opacity: 1, y: -52, scale: 1 }}
                exit={{ opacity: 0, y: -78, scale: 0.9 }}
                transition={{ duration: 1.0, ease: [0.16, 1, 0.3, 1] }}
              >
                {damage.delta > 0 ? `+${damage.delta}` : damage.delta}
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        <div className="bp__meta">
          <div className="bp__name">{displayName}</div>
          <div className="bp__ens">{ensName}</div>
        </div>

        <div className="bp__score">
          <span className="bp__score-label">REPUTATION</span>
          <motion.span
            className="bp__score-num"
            key={total}
            initial={{ scale: 1.32, color: "#ef4444" }}
            animate={{ scale: 1, color: "var(--c-fg)" }}
            transition={{
              duration: 0.55,
              ease: [0.16, 1, 0.3, 1],
            }}
          >
            {total >= 0 ? `+${total}` : `${total}`}
          </motion.span>
        </div>
      </motion.div>
    </div>
  );
}

// ─── helpers ─────────────────────────────────────────────────────────────────

function findLatestRelevant(events: ArenaEvent[], agentId: string): ArenaEvent | null {
  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i];
    if (involves(e, agentId)) return e;
  }
  return null;
}

function involves(e: ArenaEvent, agentId: string): boolean {
  const d = (e.data ?? {}) as Record<string, any>;
  switch (e.type) {
    case "combat.probe":
    case "combat.exploit.attempt":
      return d.attacker === agentId;
    case "combat.exploit.verified":
    case "combat.exploit.failed":
      return d.attacker === agentId || d.defender === agentId;
    case "combat.patch.applied":
    case "combat.patch.submitted":
    case "combat.patch.broke_service":
      return d.agent_id === agentId;
    default:
      return false;
  }
}

function mapEventToFlash(e: ArenaEvent, agentId: string): Flash | null {
  const d = (e.data ?? {}) as Record<string, any>;
  switch (e.type) {
    case "combat.exploit.attempt":
      return d.attacker === agentId ? "attacking" : null;
    case "combat.exploit.verified":
      if (d.attacker === agentId) return "attacking";
      if (d.defender === agentId) return "wounded";
      return null;
    case "combat.exploit.failed":
      return d.attacker === agentId ? "missed" : null;
    case "combat.patch.applied":
      return d.agent_id === agentId ? "patching" : null;
    case "combat.patch.broke_service":
      return d.agent_id === agentId ? "broken" : null;
    default:
      return null;
  }
}

/** Returns ±N if this event should pop a damage chip on this agent. */
function mapEventToDamage(
  e: ArenaEvent,
  agentId: string,
): Omit<DamagePop, "id"> | null {
  const d = (e.data ?? {}) as Record<string, any>;
  if (e.type === "combat.exploit.verified") {
    // wound difficulty isn't broken out per-event in the current schema;
    // we use the bug class to roughly weight: hard=3, medium=2, easy=1.
    const cls = String(d.vuln_class ?? "");
    const weight = inferDifficultyWeight(cls);
    if (d.defender === agentId) return { delta: -weight, kind: "wound" };
    if (d.attacker === agentId) return { delta: +weight, kind: "wound" };
  }
  if (e.type === "combat.patch.applied" && d.agent_id === agentId) {
    return { delta: +1, kind: "patch" };
  }
  return null;
}

function inferDifficultyWeight(vulnClass: string): number {
  // Rough mapping of vuln class → wound weight, consistent with arena scoring.
  switch (vulnClass) {
    case "sqli":
    case "cmd_injection":
    case "signature_replay":
      return 3;
    case "auth_bypass":
    case "broken_access":
    case "race_condition":
      return 2;
    default:
      return 1;
  }
}

function flashLabel(flash: Flash): string {
  switch (flash) {
    case "attacking": return "ATTACKING";
    case "wounded":   return "WOUNDED";
    case "patching":  return "PATCHING";
    case "missed":    return "MISSED";
    case "broken":    return "BROKE SERVICE";
  }
}

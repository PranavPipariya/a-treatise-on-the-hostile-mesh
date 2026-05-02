import { AnimatePresence, motion } from "framer-motion";
import {
  AlertTriangle,
  Eye,
  Flag,
  Shield,
  Skull,
  Swords,
  X,
  Zap,
} from "lucide-react";
import { useMemo } from "react";
import { playerById } from "../registry";
import { useStore } from "../state/store";
import type { ArenaEvent } from "../types";

interface Props {
  leftId: string;
  rightId: string;
}

interface Beat {
  id: string;
  ts: number;
  icon: React.ReactNode;
  tone: "probe" | "attack" | "wound" | "fail" | "patch" | "broken" | "open";
  text: React.ReactNode;
}

const MAX_BEATS = 5;
const NARRATABLE: ReadonlyArray<string> = [
  "match.opening",
  "match.started",
  "combat.probe",
  "combat.exploit.attempt",
  "combat.exploit.verified",
  "combat.exploit.failed",
  "combat.patch.applied",
  "combat.patch.broke_service",
];

/**
 * Replaces the side-by-side ThinkingPanel with a single, longer "play-by-play"
 * scroll of the last ~5 noteworthy events. Each beat reads like a sportscaster
 * line — rich verb, named subject, named object, named endpoint — instead of
 * dry mono metadata.
 */
export function BattleNarrator({ leftId, rightId }: Props) {
  const events = useStore((s) => s.events);

  const beats: Beat[] = useMemo(() => {
    const out: Beat[] = [];
    const namedAgents: Record<string, string> = {
      [leftId]: playerById(leftId)?.display_name ?? leftId,
      [rightId]: playerById(rightId)?.display_name ?? rightId,
    };
    for (const e of events) {
      if (!NARRATABLE.includes(e.type)) continue;
      const beat = renderBeat(e, namedAgents);
      if (beat) out.push(beat);
    }
    return out.slice(-MAX_BEATS);
  }, [events, leftId, rightId]);

  return (
    <div className="narrator">
      <div className="narrator__head">
        <span className="narrator__dot" />
        <span className="narrator__title">PLAY-BY-PLAY</span>
        <span className="narrator__sub">live commentary</span>
      </div>
      <ol className="narrator__feed">
        <AnimatePresence initial={false}>
          {beats.map((beat) => (
            <motion.li
              key={beat.id}
              className={"beat beat--" + beat.tone}
              initial={{ opacity: 0, y: 12, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: -8, scale: 0.98 }}
              transition={{ duration: 0.32, ease: [0.16, 1, 0.3, 1] }}
              layout
            >
              <span className="beat__icon">{beat.icon}</span>
              <span className="beat__text">{beat.text}</span>
            </motion.li>
          ))}
        </AnimatePresence>
        {beats.length === 0 && (
          <li className="beat beat--idle">
            <span className="beat__icon"><Flag size={16} /></span>
            <span className="beat__text">match opening — agents booting…</span>
          </li>
        )}
      </ol>
    </div>
  );
}

// ─── helpers ────────────────────────────────────────────────────────────────
function renderBeat(
  e: ArenaEvent,
  named: Record<string, string>,
): Beat | null {
  const d = (e.data ?? {}) as Record<string, any>;
  const id = `${e.ts}-${e.type}-${d.attacker ?? d.agent_id ?? ""}-${d.endpoint ?? d.bug_id ?? d.file ?? ""}`;
  const name = (id_: string) => named[id_] ?? id_;

  switch (e.type) {
    case "match.opening":
    case "match.started":
      return {
        id,
        ts: e.ts,
        icon: <Flag size={16} />,
        tone: "open",
        text: <>The match is on. Bugs seeded. The duel begins.</>,
      };

    case "combat.probe": {
      const a = name(String(d.attacker ?? "?"));
      const ep = String(d.endpoint ?? "an endpoint");
      return {
        id,
        ts: e.ts,
        icon: <Eye size={16} />,
        tone: "probe",
        text: (
          <>
            <strong>{a}</strong> probes <code>{ep}</code> — looking for an
            opening.
          </>
        ),
      };
    }

    case "combat.exploit.attempt": {
      const a = name(String(d.attacker ?? "?"));
      const def = name(String(d.defender ?? "?"));
      const ep = String(d.endpoint ?? "an endpoint");
      const cls = String(d.vuln_class ?? "");
      return {
        id,
        ts: e.ts,
        icon: <Swords size={16} />,
        tone: "attack",
        text: (
          <>
            <strong>{a}</strong> commits to{" "}
            {cls ? <em>{cls}</em> : "an exploit"} against <strong>{def}</strong>{" "}
            via <code>{ep}</code>.
          </>
        ),
      };
    }

    case "combat.exploit.verified": {
      const a = name(String(d.attacker ?? "?"));
      const def = name(String(d.defender ?? "?"));
      const ep = String(d.endpoint ?? "");
      const cls = String(d.vuln_class ?? "an unknown class");
      return {
        id,
        ts: e.ts,
        icon: <Zap size={16} />,
        tone: "wound",
        text: (
          <>
            <strong>WOUND.</strong> <strong>{a}</strong> lands{" "}
            <em>{cls}</em> on <strong>{def}</strong>
            {ep ? (
              <>
                {" "}
                via <code>{ep}</code>
              </>
            ) : null}
            . Verified on-chain.
          </>
        ),
      };
    }

    case "combat.exploit.failed": {
      const a = name(String(d.attacker ?? "?"));
      const ep = String(d.endpoint ?? "an endpoint");
      const reason = String(d.reason ?? "verifier rejected");
      return {
        id,
        ts: e.ts,
        icon: <X size={16} />,
        tone: "fail",
        text: (
          <>
            <strong>{a}</strong> whiffs at <code>{ep}</code> —{" "}
            <span className="beat__reason">{reason}</span>. Public failure.
          </>
        ),
      };
    }

    case "combat.patch.applied": {
      const a = name(String(d.agent_id ?? "?"));
      const bug = String(d.bug_id ?? "a bug");
      return {
        id,
        ts: e.ts,
        icon: <Shield size={16} />,
        tone: "patch",
        text: (
          <>
            <strong>{a}</strong> patches <code>{bug}</code> — closes a hole
            mid-fight.
          </>
        ),
      };
    }

    case "combat.patch.broke_service": {
      const a = name(String(d.agent_id ?? "?"));
      const file = String(d.file ?? "their service");
      return {
        id,
        ts: e.ts,
        icon: <AlertTriangle size={16} />,
        tone: "broken",
        text: (
          <>
            <strong>{a}</strong> ships a bad patch on <code>{file}</code> —{" "}
            <span className="beat__reason">service breaks, reverted</span>.
          </>
        ),
      };
    }

    default:
      return null;
  }
}

// suppress unused-warning for icons we may swap in later
void Skull;

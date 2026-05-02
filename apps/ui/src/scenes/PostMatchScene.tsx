import { Trophy, ArrowRight, Home } from "lucide-react";
import { motion } from "framer-motion";
import { playerById, playerPortrait } from "../registry";
import { useStore } from "../state/store";
import type { EnsWriteStatus, MatchState } from "../types";

interface Props {
  state: MatchState;
  onReplay: () => void;
  onHome?: () => void;
}

const ENS_LABEL: Record<EnsWriteStatus, string> = {
  submitted: "PENDING",
  confirmed: "CONFIRMED",
  failed: "FAILED",
  not_configured: "OFF-CHAIN",
};

export function PostMatchScene({ state, onReplay, onHome }: Props) {
  const ensWrites = useStore((s) => s.ensWrites);
  const seededBugs = useStore((s) => s.seededBugs);

  const winner = pickWinner(state);
  const winnerEntry = winner ? playerById(winner) : null;
  const winnerEarningsEth = winner ? earningsForAgent(state, winner) : null;

  return (
    <div className="postmatch-v3">
      <div className="bg-noise" />

      <motion.section
        className="postmatch-v3__hero"
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6 }}
      >
        <div className="postmatch-v3__eyebrow">VICTOR</div>
        {winnerEntry ? (
          <motion.div
            className="postmatch-v3__portrait"
            initial={{ scale: 0.85, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1], delay: 0.15 }}
          >
            <img
              src={playerPortrait(winnerEntry.id)}
              alt={winnerEntry.display_name}
            />
          </motion.div>
        ) : (
          <div className="postmatch-v3__portrait postmatch-v3__portrait--empty">
            <Trophy size={64} color="rgba(255,255,255,0.4)" />
          </div>
        )}
        <h1 className="postmatch-v3__name">
          {winnerEntry ? winnerEntry.display_name : "Draw"}
        </h1>
        <div className="postmatch-v3__sub">
          {winnerEntry && winnerEarningsEth !== null
            ? `+${winnerEarningsEth} SepETH`
            : winnerEntry
              ? `${totalScore(state.scores[winnerEntry.id])} reputation points`
              : "no clear winner"}
        </div>
      </motion.section>

      <motion.section
        className="postmatch-v3__scores"
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, delay: 0.2 }}
      >
        {state.combatants.map((c) => {
          const s = state.scores[c];
          const entry = playerById(c);
          return (
            <div key={c} className="scoreline">
              <div className="scoreline__id">
                <img
                  className="scoreline__avatar"
                  src={playerPortrait(c)}
                  alt={entry?.display_name ?? c}
                />
                <div className="scoreline__name">{entry?.display_name ?? c}</div>
                <div className="scoreline__total">{totalScore(s)}</div>
              </div>
              <div className="scoreline__stats">
                <Stat label="wounds dealt" v={s.wounds_inflicted} />
                <Stat label="wounds taken" v={s.wounds_taken} />
                <Stat label="patches" v={s.patches_applied} />
                <Stat label="failed claims" v={s.failed_claims} />
              </div>
            </div>
          );
        })}
      </motion.section>

      <motion.section
        className="postmatch-v3__archive"
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, delay: 0.3 }}
      >
        <div className="postmatch-v3__archive-card">
          <div className="postmatch-v3__archive-title">Seeded vulnerabilities</div>
          <ul className="postmatch-v3__archive-list">
            {seededBugs.map((b, i) => (
              <li key={i}>
                <code>{b.combatant}</code> · {b.vuln_class} · {b.title}
              </li>
            ))}
          </ul>
        </div>

        <div className="postmatch-v3__archive-card">
          <div className="postmatch-v3__archive-title">ENS archive writes</div>
          <ul className="postmatch-v3__archive-list">
            {ensWrites.length === 0 && (
              <li className="postmatch-v3__archive-empty">— no writes captured —</li>
            )}
            {ensWrites.map((w) => (
              <li key={w.id}>
                <span className={"chain-pill chain-pill--" + w.status}>
                  {ENS_LABEL[w.status]}
                </span>{" "}
                <code>{shortName(w.name)}</code> · {w.operation}
                {w.tx_hash && (
                  <span className="postmatch-v3__tx">
                    {w.tx_hash.slice(0, 8)}…{w.tx_hash.slice(-6)}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>

      </motion.section>

      <motion.footer
        className="postmatch-v3__foot"
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, delay: 0.4 }}
      >
        {onHome && (
          <button className="ghost-pill" onClick={onHome}>
            <Home size={14} /> <span>Home</span>
          </button>
        )}
        <button className="primary-pill" onClick={onReplay}>
          <span>Begin another battle</span>
          <ArrowRight size={16} />
        </button>
      </motion.footer>
    </div>
  );
}

function Stat({ label, v }: { label: string; v: number }) {
  return (
    <div className="scoreline__stat">
      <div className="scoreline__stat-num">{v}</div>
      <div className="scoreline__stat-label">{label}</div>
    </div>
  );
}

function totalScore(s: MatchState["scores"][string]): number {
  return (
    s.wounds_inflicted -
    s.wounds_taken +
    s.patches_applied -
    s.patches_broken -
    s.failed_claims
  );
}

// Mirrors the bounty math in services/arena/manager.py::_settle_payouts —
// 0.001 SepETH per verified wound + 0.0005 SepETH per successful patch.
function earningsForAgent(state: MatchState, agentId: string): string | null {
  const s = state.scores[agentId];
  if (!s) return null;
  const eth = s.wounds_inflicted * 0.001 + s.patches_applied * 0.0005;
  if (eth <= 0) return null;
  return eth.toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
}

function pickWinner(state: MatchState): string | null {
  let best: { id: string; total: number } | null = null;
  let tie = false;
  for (const c of state.combatants) {
    const t = totalScore(state.scores[c]);
    if (!best || t > best.total) {
      best = { id: c, total: t };
      tie = false;
    } else if (t === best.total) {
      tie = true;
    }
  }
  return best && !tie ? best.id : null;
}

function shortName(name: string): string {
  if (name.length <= 38) return name;
  return name.slice(0, 18) + "…" + name.slice(-18);
}

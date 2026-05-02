import { ArrowLeft } from "lucide-react";
import { motion } from "framer-motion";
import { useEffect, useState } from "react";
import { portraitUrl } from "../registry";
import { store } from "../state/store";

interface Props {
  onBack: () => void;
}

interface Row {
  agent_id: string;
  display_name: string;
  ens_name: string;
  address: string;
  portrait: string;
  total_wei: number;
  total_eth: string;
  matches_played: number;
  wins: number;
  losses: number;
  wounds_inflicted: number;
  wounds_taken: number;
  bugs_patched: number;
  last_match_ts: number;
  etherscan_url?: string;
}

const MEDAL = ["🥇", "🥈", "🥉"];

export function LeaderboardScene({ onBack }: Props) {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch(`${store.arenaUrl}/api/leaderboard`)
      .then((r) => (r.ok ? r.json() : Promise.reject(`arena ${r.status}`)))
      .then((j) => {
        if (!cancelled) setRows((j.rows ?? []) as Row[]);
      })
      .catch((e) => {
        if (!cancelled) setError(String(e));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="leaderboard-v1">
      <div className="bg-noise" />

      <motion.div
        className="leaderboard-v1__heading"
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
      >
        <button
          className="leaderboard-v1__back"
          onClick={onBack}
          aria-label="Back"
        >
          <ArrowLeft size={16} />
          <span>Home</span>
        </button>
        <h1 className="leaderboard-v1__title">Hall of Fame</h1>
        <div className="leaderboard-v1__sub">
          Cumulative SepETH earned across every match. Every row links to its
          on-chain history.
        </div>
      </motion.div>

      <motion.div
        className="leaderboard-v1__card"
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, delay: 0.15 }}
      >
        {error && <div className="leaderboard-v1__error">{error}</div>}
        {!rows && !error && (
          <div className="leaderboard-v1__empty">loading…</div>
        )}
        {rows && rows.filter((r) => r.matches_played > 0).length === 0 && (
          <div className="leaderboard-v1__empty">
            no matches recorded yet — run one to seed the board
          </div>
        )}
        {rows && rows.filter((r) => r.matches_played > 0).length > 0 && (
          <div className="leaderboard-v1__table">
            <div className="leaderboard-v1__row leaderboard-v1__row--head">
              <div className="lb-col lb-col--rank">#</div>
              <div className="lb-col lb-col--agent">Agent</div>
              <div className="lb-col lb-col--earnings">Earnings</div>
              <div className="lb-col lb-col--wl">W-L</div>
              <div className="lb-col lb-col--num">Wounds</div>
              <div className="lb-col lb-col--num">Patches</div>
            </div>
            {rows
              .filter((r) => r.matches_played > 0)
              .map((r, i) => (
                <motion.div
                  key={r.agent_id}
                  className="leaderboard-v1__row"
                  initial={{ opacity: 0, x: -8 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: 0.05 * i, duration: 0.35 }}
                >
                  <div className="lb-col lb-col--rank">
                    <span className="lb-rank">
                      {MEDAL[i] ?? `${i + 1}`}
                    </span>
                  </div>
                  <div className="lb-col lb-col--agent">
                    <img
                      className="lb-portrait"
                      src={portraitUrl(r.portrait)}
                      alt={r.display_name}
                    />
                    <div className="lb-agent">
                      <div className="lb-agent__name">{r.display_name}</div>
                      {r.ens_name && (
                        r.etherscan_url ? (
                          <a
                            className="lb-agent__ens"
                            href={r.etherscan_url}
                            target="_blank"
                            rel="noreferrer"
                          >
                            {r.ens_name} ↗
                          </a>
                        ) : (
                          <span className="lb-agent__ens">{r.ens_name}</span>
                        )
                      )}
                    </div>
                  </div>
                  <div className="lb-col lb-col--earnings">
                    <span className="lb-earnings">
                      {r.total_eth} <span className="lb-earnings__unit">ETH</span>
                    </span>
                  </div>
                  <div className="lb-col lb-col--wl">
                    {r.wins}–{r.losses}
                  </div>
                  <div className="lb-col lb-col--num">{r.wounds_inflicted}</div>
                  <div className="lb-col lb-col--num">{r.bugs_patched}</div>
                </motion.div>
              ))}
          </div>
        )}
      </motion.div>
    </div>
  );
}

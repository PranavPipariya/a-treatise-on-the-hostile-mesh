import { ArrowRight } from "lucide-react";
import { motion } from "framer-motion";
import { useEffect, useState } from "react";
import { JUDGES, PLAYERS, type RosterEntry, portraitUrl } from "../registry";
import { store } from "../state/store";

interface Props {
  onConfirm: (combatants: [string, string], matchId: string) => void;
  onBack: () => void;
}

export function PlayerPickerScene({ onConfirm, onBack }: Props) {
  const [picked, setPicked] = useState<string[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ensByID, setEnsByID] = useState<Record<string, string>>({});

  // Pre-warm portrait images so the arena has them on first paint.
  useEffect(() => {
    [...PLAYERS, ...JUDGES].forEach((p) => {
      const img = new Image();
      img.src = portraitUrl(p.portrait);
    });
  }, []);

  // Fetch the live roster so we get ens_name from the arena (the static
  // import has no ENS info — it's derived server-side from the env-var parent).
  useEffect(() => {
    fetch(`${store.arenaUrl}/api/roster`)
      .then((r) => (r.ok ? r.json() : null))
      .then((j) => {
        if (!j) return;
        const map: Record<string, string> = {};
        for (const p of j.players ?? []) if (p.ens_name) map[p.id] = p.ens_name;
        setEnsByID(map);
      })
      .catch(() => undefined);
  }, []);

  const toggle = (id: string) => {
    setError(null);
    setPicked((p) => {
      if (p.includes(id)) return p.filter((x) => x !== id);
      if (p.length >= 2) return [p[1], id];
      return [...p, id];
    });
  };

  const begin = async () => {
    if (picked.length !== 2) return;
    setSubmitting(true);
    setError(null);
    try {
      const r = await fetch(`${store.arenaUrl}/api/match/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ combatants: picked }),
      });
      if (!r.ok) {
        throw new Error(`arena ${r.status}: ${await r.text()}`);
      }
      const j = await r.json();
      onConfirm([picked[0], picked[1]], j.match_id);
    } catch (e) {
      setError(String(e));
      setSubmitting(false);
    }
  };

  return (
    <div className="picker-v3">
      <div className="bg-noise" />

      <motion.div
        className="picker-v3__heading"
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
      >
        <button className="picker-v3__back" onClick={onBack} aria-label="Back">
          ←
        </button>
        <h1 className="picker-v3__title">Pick two combatants</h1>
        <div className="picker-v3__count">{picked.length} / 2</div>
      </motion.div>

      <div className="picker-v3__grid">
        {PLAYERS.map((p, i) => (
          <PlayerCard
            key={p.id}
            entry={p}
            ensName={ensByID[p.id]}
            picked={picked.indexOf(p.id)}
            onClick={() => toggle(p.id)}
            delay={i * 0.03}
          />
        ))}
      </div>

      <motion.div
        className="picker-v3__cta"
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.4, duration: 0.5 }}
      >
        {error && <div className="picker-v3__error">{error}</div>}
        <button
          className="primary-pill"
          onClick={begin}
          disabled={picked.length !== 2 || submitting}
        >
          <span>{submitting ? "Opening match…" : "Begin Battle"}</span>
          {!submitting && <ArrowRight size={16} />}
        </button>
      </motion.div>
    </div>
  );
}

function PlayerCard({
  entry,
  ensName,
  picked,
  onClick,
  delay,
}: {
  entry: RosterEntry;
  ensName?: string;
  picked: number;
  onClick: () => void;
  delay: number;
}) {
  const ens = ensName ?? entry.ens_name ?? "";
  return (
    <motion.button
      className={"pcard-v3" + (picked >= 0 ? " pcard-v3--picked" : "")}
      onClick={onClick}
      data-ens={ens || undefined}
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay, duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
      whileTap={{ scale: 0.97 }}
    >
      <div className="pcard-v3__portrait">
        <img
          src={portraitUrl(entry.portrait)}
          alt={entry.display_name}
          loading="lazy"
        />
        {picked >= 0 && (
          <div className="pcard-v3__slot">{picked === 0 ? "P1" : "P2"}</div>
        )}
      </div>
      <div className="pcard-v3__name">{entry.display_name}</div>
    </motion.button>
  );
}

import { AnimatePresence, motion } from "framer-motion";
import { useMemo } from "react";
import { JUDGES, judgePortrait } from "../registry";
import { useStore } from "../state/store";

const ARCHETYPES = JUDGES.map((j) => j.id);

/**
 * Bottom row of 5 judge mini-cards. Each renders a portrait + name; when a
 * commentary bubble fires for that archetype, it pops up *above* the card
 * for ~5 seconds.
 *
 * Bubbles are pulled from the global store and filtered per-archetype so
 * the judges' commentary feels independent + simultaneous.
 */
export function JudgeStrip() {
  const allBubbles = useStore((s) => s.bubbles);

  return (
    <div className="judges">
      {ARCHETYPES.map((archetype) => (
        <JudgeCell
          key={archetype}
          archetype={archetype}
          allBubbles={allBubbles}
        />
      ))}
    </div>
  );
}

function JudgeCell({
  archetype,
  allBubbles,
}: {
  archetype: string;
  allBubbles: ReturnType<typeof useStore<any>>;
}) {
  const judge = JUDGES.find((j) => j.id === archetype)!;
  const bubble = useMemo(() => {
    const list = (allBubbles as any[]).filter(
      (b) => b.archetype === archetype,
    );
    return list[list.length - 1] || null;
  }, [allBubbles, archetype]);

  return (
    <div className="judge">
      <AnimatePresence>
        {bubble && (
          <motion.div
            key={bubble.id}
            className="judge__bubble"
            initial={{ opacity: 0, y: 6, scale: 0.92 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -4, scale: 0.92 }}
            transition={{ duration: 0.28, ease: [0.16, 1, 0.3, 1] }}
          >
            {bubble.text}
          </motion.div>
        )}
      </AnimatePresence>
      <div className={"judge__card" + (bubble ? " judge__card--active" : "")}>
        <img src={judgePortrait(archetype)} alt={judge.display_name} />
      </div>
      <div className="judge__name">{judge.display_name}</div>
    </div>
  );
}

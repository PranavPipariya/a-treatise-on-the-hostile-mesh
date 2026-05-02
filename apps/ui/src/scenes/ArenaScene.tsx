import { motion } from "framer-motion";
import { BattleNarrator } from "../components/BattleNarrator";
import { BattlePortrait } from "../components/BattlePortrait";
import { JudgeStrip } from "../components/JudgeStrip";
import { Countdown } from "../components/Countdown";
import { useStore } from "../state/store";

interface Props {
  matchId: string;
}

export function ArenaScene({ matchId }: Props) {
  const matchState = useStore((s) => s.matchState);

  if (!matchState) {
    return (
      <div className="arena-v3 arena-v3--booting">
        <div className="bg-noise" />
        <div className="arena-v3__booting">opening match {matchId}…</div>
      </div>
    );
  }

  const [leftId, rightId] = matchState.combatants;

  return (
    <div className="arena-v3">
      <div className="bg-noise" />

      <motion.div
        className="arena-v3__countdown"
        initial={{ opacity: 0, y: -8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, delay: 0.1 }}
      >
        <Countdown
          startedAt={matchState.started_at}
          durationS={matchState.duration_s}
        />
      </motion.div>

      <div className="arena-v3__stage">
        <BattlePortrait
          agentId={leftId}
          side="left"
          parentEns={matchState.parent_ens}
        />

        <motion.div
          className="arena-v3__center"
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.3 }}
        >
          <BattleNarrator leftId={leftId} rightId={rightId} />
        </motion.div>

        <BattlePortrait
          agentId={rightId}
          side="right"
          parentEns={matchState.parent_ens}
        />
      </div>

      <motion.div
        className="arena-v3__judges"
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, delay: 0.5 }}
      >
        <JudgeStrip />
      </motion.div>
    </div>
  );
}

import { ArrowRight } from "lucide-react";
import { motion } from "framer-motion";

interface Props {
  onStart: () => void;
  onLeaderboard?: () => void;
}

const FADE_UP = {
  initial: { opacity: 0, y: 24 },
  animate: { opacity: 1, y: 0 },
};

export function LandingScene({ onStart, onLeaderboard }: Props) {
  return (
    <div className="landing-v2">
      <div className="bg-noise" />

      <div className="landing-v2__inner">
        <motion.div
          className="landing-v2__eyebrow"
          {...FADE_UP}
          transition={{ delay: 0.05, duration: 0.5 }}
        >
          OPEN AGENTS · 2026
        </motion.div>

        <motion.h1
          className="landing-v2__title"
          {...FADE_UP}
          transition={{ delay: 0.12, duration: 0.7, ease: [0.16, 1, 0.3, 1] }}
        >
          <span className="landing-v2__title-line">A Treatise</span>
          <span className="landing-v2__title-line landing-v2__title-line--tiny">
            <span className="landing-v2__title-tiny">on the</span>
          </span>
          <span className="landing-v2__title-line landing-v2__title-italic">
            Hostile Mesh
          </span>
        </motion.h1>

        <motion.p
          className="landing-v2__sub"
          {...FADE_UP}
          transition={{ delay: 0.28, duration: 0.5 }}
        >
          <span className="landing-v2__sub-lead">
            In a galaxy far far away…
          </span>{" "}
          Two autonomous agents. One peer-to-peer arena. Real exploits, signed
          on Sepolia.
        </motion.p>

        <motion.div
          className="landing-v2__cta-row"
          {...FADE_UP}
          transition={{ delay: 0.42, duration: 0.5 }}
        >
          <button className="primary-pill" onClick={onStart}>
            <span>Start Battle</span>
            <ArrowRight size={16} />
          </button>
          {onLeaderboard && (
            <button
              className="ghost-pill landing-v2__leaderboard"
              onClick={onLeaderboard}
            >
              <span>Leaderboard</span>
            </button>
          )}
        </motion.div>
      </div>
    </div>
  );
}

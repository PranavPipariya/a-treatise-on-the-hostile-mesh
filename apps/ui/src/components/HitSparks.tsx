import { motion } from "framer-motion";

interface Props {
  /** Where the impact landed: "wound" | "miss" — drives the spark color. */
  kind: "wound" | "miss" | "patch";
  /** Optional key to force re-mount on each new event. */
  triggerId: string;
}

/**
 * Six radial shards bursting from the centre, ~600ms total. Pure framer-motion
 * + transform; no canvas, no particles lib. Re-mounts on every triggerId
 * change so each event gets a fresh burst.
 */
const SPARK_COUNT = 6;

export function HitSparks({ kind, triggerId }: Props) {
  const colorClass = "sparks sparks--" + kind;
  return (
    <div className={colorClass} key={triggerId}>
      {Array.from({ length: SPARK_COUNT }).map((_, i) => {
        const angle = (i / SPARK_COUNT) * Math.PI * 2;
        const distance = 90 + Math.random() * 40;
        const dx = Math.cos(angle) * distance;
        const dy = Math.sin(angle) * distance;
        return (
          <motion.span
            key={i}
            className="sparks__shard"
            initial={{ x: 0, y: 0, opacity: 0, scale: 0.4, rotate: 0 }}
            animate={{
              x: dx,
              y: dy,
              opacity: [0, 1, 0],
              scale: [0.4, 1, 0.6],
              rotate: angle * (180 / Math.PI),
            }}
            transition={{
              duration: 0.6,
              ease: [0.16, 1, 0.3, 1],
              times: [0, 0.3, 1],
            }}
          />
        );
      })}
    </div>
  );
}

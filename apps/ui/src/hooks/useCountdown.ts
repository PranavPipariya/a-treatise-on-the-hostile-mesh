import { useEffect, useState } from "react";

/** Returns seconds remaining (0-floored) given a unix start + duration. */
export function useCountdown(startedAt: number | null, durationS: number): number {
  const [now, setNow] = useState(() => Date.now() / 1000);

  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now() / 1000), 250);
    return () => window.clearInterval(id);
  }, []);

  if (!startedAt) return durationS;
  return Math.max(0, Math.round(startedAt + durationS - now));
}

export function formatMmSs(seconds: number): string {
  const m = Math.floor(seconds / 60).toString().padStart(2, "0");
  const s = (seconds % 60).toString().padStart(2, "0");
  return `${m}:${s}`;
}

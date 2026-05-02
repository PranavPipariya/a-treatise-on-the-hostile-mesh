import { formatMmSs, useCountdown } from "../hooks/useCountdown";

interface Props {
  startedAt: number;
  durationS: number;
}

export function Countdown({ startedAt, durationS }: Props) {
  const remaining = useCountdown(startedAt, durationS);
  const danger = remaining < 30;
  return (
    <div className={"countdown-v3" + (danger ? " countdown-v3--danger" : "")}>
      <div className="countdown-v3__digits">{formatMmSs(remaining)}</div>
    </div>
  );
}

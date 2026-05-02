import { useEffect, useState } from "react";
import { useEventStream } from "./hooks/useEventStream";
import { useMatchState } from "./hooks/useMatchState";
import { ArenaScene } from "./scenes/ArenaScene";
import { LandingScene } from "./scenes/LandingScene";
import { LeaderboardScene } from "./scenes/LeaderboardScene";
import { PlayerPickerScene } from "./scenes/PlayerPickerScene";
import { PostMatchScene } from "./scenes/PostMatchScene";
import { store } from "./state/store";

type Phase = "landing" | "picker" | "arena" | "post" | "leaderboard";

export default function App() {
  const [phase, setPhase] = useState<Phase>("landing");
  const [matchId, setMatchId] = useState<string | null>(null);
  const matchState = useMatchState(matchId);
  useEventStream(matchId);

  // Probe arena health on mount.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch(`${store.arenaUrl}/api/health`);
        if (!r.ok) return;
        const j = await r.json();
        if (!cancelled) store.setEnsChainAvailable(Boolean(j.ens_chain_available));
      } catch {
        /* noop */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Auto-progress to post-match when a match finishes.
  useEffect(() => {
    if (matchState && (matchState.status === "finished" || matchState.status === "aborted")) {
      setPhase("post");
    }
  }, [matchState?.status]);

  if (phase === "landing") {
    return (
      <LandingScene
        onStart={() => setPhase("picker")}
        onLeaderboard={() => setPhase("leaderboard")}
      />
    );
  }

  if (phase === "leaderboard") {
    return <LeaderboardScene onBack={() => setPhase("landing")} />;
  }

  if (phase === "picker") {
    return (
      <PlayerPickerScene
        onConfirm={(_combatants, id) => {
          setMatchId(id);
          setPhase("arena");
        }}
        onBack={() => setPhase("landing")}
      />
    );
  }

  if (phase === "arena") {
    if (!matchId || !matchState) {
      return (
        <div className="arena arena--booting">
          opening match {matchId ?? "…"}…
        </div>
      );
    }
    return <ArenaScene matchId={matchId} />;
  }

  if (phase === "post" && matchState) {
    return (
      <PostMatchScene
        state={matchState}
        onReplay={() => {
          setMatchId(null);
          setPhase("picker");
        }}
        onHome={() => {
          setMatchId(null);
          setPhase("landing");
        }}
      />
    );
  }

  return (
    <LandingScene
      onStart={() => setPhase("picker")}
      onLeaderboard={() => setPhase("leaderboard")}
    />
  );
}

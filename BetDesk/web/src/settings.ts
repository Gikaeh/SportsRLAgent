import { useSyncExternalStore } from "react";
import type { GameCard, Prediction } from "./api/types";

const EARLY_KEY = "deepsports.showEarlyPredictions";
const listeners = new Set<() => void>();

function readEarly(): boolean {
  try {
    return window.localStorage.getItem(EARLY_KEY) === "1";
  } catch {
    return false; // private mode / blocked storage
  }
}

let showEarly = readEarly();

/** Show early-season college predictions (a team has played fewer than 5 games). Off by default. */
export function setShowEarly(on: boolean) {
  if (on === showEarly) return;
  showEarly = on;
  try {
    window.localStorage.setItem(EARLY_KEY, on ? "1" : "0");
  } catch {
    /* storage unavailable: the choice lasts for this visit only */
  }
  listeners.forEach((l) => l());
}

export function useShowEarly(): boolean {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    () => showEarly,
  );
}

/** The prediction to display: early-season ones only when the setting is on. */
export function visiblePrediction(game: GameCard, early: boolean): Prediction | null {
  const p = game.prediction ?? null;
  return p && p.early && !early ? null : p;
}

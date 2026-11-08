import { useEffect, useRef, useState, type ReactNode } from "react";

const THRESHOLD = 70;

/** Pull down at the top of the page to refresh (touch only; standalone PWAs lack a native one). */
export function PullToRefresh({ onRefresh, children }: { onRefresh: () => Promise<void> | void; children: ReactNode }) {
  const [pull, setPull] = useState(0);
  const [busy, setBusy] = useState(false);
  const start = useRef<number | null>(null);
  const pullRef = useRef(0);
  const refreshRef = useRef(onRefresh);
  refreshRef.current = onRefresh;

  useEffect(() => {
    const onStart = (e: TouchEvent) => {
      start.current = window.scrollY <= 0 && e.touches.length === 1 ? e.touches[0].clientY : null;
    };
    const onMove = (e: TouchEvent) => {
      if (start.current == null) return;
      const dy = e.touches[0].clientY - start.current;
      const v = dy > 0 ? Math.min(110, dy * 0.5) : 0;
      pullRef.current = v;
      setPull(v);
    };
    const onEnd = async () => {
      const v = pullRef.current;
      start.current = null;
      pullRef.current = 0;
      setPull(0);
      if (v >= THRESHOLD) {
        setBusy(true);
        try {
          await refreshRef.current();
        } finally {
          setBusy(false);
        }
      }
    };
    window.addEventListener("touchstart", onStart, { passive: true });
    window.addEventListener("touchmove", onMove, { passive: true });
    window.addEventListener("touchend", onEnd);
    window.addEventListener("touchcancel", onEnd);
    return () => {
      window.removeEventListener("touchstart", onStart);
      window.removeEventListener("touchmove", onMove);
      window.removeEventListener("touchend", onEnd);
      window.removeEventListener("touchcancel", onEnd);
    };
  }, []);

  const shown = busy ? 44 : pull;
  return (
    <>
      <div className="ptr" style={{ height: shown }} aria-hidden={!busy}>
        {(busy || pull > 8) && (
          <span className={`ptr-icon${busy ? " spinning" : ""}`} style={{ transform: busy ? undefined : `rotate(${pull * 3}deg)` }}>
            ⟳
          </span>
        )}
        {busy && <span className="sr-only" role="status">Refreshing</span>}
      </div>
      {children}
    </>
  );
}

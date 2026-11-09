import { useEffect, useState } from "react";

/** "6s ago", ticking each second. Its own component so the tick re-renders only this text. */
export function LiveAge({ at }: { at: number | null }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(t);
  }, []);
  if (at == null) return null;
  const s = Math.max(0, Math.floor((now - at) / 1000));
  return <span className="live-age">{s < 60 ? `${s}s` : `${Math.floor(s / 60)}m`} ago</span>;
}

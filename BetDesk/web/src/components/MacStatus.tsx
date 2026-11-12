import { useApi } from "../hooks/useApi";
import { ApiError } from "../api/client";
import type { HealthResponse } from "../api/types";

/**
 * BetDesk reads DeepSports live on the owner's Mac through a Cloudflare Tunnel. Show a banner only
 * when the Mac can't be reached (asleep, offline, tunnel or DeepSports server stopped).
 */
export function MacStatus() {
  const q = useApi<HealthResponse>("/api/health", { refreshSeconds: () => 60, retrySeconds: 30 });
  const e = q.error;
  if (!(e instanceof ApiError)) return null;
  if (e.code === "mac_offline") {
    return (
      <div className="macstatus" role="status">
        The owner's Mac isn't reachable right now, so new data can't load. Retrying…
      </div>
    );
  }
  if (e.code === "origin_auth" || e.code === "not_configured") {
    return (
      <div className="macstatus" role="status">
        BetDesk can't connect to the Mac (setup issue: {e.code}). See BetDesk/docs/SETUP.md.
      </div>
    );
  }
  return null;
}

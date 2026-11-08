import type { ReactNode } from "react";
import { goBack } from "../router";

export function PageHeader({ title, subtitle, back, right }: { title: ReactNode; subtitle?: ReactNode; back?: string; right?: ReactNode }) {
  return (
    <header className="page-header">
      {back && (
        <button type="button" className="back-btn" onClick={() => goBack(back)} aria-label="Back">
          <svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true">
            <path d="M15 5l-7 7 7 7" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      )}
      <div className="page-title-wrap">
        <h1 className="page-title">{title}</h1>
        {subtitle && <p className="page-subtitle">{subtitle}</p>}
      </div>
      {right && <div className="page-header-right">{right}</div>}
    </header>
  );
}

export function UpdatedAt({ at, refreshing, live }: { at: number | null; refreshing: boolean; live?: boolean }) {
  if (!at) return null;
  return (
    <p className="updated" aria-live="off">
      {refreshing ? "Updating…" : `Updated ${new Date(at).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })}`}
      {live && " · auto-refreshing"}
    </p>
  );
}

export function TabBar({ active }: { active: "today" | "standings" | "model" | null }) {
  return (
    <nav className="tabbar" aria-label="Main">
      <a href="#/" className="tab" aria-current={active === "today" ? "page" : undefined}>
        <svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true">
          <rect x="3" y="5" width="18" height="15" rx="3" fill="none" stroke="currentColor" strokeWidth="2" />
          <path d="M3 10h18M8 3v4M16 3v4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        </svg>
        <span>Today</span>
      </a>
      <a href="#/standings" className="tab" aria-current={active === "standings" ? "page" : undefined}>
        <svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true">
          <path d="M5 20V11M12 20V5M19 20v-6" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
        </svg>
        <span>Standings</span>
      </a>
      <a href="#/model" className="tab" aria-current={active === "model" ? "page" : undefined}>
        <svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true">
          <circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor" strokeWidth="2" />
          <circle cx="12" cy="12" r="4" fill="none" stroke="currentColor" strokeWidth="2" />
          <circle cx="12" cy="12" r="1.2" fill="currentColor" />
        </svg>
        <span>Model</span>
      </a>
    </nav>
  );
}

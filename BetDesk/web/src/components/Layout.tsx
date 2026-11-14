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

export function TabBar({ active }: { active: "today" | "bets" | "standings" | "model" | "circa" | null }) {
  return (
    <nav className="tabbar" aria-label="Main">
      <a href="#/" className="tab" aria-current={active === "today" ? "page" : undefined}>
        <svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true">
          <rect x="3" y="5" width="18" height="15" rx="3" fill="none" stroke="currentColor" strokeWidth="2" />
          <path d="M3 10h18M8 3v4M16 3v4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        </svg>
        <span>Today</span>
      </a>
      <a href="#/bets" className="tab" aria-current={active === "bets" ? "page" : undefined}>
        <svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true">
          <circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor" strokeWidth="2" />
          <path d="M12 7v10M14.8 9.4c-.5-.8-1.5-1.2-2.8-1.2-1.6 0-2.7.7-2.7 1.9 0 2.7 5.6 1.3 5.6 3.9 0 1.2-1.2 2-2.9 2-1.4 0-2.4-.5-3-1.4" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
        </svg>
        <span>Bets</span>
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
      <a href="#/circa" className="tab" aria-current={active === "circa" ? "page" : undefined}>
        <svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true">
          <path d="M4 8.5A2.5 2.5 0 0 1 6.5 6h2l1.5-2h4l1.5 2h2A2.5 2.5 0 0 1 20 8.5v9A2.5 2.5 0 0 1 17.5 20h-11A2.5 2.5 0 0 1 4 17.5z" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
          <circle cx="12" cy="13" r="3.5" fill="none" stroke="currentColor" strokeWidth="2" />
        </svg>
        <span>Circa</span>
      </a>
    </nav>
  );
}

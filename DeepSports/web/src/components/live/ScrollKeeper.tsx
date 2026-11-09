import { Component, createRef, type ReactNode } from "react";

type Snapshot = { id: string; top: number } | { bottom: number } | null;

/**
 * Keeps the reader's place when new plays land above what they're reading. Browsers disagree here
 * (iOS Safari has no scroll anchoring), so `.content-live` turns native anchoring off and this does it.
 * A class component because getSnapshotBeforeUpdate is the one way to read the DOM just before a commit.
 */
export class ScrollKeeper extends Component<{ watch: string | null; children: ReactNode }> {
  private root = createRef<HTMLDivElement>();

  getSnapshotBeforeUpdate(prev: { watch: string | null }): Snapshot {
    const el = this.root.current;
    if (!el || prev.watch === this.props.watch) return null;
    const line = document.querySelector(".page-header")?.getBoundingClientRect().bottom ?? 0;
    const box = el.getBoundingClientRect();
    if (box.top >= line) return null; // the list's top is on screen: new rows are meant to be seen
    if (box.bottom <= line) return { bottom: box.bottom }; // scrolled past the whole list
    for (const row of el.querySelectorAll<HTMLElement>("[data-play-id]")) {
      const r = row.getBoundingClientRect();
      if (r.bottom > line) return { id: row.dataset.playId!, top: r.top };
    }
    return null;
  }

  componentDidUpdate(_p: unknown, _s: unknown, snap: Snapshot) {
    const el = this.root.current;
    if (!el || !snap) return;
    let delta = 0;
    if ("bottom" in snap) delta = el.getBoundingClientRect().bottom - snap.bottom;
    else {
      const row = el.querySelector<HTMLElement>(`[data-play-id="${CSS.escape(snap.id)}"]`);
      if (row) delta = row.getBoundingClientRect().top - snap.top;
    }
    if (delta) window.scrollBy({ top: delta, behavior: "instant" });
  }

  render() {
    return <div ref={this.root}>{this.props.children}</div>;
  }
}

"""Build the ManualBets export for the ensemble vote (boundary edge 4), stdlib only.

    uv run python tools/manualbets-export.py --out .sync/manualbets-export.json

nba.com blocks NordVPN, which this Mac runs, so the NBA half runs on the Raspberry Pi on the same
LAN (ssh host `rpi`; the repo clone is ~/SportsRLAgent there, uv kept inside it in `.tools/`, see
docs/PIPELINE.md) and the file is copied back. College reads this Mac's warehouse, so it runs here.
If the Pi fails, the NBA half is tried here too (works when the VPN is off). Prints one line.

    MANUALBETS_NBA_HOST  ssh host for the NBA half (default `rpi`; empty = run it here)
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

MANUALBETS = Path(__file__).resolve().parents[2] / "ManualBets"
REMOTE = "~/SportsRLAgent"
REMOTE_OUT = ".tools/out/manualbets-nba.json"  # relative to REMOTE
TIMEOUT = 900


def run(cmd: list[str], cwd: Path | None = None) -> tuple[bool, str]:
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return False, f"timed out after {TIMEOUT // 60} min"
    last = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""
    return r.returncode == 0, last or f"exit {r.returncode}, no output"


def local(league: str, out: Path) -> tuple[bool, str]:
    script = ["tools/export_predictions.py", "--league", league, "--out", str(out)]
    return run(["uv", "run", "python", *script], cwd=MANUALBETS)


def remote_nba(host: str, out: Path) -> tuple[bool, str]:
    ok, msg = run([
        "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host,
        f"cd {REMOTE} && git pull -q --ff-only || true; cd {REMOTE}/ManualBets && "
        f". ../.tools/env.sh && mkdir -p ../.tools/out && "
        f"uv run python tools/export_predictions.py --league nba --out ../{REMOTE_OUT} 2>/dev/null",
    ])  # fmt: skip
    if not ok:
        return False, msg
    src = f"{host}:{REMOTE}/{REMOTE_OUT}"
    copied, err = run(["scp", "-q", "-o", "BatchMode=yes", src, str(out)])
    return (True, msg) if copied else (False, f"scp failed: {err}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, type=Path)
    out: Path = ap.parse_args().out
    out.parent.mkdir(parents=True, exist_ok=True)
    host = os.environ.get("MANUALBETS_NBA_HOST", "rpi")
    nba_file, ncaab_file = out.with_suffix(".nba.json"), out.with_suffix(".ncaab.json")
    for f in (out, nba_file, ncaab_file):
        f.unlink(missing_ok=True)

    notes = []
    ok, msg = remote_nba(host, nba_file) if host else (False, "no host")
    notes.append(f"nba@{host or 'local'}: {'ok' if ok else msg}")
    if not ok:
        ok, msg = local("nba", nba_file)
        notes.append(f"nba@local: {'ok' if ok else msg}")
    ok, msg = local("ncaab", ncaab_file)
    notes.append(f"ncaab@local: {'ok' if ok else msg}")

    merged: dict = {"source": "ManualBets", "errors": {}}
    remaining = []
    for league, f in (("nba", nba_file), ("ncaab", ncaab_file)):
        try:
            part = json.loads(f.read_text())
        except (OSError, ValueError):
            merged["errors"][league] = "export failed (see the ensemble log)"
            continue
        merged.setdefault("created_at", part.get("created_at"))
        if league in part:
            merged[league] = part[league]
        merged["errors"].update(part.get("errors") or {})
        if part.get("odds_api_remaining") is not None:
            remaining.append(int(part["odds_api_remaining"]))
    if remaining:
        merged["odds_api_remaining"] = min(remaining)
    if "nba" in merged or "ncaab" in merged:
        out.write_text(json.dumps(merged, indent=1))
    print(f"{'; '.join(notes)}; odds_api_remaining {merged.get('odds_api_remaining')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

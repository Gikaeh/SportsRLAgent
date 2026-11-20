"""Closing-line value (CLV) capture and report for NBA bets.

CLV is how much better the number you bet was than the closing line/price at
tip. It is NOT taken when the model runs: the morning snapshot is the line you
bet, and the close only exists later. Run `capture` again in the last hour
before tip, then `record` to append to logs/basketball/betting/clv.csv.

From ManualBets/:
    uv run python tools/clv.py capture            # fresh odds snapshot (1 credit)
    uv run python tools/clv.py record             # append CLV for graded bets
    uv run python tools/clv.py report             # mean CLV per market

`record` pairs each bet with the newest snapshot taken after the bet and before
tip. With no late snapshot there is no CLV row (the report says how many are
missing), so the capture close to tip is the part that matters.
"""
import argparse
import glob
import re
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ODDS_DIR = Path('./data/basketball/odds_data')
LOG_DIR = Path('../logs/basketball/betting')
CLV_FILE = LOG_DIR / 'clv.csv'
PT = ZoneInfo('America/Los_Angeles')
SNAPSHOT_RE = re.compile(r'^(h2h|spread|total)_(\d{4}-\d{2}-\d{2})_(\d{2})-(\d{2})\.csv$')
MARKETS = ('h2h', 'spread', 'total')


def impliedProbability(american_odds):
    if american_odds > 0:
        return 100.0 / (american_odds + 100.0)
    return abs(american_odds) / (abs(american_odds) + 100.0)


def devig(a, b):
    total = a + b
    if total <= 0:
        return a, b
    return a / total, b / total


def snapshotTime(path):
    m = SNAPSHOT_RE.match(Path(path).name)
    if not m:
        return None
    _, date, hh, mm = m.groups()
    return pd.Timestamp(f'{date} {hh}:{mm}', tz=PT)


def loadSnapshots(market):
    out = []
    for path in glob.glob(str(ODDS_DIR / f'{market}_*.csv')):
        ts = snapshotTime(path)
        if ts is None:
            continue
        try:
            df = pd.read_csv(path)
        except pd.errors.EmptyDataError:
            continue
        df['commence_time'] = pd.to_datetime(df['commence_time'], utc=True, errors='coerce', format='ISO8601')
        out.append((ts, path, df))
    return sorted(out, key=lambda x: x[0])


def loadBets(days):
    frames = []
    # The archive is the full history; the live files repeat the newest rows.
    # Archive first so a bet is counted once, at its archive timestamp.
    for market, name in (('h2h', 'h2h_bets.csv'), ('spread', 'spread_bets.csv'), ('total', 'total_bets.csv')):
        for priority, path in ((0, LOG_DIR / 'archive' / name), (1, LOG_DIR / name)):
            if not path.exists():
                continue
            try:
                df = pd.read_csv(path)
            except pd.errors.EmptyDataError:
                continue
            if df.empty:
                continue
            df['market'] = market
            df['_priority'] = priority
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    bets = pd.concat(frames, ignore_index=True, sort=False)
    bets = bets.sort_values('_priority').drop_duplicates(
        subset=['game_id', 'type', 'bet_side'], keep='first').drop(columns='_priority')
    bets['bet_ts'] = pd.to_datetime(bets['timestamp'], errors='coerce', utc=True)
    bets['game_date'] = pd.to_datetime(bets.get('date'), errors='coerce')
    bets = bets[bets['bet_ts'].notna()]
    if days:
        cutoff = pd.Timestamp.now(tz='UTC') - pd.Timedelta(days=days)
        bets = bets[bets['bet_ts'] >= cutoff]
    return bets


def matchupParts(bet):
    """'GSW @ NOP' -> ('GSW', 'NOP'); None when the row is malformed."""
    text = str(bet.get('matchup', ''))
    if ' @ ' not in text:
        return None
    away, home = text.split(' @ ', 1)
    return away.strip(), home.strip()


def sideRows(df, bet):
    """Rows for the side the bet is on."""
    if bet['market'] == 'total':
        side = 'Over' if str(bet.get('bet_side', '')).lower().startswith('over') else 'Under'
        return df[df['name'] == side]
    team = str(bet.get('bet_team', '')).strip()
    return df[df['name'] == team]


def loggedLine(bet):
    if bet['market'] == 'total':
        return pd.to_numeric(bet.get('total_line'), errors='coerce')
    column = 'home_spread' if str(bet.get('bet_side')) == 'home' else 'away_spread'
    return pd.to_numeric(bet.get(column), errors='coerce')


def pickRow(rows, bet):
    """The row at the bet's book, closest to the logged line; fall back to any."""
    if rows.empty:
        return None
    book = str(bet.get('book', '')).strip().lower()
    if 'bookmakers_key' in rows:
        same_book = rows[rows['bookmakers_key'].astype(str).str.lower() == book]
    else:
        same_book = rows.iloc[0:0]
    candidates = same_book if not same_book.empty else rows
    line = loggedLine(bet)
    if pd.notna(line) and 'point' in candidates:
        candidates = candidates.assign(_d=(candidates['point'] - line).abs()).sort_values('_d')
    return candidates.iloc[0]


def closingSnapshot(snapshots, matchup, bet_ts, game_date=None):
    """Newest snapshot after the bet and before tip for this matchup."""
    away, home = matchup
    bet_local = bet_ts.tz_localize(PT) if bet_ts.tzinfo is None else bet_ts.tz_convert(PT)
    for ts, path, df in reversed(snapshots):
        rows = df[(df['home_team'] == home) & (df['away_team'] == away)]
        if rows.empty:
            continue
        commence = rows['commence_time'].dropna().min()
        if pd.isna(commence):
            continue
        commence = commence.tz_convert(PT)
        if ts <= bet_local or ts >= commence:
            continue
        if commence - bet_local > pd.Timedelta(hours=36):
            continue
        # Same pairing can play on consecutive nights; pin the bet's game date.
        if game_date is not None and pd.notna(game_date) and commence.date() != game_date.date():
            continue
        return ts, path, df
    return None


def clvRow(bet, snapshots):
    matchup = matchupParts(bet)
    if matchup is None:
        return None
    found = closingSnapshot(snapshots, matchup, bet['bet_ts'], bet.get('game_date'))
    if found is None:
        return None
    ts, path, df = found
    away, home = matchup
    rows = df[(df['home_team'] == home) & (df['away_team'] == away)]
    side = sideRows(rows, bet)
    close_row = pickRow(side, bet)
    if close_row is None:
        return None

    market = bet['market']
    close_price = float(close_row['price'])
    close_line = float(close_row['point']) if 'point' in close_row and pd.notna(close_row['point']) else None

    # Fair (devigged) probability at the close and at the bet price.
    if market == 'total':
        over = rows[rows['name'] == 'Over']['price']
        under = rows[rows['name'] == 'Under']['price']
        close_fair = None
        if len(over) and len(under):
            fo, fu = devig(impliedProbability(over.max()), impliedProbability(under.max()))
            close_fair = fo if str(bet.get('bet_side', '')).lower().startswith('over') else fu
        bet_fair = None
        if pd.notna(bet.get('over_odds')) and pd.notna(bet.get('under_odds')):
            fo, fu = devig(impliedProbability(float(bet['over_odds'])), impliedProbability(float(bet['under_odds'])))
            bet_fair = fo if str(bet.get('bet_side', '')).lower().startswith('over') else fu
    else:
        home_rows = rows[rows['name'] == home]['price']
        away_rows = rows[rows['name'] == away]['price']
        close_fair = None
        if len(home_rows) and len(away_rows):
            fh, fa = devig(impliedProbability(home_rows.max()), impliedProbability(away_rows.max()))
            close_fair = fh if str(bet.get('bet_side')) == 'home' else fa
        bet_fair = None
        if pd.notna(bet.get('home_odds')) and pd.notna(bet.get('away_odds')):
            fh, fa = devig(impliedProbability(float(bet['home_odds'])), impliedProbability(float(bet['away_odds'])))
            bet_fair = fh if str(bet.get('bet_side')) == 'home' else fa

    clv_points = None
    if close_line is not None:
        if market == 'spread':
            bet_line = float(bet['home_spread'] if str(bet.get('bet_side')) == 'home' else bet['away_spread'])
            clv_points = bet_line - close_line
        elif market == 'total':
            bet_line = float(bet['total_line'])
            clv_points = (close_line - bet_line) if str(bet.get('bet_side', '')).lower().startswith('over') else (bet_line - close_line)

    return {
        'game_id': bet['game_id'],
        'market': market,
        'side': bet.get('bet_team') if market != 'total' else bet.get('bet_side'),
        'line': bet.get('total_line') if market == 'total' else (bet.get('home_spread') if str(bet.get('bet_side')) == 'home' else bet.get('away_spread')),
        'price': bet.get('home_odds') if market != 'total' and str(bet.get('bet_side')) == 'home' else (bet.get('away_odds') if market != 'total' else (bet.get('over_odds') if str(bet.get('bet_side', '')).lower().startswith('over') else bet.get('under_odds'))),
        'bet_timestamp': bet['timestamp'],
        'close_line': close_line,
        'close_price': close_price,
        'clv_points': clv_points,
        'clv_prob': (close_fair - bet_fair) if (close_fair is not None and bet_fair is not None) else None,
        'close_captured_at': ts.isoformat(),
        'source': Path(path).name,
    }


def capture(_args):
    from basketball.data_pipeline.odd_scraping import BasketballOddScraping
    print('Fetching a fresh snapshot now. Run this again close to tip for a real close.')
    BasketballOddScraping().getSpreadOdds()


def record(args):
    bets = loadBets(args.days)
    if bets.empty:
        print('No bets found.')
        return
    new_rows = []
    snaps = {m: loadSnapshots(m) for m in MARKETS}
    for _, bet in bets.iterrows():
        snapshots = snaps.get(bet['market'], [])
        if not snapshots:
            continue
        row = clvRow(bet, snapshots)
        if row is not None:
            new_rows.append(row)
    if not new_rows:
        print('No CLV rows: no snapshot was taken between the bet and tip. '
              'Run `capture` in the last hour before tip.')
        return

    new = pd.DataFrame(new_rows)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    if CLV_FILE.exists():
        old = pd.read_csv(CLV_FILE)
        key = ['game_id', 'market', 'bet_timestamp']
        new = new[~new.set_index(key).index.isin(old.set_index(key).index)]
        if new.empty:
            print('CLV file already has every row.')
            return
        combined = pd.concat([old, new], ignore_index=True)
    else:
        combined = new
    combined.to_csv(CLV_FILE, index=False)
    print(f'Appended {len(new)} CLV row(s) to {CLV_FILE}')


def report(_args):
    if not CLV_FILE.exists():
        print(f'No {CLV_FILE} yet. Run `record` first.')
        return
    df = pd.read_csv(CLV_FILE)
    if df.empty:
        print('CLV file is empty.')
        return
    bets = loadBets(0)
    print(f'CLV rows: {len(df)}  (bets in logs: {len(bets)})')
    for market in MARKETS:
        g = df[df['market'] == market]
        if g.empty:
            continue
        pts = pd.to_numeric(g['clv_points'], errors='coerce').dropna()
        prob = pd.to_numeric(g['clv_prob'], errors='coerce').dropna()
        parts = [f'n={len(g)}']
        if len(pts):
            parts.append(f'mean points {pts.mean():+.2f}, beat close {100 * (pts > 0).mean():.0f}%')
        if len(prob):
            parts.append(f'mean fair-prob CLV {prob.mean() * 100:+.1f} pts, beat close {100 * (prob > 0).mean():.0f}%')
        print(f'  {market:6s} ' + ' | '.join(parts))


def main():
    parser = argparse.ArgumentParser(description='CLV capture and report (NBA)')
    sub = parser.add_subparsers(dest='command', required=True)

    p = sub.add_parser('capture', help='fetch a fresh odds snapshot (1 API credit)')
    p.set_defaults(func=capture)

    p = sub.add_parser('record', help='append CLV rows for bets that have a late snapshot')
    p.add_argument('--days', type=int, default=45, help='only bets from the last N days (0 = all)')
    p.set_defaults(func=record)

    p = sub.add_parser('report', help='summarize CLV by market')
    p.set_defaults(func=report)

    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()

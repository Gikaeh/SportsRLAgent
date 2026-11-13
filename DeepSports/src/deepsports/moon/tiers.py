"""The To The Moon (betting) risk ladder: from keeping the cash to Dubins-Savage bold play.

Each tier is a betting rule the simulator (`sim.py`) replays for 12 months with a deposit at the
start of every month. Bet types follow the owner's decision (DECISIONS 2026-11-13): spreads,
totals, moneylines and ordinary parlays of different games. No props, futures or same-game
parlays.

Stake rules:
- "none":     never bet (the benchmark: just keep the cash)
- "fraction": `fraction` x current balance per bet, up to `bets_per_month` bets a month
- "deposit":  this month's deposit on one bet; winnings are banked, never re-bet
- "all":      the whole balance on one bet a month (let it ride)
- "bold":     Dubins-Savage bold play: stake = min(balance, what reaches the target in one win),
              repeated until the target is reached or the balance is gone
`cash_out`: once the balance touches the target, stop betting for good (deposits still land).
It is on for every betting tier: it roughly doubles P(reach) for the fraction and ticket tiers
(docs/results/2026-11-13-moon-risk-ladder.md); `sim --no-cash-out` shows a tier without it.
`start_month`: first month (1-12) with bets; earlier months only bank the deposit.
"""

from __future__ import annotations

from dataclasses import dataclass

BUDGETS = (50.0, 75.0, 100.0)
DEFAULT_BUDGET = 75.0
TARGETS = (1_000.0, 2_500.0, 10_000.0)
DEFAULT_TARGET = 1_000.0
MONTHS = 12
STANDARD_PRICE = -110  # a standard spread/total price; the default vig comes from it
DOG_PRICE = 300  # the underdog-moneyline tier's typical price (+200 to +400)
STAKE_RULES = ("none", "fraction", "deposit", "all", "bold")


@dataclass(frozen=True)
class Tier:
    id: int
    key: str
    name: str
    description: str
    stake: str
    legs: int = 1
    leg_price: int = STANDARD_PRICE
    fraction: float = 0.0
    bets_per_month: int = 0  # 0 = as many as the rule needs (bold)
    per_day: int = 1  # how many bets `propose` lists on one slate
    cash_out: bool = True
    start_month: int = 1

    def __post_init__(self) -> None:
        if self.stake not in STAKE_RULES:
            raise ValueError(f"unknown stake rule {self.stake!r}")

    @property
    def bet_kind(self) -> str:
        if self.stake == "none":
            return "no bet"
        if self.legs > 1:
            return f"{self.legs}-leg parlay"
        return "moneyline underdog" if self.leg_price > 0 else "single (spread/total)"


TIERS: tuple[Tier, ...] = (
    Tier(1, "cash", "Keep the cash",
         "No bets: deposits only. The benchmark every tier is judged against.", "none",
         cash_out=False),
    Tier(2, "timid", "Timid singles",
         "2% of the balance on each spread/total at -110, about 30 bets a month.",
         "fraction", fraction=0.02, bets_per_month=30, per_day=2),
    Tier(3, "units", "10% singles",
         "10% of the balance on each spread/total at -110, about 10 bets a month.",
         "fraction", fraction=0.10, bets_per_month=10, per_day=1),
    Tier(4, "dogs", "Underdog moneylines",
         "10% of the balance on a +200 to +400 moneyline underdog, about 10 a month.",
         "fraction", leg_price=DOG_PRICE, fraction=0.10, bets_per_month=10, per_day=1),
    Tier(5, "parlay2", "2-leg parlays",
         "20% of the balance on a 2-leg parlay (about +264), about 5 a month.",
         "fraction", legs=2, fraction=0.20, bets_per_month=5, per_day=1),
    Tier(6, "ticket3", "Monthly 3-leg ticket",
         "The month's deposit on one 3-leg parlay (about +596); winnings are banked.",
         "deposit", legs=3, bets_per_month=1),
    Tier(7, "ticket4", "Monthly 4-leg ticket",
         "The month's deposit on one 4-leg parlay (about +1228); winnings are banked.",
         "deposit", legs=4, bets_per_month=1),
    Tier(8, "ride3", "Let it ride, 3-leg",
         "The whole balance on one 3-leg parlay each month.",
         "all", legs=3, bets_per_month=1),
    Tier(9, "bold", "Bold play",
         "Dubins-Savage: stake min(balance, what reaches the target) on -110 singles, "
         "again and again until the target or $0.",
         "bold"),
    Tier(10, "save-bold", "Save, then bold",
         "Bank every deposit for 11 months, then play bold with all of it in month 12; "
         "cash out at the target.",
         "bold", start_month=MONTHS),
)  # fmt: skip

BY_ID = {t.id: t for t in TIERS}
BY_KEY = {t.key: t for t in TIERS}


def get(tier: int | str) -> Tier:
    """A tier by id (1-10, also as a string) or key ('bold')."""
    s = str(tier).strip().lower()
    if s.isdigit() and int(s) in BY_ID:
        return BY_ID[int(s)]
    if s in BY_KEY:
        return BY_KEY[s]
    known = ", ".join(f"{t.id}={t.key}" for t in TIERS)
    raise ValueError(f"unknown tier {tier!r}; known: {known}")

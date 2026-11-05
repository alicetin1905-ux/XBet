"""Data structures used by the surebet finder."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class Quote:
    """The best price found for one outcome of a market."""

    outcome: str
    point: float | None
    bookmaker: str
    bookmaker_title: str
    odds: float  # decimal odds as quoted by the bookmaker
    effective_odds: float  # odds after commission (equal to `odds` for normal bookmakers)


@dataclass(frozen=True)
class Leg:
    """One bet that is part of a surebet."""

    quote: Quote
    stake: float
    payout: float


@dataclass
class Surebet:
    event_id: str
    sport_key: str
    sport_title: str
    home_team: str
    away_team: str
    commence_time: datetime | None
    market: str
    line: float | None
    legs: list[Leg] = field(default_factory=list)
    implied_sum: float = 0.0
    profit_pct: float = 0.0  # theoretical profit on total stake, in percent
    total_stake: float = 0.0
    guaranteed_profit: float = 0.0  # worst-case profit after stake rounding
    matched_names: dict[str, str] = field(default_factory=dict)  # bookmaker -> its name for the game

    @property
    def key(self) -> tuple:
        """Identity used to avoid sending the same alert twice."""
        books = tuple(sorted((l.quote.outcome, l.quote.point, l.quote.bookmaker) for l in self.legs))
        return (self.event_id, self.market, self.line, books)

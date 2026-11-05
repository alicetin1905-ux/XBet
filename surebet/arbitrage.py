"""Core surebet (arbitrage) detection and stake calculation.

A set of mutually exclusive, exhaustive outcomes is a surebet when the sum of
the implied probabilities of the best available odds is below 1:

    S = sum(1 / odds_i) < 1

Staking ``total * (1 / odds_i) / S`` on every outcome returns ``total / S``
whatever happens, i.e. a profit of ``1 / S - 1``.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Iterable, Mapping

from .models import Leg, Quote, Surebet


def implied_sum(odds: Iterable[float]) -> float:
    return sum(1.0 / o for o in odds)


def apply_commission(odds: float, commission: float) -> float:
    """Effective decimal odds when the winnings are taxed (e.g. exchanges)."""
    return 1.0 + (odds - 1.0) * (1.0 - commission)


def calculate_stakes(
    odds: list[float], total_stake: float, round_to: float | None = None
) -> tuple[list[float], list[float]]:
    """Split ``total_stake`` so that every outcome pays out (about) the same.

    Returns ``(stakes, payouts)``. With ``round_to`` (e.g. 1 or 5) the stakes are
    rounded, which makes the bets look less suspicious to bookmakers at the cost
    of slightly unequal payouts.
    """
    s = implied_sum(odds)
    stakes = [total_stake * (1.0 / o) / s for o in odds]
    if round_to:
        stakes = [round(st / round_to) * round_to for st in stakes]
    payouts = [st * o for st, o in zip(stakes, odds)]
    return stakes, payouts


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _line_key(point: float | None) -> float | None:
    # Totals (Over 2.5 / Under 2.5) and spreads (A -1.5 / B +1.5) share abs(point).
    return None if point is None else abs(point)


def _split_market(outcomes: list[dict]) -> dict[float | None, list[dict]]:
    """Split a bookmaker market into one sub-market per line."""
    parts: dict[float | None, list[dict]] = defaultdict(list)
    for o in outcomes:
        parts[_line_key(o.get("point"))].append(o)
    return parts


def find_surebets(
    events: list[dict],
    *,
    total_stake: float = 100.0,
    min_profit_pct: float = 0.0,
    max_profit_pct: float | None = 20.0,
    commissions: Mapping[str, float] | None = None,
    max_age_seconds: float | None = None,
    include_live: bool = False,
    bookmakers: set[str] | None = None,
    exclude_bookmakers: set[str] | None = None,
    round_to: float | None = None,
    now: datetime | None = None,
) -> list[Surebet]:
    """Find surebets in events formatted like The Odds API v4 ``/odds`` response.

    Only bookmakers that list exactly the same set of outcomes (names and
    points) are compared with each other, so e.g. "Over 225.5" is never
    combined with "Under 224.5", and a 2-way moneyline is never mixed with a
    3-way (1X2) market.

    ``max_profit_pct`` filters out implausibly large edges, which are almost
    always stale odds or a bookmaker error that will be voided.
    """
    commissions = commissions or {}
    now = now or datetime.now(timezone.utc)
    results: list[Surebet] = []

    for event in events:
        commence = parse_time(event.get("commence_time"))
        if not include_live and commence is not None and commence <= now:
            continue

        # (market key, line, outcome signature) -> outcome key -> best Quote
        groups: dict[tuple, dict[tuple, Quote]] = defaultdict(dict)

        for book in event.get("bookmakers", []):
            bkey = book["key"]
            if bookmakers and bkey not in bookmakers:
                continue
            if exclude_bookmakers and bkey in exclude_bookmakers:
                continue
            commission = commissions.get(bkey, 0.0)

            for market in book.get("markets", []):
                updated = parse_time(market.get("last_update") or book.get("last_update"))
                if max_age_seconds is not None and updated is not None:
                    if (now - updated).total_seconds() > max_age_seconds:
                        continue

                for line, outcomes in _split_market(market.get("outcomes", [])).items():
                    keys = [(o["name"], o.get("point")) for o in outcomes]
                    if len(keys) < 2 or len(set(keys)) != len(keys):
                        continue
                    signature = tuple(sorted(keys, key=repr))
                    best = groups[(market["key"], line, signature)]

                    for o, okey in zip(outcomes, keys):
                        price = float(o["price"])
                        if price <= 1.0:
                            continue
                        eff = apply_commission(price, commission)
                        current = best.get(okey)
                        if current is None or eff > current.effective_odds:
                            best[okey] = Quote(
                                outcome=o["name"],
                                point=o.get("point"),
                                bookmaker=bkey,
                                bookmaker_title=book.get("title", bkey),
                                odds=price,
                                effective_odds=eff,
                            )

        for (market_key, line, signature), best in groups.items():
            if len(best) != len(signature):
                continue  # some outcome had no valid price
            quotes = [best[k] for k in signature]
            if len({q.bookmaker for q in quotes}) < 2:
                continue  # a single bookmaker never offers a real arb

            odds = [q.effective_odds for q in quotes]
            s = implied_sum(odds)
            if s >= 1.0:
                continue
            profit_pct = (1.0 / s - 1.0) * 100.0
            if profit_pct < min_profit_pct:
                continue
            if max_profit_pct is not None and profit_pct > max_profit_pct:
                continue

            stakes, payouts = calculate_stakes(odds, total_stake, round_to)
            staked = sum(stakes)
            results.append(
                Surebet(
                    event_id=event.get("id", ""),
                    sport_key=event.get("sport_key", ""),
                    sport_title=event.get("sport_title", event.get("sport_key", "")),
                    home_team=event.get("home_team", ""),
                    away_team=event.get("away_team", ""),
                    commence_time=commence,
                    market=market_key,
                    line=line,
                    legs=[Leg(q, st, p) for q, st, p in zip(quotes, stakes, payouts)],
                    implied_sum=s,
                    profit_pct=profit_pct,
                    total_stake=staked,
                    guaranteed_profit=min(payouts) - staked,
                )
            )

    results.sort(key=lambda sb: sb.profit_pct, reverse=True)
    return results

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from surebet.arbitrage import apply_commission, calculate_stakes, find_surebets, implied_sum
from surebet.cli import main

NOW = datetime(2030, 3, 1, 12, 0, tzinfo=timezone.utc)
SAMPLE = json.loads((Path(__file__).parent.parent / "examples" / "sample_odds.json").read_text())


def event(bookmakers, commence="2030-03-01T19:00:00Z", **extra):
    return {"id": "e1", "sport_key": "x", "home_team": "A", "away_team": "B",
            "commence_time": commence, "bookmakers": bookmakers, **extra}


def book(key, markets, last_update="2030-03-01T11:55:00Z"):
    return {"key": key, "title": key.title(), "last_update": last_update, "markets": markets}


def h2h(*prices, names=("A", "B", "Draw")):
    return {"key": "h2h", "outcomes": [{"name": n, "price": p} for n, p in zip(names, prices)]}


def test_implied_sum_and_equal_payouts():
    odds = [2.25, 3.75, 3.90]
    assert implied_sum(odds) == pytest.approx(1 / 2.25 + 1 / 3.75 + 1 / 3.90)
    stakes, payouts = calculate_stakes(odds, 100)
    assert sum(stakes) == pytest.approx(100)
    assert max(payouts) - min(payouts) == pytest.approx(0, abs=1e-9)
    assert payouts[0] == pytest.approx(100 / implied_sum(odds))


def test_rounded_stakes():
    stakes, payouts = calculate_stakes([2.25, 3.75, 3.90], 100, round_to=1)
    assert all(s == int(s) for s in stakes)
    assert min(payouts) > sum(stakes)  # still profitable after rounding


def test_commission():
    assert apply_commission(3.0, 0.05) == pytest.approx(2.9)
    assert apply_commission(3.0, 0.0) == 3.0


def test_finds_three_way_arb_with_best_odds():
    events = [event([
        book("b1", [h2h(2.25, 3.40, 3.30)]),
        book("b2", [h2h(2.10, 3.90, 3.75)]),
    ])]
    [sb] = find_surebets(events, now=NOW)
    best = {l.quote.outcome: (l.quote.bookmaker, l.quote.odds) for l in sb.legs}
    assert best == {"A": ("b1", 2.25), "B": ("b2", 3.90), "Draw": ("b2", 3.75)}
    assert sb.profit_pct == pytest.approx((1 / implied_sum([2.25, 3.90, 3.75]) - 1) * 100)
    assert sb.guaranteed_profit > 0


def test_no_arb_when_margin_positive():
    events = [event([book("b1", [h2h(1.9, 1.9, names="AB")]), book("b2", [h2h(1.95, 1.85, names="AB")])])]
    assert find_surebets(events, now=NOW) == []


def test_does_not_mix_two_way_and_three_way_markets():
    # A 2-way market without draw would look like a huge arb against a 1X2 market.
    events = [event([
        book("b1", [h2h(1.5, 2.8, names="AB")]),
        book("b2", [h2h(2.6, 3.0, 4.0)]),
    ])]
    assert find_surebets(events, now=NOW) == []


def test_does_not_combine_different_total_lines():
    totals = lambda o, u, pt: {"key": "totals", "outcomes": [
        {"name": "Over", "price": o, "point": pt}, {"name": "Under", "price": u, "point": pt}]}
    events = [event([book("b1", [totals(2.10, 1.75, 225.5)]), book("b2", [totals(1.87, 1.95, 224.5)])])]
    assert find_surebets(events, now=NOW) == []

    events = [event([book("b1", [totals(2.05, 1.80, 2.5)]), book("b2", [totals(1.90, 2.02, 2.5)])])]
    [sb] = find_surebets(events, now=NOW)
    assert sb.line == 2.5


def test_spreads_require_matching_sides():
    spread = lambda pa, pb, a, b: {"key": "spreads", "outcomes": [
        {"name": "A", "price": pa, "point": a}, {"name": "B", "price": pb, "point": b}]}
    # A -1.5 / B +1.5 vs A +1.5 / B -1.5 are different markets.
    events = [event([book("b1", [spread(2.5, 1.5, -1.5, 1.5)]), book("b2", [spread(1.4, 2.6, 1.5, -1.5)])])]
    assert find_surebets(events, now=NOW) == []


def test_filters_stale_odds_and_started_events():
    good = [book("b1", [h2h(2.1, 1.9, names="AB")]),
            book("b2", [h2h(1.9, 2.1, names="AB")], last_update="2030-03-01T09:00:00Z")]
    assert len(find_surebets([event(good)], now=NOW)) == 1
    assert find_surebets([event(good)], now=NOW, max_age_seconds=600) == []
    started = event(good, commence="2030-03-01T11:00:00Z")
    assert find_surebets([started], now=NOW) == []
    assert len(find_surebets([started], now=NOW, include_live=True)) == 1


def test_profit_bounds_and_single_bookmaker():
    events = [event([book("b1", [h2h(3.0, 3.0, names="AB")]), book("b2", [h2h(1.1, 1.1, names="AB")])])]
    assert find_surebets(events, now=NOW) == []  # all legs at one bookmaker
    events = [event([book("b1", [h2h(3.0, 1.1, names="AB")]), book("b2", [h2h(1.1, 3.0, names="AB")])])]
    assert find_surebets(events, now=NOW) == []  # 50% edge: almost certainly an error
    assert len(find_surebets(events, now=NOW, max_profit_pct=None)) == 1


def test_commission_can_remove_arb():
    events = [event([book("b1", [h2h(2.02, 1.9, names="AB")]), book("ex", [h2h(1.9, 2.02, names="AB")])])]
    assert len(find_surebets(events, now=NOW)) == 1
    assert find_surebets(events, now=NOW, commissions={"ex": 0.05}) == []


def test_sample_data():
    found = find_surebets(SAMPLE, now=NOW, min_profit_pct=0.5,
                          commissions={"betfair_ex_eu": 0.05})
    summary = {(sb.event_id, sb.market, sb.line) for sb in found}
    assert summary == {
        ("demo-eredivisie-1", "h2h", None),
        ("demo-eredivisie-2", "totals", 2.5),
        ("demo-eredivisie-2", "h2h", None),
        ("demo-nba-1", "h2h", None),
    }


def test_cli_demo(capsys):
    assert main(["--demo", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data and all(d["guaranteed_profit"] > 0 for d in data)

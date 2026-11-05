import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from surebet.arbitrage import find_surebets
from surebet.sources import build_sources, SourceError
from surebet.sources.kambi import parse_list_view
from surebet.sources.merge import group_events, normalize_team, team_similarity, to_odds_events

FIX = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)


def load(name):
    return json.loads((FIX / name).read_text())


def test_parse_kambi_football():
    events = parse_list_view(load("kambi_jpl.json"), "unibet", "Unibet BE", now=NOW)
    assert len(events) == 3
    e = events[0]
    assert (e.home, e.away, e.sport) == ("Standard Luik", "SK Beveren", "football")
    assert e.start == datetime(2026, 11, 6, 19, 45, tzinfo=timezone.utc)
    assert e.markets["h2h"] == [
        {"name": "home", "price": 1.77}, {"name": "draw", "price": 4.10}, {"name": "away", "price": 4.50}]
    assert e.markets["totals"] == [
        {"name": "Over", "price": 1.56, "point": 2.5}, {"name": "Under", "price": 2.38, "point": 2.5}]
    assert e.platform_id.startswith("kambi:")


def test_parse_kambi_basketball_markets():
    events = parse_list_view(load("kambi_basketball.json"), "unibet", "Unibet BE", now=NOW)
    assert {k for e in events for k in e.markets} == {"h2h_ot", "spreads_ot", "totals_ot"}
    spread = events[0].markets["spreads_ot"]
    assert spread[0]["point"] == -spread[1]["point"]  # handicap from each side's perspective


def test_closed_outcomes_are_skipped():
    data = load("kambi_jpl.json")
    data["events"][0]["betOffers"][0]["outcomes"][1]["status"] = "SUSPENDED"
    e = parse_list_view(data, "unibet", "Unibet BE", now=NOW)[0]
    assert "h2h" not in e.markets


@pytest.mark.parametrize("a,b", [
    ("Standard Luik", "Standard de Liège"),
    ("KV Mechelen", "Mechelen"),
    ("Sporting de Charleroi", "R. Charleroi SC"),
    ("OH Leuven", "Oud-Heverlee Leuven"),
])
def test_same_team_matches(a, b):
    assert team_similarity(a, b) >= 0.75, (normalize_team(a), normalize_team(b))


@pytest.mark.parametrize("a,b", [
    ("KRC Genk", "KAA Gent"),
    ("Westerlo", "Beveren"),
])
def test_different_teams_do_not_match(a, b):
    assert team_similarity(a, b) < 0.75


def _other_bookmaker(events, **changes):
    """Same games at a second bookmaker with its own naming and ids."""
    out = []
    for e in events:
        out.append(replace(e, bookmaker="other", bookmaker_title="Other", platform_id=None, **changes))
    return out


def test_grouping_matches_renamed_games():
    unibet = parse_list_view(load("kambi_jpl.json"), "unibet", "Unibet BE", now=NOW)
    other = _other_bookmaker(unibet)
    other[0] = replace(other[0], home="Standard de Liège", away="Beveren",
                       start=other[0].start + timedelta(minutes=5))
    clusters = group_events(unibet + other)
    assert sorted(len(c) for c in clusters) == [2, 2, 2]


def test_grouping_rejects_different_kickoff():
    unibet = parse_list_view(load("kambi_jpl.json"), "unibet", "Unibet BE", now=NOW)[:1]
    other = _other_bookmaker(unibet, start=unibet[0].start + timedelta(hours=3))
    assert len(group_events(unibet + other)) == 2


def test_kambi_operators_share_event_ids():
    unibet = parse_list_view(load("kambi_jpl.json"), "unibet", "Unibet BE", now=NOW)
    napoleon = parse_list_view(load("kambi_jpl.json"), "napoleon", "Napoleon Sports", now=NOW)
    napoleon = [replace(e, home=e.home.upper()) for e in napoleon]  # names differ, ids match
    assert sorted(len(c) for c in group_events(unibet + napoleon)) == [2, 2, 2]


def test_end_to_end_surebet_between_two_bookmakers():
    unibet = parse_list_view(load("kambi_jpl.json"), "unibet", "Unibet BE", now=NOW)[:1]
    # Standard Luik - Beveren at Unibet: 1.77 / 4.10 / 4.50. Other bookie is generous on the home win.
    other = _other_bookmaker(unibet, home="Standard de Liège", away="Beveren")
    other[0].markets = {"h2h": [{"name": "home", "price": 2.40}, {"name": "draw", "price": 3.60},
                                {"name": "away", "price": 3.20}]}
    events = to_odds_events(unibet + other)
    [sb] = find_surebets(events, now=NOW)
    legs = {l.quote.outcome: (l.quote.bookmaker, l.quote.odds) for l in sb.legs}
    assert legs == {"Standard Luik": ("other", 2.40), "Draw": ("unibet", 4.10), "SK Beveren": ("unibet", 4.50)}
    assert sb.matched_names == {"Unibet BE": "Standard Luik - SK Beveren", "Other": "Standard de Liège - Beveren"}


def test_unsupported_bookmaker_explains():
    with pytest.raises(SourceError, match="capture_site"):
        build_sources(["unibet", "bwin"])

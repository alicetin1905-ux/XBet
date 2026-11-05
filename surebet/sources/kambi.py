"""Bookmakers on the Kambi platform (Unibet BE, Napoleon Sports, 711 Sports).

Kambi serves the odds that these websites show from a public JSON feed, the
same one the website itself loads in your browser.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .base import BookEvent, PoliteClient, SourceError

BASE_URL = "https://eu-offering-api.kambicdn.com/offering/v2018"

OPERATORS = {
    # key: (Kambi operator code, display name)
    "unibet": ("ubbe", "Unibet BE"),
    "napoleon": ("ngbe", "Napoleon Sports"),
    "711": ("sevelevbe", "711 Sports"),
}

DEFAULT_SPORTS = ["football", "tennis", "basketball", "ice_hockey"]

# Kambi criterion (English label) -> canonical market key. Anything else is ignored.
CRITERIA = {
    "Full Time": "h2h",
    "Match Odds": "h2h",
    "Match Odds - Regular Time": "h2h",
    "Moneyline - Including Overtime": "h2h_ot",
    "Total Goals": "totals",
    "Total Goals - Regular Time": "totals",
    "Total Points - Including Overtime": "totals_ot",
    "Total Games": "totals_games",
    "Puck Line - Regular Time": "spreads",
    "Point Spread - Including Overtime": "spreads_ot",
    "Game Handicap": "spreads_games",
}

OUTCOME_TYPES = {
    "OT_ONE": "home",
    "OT_CROSS": "draw",
    "OT_TWO": "away",
    "OT_OVER": "Over",
    "OT_UNDER": "Under",
}


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def parse_list_view(data: dict, bookmaker: str, title: str, now: datetime | None = None) -> list[BookEvent]:
    """Convert a Kambi ``listView`` response into BookEvents."""
    now = now or datetime.now(timezone.utc)
    events: list[BookEvent] = []
    for item in data.get("events", []):
        ev = item.get("event", {})
        if not ev.get("homeName") or not ev.get("awayName"):
            continue  # outrights / specials
        sport_path = ev.get("path") or [{}]
        markets: dict[str, list[dict]] = {}
        for offer in item.get("betOffers", []):
            key = CRITERIA.get(offer.get("criterion", {}).get("englishLabel"))
            if key is None or key in markets:
                continue
            outcomes = []
            for o in offer.get("outcomes", []):
                name = OUTCOME_TYPES.get(o.get("type"))
                if name is None or o.get("status") != "OPEN" or not o.get("odds"):
                    outcomes = []
                    break
                out = {"name": name, "price": o["odds"] / 1000.0}
                if "line" in o:
                    out["point"] = o["line"] / 1000.0
                outcomes.append(out)
            if len(outcomes) >= 2:
                markets[key] = outcomes
        if not markets:
            continue
        events.append(
            BookEvent(
                bookmaker=bookmaker,
                bookmaker_title=title,
                sport=sport_path[0].get("termKey", ev.get("sport", "")).lower(),
                league=ev.get("group", ""),
                home=ev["homeName"],
                away=ev["awayName"],
                start=_time(ev["start"]),
                live=ev.get("state") == "STARTED",
                updated=now,
                markets=markets,
                platform_id=f"kambi:{ev['id']}",
            )
        )
    return events


class KambiSource:
    def __init__(self, key: str, sports: list[str] | None = None, leagues: list[str] | None = None,
                 client: PoliteClient | None = None, lang: str = "nl_BE"):
        if key not in OPERATORS:
            raise ValueError(f"Onbekende Kambi-bookmaker '{key}'")
        self.key = key
        self.code, self.title = OPERATORS[key]
        self.sports = sports or DEFAULT_SPORTS
        # e.g. "football/belgium/jupiler_pro_league": all matches of that league, not only the next ~24h
        self.leagues = leagues or []
        self.client = client or PoliteClient()
        self.lang = lang

    def _url(self, path: str) -> str:
        return f"{BASE_URL}/{self.code}/listView/{path}.json?lang={self.lang}&market=BE&useCombined=true"

    def fetch(self) -> list[BookEvent]:
        events: dict[str, BookEvent] = {}
        errors = []
        for path in [*self.sports, *self.leagues]:
            try:
                data = self.client.get_json(self._url(path))
            except SourceError as exc:
                errors.append(str(exc))
                continue
            for e in parse_list_view(data, self.key, self.title):
                events[e.platform_id] = e
        if errors and not events:
            raise SourceError(f"{self.title}: " + "; ".join(errors[:2]))
        return list(events.values())

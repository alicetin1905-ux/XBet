"""Match the same game across bookmakers and build input for ``find_surebets``.

Every bookmaker writes team names differently ("Standard Luik" vs "Standard de
Liège", "KV Mechelen" vs "Mechelen"), so games are matched on sport, kick-off
time and fuzzy team names.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from .base import BookEvent

# Words that carry no meaning for matching.
STOPWORDS = {
    "fc", "kv", "sk", "krc", "rsc", "kaa", "kas", "rfc", "rc", "cf", "sc", "ac", "afc", "cd",
    "ud", "sv", "fk", "as", "us", "ss", "club", "royal", "r", "sporting", "de", "du", "the",
    "royale", "bv", "vv", "kfc", "rwd", "ksc", "kvc", "oh", "rcs", "united", "city", "calcio",
}

# Dutch/French/English place names that refer to the same club.
ALIASES = {
    "luik": "liege", "bergen": "mons", "doornik": "tournai", "namen": "namur",
    "leuven": "louvain", "brussel": "bruxelles", "brussels": "bruxelles",
    "kortrijk": "courtrai", "moeskroen": "mouscron", "gent": "gand",
    "antwerpen": "antwerp", "anvers": "antwerp", "munchen": "munich",
    "praag": "prague", "lissabon": "lisbon", "milaan": "milan", "rome": "roma",
    "keulen": "koln", "cologne": "koln",
}

MAX_START_DIFF_SECONDS = 15 * 60
MIN_SIMILARITY = 0.75


def normalize_team(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    tokens = [ALIASES.get(t, t) for t in s.split()]
    kept = [t for t in tokens if t not in STOPWORDS]
    return " ".join(kept or tokens)


def team_similarity(a: str, b: str) -> float:
    na, nb = normalize_team(a), normalize_team(b)
    if na == nb:
        return 1.0
    ta, tb = set(na.split()), set(nb.split())
    if ta and tb and (ta <= tb or tb <= ta):
        return 0.9
    return SequenceMatcher(None, na, nb).ratio()


def _match_score(a: BookEvent, b: BookEvent) -> float:
    if a.platform_id and a.platform_id == b.platform_id:
        return 2.0
    if a.sport != b.sport:
        return 0.0
    if abs((a.start - b.start).total_seconds()) > MAX_START_DIFF_SECONDS:
        return 0.0
    return min(team_similarity(a.home, b.home), team_similarity(a.away, b.away))


def group_events(events: list[BookEvent]) -> list[list[BookEvent]]:
    """Cluster BookEvents that are the same game. Max one entry per bookmaker."""
    clusters: list[list[BookEvent]] = []
    for ev in sorted(events, key=lambda e: e.start):
        best, best_score = None, MIN_SIMILARITY
        for cluster in clusters:
            if any(c.bookmaker == ev.bookmaker for c in cluster):
                continue
            score = max(_match_score(c, ev) for c in cluster)
            if score >= best_score:
                best, best_score = cluster, score
        if best is None:
            clusters.append([ev])
        else:
            best.append(ev)
    return clusters


def to_odds_events(events: list[BookEvent]) -> list[dict]:
    """Build events in The Odds API format, so ``find_surebets`` can use them."""
    result = []
    for cluster in group_events(events):
        if len(cluster) < 2:
            continue  # nothing to compare with
        ref = cluster[0]
        names = {"home": ref.home, "away": ref.away, "draw": "Draw"}
        books = []
        for ev in cluster:
            if ev.live != ref.live:
                continue
            markets = [
                {
                    "key": key,
                    "outcomes": [{**o, "name": names.get(o["name"], o["name"])} for o in outcomes],
                }
                for key, outcomes in ev.markets.items()
            ]
            books.append({
                "key": ev.bookmaker,
                "title": ev.bookmaker_title,
                "last_update": ev.updated.isoformat(),
                "markets": markets,
            })
        result.append({
            "id": ref.platform_id or f"{ref.sport}:{ref.start.isoformat()}:{ref.home}",
            "sport_key": ref.sport,
            "sport_title": f"{ref.sport} - {ref.league}" if ref.league else ref.sport,
            "commence_time": ref.start.isoformat(),
            "home_team": ref.home,
            "away_team": ref.away,
            "bookmakers": books,
            # How each bookmaker names the game, to check the matching by eye.
            "matched_names": {ev.bookmaker_title: f"{ev.home} - {ev.away}" for ev in cluster},
        })
    return result

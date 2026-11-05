"""Shared types and HTTP helper for bookmaker sources (scrapers)."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)

# Canonical market keys shared by all sources, so markets are only compared
# when they really are the same bet:
#   h2h          result in regular time (1X2 for football/hockey, winner for tennis)
#   h2h_ot       winner including overtime (basketball moneyline)
#   totals       over/under goals in regular time
#   totals_ot    over/under points including overtime
#   totals_games over/under games (tennis)
#   spreads, spreads_ot, spreads_games   handicaps, same split as above
# Outcome names are canonical too: "home", "draw", "away", "Over", "Under".
# Handicap points are always from the perspective of the outcome itself.


class SourceError(RuntimeError):
    pass


@dataclass
class BookEvent:
    """One match as offered by one bookmaker."""

    bookmaker: str
    bookmaker_title: str
    sport: str  # football, tennis, basketball, ice_hockey, ...
    league: str
    home: str
    away: str
    start: datetime
    live: bool
    updated: datetime
    markets: dict[str, list[dict]] = field(default_factory=dict)
    platform_id: str | None = None  # same id across operators of one platform (e.g. Kambi)


class PoliteClient:
    """Small JSON HTTP client that waits between requests to stay gentle."""

    def __init__(self, delay: float = 1.0, timeout: float = 20.0):
        self.delay = delay
        self.timeout = timeout
        self._last = 0.0

    def get_json(self, url: str, headers: dict | None = None):
        wait = self._last + self.delay - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        req = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT, "Accept": "application/json", **(headers or {})}
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            hint = ""
            if exc.code in (403, 429):
                hint = " (geblokkeerd: draai je dit vanaf een Belgische internetverbinding?)"
            raise SourceError(f"HTTP {exc.code} voor {url}{hint}") from exc
        except urllib.error.URLError as exc:
            raise SourceError(f"Verbinding mislukt voor {url}: {exc.reason}") from exc
        finally:
            self._last = time.monotonic()

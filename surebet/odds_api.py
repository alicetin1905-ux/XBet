"""Minimal client for The Odds API v4 (https://the-odds-api.com)."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

BASE_URL = "https://api.the-odds-api.com/v4"


class OddsApiError(RuntimeError):
    pass


class OddsApiClient:
    def __init__(self, api_key: str, base_url: str = BASE_URL, timeout: float = 20.0):
        if not api_key:
            raise OddsApiError("Geen API-key. Zet ODDS_API_KEY of gebruik --api-key.")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.requests_remaining: str | None = None
        self.requests_used: str | None = None

    def _get(self, path: str, **params) -> list[dict]:
        params["apiKey"] = self.api_key
        url = f"{self.base_url}{path}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"User-Agent": "surebet-finder/0.1"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                self.requests_remaining = resp.headers.get("x-requests-remaining")
                self.requests_used = resp.headers.get("x-requests-used")
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="replace")
            raise OddsApiError(f"HTTP {exc.code} voor {path}: {body}") from exc
        except urllib.error.URLError as exc:
            raise OddsApiError(f"Verbinding mislukt voor {path}: {exc.reason}") from exc

    def sports(self, all_sports: bool = False) -> list[dict]:
        params = {"all": "true"} if all_sports else {}
        return self._get("/sports", **params)

    def odds(
        self,
        sport: str,
        regions: str = "eu",
        markets: str = "h2h",
        bookmakers: str | None = None,
    ) -> list[dict]:
        """Fetch odds for one sport key (or ``upcoming`` for all sports).

        Quota cost per call = number of markets x number of regions.
        """
        params = {
            "markets": markets,
            "oddsFormat": "decimal",
            "dateFormat": "iso",
        }
        # The API ignores `regions` when `bookmakers` is given.
        if bookmakers:
            params["bookmakers"] = bookmakers
        else:
            params["regions"] = regions
        return self._get(f"/sports/{sport}/odds", **params)

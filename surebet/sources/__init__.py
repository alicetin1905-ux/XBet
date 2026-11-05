"""Odds sources that read Belgian bookmakers directly."""

from __future__ import annotations

from .base import BookEvent, PoliteClient, SourceError
from .kambi import OPERATORS as KAMBI_OPERATORS, KambiSource
from .merge import group_events, to_odds_events

# Bookmakers that can be scraped right now, and those still waiting for an adapter.
AVAILABLE = {**{k: v[1] for k, v in KAMBI_OPERATORS.items()}}
PLANNED = {
    "bwin": "Bwin.be (Entain)",
    "betcenter": "Betcenter (EveryMatrix)",
    "magicbetting": "Magic Betting (Digitain)",
}
# Checked but not possible without getting around their protection, which this bot doesn't do.
BLOCKED = {
    "starsport": "Starsport / Star Casino (Altenar): de odds-API weigert verzoeken van buiten hun site",
    "vivatbet": "VivatBet: alleen de 10 topwedstrijden zijn open, de rest zit achter een botcontrole",
}


def build_sources(books: list[str], sports: list[str] | None = None, leagues: list[str] | None = None,
                  delay: float = 1.0):
    client = PoliteClient(delay=delay)
    sources = []
    for b in books:
        if b in KAMBI_OPERATORS:
            sources.append(KambiSource(b, sports=sports, leagues=leagues, client=client))
        elif b in BLOCKED:
            raise SourceError(f"{BLOCKED[b]}. Deze bookmaker wordt niet ondersteund.")
        elif b in PLANNED:
            raise SourceError(
                f"{PLANNED[b]} wordt nog niet ondersteund. Gebruik tools/capture_site.py om het "
                "netwerkverkeer op te nemen, dan kan de koppeling gebouwd worden."
            )
        else:
            raise SourceError(f"Onbekende bookmaker '{b}'. Beschikbaar: {', '.join(AVAILABLE)}")
    return sources


def fetch_all(sources) -> tuple[list[BookEvent], list[str]]:
    """Fetch every source; one failing bookmaker doesn't stop the others."""
    events, errors = [], []
    for s in sources:
        try:
            events.extend(s.fetch())
        except SourceError as exc:
            errors.append(str(exc))
    return events, errors


__all__ = [
    "AVAILABLE", "BLOCKED", "PLANNED", "BookEvent", "KambiSource", "PoliteClient", "SourceError",
    "build_sources", "fetch_all", "group_events", "to_odds_events",
]

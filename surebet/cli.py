"""Command line interface.

Examples:
    python -m surebet --demo
    python -m surebet --sports soccer_epl,soccer_netherlands_eredivisie --markets h2h,totals
    python -m surebet --sports upcoming --watch 300 --telegram
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from .arbitrage import find_surebets
from .notify import format_surebet, send_telegram
from .odds_api import OddsApiClient, OddsApiError

DEMO_FILE = Path(__file__).resolve().parent.parent / "examples" / "sample_odds.json"

# Exchanges take commission on net winnings; adjust to your own rate.
DEFAULT_COMMISSIONS = {
    "betfair_ex_eu": 0.05,
    "betfair_ex_uk": 0.05,
    "betfair_ex_au": 0.05,
    "matchbook": 0.02,
    "smarkets": 0.02,
}


def _csv(value: str | None) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()] if value else []


def _parse_commissions(items: list[str]) -> dict[str, float]:
    result = dict(DEFAULT_COMMISSIONS)
    for item in items:
        key, _, pct = item.partition("=")
        if not pct:
            raise argparse.ArgumentTypeError(f"Ongeldige --commission '{item}', gebruik bookie=2.5")
        result[key.strip()] = float(pct) / 100.0
    return result


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="surebet", description="Vind surebets tussen bookmakers.")
    src = p.add_argument_group("databron")
    src.add_argument("--demo", action="store_true", help="gebruik voorbeelddata (geen API-key nodig)")
    src.add_argument("--file", help="lees odds uit een JSON-bestand (Odds API-formaat)")
    src.add_argument("--api-key", default=os.environ.get("ODDS_API_KEY"), help="The Odds API key (of env ODDS_API_KEY)")
    src.add_argument("--sports", default="upcoming", help="komma-gescheiden sport keys, of 'upcoming' (standaard)")
    src.add_argument("--regions", default="eu,uk", help="bookmaker-regio's: eu,uk,us,us2,au (standaard eu,uk)")
    src.add_argument("--markets", default="h2h", help="markten: h2h,totals,spreads (elke markt kost quota)")
    src.add_argument("--list-sports", action="store_true", help="toon beschikbare sport keys en stop")

    f = p.add_argument_group("filters")
    f.add_argument("--stake", type=float, default=100.0, help="totale inzet per surebet (standaard 100)")
    f.add_argument("--min-profit", type=float, default=0.5, help="minimale winst in %% (standaard 0.5)")
    f.add_argument("--max-profit", type=float, default=20.0, help="negeer verdacht hoge winst boven %% (standaard 20)")
    f.add_argument("--max-age", type=float, default=600, help="negeer odds ouder dan N seconden (standaard 600, 0 = uit)")
    f.add_argument("--include-live", action="store_true", help="neem ook al begonnen wedstrijden mee")
    f.add_argument("--bookmakers", help="alleen deze bookmakers (keys, komma-gescheiden)")
    f.add_argument("--exclude", help="sluit deze bookmakers uit")
    f.add_argument("--commission", action="append", default=[], metavar="BOOKIE=PCT",
                   help="commissie op winst, bv. betfair_ex_eu=5 (herhaalbaar)")
    f.add_argument("--round", type=float, dest="round_to", help="rond inzetten af op dit bedrag, bv. 1 of 5")

    o = p.add_argument_group("uitvoer")
    o.add_argument("--watch", type=int, metavar="SEC", help="blijf scannen elke SEC seconden")
    o.add_argument("--telegram", action="store_true",
                   help="stuur nieuwe surebets naar Telegram (env TELEGRAM_BOT_TOKEN en TELEGRAM_CHAT_ID)")
    o.add_argument("--json", action="store_true", help="geef resultaten als JSON")
    o.add_argument("--currency", default="€")
    return p


def load_events(args, client: OddsApiClient | None) -> list[dict]:
    if args.demo or args.file:
        path = Path(args.file) if args.file else DEMO_FILE
        return json.loads(path.read_text())
    events: list[dict] = []
    for sport in _csv(args.sports):
        events.extend(client.odds(sport, regions=args.regions, markets=args.markets,
                                  bookmakers=args.bookmakers))
    return events


def to_json(sb) -> dict:
    return {
        "event_id": sb.event_id,
        "sport": sb.sport_key,
        "match": f"{sb.home_team} vs {sb.away_team}",
        "commence_time": sb.commence_time.isoformat() if sb.commence_time else None,
        "market": sb.market,
        "line": sb.line,
        "profit_pct": round(sb.profit_pct, 3),
        "total_stake": round(sb.total_stake, 2),
        "guaranteed_profit": round(sb.guaranteed_profit, 2),
        "legs": [
            {
                "outcome": l.quote.outcome,
                "point": l.quote.point,
                "bookmaker": l.quote.bookmaker,
                "odds": l.quote.odds,
                "stake": round(l.stake, 2),
                "payout": round(l.payout, 2),
            }
            for l in sb.legs
        ],
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        commissions = _parse_commissions(args.commission)
    except (argparse.ArgumentTypeError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 2

    offline = args.demo or bool(args.file)
    client = None
    if not offline:
        try:
            client = OddsApiClient(args.api_key)
        except OddsApiError as exc:
            print(f"{exc}\nTip: probeer eerst `python -m surebet --demo`.", file=sys.stderr)
            return 2

    if args.list_sports:
        if client is None:
            print("--list-sports heeft een API-key nodig.", file=sys.stderr)
            return 2
        for s in client.sports():
            print(f"{s['key']:<45} {s['title']}")
        return 0

    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    tg_chat = os.environ.get("TELEGRAM_CHAT_ID")
    if args.telegram and not (tg_token and tg_chat):
        print("--telegram vereist TELEGRAM_BOT_TOKEN en TELEGRAM_CHAT_ID.", file=sys.stderr)
        return 2

    seen: dict[tuple, float] = {}
    while True:
        try:
            events = load_events(args, client)
        except (OddsApiError, OSError, json.JSONDecodeError) as exc:
            print(f"Fout bij ophalen odds: {exc}", file=sys.stderr)
            if not args.watch:
                return 1
            time.sleep(args.watch)
            continue

        surebets = find_surebets(
            events,
            total_stake=args.stake,
            min_profit_pct=args.min_profit,
            max_profit_pct=args.max_profit or None,
            commissions=commissions,
            # Demo data has fixed timestamps, so don't apply the freshness filter there.
            max_age_seconds=None if offline or not args.max_age else args.max_age,
            include_live=args.include_live,
            bookmakers=set(_csv(args.bookmakers)) or None,
            exclude_bookmakers=set(_csv(args.exclude)) or None,
            round_to=args.round_to,
        )

        if args.json:
            print(json.dumps([to_json(sb) for sb in surebets], indent=2, ensure_ascii=False))
        else:
            stamp = time.strftime("%H:%M:%S")
            print(f"[{stamp}] {len(events)} wedstrijden gescand, {len(surebets)} surebet(s) gevonden.")
            if client and client.requests_remaining is not None:
                print(f"           API-quota: {client.requests_used} gebruikt, {client.requests_remaining} over.")
            for sb in surebets:
                print()
                print(format_surebet(sb, args.currency))

        if args.telegram:
            for sb in surebets:
                # Only alert for new surebets, or when the edge improved noticeably.
                if sb.profit_pct > seen.get(sb.key, -1.0) + 0.25:
                    try:
                        send_telegram(tg_token, tg_chat, format_surebet(sb, args.currency))
                    except OSError as exc:
                        print(f"Telegram-fout: {exc}", file=sys.stderr)
                seen[sb.key] = max(sb.profit_pct, seen.get(sb.key, -1.0))

        if not args.watch:
            return 0
        time.sleep(args.watch)

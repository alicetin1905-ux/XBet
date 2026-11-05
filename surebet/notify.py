"""Text formatting and Telegram notifications."""

from __future__ import annotations

import json
import urllib.request

from .models import Surebet


def _outcome_label(name: str, point: float | None) -> str:
    if point is None:
        return name
    return f"{name} {point:+g}" if name not in ("Over", "Under") else f"{name} {point:g}"


def format_surebet(sb: Surebet, currency: str = "€") -> str:
    when = sb.commence_time.strftime("%Y-%m-%d %H:%M UTC") if sb.commence_time else "?"
    market = sb.market if sb.line is None else f"{sb.market} ({sb.line:g})"
    lines = [
        f"[+{sb.profit_pct:.2f}%] {sb.sport_title} | {sb.home_team} vs {sb.away_team} | {when}",
        f"  Markt: {market}",
    ]
    def odds_text(q) -> str:
        text = f"{q.odds:.2f}"
        if abs(q.effective_odds - q.odds) > 1e-9:
            text += f" (netto {q.effective_odds:.3f})"
        return text

    width = max(len(_outcome_label(l.quote.outcome, l.quote.point)) for l in sb.legs)
    owidth = max(len(odds_text(l.quote)) for l in sb.legs)
    bwidth = max(len(l.quote.bookmaker_title) for l in sb.legs)
    for leg in sb.legs:
        q = leg.quote
        lines.append(
            f"  {_outcome_label(q.outcome, q.point):<{width}}  @ {odds_text(q):<{owidth}}  {q.bookmaker_title:<{bwidth}}"
            f"  inzet {currency}{leg.stake:,.2f} -> {currency}{leg.payout:,.2f}"
        )
    if len(set(sb.matched_names.values())) > 1:
        names = "; ".join(f"{book}: {name}" for book, name in sb.matched_names.items())
        lines.append(f"  Controleer koppeling -> {names}")
    lines.append(
        f"  Totaal inzet {currency}{sb.total_stake:,.2f} | "
        f"gegarandeerde winst {currency}{sb.guaranteed_profit:,.2f}"
    )
    return "\n".join(lines)


def send_telegram(token: str, chat_id: str, text: str, timeout: float = 15.0) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = json.dumps({"chat_id": chat_id, "text": text}).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        resp.read()

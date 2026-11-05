"""Record how a bookmaker website loads its odds, to build a new adapter.

Run this on your own computer, on a Belgian internet connection:

    pip install playwright
    python -m playwright install chromium
    python tools/capture_site.py bwin          # or: betcenter, magicbetting

A browser window opens on the football page. Click around a bit (a
competition, a match) for about a minute, then press Enter in the terminal.
Do NOT log in: it isn't needed, and this way no personal data ends up in the
recording. Cookies and auth headers are never saved.

The result is written to captures/<site>-<time>.json. Commit it (or send it)
so the adapter for that bookmaker can be written.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

SITES = {
    "bwin": "https://www.bwin.be/nl/sports/voetbal-4",
    "betcenter": "https://sports2.betcenter.be/nl/",  # the sportsbook iframe of betcenter.be
    "magicbetting": "https://magicbettingsports.be/",
}

MAX_BODY = 200_000  # characters kept per response / frame
SKIP_HEADERS = {"cookie", "set-cookie", "authorization", "x-auth-token"}


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in SITES:
        print(f"Gebruik: python tools/capture_site.py <{'|'.join(SITES)}>")
        return 2
    site = sys.argv[1]
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Installeer eerst Playwright:\n  pip install playwright\n  python -m playwright install chromium")
        return 2

    records: list[dict] = []
    lock = threading.Lock()

    def add(rec: dict) -> None:
        with lock:
            records.append(rec)

    def on_response(resp) -> None:
        req = resp.request
        if req.resource_type not in ("xhr", "fetch"):
            return
        ctype = resp.headers.get("content-type", "")
        if "json" not in ctype and "text" not in ctype:
            return
        try:
            body = resp.text()
        except Exception:
            return
        add({
            "kind": "http",
            "method": req.method,
            "url": req.url,
            "status": resp.status,
            "request_headers": {k: v for k, v in req.headers.items() if k.lower() not in SKIP_HEADERS},
            "post_data": (req.post_data or "")[:5000],
            "body": body[:MAX_BODY],
        })

    def on_websocket(ws) -> None:
        add({"kind": "ws_open", "url": ws.url})
        ws.on("framesent", lambda p: add({"kind": "ws_sent", "url": ws.url, "data": str(p)[:MAX_BODY]}))
        ws.on("framereceived", lambda p: add({"kind": "ws_recv", "url": ws.url, "data": str(p)[:MAX_BODY]}))

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=os.environ.get("CAPTURE_HEADLESS") == "1")
        page = browser.new_page(locale="nl-BE")
        page.on("response", on_response)
        page.on("websocket", on_websocket)
        page.goto(SITES[site], wait_until="domcontentloaded", timeout=60_000)
        # Playwright only handles events while we call into it, so wait for Enter on a thread
        # and keep the browser busy in the meantime.
        done = threading.Event()
        threading.Thread(target=lambda: (input(), done.set()), daemon=True).start()
        print("Klik wat rond op de site (voetbal, een competitie, een wedstrijd) en druk dan op Enter...")
        while not done.is_set():
            page.wait_for_timeout(500)
        page.wait_for_timeout(1000)
        browser.close()

    out_dir = Path("captures")
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"{site}-{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps(records, ensure_ascii=False, indent=1))
    kinds = {k: sum(r["kind"] == k for r in records) for k in ("http", "ws_open", "ws_recv")}
    print(f"Opgeslagen: {out}  ({kinds['http']} API-antwoorden, {kinds['ws_open']} websockets, "
          f"{kinds['ws_recv']} websocket-berichten)")
    if not records:
        print("Niets opgenomen. Werd de site geblokkeerd? Zit je op een Belgische verbinding?")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

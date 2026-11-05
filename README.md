# XBet – Surebet finder

Een bot die **surebets** (arbitrage) zoekt tussen bookmakers. Hij leest de odds rechtstreeks
bij Belgische bookmakers (of via [The Odds API](https://the-odds-api.com)), vergelijkt per
wedstrijd de beste odds per uitkomst en meldt combinaties waarbij je, ongeacht de uitslag,
winst maakt.

## Belgische bookmakers (aanbevolen)

The Odds API heeft geen Belgische bookmakers. Daarom kan de bot ze ook rechtstreeks uitlezen,
uit dezelfde odds-feed die hun website in je browser laadt.

| Bookmaker | Platform | Status |
|---|---|---|
| Unibet (`unibet`) | Kambi | ✅ werkt |
| Napoleon Sports (`napoleon`) | Kambi | ✅ ingebouwd, werkt alleen vanaf een Belgische verbinding |
| Bwin.be (`bwin`) | Entain | ⏳ opname nodig (zie hieronder) |
| Betcenter (`betcenter`) | EveryMatrix | ⏳ opname nodig |
| Magic Betting (`magicbetting`) | Digitain | ⏳ opname nodig |

**Draai dit op je eigen pc met een Belgische internetverbinding.** De meeste sites blokkeren
bezoekers uit het buitenland en van servers.

```bash
python -m surebet --books unibet,napoleon
python -m surebet --books unibet,napoleon --leagues football/belgium/jupiler_pro_league --watch 120
```

Zonder `--leagues` kijkt de bot naar de wedstrijden van de komende ~24 uur in voetbal, tennis,
basketbal en ijshockey. De bot wacht standaard 1 seconde tussen verzoeken (`--delay`) om de
sites niet te belasten. Hou het scaninterval redelijk (bv. `--watch 120`).

Unibet en Napoleon krijgen hun odds allebei van Kambi en liggen daardoor vaak dicht bij elkaar.
Surebets zitten vooral *tussen verschillende platforms*, dus de echte winst komt pas met
Bwin, Betcenter en Magic Betting erbij.

### Een nieuwe bookmaker toevoegen: opname maken

Voor Bwin, Betcenter en Magic Betting moet eerst bekeken worden hoe hun site de odds laadt. Dat
kan alleen vanaf een Belgische verbinding:

```bash
pip install playwright
python -m playwright install chromium
python tools/capture_site.py bwin        # of betcenter, magicbetting
```

Er opent een browser. Klik een minuut rond (voetbal, een competitie, een wedstrijd) en druk
op Enter. **Log niet in**, dat is niet nodig. Cookies en inloggegevens worden nooit opgeslagen.
De opname komt in `captures/`; commit en push die, dan kan de koppeling gebouwd worden.

### Hoe worden wedstrijden gekoppeld?

Elke bookmaker schrijft namen anders ("Standard Luik" / "Standard de Liège"). De bot koppelt op
sport, aftraptijd (max. 15 min verschil) en teamnamen (beide teams moeten lijken). Als de
namen verschillen, zie je bij de surebet een regel `Controleer koppeling -> ...`. **Kijk die
altijd na**: een verkeerde koppeling lijkt een surebet, maar is het niet.

## Hoe het werkt

Voor een markt met uitkomsten 1..n en beste odds `o_i`:

```
S = 1/o_1 + 1/o_2 + ... + 1/o_n
```

Is `S < 1`, dan is het een surebet. Zet je `inzet_i = totaal × (1/o_i) / S` in, dan krijg je
altijd `totaal / S` terug, dus een winst van `1/S − 1`.

Voorbeeld: Ajax 2.25 (Unibet), gelijk 3.75 (Pinnacle), PSV 3.90 (William Hill)
→ S = 0.9675 → **+3.36%** winst.

De bot is voorzichtig met wat hij vergelijkt:

- Alleen **identieke markten** worden gecombineerd: geen 2-weg met 3-weg (1X2), geen
  "Over 225.5" met "Under 224.5", geen handicap -1.5 met +1.5 van de verkeerde kant.
- Er moeten **minstens 2 verschillende bookmakers** in zitten.
- **Verouderde odds** (standaard > 10 min) en **al begonnen wedstrijden** worden overgeslagen.
- **Verdacht hoge winst** (standaard > 20%) wordt genegeerd, want dat is bijna altijd een fout
  van de bookmaker of verouderde data.
- **Commissie** van exchanges (Betfair 5%, Matchbook/Smarkets 2%) wordt verrekend.

## Installatie

Python 3.10+ is genoeg; de bot zelf heeft geen externe dependencies.

```bash
pip install -r requirements-dev.txt   # alleen nodig voor de tests
```

## Gebruik via The Odds API

Probeer het eerst met voorbeelddata (geen API-key nodig):

```bash
python -m surebet --demo
```

Met echte odds: maak een gratis key aan op https://the-odds-api.com (500 requests/maand) en:

```bash
export ODDS_API_KEY=jouw_key

# Welke sporten/competities zijn er?
python -m surebet --list-sports

# Alle komende wedstrijden, Europese + Britse bookmakers
python -m surebet --sports upcoming --regions eu,uk

# Specifieke competities, ook over/under, inzet €250, afgerond op hele euro's
python -m surebet --sports soccer_epl,soccer_netherlands_eredivisie \
    --markets h2h,totals --stake 250 --round 1

# Elke 5 minuten scannen en nieuwe surebets naar Telegram sturen
export TELEGRAM_BOT_TOKEN=...  TELEGRAM_CHAT_ID=...
python -m surebet --sports upcoming --watch 300 --telegram
```

Belangrijke opties (`python -m surebet --help` voor alles):

| Optie | Betekenis |
|---|---|
| `--min-profit 0.5` | minimale winst in % |
| `--max-profit 20` | negeer winst boven dit % (waarschijnlijk fout) |
| `--max-age 600` | negeer odds ouder dan N seconden |
| `--bookmakers a,b` / `--exclude a,b` | alleen / niet deze bookmakers (bv. waar je een account hebt) |
| `--commission bookie=PCT` | eigen commissie per bookmaker |
| `--round 5` | inzetten afronden (minder opvallend bij bookmakers) |
| `--json` | uitvoer als JSON |

**Let op de API-quota:** elke call kost `aantal markten × aantal regio's` credits, per sport.
`--sports upcoming --markets h2h --regions eu` kost dus 1 credit per scan. Met `--watch 300`
verbruik je ~290 credits per dag; kies het interval op basis van je abonnement.

## Telegram instellen

1. Stuur `/newbot` naar [@BotFather](https://t.me/BotFather) en kopieer de token.
2. Stuur je bot een bericht en open `https://api.telegram.org/bot<TOKEN>/getUpdates`
   om je `chat.id` te vinden.
3. Zet `TELEGRAM_BOT_TOKEN` en `TELEGRAM_CHAT_ID`.

De bot stuurt per surebet één melding, en opnieuw alleen als de winst duidelijk stijgt.

## Risico's (lees dit even)

Surebets zijn in theorie risicoloos, in de praktijk niet helemaal:

- **Odds veranderen snel.** Plaats eerst de weddenschap met de meest "afwijkende" odds,
  en controleer alles vóór je inzet.
- **Bookmakers beperken accounts** van arbitrage-gokkers (lagere maxima of afsluiten).
- **Verschillende regels**: bv. wat er gebeurt bij een gestaakte wedstrijd, of een tennisser
  die opgeeft, kan per bookmaker verschillen.
- **Palpable errors**: bookmakers mogen weddenschappen op duidelijk foute odds annuleren.
- **Voorwaarden van de bookmakers**: automatisch odds uitlezen staat meestal niet toegestaan in
  hun gebruiksvoorwaarden. De bot leest alleen publieke odds, zonder in te loggen en op een
  rustig tempo. Gebruik hem nooit met je ingelogde account en verwacht dat een site je IP
  tijdelijk kan blokkeren.
- Gok alleen bij **legale, vergunde aanbieders** (in België: met een F1+-vergunning van de
  Kansspelcommissie, vanaf 21 jaar) en alleen met geld dat je kunt missen.

## Tests

```bash
python -m pytest
```

## Structuur

```
surebet/
  arbitrage.py   detectie en inzetberekening
  odds_api.py    client voor The Odds API v4
  sources/       Belgische bookmakers rechtstreeks (kambi.py) en koppelen van wedstrijden (merge.py)
  notify.py      tekstopmaak en Telegram
  cli.py         command line interface
examples/sample_odds.json   demo-data
tools/capture_site.py       opname maken van een bookmaker-site
tests/                      unit tests
```

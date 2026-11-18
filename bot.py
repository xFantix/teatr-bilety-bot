"""Powiadamia na Telegramie, gdy na spektaklu w Teatrze Muzycznym w Gdyni zwolnią się miejsca.

Konfiguracja:
  shows.json            - lista linków "Kup bilet" z bilety.muzyczny.org
  TELEGRAM_TOKEN        - token bota od @BotFather
  TELEGRAM_CHAT_ID      - id czatu, na który idą powiadomienia
Bez zmiennych TELEGRAM_* bot tylko wypisuje wiadomości na stdout (tryb testowy).
"""

import html
import http.cookiejar
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://bilety.muzyczny.org/rezerwacja/"
ROOT = Path(__file__).parent
SHOWS_FILE = ROOT / "shows.json"
STATE_FILE = ROOT / "state.json"
USER_AGENT = "Mozilla/5.0 (teatr-bilety-bot; sprawdza wolne miejsca)"
MAX_SEATS_LISTED = 10
MIN_FREE_SEATS = 2  # ile biletów potrzebujemy - rzadziej nie ma sensu powiadamiać


def fetch(opener, url, referer=None):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    if referer:
        req.add_header("Referer", referer)
        req.add_header("X-Requested-With", "XMLHttpRequest")
    with opener.open(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


def check_show(url):
    """Zwraca (tytuł, liczba wolnych miejsc, bloki sąsiednich wolnych miejsc) dla linku "Kup bilet"."""
    # Endpoint z miejscami wymaga sesji założonej przez stronę wyboru miejsc.
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )
    page = fetch(opener, url)

    params = {}
    for name in ("ter_id", "wiz_id", "cen_id"):
        m = re.search(rf"var {name}=(\d+);", page)
        if not m:
            raise RuntimeError(f"brak '{name}' na stronie - spektakl nienumerowany, zakończony lub zmienił się system")
        params[name] = m.group(1)
    for name in ("ter_idt", "wiz_idt"):
        params[name] = re.search(rf"var {name}='([0-9a-f]+)';", page).group(1)

    m = re.search(r'<h2 class="nazwa">\s*(.*?)\s*<time[^>]*>(.*?)</time>', page, re.S)
    title = f"{html.unescape(m.group(1)).strip()} ({html.unescape(m.group(2)).strip()})" if m else url

    data = json.loads(fetch(opener, BASE + "miejsca-wolne.html?" + urllib.parse.urlencode(params), referer=url))
    if data.get("status") != 0:
        raise RuntimeError(f"system biletowy zwrócił błąd: {data.get('komunikat')}")
    if not data.get("miejsca"):
        raise RuntimeError("pusta lista miejsc")

    # Klasa "w ..." = wolne, "z" = zajęte.
    free = [s for s in data["miejsca"] if s["class"].split()[0] == "w"]
    return title, len(free), adjacent_blocks(page, free)


def adjacent_blocks(page, free):
    """Grupuje wolne miejsca w bloki stojące obok siebie i zwraca te z min. MIN_FREE_SEATS miejscami.

    Sąsiedztwo liczymy z planu sali (SVG), nie z numerów - numeracja bywa nieparzyste/parzyste po
    przeciwnych stronach. Miejsca w rzędzie mają ten sam y i stały odstęp, przejścia są dużo szersze.
    """
    positions = {}
    for attrs in re.findall(r'<rect([^>]*class="miejsce[^"]*"[^>]*)>', page):
        a = dict(re.findall(r'(\w+)="([^"]*)"', attrs))
        positions[a["id"]] = (float(a["y"]), float(a["x"]), float(a["width"]))

    seats = sorted(
        (positions[str(s["id"])], s["title"]) for s in free if str(s["id"]) in positions
    )
    blocks = []
    prev = None
    for (y, x, width), title in seats:
        if prev and prev[0] == y and x - prev[1] <= width * 1.5:
            blocks[-1].append(title)
        else:
            blocks.append([title])
        prev = (y, x)
    return [b for b in blocks if len(b) >= MIN_FREE_SEATS]


def parse_seat(title):
    # title wygląda jak "Rząd:&nbsp;1;Miejsce:&nbsp;2<br />...<td>bilet normalny II</td><td>170 zł</td>..."
    text = html.unescape(title).replace("\xa0", " ")
    row = re.search(r"Rząd:\s*([^;<]+)", text)
    seat = re.search(r"Miejsce:\s*([^;<]+)", text)
    price = re.search(r"<td>([\d ,]+zł)</td>", text)
    return (
        row.group(1).strip() if row else "?",
        seat.group(1).strip() if seat else "?",
        price.group(1) if price else None,
    )


def describe_block(block):
    seats = [parse_seat(t) for t in block]
    numbers = ", ".join(s[1] for s in seats)
    prices = sorted({s[2] for s in seats if s[2]})
    return f"rząd {seats[0][0]}, miejsca {numbers}" + (f" ({' / '.join(prices)})" if prices else "")


def notify(message):
    token = os.environ.get("TELEGRAM_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("[tryb testowy, brak TELEGRAM_*]\n" + message)
        return
    body = urllib.parse.urlencode(
        {"chat_id": chat_id, "text": message, "disable_web_page_preview": "true"}
    ).encode()
    urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", body, timeout=30)


def main():
    shows = json.loads(SHOWS_FILE.read_text())
    old_state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    state = {}
    new_shows = []
    failed = False

    for url in shows:
        try:
            title, free_count, blocks = check_show(url)
        except Exception as e:
            print(f"BŁĄD {url}: {e}", file=sys.stderr)
            failed = True
            if url in old_state:
                state[url] = old_state[url]
            continue

        # Stan = liczba wolnych miejsc w blokach min. MIN_FREE_SEATS sąsiednich miejsc.
        together = sum(len(b) for b in blocks)
        previous = old_state.get(url)
        print(f"{title}: {free_count} wolnych, {together} obok siebie (poprzednio: {previous})")

        if previous is None:
            new_shows.append(f"• {title}: {free_count} wolnych, {len(blocks)} bloków obok siebie")
        elif together > previous:
            lines = "\n".join(f"• {describe_block(b)}" for b in blocks[:MAX_SEATS_LISTED])
            more = f"\n…i {len(blocks) - MAX_SEATS_LISTED} więcej" if len(blocks) > MAX_SEATS_LISTED else ""
            notify(
                f"🎭 Są min. {MIN_FREE_SEATS} miejsca obok siebie: {title}\n{lines}{more}\n\nKup: {url}"
            )
        state[url] = together

    if new_shows:
        notify(
            f"👀 Obserwuję {len(new_shows)} termin(ów), powiadomię gdy będzie min. {MIN_FREE_SEATS} miejsc obok siebie:\n"
            + "\n".join(new_shows)
        )

    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

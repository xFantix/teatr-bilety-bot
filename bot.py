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
    """Zwraca (tytuł, lista wolnych miejsc) dla linku "Kup bilet"."""
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
    free = [describe_seat(s["title"]) for s in data["miejsca"] if s["class"].split()[0] == "w"]
    return title, free


def describe_seat(title):
    # title wygląda jak "Rząd:&nbsp;1;Miejsce:&nbsp;2<br />...<td>bilet normalny II</td><td>170 zł</td>..."
    text = html.unescape(title).replace("\xa0", " ")
    row = re.search(r"Rząd:\s*([^;<]+)", text)
    seat = re.search(r"Miejsce:\s*([^;<]+)", text)
    price = re.search(r"<td>([\d ,]+zł)</td>", text)
    desc = f"rząd {row.group(1).strip()}, miejsce {seat.group(1).strip()}" if row and seat else "miejsce"
    return f"{desc} ({price.group(1)})" if price else desc


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
            title, free = check_show(url)
        except Exception as e:
            print(f"BŁĄD {url}: {e}", file=sys.stderr)
            failed = True
            if url in old_state:
                state[url] = old_state[url]
            continue

        previous = old_state.get(url)
        print(f"{title}: {len(free)} wolnych (poprzednio: {previous})")

        if previous is None:
            new_shows.append(f"• {title}: {len(free)} wolnych")
        elif len(free) > previous and len(free) >= MIN_FREE_SEATS:
            seats = "\n".join(f"• {s}" for s in free[:MAX_SEATS_LISTED])
            more = f"\n…i {len(free) - MAX_SEATS_LISTED} więcej" if len(free) > MAX_SEATS_LISTED else ""
            notify(
                f"🎭 Zwolniły się miejsca: {title}\n"
                f"Wolnych: {len(free)} (było {previous})\n{seats}{more}\n\nKup: {url}"
            )
        state[url] = len(free)

    if new_shows:
        notify(
            f"👀 Obserwuję {len(new_shows)} termin(ów), powiadomię gdy będzie min. {MIN_FREE_SEATS} wolnych:\n"
            + "\n".join(new_shows)
        )

    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

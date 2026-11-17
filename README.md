# teatr-bilety-bot

Co 5 minut sprawdza wolne miejsca na wybranych spektaklach Teatru Muzycznego w Gdyni
(bilety.muzyczny.org) i wysyła powiadomienie na Telegramie, gdy liczba wolnych miejsc wzrośnie.
Działa na GitHub Actions — za darmo w publicznym repo, bez włączonego komputera.

## Konfiguracja

1. **Bot Telegrama:** napisz do [@BotFather](https://t.me/BotFather) → `/newbot` → zapisz token.
2. **Chat ID:** napisz cokolwiek do swojego nowego bota, potem otwórz
   `https://api.telegram.org/bot<TOKEN>/getUpdates` i skopiuj `message.chat.id`.
3. **Sekrety w repo:** Settings → Secrets and variables → Actions → dodaj
   `TELEGRAM_TOKEN` i `TELEGRAM_CHAT_ID`.
4. **Spektakle:** w `shows.json` wpisz linki z przycisku „Kup bilet” na
   [muzyczny.org/pl/repertuar.html](https://www.muzyczny.org/pl/repertuar.html) (jeden link = jeden termin).
5. **Start:** zakładka Actions → „Sprawdź bilety” → Run workflow. Pierwsze uruchomienie
   wysyła wiadomość „Obserwuję…” — to potwierdzenie, że wszystko działa.

## Lokalnie

```sh
python3 bot.py   # bez TELEGRAM_* wypisuje wiadomości zamiast wysyłać
```

## Uwagi

- Obsługiwane są tylko spektakle z numerowanymi miejscami.
- Harmonogram GitHub Actions bywa opóźniony o kilka–kilkanaście minut.
- `state.json` (ostatnia liczba wolnych miejsc) jest commitowany przez workflow.
- Po zakończonym spektaklu usuń jego link z `shows.json`, inaczej workflow będzie zgłaszał błąd.

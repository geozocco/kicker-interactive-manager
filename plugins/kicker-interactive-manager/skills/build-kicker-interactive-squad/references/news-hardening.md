# News-Härtung

## Zielbild

Die News-Prüfung ist hybrid:

1. Ein zentraler täglicher Lauf liest SportsMonks und API-Sports mit den geheimen Provider-Schlüsseln aus.
2. Er veröffentlicht ausschließlich ein normalisiertes Snapshot ohne Schlüssel und ohne vollständige Rohantworten.
3. Jeder Optimierungslauf lädt dieses Snapshot, prüft Alter, Wettbewerb, Saison, Prüfsumme, Spielerzuordnung und Provider-Konflikte.
4. Offizielle Vereins-, Liga- und Transfermeldungen bleiben der gezielte Fallback für fehlende Zuordnungen, Konflikte und besonders folgenreiche Meldungen.

Provider-Schlüssel niemals in das Plugin, in Annotationen, in das Snapshot, in Browseraktionen oder in eine Antwort an den Nutzer schreiben. Auf Kollegenrechnern werden nur `KICKER_NEWS_FEED_URL` und optional `KICKER_NEWS_FEED_TOKEN` benötigt.

## Sicherheitsregeln

- Ein aktuelles Snapshot läuft nach höchstens 18 Stunden ab. Ein abgelaufenes oder nicht zum Wettbewerb beziehungsweise zur Saison passendes Snapshot darf keinen finalen Browserumbau begründen.
- Risiken aus dem Snapshot dürfen manuelle Annotationen erhöhen, aber niemals herabsetzen. Die Fitness darf nur nach unten begrenzt werden.
- Ein Transfergerücht führt nie automatisch zum Ausschluss. Es erhöht Transfer- und Rollenrisiko und kann den Status als verlässlicher Anker kosten.
- Ein bestätigter Transfer wird nur dann als Abgang behandelt, wenn die Richtung aus dem aktuellen Verein heraus verifiziert ist. Historische oder eingehende Transfers sind kein Ausschlussgrund.
- Ein harter Ausschluss erfordert mindestens mittlere Konfidenz, keine offene Quellen- oder Identitätskollision und entweder bestätigte Nichtverfügbarkeit oder einen verifizierten Abgang aus dem Wettbewerb.
- Namens- oder Vereinsabweichungen bei derselben Kicker-ID sind ein Konflikt. Ausgewählte Spieler mit offenem Konflikt blockieren den finalen Lauf.
- Für jeden ausgewählten Spieler muss bei mindestens einem Provider ein verifiziertes Paar aus Spieler- und aktuellem Team-ID vorliegen. Nur so lässt sich die Richtung eines Transfers sicher bewerten. Fehlt es, den Spieler am selben Tag manuell in Primärquellen prüfen und die zentrale Zuordnung ergänzen, bevor Chrome geändert wird.
- Direkt vor dem ersten Verkauf Snapshot erneut laden. Liegt die letzte Prüfung mehr als zwei Stunden zurück oder gab es neue Meldungen, finalen Lauf mit demselben Seed wiederholen.

## Zentralen Aktualisierungslauf einrichten

Die Mapping-Datei verbindet Kicker-IDs mit Provider-IDs:

```json
{
  "competition": "2. Bundesliga",
  "season": "2026/27",
  "api_sports": {
    "league_id": 79,
    "season": 2026,
    "team_ids": {
      "Beispielverein": 222
    },
    "competition_team_ids_complete": true,
    "transfer_lookback_days": 120
  },
  "sportsmonks": {
    "team_ids": {
      "Beispielverein": 1234
    },
    "competition_team_ids_complete": true,
    "transfer_lookback_days": 120
  },
  "players": {
    "pl-k00123456": {
      "name": "Beispielspieler",
      "club": "Beispielverein",
      "api_sports_player_id": 111,
      "api_sports_team_id": 222,
      "sportsmonks_player_id": 333,
      "sportsmonks_team_id": 1234,
      "mapping_confidence": "verified"
    }
  }
}
```

Die Liga- und Team-IDs sind providerabhängig und müssen vor dem ersten Lauf gegen den aktuellen Wettbewerb geprüft werden. `competition_team_ids_complete` erst dann auf `true` setzen, wenn wirklich alle aktuellen Vereine der Liga in `team_ids` oder `competition_team_ids` enthalten sind. Nur dann darf ein Zielverein außerhalb dieser Menge als bestätigter Abgang aus dem Wettbewerb gewertet werden. Ein Wechsel innerhalb der Ligamenge erhöht dagegen lediglich Rollen- und Transferrisiko. Anschließend zentral ausführen:

```text
SPORTMONKS_API_TOKEN=<secret> API_SPORTS_KEY=<secret> <python-3-command> scripts/refresh_news_snapshot.py --mapping <mapping-json> --output <snapshot-directory>/2-bundesliga.json
```

Der Lauf ist für eine tägliche Ausführung gedacht. Er verwendet begrenzte Wiederholungen mit Backoff, vollständige Pagination, API-Sports-Batches bis 20 Spieler, vereinsweise statt spielerweise Transferabfragen, die SportsMonks-Gerüchte der letzten höchstens 31 Tage, providerseitige Aktualitätsdaten und atomaren Dateiaustausch. Nach einem fehlgeschlagenen Refresh bleibt die vorige Datei erhalten, läuft aber regulär ab und wird danach vom Optimierer abgelehnt.

## Feed bereitstellen

Das Snapshot über einen internen HTTPS-Endpunkt ausliefern. Dafür kann `scripts/serve_news_feed.py` hinter einem TLS-Reverse-Proxy verwendet werden:

```text
KICKER_NEWS_FEED_TOKEN=<shared-random-token> <python-3-command> scripts/serve_news_feed.py --root <snapshot-directory> --host 127.0.0.1 --port 8787
```

Der Reverse-Proxy veröffentlicht zum Beispiel:

```text
https://intern.example.org/v1/news/2-bundesliga.json
```

Er muss HTTPS erzwingen und den Backend-Port nicht öffentlich freigeben. Der mitgelieferte Server prüft Bearer-Token, sichere Dateinamen, Snapshot-Gültigkeit und ETags. Alternativ ist jeder interne HTTPS-Speicher zulässig, der dieselbe JSON-Datei unverändert und zugriffsgeschützt ausliefert.

Auf jedem Kollegenrechner werden URL und optional Feed-Token als lokale Umgebungsvariablen gesetzt. Niemals die Provider-Schlüssel verteilen:

```text
KICKER_NEWS_FEED_URL=https://intern.example.org/v1/news/2-bundesliga.json
KICKER_NEWS_FEED_TOKEN=<feed-token>
```

## Finaler Optimierungslauf

```text
<python-3-command> scripts/optimize_squad.py --players <players-csv> --annotations <annotations-json> --competition "2. Bundesliga" --season "2026/27" --news-snapshot <https-url-oder-datei> --require-news-snapshot --require-news-coverage --profile reliable --variation medium --maintenance low --min-reliable-anchors 3 --seed <seed> --budget <budget> --format json
```

`news_audit` im Ergebnis dokumentiert Snapshot-Prüfsumme, Providerstatus, Erzeugungs- und Ablaufzeit, angewandte Spieler, fehlende Zuordnungen, Konflikte und harte Ausschlüsse. Dieses Audit vor jeder Browseränderung lesen.

## Fallback ohne erreichbaren Feed

Ist der zentrale Feed vorübergehend nicht erreichbar, keinen alten Snapshot schönreden. Für einen finalen Lauf entweder:

- den zentralen Refresh reparieren und erneut laden oder
- jeden möglichen Zielspieler und entscheidenden Near-Miss am selben Tag manuell über offizielle Vereins-/Ligameldungen und eine zweite belastbare Quelle prüfen, vollständig annotieren und offen dokumentieren, dass der zentrale News-Gate nicht verfügbar war.

Bei einem offenen Konflikt über Verletzung, Spielberechtigung oder Transferstatus keine Browseränderung vornehmen. `--allow-news-conflicts` ist nur ein technischer, ausdrücklich zu begründender Override nach dokumentierter manueller Klärung.

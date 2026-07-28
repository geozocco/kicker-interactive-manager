# News-Härtung

## Zielbild

Die News-Prüfung ist hybrid:

1. Ein zentraler Lauf liest API-Sports viermal täglich mit dem geheimen Provider-Schlüssel aus. Sportmonks ist als optionale unabhängige Zweitquelle zugeschaltet, sobald Token sowie verifizierte Team- und Spielerzuordnungen vorliegen. OpenAI Web Search recherchiert priorisierte aktuelle Rollenfragen und liefert streng strukturierte, quellengebundene Profile.
2. Er veröffentlicht ausschließlich ein normalisiertes Snapshot ohne Schlüssel und ohne vollständige Rohantworten.
3. Der zentrale Qualitätslauf verbindet dieses Snapshot mit einem getrennten, ebenfalls frischen Vorbereitungssnapshot und prüft Alter, Wettbewerb, Saison, Prüfsummen, Spielerzuordnung und Provider-Konflikte.
4. Offizielle Vereins-, Liga- und Transfermeldungen bleiben der gezielte Fallback für fehlende Zuordnungen, Konflikte und besonders folgenreiche Meldungen.

Provider-Schlüssel niemals in das Plugin, in Annotationen, in das Snapshot, in Browseraktionen oder in eine Antwort an den Nutzer schreiben. Die offiziellen Team-Feeds für 2. Bundesliga und 3. Liga 2026/27 sind im Optimierer hinterlegt; Kollegen benötigen weder Provider-Schlüssel noch lokale Feed-Konfiguration.

Vorbereitung nicht als gewöhnliche News-Risikomeldung modellieren. Testspiele besitzen eigene Stichproben-, Quellen- und Verfallsregeln nach [preseason-evidence.md](preseason-evidence.md). Der News-Gate bleibt für Verletzung, Transfer und Verfügbarkeit maßgeblich.

## Sicherheitsregeln

- Ein aktuelles Snapshot läuft nach höchstens 18 Stunden ab. Ein abgelaufenes oder nicht zum Wettbewerb beziehungsweise zur Saison passendes Snapshot darf keinen finalen Browserumbau begründen.
- Risiken aus dem Snapshot dürfen manuelle Annotationen erhöhen, aber niemals herabsetzen. Die Fitness darf nur nach unten begrenzt werden.
- Ein Transfergerücht führt nie automatisch zum Ausschluss. Es erhöht Transfer- und Rollenrisiko und kann den Status als verlässlicher Anker kosten.
- Die automatische Kadererkennung speichert auch die Provider-Position. Dadurch kann der Qualitätslauf vereinsweise alle Torhüter erkennen. Ein bereits im Provider-Kader geführter, aber noch nicht im aktuellen Kicker-Markt zuordenbarer eingehender Torwart erhöht das externe Besetzungsrisiko des gesamten Blocks deutlich; ein bloßer zusätzlicher Nachwuchskeeper ohne Transferbeleg erhöht nur die Unsicherheit.
- Torwarttransfers werden nicht wie gewöhnliche Rotationssignale behandelt. Da Trainer eine Nummer eins häufig langfristig festlegen, senkt ein plausibler externer Stammkeeper die Saison-Stammplatzwahrscheinlichkeit des bisherigen Favoriten und kann den Block für `gering` vollständig sperren.
- Ein bestätigter Transfer wird nur dann als Abgang behandelt, wenn die Richtung aus dem aktuellen Verein heraus verifiziert ist. Historische oder eingehende Transfers sind kein Ausschlussgrund.
- Ein harter Ausschluss erfordert mindestens mittlere Konfidenz, keine offene Quellen- oder Identitätskollision und entweder bestätigte Nichtverfügbarkeit oder einen verifizierten Abgang aus dem Wettbewerb.
- Namens- oder Vereinsabweichungen bei derselben Kicker-ID sind ein Konflikt. Ausgewählte Spieler mit offenem Konflikt blockieren den finalen Lauf.
- Liefert ein Provider den Vornamen nur als Initiale, ist eine automatische Zuordnung ausschließlich bei passender Initiale, vollständigem identischem Nachnamen und passendem Verein zulässig. Mehrdeutige Treffer bleiben Konflikte.
- Für jeden ausgewählten Spieler muss bei mindestens einem Provider ein verifiziertes Paar aus Spieler- und aktuellem Team-ID vorliegen. Nur so lässt sich die Richtung eines Transfers sicher bewerten. Fehlt es, den Spieler am selben Tag manuell in Primärquellen prüfen und die zentrale Zuordnung ergänzen, bevor Chrome geändert wird.
- Ein fehlendes Provider-Paar darf einen Feldspieler nicht bereits aus dem zentralen Qualitäts- und Near-Miss-Pool entfernen. Bis zur nachgezogenen Zuordnung ist eine manuelle Freigabe zulässig, wenn Verfügbarkeit, Fitness, Rolle und Transferlage mit mindestens zwei aktuellen direkten Quellen geprüft, Risiken nur erhöht und die Prüfung spätestens nach sieben Tagen verworfen wird. Für Torwartblöcke gilt diese Ausnahme wegen der unvollständigen Konkurrenzhierarchie nicht.
- Direkt vor dem ersten Verkauf Snapshot erneut laden. Liegt die letzte Prüfung mehr als zwei Stunden zurück oder gab es neue Meldungen, finalen Lauf ohne `--new-variant` wiederholen; so bleibt die automatische persönliche Variante stabil. Bei einem ausdrücklich gesetzten Seed denselben Wert verwenden.
- Das Sprachmodell darf keine Rolle aus Preis, Bekanntheit oder Vorjahrespunkten erfinden. Ein maschinelles Rollenprofil wird nur akzeptiert, wenn jede Evidenz-URL tatsächlich in den Web-Search-Quellen vorkommt, höchstens 45 Tage alt ist und einem bekannten Spieler des aktuellen Marktes zugeordnet werden kann.
- Widersprüchliche Rollenmeldungen werden deterministisch auf `open_competition` mit niedriger Konfidenz begrenzt. Hohe Konfidenz verlangt mindestens eine starke Primärquelle. Der Qualitätsalgorithmus und der Torwart-Resolver bleiben deterministisch; das Modell entscheidet niemals allein über Kauf oder Verkauf.

## Zentraler GitHub-Aktualisierungslauf

Der Workflow `.github/workflows/update-news-feed.yml` läuft um 02:17, 08:17, 14:17 und 20:17 UTC sowie manuell. Der API-Sports-Schlüssel liegt ausschließlich als Repository-Secret `API_SPORTS_KEY` vor. Der OpenAI-Schlüssel liegt als Repository-Secret `OPENAI_APIKEY` vor und wird im Workflow nur für den Prozess als `OPENAI_API_KEY` bereitgestellt. `SPORTMONKS_API_TOKEN` ist optional: Fehlt er, veröffentlicht das Provider-Audit `not_configured`; fehlen bei vorhandenem Token noch verifizierte Zuordnungen, erscheint `configuration_required`. Beides blockiert den bewährten API-Sports-Lauf nicht. GitHub Pages veröffentlicht danach:

```text
https://geozocco.github.io/kicker-interactive-manager/v1/news/2-bundesliga.json
https://geozocco.github.io/kicker-interactive-manager/v1/news/3-liga.json
```

Die Konfigurationen in `config/news/` enthalten nur Wettbewerb, Saison und öffentliche Provider-IDs. Der Lauf ermittelt alle aktuellen Teams und Spieler automatisch, verlangt die erwartete Teamzahl und bricht bei unvollständigen Ligadaten ab. Über `--role-evidence-config` liest er zusätzlich die manuell belegten Rollenmeldungen aus `config/quality/` ein.

Die OpenAI-Rollenrecherche bezieht jeden aktuell verfügbaren Spieler der zentralen Kicker-Marktliste ein. Die bisherige feste Obergrenze entfällt. Offene Rollenfälle, Benchmarks, bestätigte Ankerkandidaten, Torwarthierarchien, hochpreisige Offensivspieler und qualifizierte U23-Potenzialspieler bestimmen weiterhin die Reihenfolge, nicht mehr die Teilnahme. Sie erfasst neben Startwahrscheinlichkeit und Standards auch Trainervertrauen, Kaderstatus, taktische Passung, Konkurrenz um den Platz, erwartetes Minutenband und Rollenstabilität. Diese Umfeldsignale bleiben von Verletzung, Transfer, Vorbereitung und historischer Form getrennt, um Doppelzählung zu vermeiden. Sie verwendet standardmäßig `gpt-5.6-luna` mit niedriger Reasoning-Stufe und Web Search. Ergebnisse besitzen getrennte Fristen: offene Torwartfragen werden nach drei Tagen, übrige Torwartrollen nach sieben Tagen und stabile Feldspielerrollen nach vierzehn Tagen erneut geprüft. Bis zum nächsten Prüfzeitpunkt entstehen keine neuen Modellaufrufe. Auch ein korrektes Ergebnis „kein belastbares aktuelles Rollensignal“ wird drei beziehungsweise sieben Tage separat gecacht, ohne daraus eine Spielerrolle zu erfinden. Fehlt ein Spieler in einer Modellausgabe oder scheitert seine Belegnormalisierung, wird er ausdrücklich als `research_inconclusive` gespeichert und bereits im nächsten Lauf erneut geprüft; dieser Status ist niemals ein sportlicher Malus. Ein noch gültiges altes Profil bleibt bei einem vorübergehenden API-Fehler als gekennzeichneter Fallback erhalten; ohne gültigen Beleg greift die bestehende deterministische Rollenheuristik. Das Snapshot-Audit `role_research` nennt Modell, vollständige Zielzahl, Positions- und Vereinsabdeckung, Cachetreffer, neue Profile, belegte Enthaltungen, unklare Ergebnisse, Requests und Fehler, aber niemals Schlüssel oder vollständige Modellprompts.

Die getrennte OpenAI-Teamrecherche arbeitet einmal je Verein und cached das Ergebnis vierzehn Tage. Sie erfasst den aktuellen Trainer, belegte jüngere Trainerhistorie, bevorzugte Systeme, Jugendeinsatz, Rotation, Systemstabilität sowie den aktuellen offensiven und defensiven Ausblick. Mindestens ein aktueller Beleg der letzten 30 Tage ist erforderlich; ältere Karrierebelege dürfen diesen nur ergänzen. Das Teamprofil verändert individuelle Leistung nie direkt, sondern begrenzt Teamkontext und Trainer-/Systemsignale.

Trainerentscheidungen, Aussagen zur sofortigen Hilfe oder Perspektivrolle, glaubhafte externe Torwart-Transfergefahr und aktuelle Standardverantwortungen bleiben so zentral wiederverwendbar, ohne Provider-Risikosignale mit redaktioneller Rolleninterpretation zu vermischen. Snapshots werden als Pages-Artefakt veröffentlicht und nicht in Git eingecheckt.

Für eine manuelle zentrale Ausführung gilt weiterhin:

Eine optionale Mapping-Datei kann einzelne Kicker-IDs ausdrücklich mit Provider-IDs verbinden:

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

Die Liga- und Team-IDs sind providerabhängig und müssen vor dem ersten Lauf gegen den aktuellen Wettbewerb geprüft werden. Bei `auto_discover_players: true` setzt das Skript `competition_team_ids_complete` nur nach erfolgreicher Prüfung der erwarteten Teamzahl. Ohne automatische Erkennung darf das Feld erst dann auf `true` gesetzt werden, wenn wirklich alle aktuellen Vereine enthalten sind. Nur dann darf ein Zielverein außerhalb dieser Menge als bestätigter Abgang aus dem Wettbewerb gewertet werden. Ein Wechsel innerhalb der Ligamenge erhöht dagegen lediglich Rollen- und Transferrisiko. Anschließend zentral ausführen:

```text
OPENAI_API_KEY=<secret> SPORTMONKS_API_TOKEN=<secret> API_SPORTS_KEY=<secret> <python-3-command> scripts/refresh_news_snapshot.py --mapping <mapping-json> --role-evidence-config <quality-config-json> --market <market-snapshot-json> --previous-quality <quality-snapshot-url-oder-json> --previous <news-snapshot-url-oder-json> --output <snapshot-directory>/2-bundesliga.json --provider api_sports --optional-provider sportsmonks
```

Der Lauf ist für mehrere Aktualisierungen pro Tag gedacht. Er verwendet begrenzte Wiederholungen mit Backoff, vollständige Pagination, API-Sports-Batches bis 20 Spieler, vereinsweise statt spielerweise Transferabfragen, bei optionalem SportsMonks-Betrieb nur Gerüchte der letzten höchstens 31 Tage, providerseitige Aktualitätsdaten und atomaren Dateiaustausch. Nach einem fehlgeschlagenen Refresh bleibt im selbst gehosteten Modus die vorige Datei erhalten, läuft aber regulär ab und wird danach vom Optimierer abgelehnt; GitHub Pages veröffentlicht bei einem fehlgeschlagenen Workflow gar kein neues Artefakt.

## Alternativen zur GitHub-Pages-Bereitstellung

Das Snapshot über einen internen HTTPS-Endpunkt ausliefern. Dafür kann `scripts/serve_news_feed.py` hinter einem TLS-Reverse-Proxy verwendet werden:

```text
KICKER_NEWS_FEED_TOKEN=<shared-random-token> <python-3-command> scripts/serve_news_feed.py --root <snapshot-directory> --host 127.0.0.1 --port 8787
```

Der Reverse-Proxy veröffentlicht zum Beispiel:

```text
https://intern.example.org/v1/news/2-bundesliga.json
```

Er muss HTTPS erzwingen und den Backend-Port nicht öffentlich freigeben. Der mitgelieferte Server prüft Bearer-Token, sichere Dateinamen, Snapshot-Gültigkeit und ETags. Alternativ ist jeder interne HTTPS-Speicher zulässig, der dieselbe JSON-Datei unverändert und zugriffsgeschützt ausliefert.

Für einen ausdrücklich gewünschten internen Spiegel können URL und optional Feed-Token als lokale Umgebungsvariablen gesetzt werden. Sie überschreiben den eingebauten Team-Feed. Niemals die Provider-Schlüssel verteilen:

```text
KICKER_NEWS_FEED_URL=https://intern.example.org/v1/news/2-bundesliga.json
KICKER_NEWS_FEED_TOKEN=<feed-token>
```

## Finaler Optimierungslauf

```text
<python-3-command> scripts/optimize_squad.py --annotations <annotations-json> --competition "2. Bundesliga" --season "2026/27" --require-market-snapshot --news-snapshot <https-url-oder-datei> --require-news-snapshot --require-news-coverage --profile reliable --variation medium --maintenance low --min-reliable-anchors 3 --budget <budget> --format json
```

`news_audit` im Ergebnis dokumentiert Snapshot-Prüfsumme, Providerstatus, Erzeugungs- und Ablaufzeit, angewandte Spieler, fehlende Zuordnungen, Konflikte und harte Ausschlüsse. Dieses Audit vor jeder Browseränderung lesen.

## Fallback ohne erreichbaren Feed

Ist der zentrale Feed vorübergehend nicht erreichbar, keinen alten Snapshot schönreden. Für einen finalen Lauf entweder:

- den zentralen Refresh reparieren und erneut laden oder
- jeden möglichen Zielspieler und entscheidenden Near-Miss am selben Tag manuell über offizielle Vereins-/Ligameldungen und eine zweite belastbare Quelle prüfen, vollständig annotieren und offen dokumentieren, dass der zentrale News-Gate nicht verfügbar war.

Bei einem offenen Konflikt über Verletzung, Spielberechtigung oder Transferstatus keine Browseränderung vornehmen. `--allow-news-conflicts` ist nur ein technischer, ausdrücklich zu begründender Override nach dokumentierter manueller Klärung.

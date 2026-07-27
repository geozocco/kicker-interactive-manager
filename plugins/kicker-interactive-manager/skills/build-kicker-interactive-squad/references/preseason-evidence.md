# Vorbereitungssignale

## Zweck

Vorbereitungseindrücke als zeitlich begrenztes Einsatz- und Rollensignal verwenden, besonders bei jungen, neuen, zurückkehrenden oder bislang kaum eingesetzten Spielern. Testspiele niemals als bestätigte Seniorensaison, Pflichtspielniveau oder verlässlichen Anker behandeln.

## Zentraler Bestand

Für 2. Bundesliga und 3. Liga veröffentlicht der zentrale Lauf:

```text
https://geozocco.github.io/kicker-interactive-manager/v1/preseason/2-bundesliga.json
https://geozocco.github.io/kicker-interactive-manager/v1/preseason/3-liga.json
```

Der Lauf kombiniert:

- erfasste Testspiele, Aufstellungen, Einsatzminuten und Scorer aus API-Sports,
- aktuelle offizielle Vereinsberichte und Traineräußerungen als strukturierte Ergänzung,
- Wiederholung über mehrere Spiele,
- Verwendung in erster, gemischter oder zweiter Formation,
- Teilnahme am Mannschaftstraining,
- grob normalisierte Gegnerstärke.

Nur verdichtete Beobachtungen, Quellenlinks und Scores veröffentlichen. Keine Provider-Schlüssel oder vollständigen Rohantworten speichern.

## Gewichtung

`preseason_summary` getrennt von Mehrjahresleistung auswerten:

- junger Spieler bis 21 ohne bestätigte Saison: höchstens 25 Prozent Gewicht auf die aktuelle Einsatzreife,
- Spieler mit dünner Seniorenhistorie: höchstens 18 Prozent,
- etablierter junger Spieler: höchstens 10 Prozent,
- etablierter älterer Spieler: höchstens 6 Prozent.

Konfidenz, Stichprobengröße und zeitlicher Verfall reduzieren diese Obergrenzen zusätzlich. Ein einzelner Einsatz oder Treffer darf keinen hohen Ausbruchstatus auslösen. Für `high_upside_pre_breakthrough` mindestens zwei Vorbereitungseinsätze, mittlere Konfidenz, ein positives Gesamtsignal und einen unabhängig starken Jugend-/Talentpfad verlangen.

Positive Vorbereitung darf `minutes`, `role`, `upside`, `value` und `unknown_role` begrenzt verändern. Sie darf niemals:

- `confirmed_performance` erhöhen,
- `proven_seasons` erzeugen,
- `reliable_anchor` erzeugen,
- ein offenes Stammplatzduell als sicher ausgeben.

Negative oder fehlende Vorbereitung bei einem jungen Spieler als Unsicherheit behandeln. Belegte Nichtteilnahme, Reha oder dauerhafte zweite Formation dürfen Einsatz- und Rollenwerte senken, benötigen aber aktuelle Quellen.

API-Sports-Testspiele über `/fixtures` liefern nur die Begegnungshülle. Spielerbeobachtungen ausschließlich aus `/fixtures/players` oder einem direkten offiziellen Vereinsbeleg ableiten. Findet der zentrale Lauf mehrere Testspiele, aber keinerlei Spielerstatistiken, darf er keinen scheinbar gesunden leeren Snapshot veröffentlichen.

Bei einem belegten Comeback gesundes, mehrjährig bestätigtes Leistungsniveau und aktuelle Einsatzreife strikt trennen: Ein verletzungsbedingt minutenarmes Jahr senkt nicht zusätzlich `confirmed_performance`. Individuelles beziehungsweise teilweises Training begrenzt stattdessen `fitness`, setzt einen aktuellen Boden für `injury` und hält die Rollenunsicherheit sichtbar. Erst wiederholtes Mannschaftstraining und Spieleinsätze lösen diese Begrenzung schrittweise.

## Verfall

Einzelbeobachtungen besitzen eine Halbwertszeit von 28 Tagen. Ab dem ersten Pflichtspieltag sinkt das gesamte Vorbereitungssignal innerhalb von 35 Tagen auf neutral. Pflichtspieldaten ersetzen es damit schrittweise.

Nach Ablauf der konfigurierten Vorbereitung keine alten Testspieltore als aktuelle Form darstellen. Quellen und historische Beobachtungen bleiben nachvollziehbar, ihr wirksamer Faktor fällt jedoch auf null.

## Manuelle Primärquellen

Offizielle Ergänzungen in `config/preseason/<liga>.json` nur mit direktem HTTPS-Link erfassen. Pro Beobachtung mindestens Datum, Gegner, Einsatzstatus, geschätzte Minuten, Formationsrolle, Konfidenz, Behauptung und Quelle angeben. Werte nicht aus einem Ergebnis allein erraten.

API- und offizielle Beobachtungen desselben Spiels anhand von Datum und Gegner zusammenführen. Die offizielle Quelle darf fehlende Formations- oder Rolleninformationen ergänzen, aber keine belegten API-Minuten verdoppeln.

## Ergebnisinterpretation

- `strong`: wiederholtes, belastbares positives Rollen- und Einsatzsignal
- `positive`: interessanter Hinweis mit weiterhin sichtbarer Unsicherheit
- `neutral`: keine klare Veränderung
- `negative`: belegtes schwaches Einsatz-/Rollensignal
- `insufficient`: keine verwertbare Stichprobe

Im Nutzerergebnis konkrete Beobachtungen nennen. „Gute Vorbereitung“ ohne Spiele, Rolle, Zeitraum und Quelle genügt nicht.

# Bestehenden Kader bewerten

## Ziel

Den aktuell sichtbaren kicker-Interactive-Kader vollständig read-only prüfen. Eine Bewertung darf den Kader weder verkaufen noch ergänzen. Änderungen erst nach einer neuen ausdrücklichen Aufforderung umsetzen.

## Eingabe aus Chrome

Wettbewerb, Saison, Budget, Positionsvorgaben und jeden sichtbaren Spieler erfassen. Für die eindeutige Zuordnung möglichst Kicker-ID verwenden; andernfalls vollständigen Namen, Verein, Position und Preis speichern:

```json
{
  "players": [
    {
      "name": "Beispielspieler",
      "club": "Beispielverein",
      "position": "MIDFIELDER",
      "cost": 700000
    }
  ]
}
```

Uneindeutige oder nicht zur offiziellen Kicker-CSV passende Einträge nicht erraten. Den sichtbaren Kader erneut lesen und korrigieren.

## Rechercheumfang

Für eine belastbare Bestätigung jeden gewählten Spieler am selben Tag vollständig nach `annotation-schema.md` annotieren. Dabei besonders prüfen:

- aktuelle Verletzung, Trainingsstatus und Belastbarkeit
- bestätigte oder konkret drohende Transfers
- Startelf-, Standard- und Schlüsselrolle
- Rotation, Konkurrenz und Spielberechtigung
- wiederholbare Leistung über mehrere Spielzeiten

Für konkrete Verbesserungsvorschläge zusätzlich mindestens zwei realistisch bezahlbare, aktuell recherchierte Alternativen je Feldposition aufnehmen. Ohne Alternativen bleibt die Sicherheitsprüfung gültig, aber die Aussage zur relativen Kaderqualität ist enger.

Für Bundesliga, 2. Bundesliga und 3. Liga das frische zentrale Snapshot verlangen. Fehlende Zuordnungen oder Konflikte bei einem gewählten Spieler blockieren die grüne Bestätigung, bis Primärquellen die Lage klären. Für eine Liga ohne eingerichteten Feed alle gewählten Spieler am selben Tag manuell prüfen und die Einschränkung nennen.

## Skriptlauf

```text
<python-3-command> scripts/evaluate_squad.py --roster <current-roster-json> --annotations <annotations-json-path> --competition "2. Bundesliga" --season "2026/27" --require-market-snapshot --require-news-snapshot --require-news-coverage --profile reliable --maintenance low --budget 10000000 --goalkeepers 3 --defenders 7 --midfielders 7 --forwards 5 --format json
```

Für die Bundesliga `--competition "Bundesliga" --budget 42500000` verwenden; alle übrigen Gates und Audits bleiben identisch.

Wettbewerb, Saison, Budget und Positionszahlen immer aus der sichtbaren Seite übernehmen.

## Auswertung

Die Ausgabe unterscheidet:

- `ready`: Daten vollständig; keine kritischen Datenlücken
- `attention`: belastbare Bewertung, aber mindestens ein hohes sportliches oder strukturelles Risiko
- `critical`: bestätigter vermeidbarer Fehler wie Nichtverfügbarkeit oder ungültiger Kader
- `blocked`: keine belastbare Gesamtnote wegen fehlender oder widersprüchlicher aktueller Daten

`avoidable_error_free: true` nur als grüne Bestätigung verwenden. Ein numerischer Wert allein ist keine Freigabe.

Die Bewertung umfasst:

- Kadergröße, Positionen, Budget und Torwartblock
- stärkste legale Startelf und Wertanteil des Kerns
- gemeinsame Startelf-/Bank-Bewertung mit vollständigem Startergewicht und positionsabhängiger erwarteter Reservenutzung
- `budget_allocation` nach Position einschließlich Beitrag je 0,1 Mio. und der fünf Plätze mit dem niedrigsten Grenznutzen
- mehrjährig bestätigte Anker in der Startelf
- teure Bank und ungenutztes Budget
- Vereinskonzentration
- aktuelle Verletzungs-, Transfer- und Rollenrisiken
- frische News-Abdeckung und Konflikte
- bis zu fünf bezahlbare Ein-zu-eins-Alternativen aus dem recherchierten Pool

Alternativen sind Prüfhinweise, keine automatische Transferanweisung. Vor einem später beauftragten Umbau erneut Snapshot und sichtbaren Chrome-Zustand prüfen.

## Nutzerantwort

Mit dem Urteil beginnen und danach knapp liefern:

1. Gesamtnote oder klaren Grund, warum sie noch nicht belastbar ist
2. grüne Stärken
3. kritische und hohe Warnungen zuerst, jeweils mit Spieler und aktueller Quelle
4. strukturelle Hinweise zu Startelf, Bank und Budget; theoretische Preisobergrenze, tatsächliche Kernquote und positionsbezogenen Grenznutzen klar trennen
5. bezahlbare Alternativen samt Kosten- und Bewertungsdifferenz
6. Snapshot-Zeitpunkt, Abdeckung und verbleibende Unsicherheit

Ausdrücklich bestätigen, dass Chrome nicht verändert wurde.

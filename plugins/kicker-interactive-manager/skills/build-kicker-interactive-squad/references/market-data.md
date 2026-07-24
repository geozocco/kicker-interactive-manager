# Zentraler Marktbestand

## Zweck und Grenze

Für 2. Bundesliga und 3. Liga 2026/27 einen gemeinsamen, nur lesbaren Marktbestand verwenden. Er enthält die öffentliche Kicker-Spielerliste mit IDs, Vereinen, Positionen, Preisen und den in der Kicker-CSV enthaltenen Leistungswerten. Persönliche Präferenzen, lokale Variantenkennungen, Kollegenkader und Kaderbelegungen niemals zentral speichern.

Der gemeinsame Marktbestand beschleunigt und vereinheitlicht die Recherche. Er garantiert keine kollisionsfreien Kader bei unabhängig gestarteten Kollegen. Überschneidungsfreie Ankerkerne nur über ein gemeinsam erzeugtes Gruppenportfolio koordinieren.

## Öffentliche Endpunkte

```text
https://geozocco.github.io/kicker-interactive-manager/v1/market/2-bundesliga.json
https://geozocco.github.io/kicker-interactive-manager/v1/market/3-liga.json
```

Der Workflow `.github/workflows/update-news-feed.yml` aktualisiert Markt- und News-Snapshots viermal täglich. Die Marktkonfigurationen unter `config/market/` verweisen auf die offiziellen Kicker-CSV-Quellen und verlangen die vollständige Anzahl aktueller Vereine sowie einen plausiblen Spielerkorridor.

## Sicherheitsvertrag

Das Snapshot nur verwenden, wenn:

- HTTPS, Prüfsumme und Schema gültig sind,
- Erzeugungs- und Ablaufzeit plausibel sind,
- Wettbewerb und Saison zur sichtbaren Kicker-Seite passen,
- jede Spieler-ID eindeutig ist,
- Position und positiver Marktwert gültig sind,
- die Anzahl unterschiedlicher Vereine exakt zur Konfiguration passt.

Bei einem Verstoß nicht mit einem teilweise geladenen Pool weiterrechnen.

## Verwendung

Für unterstützte Ligen lädt der Optimierer den Marktfeed anhand von Wettbewerb und Saison automatisch, wenn `--players` fehlt. Bei einem finalen Lauf zusätzlich `--require-market-snapshot` setzen:

```text
<python-3-command> scripts/optimize_squad.py --competition "2. Bundesliga" --season "2026/27" --require-market-snapshot ...
```

`market_audit` im Ergebnis muss `status: fresh`, die richtige Liga und Saison, die erwartete Vereinszahl sowie eine plausible Spielerzahl ausweisen.

Das Snapshot kann zentrale Annotationen enthalten. Diese müssen sich auf aktuelle Kicker-IDs beziehen. Auf dem jeweiligen Rechner recherchierte Annotationen dürfen zentrale Annotationen gezielt überschreiben; Kicker-ID, Verein, Position und Preis stammen weiterhin aus dem validierten Marktbestand.

## Manueller Fallback

Ist der zentrale Marktfeed nicht erreichbar oder abgelaufen:

1. Den zentralen Workflow einmal reparieren beziehungsweise neu ausführen.
2. Nur wenn das nicht rechtzeitig möglich ist, die aktuelle offizielle Kicker-CSV lokal speichern und mit `--players` verwenden.
3. Wettbewerb, Saison, Vereinszahl, Zeitpunkt und Quell-URL offen dokumentieren.
4. Den lokalen Lauf nicht als zentral geprüft ausweisen.

Die offizielle CSV nicht in einem sichtbaren Chrome-Tab öffnen, wenn sie im Hintergrund sicher geladen oder als Snapshot verwendet werden kann.

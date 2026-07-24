# Zentraler Marktbestand

## Zweck und Grenze

Für 2. Bundesliga und 3. Liga 2026/27 einen gemeinsamen, nur lesbaren Marktbestand und einen getrennten Qualitätsbestand verwenden. Der Markt enthält ausschließlich öffentliche Kicker-Fakten. Der Qualitätsbestand enthält breit recherchierte, reproduzierbare Mehrjahres-, Rollen-, Fitness- und Transfereinschätzungen. Persönliche Präferenzen, lokale Variantenkennungen, Kollegenkader und Kaderbelegungen niemals zentral speichern.

Der gemeinsame Marktbestand beschleunigt und vereinheitlicht die Recherche. Er garantiert keine kollisionsfreien Kader bei unabhängig gestarteten Kollegen. Überschneidungsfreie Ankerkerne nur über ein gemeinsam erzeugtes Gruppenportfolio koordinieren.

## Öffentliche Endpunkte

```text
https://geozocco.github.io/kicker-interactive-manager/v1/market/2-bundesliga.json
https://geozocco.github.io/kicker-interactive-manager/v1/market/3-liga.json
https://geozocco.github.io/kicker-interactive-manager/v1/quality/2-bundesliga.json
https://geozocco.github.io/kicker-interactive-manager/v1/quality/3-liga.json
```

Der Workflow `.github/workflows/update-news-feed.yml` aktualisiert Markt-, News- und Qualitäts-Snapshots viermal täglich. Die Qualitätskonfigurationen unter `config/quality/` verlangen je Liga mindestens 60 vollständig bewertete Kandidaten, 20 verlässliche Anker, 15 offensive Anker und sechs vollständige Torwartblöcke. Spieler werden algorithmisch aus dem gesamten Markt ausgewählt; namentliche Beispiele oder frühere Nutzerprompts erhalten keinen Bonus.

## Sicherheitsvertrag

Das Snapshot nur verwenden, wenn:

- HTTPS, Prüfsumme und Schema gültig sind,
- Erzeugungs- und Ablaufzeit plausibel sind,
- Wettbewerb und Saison zur sichtbaren Kicker-Seite passen,
- jede Spieler-ID eindeutig ist,
- Position und positiver Marktwert gültig sind,
- die Anzahl unterschiedlicher Vereine exakt zur Konfiguration passt.
- der Qualitätsbestand exakt zur Prüfsumme des aktuellen Markt- und News-Bestands gehört,
- alle acht Qualitätskomponenten und fünf Risiken vollständig sind,
- die ligaweiten Mindestzahlen für Kandidaten und Anker erreicht werden.

Bei einem Verstoß nicht mit einem teilweise geladenen Pool weiterrechnen.

## Verwendung

Für unterstützte Ligen lädt der Optimierer den Marktfeed anhand von Wettbewerb und Saison automatisch, wenn `--players` fehlt. Bei einem finalen Lauf zusätzlich `--require-market-snapshot` setzen:

```text
<python-3-command> scripts/optimize_squad.py --competition "2. Bundesliga" --season "2026/27" --require-market-snapshot --require-quality-snapshot ...
```

`market_audit` muss frisch sein. `quality_audit` muss mindestens 60 Kandidaten, 20 Anker, 15 offensive Anker und sechs Torwartblöcke ausweisen und dieselbe Markt-Prüfsumme tragen.

Der Qualitätsbestand liefert die zentralen Annotationen. Auf dem jeweiligen Rechner recherchierte Annotationen dürfen sie gezielt überschreiben; Kicker-ID, Verein, Position und Preis stammen weiterhin aus dem validierten Marktbestand.

## Manueller Fallback

Ist der zentrale Marktfeed nicht erreichbar oder abgelaufen:

1. Den zentralen Workflow einmal reparieren beziehungsweise neu ausführen.
2. Nur wenn das nicht rechtzeitig möglich ist, die aktuelle offizielle Kicker-CSV lokal speichern und mit `--players` verwenden.
3. Wettbewerb, Saison, Vereinszahl, Zeitpunkt und Quell-URL offen dokumentieren.
4. Den lokalen Lauf nicht als zentral geprüft ausweisen und fehlende Qualitätsmerkmale manuell vollständig belegen.

Die offizielle CSV nicht in einem sichtbaren Chrome-Tab öffnen, wenn sie im Hintergrund sicher geladen oder als Snapshot verwendet werden kann.

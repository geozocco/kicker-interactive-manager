# Kandidaten-Annotationen

Die Annotationen ergänzen die Kicker-CSV um aktuelle Informationen, die nicht zuverlässig in Vorjahrespunkten oder Preisen stecken.

## Format

```json
{
  "players": {
    "pl-k00123456": {
      "components": {
        "confirmed_performance": 72,
        "minutes": 85,
        "role": 78,
        "stability": 82,
        "context": 70,
        "fitness": 75,
        "upside": 64,
        "value": 73
      },
      "risks": {
        "transfer": 5,
        "injury": 20,
        "rotation": 15,
        "outlier": 25,
        "unknown_role": 10
      },
      "note": "Voraussichtlicher Stammspieler; Standards möglich.",
      "exclude": false
    }
  }
}
```

Spieler-ID bevorzugen. Der vollständige Anzeigename ist als Fallback zulässig. Für jeden Kandidaten eines finalen Laufs müssen alle acht Komponenten und alle fünf Risiken als endliche Zahlen zwischen 0 und 100 vorliegen.

Teilannotationen dürfen als vorläufige Arbeitsnotiz in einem Recherche- oder Shortlist-Lauf verwendet werden. Fehlende Felder leitet das Skript dort vorsichtig aus CSV-Punkten, Note und Preis ab; der Spieler gilt dadurch ausdrücklich **nicht** als final geprüft und wird im normalen finalen Lauf ausgeschlossen. `--allow-unannotated` dient nur technischen Smoke-Tests und niemals einer Kaderempfehlung.

## Bewertungsregeln

- Nur Werte zwischen 0 und 100 verwenden.
- `confirmed_performance` nicht mit Vorjahrespunkten gleichsetzen. Andere Ligen, mehrere Saisons und individuelle Rolle einbeziehen.
- Bei Neuzugängen `minutes`, `role`, `stability` und `unknown_role` neu bewerten.
- Herausragende Jugendleistungen vor allem in `upside` erfassen; den Sprung in den Profibereich über `minutes` und `unknown_role` begrenzen.
- Frühere Verletzungen getrennt bewerten: aktuelle Fitness in `fitness`, Rückfallwahrscheinlichkeit in `injury`.
- Trainer- und Teamwechsel in `context` abbilden.
- Offene, belastbare Quelle im Feld `note` kurz zusammenfassen. Quellen im Arbeitsbericht verlinken; keine langen Zitate speichern.
- Spieler mit bestätigtem Abgang, Langzeitverletzung oder fehlender Spielberechtigung mit `exclude: true` ausschließen.

## Mindestabdeckung

Vor einer finalen Optimierung mindestens folgende aktuell recherchierte, nicht ausgeschlossene Kandidaten annotieren:

- Torhüter: doppelte Zahl der tatsächlichen Torwartplätze; im Standardmodus aus mindestens zwei vollständigen realistischen Torwartblöcken
- Verteidiger: tatsächliche Sollzahl plus 3
- Mittelfeldspieler: tatsächliche Sollzahl plus 3
- Stürmer: tatsächliche Sollzahl plus 3

Bei den üblichen Positionsvorgaben 3/7/7/5 entspricht das 6/10/10/8. Wird auf ausdrücklichen Wunsch `--mixed-goalkeepers` verwendet, entfällt nur die Blockanforderung; die Mindestzahl recherchierter Torhüter bleibt bestehen.

Die automatische Shortlist ist nur ein Ausgangspunkt. Zusätzlich prominente Neuzugänge, höherklassig erprobte Rebound-Kandidaten und herausragende Nachwuchsspieler ergänzen. Ohne Mindestabdeckung bricht das Skript ab; `--allow-unannotated` ist ausschließlich für technische Tests vorgesehen.

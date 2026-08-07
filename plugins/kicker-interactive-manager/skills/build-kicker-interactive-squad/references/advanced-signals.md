# Erweiterte Kontextsignale

Diese Signale ergänzen die dauerhafte Spielerqualität. Fehlende Stichproben neutral behandeln und niemals aus einem leeren Datenfeld einen Bonus oder Malus ableiten.

## Saisonale Signale

- `positional_flexibility`: Tatsächlich in API-Sports-Spielstatistiken oder Vorbereitungseinsätzen beobachtete Positionsgruppen erfassen. Reine Transfermarkt-Positionslisten nicht als Einsatznachweis behandeln.
- `team_projection`: Offensivstärke, Defensivstärke, Chancenerzeugung und Clean-Sheet-Ausblick aus den besten einsatznahen Spielern eines Vereins ableiten und mit dem quellengebundenen Teamprofil begrenzt abgleichen. Höchstens vier Kontextpunkte auf den Spieler anwenden.
- `competition_graph`: Spieler nur mit direkten Konkurrenten derselben Kicker-Positionsgruppe und desselben Vereins vergleichen. Startwahrscheinlichkeit vor allgemeinem Spielerscore verwenden. Konkurrenz erhöht höchstens das Rotationsrisiko; sie löscht keine historische Leistung.
- `coach_usage`: Aktuelle Trainerhistorie zentral je Verein recherchieren. Jugendeinsatz, Rotation, bevorzugte Systeme, Systemstabilität sowie aktuellen offensiven und defensiven Ausblick getrennt erfassen. Belegter Jugendeinsatz darf den Upside-Wert junger Spieler höchstens um zwei Punkte verändern, Systemstabilität höchstens um einen Punkt; hohe Rotation setzt einen begrenzten Risikoboden. Ohne aktuelle Quelle `unknown` verwenden.
- `discipline`: Gelbe und rote Karten der jüngsten drei Spielzeiten mit abnehmendem Gewicht pro 90 Minuten bewerten. Aktuelle Kartenstände und die Nähe zur nächsten Gelbsperre separat markieren. Das Signal senkt begrenzt die Stabilität; eine einzelne Karte oder kleine Stichprobe bleibt neutral.
- `usage_trajectory`: Chronologische Vorbereitungseinsätze und verfügbare aktuelle Pflichtspiele in frühe und jüngste Einsatzanteile teilen. Mindestens zwei Beobachtungen für `rising` oder `falling` verlangen. Zusätzlich direkte Konkurrenzentscheidungen der jüngsten bis zu zwölf Pflichtspiele erfassen. Belegte Entscheidungsspiele und wiederholte jüngste Bevorzugung eines direkten Konkurrenten überstimmen den bloßen Saison-Minutenanteil; sie dürfen historische Qualität nicht löschen, wohl aber die aktuelle Startwahrscheinlichkeit deckeln.

## Spieltagskontext

`v1/matchday/<liga>.json` bleibt ein kurzlebiger, separater Feed. Der Feed enthält den nächsten Gegner, Heim/Auswärts, Gegnerstärken und Schwierigkeit. `scripts/analyze_matchday.py` darf daraus je Spieler höchstens ±6 Punkte für die konkrete Aufstellungsentscheidung ableiten.

Spieltagsanpassungen niemals in Marktwert, Mehrjahresleistung, Ankerstatus oder den saisonalen Kadergrundscore zurückschreiben. Ist der Provider nicht verfügbar, `status: unavailable` ausgeben und mit null Spieltagsanpassung arbeiten.

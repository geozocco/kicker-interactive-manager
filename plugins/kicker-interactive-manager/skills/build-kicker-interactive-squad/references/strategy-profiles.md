# Strategieprofile und kontrollierte Variabilität

## Inhaltsübersicht

1. Bewertungskomponenten
2. Profilgewichte
3. Betreuungsaufwand
4. Variabilität
5. Portfolioregeln

## Bewertungskomponenten

Alle Komponenten auf 0 bis 100 normieren.

- `confirmed_performance`: Mehrjährige oder ligaübergreifend bestätigte individuelle Leistung. Eine einzelne Ausreißersaison nur reduziert anrechnen.
- `minutes`: Erwartete Einsatzzeit und Startelfwahrscheinlichkeit.
- `role`: Standards, Kapitänsamt, kreative beziehungsweise offensive Verantwortung und taktische Passung.
- `stability`: Vertragssituation, Wechselwahrscheinlichkeit und Kontinuität im Team.
- `context`: Trainerqualität, Spielidee, Teamumbau und wahrscheinliche Mannschaftsstärke.
- `fitness`: Aktuelle Belastbarkeit, Verletzungshistorie und Vorbereitung.
- `upside`: Jugendleistung, Ausbildung, Athletik, höherklassige Qualität, Rebound- oder Rollengewinnpotenzial.
- `value`: Erwartbare Leistung relativ zum kicker-Preis.

Risiken ebenfalls auf 0 bis 100 schätzen:

- `transfer`
- `injury`
- `rotation`
- `outlier`
- `unknown_role`

## Profilgewichte

| Komponente | Verlässlich | Ausgewogen | Ausbruch |
|---|---:|---:|---:|
| confirmed_performance | 30 | 18 | 8 |
| minutes | 25 | 23 | 18 |
| role | 14 | 13 | 10 |
| stability | 12 | 10 | 6 |
| context | 6 | 8 | 8 |
| fitness | 7 | 8 | 7 |
| upside | 2 | 10 | 25 |
| value | 4 | 10 | 18 |

Risikopenalties:

| Risiko | Verlässlich | Ausgewogen | Ausbruch |
|---|---:|---:|---:|
| transfer | 0,15 | 0,10 | 0,06 |
| injury | 0,12 | 0,10 | 0,08 |
| rotation | 0,16 | 0,12 | 0,08 |
| outlier | 0,12 | 0,08 | 0,04 |
| unknown_role | 0,14 | 0,10 | 0,07 |

Den Risikowert mit dem Faktor multiplizieren und vom Komponentenscore abziehen.

### Wiederholbarkeit

- Drei oder mehr stabile Spielzeiten: volle historische Evidenz zulassen.
- Zwei stabile Spielzeiten: leichte Regression einkalkulieren.
- Eine Ausreißersaison: historischen Wert je nach Rolle und zugrunde liegender Qualität deutlich schrumpfen.
- Wiederholbare Standards, Kapitänsrolle oder eine über Jahre identische Schlüsselrolle dürfen die Regression teilweise ausgleichen.
- Nach einem Wechsel weder die alte Rolle fortschreiben noch pauschal alles verwerfen. Neue Konkurrenz, Traineridee und Preis entscheiden.

## Betreuungsaufwand

### Gering

- Gewichte für `minutes`, `role` und `stability` erhöhen.
- `upside` und `value` leicht reduzieren.
- Mindestens 16 bis 18 Feldspieler mit plausibler regelmäßiger Einsatzchance anstreben.
- Verletzte, stark wechselgefährdete und reine Entwicklungsprojekte höchstens als einzelne Wetten einsetzen.

### Normal

- Profilgewichte unverändert verwenden.
- Vier bis sechs bewusst riskantere Plätze sind vertretbar.

### Aktiv

- `upside` und `value` leicht erhöhen.
- Frühere Wetten und offene Konkurrenzkämpfe zulassen.
- Nur verwenden, wenn der Nutzer während der Saison aktiv nachsteuern will.

## Variabilität

Variabilität darf keine blinde Zufallsauswahl sein. Zuerst den besten Kader nach Basisscore bestimmen, anschließend alternative Kader mit einem Seed erzeugen.

| Stufe | Zielabstand zum Optimum | Zielunterschied |
|---|---:|---:|
| niedrig | höchstens 2 % | mindestens 2 Spieler |
| mittel | höchstens 5 % | mindestens 4 Spieler |
| hoch | höchstens 8 % | mindestens 6 Spieler |

- Beim Profil `verlässlich` die Qualitätsgrenze mit Faktor 0,75 enger setzen.
- Beim Profil `ausbruch` die Qualitätsgrenze mit Faktor 1,20 erweitern.
- Einen zufälligen Seed lokal erzeugen, wenn der Nutzer keinen nennt. Keine personenbezogenen Daten als Seed verwenden.
- Den Seed im Ergebnis ausgeben, damit ein Kader reproduzierbar bleibt.
- Bei bekannten Kollegenkadern Überschneidungen über `--avoid-roster` bestrafen. Niemals einen klar schlechteren Spieler allein zur Abgrenzung wählen.
- Innerhalb einer Gruppe darf ein gemeinsamer Ankerkern bestehen. Unterschiedliche Seeds sollen vor allem mittlere Preisklassen, Bankplätze und ähnlich bewertete Alternativen variieren.

## Portfolioregeln

- Positions- und Budgetvorgaben immer aus der aktuellen Kicker-Seite übernehmen.
- Torwartblock standardmäßig aus einem Verein bilden.
- Standardobergrenze für Feldspieler desselben Vereins:
  - verlässlich: 4
  - ausgewogen: 4
  - ausbruch: 3
- Einen höheren Wert nur bei außergewöhnlich guter Rolle und vertretbarem Teamrisiko zulassen.
- Bei geringem Betreuungsaufwand mindestens zwei robuste Optionen je Feldposition außerhalb der wahrscheinlichen Startelf behalten.
- Maximal ein bis drei extreme Longshots einsetzen, abhängig vom Profil.

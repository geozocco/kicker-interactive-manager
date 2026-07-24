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
| confirmed_performance | 38 | 18 | 8 |
| minutes | 22 | 23 | 18 |
| role | 13 | 13 | 10 |
| stability | 11 | 10 | 6 |
| context | 6 | 8 | 8 |
| fitness | 6 | 8 | 7 |
| upside | 2 | 10 | 25 |
| value | 2 | 10 | 18 |

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
- Beim Profil `verlässlich` die Modellutility innerhalb jeder Position zugunsten der bestbewerteten Kandidaten krümmen: Der Spitzenkandidat behält sein volles Gewicht, während Ergänzungen bis auf 10 Prozent Bankgewicht sinken. Mehrjährig bestätigte Anker behalten dabei mindestens 95 Prozent in Mittelfeld und Sturm beziehungsweise 85 Prozent in der Abwehr. So finanziert der Solver einen starken Aufstellungskern statt 22 annähernd gleichwertiger Spieler.
- Elf bis 14 hochwertige Kernspieler anstreben. Die übrigen Plätze günstig, aber mit plausibler Einsatzchance besetzen; eine gleichwertige Premiumbank ist nicht erforderlich.
- Mindestens 70 Prozent des gesamten Kaderwerts müssen in der stärksten legalen Startelf liegen.
- Verletzte, stark wechselgefährdete und reine Entwicklungsprojekte höchstens als einzelne Wetten einsetzen.

### Normal

- Profilgewichte unverändert verwenden.
- Vier bis sechs bewusst riskantere Plätze sind vertretbar.

### Aktiv

- `upside` und `value` leicht erhöhen.
- Frühere Wetten und offene Konkurrenzkämpfe zulassen.
- Nur verwenden, wenn der Nutzer während der Saison aktiv nachsteuern will.

## Variabilität

Variabilität darf keine blinde Zufallsauswahl sein. Zuerst das beste Ergebnis innerhalb des vollständig annotierten Kandidatenpools bestimmen, anschließend alternative Kader mit einem Seed erzeugen.

| Stufe | Zielabstand zum besten Pool-Ergebnis | Zielunterschied |
|---|---:|---:|
| niedrig | höchstens 2 % | genau 2 Spieler, sofern im Korridor machbar |
| mittel | höchstens 5 % | genau 4 Spieler, sofern im Korridor machbar |
| hoch | höchstens 8 % | genau 6 Spieler, sofern im Korridor machbar |

- Beim Profil `verlässlich` die Qualitätsgrenze mit Faktor 0,75 enger setzen.
- Beim Profil `ausbruch` die Qualitätsgrenze mit Faktor 1,20 erweitern.
- Ohne Nutzereingabe die automatische private Installationsvariante des Optimierers verwenden. Keine Kadernummer erfragen und keine personenbezogenen Daten ableiten.
- Bei „neue Variante“ genau einmal `--new-variant` verwenden. Der lokale Variantenstand hält das Ergebnis anschließend reproduzierbar.
- Im Nutzerergebnis „automatische persönliche Variante“ nennen; die private Installationskennung niemals lesen oder ausgeben. Den numerischen Seed nur bei ausdrücklich technischer Diagnose oder vom Nutzer gewünschter exakter Reproduktion nennen.
- Bei bekannten Kollegenkadern Überschneidungen über `--avoid-roster` nach Auswahlhäufigkeit bestrafen. Niemals einen klar schlechteren Spieler allein zur Abgrenzung wählen.
- Nur für ein ausdrücklich zentral koordiniertes Portfolio `--portfolio-size`, `--max-anchor-exposure 1` und eindeutige `--portfolio-index`-Werte mit demselben Gruppenseed verwenden. Das ist eine fortgeschrittene Ausnahme, nicht der normale Kollegenablauf.
- Portfolio-Diversität umfasst auch Anker und Premiumspieler. Standardmäßig darf ein verlässlicher Anker in einem koordinierten Portfolio nur einmal vorkommen. Reicht der Pool dafür nicht, muss die Recherche ligaweit verbreitert werden oder der Lauf verständlich abbrechen. Eine frühere Erwähnung durch den Nutzer begründet weder Ankerstatus noch Mehrfachexposition.
- `benchmark: true` besitzt keinerlei Scorebonus. Es erzwingt nur, dass ein Kandidat recherchiert, verglichen und bei Nichtauswahl erklärt wird.
- Innerhalb einer koordinierten Gruppe gibt es standardmäßig keinen gemeinsamen Ankerkern. Eine höhere Ankerexposition ist nur eine ausdrücklich vom Nutzer genehmigte Lockerung, nachdem der konkrete Qualitätskonflikt erklärt wurde.
- Technische Läufe mit `--allow-unannotated` begrenzen bei sehr großen Rohpools nur die Variationssuche auf das globale Optimum, Anker/Benchmarks sowie starke und günstige Positionsalternativen. Vollständig recherchierte Endläufe bleiben exakt und berechnen weiterhin die Gegenfaktual-Begründungen.

## Portfolioregeln

- Der zentrale Kandidatenpool ist eine gemeinsame Datengrundlage, keine gemeinsame Namensvorgabe. Er soll alle aktuell plausiblen Anker der Liga enthalten und darf nicht aus zuvor im Gespräch genannten Beispielen abgeleitet werden.
- Für `N` Portfolioslots und `A` Pflichtanker pro Kader sind bei maximaler Ankerexposition eins mindestens `N × A` auswählbare Anker erforderlich. Da ein Kader mehr als die Mindestzahl auswählen kann und Budget sowie Positionen die Kombinierbarkeit einschränken, zusätzliche Reserve recherchieren.
- `anchor_diversity_target_met` muss wahr und `max_reliable_anchor_exposure` höchstens eins sein, bevor ein Fünfer-Portfolio als erfolgreich präsentiert wird.

- Positions- und Budgetvorgaben immer aus der aktuellen Kicker-Seite übernehmen.
- Torwartblock standardmäßig aus einem Verein bilden.
- Standardobergrenze für Feldspieler desselben Vereins:
  - verlässlich: 4
  - ausgewogen: 4
  - ausbruch: 3
- Einen höheren Wert nur bei außergewöhnlich guter Rolle und vertretbarem Teamrisiko zulassen.
- Bei geringem Betreuungsaufwand je Feldposition günstige, einsatzfähige Absicherung vorsehen, ohne den Premiumkern doppelt zu bezahlen.
- Beim Profil `verlässlich` mindestens vier aktuell belastbare Feldspieler als `reliable_anchor` verlangen, davon mindestens drei in Mittelfeld oder Sturm. Jeder Anker benötigt mindestens zwei belegte Spielzeiten auf vergleichbarem oder höherem Niveau. Verletzungs-, Transfer- und Rollenrisiken können einen bekannten Spieler vom Ankerstatus ausschließen.
- Maximal ein bis drei extreme Longshots einsetzen, abhängig vom Profil.

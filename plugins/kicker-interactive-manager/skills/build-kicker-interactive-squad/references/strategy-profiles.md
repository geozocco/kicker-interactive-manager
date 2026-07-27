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
- Historische Einsätze, Minuten und Scorer mit dem damaligen Wettbewerbsfaktor normalisieren. Bundesliga-Leistung wiegt höher als 2.-Bundesliga-Leistung, diese wiederum höher als 3.-Liga- oder Regionalliga-Leistung.
- Innerhalb dieser Mehrjahresbasis die Form zeitlich abklingen lassen: jüngste Saison 1,0, danach 0,62 je Saison; bei U21-Spielern 0,50, damit reale Entwicklungssprünge schneller sichtbar werden. Stichprobenkonfidenz und Ligastärke bleiben vorgeschaltet.
- Form und nachgewiesene Klasse getrennt halten. Ein aktuelles Formtief senkt die Prognose begrenzt, löscht aber nicht mehrere bestätigte Spielzeiten. Umgekehrt macht eine kurze Hochphase aus einem unbestätigten Spieler keinen Anker.
- Einsatzminuten-Einbrüche und aktuelle Verletzungsmeldungen gemeinsam als Rückkehrsignal bewerten. Ohne Verletzungsbeleg die Ursache nicht erfinden; bei belegter Verletzung aktuelle Fitness und Rollenunsicherheit stärker begrenzen.
- Nach einem Vereinswechsel die Formübertragbarkeit auf Rolle und Kontext reduzieren und `unknown_role` erhöhen. Portable individuelle Qualität bleibt erhalten. Systempassung erst dann positiv oder negativ festschreiben, wenn Trainer-, Positions- oder Formationsbelege vorliegen.
- Die österreichische Bundesliga und die Schweizer Super League als ungefähr deutsches Drittliganiveau (`0,64`) behandeln. Sie können eine Drittligasaison bestätigen, aber allein keine Zweitligasaison.
- Eine Spielzeit zählt für `proven_seasons` nur, wenn ausreichende Minuten auf einem zur Zielliga vergleichbaren oder höheren Niveau belegt sind. Eine starke 3.-Liga-Saison ist daher ein wertvolles Potenzial- und Value-Signal für die 2. Bundesliga, aber noch keine voll bestätigte Zweitliga-Spielzeit.
- Nachwuchsligen, Jugendpokale und Jugendnationalmannschaften getrennt gewichten. Einsätze in mehreren U15- bis U21-Nationalmannschaften, Minuten in starken Nachwuchswettbewerben und besonders frühe Ligaminuten im Herrenbereich bilden einen eigenen altersbereinigten `talent_score`. Regelmäßige Herrenminuten mit 18 oder jünger sind ein sehr starkes Signal; 19 und 20 bilden das normale Durchbruchsfenster, 16 oder 17 bleiben seltene Ausnahmefälle. Das gilt positionsneutral und verlangt von Torhütern keine Tore oder Vorlagen.
- Ein für einen 21-jährigen oder jüngeren Spieler ungewöhnlich hoher Kicker-Preis darf als begrenztes redaktionelles Erwartungssignal wirken, aber nur wenn der unabhängig berechnete Talentpfad bereits stark ist. Der Preis allein erzeugt weder Talentstatus noch einen Scorebonus.
- Reine Jugend- und Nationalmannschaftssignale dürfen `upside` und die Shortlist-Chance erhöhen, aber nie `confirmed_performance`, `proven_seasons` oder `reliable_anchor`. Tatsächlich absolvierte frühe Herren-Ligaminuten dürfen zusätzlich als stark rabattierte, ligakontextualisierte Teilbestätigung in `confirmed_performance` einfließen und eine vorsichtige Einsatz- und Rollenprognose stützen; sie erzeugen weiterhin weder eine bestätigte Zielniveau-Saison noch Ankerstatus.
- Pokal- und Freundschaftsspiele nicht als Ersatz für eine bestätigte Senior-Ligasaison verwenden. Aktuelle Vorbereitung getrennt als verfallendes Einsatz- und Rollensignal bewerten: höchstens 25 Prozent bei U21-Spielern ohne bestätigte Saison, 18 Prozent bei sonst dünner Historie, 10 Prozent bei jungen etablierten und 6 Prozent bei älteren etablierten Spielern. Konfidenz und Stichprobe reduzieren diese Maxima weiter.
- Einzelne Testspieltore nie als Durchbruchsnachweis behandeln. Mindestens zwei Einsätze, wiederholte Rollenhinweise und einen unabhängig starken Nachwuchspfad für `high_upside_pre_breakthrough` verlangen. Das Vorbereitungssignal ab Saisonstart innerhalb von fünf Wochen durch Pflichtspieldaten ersetzen.

## Betreuungsaufwand

### Gering

- Gewichte für `minutes`, `role` und `stability` erhöhen.
- `upside` und `value` leicht reduzieren.
- In allen Profilen die Modellutility innerhalb jeder Position zugunsten der bestbewerteten Kandidaten krümmen. `Verlässlich` konzentriert am stärksten, `ausgewogen` und `ausbruch` behalten mehr Tiefe und schützen zugleich außergewöhnliche Talente mit belegter Einsatz- und Rollenreife. So finanziert der Solver einen starken Aufstellungskern statt 22 annähernd gleichwertiger Spieler.
- Elf bis 14 hochwertige Kernspieler anstreben. Die übrigen Plätze günstig, aber mit plausibler Einsatzchance besetzen; eine gleichwertige Premiumbank ist nicht erforderlich.
- Mindestens 80 Prozent des gesamten Kaderwerts müssen unabhängig vom Strategieprofil in der stärksten legalen Startelf liegen.
- Die stärkste wartungsarme Startelf enthält mindestens zwei Stürmer und höchstens vier Verteidiger. Dadurch bleiben mindestens zwei belastbare offensive Wege erhalten und ein fünfter teurer Abwehrspieler wird nicht als vermeintliche Kerninvestition vor einer besseren Mittelfeld- oder Sturmoption geschützt.
- Im Profil `verlässlich` mindestens einen offensiven Premiumanker in dieser Startelf verlangen. Ihn positionsneutral innerhalb von Mittelfeld und Sturm aus mehrjähriger bestätigter Leistung, wiederholbarer Schlüssel- oder Standardrolle, Stabilität und aktueller Einsatzsicherheit ableiten. Weder `benchmark`, Bekanntheit noch eine frühere Nennung durch den Nutzer dürfen diesen Status erzeugen.
- Beim Torwartblock muss die vereinsintern ermittelte Nummer eins enthalten sein. Die Prognose verbindet `minutes`, `role`, mehrjährige Bestätigung, den Abstand zur Konkurrenz, den relativen Kicker-Preis im Vereinsblock und die aktuelle Kader-/Transferlage. Drei billigere Vereinskeeper ohne den wahrscheinlich Spielenden sind kein gültiger Block.
- Für `gering` sind mindestens 70 Prozent Saison-Stammplatzwahrscheinlichkeit, höchstens 40 Prozent Risiko eines externen Neuzugangs als Nummer eins und mindestens mittlere Hierarchiesicherheit Pflicht. Ein offener Konkurrenzkampf, ein wahrscheinlicher weiterer Torwarttransfer oder reine Hoffnung auf einen späteren Wechsel sperrt den gesamten Vereinsblock.
- Verletzte, stark wechselgefährdete und reine Entwicklungsprojekte höchstens als einzelne Wetten einsetzen.

### Normal

- Profilgewichte unverändert verwenden.
- Vier bis sechs bewusst riskantere Plätze sind vertretbar.
- Im Tor sind mindestens 60 Prozent Saison-Stammplatzwahrscheinlichkeit, höchstens 55 Prozent externes Besetzungsrisiko und mindestens mittlere Hierarchiesicherheit erforderlich.

### Aktiv

- `upside` und `value` leicht erhöhen.
- Frühere Wetten und offene Konkurrenzkämpfe zulassen.
- Im Tor dürfen offene Duelle ab 48 Prozent Stammplatzwahrscheinlichkeit und bis 70 Prozent externem Besetzungsrisiko bewusst eingegangen werden.
- Nur verwenden, wenn der Nutzer während der Saison aktiv nachsteuern will.

## Variabilität

Variabilität darf keine blinde Zufallsauswahl sein. Zuerst das beste Ergebnis innerhalb des vollständig annotierten Kandidatenpools bestimmen, anschließend alternative Kader mit einem Seed erzeugen.

| Stufe | Zielabstand zum besten Pool-Ergebnis | Zielunterschied |
|---|---:|---:|
| niedrig | höchstens 2 % | genau 2 Spieler, sofern im Korridor machbar |
| mittel | höchstens 5 % | genau 4 Spieler, sofern im Korridor machbar |
| hoch | höchstens 8 % | genau 6 Spieler, sofern im Korridor machbar |

- Eine nachgelagerte Kern-, Budget- oder Torwarthierarchie-Reparatur darf den Zielunterschied um genau einen Spieler unter- oder überschreiten. Damit gelten nach allen harten Regeln 1–3, 3–5 beziehungsweise 5–7 Spieler als enge zulässige Toleranz; größere Abweichungen bleiben eine Warnung.
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

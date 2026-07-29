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
- Nach einem Vereinswechsel die Formübertragbarkeit nur dann auf Rolle und Kontext reduzieren und `unknown_role` erhöhen, wenn der neue Auftrag noch ungeklärt ist. Belegen aktuelle Primärquellen eine bestätigte oder erweiterte Start- und Schlüsselrolle, darf der Transferfaktor 1,0 bleiben. Eine höhere Teamqualität kann dann `context` begrenzt verbessern; ein erwarteter Rollenverlust bleibt klar negativ. Systempassung erst mit Trainer-, Positions- oder Formationsbelegen festschreiben.
- Erwartete Rollen strukturiert bewerten: Startwahrscheinlichkeit, Elfmeter, direkte Freistöße, Ecken, Spielmacher- und offensive Fokusrolle, Kapitänsamt sowie bei Verteidigern die torgefährliche Anspielstation für Standards. Historische Verantwortungen am alten Verein nie ohne aktuelle Bestätigung übertragen.
- Die endgültige Startelf-Zielfunktion ergänzt den allgemeinen Spielerscore um einen begrenzten `starting_scorer_leverage`. Er verbindet wiederholbare, ligagewichtete Tore und Vorlagen mit aktuell belegten Standards und offensiven Verantwortungen. Mittelfeld und Sturm erhalten höchstens 16 Zusatzpunkte, Verteidiger höchstens 8; bei Vereinswechsel und ungeklärter Rolle wird das Signal stark reduziert. Auf der Bank wirkt es nur entsprechend der erwarteten positions- und slotabhängigen Nutzung.
- Die österreichische Bundesliga und die Schweizer Super League als ungefähr deutsches Drittliganiveau (`0,64`) behandeln. Sie können eine Drittligasaison bestätigen, aber allein keine Zweitligasaison.
- Herausragende jüngere Leistungen genau eine Stufe unter der Zielliga mit dem Verhältnis aus Quell- und Zielstärke übersetzen. Hohe Minuten, Startquote und positionsgerechte Scorer können einen gedeckelten Bonus auf `value` und `upside` auslösen; sie erzeugen weder eine bestätigte Zielniveau-Saison noch automatisch einen Ankerstatus.
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
- In allen Profilen zunächst die Modellutility innerhalb jeder Position zugunsten der bestbewerteten Kandidaten krümmen. Anschließend den vollständigen Kader mit der aktuellen `joint-xi-bench`-Modellversion neu bewerten: Die beste legale Elf erhält Gewicht `1,0`; Reserven erhalten abhängig von Position und Betreuungsaufwand nur ihren erwarteten Einsatzanteil. Bei `gering` gelten Tor `0,04`, Abwehr `0,30`, Mittelfeld `0,22` und Sturm `0,20`.
- Elf bis 14 hochwertige Kernspieler anstreben. Die übrigen Plätze günstig, aber mit plausibler Einsatzchance besetzen; eine gleichwertige Premiumbank ist nicht erforderlich.
- Mindestens 80 Prozent des Mittelfeldbudgets in die dort tatsächlich startenden Spieler lenken. Höchstens einen gewöhnlichen Mittelfeldreservisten oberhalb des positionsbezogenen Mindestpreises zulassen; ein zusätzlicher teurerer Reservist muss die qualifizierte Potenzialschwelle erfüllen.
- Das vollständige Budget muss zuerst verwendet werden. Danach müssen unabhängig vom Strategieprofil mindestens 55 Prozent des Kaderwerts in der stärksten legalen Startelf liegen. Für `gering` liegt das Wunschziel bei 80 Prozent. Getrennt ausweisen: (1) Preisobergrenze aus den aktuellen Positionspreisen und (2) tatsächlich im lokalen Ein-/Doppeltausch-Suchraum erreichbare Quote innerhalb höchstens 1,5 Prozent Modellutility-Verlust. Die zweite Quote ist das operative Ziel. Ein höherer Kernanteil bleibt nachrangig gegenüber erwarteter Rollenleistung und darf weder durch Restbudget noch durch einen objektiv schlechteren teuren Starter erkauft werden.
- Bei vollem Budget Einzelswaps gleicher Position und gleichen Preises sowie gekoppelte Doppeltausche mit identischen Positionszahlen und identischem Gesamtpreis prüfen. Nach jedem Kandidatentausch die beste Formation, Startelf, Ankerbedingungen, Vereinsgrenze und positionsgewichtete Bankleistung vollständig neu berechnen.
- Die stärkste wartungsarme Startelf enthält mindestens zwei Stürmer und höchstens vier Verteidiger. Dadurch bleiben mindestens zwei belastbare offensive Wege erhalten und ein fünfter teurer Abwehrspieler wird nicht als vermeintliche Kerninvestition vor einer besseren Mittelfeld- oder Sturmoption geschützt.
- Solange mindestens ein qualifizierter offensiver Premiumstarter verfügbar ist, gilt für die sieben Abwehrplätze ein weicher Gesamtbudget-Richtwert von 28 Prozent. Belegte torgefährliche Standardrollen der startenden Verteidiger können ihn um höchstens zwei Prozentpunkte erhöhen. Überschreitungen erhalten einen Opportunitätskostenabzug und müssen sich gegen kostenneutrale Mehrspielertausche zugunsten eines Scorers behaupten.
- Die Abwehr besitzt zusätzlich eine harte Spielbarkeitsuntergrenze. Von den startenden Verteidigern müssen alle bis auf höchstens einen mindestens `minutes 65`, `role 65`, `fitness 65`, `transfer 45`, `injury 45`, `rotation 40` und `unknown_role 40` erfüllen. Der nach Modellscore erste Abwehrersatz benötigt mindestens `minutes 60`, `role 60`, `fitness 65` und höchstens 45 in allen Risiken. Danach sind bei einer Dreierkette höchstens drei, bei einer Viererkette höchstens zwei nicht funktionale Mindestpreisfüller erlaubt. Erfüllt ein Mindestpreisspieler die Starter- oder direkte Ersatzschwelle, zählt er als funktional und nicht als Füller; Preis oder Alter allein entscheiden nicht.
- Abwehrpakete mit derselben vollständigen Positionssuche wie Mittelfeld und Sturm prüfen. Zusätzlich gezielt kostenneutrale positionsübergreifende Doppeltausche zwischen einem teuren Mittelfeld-/Sturmreservisten und einem Abwehrplatz sowie Drei- und Vierfachpakete prüfen. Kann dadurch ein Starter oder der erste Abwehrersatz verbessert werden, ohne eine harte Regel, die Qualitätsgrenze oder die Zielfunktion zu verschlechtern, ist der Ausgangskader dominiert und darf nicht ausgegeben werden. Startet die Optimierung mit einer unzulässigen Struktur, ausschließlich Tausche akzeptieren, die die Zahl harter Verstöße schrittweise senken, bis ein gültiger Kader erreicht ist.
- Im Profil `verlässlich` mindestens einen offensiven Premiumanker in dieser Startelf verlangen. Ihn positionsneutral innerhalb von Mittelfeld und Sturm aus zwei getrennten Gates ableiten: (1) mehrjährige bestätigte Leistung, Stabilität und aktuelle Einsatzsicherheit als verlässliches Fundament und (2) mindestens `4,0` Punkte `starting_scorer_leverage` als belegten Offensivpfad. Dieser zweite Pfad entsteht nur aus wiederholbarer, ligagewichteter Tor-/Vorlagenproduktion und/oder aktuell bestätigten Elfmetern, direkten Freistößen, Ecken, Spielmacher- oder offensiven Fokusaufgaben. Hohe Minuten, allgemeine Rolle, Kapitänsamt oder defensive Zuverlässigkeit allein reichen nicht. Weder `benchmark`, Bekanntheit noch eine frühere Nennung durch den Nutzer dürfen diesen Status erzeugen.
- Elite-Rebound-Stürmer als engere Sonderklasse modellieren: mindestens vier bestätigte Spielzeiten, außergewöhnlicher historischer Abschluss- oder Scorerpfad, eine klar schwächere jüngste Saison, mindestens 75 Prozent aktuell belegte Startwahrscheinlichkeit, wiederhergestellte Fitness sowie niedrige Verletzungs-, Rotations-, Transfer- und Rollenrisiken. Nur dann darf die einzelne schwache Saison den Mehrjahreswert um höchstens sechs Scorepunkte weniger absenken. Diese Evidenz kann einen Kandidaten auch unterhalb des höchsten aktuellen Kicker-Preises in die Premiumstartergruppe heben.
- Fehlt ein verfügbarer Elite-Rebound-Stürmer im Kern, den kleinsten nötigen Aufpreis gegenüber einem startenden Stürmer mit dem überschüssigen Budget der Mittelfeld- und Sturmreserven vergleichen. Ist er daraus finanzierbar, erhält die Architektur einen sichtbaren Opportunitätskostenabzug und muss kostenneutrale Zwei-, Drei- und Vierfachtauschpakete zugunsten des Elite-Stürmers prüfen. Das ist ein weiches sportliches Ziel, keine namentliche Pflichtauswahl.
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
- Die letzten fünf abgeschlossenen lokalen Varianten desselben Kontexts als Expositionshistorie verwenden. Innerhalb des engen Qualitätskorridors wiederholt ausgewählte gewöhnliche Spieler zunehmend abwerten; nur evidenzbasiert nicht gleichwertig ersetzbare Ausnahmespieler schützen. Eine neue Variante soll dadurch andere Rollenäquivalente wählen und nicht bloß billige Bankplätze austauschen.
- Im Profil `verlässlich` mit geringem Betreuungsaufwand besonders belastbare offensive Premiumanker des seed-unabhängigen Grundoptimums schützen. Der Schutz wird ausschließlich aus oberstem Positionsperzentil, mindestens vier bestätigten Spielzeiten, einem qualifizierten offensiven Scorerpfad, hoher Einsatz- und Fitnesssicherheit sowie niedrigen Transfer-, Verletzungs-, Rotations-, Ausreißer- und Rollenrisiken abgeleitet. Ein verlässlicher, aber offensiv unauffälliger Stammspieler darf ausgewählt werden, erhält jedoch keinen Premiumschutz. Namen, `benchmark` oder frühere Nutzernennungen dürfen ihn niemals erzeugen.
- Eine persönliche Variante darf einen solchen geschützten Premiumanker nicht zufällig gegen mehrere gewöhnliche Anker oder zusätzliche Banktiefe tauschen. Ist die gewünschte Spielerdistanz unter dieser Bedingung nicht erreichbar, weniger Plätze variieren oder zum Grundoptimum zurückfallen. Das koordinierte Gruppenportfolio bleibt die ausdrückliche Ausnahme: Dort darf die Ankerverteilung für kollisionsarme Kollegenkader bewusst neu optimiert werden.
- Qualitätskorridor und Abweichung nach der vollständigen Startelf-/Bankfinalisierung erneut prüfen. Varianten oberhalb der zulässigen Distanz oder unterhalb der finalen Architektur-Qualitätsgrenze verwerfen; eine vorgelagerte additive 22-Spieler-Bewertung genügt nicht.
- Im Nutzerergebnis „automatische persönliche Variante“ nennen; die private Installationskennung niemals lesen oder ausgeben. Den numerischen Seed nur bei ausdrücklich technischer Diagnose oder vom Nutzer gewünschter exakter Reproduktion nennen.
- Bei bekannten Kollegenkadern Überschneidungen über `--avoid-roster` nach Auswahlhäufigkeit bestrafen. Niemals einen klar schlechteren Spieler allein zur Abgrenzung wählen.
- Nur für ein ausdrücklich zentral koordiniertes Portfolio `--portfolio-size`, `--max-anchor-exposure 1` und eindeutige `--portfolio-index`-Werte mit demselben Gruppenseed verwenden. Das ist eine fortgeschrittene Ausnahme, nicht der normale Kollegenablauf.
- Portfolio-Diversität umfasst auch Anker und Premiumspieler. Standardmäßig darf ein verlässlicher Anker in einem koordinierten Portfolio nur einmal vorkommen. Reicht der Pool dafür nicht, muss die Recherche ligaweit verbreitert werden oder der Lauf verständlich abbrechen. Eine frühere Erwähnung durch den Nutzer begründet weder Ankerstatus noch Mehrfachexposition.
- `benchmark: true` besitzt keinerlei Scorebonus. Es erzwingt nur, dass ein Kandidat recherchiert, verglichen und bei Nichtauswahl erklärt wird.
- Exakte Gegenrechnungen mit derselben Startelf-, Bank-, Budget-, Torwart- und Premiumankerfinalisierung wie den Referenzkader bewerten. Überschreitet eine Gegenrechnung danach das ausgewiesene Grundoptimum, keinen scheinpräzisen Prozentvorteil ausgeben, sondern zuerst den Referenzkader neu optimieren.
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
- Beim Profil `verlässlich` und geringem Betreuungsaufwand im erweiterten Kern mindestens einen qualifizierten U23-Potenzialspieler oberhalb des Minimalpreises verlangen und zwei anstreben, sofern ligaweit geeignete Kandidaten verfügbar sind. Talentwert, Herrenreife, Einsatzprognose, Rolle und Fitness müssen gemeinsam tragen; keine pauschale Altersquote verwenden. Eine Startelf über 28 Jahre oder ohne U23-Spieler als prüfbare Warnung ausgeben, nicht automatisch verwerfen.
- Premiumanker als austauschbare Qualitätsgruppe behandeln. Gibt es einen nicht ausgewählten gleich positionsgebundenen, mehrjährig bestätigten und risikoarmen Premiumanker innerhalb von drei Prozent des Scores, die konkrete Identität des ursprünglichen Optimums nicht schützen.
- Das Referenzoptimum von mehreren gleich teuren, positionsgleichen Premiumankern aus neu optimieren. So darf ein kurzfristig minimal schwächerer Ankertausch eine anschließend bessere Drei- oder Vier-Spieler-Umschichtung öffnen, ohne dass der lokale Bergauf-Optimierer sie übersieht.
- Neben Einzel- und Doppeltauschen kostenneutrale Drei- und Vierfachtauschpakete über mehrere Positionen prüfen. So darf eine günstigere Bank einen zusätzlichen Scorer oder qualifizierten Potenzialspieler finanzieren, ohne Budget, Vereinsgrenze, Torwartblock oder Startelfqualität zu verletzen.
- Maximal ein bis drei extreme Longshots einsetzen, abhängig vom Profil.

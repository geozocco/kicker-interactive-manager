---
name: build-kicker-interactive-squad
description: Plane, optimiere, bewerte und ändere Kader im kicker Managerspiel Interactive über eine bereits angemeldete Chrome-Sitzung. Verwende diesen Skill bei Anfragen zu kicker Interactive, automatischer Kaderzusammenstellung, „bewerte/prüfe meinen Kader“, Verletzungs- oder Transferchecks, Mannschaftsoptimierung, Geheimtipps oder Strategieprofilen für Bundesliga, 2. Bundesliga und 3. Liga. Die WM ist ausdrücklich ausgeschlossen. Unterstützt read-only Kader-Audits, konservative, ausgewogene und ausbruchsorientierte Auswahl sowie kontrolliert unterschiedliche Kader für mehrere Personen.
---

# kicker Interactive Kader aufstellen und bewerten

## Grundvertrag

- Ausschließlich die bereits angemeldete Chrome-Sitzung verwenden. Keine Passwörter, Cookies, Tokens oder Browser-Speicher lesen oder exportieren.
- Vor jeder Browsersteuerung den verfügbaren Chrome-Control-Skill vollständig laden und dessen Interaktions- und Finalisierungsregeln befolgen.
- Aktuelle Informationen zu Transfers, Verletzungen, Vorbereitung, Trainer und Rollen im Web verifizieren. Offizielle Vereins- und Ligaseiten bevorzugen.
- Für die 2. Bundesliga und 3. Liga 2026/27 die im Optimierer hinterlegten zentralen Markt-, Transfermarkt-Historien-, Qualitäts- und News-Feeds als erstes maschinenlesbares Gate verwenden. Der Qualitätsbestand ist nur gültig, wenn er zur aktuellen Historien-Prüfsumme gehört. Lokale Feed-URLs dürfen diesen Standard für Tests oder einen internen Spiegel überschreiben. Der News-Feed ersetzt die gezielte Prüfung von Lücken, Konflikten und folgenreichen Meldungen in Primärquellen nicht.
- Keine Vorjahrespunkte als Prognose behandeln. Wiederholbarkeit, Rolle, Einsatzwahrscheinlichkeit, Umfeld und Preis getrennt bewerten. Historische Minuten und Scorer stets im Niveau der damaligen Liga bewerten; unterklassige Produktion nicht eins zu eins auf die Zielliga übertragen. Die österreichische Bundesliga und die Schweizer Super League im Modell ungefähr auf deutschem Drittliganiveau einordnen.
- Berücksichtigen, dass nur die am Spieltag aufgestellte Elf Punkte sammelt. Reservequalität ist Absicherung und darf insbesondere bei geringem Betreuungsaufwand nicht genauso viel Budgetgewicht erhalten wie der wahrscheinliche Kern.
- Nie „Alle verkaufen“ verwenden. Änderungen einzeln ausführen und nach jeder Phase Kadergröße, Positionen und Budget prüfen.

## Python-Laufzeit unter macOS und Windows

- Vor dem ersten Skriptlauf die von Codex Desktop bereitgestellten Workspace-Abhängigkeiten laden und den dort ausgewiesenen absoluten Pfad zum Python-Executable verwenden.
- Ist keine gebündelte Laufzeit verfügbar, selbstständig einen Python-3-Befehl ermitteln: unter macOS/Linux nacheinander `python3` und `python`, unter Windows nacheinander `py -3`, `python3` und `python` prüfen.
- Nur eine Laufzeit ab Python 3.9 verwenden. Dies mit `<python-3-command> -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)"` verifizieren.
- Den ermittelten `<python-3-command>` für alle folgenden Aufrufe wiederverwenden. Absolute Pfade mit Leerzeichen als ein Argument behandeln; in PowerShell für einen absoluten Executable-Pfad den Aufrufoperator `&` verwenden.
- Den Nutzer erst dann um eine Python-Installation bitten, wenn weder die gebündelte Codex-Laufzeit noch einer der plattformspezifischen Befehle funktioniert.

## Parameter auflösen

Den Wettbewerb sowie die drei Strategieparameter aus der Anfrage übernehmen.

0. Wettbewerb:
   - ausschließlich `Bundesliga`, `2. Bundesliga` oder `3. Liga`
   - die WM und andere Turniere sind ausdrücklich ausgeschlossen
   - fehlt die Spielklasse bei einer Zusammenstellung oder Änderung, vor Recherche oder Browseränderungen nachfragen; nicht aus einem zufällig geöffneten Tab raten
   - bei einer ausdrücklich read-only angeforderten Bewertung darf die Liga aus genau einem geöffneten, eindeutig erkennbaren kicker-Interactive-Kadertab übernommen werden; bei mehreren passenden Tabs oder uneindeutiger Seite nachfragen
   - ist der kicker-Transfermarkt der gewählten Liga noch nicht geöffnet oder fehlt der Spieler-Daten-Export, keine andere Liga auswählen und keinen Kader erfinden; den Nutzer knapp auf den noch geschlossenen Markt hinweisen

1. Strategie:
   - `verlässlich` (Default): bestätigte, wiederholbare Leistung und sichere Minuten
   - `ausgewogen`: Floor und Potenzial ausgewogen kombinieren
   - `ausbruch`: unterbewertete Talente, Neustarts und Rollengewinner stärker gewichten
2. Variabilität:
   - `niedrig`: kleiner Abstand zum besten Ergebnis im vollständig annotierten Kandidatenpool
   - `mittel` (Default): mehrere Plätze aus einem nahezu gleichwertigen Kandidatenband variieren
   - `hoch`: deutlich individuellere Kader bei weiterhin begrenztem Qualitätsabschlag
3. Betreuungsaufwand:
   - `gering` (Default): einen starken, verlässlichen Aufstellungskern finanzieren und die Bank günstig, aber einsatzfähig halten; nicht das Budget auf 22 annähernd gleichwertige Spieler verteilen
   - `normal`: moderate Rollenrisiken zulassen
   - `aktiv`: mehr frühe Wetten zulassen, wenn der Nutzer regelmäßig nachsteuert

Fehlende Strategieparameter auf die angegebenen Defaults setzen und knapp nennen, statt den Ablauf unnötig zu blockieren.

Für exakte Gewichtungen und Qualitätsgrenzen [references/strategy-profiles.md](references/strategy-profiles.md) vollständig lesen.

Vor der ersten Datenabfrage [references/market-data.md](references/market-data.md) und [references/news-hardening.md](references/news-hardening.md) vollständig lesen. Dort stehen Markt- und News-Snapshot-Vertrag, Ablaufzeit, Konfliktbehandlung und manueller Fallback.

Die Kombination `verlässlich` und `gering` ist das konservative Kollegenprofil: Der Kader soll über einen möglichst sicheren, hochwertigen Kern funktionieren. Die Bank fängt einzelne Ausfälle mit günstigen Spielern ab, die realistische Einsatzminuten haben; sie muss den Kern weder preislich noch leistungsmäßig spiegeln. Ein geringer Betreuungsaufwand konzentriert aber in jedem Strategieprofil mindestens 70 Prozent des Budgets auf die stärkste Elf, verlangt dort mindestens zwei Stürmer sowie höchstens vier Verteidiger und nimmt nur einen Torwartblock mit belastbarer vereinsinterner Nummer eins. Dafür gelten mindestens 70 Prozent Saison-Stammplatzwahrscheinlichkeit, höchstens 40 Prozent Risiko eines noch kommenden externen Stammkeepers und mindestens mittlere Hierarchiesicherheit. Offene Torwartduelle sind für `gering` kein zulässiges Glücksspiel.

## Arbeitsmodus bestimmen

- Fragt der Nutzer nach unterstützten Modi, Funktionen oder Beispielprompts, [references/prompt-examples.md](references/prompt-examples.md) vollständig lesen und eine kompakte Auswahl anbieten. Dabei keine Browserrecherche oder Kaderänderung starten.
- „Stelle auf“, „optimiere“, „ändere“ oder gleichwertige Formulierungen autorisieren die inkrementelle Umsetzung im Kicker-Kader.
- „Vorschlag“, „Liste“, „bewerte“, „prüfe“ oder „was hältst du“ bleiben read-only. Insbesondere bei einer Kaderbewertung keine Browseränderung ausführen.
- Bei mehreren Wettbewerben jeden Kader getrennt analysieren und verifizieren.
- Bei fehlender Anmeldung den Nutzer auffordern, sich in Chrome bei kicker anzumelden und anschließend Bescheid zu geben. Nicht auf einen anderen Browser ausweichen.

## Workflow

### 1. Ist-Zustand erfassen

- Prüfen, dass die sichtbare Kicker-Seite zur ausdrücklich gewählten Spielklasse gehört. Wettbewerb, Saison-ID, Budget, Positionsvorgaben, aktuellen Kader und offene Plätze erfassen.
- Für 2. Bundesliga und 3. Liga den frischen zentralen Marktbestand als maßgeblichen Preis-/Positionsbestand verwenden und gegen die sichtbare Saison prüfen. Die offizielle Roh-CSV nicht unnötig in einem Chrome-Tab öffnen.
- Standardmäßig alle Torhüter aus demselben Verein wählen. Nur auf ausdrücklichen Wunsch mit `--mixed-goalkeepers` abweichen.
- Einen vollständigen Torwartblock nicht mit einem sicheren Block verwechseln. Der zentrale Qualitätsstand bewertet jeden verfügbaren Vereinsblock anhand aktueller Einsatz- und Rollenwerte, Abstand zur internen Konkurrenz, relativem Kicker-Preis und Provider-Kader-/Transferlage. Ein drohender neuer Stammkeeper oder ein offenes Duell sperrt den Block abhängig vom Betreuungsprofil.
- Vor dem finalen Browserumbau die in Frage kommenden Torwartvereine zusätzlich gezielt in aktuellen offiziellen Vereinsmeldungen, Trainerzitaten und belastbaren Transfermeldungen prüfen. Provider-Kader erkennen bestätigte oder bereits geführte Neuzugänge gut, aber nicht jedes frühe Gerücht oder jede öffentlich angekündigte Kaderplanung. Solche Belege als `goalkeeper_evidence` dokumentieren; bei angekündigter Suche nach einer neuen Nummer eins den Block für `gering` sperren.
- Weichen die sichtbaren Positionsvorgaben von 3/7/7/5 ab, dem Skript die tatsächlichen Werte über `--goalkeepers`, `--defenders`, `--midfielders` und `--forwards` übergeben.

### 1a. Bestehenden Kader read-only bewerten

Wenn der Nutzer den vorhandenen Kader bewerten oder auf vermeidbare Fehler prüfen lassen möchte, [references/squad-evaluation.md](references/squad-evaluation.md) vollständig lesen und diesen Zweig statt der Kaderoptimierung ausführen.

- Aktuellen Kader zweimal aus dem sichtbaren Chrome-Zustand erfassen und eindeutig gegen den zentralen Marktbestand auflösen.
- Jeden gewählten Spieler vollständig und aktuell annotieren. Für Verbesserungsvorschläge zusätzlich bezahlbare Alternativen recherchieren; für eine reine Sicherheitsprüfung reicht der vollständig geprüfte Zielkader.
- Bei 2. Bundesliga und 3. Liga den frischen zentralen Feed mit `--require-news-snapshot --require-news-coverage` verlangen. Fehlende oder widersprüchliche Daten verhindern eine grüne Bestätigung.
- `scripts/evaluate_squad.py` mit sichtbarem Budget, Positionszahlen, Strategie und Betreuungsaufwand ausführen.
- `avoidable_error_free: true` als einzige grüne Bestätigung behandeln. Bei `blocked` keine numerische Scheinsicherheit erzeugen, sondern die fehlenden Prüfungen nennen.
- Verletzungs-, Transfer- und Rollenwarnungen mit spielerbezogenen aktuellen Quellen nennen. Bezahlbare Alternativen als Prüfhinweise behandeln.
- Im Browser nichts verändern. Erst eine spätere ausdrückliche Aufforderung zum Umbau autorisiert den Schreibworkflow.

### 2. Kandidatenpool bilden

- Zuerst einen breiten Recherchepool erzeugen:

```text
<python-3-command> scripts/optimize_squad.py --competition "2. Bundesliga" --season "2026/27" --profile reliable --budget 10000000 --shortlist-only
```

- Je Position etablierte Kandidaten, Neuzugänge, höherklassig erprobte Spieler, Jugendtalente und Rebound-Kandidaten aufnehmen.
- Mindestens die realistischen Startelf- und Bankkandidaten prüfen; reine 0,05-/0,10-Füller nicht ohne belegbare Einsatzchance bevorzugen.
- Vor dem finalen Lauf in jeder Position mindestens die doppelte tatsächliche Sollzahl aktuell annotieren. Bei den üblichen 3/7/7/5 sind das 6/14/14/10. Im Standardmodus mindestens zwei hierarchisch ausreichend sichere vollständige Torwartblöcke abdecken.
- In Abwehr, Mittelfeld und Sturm jeweils mindestens zwei auswählbare Leistungsreferenzen mit `benchmark: true` annotieren. Diese Spieler bilden den Vergleichsmaßstab für Preis, Sicherheit und erwartbare Leistung; sie müssen nicht automatisch gekauft werden.
- Jeden vom Nutzer genannten Spieler vollständig und mit `benchmark: true` annotieren, auch wenn der Preis oder die automatische Shortlist gegen ihn spricht. Bestätigt nicht auswählbare Spieler mit Quellen belegen und über `exclude: true` kennzeichnen, statt sie still wegzulassen.
- Einen vom Nutzer nur als Beispiel genannten Spieler niemals wegen der Nennung höher bewerten, erzwingen oder automatisch in einen Ankerkern aufnehmen. `benchmark: true` steuert ausschließlich Recherche, Vergleich und Begründung; es verändert den numerischen Spielerscore nicht. Nur ausdrücklich formulierte Wünsche wie „Spieler X muss in den Kader“ als Auswahlvorgabe behandeln.
- Premiumsignale ligaweit ausdrücklich suchen und annotieren: mehrjährige Spitzenleistung, wiederholbare Standards oder Schlüsselrolle, Kapitänsverantwortung, frühere Torjägerkrone, außergewöhnliche individuelle Kreativ- oder Abschlussqualität sowie bereits höherklassig bestätigte Leistung. Aktuelle Verletzungs-, Transfer- oder Rollenrisiken können gegen eine Auswahl sprechen, aber nicht gegen die Aufnahme in den Vergleich.
- Jugendhistorien aus deutschen und ausländischen Nachwuchswettbewerben als eigenes, wettbewerbsgewichtetes Potenzialsignal verwenden. Sie dürfen `upside` und die Aufnahme in den Geheimtipp-Pool erhöhen, aber niemals `proven_seasons`, `confirmed_performance` oder den Ankerstatus einer Seniorensaison ersetzen.
- Vorjahresausreißer mit Regression, gegnerischer Anpassung und möglichem Rollenverlust belasten.
- Mehrjährige Konstanz, Standards, Kapitänsrolle und trainerbestätigte Schlüsselrollen als wiederholbare Signale aufwerten.
- API-Sports-Providernoten nur als kleines Hilfssignal verwenden. Positionsabhängige, wiederholbare Ereignisse wie Startelfquote, Schüsse aufs Tor, Key Passes, Duelle, Defensivaktionen, Saves und Scorer tragen stärker. Eine Provider-Note niemals als Kicker-Note ausgeben.
- Den zentralen Kicker-Zeitverlauf für Preise, kumulierte Punkte und Notenschnitt einbeziehen. Eine einzelne Beobachtung bleibt neutral; erst mindestens zwei zeitlich getrennte Beobachtungen erzeugen ein begrenztes Formsignal. Kurzfristige Form darf eine mehrjährige Leistungsbasis ergänzen, aber nicht ersetzen.
- Transfers als Rollenreset behandeln. Qualität des Spielers und Passung zum neuen Team getrennt von seiner alten Produktion bewerten.
- Transfer-, Rotations- und Verletzungsrisiken aktuell recherchieren. Unsicherheit offen markieren, nicht erfinden.

### 3. Kandidaten bewerten

- Alle hier genannten Skript- und Referenzpfade relativ zum Verzeichnis dieses `SKILL.md` auflösen.
- Komponenten und Risiken nach [references/annotation-schema.md](references/annotation-schema.md) erfassen.
- Für jeden final geprüften Kandidaten zusätzlich `reliable_anchor`, `proven_seasons`, `anchor_reason`, `benchmark` und belastbare `evidence` erfassen. `proven_seasons` zählt nur Spielzeiten mit belastbarer Leistung auf vergleichbarem oder höherem Niveau; eine einzelne starke Vorsaison reicht nicht.
- Den Ankerpool ligaweit und ergebnisoffen recherchieren. Er muss Rollen aus mehreren Vereinen und Preisklassen enthalten. Namen, die der Nutzer als Beispiele, frühere Gedanken oder Kritik erwähnt hat, sind Vergleichskandidaten und dürfen weder den Pool definieren noch einen Auswahlbonus erhalten. Nur ein ausdrückliches „Spieler X muss in den Kader“ ist eine harte Vorgabe.
- `scripts/optimize_squad.py` mit zentralem Marktbestand, Profil, Variabilität, Betreuungsaufwand, Budget und Annotationen ausführen.
- Für einen finalen Lauf `--require-market-snapshot --require-quality-snapshot` verlangen. `market_audit` und `quality_audit` müssen frisch sein, zusammengehören und zur sichtbaren Liga und Saison passen. Der Qualitätsbestand muss mindestens 60 Kandidaten, 20 ligaweit unterschiedliche Anker, 15 offensive Anker und sechs vollständige Torwartblöcke enthalten. Nur beim dokumentierten manuellen Fallback eine aktuelle lokale Kicker-CSV mit `--players` verwenden.
- Den eingebauten zentralen Feed anhand von Wettbewerb und Saison verwenden. `KICKER_NEWS_FEED_URL` und optional `KICKER_NEWS_FEED_TOKEN` aus der Laufzeit überschreiben ihn nur, wenn sie ausdrücklich zentral eingerichtet sind. Die Werte nicht ausgeben. Niemals nach `SPORTMONKS_API_TOKEN` oder `API_SPORTS_KEY` auf einem Kollegenrechner suchen; diese gehören ausschließlich in den zentralen Aktualisierungslauf.
- Beim zentralen Feed immer Wettbewerb und Saison gegen die sichtbare Kicker-Seite prüfen und für den finalen Lauf `--require-news-snapshot --require-news-coverage` verwenden.
- Ist kein zentraler Feed eingerichtet oder erreichbar, den in `news-hardening.md` beschriebenen manuellen Tagescheck für jeden möglichen Zielspieler und entscheidenden Near-Miss durchführen. Ein abgelaufenes Snapshot niemals als aktuellen Beleg verwenden.
- Im finalen Lauf werden ausschließlich vollständig aktuell annotierte Spieler berücksichtigt.
- Einen finalen Kader nicht aus einem unannotierten Lauf ableiten. `--allow-unannotated` ausschließlich für technische Smoke-Tests verwenden und dessen Ergebnis nie als Empfehlung oder Browser-Zielkader präsentieren.
- Im Normalfall keinen Seed erfinden und keine Kadernummer abfragen. `scripts/optimize_squad.py` ohne `--seed` ausführen; es erzeugt beziehungsweise verwendet automatisch eine private, nicht personenbezogene Installationskennung und leitet daraus für Liga, Saison und Strategie eine stabile persönliche Variante ab.
- Fordert der Nutzer „eine neue Variante“, „neu würfeln“ oder sinngleich eine weitere Alternative an, denselben Lauf einmal mit `--new-variant` ausführen. Nicht mehrfach neu würfeln, sofern der Nutzer nicht mehrere Varianten verlangt.
- `--seed` nur verwenden, wenn der Nutzer ausdrücklich eine konkrete technische Variante reproduzieren oder teilen möchte. Niemals die private Installationskennung lesen, ausgeben oder übertragen.
- Meldet die Ausführungsumgebung einen noch laufenden Optimiererprozess, denselben Prozess weiter abwarten statt einen zweiten Lauf zu starten. Nur nach bestätigtem Abbruch mit demselben Seed erneut ausführen.
- Wenn Kader anderer Kollegen als JSON vorliegen, diese jeweils mit `--avoid-roster` übergeben. Wiederholte Spieler werden nach ihrer tatsächlichen bisherigen Einsatzhäufigkeit stärker belastet; das diversifiziert auch Premiumplätze innerhalb des Qualitätskorridors.
- Nur wenn der Nutzer ausdrücklich ein zentral koordiniertes Gruppenportfolio verlangt, die fortgeschrittenen Optionen `--portfolio-size`, `--portfolio-index`, `--max-anchor-exposure 1` und einen gemeinsamen Seed verwenden. Vor einem Fünfer-Portfolio mit vier Pflichtankern müssen mindestens 20 tatsächlich auswählbare, vollständig recherchierte Anker ligaweit im Pool stehen; zusätzliche Reserve ist sinnvoll. Für normale Kollegenkader weder Kadernummer noch Gruppenseed verlangen.

Beispiel:

```text
<python-3-command> scripts/optimize_squad.py --competition "2. Bundesliga" --season "2026/27" --require-market-snapshot --require-quality-snapshot --require-news-snapshot --require-news-coverage --profile reliable --variation medium --maintenance low --min-reliable-anchors 4 --min-attacking-anchors 3 --min-core-budget-share 0.70 --budget 10000000 --goalkeepers 3 --defenders 7 --midfielders 7 --forwards 5 --format json
```

Beispiel für eine ausdrücklich gewünschte neue persönliche Variante:

```text
<python-3-command> scripts/optimize_squad.py ... --variation medium --new-variant --format json
```

Wettbewerb, Saison und vier Positionsargumente immer mit den zuvor von der sichtbaren Kicker-Seite erfassten Werten belegen; die gezeigten Werte sind nur ein Beispiel. Für das Profil `verlässlich` mindestens vier `reliable_anchor` verlangen, davon mindestens drei in Mittelfeld oder Sturm. Ist das mit aktuell auswählbaren Spielern nicht möglich, den Pool um mehrjährig bestätigte Scorer, Kreativspieler und Standard- oder Schlüsselspieler erweitern oder die Einschränkung offen erklären; die Mindestzahl nicht still absenken.

### 4. Portfolio prüfen

- Kader nicht nur nach Summenscore beurteilen:
  - einen klaren, hochwertigen Kern aus wahrscheinlichen Startern
  - bei `verlässlich` mindestens vier aktuell belastbare `reliable_anchor`, davon mindestens drei in Mittelfeld oder Sturm
  - keine unnötige Häufung desselben Teamrisikos
  - wenige teure Spieler nur bei wiederholbarer Rolle
  - bei geringem Betreuungsaufwand die Qualität auf den Kern konzentrieren und teure Doppelbesetzungen vermeiden
  - günstige Bankspieler nur mit belegbarer Einsatzchance wählen; keine Bank voller unklarer Entwicklungsprojekte
- Transfergefahr vor Saisonstart gesondert prüfen
- `news_audit` muss frisch sein, zum Wettbewerb und zur Saison passen und darf bei ausgewählten Spielern weder fehlende Provider-Zuordnungen noch offene Konflikte enthalten
- `market_audit` muss frisch sein, zum Wettbewerb und zur Saison passen und die vollständige zentrale Spielerliste ausweisen
- `quality_audit` muss frisch sein, dieselbe Markt-, News-, Transfermarkt-Historien- und Kicker-Zeitreihen-Prüfsumme tragen, mindestens 75 Prozent eindeutig oder mit hoher Plausibilität zugeordnete Transfermarkt-Historien ausweisen und die Mindestwerte von 60 Kandidaten, 20 Ankern, 15 offensiven Ankern und sechs Torwartblöcken erreichen
- Für `gering` unabhängig vom Strategieprofil standardmäßig 11 bis 14 Kernspieler, wenige günstige direkte Vertreter und anschließend preiswerte einsatzfähige Ergänzungen bilden. Eine gleichmäßig teure Bank ist kein Qualitätsmerkmal und erschwert die Finanzierung von Ausnahmespielern.
- Für `gering` müssen mindestens 70 Prozent des gesamten Kaderwerts in der stärksten legalen Startelf liegen. Diese enthält mindestens zwei Stürmer, höchstens vier Verteidiger und die vereinsinterne Nummer eins eines freigegebenen Torwartblocks. Die Torwartprognose muss mindestens 70 Prozent Saison-Stammplatzwahrscheinlichkeit, höchstens 40 Prozent externes Besetzungsrisiko und mindestens mittlere Sicherheit erreichen. Ein Verstoß ist ein Abbruchgrund.
- Variabilität darf einzelne Kernentscheidungen und günstige Ergänzungen verändern, aber nicht die Kaderarchitektur in 22 gleichwertige Alternativen auflösen.
- Bei einem Gruppenportfolio nicht nur Bankplätze rotieren. Anker, Scorer und Premiumspieler ebenfalls über die Slots verteilen. Jeder Einzelkader muss weiterhin seine Anker-, Startelf- und Qualitätsgrenzen erfüllen.
- Das `portfolio`-Audit einschließlich `common_starting_player_ids`, `common_reliable_anchor_ids`, `reliable_anchor_exposure` und `anchor_diversity_target_met` prüfen. Bei `--max-anchor-exposure 1` müssen die Ankerkerne paarweise überschneidungsfrei sein. Ist das innerhalb des Qualitätskorridors nicht möglich, den ligaweiten Kandidatenpool verbreitern und neu recherchieren; niemals still dieselben bekannten Namen in alle Kader schreiben. Eine Lockerung der Ankerexposition ist nur nach ausdrücklicher Zustimmung des Nutzers zulässig.
- Variabilität nur innerhalb der in `strategy-profiles.md` festgelegten Qualitätsgrenze zulassen.
- Bleiben mehr als 10 Prozent des Budgets ungenutzt, den Kandidatenpool über mehrere Preisklassen erweitern und neu rechnen. Einen solchen Rohkader nicht direkt umsetzen.
- Abweichungen vom Optimierer begründen und Budget erneut berechnen.

### 5. Auswahl begründen und gegenprüfen

Vor jeder Änderung in Chrome einen vollständigen Ergebnisentwurf erstellen und prüfen. Kann eine Auswahl oder ein bewusst ausgelassener Premiumspieler nicht konkret erklärt werden, Annotationen und Kandidatenpool verbessern und erneut rechnen. Erst nach bestandener Prüfung den Kader im Browser verändern.

Direkt vor dem ersten Verkauf den zentralen Feed erneut laden. Ist das Snapshot inzwischen abgelaufen, älter als die in `news-hardening.md` festgelegte letzte Kontrollfrist oder inhaltlich geändert, ohne `--new-variant` erneut optimieren und so dieselbe automatische Variante beibehalten. Bei einem ausdrücklich gesetzten Seed denselben Seed erneut verwenden. Bei manueller Fallback-Recherche den Zeitpunkt der letzten Prüfung entsprechend kontrollieren.

Der Ergebnisentwurf muss enthalten:

1. Den Geltungsbereich korrekt benennen: „bestes Ergebnis innerhalb des aktuell recherchierten und annotierten Kandidatenpools“. Nicht ohne diese Einschränkung von einem „mathematischen Optimum“ sprechen.
2. Kern, direkte Vertreter und günstige Ergänzungen klar trennen. Für jeden Kernspieler einen individuellen sportlichen und wirtschaftlichen Auswahlgrund nennen; auch bei jedem Bankspieler die konkrete Funktion wie Einsatzsicherheit, Positionsabdeckung oder Preisvorteil nennen.
3. Für Abwehr, Mittelfeld und Sturm jeweils mindestens zwei wichtige nicht gewählte Kandidaten als Near-Misses vergleichen. Zusätzlich jeden ausgelassenen Spieler mit `benchmark: true` aufführen.
4. Für jeden Near-Miss die vom Optimierer ausgegebene `counterfactual`-Variante verwenden: das tatsächlich verdrängte Spielerpaket, die Budgetänderung und den Utility-Abstand nennen. Danach knapp erklären, welcher Rollen-, Fitness- oder Risikofaktor zusätzlich ausschlaggebend war.
5. Die Budgetarchitektur erklären: wofür Premiumbudget eingesetzt wird, an welchen Bankplätzen bewusst gespart wird und welche Stärke dieser Tausch finanziert.
6. Spielerbezogene Aussagen mit den in `evidence` erfassten aktuellen Quellen belegen. Allgemeine Vereins- oder Trainingslagerlinks ersetzen keine Belege für Rolle, Fitness, Transferlage oder Auswahlentscheidung eines konkreten Spielers.
7. Verbleibende Risiken und den sinnvollen nächsten Kontrollzeitpunkt nennen.
8. News-Audit knapp nennen: Snapshot-Zeitpunkt und -Ablauf, verwendete Provider, Abdeckung des Zielkaders, Konflikte sowie manuell geprüfte Lücken.

Generische drei bis fünf Gründe für den Gesamtkader genügen diesem Vertrag nicht.

### 6. In Chrome umsetzen

- Vor tatsächlichen Änderungen [references/browser-workflow.md](references/browser-workflow.md) vollständig lesen.
- Keine Browseränderung beginnen, solange der News-Gate für einen Zielspieler veraltet, unvollständig oder widersprüchlich ist.
- Erst Verkäufe, dann Käufe einzeln und positionsweise durchführen.
- Vor jeder Aktion einen frischen DOM-Zustand erfassen, den Spielereintrag eindeutig über Name, Verein, Position und Preis abgrenzen und genau einen Treffer verlangen.
- Nach jeder Positionsgruppe sowie abschließend Kadergröße, Positionszahlen, Restbudget und alle Zielnamen verifizieren.
- Den bearbeiteten Kicker-Tab als sichtbares Ergebnis an den Nutzer übergeben.

## Ergebnis

Bei einer Kaderbewertung das Urteil nach `squad-evaluation.md` liefern und ausdrücklich bestätigen, dass Chrome unverändert blieb.

Bei einer Zusammenstellung den unter „Auswahl begründen und gegenprüfen“ vorbereiteten Ergebnisentwurf vollständig liefern und um Profil, Variabilität, Betreuungsaufwand, „automatische persönliche Variante“ beziehungsweise ausdrücklich gesetzten Seed, Kadergröße, Restbudget und den vollständigen Kader ergänzen. Die private Installationskennung niemals nennen. Bei ausgeführter Änderung ausdrücklich bestätigen, dass Namen, Positionen und Budget anschließend in Chrome verifiziert wurden.

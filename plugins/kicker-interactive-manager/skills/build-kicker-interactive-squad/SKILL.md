---
name: build-kicker-interactive-squad
description: Plane, optimiere, bewerte und ändere Kader im kicker Managerspiel Interactive über eine bereits angemeldete Chrome-Sitzung. Verwende diesen Skill bei Anfragen zu kicker Interactive, automatischer Kaderzusammenstellung, „bewerte/prüfe meinen Kader“, Verletzungs- oder Transferchecks, Mannschaftsoptimierung, Geheimtipps oder Strategieprofilen für Bundesliga, 2. Bundesliga und 3. Liga. Die WM ist ausdrücklich ausgeschlossen. Unterstützt read-only Kader-Audits, konservative, ausgewogene und ausbruchsorientierte Auswahl sowie kontrolliert unterschiedliche Kader für mehrere Personen.
---

# kicker Interactive Kader aufstellen und bewerten

## Grundvertrag

- Ausschließlich die bereits angemeldete Chrome-Sitzung verwenden. Keine Passwörter, Cookies, Tokens oder Browser-Speicher lesen oder exportieren.
- Vor jeder Browsersteuerung den verfügbaren Chrome-Control-Skill vollständig laden und dessen Interaktions- und Finalisierungsregeln befolgen.
- Aktuelle Informationen zu Transfers, Verletzungen, Vorbereitung, Trainer und Rollen im Web verifizieren. Offizielle Vereins- und Ligaseiten bevorzugen.
- Für die 2. Bundesliga und 3. Liga 2026/27 den im Optimierer hinterlegten zentralen News-Feed als erstes maschinenlesbares Aktualitäts-Gate verwenden. Eine lokale `KICKER_NEWS_FEED_URL` darf diesen Standard für Tests oder einen internen Spiegel überschreiben. Der Feed ersetzt die gezielte Prüfung von Lücken, Konflikten und folgenreichen Meldungen in Primärquellen nicht.
- Keine Vorjahrespunkte als Prognose behandeln. Wiederholbarkeit, Rolle, Einsatzwahrscheinlichkeit, Umfeld und Preis getrennt bewerten.
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

Vor der ersten News-Abfrage [references/news-hardening.md](references/news-hardening.md) vollständig lesen. Dort stehen Snapshot-Vertrag, Provider-Regeln, Ablaufzeit, Konfliktbehandlung und manueller Fallback.

Die Kombination `verlässlich` und `gering` ist das konservative Kollegenprofil: Der Kader soll über einen möglichst sicheren, hochwertigen Kern funktionieren. Die Bank fängt einzelne Ausfälle mit günstigen Spielern ab, die realistische Einsatzminuten haben; sie muss den Kern weder preislich noch leistungsmäßig spiegeln.

## Arbeitsmodus bestimmen

- „Stelle auf“, „optimiere“, „ändere“ oder gleichwertige Formulierungen autorisieren die inkrementelle Umsetzung im Kicker-Kader.
- „Vorschlag“, „Liste“, „bewerte“, „prüfe“ oder „was hältst du“ bleiben read-only. Insbesondere bei einer Kaderbewertung keine Browseränderung ausführen.
- Bei mehreren Wettbewerben jeden Kader getrennt analysieren und verifizieren.
- Bei fehlender Anmeldung den Nutzer auffordern, sich in Chrome bei kicker anzumelden und anschließend Bescheid zu geben. Nicht auf einen anderen Browser ausweichen.

## Workflow

### 1. Ist-Zustand erfassen

- Prüfen, dass die sichtbare Kicker-Seite zur ausdrücklich gewählten Spielklasse gehört. Wettbewerb, Saison-ID, Budget, Positionsvorgaben, aktuellen Kader und offene Plätze erfassen.
- Den Link „Spieler-Daten Export“ der aktuellen Saison verwenden und die CSV als maßgeblichen Preis-/Positionsbestand behandeln.
- Standardmäßig alle Torhüter aus demselben Verein wählen. Nur auf ausdrücklichen Wunsch mit `--mixed-goalkeepers` abweichen.
- Weichen die sichtbaren Positionsvorgaben von 3/7/7/5 ab, dem Skript die tatsächlichen Werte über `--goalkeepers`, `--defenders`, `--midfielders` und `--forwards` übergeben.

### 1a. Bestehenden Kader read-only bewerten

Wenn der Nutzer den vorhandenen Kader bewerten oder auf vermeidbare Fehler prüfen lassen möchte, [references/squad-evaluation.md](references/squad-evaluation.md) vollständig lesen und diesen Zweig statt der Kaderoptimierung ausführen.

- Aktuellen Kader zweimal aus dem sichtbaren Chrome-Zustand erfassen und eindeutig gegen die offizielle CSV auflösen.
- Jeden gewählten Spieler vollständig und aktuell annotieren. Für Verbesserungsvorschläge zusätzlich bezahlbare Alternativen recherchieren; für eine reine Sicherheitsprüfung reicht der vollständig geprüfte Zielkader.
- Bei 2. Bundesliga und 3. Liga den frischen zentralen Feed mit `--require-news-snapshot --require-news-coverage` verlangen. Fehlende oder widersprüchliche Daten verhindern eine grüne Bestätigung.
- `scripts/evaluate_squad.py` mit sichtbarem Budget, Positionszahlen, Strategie und Betreuungsaufwand ausführen.
- `avoidable_error_free: true` als einzige grüne Bestätigung behandeln. Bei `blocked` keine numerische Scheinsicherheit erzeugen, sondern die fehlenden Prüfungen nennen.
- Verletzungs-, Transfer- und Rollenwarnungen mit spielerbezogenen aktuellen Quellen nennen. Bezahlbare Alternativen als Prüfhinweise behandeln.
- Im Browser nichts verändern. Erst eine spätere ausdrückliche Aufforderung zum Umbau autorisiert den Schreibworkflow.

### 2. Kandidatenpool bilden

- Zuerst einen breiten Recherchepool erzeugen:

```text
<python-3-command> scripts/optimize_squad.py --players <players-csv-path> --profile reliable --budget 10000000 --shortlist-only
```

- Je Position etablierte Kandidaten, Neuzugänge, höherklassig erprobte Spieler, Jugendtalente und Rebound-Kandidaten aufnehmen.
- Mindestens die realistischen Startelf- und Bankkandidaten prüfen; reine 0,05-/0,10-Füller nicht ohne belegbare Einsatzchance bevorzugen.
- Vor dem finalen Lauf in jeder Position mindestens die doppelte tatsächliche Sollzahl aktuell annotieren. Bei den üblichen 3/7/7/5 sind das 6/14/14/10. Im Standardmodus mindestens zwei vollständige Torwartblöcke abdecken.
- In Abwehr, Mittelfeld und Sturm jeweils mindestens zwei auswählbare Leistungsreferenzen mit `benchmark: true` annotieren. Diese Spieler bilden den Vergleichsmaßstab für Preis, Sicherheit und erwartbare Leistung; sie müssen nicht automatisch gekauft werden.
- Jeden vom Nutzer genannten Spieler vollständig und mit `benchmark: true` annotieren, auch wenn der Preis oder die automatische Shortlist gegen ihn spricht. Bestätigt nicht auswählbare Spieler mit Quellen belegen und über `exclude: true` kennzeichnen, statt sie still wegzulassen.
- Premiumsignale ligaweit ausdrücklich suchen und annotieren: mehrjährige Spitzenleistung, wiederholbare Standards oder Schlüsselrolle, Kapitänsverantwortung, frühere Torjägerkrone, außergewöhnliche individuelle Kreativ- oder Abschlussqualität sowie bereits höherklassig bestätigte Leistung. Aktuelle Verletzungs-, Transfer- oder Rollenrisiken können gegen eine Auswahl sprechen, aber nicht gegen die Aufnahme in den Vergleich.
- Vorjahresausreißer mit Regression, gegnerischer Anpassung und möglichem Rollenverlust belasten.
- Mehrjährige Konstanz, Standards, Kapitänsrolle und trainerbestätigte Schlüsselrollen als wiederholbare Signale aufwerten.
- Transfers als Rollenreset behandeln. Qualität des Spielers und Passung zum neuen Team getrennt von seiner alten Produktion bewerten.
- Transfer-, Rotations- und Verletzungsrisiken aktuell recherchieren. Unsicherheit offen markieren, nicht erfinden.

### 3. Kandidaten bewerten

- Alle hier genannten Skript- und Referenzpfade relativ zum Verzeichnis dieses `SKILL.md` auflösen.
- Komponenten und Risiken nach [references/annotation-schema.md](references/annotation-schema.md) erfassen.
- Für jeden final geprüften Kandidaten zusätzlich `reliable_anchor`, `proven_seasons`, `anchor_reason`, `benchmark` und belastbare `evidence` erfassen. `proven_seasons` zählt nur Spielzeiten mit belastbarer Leistung auf vergleichbarem oder höherem Niveau; eine einzelne starke Vorsaison reicht nicht.
- `scripts/optimize_squad.py` mit CSV, Profil, Variabilität, Betreuungsaufwand, Budget und Annotationen ausführen.
- Den eingebauten zentralen Feed anhand von Wettbewerb und Saison verwenden. `KICKER_NEWS_FEED_URL` und optional `KICKER_NEWS_FEED_TOKEN` aus der Laufzeit überschreiben ihn nur, wenn sie ausdrücklich zentral eingerichtet sind. Die Werte nicht ausgeben. Niemals nach `SPORTMONKS_API_TOKEN` oder `API_SPORTS_KEY` auf einem Kollegenrechner suchen; diese gehören ausschließlich in den zentralen Aktualisierungslauf.
- Beim zentralen Feed immer Wettbewerb und Saison gegen die sichtbare Kicker-Seite prüfen und für den finalen Lauf `--require-news-snapshot --require-news-coverage` verwenden.
- Ist kein zentraler Feed eingerichtet oder erreichbar, den in `news-hardening.md` beschriebenen manuellen Tagescheck für jeden möglichen Zielspieler und entscheidenden Near-Miss durchführen. Ein abgelaufenes Snapshot niemals als aktuellen Beleg verwenden.
- Im finalen Lauf werden ausschließlich vollständig aktuell annotierte Spieler berücksichtigt.
- Einen finalen Kader nicht aus einem unannotierten Lauf ableiten. `--allow-unannotated` ausschließlich für technische Smoke-Tests verwenden und dessen Ergebnis nie als Empfehlung oder Browser-Zielkader präsentieren.
- Vor dem finalen Lauf einen zufälligen, nicht personenbezogenen Seed erzeugen, sofern der Nutzer keinen vorgibt, und ihn ausdrücklich mit `--seed` übergeben. Den Seed bereits vor beziehungsweise beim Start festhalten. Derselbe Seed reproduziert denselben Kader; ein neuer Seed erzeugt eine kontrollierte Alternative.
- Meldet die Ausführungsumgebung einen noch laufenden Optimiererprozess, denselben Prozess weiter abwarten statt einen zweiten Lauf zu starten. Nur nach bestätigtem Abbruch mit demselben Seed erneut ausführen.
- Wenn Kader anderer Kollegen als JSON vorliegen, diese mit `--avoid-roster` übergeben. Dadurch wird Überschneidung innerhalb des Qualitätskorridors zusätzlich reduziert.

Beispiel:

```text
<python-3-command> scripts/optimize_squad.py --players <players-csv-path> --annotations <annotations-json-path> --competition "2. Bundesliga" --season "2026/27" --require-news-snapshot --require-news-coverage --profile reliable --variation medium --maintenance low --min-reliable-anchors 4 --min-attacking-anchors 3 --min-core-budget-share 0.70 --seed <seed> --budget 10000000 --goalkeepers 3 --defenders 7 --midfielders 7 --forwards 5 --format json
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
- Für `verlässlich` plus `gering` standardmäßig 11 bis 14 Kernspieler, wenige günstige direkte Vertreter und anschließend preiswerte einsatzfähige Ergänzungen bilden. Eine gleichmäßig teure Bank ist kein Qualitätsmerkmal und erschwert die Finanzierung von Ausnahmespielern.
- Für `verlässlich` plus `gering` müssen mindestens 70 Prozent des gesamten Kaderwerts in der stärksten legalen Startelf liegen. Ein niedrigerer Wert ist ein Abbruchgrund: Bank verbilligen, nachgewiesene Scorer und Kreativspieler finanzieren und neu rechnen.
- Variabilität darf einzelne Kernentscheidungen und günstige Ergänzungen verändern, aber nicht die Kaderarchitektur in 22 gleichwertige Alternativen auflösen.
- Variabilität nur innerhalb der in `strategy-profiles.md` festgelegten Qualitätsgrenze zulassen.
- Bleiben mehr als 10 Prozent des Budgets ungenutzt, den Kandidatenpool über mehrere Preisklassen erweitern und neu rechnen. Einen solchen Rohkader nicht direkt umsetzen.
- Abweichungen vom Optimierer begründen und Budget erneut berechnen.

### 5. Auswahl begründen und gegenprüfen

Vor jeder Änderung in Chrome einen vollständigen Ergebnisentwurf erstellen und prüfen. Kann eine Auswahl oder ein bewusst ausgelassener Premiumspieler nicht konkret erklärt werden, Annotationen und Kandidatenpool verbessern und erneut rechnen. Erst nach bestandener Prüfung den Kader im Browser verändern.

Direkt vor dem ersten Verkauf den zentralen Feed erneut laden. Ist das Snapshot inzwischen abgelaufen, älter als die in `news-hardening.md` festgelegte letzte Kontrollfrist oder inhaltlich geändert, mit demselben Seed erneut optimieren und den Ergebnisentwurf aktualisieren. Bei manueller Fallback-Recherche den Zeitpunkt der letzten Prüfung entsprechend kontrollieren.

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

Bei einer Zusammenstellung den unter „Auswahl begründen und gegenprüfen“ vorbereiteten Ergebnisentwurf vollständig liefern und um Profil, Variabilität, Betreuungsaufwand, Seed, Kadergröße, Restbudget und den vollständigen Kader ergänzen. Bei ausgeführter Änderung ausdrücklich bestätigen, dass Namen, Positionen und Budget anschließend in Chrome verifiziert wurden.

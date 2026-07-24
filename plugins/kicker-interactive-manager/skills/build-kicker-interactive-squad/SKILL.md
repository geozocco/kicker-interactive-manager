---
name: build-kicker-interactive-squad
description: Plane, optimiere und ändere Kader im kicker Managerspiel Interactive über eine bereits angemeldete Chrome-Sitzung. Verwende diesen Skill bei Anfragen zu kicker Interactive, automatischer Kaderzusammenstellung, Transfers, Mannschaftsoptimierung, Geheimtipps oder Strategieprofilen für Bundesliga, 2. Bundesliga, 3. Liga und weitere angebotene Wettbewerbe. Unterstützt konservative, ausgewogene und ausbruchsorientierte Auswahl sowie kontrolliert unterschiedliche Kader für mehrere Personen.
---

# kicker Interactive Kader aufstellen

## Grundvertrag

- Ausschließlich die bereits angemeldete Chrome-Sitzung verwenden. Keine Passwörter, Cookies, Tokens oder Browser-Speicher lesen oder exportieren.
- Vor jeder Browsersteuerung den verfügbaren Chrome-Control-Skill vollständig laden und dessen Interaktions- und Finalisierungsregeln befolgen.
- Aktuelle Informationen zu Transfers, Verletzungen, Vorbereitung, Trainer und Rollen im Web verifizieren. Offizielle Vereins- und Ligaseiten bevorzugen.
- Keine Vorjahrespunkte als Prognose behandeln. Wiederholbarkeit, Rolle, Einsatzwahrscheinlichkeit, Umfeld und Preis getrennt bewerten.
- Nie „Alle verkaufen“ verwenden. Änderungen einzeln ausführen und nach jeder Phase Kadergröße, Positionen und Budget prüfen.

## Python-Laufzeit unter macOS und Windows

- Vor dem ersten Skriptlauf die von Codex Desktop bereitgestellten Workspace-Abhängigkeiten laden und den dort ausgewiesenen absoluten Pfad zum Python-Executable verwenden.
- Ist keine gebündelte Laufzeit verfügbar, selbstständig einen Python-3-Befehl ermitteln: unter macOS/Linux nacheinander `python3` und `python`, unter Windows nacheinander `py -3`, `python3` und `python` prüfen.
- Nur eine Laufzeit ab Python 3.9 verwenden. Dies mit `<python-3-command> -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)"` verifizieren.
- Den ermittelten `<python-3-command>` für alle folgenden Aufrufe wiederverwenden. Absolute Pfade mit Leerzeichen als ein Argument behandeln; in PowerShell für einen absoluten Executable-Pfad den Aufrufoperator `&` verwenden.
- Den Nutzer erst dann um eine Python-Installation bitten, wenn weder die gebündelte Codex-Laufzeit noch einer der plattformspezifischen Befehle funktioniert.

## Parameter auflösen

Diese drei Parameter aus der Anfrage übernehmen. Fehlende Werte auf die angegebenen Defaults setzen und knapp nennen, statt den Ablauf unnötig zu blockieren.

1. Strategie:
   - `verlässlich` (Default): bestätigte, wiederholbare Leistung und sichere Minuten
   - `ausgewogen`: Floor und Potenzial ausgewogen kombinieren
   - `ausbruch`: unterbewertete Talente, Neustarts und Rollengewinner stärker gewichten
2. Variabilität:
   - `niedrig`: kleiner Abstand zum mathematisch besten Kader
   - `mittel` (Default): mehrere Plätze aus einem nahezu gleichwertigen Kandidatenband variieren
   - `hoch`: deutlich individuellere Kader bei weiterhin begrenztem Qualitätsabschlag
3. Betreuungsaufwand:
   - `gering` (Default): robuste Stammspieler, belastbare Bank und wenig Wechselbedarf
   - `normal`: moderate Rollenrisiken zulassen
   - `aktiv`: mehr frühe Wetten zulassen, wenn der Nutzer regelmäßig nachsteuert

Für exakte Gewichtungen und Qualitätsgrenzen [references/strategy-profiles.md](references/strategy-profiles.md) vollständig lesen.

## Arbeitsmodus bestimmen

- „Stelle auf“, „optimiere“, „ändere“ oder gleichwertige Formulierungen autorisieren die inkrementelle Umsetzung im Kicker-Kader.
- „Vorschlag“, „Liste“, „bewerte“ oder „was hältst du“ bleiben zunächst read-only.
- Bei mehreren Wettbewerben jeden Kader getrennt analysieren und verifizieren.
- Bei fehlender Anmeldung den Nutzer auffordern, sich in Chrome bei kicker anzumelden und anschließend Bescheid zu geben. Nicht auf einen anderen Browser ausweichen.

## Workflow

### 1. Ist-Zustand erfassen

- Wettbewerb, Saison-ID, Budget, Positionsvorgaben, aktuellen Kader und offene Plätze aus der sichtbaren Kicker-Seite erfassen.
- Den Link „Spieler-Daten Export“ der aktuellen Saison verwenden und die CSV als maßgeblichen Preis-/Positionsbestand behandeln.
- Standardmäßig alle Torhüter aus demselben Verein wählen. Nur auf ausdrücklichen Wunsch mit `--mixed-goalkeepers` abweichen.
- Weichen die sichtbaren Positionsvorgaben von 3/7/7/5 ab, dem Skript die tatsächlichen Werte über `--goalkeepers`, `--defenders`, `--midfielders` und `--forwards` übergeben.

### 2. Kandidatenpool bilden

- Zuerst einen breiten Recherchepool erzeugen:

```text
<python-3-command> scripts/optimize_squad.py --players <players-csv-path> --profile reliable --budget 10000000 --shortlist-only
```

- Je Position etablierte Kandidaten, Neuzugänge, höherklassig erprobte Spieler, Jugendtalente und Rebound-Kandidaten aufnehmen.
- Mindestens die realistischen Startelf- und Bankkandidaten prüfen; reine 0,05-/0,10-Füller nicht ohne belegbare Einsatzchance bevorzugen.
- Vor dem finalen Lauf mindestens doppelt so viele Torhüter wie Torwartplätze sowie je drei zusätzliche Feldspieler über der jeweiligen Sollzahl aktuell annotieren. Bei den üblichen 3/7/7/5 sind das 6/10/10/8. Im Standardmodus zwei vollständige Torwartblöcke abdecken.
- Vorjahresausreißer mit Regression, gegnerischer Anpassung und möglichem Rollenverlust belasten.
- Mehrjährige Konstanz, Standards, Kapitänsrolle und trainerbestätigte Schlüsselrollen als wiederholbare Signale aufwerten.
- Transfers als Rollenreset behandeln. Qualität des Spielers und Passung zum neuen Team getrennt von seiner alten Produktion bewerten.
- Transfer-, Rotations- und Verletzungsrisiken aktuell recherchieren. Unsicherheit offen markieren, nicht erfinden.

### 3. Kandidaten bewerten

- Alle hier genannten Skript- und Referenzpfade relativ zum Verzeichnis dieses `SKILL.md` auflösen.
- Komponenten und Risiken nach [references/annotation-schema.md](references/annotation-schema.md) erfassen.
- `scripts/optimize_squad.py` mit CSV, Profil, Variabilität, Betreuungsaufwand, Budget und Annotationen ausführen.
- Im finalen Lauf werden ausschließlich vollständig aktuell annotierte Spieler berücksichtigt.
- Einen finalen Kader nicht aus einem unannotierten Lauf ableiten. `--allow-unannotated` ausschließlich für technische Smoke-Tests verwenden und dessen Ergebnis nie als Empfehlung oder Browser-Zielkader präsentieren.
- Den ausgegebenen Seed festhalten. Derselbe Seed reproduziert denselben Kader; ein neuer Seed erzeugt eine kontrollierte Alternative.
- Wenn Kader anderer Kollegen als JSON vorliegen, diese mit `--avoid-roster` übergeben. Dadurch wird Überschneidung innerhalb des Qualitätskorridors zusätzlich reduziert.

Beispiel:

```text
<python-3-command> scripts/optimize_squad.py --players <players-csv-path> --annotations <annotations-json-path> --profile balanced --variation medium --maintenance low --budget 10000000 --goalkeepers 3 --defenders 7 --midfielders 7 --forwards 5 --format json
```

Die vier Positionsargumente immer mit den zuvor von der sichtbaren Kicker-Seite erfassten Werten belegen; die gezeigten Zahlen sind nur das übliche Beispiel.

### 4. Portfolio prüfen

- Kader nicht nur nach Summenscore beurteilen:
  - ausreichend wahrscheinliche Starter und belastbare Ersatzspieler
  - keine unnötige Häufung desselben Teamrisikos
  - wenige teure Spieler nur bei wiederholbarer Rolle
  - bei geringem Betreuungsaufwand keine Bank voller Projektspieler
  - Transfergefahr vor Saisonstart gesondert prüfen
- Variabilität nur innerhalb der in `strategy-profiles.md` festgelegten Qualitätsgrenze zulassen.
- Bleiben mehr als 10 Prozent des Budgets ungenutzt, den Kandidatenpool über mehrere Preisklassen erweitern und neu rechnen. Einen solchen Rohkader nicht direkt umsetzen.
- Abweichungen vom Optimierer begründen und Budget erneut berechnen.

### 5. In Chrome umsetzen

- Vor tatsächlichen Änderungen [references/browser-workflow.md](references/browser-workflow.md) vollständig lesen.
- Erst Verkäufe, dann Käufe einzeln und positionsweise durchführen.
- Vor jeder Aktion einen frischen DOM-Zustand erfassen, den Spielereintrag eindeutig über Name, Verein, Position und Preis abgrenzen und genau einen Treffer verlangen.
- Nach jeder Positionsgruppe sowie abschließend Kadergröße, Positionszahlen, Restbudget und alle Zielnamen verifizieren.
- Den bearbeiteten Kicker-Tab als sichtbares Ergebnis an den Nutzer übergeben.

## Ergebnis

Kompakt berichten:

1. gewähltes Profil, Variabilität, Betreuungsaufwand und Seed
2. Kadergröße und Restbudget
3. wichtigste Käufe/Verkäufe oder vollständiger Kader, wenn verlangt
4. drei bis fünf zentrale Begründungen
5. verbleibende Unsicherheiten wie offene Transfers oder Verletzungen
6. bei ausgeführter Änderung ausdrücklich bestätigen, dass der Kader in Chrome verifiziert wurde

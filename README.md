# kicker Interactive Manager für Codex

Dieses öffentliche Codex-Marketplace enthält den Skill `kicker-interactive-manager`. Er recherchiert, bewertet und optimiert Kader für das kicker Managerspiel Interactive in der Bundesliga, 2. Bundesliga oder 3. Liga und setzt gewünschte Änderungen über eine bereits angemeldete Chrome-Sitzung um. Die WM ist ausdrücklich ausgeschlossen.

## Installation

Du brauchst dafür weder Git noch Programmierkenntnisse. Codex muss lediglich bereits installiert sein.

### Windows

1. Öffne das Windows-Startmenü.
2. Suche nach **PowerShell** und öffne **Windows PowerShell**.
3. Kopiere die folgende Zeile vollständig, füge sie in das blaue Fenster ein und drücke **Enter**:

```powershell
$installer = "$env:TEMP\install-kicker-interactive-manager.ps1"; Invoke-WebRequest "https://raw.githubusercontent.com/geozocco/kicker-interactive-manager/382055f175089dfc4704300b1555842b732e52e2/install.ps1" -OutFile $installer; powershell -NoProfile -ExecutionPolicy Bypass -File $installer
```

4. Warte, bis sich Codex öffnet.
5. Klicke in Codex auf **Plugin installieren**.
6. Schließe Codex vollständig, öffne es erneut und starte einen neuen Task.

### macOS

1. Drücke **⌘ + Leertaste**, suche nach **Terminal** und öffne es.
2. Kopiere die folgende Zeile vollständig, füge sie in das Terminalfenster ein und drücke **Enter**:

```bash
INSTALLER="$(mktemp /tmp/install-kicker-interactive-manager.XXXXXX)"; curl -fsSL "https://raw.githubusercontent.com/geozocco/kicker-interactive-manager/e9d5a81b442dd48cfd54d93d007c59dee5e67f36/install-macos.sh" -o "$INSTALLER"; /bin/bash "$INSTALLER"; rm -f "$INSTALLER"
```

3. Warte, bis sich Codex öffnet.
4. Klicke in Codex auf **Plugin installieren**.
5. Schließe Codex vollständig, öffne es erneut und starte einen neuen Task.

Für beide Wege gilt: Es werden keine Administratorrechte, kein Git und keine Codex-Kommandozeile benötigt.

## Einmalig Chrome mit Codex verbinden

Das Plugin arbeitet direkt im sichtbaren Chrome-Browser. Deshalb muss Chrome einmalig mit Codex verbunden werden:

1. Öffne in Codex die Plugin-Übersicht und stelle sicher, dass das Plugin **Chrome** installiert und aktiviert ist.
2. Installiere im verwendeten Chrome-Profil die [ChatGPT Chrome Extension](https://chromewebstore.google.com/detail/codex/hehggadaopoacecdllhhajmbjkdcmajg).
3. Prüfe unter `chrome://extensions`, dass die **ChatGPT Chrome Extension** eingeschaltet ist.
4. Starte Chrome und Codex anschließend neu.

Wichtig: Verwende später dasselbe Chrome-Profil, in dem die Erweiterung installiert wurde.

## Das Plugin verwenden

1. Öffne Chrome.
2. Melde dich bei [kicker](https://www.kicker.de/) an.
3. Öffne das **Managerspiel Interactive** und dort den Kader, den du bearbeiten möchtest.
4. Lasse diesen Chrome-Tab geöffnet.
5. Öffne in Codex/ChatGPT einen neuen Task beziehungsweise Chat, in dem das Plugin installiert ist.
6. Beauftrage Codex/ChatGPT mit der Zusammenstellung. Nenne dabei immer ausdrücklich die gewünschte Liga.

Beispiel für die 2. Bundesliga:

> Stelle meinen Kader für die 2. Bundesliga im kicker Managerspiel Interactive zusammen. Wähle eine ausgewogene Mischung aus verlässlichen Spielern und Talenten und nutze meine geöffnete Chrome-Sitzung.

Beispiel für die 3. Liga:

> Stelle meinen Kader für die 3. Liga im kicker Managerspiel Interactive zusammen. Setze stärker auf Ausbruchspotenzial, halte die Bank aber ausreichend robust und nutze meine geöffnete Chrome-Sitzung.

Beispiel für die Bundesliga:

> Stelle meinen Kader für die Bundesliga im kicker Managerspiel Interactive verlässlich und wartungsarm zusammen und nutze meine geöffnete Chrome-Sitzung.

### Einen selbst zusammengestellten Kader prüfen

Du kannst deinen Kader weiterhin selbst zusammenstellen und anschließend read-only prüfen lassen:

> Bewerte meinen aktuell in Chrome geöffneten kicker-Interactive-Kader für die 2. Bundesliga. Prüfe insbesondere aktuelle Verletzungen, Transfers, Startelfchancen, Budgetverteilung und vermeidbare Risiken. Verändere den Kader nicht.

Ist nur ein eindeutig erkennbarer kicker-Interactive-Kadertab geöffnet, genügt auch:

> Bewerte meinen aktuell in Chrome geöffneten Kader und verändere nichts.

Codex liest den sichtbaren Kader, gleicht die Spieler mit den offiziellen Kicker-Daten ab und prüft aktuelle News. Das Ergebnis enthält:

- eine Gesamteinschätzung mit klarer Datenkonfidenz,
- Warnungen zu Verletzungen, Transfers und unsicheren Rollen,
- die Verteilung des Kaderwerts auf Startelf und Bank,
- verlässliche Ankerspieler und Vereinskonzentrationen sowie
- bei ausreichender Recherche bezahlbare Alternativen.

Eine grüne Bestätigung wird nur erteilt, wenn alle gewählten Spieler aktuell geprüft wurden und keine kritischen News-Lücken oder vermeidbaren hohen Risiken offen sind. Bei fehlenden oder widersprüchlichen Informationen nennt Codex stattdessen die notwendigen Nachprüfungen. Der Chrome-Kader bleibt bei dieser Funktion unverändert.

### Weitere Prompt-Varianten

Liga, Strategie, Variabilität und Betreuungsaufwand lassen sich frei kombinieren:

| Zweck | Beispiel |
|---|---|
| Geführter Einstieg | „Hilf mir bei der Kaderplanung und frage mich nach Liga, Strategie, Variabilität und Betreuungsaufwand.“ |
| Verlässlich | „Stelle meinen Kader für die 2. Bundesliga verlässlich und wartungsarm auf.“ |
| Ausgewogen | „Stelle meinen Kader für die 3. Liga ausgewogen und mit mittlerer Variabilität auf.“ |
| Ausbruch | „Stelle meinen Kader mit Fokus auf Ausbruchspotenzial auf. Ich möchte aktiv nachsteuern.“ |
| Read-only Bewertung | „Bewerte meinen geöffneten Kader, prüfe Verletzungen und Transfers und verändere nichts.“ |
| Nur Vorschläge | „Zeige mir die fünf wichtigsten Verbesserungen, aber setze noch nichts in Chrome um.“ |
| Optimieren und umsetzen | „Prüfe meinen Kader und setze nur klar begründete Verbesserungen in Chrome um.“ |
| Variantenvergleich | „Vergleiche einen verlässlichen und einen ausgewogenen Kader, ohne Chrome zu ändern.“ |
| Persönliche Variante | „Stelle mir einen verlässlichen Kader zusammen. Nutze automatisch meine persönliche, anonyme Variante.“ |
| Neu würfeln | „Erzeuge mir eine neue, nahezu gleichwertige Variante und erkläre die Unterschiede.“ |
| Spielercheck | „Prüfe, ob [Spielername] zu meinem Kader passt, und nenne bezahlbare Alternativen.“ |

Alternativ genügt:

> Zeige mir alle unterstützten Modi und passende Beispielprompts.

Der Bundesliga-Kader kann erst aufgestellt werden, wenn kicker den zugehörigen Transfermarkt für die neue Saison geöffnet hat. Bis dahin soll Codex keine andere Liga auswählen und keinen Kader erfinden. Die Weltmeisterschaft wird von diesem Plugin nicht unterstützt.

Codex/ChatGPT fragt bei Bedarf nach Spielklasse, Risikoprofil und gewünschtem Betreuungsaufwand. Anschließend wird der Spielermarkt analysiert und der Kader direkt im geöffneten Chrome-Tab zusammengestellt. Bestätige den Zugriff auf Chrome, falls du danach gefragt wirst. Lasse Chrome und den kicker-Tab geöffnet, bis der fertige Kader bestätigt wurde.

Bei **verlässlich und wartungsarm** konzentriert das Plugin das Budget auf einen starken Aufstellungskern mit mindestens vier bestätigten Leistungsträgern. Die Bank wird günstiger, aber mit realistischen Einsatzchancen besetzt. Im Ergebnis erklärt Codex die wichtigsten Spieler einzeln und vergleicht bewusst ausgelassene etablierte Alternativen samt Budget- und Risikogründen.

### Unterschiedliche Kader für mehrere Kollegen

Das Plugin erzeugt auf jedem Rechner automatisch eine eigene, anonyme Variante. Niemand muss eine Kadernummer oder einen Gruppenseed kennen:

> Stelle meinen Kader für die 2. Bundesliga verlässlich und wartungsarm zusammen.

Beim ersten Lauf legt das Plugin ausschließlich auf dem eigenen Rechner eine zufällige technische Kennung ab. Daraus werden zusammen mit Liga, Saison und Strategie kontrollierte Entscheidungen innerhalb des zulässigen Qualitätskorridors abgeleitet. Die Kennung enthält keine Namen, E-Mail-Adressen oder andere personenbezogene Daten, wird nicht hochgeladen und erscheint nicht im Ergebnis. Deshalb erhalten Kollegen normalerweise unterschiedliche Kader, ohne sich untereinander abzustimmen.

Wer auf demselben Rechner eine weitere Alternative sehen möchte, schreibt einfach:

> Erzeuge mir eine neue, nahezu gleichwertige Variante dieses Kaders.

Das Plugin würfelt dann kontrolliert neu und erklärt die Unterschiede. Bewährte Ausnahmespieler dürfen trotzdem in mehreren Kadern vorkommen; Varianz ist kein Selbstzweck und verdrängt keine klar bessere Wahl. Eine garantierte weltweite Einzigartigkeit gibt es ohne zentralen Kaderspeicher nicht, zufällige Überschneidungen bleiben also möglich. Ein namentlich erwähnter Spieler wird nur recherchiert und verglichen; er erhält dadurch keinen Bonus und wird nur auf ausdrücklichen Wunsch zwingend gekauft.

Wenn fünf Kader gemeinsam in einem Lauf erzeugt werden sollen, kann Codex ein **koordiniertes Gruppenportfolio** erstellen. Dabei wird ein breiter, ligaweiter Ankerpool verwendet und jeder verlässliche Anker standardmäßig höchstens einem Kader zugeteilt:

> Erzeuge fünf koordinierte, gleichwertige Kader für die 2. Bundesliga. Die Ankerkerne sollen sich nicht überschneiden. Verändere Chrome noch nicht.

Sind dafür nicht genügend gleichwertige und vollständig geprüfte Anker vorhanden, bricht das Plugin mit einer verständlichen Meldung ab und erweitert zuerst die Recherche. Es setzt dann nicht heimlich dieselben bekannten Namen in alle fünf Kader. Diese Garantie gilt für gemeinsam erzeugte Portfolios. Fünf völlig unabhängig gestartete Rechner kennen die Auswahl der anderen nicht; dafür wäre zusätzlich ein zentraler Belegungsdienst nötig. Eine zentral gespeicherte Preis- und Kandidatenliste beschleunigt die Recherche, ersetzt diese Koordination aber nicht.

Vor dem Umbau prüft das Plugin außerdem aktuelle Verletzungs- und Transfermeldungen. Für die 2. Bundesliga und 3. Liga der Saison 2026/27 verwendet das Plugin automatisch den zentralen API-Sports-Feed dieses Projekts. Dafür müssen Kollegen weder einen API-Key noch eine Feed-Adresse einrichten. Der Feed wird viermal täglich aktualisiert und enthält nur normalisierte Spieler-, Verletzungs- und Transferdaten; der geheime Provider-Schlüssel bleibt im geschützten GitHub-Secret-Speicher.

Auch die offiziellen Kicker-Spielerlisten und Preise werden für beide Ligen viermal täglich zentral aktualisiert. Dadurch laden alle Installationen denselben geprüften Marktstand, statt die CSV auf jedem Rechner erneut im Browser zu öffnen. Das Snapshot enthält Kicker-ID, Name, Verein, Position, Marktwert und die von Kicker bereitgestellten Leistungswerte. Es enthält keine Kollegenkader, persönlichen Präferenzen oder lokalen Variantenkennungen.

Zusätzlich wird für jeden aktuell auswählbaren Kicker-Spieler eine zentrale Transfermarkt-Historie aus Einsätzen, Starts, Minuten, Toren und Vorlagen über bis zu acht Spielzeiten aufgebaut. Jede Saison behält ihre damalige Liga: Eine Leistung in der Bundesliga wiegt höher als in der 2. Bundesliga, diese wiederum höher als in der 3. Liga. Eine starke unterklassige Saison bleibt ein interessantes Potenzialsignal, wird aber nicht als bereits bestätigte Leistung auf höherem Niveau ausgegeben. Nicht eindeutig zuordenbare Spieler oder unbekannte Wettbewerbe werden sichtbar markiert und nicht mit erfundenen Annahmen bewertet. Da Transfermarkt GitHub-Runner zeitweise blockiert, liegt zusätzlich ein kompakter, lokal geprüfter Performance-Stand im Repository. Der zentrale Lauf versucht einen Live-Refresh und fällt sonst nachvollziehbar auf diesen Datenstand zurück; aktuelle Kicker-, News- und API-Sports-Daten werden weiterhin viermal täglich erneuert.

Die eigentliche Bewertung und Kaderauswahl bleibt lokal. Deshalb können unterschiedliche Profile und persönliche Varianten weiterhin zu unterschiedlichen Mannschaften führen. Der zentrale Marktbestand ist eine gemeinsame Faktengrundlage und kein vorgegebener Ankerkern.

Veraltete Daten, falsche Liga- oder Saisonangaben, fehlende Spielerzuordnungen und widersprüchliche Meldungen stoppen den automatischen Umbau, bis Codex die betroffenen Spieler in aktuellen Primärquellen geprüft hat. API-Sports ist ein zusätzlicher Frühwarnkanal und ersetzt diese gezielte Gegenprüfung nicht. Für normale Nutzer ändert sich am oben beschriebenen Ablauf nichts.

Der technische Betrieb und die Feed-Endpunkte sind in den Plugin-Referenzen `references/market-data.md` und `references/news-hardening.md` dokumentiert. Zusätzlich zu Markt, Transfermarkt-Historie und News wird zentral ein breiter Qualitätsbestand gepflegt: mindestens 60 vollständig bewertete Kandidaten, 20 verlässliche Anker, 15 offensive Anker und sechs vollständige Torwartblöcke je Liga. Die Bewertung nutzt mehrere ligakontextualisierte Spielzeiten und aktuelle Rollen-, Fitness- und Transfersignale; Namen aus Beispielprompts werden nicht bevorzugt. Provider-Zugangsdaten werden nie an Kollegen verteilt.

Falls Codex nicht auf Chrome zugreifen kann, prüfe zuerst, ob:

- Google Chrome geöffnet ist,
- die ChatGPT Chrome Extension im richtigen Chrome-Profil aktiviert ist,
- das Chrome-Plugin in Codex aktiviert ist und
- du in diesem Chrome-Profil bei kicker angemeldet bist.

## Alternative Installation für technisch erfahrene Nutzer

### macOS

```bash
git clone https://github.com/geozocco/kicker-interactive-manager.git "$HOME/kicker-interactive-manager"
codex plugin marketplace add "$HOME/kicker-interactive-manager"
codex plugin add kicker-interactive-manager@kicker-interactive-manager
```

### Windows

```powershell
git clone https://github.com/geozocco/kicker-interactive-manager.git "$HOME\kicker-interactive-manager"
codex plugin marketplace add "$HOME\kicker-interactive-manager"
codex plugin add kicker-interactive-manager@kicker-interactive-manager
```

## Aktualisierung

Führe einfach dieselben Installationsschritte noch einmal aus. Die bisherige Version wird automatisch als Sicherung aufgehoben.

Wer die alternative Git-Installation verwendet hat, führt stattdessen im geklonten Verzeichnis `git pull` aus und aktualisiert das Plugin in Codex über **Refresh**.

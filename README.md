# kicker Interactive Manager für Codex

Dieses öffentliche Codex-Marketplace enthält den Skill `kicker-interactive-manager`. Er recherchiert und optimiert Kader für das kicker Managerspiel Interactive in der Bundesliga, 2. Bundesliga oder 3. Liga und setzt sie über eine bereits angemeldete Chrome-Sitzung um. Die WM ist ausdrücklich ausgeschlossen.

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

Der Bundesliga-Kader kann erst aufgestellt werden, wenn kicker den zugehörigen Transfermarkt für die neue Saison geöffnet hat. Bis dahin soll Codex keine andere Liga auswählen und keinen Kader erfinden. Die Weltmeisterschaft wird von diesem Plugin nicht unterstützt.

Codex/ChatGPT fragt bei Bedarf nach Spielklasse, Risikoprofil und gewünschtem Betreuungsaufwand. Anschließend wird der Spielermarkt analysiert und der Kader direkt im geöffneten Chrome-Tab zusammengestellt. Bestätige den Zugriff auf Chrome, falls du danach gefragt wirst. Lasse Chrome und den kicker-Tab geöffnet, bis der fertige Kader bestätigt wurde.

Bei **verlässlich und wartungsarm** konzentriert das Plugin das Budget auf einen starken Aufstellungskern mit mindestens drei bestätigten Leistungsträgern. Die Bank wird günstiger, aber mit realistischen Einsatzchancen besetzt. Im Ergebnis erklärt Codex die wichtigsten Spieler einzeln und vergleicht bewusst ausgelassene etablierte Alternativen samt Budget- und Risikogründen.

Vor dem Umbau prüft das Plugin außerdem aktuelle Verletzungs- und Transfermeldungen. Wenn euer Team einen zentralen News-Feed eingerichtet hat, werden SportsMonks und API-Sports automatisch als zusätzlicher Frühwarnkanal verwendet. Veraltete Daten, falsche Liga- oder Saisonangaben, fehlende Spielerzuordnungen und widersprüchliche Meldungen stoppen den automatischen Umbau, bis Codex die betroffenen Spieler in aktuellen Quellen geprüft hat. Ohne zentralen Feed recherchiert Codex diese Informationen weiterhin individuell im Web.

Die Provider-Zugangsdaten werden nur auf dem zentralen Aktualisierungsrechner benötigt und nie an Kollegen verteilt. Die technische Einrichtung für den Team-Administrator steht in der Plugin-Referenz `references/news-hardening.md`; für normale Nutzer ändert sich am oben beschriebenen Ablauf nichts.

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

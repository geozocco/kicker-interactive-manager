# kicker Interactive Manager für Codex

Dieses öffentliche Codex-Marketplace enthält den Skill `kicker-interactive-manager`. Er recherchiert und optimiert Kader für das kicker Managerspiel Interactive und setzt sie über eine bereits angemeldete Chrome-Sitzung um.

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

## Kader erstellen

1. Melde dich in Chrome bei kicker an und öffne das Managerspiel Interactive.
2. Öffne in Codex einen neuen Task.
3. Schreibe zum Beispiel:

> Stelle meinen kicker-Interactive-Kader verlässlich, wartungsarm und mit mittlerer Variabilität auf.

Codex fragt bei Bedarf nach Spielklasse und Risikoprofil und stellt den Kader anschließend über die bereits angemeldete Chrome-Sitzung zusammen.

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

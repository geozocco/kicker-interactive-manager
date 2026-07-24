# kicker Interactive Manager für Codex

Dieses öffentliche Codex-Marketplace enthält den Skill `kicker-interactive-manager`. Er recherchiert und optimiert Kader für das kicker Managerspiel Interactive und setzt sie über eine bereits angemeldete Chrome-Sitzung um.

## Installation auf einem frischen Windows-Rechner

Git und das Codex-CLI werden nicht benötigt. Diese Zeile vollständig in PowerShell einfügen:

```powershell
$installer = "$env:TEMP\install-kicker-interactive-manager.ps1"; Invoke-WebRequest "https://raw.githubusercontent.com/geozocco/kicker-interactive-manager/main/install.ps1" -OutFile $installer; powershell -NoProfile -ExecutionPolicy Bypass -File $installer
```

Der Installer:

1. lädt das öffentliche Marketplace mit Windows-Bordmitteln herunter,
2. installiert es ohne Administratorrechte im Benutzerprofil,
3. öffnet den lokalen Installationsdialog in Codex.

In Codex anschließend auf **Plugin installieren** klicken, Codex neu starten und einen neuen Task öffnen.

## Installation unter macOS mit Git und Codex-CLI

```bash
git clone https://github.com/geozocco/kicker-interactive-manager.git "$HOME/kicker-interactive-manager"
codex plugin marketplace add "$HOME/kicker-interactive-manager"
codex plugin add kicker-interactive-manager@kicker-interactive-manager
```

## Alternative Windows-Installation mit Git und Codex-CLI

```powershell
git clone https://github.com/geozocco/kicker-interactive-manager.git "$HOME\kicker-interactive-manager"
codex plugin marketplace add "$HOME\kicker-interactive-manager"
codex plugin add kicker-interactive-manager@kicker-interactive-manager
```

Anschließend Codex neu starten und einen neuen Task öffnen. In Chrome bei kicker anmelden und beispielsweise schreiben:

> Stelle meinen kicker-Interactive-Kader verlässlich, wartungsarm und mit mittlerer Variabilität auf.

## Aktualisierung

Auf Windows den PowerShell-Installer erneut ausführen. Die vorherige Version wird dabei als Backup erhalten. Bei einer Git-Installation im geklonten Verzeichnis `git pull` ausführen und das Plugin in Codex über **Refresh** aktualisieren.

Der Marketplace wird auf jedem Rechner lokal importiert. Er enthält deshalb keinen absoluten macOS- oder Windows-Pfad und kann zwischen den Betriebssystemen geteilt werden.

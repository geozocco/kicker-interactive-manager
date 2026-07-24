# kicker Interactive Manager für Codex

Dieses öffentliche Codex-Marketplace enthält den Skill `kicker-interactive-manager`. Er recherchiert und optimiert Kader für das kicker Managerspiel Interactive und setzt sie über eine bereits angemeldete Chrome-Sitzung um.

## Installation unter macOS

```bash
git clone https://github.com/geozocco/kicker-interactive-manager.git "$HOME/kicker-interactive-manager"
codex plugin marketplace add "$HOME/kicker-interactive-manager"
codex plugin add kicker-interactive-manager@kicker-interactive-manager
```

## Installation unter Windows

```powershell
git clone https://github.com/geozocco/kicker-interactive-manager.git "$HOME\kicker-interactive-manager"
codex plugin marketplace add "$HOME\kicker-interactive-manager"
codex plugin add kicker-interactive-manager@kicker-interactive-manager
```

Anschließend Codex neu starten und einen neuen Task öffnen. In Chrome bei kicker anmelden und beispielsweise schreiben:

> Stelle meinen kicker-Interactive-Kader verlässlich, wartungsarm und mit mittlerer Variabilität auf.

## Aktualisierung

Im geklonten Verzeichnis `git pull` ausführen und das Plugin in Codex über **Refresh** aktualisieren. Alternativ den letzten `codex plugin add`-Befehl erneut ausführen.

Der Marketplace wird auf jedem Rechner lokal importiert. Er enthält deshalb keinen absoluten macOS- oder Windows-Pfad und kann zwischen den Betriebssystemen geteilt werden.

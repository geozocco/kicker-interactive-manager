# Chrome-Workflow für kicker Interactive

## Voraussetzungen

- Den offiziellen Chrome-Control-Skill verwenden und dessen vollständige Dokumentation vor der ersten Interaktion lesen.
- Nur die bereits angemeldete Chrome-Sitzung verwenden.
- Keine Zugangsdaten, Cookies, Tokens, Local Storage oder Session Storage untersuchen.
- Bei nicht angemeldetem Zustand den Nutzer um Anmeldung bitten und pausieren.

## Lesen

1. Passenden offenen kicker-Tab ermitteln oder einen Agent-Tab zur angegebenen Kicker-URL öffnen.
2. Nach Navigation kurz auf das Laden der angemeldeten Anwendung warten.
3. DOM-Snapshot erfassen.
4. Wettbewerb, Saison-ID, Kaderzahl, Budget, Positionszahlen und aktuellen Kader aus sichtbaren Elementen lesen.
5. Den zentralen Marktbestand für die sichtbare Liga und Saison verwenden. Den Link „Spieler-Daten Export“ nur beim dokumentierten manuellen Fallback verwenden. Keine private API aus Browserzuständen rekonstruieren.

## Read-only-Bewertung

- Bei „Bewerte meinen Kader“, „prüfe meinen Kader“ oder vergleichbaren Formulierungen ausschließlich lesen.
- Jeden sichtbaren Spieler mit Name, Verein, Position und Preis erfassen und anschließend gegen den zentralen Marktbestand auflösen.
- Keine Verkaufs-, Kauf-, Aufstellungs- oder Bestätigungsbuttons betätigen.
- Den Zustand nach der Erfassung erneut lesen und Spielerzahl, Positionen sowie Budget gegen die Bewertungsdatei prüfen.
- Das Ergebnis nach `squad-evaluation.md` liefern. Erst eine spätere ausdrückliche Änderungsanweisung wechselt in den Schreibmodus.

## Schreiben

Eine ausdrückliche Aufforderung wie „stelle auf“, „optimiere“ oder „ändere meinen Kader“ autorisiert die dafür notwendigen Kaderänderungen.

1. Zielkader vor dem ersten Klick vollständig berechnen.
2. Unmittelbar davor Markt- und News-Gate erneut prüfen: beide Snapshots frisch, richtige Liga und Saison, vollständige Zuordnung aller Zielspieler, keine offenen Konflikte.
3. Zu verkaufende Spieler einzeln über den Kaderbereich lokalisieren.
4. Vor jedem Klick:
   - frischen DOM-Snapshot erfassen
   - Spieler anhand Name, Verein, Position und Preis prüfen
   - Locator auf genau einen Treffer begrenzen
5. Verkauf ausführen und aktualisierten Zustand abwarten.
6. Kaufkandidaten über das sichtbare Suchfeld suchen. Nachname verwenden, wenn die Vollnamensuche keinen Treffer liefert.
7. Marktkarte anhand vollständigem Namen, Verein, Position und Preis prüfen.
8. Kauf nur bei genau einem passenden Treffer ausführen.
9. Nach jeder Positionsgruppe Kaderzahl und Budget kontrollieren.

Nie verwenden:

- „Alle verkaufen“
- ungezielte Klicks auf den n-ten gleichnamigen Preisbutton
- Browser-Speicher oder Cookies zur Authentifizierung
- eine andere Browseroberfläche ohne Zustimmung, wenn Chrome verlangt wurde

## Fehlerbehandlung

- Bei uneindeutigem Spieler nicht klicken; Suchbegriff verfeinern.
- Bei abweichendem Preis oder Position den Datensatz aktualisieren und neu optimieren.
- Bei einem fehlgeschlagenen Teilumbau den bereits erreichten Zustand lesen, Restbudget neu berechnen und nur die fehlenden Schritte reparieren.
- Keine Wiederholungsschleifen ohne frische Zustandsprüfung.

## Abschluss

1. Vollständigen Kader im Seitenbereich erneut lesen.
2. Exakte Positionszahlen, Gesamtzahl und Restbudget verifizieren.
3. Zielkäufe als vorhanden und Zielverkäufe als nicht vorhanden prüfen.
4. Den bearbeiteten Kicker-Tab gemäß Chrome-Control-Dokumentation als `deliverable` finalisieren.
5. Im Ergebnis keine erfolgreiche Änderung behaupten, wenn eine der Prüfungen fehlt.

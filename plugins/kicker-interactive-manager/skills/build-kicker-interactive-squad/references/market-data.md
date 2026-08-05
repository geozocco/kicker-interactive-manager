# Zentraler Marktbestand

## Zweck und Grenze

Für Bundesliga, 2. Bundesliga und 3. Liga 2026/27 je einen gemeinsamen, nur lesbaren Marktbestand, einen getrennten Transfermarkt-Historienbestand und einen Qualitätsbestand verwenden. Der Markt enthält ausschließlich öffentliche Kicker-Fakten. Die Historie enthält normalisierte öffentliche Transfermarkt-Einsatzdaten. Der Qualitätsbestand enthält breit recherchierte, reproduzierbare Mehrjahres-, Rollen-, Fitness- und Transfereinschätzungen. Persönliche Präferenzen, lokale Variantenkennungen, Kollegenkader und Kaderbelegungen niemals zentral speichern.

Der gemeinsame Marktbestand beschleunigt und vereinheitlicht die Recherche. Er garantiert keine kollisionsfreien Kader bei unabhängig gestarteten Kollegen. Überschneidungsfreie Ankerkerne nur über ein gemeinsam erzeugtes Gruppenportfolio koordinieren.

## Feste Wettbewerbsbudgets

Die Kicker-Gesamtbudgets sind Teil des Wettbewerbsvertrags:

- Bundesliga: `42.500.000`
- 2. Bundesliga: `10.000.000`
- 3. Liga: `6.000.000`

Das Budget nicht aus dem Marktwertniveau ableiten und niemals zwischen Ligen übernehmen. Optimierer und Kaderbewertung müssen bei einem abweichenden expliziten Budget abbrechen. Für technische Fixtures ist nur der ausdrücklich markierte Test-Override zulässig.

## Öffentliche Endpunkte

```text
https://geozocco.github.io/kicker-interactive-manager/v1/market/bundesliga.json
https://geozocco.github.io/kicker-interactive-manager/v1/market/2-bundesliga.json
https://geozocco.github.io/kicker-interactive-manager/v1/market/3-liga.json
https://geozocco.github.io/kicker-interactive-manager/v1/quality/bundesliga.json
https://geozocco.github.io/kicker-interactive-manager/v1/quality/2-bundesliga.json
https://geozocco.github.io/kicker-interactive-manager/v1/quality/3-liga.json
https://geozocco.github.io/kicker-interactive-manager/v1/history/bundesliga.json
https://geozocco.github.io/kicker-interactive-manager/v1/history/2-bundesliga.json
https://geozocco.github.io/kicker-interactive-manager/v1/history/3-liga.json
https://geozocco.github.io/kicker-interactive-manager/v1/kicker-history/bundesliga.json
https://geozocco.github.io/kicker-interactive-manager/v1/kicker-history/2-bundesliga.json
https://geozocco.github.io/kicker-interactive-manager/v1/kicker-history/3-liga.json
https://geozocco.github.io/kicker-interactive-manager/v1/preseason/bundesliga.json
https://geozocco.github.io/kicker-interactive-manager/v1/preseason/2-bundesliga.json
https://geozocco.github.io/kicker-interactive-manager/v1/preseason/3-liga.json
```

Bereits validierte API-Sports-Spielerhistorien werden aus dem vorherigen Qualitätsbestand übernommen, sofern Kicker-ID, Provider-Zuordnung, Liga, Saison und Historienjahr übereinstimmen. Nur fehlende Jahre oder neue Spieler lösen neue Providerabrufe aus. Ist ausschließlich das API-Sports-Tageskontingent erschöpft, darf der Lauf einen noch frischen validierten News- oder Vorbereitungsbestand unverändert weiterverwenden. Er verlängert dessen Ablaufzeit nicht; andere Fehler oder ein bereits abgelaufener Bestand bleiben blockierend.

Der Workflow `.github/workflows/update-news-feed.yml` aktualisiert Markt-, News-, Vorbereitungs-, Kicker-Zeitreihen- und Qualitäts-Snapshots viermal täglich. Transfermarkt-Kaderzuordnungen werden dabei gegen den aktuellen Markt erneuert; teure Performance-Abrufe werden normalerweise sechs Tage wiederverwendet und anschließend zentral aktualisiert. Blockiert Transfermarkt einen GitHub-Runner, verwendet der Lauf die versionierte, zuvor eindeutig geprüfte Identitätsliste unter `config/history/identities/` sowie den komprimierten Performance-Stand unter `config/history/performance/`. Er markiert neue, noch nicht enthaltene Spieler als nicht zugeordnet und rät keine Identitäten oder Leistungen. Ein Probeabruf erkennt automatisch, wenn ein Live-Refresh wieder möglich ist. Die Qualitätskonfigurationen unter `config/quality/` verlangen je Liga mindestens 60 vollständig bewertete Kandidaten, 20 verlässliche Anker, 15 offensive Anker, sechs hierarchisch stabile vollständige Torwartblöcke und mindestens 75 Prozent aufgelöste Transfermarkt-Historien. Für Torhüter wird nicht auf die Positionsquote gekürzt: Alle providerzugeordneten Keeper des aktuellen Kicker-Markts werden vereinsweise bewertet, damit auch ein vierter Konkurrent oder ein noch nicht im Kicker-Markt gelisteter Provider-Neuzugang die Hierarchie verändern kann. Spieler werden ansonsten algorithmisch aus dem gesamten Markt ausgewählt; namentliche Beispiele oder frühere Nutzerprompts erhalten keinen Bonus.

Jeder Kicker-Spieler steht im Historienbestand. Die Zuordnung trägt ausdrücklich `verified`, `probable`, `unmatched` oder `ambiguous`. Nur `verified` und vorsichtiger gewichtete `probable`-Zuordnungen wirken auf den Score. Unklare Identitäten und technisch nicht klassifizierte Wettbewerbe werden nicht negativ interpretiert und erhalten keinen erfundenen Leistungsfaktor.

Die Wettbewerbsfaktoren unter `config/history/competition-strength.json` verwenden die Bundesliga als Referenz `1,00`, die 2. Bundesliga mit `0,80` und die 3. Liga mit `0,64`. Die österreichische Bundesliga und die Schweizer Super League stehen ebenfalls bei `0,64`: Für die 3. Liga sind sie vergleichbar, für die 2. Bundesliga bleiben sie ein wertvolles, aber unterklassiges Seniorensignal. Eine Spielzeit gilt nur dann als bestätigt, wenn genügend Ligaminuten auf vergleichbarem oder höherem Niveau vorliegen.

Jugendwettbewerbe aus Deutschland und dem Ausland werden separat nach Nachwuchsniveau gewichtet. Zusätzlich kombiniert ein altersbereinigter `talent_score` Einsätze in U15- bis U21-Nationalmannschaften, Minuten in starken Nachwuchswettbewerben und frühe Ligaminuten im Herrenbereich. Regelmäßige Herrenminuten bis 18 gelten als sehr starkes Reifesignal; 19/20 bilden das normale Durchbruchsfenster. Die Berechnung ist positionsneutral und benachteiligt Torhüter nicht wegen fehlender Tore oder Vorlagen. Ein ungewöhnlich hoher Kicker-Preis wirkt bei höchstens 21-Jährigen nur dann begrenzt bestätigend, wenn dieser unabhängige Talentpfad bereits stark ist. Jugend- und Talentsignale erzeugen weder bestätigte Seniorenspielzeiten noch einen verlässlichen Anker. Pokal und Freundschaft bleiben ohne historischen Score. Die veröffentlichten Daten enthalten nur verdichtete Fakten und Quellenlinks, keine vollständigen Transfermarkt-Seiten.

Beim Ligawechsel wird die bekannte Transfermarkt-Spieleridentität aus den zentralen Katalogen der anderen unterstützten Liga mitgeführt. Eine global eindeutige exakte Namensidentität darf trotz altem Vereinsnamen als `probable` übernommen werden; mehrdeutige Namen bleiben ungelöst. Dadurch verlieren Aufsteiger und Leihspieler ihre historische Laufbahn nicht, während ein Vereinswechsel weiterhin als eigenständiger Rollenwechsel behandelt wird.

Der Vorbereitungsbestand kombiniert erfasste API-Sports-Testspiele mit strukturierten offiziellen Vereinsbelegen. Wiederholte Einsätze, Starts, Formationsrolle, Training, Gegnerniveau und Trainerhinweise bilden ein zeitlich verfallendes Bereitschaftssignal. Es wirkt bei jungen oder historisch wenig belegten Spielern stärker, bleibt aber auf 25 Prozent begrenzt und erzeugt niemals bestätigte Seniorleistung oder Ankerstatus.

Der Qualitätsbestand führt zusätzlich einen belegpflichtigen `role_context`. Er trennt einen ungeklärten Rollenreset von einer bestätigten, erweiterten oder reduzierten Rolle beim aktuellen Verein und erfasst Startwahrscheinlichkeit, Mannschaftsstärke sowie Elfmeter-, Freistoß-, Ecken-, Spielmacher-, Fokus-, Kapitäns- und Standardziel-Verantwortung. Historische Aufgaben werden nach einem Wechsel nur mit aktueller spielerbezogener Evidenz übertragen. Dadurch ist ein Transfer weder automatisch positiv noch negativ.

Kann die API-Historie den letzten Verein nicht liefern, gilt ein im Newsbestand
bestätigter Zugang zum aktuellen Kicker-Verein trotzdem als erkannter
Vereinswechsel. Wiederholte aktuelle offizielle Starts in der ersten Formation
können dann gemeinsam mit starker historischer Start- und Scorerstruktur eine
vorsichtige Rollenfortsetzung bestätigen. Reine Provider-Aufstellungen oder
ein einzelner Vorbereitungsscorrer reichen dafür nicht.

Der Kicker-Zeitreihenbestand speichert pro Tag höchstens eine Beobachtung je Spieler. Er baut ab der ersten Veröffentlichung fortlaufend Preis-, Punkte- und Notenverläufe auf; historische Werte vor diesem Startdatum werden nicht erfunden. Mindestens zwei zeitlich getrennte Beobachtungen sind nötig, bevor daraus ein begrenztes Formsignal entsteht. API-Sports ergänzt die Bewertung positionsabhängig um wiederholbare Ereignisse wie Startelfquote, Schüsse aufs Tor, Key Passes, Duelle, Defensivaktionen und Saves. Die API-Sports-Note bleibt ein kleines Hilfssignal und wird nicht als Kicker-Note behandelt.

## Sicherheitsvertrag

Das Snapshot nur verwenden, wenn:

- HTTPS, Prüfsumme und Schema gültig sind,
- Erzeugungs- und Ablaufzeit plausibel sind,
- Wettbewerb und Saison zur sichtbaren Kicker-Seite passen,
- jede Spieler-ID eindeutig ist,
- Position und positiver Marktwert gültig sind,
- die Anzahl unterschiedlicher Vereine exakt zur Konfiguration passt.
- der Historienbestand jeden Spieler des aktuellen Markts mit einem expliziten Zuordnungsstatus enthält,
- der Qualitätsbestand exakt zur Prüfsumme des aktuellen Markt-, News-, Vorbereitungs-, Transfermarkt-Historien- und Kicker-Zeitreihenbestands gehört,
- alle acht Qualitätskomponenten und fünf Risiken vollständig sind,
- die ligaweiten Mindestzahlen für Kandidaten und Anker erreicht werden.

Bei einem Verstoß nicht mit einem teilweise geladenen Pool weiterrechnen.

## Verwendung

Für unterstützte Ligen lädt der Optimierer den Marktfeed anhand von Wettbewerb und Saison automatisch, wenn `--players` fehlt. Bei einem finalen Lauf zusätzlich `--require-market-snapshot` setzen:

```text
<python-3-command> scripts/optimize_squad.py --competition "2. Bundesliga" --season "2026/27" --require-market-snapshot --require-quality-snapshot ...
```

`market_audit` muss frisch sein. `quality_audit` muss mindestens 60 Kandidaten, 20 Anker, 15 offensive Anker, sechs Torwartblöcke und die geforderte Transfermarkt-Abdeckung ausweisen sowie dieselben Markt-, News-, Vorbereitungs-, Transfermarkt-Historien- und Kicker-Zeitreihen-Prüfsummen tragen.

Der Qualitätsbestand liefert die zentralen Annotationen. Auf dem jeweiligen Rechner recherchierte Annotationen dürfen sie gezielt überschreiben; Kicker-ID, Verein, Position und Preis stammen weiterhin aus dem validierten Marktbestand.

## Manueller Fallback

Ist der zentrale Marktfeed nicht erreichbar oder abgelaufen:

1. Den zentralen Workflow einmal reparieren beziehungsweise neu ausführen.
2. Nur wenn das nicht rechtzeitig möglich ist, die aktuelle offizielle Kicker-CSV lokal speichern und mit `--players` verwenden.
3. Wettbewerb, Saison, Vereinszahl, Zeitpunkt und Quell-URL offen dokumentieren.
4. Den lokalen Lauf nicht als zentral geprüft ausweisen und fehlende Qualitätsmerkmale manuell vollständig belegen.

Die offizielle CSV nicht in einem sichtbaren Chrome-Tab öffnen, wenn sie im Hintergrund sicher geladen oder als Snapshot verwendet werden kann.

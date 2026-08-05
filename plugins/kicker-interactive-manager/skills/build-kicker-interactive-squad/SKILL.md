---
name: build-kicker-interactive-squad
description: Plane, optimiere, bewerte und ändere Kader im kicker Managerspiel Interactive über eine bereits angemeldete Chrome-Sitzung. Verwende diesen Skill bei Anfragen zu kicker Interactive, automatischer Kaderzusammenstellung, „bewerte/prüfe meinen Kader“, Verletzungs- oder Transferchecks, Mannschaftsoptimierung, Geheimtipps oder Strategieprofilen für Bundesliga, 2. Bundesliga und 3. Liga. Die WM ist ausdrücklich ausgeschlossen. Unterstützt read-only Kader-Audits, konservative, ausgewogene und ausbruchsorientierte Auswahl sowie kontrolliert unterschiedliche Kader für mehrere Personen.
---

# kicker Interactive Kader aufstellen und bewerten

## Grundvertrag

- Ausschließlich die bereits angemeldete Chrome-Sitzung verwenden. Keine Passwörter, Cookies, Tokens oder Browser-Speicher lesen oder exportieren.
- Vor jeder Browsersteuerung den verfügbaren Chrome-Control-Skill vollständig laden und dessen Interaktions- und Finalisierungsregeln befolgen.
- Aktuelle Informationen zu Transfers, Verletzungen, Vorbereitung, Trainer und Rollen im Web verifizieren. Offizielle Vereins- und Ligaseiten bevorzugen. Den zentralen redaktionellen Transfer-Watcher für Transfermarkt-, kicker-, Sky-, Vereins- und Zielvereinsmeldungen auswerten: Gerüchte nie automatisch ausschließen, fortgeschrittene Meldungen kurzfristig primär prüfen und bestätigte Abgänge sofort berücksichtigen.
- Für die 2. Bundesliga und 3. Liga 2026/27 die im Optimierer hinterlegten zentralen Markt-, Transfermarkt-Historien-, Vorbereitungs-, Qualitäts- und News-Feeds als erstes maschinenlesbares Gate verwenden. Der Qualitätsbestand ist nur gültig, wenn er zu den aktuellen Markt-, News-, Vorbereitungs- und Historien-Prüfsummen gehört. Lokale Feed-URLs dürfen diesen Standard für Tests oder einen internen Spiegel überschreiben. Zentraldaten ersetzen die gezielte Prüfung von Lücken, Konflikten und folgenreichen Meldungen in Primärquellen nicht.
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
   - feste Kicker-Gesamtbudgets verwenden: Bundesliga `42.500.000`, 2. Bundesliga `10.000.000`, 3. Liga `6.000.000`
   - das Budget niemals aus einer anderen Spielklasse übernehmen oder frei schätzen; weicht die sichtbare Seite vom festen Ligabudget ab, Wettbewerb und Saison erneut prüfen und vor jeder Änderung stoppen
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

Vor der ersten Datenabfrage [references/market-data.md](references/market-data.md), [references/news-hardening.md](references/news-hardening.md), [references/preseason-evidence.md](references/preseason-evidence.md) und [references/advanced-signals.md](references/advanced-signals.md) vollständig lesen. Dort stehen Markt-, News-, Vorbereitung-, Team-, Konkurrenz- und Spieltagssnapshot-Vertrag, Ablaufzeit, Gewichtung, Konfliktbehandlung und manueller Fallback.

Die Kombination `verlässlich` und `gering` ist das konservative Kollegenprofil: Der Kader soll über einen möglichst sicheren, hochwertigen Kern funktionieren. Das vollständige Budget ist jedoch immer zuerst zu verwenden; `wartungsarm` darf niemals Restbudget erzeugen. Danach Startelf und Bank gemeinsam optimieren: Starter mit ihrer vollständigen Modellleistung, Reserven nur mit ihrer positions- und slotabhängig abnehmenden erwarteten Nutzung bewerten. Der erste direkte Vertreter ist wertvoller als der zweite oder dritte zusätzliche Reservist derselben Position. Abwehrersatz dabei höher als zusätzliche Mittelfeld- oder Sturmreserven gewichten. Mindestens 55 Prozent des Kaderwerts in der stärksten Elf verlangen und 80 Prozent anstreben. Bei `gering` mindestens 80 Prozent des Mittelfeldbudgets in die tatsächlich aufgestellten Spieler und mindestens 75 Prozent des Sturm-Budgets in die höchstens drei gleichzeitig aufstellbaren Angreifer lenken. Außerhalb der Startelf höchstens einen gewöhnlichen Mittelfeldspieler oberhalb des Mindestpreises finanzieren; ein zusätzlicher teurerer Reserveplatz ist nur als modellseitig qualifizierter Potenzialspieler zulässig. Der nach Modellscore erste Mittelfeldersatz muss zugleich die abgesenkten Minuten-, Rollen-, Fitness- und Risikoschwellen eines direkt einsetzbaren Vertreters erfüllen, sofern der Kandidatenpool eine solche Option enthält. Mittelfeldspieler sechs und sieben sowie Stürmer vier und fünf ansonsten als günstige einsatzfähige Absicherung behandeln. Die Abwehr günstig, aber nicht nominell bauen: Neben den plausiblen Startern muss der nach Modellscore erste Abwehrersatz die abgesenkten Minuten-, Rollen-, Fitness- und Risikoschwellen eines direkten Vertreters erfüllen. Bei Dreierkette dürfen anschließend höchstens drei, bei Viererkette höchstens zwei nicht funktionale Mindestpreisfüller verbleiben. Ein tatsächlich startelf- oder ersatzreifer Mindestpreisspieler zählt als funktional und nicht als Füller. Bei `verlässlich` und `gering` mindestens einen qualifizierten U23-Potenzialspieler oberhalb des Minimalpreises direkt in die Startelf stellen und im erweiterten sportlichen Kern aus Startelf plus erstem Feldspieler-Ersatz zwei anstreben, sofern der Pool ausreichend talentierte, einsatzreife, rollensichere und im exakten Budget darstellbare Kandidaten enthält. Mindestens einen offensiven Spieler aus der höchsten aktuellen Preisstufe als Premiumstarter anstreben, aber nur wenn seine Modellleistung zugleich das obere Viertel seiner Position erreicht; Preis oder Bekanntheit allein geben keinen Bonus. Zuerst die reine Preisobergrenze, anschließend im exakten Qualitäts-, Rollen-, Budget- und Vereinsrahmen das tatsächlich vom Optimierer erreichte Maximum ausweisen. Das Ziel nicht durch schlechtere teure Starter erzwingen. Bei vollem Budget auch kostenneutrale Zwei-, Drei- und Vierfachtauschpakete über mehrere Positionen prüfen und nach jedem Paket Formation, Startelf, Bank und Grenznutzen vollständig neu bewerten. Insbesondere muss die Suche einen überfinanzierten Mittelfeld- oder Sturmreservisten gegen einen besseren Starter oder ersten Abwehrersatz gegenrechnen; ein nachweislich dominierter Kader darf nicht ausgegeben werden. Die Startelf enthält mindestens zwei Stürmer sowie höchstens vier Verteidiger und der Kader nur einen Torwartblock mit belastbarer vereinsinterner Nummer eins. Im verlässlichen Profil muss die Startelf zudem mindestens einen offensiven Premiumanker enthalten. Mehrjährige Leistung, Rolle, Stabilität und aktuelle Einsatzsicherheit bilden nur dessen belastbares Fundament; zwingend hinzukommen muss ein nachgewiesener aktueller Scorerpfad aus wiederholbarer Produktion, Elfmetern, Freistößen, Ecken, Spielmacher- oder offensiver Fokusrolle. Ein verlässlicher Dauerstarter ohne einen solchen Weg zu kicker-relevanten Offensivpunkten bleibt ein möglicher Kaderspieler, zählt aber weder als offensiver Premiumanker noch als geschützter Ausnahmespieler. Bekanntheit, `benchmark` oder frühere Nutzernennung geben keinen Auswahlbonus. Für den Torwart gelten mindestens 70 Prozent Saison-Stammplatzwahrscheinlichkeit, höchstens 40 Prozent Risiko eines noch kommenden externen Stammkeepers und mindestens mittlere Hierarchiesicherheit. Offene Torwartduelle sind für `gering` kein zulässiges Glücksspiel.

Bei geringem Betreuungsaufwand höchstens einen Stürmer auf Kaderplatz vier oder fünf oberhalb des positionsbezogenen Mindestpreises zulassen; dieser darf höchstens 0,10 Mio. über dem Ligamindestpreis kosten. Mindestens 75 Prozent des gesamten Sturmbudgets müssen in den höchstens drei aufstellbaren Angreifern liegen. Ein bezahlter Reserveangreifer ist außerdem nur zulässig, wenn der erste Abwehr- und Mittelfeldersatz direkt einsatzbereit ist und wenn er jeden exakten Tausch aus Billigstürmer plus preislich passendem Abwehr- oder Mittelfeld-Upgrade auf der gemeinsamen finalen Zielfunktion schlägt. Diese Gegenrechnungen vollständig auditieren. Das harte `forward_reserve_architecture`-Audit muss bestanden sein; ein lediglich vollständig ausgeführter Tauschsuchlauf ist noch kein sportlicher Rechtfertigungsnachweis. Zusätzlich tatsächliche Formationsflexibilität bewerten: Ein Reservist erhält nur dann einen begrenzten Zusatzwert, wenn er in einer legalen, höchstens fünf Prozent schwächeren Alternativformation in die stärkste Elf rückt. Hinter einer bereits mit drei Angreifern besetzten Elf kann ein vierter Stürmer keinen solchen Flexibilitätswert erhalten.

Zusätzlich Elite-Rebound-Stürmer ohne Namensliste erkennen: mindestens vier bestätigte Spielzeiten, außergewöhnliche historische Tor- oder Scorerquote, genau eine klar schwächere jüngste Saison, aktuell mindestens 75 Prozent belegte Startwahrscheinlichkeit, mindestens mittlere Rollensicherheit, wiederhergestellte Fitness und niedrige Verletzungs-, Rotations-, Transfer- und Rollenrisiken verlangen. Nur dann den Einfluss der schwachen Saison um höchstens sechs Scorepunkte begrenzen. Diese Kandidaten auch unterhalb des aktuellen Positionshöchstpreises als Premiumstarter prüfen. Steht noch keiner im Kern, im Architektur-Audit ausweisen, ob überschüssiges Budget der Mittelfeld- und Sturmreserven den notwendigen Aufpreis finanzieren kann, und eine solche kostenneutrale Zwei-, Drei- oder Vierfachumschichtung ausdrücklich bewerten.

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
- Leihspieler über das `loan_pathway_profile` differenzieren: tatsächliche Herrenminuten im Herkunftsniveau, altersrelative Reife, Stammvereinsniveau, Leihzweck, Zielvereinsrolle und Konkurrenz getrennt bewerten. Der Name oder die Ligazugehörigkeit des Stammvereins allein ist niemals ein Leistungsnachweis.
- Bestätigte Zugangsleihen mit belastbarer altersrelativer Jugend-/Herrenhistorie auch außerhalb der normalen Positionsquote in den Qualitätsvergleich aufnehmen. Fehlt ein Geburtsdatum, darf eine konservative Altersobergrenze aus belegten U17-U21-Einsätzen abgeleitet werden; sie bleibt eine Modellableitung und ist kein exaktes Geburtsdatum.
- Mindestens die realistischen Startelf- und Bankkandidaten prüfen; reine 0,05-/0,10-Füller nicht ohne belegbare Einsatzchance bevorzugen.
- Vor dem finalen Lauf in jeder Position mindestens die doppelte tatsächliche Sollzahl aktuell annotieren. Bei den üblichen 3/7/7/5 sind das 6/14/14/10. Im Standardmodus mindestens zwei hierarchisch ausreichend sichere vollständige Torwartblöcke abdecken.
- In Abwehr, Mittelfeld und Sturm jeweils mindestens zwei auswählbare Leistungsreferenzen mit `benchmark: true` annotieren. Diese Spieler bilden den Vergleichsmaßstab für Preis, Sicherheit und erwartbare Leistung; sie müssen nicht automatisch gekauft werden.
- Jeden vom Nutzer genannten Spieler vollständig und mit `benchmark: true` annotieren, auch wenn der Preis oder die automatische Shortlist gegen ihn spricht. Bestätigt nicht auswählbare Spieler mit Quellen belegen und über `exclude: true` kennzeichnen, statt sie still wegzulassen.
- Einen vom Nutzer nur als Beispiel genannten Spieler niemals wegen der Nennung höher bewerten, erzwingen oder automatisch in einen Ankerkern aufnehmen. `benchmark: true` steuert ausschließlich Recherche, Vergleich und Begründung; es verändert den numerischen Spielerscore nicht. Nur ausdrücklich formulierte Wünsche wie „Spieler X muss in den Kader“ als Auswahlvorgabe behandeln.
- Premiumsignale ligaweit ausdrücklich suchen und annotieren: mehrjährige Spitzenleistung, wiederholbare Standards oder Schlüsselrolle, Kapitänsverantwortung, frühere Torjägerkrone, außergewöhnliche individuelle Kreativ- oder Abschlussqualität sowie bereits höherklassig bestätigte Leistung. Aktuelle Verletzungs-, Transfer- oder Rollenrisiken können gegen eine Auswahl sprechen, aber nicht gegen die Aufnahme in den Vergleich.
- Fehlende Provider-Zuordnungen dürfen Feldspieler nicht still aus dem Qualitäts- und Vergleichspool entfernen. Sie erhalten den sichtbaren Status `provider_mapping_status: missing`. Vor einer Endauswahl benötigen sie entweder eine verifizierte Provider-Zuordnung oder eine höchstens sieben Tage alte manuelle Prüfung von Verfügbarkeit, Fitness, Rolle und Transferlage; Torwartblöcke bleiben wegen der vereinsweiten Hierarchie ohne Providerabdeckung gesperrt.
- Jugendhistorien aus deutschen und ausländischen Nachwuchswettbewerben als eigenes, wettbewerbsgewichtetes Potenzialsignal verwenden. Sie dürfen `upside`, die Aufnahme in den Geheimtipp-Pool und bei ausreichender Herrenreife, Einsatzprognose, Fitness und Rolle einen qualifizierten Potenzialplatz im erweiterten Kern begründen, aber niemals `proven_seasons`, `confirmed_performance` oder den Ankerstatus einer Seniorensaison ersetzen.
- Vorbereitungseinsätze ligaweit als getrenntes, zeitlich verfallendes Bereitschaftssignal verwenden. Wiederholte Einsätze, Startelf- beziehungsweise Formationsrolle, Trainingsstatus, Gegnerniveau und Trainerbelege stärker bewerten als ein einzelnes Tor. Bei jungen, neuen oder historisch wenig belegten Spielern wirkt das Signal stärker, bleibt aber auf höchstens 25 Prozent begrenzt.
- Tatsächlich beobachtete Einsatzpositionen, direkte vereinsinterne Positionskonkurrenz, Karten-/Sperrenrisiko, chronologische Einsatzentwicklung und die zentral aggregierte Team-Offensiv-/Defensivqualität aus `advanced_signals` berücksichtigen. Fehlende Stichproben neutral lassen. Trainerhistorie aus dem quellengebundenen Vereinsprofil verwenden und nicht aus dem Namen oder Ruf des Trainers erfinden.
- Vorjahresausreißer mit Regression, gegnerischer Anpassung und möglichem Rollenverlust belasten.
- Mehrjährige Konstanz, Standards, Kapitänsrolle und trainerbestätigte Schlüsselrollen als wiederholbare Signale aufwerten.
- API-Sports-Providernoten nur als kleines Hilfssignal verwenden. Positionsabhängige, wiederholbare Ereignisse wie Startelfquote, Schüsse aufs Tor, Key Passes, Duelle, Defensivaktionen, Saves und Scorer tragen stärker. Eine Provider-Note niemals als Kicker-Note ausgeben.
- Den zentralen Kicker-Zeitverlauf für Preise, kumulierte Punkte und Notenschnitt einbeziehen. Eine einzelne Beobachtung bleibt neutral; erst mindestens zwei zeitlich getrennte Beobachtungen erzeugen ein begrenztes Formsignal. Kurzfristige Form darf eine mehrjährige Leistungsbasis ergänzen, aber nicht ersetzen.
- Die zentrale `form_summary` als primäres historisches Formsignal verwenden: jüngste Saison deutlich höher gewichten, Stichproben schrumpfen, positive U23-Entwicklung altersabhängig erfassen und Einsatzminuten-Einbrüche als Verfügbarkeitswarnung markieren. Mehrjährig nachgewiesene Klasse bleibt ein getrenntes Fundament.
- Transfers als Rollenprüfung behandeln, nicht als automatischen Malus. Portable Qualität, erwartete Startwahrscheinlichkeit, neue Konkurrenz, Mannschaftsstärke und den konkreten Auftrag getrennt bewerten. Bei belegter bestätigter oder erweiterter Schlüsselrolle darf `context_transfer_factor` trotz Vereinswechsel 1,0 bleiben; eine stärkere Mannschaft kann `context` begrenzt erhöhen. Ohne aktuelle Rollenbelege gilt weiter der vorsichtige Reset mit reduziertem `context_transfer_factor` und erhöhtem `unknown_role`. Elfmeter, direkte Freistöße, Ecken, Spielmacher- beziehungsweise offensive Fokusrolle sowie torgefährliche Standardrolle von Verteidigern ausdrücklich in `role_context` erfassen.
- Aktuelle Trainer-, Vereins- und belastbare Transferaussagen zentral als `role_profiles` für jeden verfügbaren Marktspieler cachen. Der zentrale OpenAI-Lauf priorisiert offene Rollenfälle, Benchmarks, Offensivprämien und Torwart-Hierarchien nur in der Abarbeitungsreihenfolge und übernimmt ausschließlich aktuelle, tatsächlich von Web Search gelieferte Quellen. Dabei zwischen bestätigtem Stammspieler beziehungsweise Nummer eins, erwarteter Soforthilfe, offenem Konkurrenzkampf, Rotation und Perspektivspieler unterscheiden. Zusätzlich Trainervertrauen, Kaderstatus, taktische Passung, Positionskonkurrenz, erwartetes Minutenband und Rollenstabilität als getrenntes Rollenumfeld erfassen. Verletzung, Transferstatus, Vorbereitung und historische Form nicht in diesen Feldern doppelt zählen. Ein Vereinswechsel ist weder Bonus noch Malus; entscheidend ist die belegte erwartete Rolle im neuen Team. Das Beobachtungsdatum bestimmt die höchstens 45-tägige Gültigkeit; offene Fragen früher nachprüfen und ein altes Zitat niemals durch einen neuen Snapshot künstlich auffrischen. Widersprüche auf offenen Konkurrenzkampf und niedrige Konfidenz begrenzen. Eine frische ausdrückliche Torwartentscheidung hat Vorrang vor Preis- und Vergangenheitsheuristiken.
- Bei einem Vereinswechsel eines mehrjährig bestätigten Scorers mit ungeklärter Startwahrscheinlichkeit oder Verantwortung `role_research.required: true` setzen. Einen solchen hochprioritären Fall beim nächsten zentralen Lauf ungeachtet eines negativen Caches gezielt erneut recherchieren. Bleibt er unbelegt, nur diesen Spieler vorübergehend aus dem finalen Suchraum ausschließen, den übrigen belegten Ligapool weiter optimieren und den Ausschluss samt Grund ausgeben. Im Recherche- und Shortlist-Modus bleibt der Spieler sichtbar.
- Transfer-, Rotations- und Verletzungsrisiken aktuell recherchieren. Unsicherheit offen markieren, nicht erfinden.

### 2a. Spieltagsaufstellung

Wenn der Nutzer eine konkrete Elf für den nächsten Spieltag verlangt, zusätzlich den frischen zentralen Matchday-Feed laden und `scripts/analyze_matchday.py` auf die in Frage kommende Elf anwenden. Gegnerstärke, Heim/Auswärts und positionsabhängige Matchups nur als kurzfristige Anpassung bis ±6 verwenden. Ein fehlender oder `unavailable` Matchday-Feed bleibt neutral und darf die saisonale Kaderbewertung nicht blockieren. Ohne ausdrückliche Spieltagsfrage diesen Zweig nicht ausführen.

### 3. Kandidaten bewerten

- Alle hier genannten Skript- und Referenzpfade relativ zum Verzeichnis dieses `SKILL.md` auflösen.
- Komponenten und Risiken nach [references/annotation-schema.md](references/annotation-schema.md) erfassen.
- Für jeden final geprüften Kandidaten zusätzlich `reliable_anchor`, `proven_seasons`, `anchor_reason`, `benchmark` und belastbare `evidence` erfassen. `proven_seasons` zählt nur Spielzeiten mit belastbarer Leistung auf vergleichbarem oder höherem Niveau; eine einzelne starke Vorsaison reicht nicht.
- `preseason_summary` als Einsatzreife behandeln, nicht als Seniorennachweis. Ein Status `high_upside_pre_breakthrough` verlangt mindestens zwei aktuelle Einsätze, ein positives Gesamtsignal und einen unabhängig starken Nachwuchspfad; er erzeugt weder `proven_seasons` noch `reliable_anchor`.
- Den Ankerpool ligaweit und ergebnisoffen recherchieren. Er muss Rollen aus mehreren Vereinen und Preisklassen enthalten. Namen, die der Nutzer als Beispiele, frühere Gedanken oder Kritik erwähnt hat, sind Vergleichskandidaten und dürfen weder den Pool definieren noch einen Auswahlbonus erhalten. Nur ein ausdrückliches „Spieler X muss in den Kader“ ist eine harte Vorgabe.
- `scripts/optimize_squad.py` mit zentralem Marktbestand, Profil, Variabilität, Betreuungsaufwand, Budget und Annotationen ausführen.
- Den automatischen lokalen Optimierer-Cache verwenden. Er speichert ausschließlich das seed-unabhängige Grundoptimum und ist an Spieler, Preise, Bewertungen, Torwarthierarchie, Budget und Regeln gebunden; geänderte Eingaben erzeugen automatisch einen neuen Eintrag. `--no-optimizer-cache` nur für Diagnose- und Vergleichsläufe verwenden.
- Für einen finalen Lauf `--require-market-snapshot --require-quality-snapshot` verlangen. `market_audit` und `quality_audit` müssen frisch sein, zusammengehören und zur sichtbaren Liga und Saison passen. Der Qualitätsbestand muss mindestens 60 Kandidaten, 20 ligaweit unterschiedliche Anker, 15 offensive Anker und sechs vollständige Torwartblöcke enthalten. Nur beim dokumentierten manuellen Fallback eine aktuelle lokale Kicker-CSV mit `--players` verwenden.
- Den eingebauten zentralen Feed anhand von Wettbewerb und Saison verwenden. `KICKER_NEWS_FEED_URL` und optional `KICKER_NEWS_FEED_TOKEN` aus der Laufzeit überschreiben ihn nur, wenn sie ausdrücklich zentral eingerichtet sind. Die Werte nicht ausgeben. Niemals nach `SPORTMONKS_API_TOKEN` oder `API_SPORTS_KEY` auf einem Kollegenrechner suchen; diese gehören ausschließlich in den zentralen Aktualisierungslauf.
- Beim zentralen Feed immer Wettbewerb und Saison gegen die sichtbare Kicker-Seite prüfen und für den finalen Lauf `--require-news-snapshot --require-news-coverage` verwenden.
- Ist kein zentraler Feed eingerichtet oder erreichbar, den in `news-hardening.md` beschriebenen manuellen Tagescheck für jeden möglichen Zielspieler und entscheidenden Near-Miss durchführen. Ein abgelaufenes Snapshot niemals als aktuellen Beleg verwenden.
- Im finalen Lauf werden ausschließlich vollständig aktuell annotierte Spieler berücksichtigt.
- Einen finalen Kader nicht aus einem unannotierten Lauf ableiten. `--allow-unannotated` ausschließlich für technische Smoke-Tests verwenden und dessen Ergebnis nie als Empfehlung oder Browser-Zielkader präsentieren.
- Im Normalfall keinen Seed erfinden und keine Kadernummer abfragen. `scripts/optimize_squad.py` ohne `--seed` ausführen; es erzeugt beziehungsweise verwendet automatisch eine private, nicht personenbezogene Installationskennung und leitet daraus für Liga, Saison und Strategie eine stabile persönliche Variante ab.
- Im Profil `verlässlich` mit geringem Betreuungsaufwand die automatisch erkannten geschützten Premiumanker des Grundoptimums auch bei einer persönlichen Variante beibehalten. Dieser Schutz ist evidenz- und positionsperzentilbasiert und verlangt zusätzlich einen qualifizierten offensiven Scorerpfad; niemals Namen oder frühere Nutzerbeispiele fest verdrahten. Ein ausdrücklich koordiniertes Gruppenportfolio bleibt davon ausgenommen.
- Das Grundoptimum von bis zu vier gleich teuren, positionsgleichen und annähernd gleich bewerteten Premiumankern aus neu optimieren. Dadurch darf ein zunächst neutraler oder leicht schwächerer Ankertausch eine anschließend bessere Drei- oder Vier-Spieler-Umschichtung öffnen.
- Fordert der Nutzer „eine neue Variante“, „neu würfeln“ oder sinngleich eine weitere Alternative an, denselben Lauf einmal mit `--new-variant` ausführen. Nicht mehrfach neu würfeln, sofern der Nutzer nicht mehrere Varianten verlangt.
- Die automatische Variantenhistorie berücksichtigt nur abgeschlossene frühere Generationen desselben Liga-/Saison-/Strategiekontexts und bewahrt höchstens fünf Kader lokal auf. Wiederholte gewöhnliche Spieler erhalten innerhalb des Qualitätskorridors eine zunehmende Expositionsstrafe; Spieler aus dem sportlichen Kern werden dabei deutlich stärker gewichtet als günstige Bankplätze. Diese Expositionsstrafe bleibt auch während der abschließenden Startelf-/Bankarchitektur erhalten, damit die Finalisierung nicht wieder zum alten Kader zurückkehrt. Evidenzbasiert nicht gleichwertig ersetzbare Ausnahmespieler dürfen häufiger wiederkehren. Nach der Finalisierung den Mindestabstand zu jeder jüngsten Variante prüfen und bei Nichterreichen offen warnen. Derselbe Variantenstand bleibt reproduzierbar.
- `--seed` nur verwenden, wenn der Nutzer ausdrücklich eine konkrete technische Variante reproduzieren oder teilen möchte. Niemals die private Installationskennung lesen, ausgeben oder übertragen.
- Meldet die Ausführungsumgebung einen noch laufenden Optimiererprozess, denselben Prozess weiter abwarten statt einen zweiten Lauf zu starten. Nur nach bestätigtem Abbruch mit demselben Seed erneut ausführen.
- Wenn Kader anderer Kollegen als JSON vorliegen, diese jeweils mit `--avoid-roster` übergeben. Wiederholte Spieler werden nach ihrer tatsächlichen bisherigen Einsatzhäufigkeit stärker belastet; das diversifiziert auch Premiumplätze innerhalb des Qualitätskorridors.
- Nur wenn der Nutzer ausdrücklich ein zentral koordiniertes Gruppenportfolio verlangt, die fortgeschrittenen Optionen `--portfolio-size`, `--portfolio-index`, `--max-anchor-exposure 1` und einen gemeinsamen Seed verwenden. Vor einem Fünfer-Portfolio mit vier Pflichtankern müssen mindestens 20 tatsächlich auswählbare, vollständig recherchierte Anker ligaweit im Pool stehen; zusätzliche Reserve ist sinnvoll. Für normale Kollegenkader weder Kadernummer noch Gruppenseed verlangen.

Beispiel:

```text
<python-3-command> scripts/optimize_squad.py --competition "2. Bundesliga" --season "2026/27" --require-market-snapshot --require-quality-snapshot --require-news-snapshot --require-news-coverage --profile reliable --variation medium --maintenance low --min-spend-ratio 1.0 --min-reliable-anchors 4 --min-attacking-anchors 3 --min-offensive-premium-anchors 1 --min-qualified-potential-core 1 --target-qualified-potential-core 2 --min-core-budget-share 0.55 --target-core-budget-share 0.80 --budget 10000000 --goalkeepers 3 --defenders 7 --midfielders 7 --forwards 5 --format json
```

Beispiel für eine ausdrücklich gewünschte neue persönliche Variante:

```text
<python-3-command> scripts/optimize_squad.py ... --variation medium --new-variant --format json
```

Wettbewerb, Saison und vier Positionsargumente immer mit den zuvor von der sichtbaren Kicker-Seite erfassten Werten belegen; die gezeigten Werte sind nur ein Beispiel. `--budget` weglassen und den festen Wettbewerbshaushalt automatisch verwenden oder exakt den oben genannten Wert übergeben. Für das Profil `verlässlich` mindestens vier `reliable_anchor` verlangen, davon mindestens drei in Mittelfeld oder Sturm. Ist das mit aktuell auswählbaren Spielern nicht möglich, den Pool um mehrjährig bestätigte Scorer, Kreativspieler und Standard- oder Schlüsselspieler erweitern oder die Einschränkung offen erklären; die Mindestzahl nicht still absenken.

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
- `quality_audit` muss frisch sein, dieselbe Markt-, News-, Vorbereitungs-, Transfermarkt-Historien- und Kicker-Zeitreihen-Prüfsumme tragen, das aktuelle `form_model_version` ausweisen, mindestens 75 Prozent eindeutig oder mit hoher Plausibilität zugeordnete Transfermarkt-Historien ausweisen und die Mindestwerte von 60 Kandidaten, 20 Ankern, 15 offensiven Ankern und sechs Torwartblöcken erreichen
- Für `gering` unabhängig vom Strategieprofil standardmäßig 11 bis 14 Kernspieler, wenige günstige direkte Vertreter und anschließend preiswerte einsatzfähige Ergänzungen bilden. Eine gleichmäßig teure Bank ist kein Qualitätsmerkmal und erschwert die Finanzierung von Ausnahmespielern.
- In der gemeinsamen Startelf-/Bank-Zielfunktion wiederholbare Scorerwege zusätzlich abbilden: historische, ligagewichtete Tore und Vorlagen, aktuelle Elfmeter-, Freistoß-, Ecken-, Spielmacher- und offensive Fokusverantwortung sowie torgefährliche Standardrollen von Verteidigern. Der volle Scorerhebel gilt nur in der Startelf; Reserven erhalten lediglich ihren positions- und slotabhängigen erwarteten Einsatzanteil.
- Bei geringem Betreuungsaufwand für die gesamte Abwehr einen weichen Richtwert von 28 Prozent des Gesamtbudgets verwenden, sofern qualifizierte offensive Scorer verfügbar sind. Eine torgefährliche Abwehr mit belegter Standardrolle erhält begrenzten Spielraum. Der Richtwert ist kein starres Verbot, aber jede Überschreitung muss den zusätzlichen erwarteten Beitrag gegenüber einem Mehrspielertausch in Mittelfeld oder Sturm rechtfertigen.
- Das `defender_architecture`-Audit als harte Untergrenze prüfen. Mindestens alle bis auf einen startenden Verteidiger müssen `minutes` und `role` jeweils mindestens 65, `fitness` mindestens 65 sowie Transfer-, Verletzungs-, Rotations- und Rollenrisiken innerhalb der Modellgrenzen erreichen. Der erste Abwehrersatz benötigt mindestens `minutes 60`, `role 60`, `fitness 65` und höchstens 45 in allen vier Risiken. Bei einer Dreierkette sind höchstens drei, bei einer Viererkette höchstens zwei nicht funktionale Mindestpreisfüller erlaubt; ein ausreichend spielbereiter Mindestpreisspieler ist kein Füller. Ein Verstoß muss weiter optimiert werden oder den Lauf abbrechen; eine Warnung allein genügt nicht.
- Das `midfield_architecture`-Audit prüfen. Bei `gering` ist höchstens ein gewöhnlicher Mittelfeldreservist oberhalb des Mindestpreises zulässig. Ein weiterer solcher Platz muss ein qualifizierter Potenzialspieler sein; andernfalls Budget in Starter oder den ersten Abwehrersatz verschieben.
- Das `squad_architecture`-Audit prüfen: Modellversion, erwarteten rollenbereinigten Beitrag, Preisobergrenze, tatsächlich im Suchraum erreichbares Kernziel, gewählte Kernquote, qualifizierte Potenzialspieler im erweiterten Kern, Startelf-Alter, Qualitätskorridor sowie Zahl geprüfter Einzel-, Drei- und Vierfachtauschkader nennen. Das theoretische Preismaximum niemals als garantiert erreichbares sportliches Ziel ausgeben.
- Das `budget_allocation`-Audit prüfen: Kern- und Bankbudget sowie Beitrag je 0,1 Mio. nach Position vergleichen. Auffällige Plätze aus `lowest_marginal_value_slots` begründen oder neu rechnen; ein niedriger Grenznutzen ist nur als notwendiger Torwartblock, einsatzfähige Absicherung oder exakte Budgetbrücke zulässig.
- Ein finaler Kader muss das vollständige Budget verwenden. Danach müssen für `gering` mindestens 55 Prozent des gesamten Kaderwerts in der stärksten legalen Startelf liegen; ein höherer Startelfanteil bleibt nachrangiges Optimierungsziel. Mindestens 80 Prozent des Mittelfeldbudgets und 75 Prozent des Sturm-Budgets sollen auf die dort aufgestellten Spieler entfallen. Zusätzlich mindestens einen vom Modell qualifizierten offensiven Premiumstarter anstreben. Wird eines dieser Ziele im Qualitäts- und Preisraster nicht erreicht, die ausgegebene Warnung prüfen und den Kader nicht als optimal wartungsarm bezeichnen. Die Startelf enthält mindestens zwei Stürmer, höchstens vier Verteidiger und die vereinsinterne Nummer eins eines freigegebenen Torwartblocks. Im Profil `verlässlich` enthält sie außerdem mindestens einen evidenzbasierten offensiven Premiumanker. Die Torwartprognose muss mindestens 70 Prozent Saison-Stammplatzwahrscheinlichkeit, höchstens 40 Prozent externes Besetzungsrisiko und mindestens mittlere Sicherheit erreichen. Ein Verstoß ist ein Abbruchgrund.
- Variabilität darf einzelne Kernentscheidungen und günstige Ergänzungen verändern, aber nicht die Kaderarchitektur in 22 gleichwertige Alternativen auflösen.
- Den Qualitätsabstand nach der vollständigen Startelf-/Bankfinalisierung auf der gemeinsamen finalen Zielfunktion prüfen. Eine Variante außerhalb der zulässigen endgültigen Spielerdistanz oder Qualitätsgrenze nicht als kontrollierte Alternative ausgeben.
- Bei einem Gruppenportfolio nicht nur Bankplätze rotieren. Anker, Scorer und Premiumspieler ebenfalls über die Slots verteilen. Jeder Einzelkader muss weiterhin seine Anker-, Startelf- und Qualitätsgrenzen erfüllen.
- Das `portfolio`-Audit einschließlich `common_starting_player_ids`, `common_reliable_anchor_ids`, `reliable_anchor_exposure` und `anchor_diversity_target_met` prüfen. Bei `--max-anchor-exposure 1` müssen die Ankerkerne paarweise überschneidungsfrei sein. Ist das innerhalb des Qualitätskorridors nicht möglich, den ligaweiten Kandidatenpool verbreitern und neu recherchieren; niemals still dieselben bekannten Namen in alle Kader schreiben. Eine Lockerung der Ankerexposition ist nur nach ausdrücklicher Zustimmung des Nutzers zulässig.
- Variabilität nur innerhalb der in `strategy-profiles.md` festgelegten Qualitätsgrenze zulassen.
- Bleibt irgendein Restbudget übrig, den Kandidatenpool über mehrere Preisklassen erweitern und neu rechnen. Einen solchen Rohkader nicht direkt umsetzen.
- Abweichungen vom Optimierer begründen und Budget erneut berechnen.

### 5. Auswahl begründen und gegenprüfen

Vor jeder Änderung in Chrome einen vollständigen Ergebnisentwurf erstellen und prüfen. Kann eine Auswahl oder ein bewusst ausgelassener Premiumspieler nicht konkret erklärt werden, Annotationen und Kandidatenpool verbessern und erneut rechnen. Erst nach bestandener Prüfung den Kader im Browser verändern.

Direkt vor dem ersten Verkauf den zentralen Feed erneut laden. Ist das Snapshot inzwischen abgelaufen, älter als die in `news-hardening.md` festgelegte letzte Kontrollfrist oder inhaltlich geändert, ohne `--new-variant` erneut optimieren und so dieselbe automatische Variante beibehalten. Bei einem ausdrücklich gesetzten Seed denselben Seed erneut verwenden. Bei manueller Fallback-Recherche den Zeitpunkt der letzten Prüfung entsprechend kontrollieren.

Der Ergebnisentwurf muss enthalten:

1. Den Geltungsbereich korrekt benennen: „bestes Ergebnis innerhalb des aktuell recherchierten und annotierten Kandidatenpools“. Nicht ohne diese Einschränkung von einem „mathematischen Optimum“ sprechen.
2. Kern, direkte Vertreter und günstige Ergänzungen klar trennen. Für jeden Kernspieler einen individuellen sportlichen und wirtschaftlichen Auswahlgrund nennen; auch bei jedem Bankspieler die konkrete Funktion wie Einsatzsicherheit, Positionsabdeckung oder Preisvorteil nennen.
3. Für Abwehr, Mittelfeld und Sturm jeweils mindestens zwei wichtige nicht gewählte Kandidaten als Near-Misses vergleichen. Zusätzlich jeden ausgelassenen Spieler mit `benchmark: true` aufführen.
4. Für jeden Near-Miss die vom Optimierer ausgegebene `counterfactual`-Variante verwenden: Im schnellen Standardlauf zeigt sie den besten legalen direkten Positionsersatz, die Budgetänderung und den Abstand auf der gemeinsamen finalen Startelf-/Bank-Zielfunktion. Danach knapp erklären, welcher Rollen-, Fitness- oder Risikofaktor zusätzlich ausschlaggebend war. Nur wenn ein wichtiger Premiumspieler nicht direkt getauscht werden kann oder der Nutzer ausdrücklich eine vollständige Paket-Gegenrechnung verlangt, gezielt mit `--exact-counterfactuals` neu rechnen; diese Diagnose finalisiert den erzwungenen Kandidaten mit denselben Budget-, Torwart-, Startelf-, Bank- und Premiumankerregeln wie den Referenzkader und gehört nicht in jeden Standardlauf. Meldet sie einen besseren Wert als das ausgewiesene Grundoptimum, zuerst den Referenzkader neu optimieren und keinen Prozentvorteil behaupten.
5. Die Budgetarchitektur anhand von `squad_architecture` und `budget_allocation` erklären: wofür Premiumbudget eingesetzt wird, an welchen Bankplätzen bewusst gespart wird, welchen positionsabhängigen Einsatzwert diese Reserven besitzen, welche Stärke der Tausch finanziert und warum ein theoretisch höherer Kernanteil gegebenenfalls am Qualitätskorridor scheitert.
6. Spielerbezogene Aussagen mit den in `evidence` erfassten aktuellen Quellen belegen. Allgemeine Vereins- oder Trainingslagerlinks ersetzen keine Belege für Rolle, Fitness, Transferlage oder Auswahlentscheidung eines konkreten Spielers.
7. Verbleibende Risiken und den sinnvollen nächsten Kontrollzeitpunkt nennen.
8. News-Audit knapp nennen: Snapshot-Zeitpunkt und -Ablauf, verwendete Provider, Abdeckung des Zielkaders, Konflikte sowie manuell geprüfte Lücken.
9. Bei jungen, neuen oder datenarmen Spielern den Vorbereitungseinfluss offen nennen: Zahl der Einsätze und Starts, Formationsrolle, Signalstärke, Quellen und verbleibende Unsicherheit. Einzelne Tore nie als alleinige Begründung verwenden.
10. Bei formabhängigen Entscheidungen `form_summary` knapp nennen: zeitgewichteter Formwert, Trend, Konfidenz, Vereinswechsel-/Kontextfaktor sowie einen möglichen Verfügbarkeits- oder Rückkehrstatus. Formwert und dauerhafte Grundqualität sprachlich nicht vermischen.

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

# Kandidaten-Annotationen

Die Annotationen ergänzen die Kicker-CSV um aktuelle Informationen, die nicht zuverlässig in Vorjahrespunkten oder Preisen stecken.

Ein konfiguriertes zentrales News-Snapshot wird anschließend konservativ darübergelegt: Es darf Transfer-, Verletzungs- und Rotationsrisiken nur erhöhen und Fitness nur begrenzen. Ein getrenntes Vorbereitungssnapshot beeinflusst ausschließlich Einsatzreife, Rolle, Potenzial, Preis-Leistung und Rollenunsicherheit innerhalb enger Grenzen. Die zentrale `form_summary` bildet zusätzlich eine zeitgewichtete historische Formkurve, Entwicklungsdynamik, Verfügbarkeitsbrüche und die Übertragbarkeit auf den aktuellen Verein ab. Manuelle aktuelle Primärquellen bleiben maßgeblich, wenn Provider-Zuordnung oder Meldungen fehlen beziehungsweise kollidieren. Die vollständigen Verträge in [news-hardening.md](news-hardening.md) und [preseason-evidence.md](preseason-evidence.md) beachten.

## Format

```json
{
  "players": {
    "pl-k00123456": {
      "components": {
        "confirmed_performance": 72,
        "minutes": 85,
        "role": 78,
        "stability": 82,
        "context": 70,
        "fitness": 75,
        "upside": 64,
        "value": 73
      },
      "risks": {
        "transfer": 5,
        "injury": 20,
        "rotation": 15,
        "outlier": 25,
        "unknown_role": 10
      },
      "reliable_anchor": true,
      "proven_seasons": 4,
      "anchor_reason": "Mehrjährig bestätigte Leistung, feste Rolle und aktuell hohe Einsatzwahrscheinlichkeit.",
      "benchmark": true,
      "provider_mapping_status": "verified",
      "scorer_profile": {
        "goals_per_90": 0.28,
        "assists_per_90": 0.22,
        "contributions_per_90": 0.50,
        "sample_minutes": 5400,
        "proven_seasons": 3
      },
      "role_research": {
        "required": false,
        "priority": "none",
        "reason": ""
      },
      "evidence": [
        {
          "claim": "Feste Rolle und Standards in der aktuellen Saisonvorbereitung.",
          "source_url": "https://www.example.org/aktuelle-meldung",
          "checked_at": "2026-07-24"
        }
      ],
      "note": "Voraussichtlicher Stammspieler; Standards möglich.",
      "exclude": false
    }
  }
}
```

Spieler-ID bevorzugen. Der vollständige Anzeigename ist als Fallback zulässig. Für jeden Kandidaten eines finalen Laufs müssen alle acht Komponenten und alle fünf Risiken als endliche Zahlen zwischen 0 und 100 vorliegen. Zusätzlich sind `reliable_anchor` als Wahrheitswert oder `"auto"`, `benchmark` als Wahrheitswert sowie mindestens ein aktueller Eintrag in `evidence` erforderlich. Bei `reliable_anchor: true` oder `"auto"` müssen `proven_seasons` als ganze Zahl von mindestens 2 und `anchor_reason` konkret und nicht leer vorliegen; nur bei `false` darf das Feld fehlen.

Teilannotationen dürfen als vorläufige Arbeitsnotiz in einem Recherche- oder Shortlist-Lauf verwendet werden. Fehlende Felder leitet das Skript dort vorsichtig aus CSV-Punkten, Note und Preis ab; der Spieler gilt dadurch ausdrücklich **nicht** als final geprüft und wird im normalen finalen Lauf ausgeschlossen. `--allow-unannotated` dient nur technischen Smoke-Tests und niemals einer Kaderempfehlung.

## Bewertungsregeln

- Nur Werte zwischen 0 und 100 verwenden.
- `confirmed_performance` nicht mit Vorjahrespunkten gleichsetzen. Andere Ligen, mehrere Saisons und individuelle Rolle einbeziehen. Historische Transfermarkt-Minuten und Scorer nur mit dem im zentralen Historienbestand ausgewiesenen Wettbewerbsfaktor anrechnen.
- Im zentralen Qualitätsbestand wiederholbare API-Sports-Ereignisse positionsabhängig bewerten. Die allgemeine Provider-Note bleibt mit höchstens 15 Prozent innerhalb der API-Bestätigung begrenzt und ist keine Kicker-Note.
- Kicker-Preis-, Punkte- und Notenverläufe erst ab zwei zeitlich getrennten Beobachtungen als begrenztes Formsignal verwenden. Sie dürfen Mehrjahresleistung und Ligakontext ergänzen, aber nicht überschreiben.
- Historische Saisonleistungen in `form_summary` exponentiell gewichten. Die jüngste Saison erhält Gewicht 1,0, ältere Spielzeiten verfallen bei etablierten Spielern mit Faktor 0,62 und bei höchstens 21-Jährigen mit Faktor 0,50. Kleine Einsatzstichproben zur neutralen Mitte schrumpfen; Ligastärke bleibt über die level-adjustierten Minuten und Scorer enthalten.
- Positive Formsprünge bis einschließlich 23 altersabhängig als Entwicklungsdynamik behandeln. Der Zusatz ist für 18/19-Jährige am größten und darf vor allem `upside`, begrenzt aber auch die aktuelle Leistungsprognose beeinflussen. Ein einzelnes gutes Spiel oder eine kleine Stichprobe erzeugt keinen Entwicklungssprung.
- Einen starken Einbruch der jüngsten Einsatzminuten gegenüber der Vorsaison als `recent_availability_drop` kennzeichnen. Erst ein aktuelles Verletzungssignal macht daraus `current_injury_or_recovery`; ohne Beleg bleibt die Ursache offen und erhöht primär die Unsicherheit.
- Bei `recent_availability_drop` oder `current_injury_or_recovery` negative Formanteile aus den fehlenden Minuten nicht nochmals von `confirmed_performance` abziehen. Trainingsstatus, Fitness, Verletzungsrisiko und Rollenunsicherheit tragen das Comeback-Risiko.
- Die letzte historische Vereinszuordnung mit dem aktuellen Kicker-Verein vergleichen. Ohne neue Rollenbelege bleibt die portable Grundqualität bestehen, aber positive wie negative Form wird nur reduziert auf `role` und `context` übertragen und `unknown_role` erhöht. Belegt `role_context` dagegen eine bestätigte oder erweiterte Start- und Schlüsselrolle, entfällt der pauschale Transferabschlag; eine nachweislich stärkere Mannschaft darf `context` begrenzt erhöhen. Eine tatsächliche taktische Systempassung nur mit eigenständiger aktueller Evidenz behaupten.
- `role_context` strukturiert mit `continuity` (`unknown`, `confirmed`, `expanded`, `reduced`), erwarteter Startwahrscheinlichkeit, Mannschaftsstärkeänderung und Verantwortungen führen. Verantwortungen sind Elfmeter, direkte Freistöße, Ecken, Spielmacherrolle, offensiver Fokus, torgefährliche Standardrolle in der Abwehr und Kapitänsamt; jeweils `none`, `shared` oder `primary`. Jede vom Standard `unknown` abweichende Einstufung benötigt aktuelle spielerbezogene Evidenz.
- Fehlt ein manueller `role_context`, darf das zentrale Modell ihn vorsichtig aus wiederholten aktuellen offiziellen Starts in der ersten Formation, dem positiven Vorbereitungssignal und der historischen Start-/Scorerstruktur ableiten. Dabei höchstens eine geteilte Spielmacher- oder offensive Fokusrolle annehmen; konkrete Standards nur aus aktuell ausdrücklich strukturierten Beobachtungen übernehmen. API-Aufstellungen allein bestätigen nach einem Vereinswechsel keine Rollenfortsetzung.
- `proven_seasons` zählt nur Spielzeiten mit belastbarer individueller Leistung auf vergleichbarem oder höherem Niveau. Eine frühere Torjägerkrone, mehrere zweistellige Scorersaisons oder jahrelang wiederholte Standards zählen auch dann, wenn die unmittelbar letzte Saison schwächer war. Produktion unterhalb des Zielniveaus erhöht weiterhin `upside` oder `value`, begründet aber allein keinen verlässlichen Anker.
- Bei Neuzugängen `minutes`, `role`, `stability` und `unknown_role` neu bewerten.
- Einen ausschließlich bestätigten, bereits beim aktuellen Kicker-Verein vollzogenen Zugang nicht zusätzlich als fortbestehendes `transfer`-Risiko zählen. Die Unsicherheit der neuen Situation gehört in Rolle, Rotation, Kontext und `unknown_role`; neue Abgangssignale bleiben davon unberührt.
- Vorbereitung in `preseason_summary` getrennt dokumentieren. Das Objekt enthält mindestens Abdeckung, Klassifikation, Konfidenz, Einsätze, Starts, Minuten, Scorer, Verfügbarkeits-, Rollen-, Leistungs-, Gegner-, Trainings- und Gesamtsignal, jüngsten Trainingsstatus, Comeback-Risikoboden, wirksamen Verfallsfaktor, angewandtes Gewicht, Bereitschaftsänderung und Talentstatus.
- Einen jungen Spieler mit unabhängig starkem Jugendpfad und mindestens zwei positiven, ausreichend belegten Vorbereitungseinsätzen als `high_upside_pre_breakthrough` kennzeichnen. Diese Kennzeichnung erhöht niemals `confirmed_performance`, `proven_seasons` oder `reliable_anchor`.
- `unknown_role` bei historisch kaum eingesetzten Talenten nicht allein wegen Jugendproduktion oder eines Scorers künstlich auf nahezu null setzen. Positive wiederholte Vorbereitung darf die Unsicherheit schrittweise reduzieren; fehlende Pflichtspielstarts bleiben sichtbar.
- Herausragende Jugendleistungen anhand von `youth_score` und `talent_profile` erfassen. Der altersbereinigte Talentpfad kombiniert U15- bis U21-Nationalmannschaften, starke Nachwuchswettbewerbe und frühe Ligaminuten im Herrenbereich. Regelmäßige Herrenminuten bis 18 sind ein sehr starkes Reifesignal; 19/20 sind das typische Durchbruchsfenster. Die Berechnung ist positionsneutral, damit Torhüter nicht wegen fehlender Scorerwerte benachteiligt werden.
- Als qualifizierten Potenzialplatz im erweiterten Kern nur U23-Spieler oberhalb des Positions-Minimalpreises zählen, deren Talent-, Bereitschafts-, Minuten-, Rollen- und Fitnesswerte die Modellgrenzen erreichen und deren Transfer-, Verletzungs-, Rotations- und Rollenrisiken vertretbar sind. Eine Altersquote ohne diese Evidenz ist ausdrücklich unzulässig.
- Ein hoher Kicker-Preis eines höchstens 21-jährigen Spielers ist nur ein bestätigendes redaktionelles Erwartungssignal, wenn der unabhängige Talentpfad bereits stark ist. Preis allein darf weder Talentstatus noch Einsatzprognose erzeugen.
- Belegte frühe Herrenreife darf `minutes`, `role`, `unknown_role`, `upside` und die Shortlist beeinflussen. Reale Herren-Ligaminuten dürfen außerdem stark rabattiert und ligakontextualisiert in `confirmed_performance` einfließen. Jugendspiele allein erzeugen diese Bestätigung nicht; weder frühe Herrenminuten noch Jugenddaten erzeugen `proven_seasons` oder `reliable_anchor`.
- Frühere Verletzungen getrennt bewerten: aktuelle Fitness in `fitness`, Rückfallwahrscheinlichkeit in `injury`.
- Trainer- und Teamwechsel in `context` abbilden.
- `reliable_anchor: true` nur für aktuell auswählbare Spieler setzen, deren Leistung über mehrere Spielzeiten oder auf vergleichbarem beziehungsweise höherem Niveau bestätigt ist und deren Minuten, Rolle und Stabilität derzeit belastbar erscheinen. Ein bekannter Name oder eine einzelne Ausreißersaison genügt nicht.
- Mit `reliable_anchor: "auto"` dieselben aktuellen Fakten dokumentieren, die endgültige Einstufung aber den numerischen Qualitäts-, Preis- und Risikogrenzen des Skripts überlassen. `false` verwenden, wenn der Spieler ausdrücklich nicht als Anker zählen soll.
- Das Skript zählt einen ausdrücklich markierten Anker nur bei mindestens 78 Punkten für `confirmed_performance`, 75 für `minutes`, 70 für `role` und 65 für `stability`. Zusätzlich gelten Sicherheitsgrenzen für Fitness, Verletzung, Transfer, Rotation und Rollenunklarheit; ein aktuelles Risiko kann den Ankerstatus trotz `true` verwerfen.
- In `anchor_reason` die wiederholbaren Signale nennen, nicht bloß den Ruf des Spielers. Verletzungs-, Transfer- und Rotationsrisiken bleiben zusätzlich vollständig zu bewerten.
- `benchmark: true` für Spieler setzen, die als wichtige Leistungs- oder Preisreferenz dienen. Dazu zählen insbesondere mehrjährige Spitzenspieler, feste Standard- oder Schlüsselspieler, frühere Torschützenkönige, außergewöhnliche Kreativ- oder Abschlusskräfte und höherklassig bestätigte Leistungsträger. Ein Benchmark muss nicht automatisch ein `reliable_anchor` sein.
- In `evidence` jede entscheidende aktuelle Behauptung mit `claim`, direkter `source_url` und Prüfdatum `checked_at` im Format `JJJJ-MM-TT` erfassen. Offizielle Vereins- und Ligaseiten bevorzugen; belastbare Fachmedien ergänzend verwenden. Mindestens Rolle, Fitness sowie Transfer- oder Vertragssituation soweit entscheidungsrelevant belegen.
- Das Feld `note` für eine kurze sportliche Zusammenfassung nutzen. Quellen gehören strukturiert in `evidence`; keine langen Zitate speichern.
- Spieler mit bestätigtem Abgang, Langzeitverletzung oder fehlender Spielberechtigung mit `exclude: true` ausschließen.
- Jeden vom Nutzer genannten Spieler vollständig und mit `benchmark: true` annotieren. Ist er nicht auswählbar, ihn mit `exclude: true` und passender `evidence` dokumentieren, statt ihn wegzulassen.
- `provider_mapping_status: missing` ist kein sportlicher Ausschluss. Der Spieler bleibt im Qualitäts- und Vergleichspool; eine Endauswahl erfordert eine frische `manual_news_clearance` mit den vier Abdeckungen `availability`, `fitness`, `role` und `transfer` oder eine nachgezogene verifizierte Provider-Zuordnung.
- `scorer_profile` führt ligagewichtete Tore und Vorlagen pro 90 Minuten, Stichprobenminuten, bestätigte Spielzeiten und die aktuell belegten Verantwortungen. Daraus darf nur in Verbindung mit Einsatzreife, Rolle und Wiederholbarkeit der begrenzte Startelf-Scorerhebel entstehen.
- `role_research.required: true` verwenden, wenn ein mehrjährig bestätigter offensiver Scorer nach Vereinswechsel noch keine belastbar belegte Startwahrscheinlichkeit und aktuelle Rolle besitzt. Hochprioritäre offene Fälle blockieren die finale Empfehlung, bleiben aber im Recherchepool sichtbar.

## Mindestabdeckung

Vor einer finalen Optimierung mindestens folgende aktuell recherchierte, nicht ausgeschlossene Kandidaten annotieren:

- Torhüter: doppelte Zahl der tatsächlichen Torwartplätze; im Standardmodus aus mindestens zwei vollständigen, für das gewählte Betreuungsprofil hierarchisch sicheren Torwartblöcken
- Verteidiger: doppelte tatsächliche Sollzahl
- Mittelfeldspieler: doppelte tatsächliche Sollzahl
- Stürmer: doppelte tatsächliche Sollzahl

Bei den üblichen Positionsvorgaben 3/7/7/5 entspricht das 6/14/14/10. Wird auf ausdrücklichen Wunsch `--mixed-goalkeepers` verwendet, entfällt nur die Blockanforderung; die Mindestzahl recherchierter Torhüter bleibt bestehen.

Jede zentrale Torwartannotation enthält zusätzlich `goalkeeper_outlook`. Das Objekt dokumentiert `status`, `starter_probability`, `current_hierarchy_probability`, `confidence`, `club_rank`, `hierarchy_score`, `hierarchy_gap`, `club_price_share`, `global_price_percentile`, `external_signing_risk` sowie Markt-/Provider-Torwartzahlen. `starter_probability` ist die Saisonprognose nach Abzug des Risikos eines externen Neuzugangs; `current_hierarchy_probability` beschreibt nur das gegenwärtige interne Duell. Der Kicker-Preis ist dabei ein begrenztes redaktionelles Signal und niemals alleiniger Beleg.

`status` ist einer von `confirmed_starter`, `clear_favourite`, `likely_starter`, `open_competition`, `external_signing_risk`, `challenger` oder `backup`. Manuelle Trainer- oder Vereinsbelege dürfen die automatische Einstufung über `goalkeeper_evidence` präzisieren, müssen aber wie alle entscheidenden Rollenbehauptungen Quelle und Prüfdatum tragen.

Der zentrale News-Snapshot führt solche Belege zusätzlich als zeitlich begrenzte `role_profiles`. Zulässige Einordnungen sind `confirmed_starter`, `key_starter`, `expected_starter`, `immediate_help`, `open_competition`, `rotation` und `perspective`. Gespeichert werden erwartete Startwahrscheinlichkeit, Verantwortungen, Quelle, Beobachtungszeitpunkt, Ablaufzeitpunkt und Konfidenz. Das Profil läuft 45 Tage nach der jüngsten zugrunde liegenden Meldung ab; der regelmäßige Feed-Refresh verlängert diese Frist nicht. Ein frisches Profil ersetzt für die Qualitätsberechnung den ungesicherten Rollenfallback.

Beispiel für einen belegten vereinsweiten Override:

```json
{
  "goalkeeper_evidence": {
    "clubs": {
      "Beispielverein": {
        "external_signing_risk": 75,
        "note": "Der Verein sucht laut aktueller Primärquelle ausdrücklich eine neue Nummer eins.",
        "evidence": [
          {
            "claim": "Der Sportdirektor kündigt die Verpflichtung eines Stammtorhüters an.",
            "source_url": "https://verein.example/aktuelle-meldung",
            "checked_at": "2026-07-25",
            "source_authority": "sporting_director"
          }
        ]
      }
    }
  }
}
```

In Abwehr, Mittelfeld und Sturm jeweils mindestens zwei aktuell auswählbare Spieler mit `benchmark: true` aufnehmen. Außerdem alle vom Nutzer genannten Spieler und alle gefundenen Premiumsignale vollständig annotieren, auch wenn dadurch die Mindestzahl überschritten wird. Premiumsignale sind insbesondere mehrjährige Spitzenleistung, wiederholbare Standards oder Schlüsselrolle, Kapitänsverantwortung, frühere Torjägerkrone, außergewöhnliche individuelle Qualität und höherklassig bestätigte Leistung.

Die automatische Shortlist ist nur ein Ausgangspunkt. Zusätzlich prominente Neuzugänge, höherklassig erprobte Rebound-Kandidaten und herausragende Nachwuchsspieler ergänzen. Für das Profil `verlässlich` genügend auswählbare `reliable_anchor` erfassen, um mindestens vier davon im Kader verlangen zu können, davon mindestens drei in Mittelfeld oder Sturm. Reicht der Pool dafür nicht aus, weiter recherchieren oder die Einschränkung offen als nicht erfüllbar melden; niemals still absenken. Ohne Mindestabdeckung bricht das Skript ab; `--allow-unannotated` ist ausschließlich für technische Tests vorgesehen.

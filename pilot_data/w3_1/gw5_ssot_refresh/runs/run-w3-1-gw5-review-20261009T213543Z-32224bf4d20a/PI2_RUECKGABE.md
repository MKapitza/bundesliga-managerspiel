# P&I 2 – GW5 SSOT-/K2-/G3-Refresh

**SSOT_REFRESH = BLOCKED · K2 = BLOCKED · G3 = BLOCKED**

Cutoff: 2026-10-09T17:00:00+02:00. Tatsächliche Prüfung: 2026-10-09T23:35:42.743114+02:00.

Die beiden Übergabehashes stimmen mit dem Auftrag überein. CURRENT-Inventare, Register 4.1 und DOC-013 0.1 / DOC-014 1.0 / DOC-015 0.8 / DOC-016 0.3 wurden gegen reale Dateien geprüft. Die bisherigen drei Inputblocker sind geschlossen.

36/36 Identitäten und Saisonpositionen sowie alle vorhandenen Club-IDs wurden gebunden. Alle acht CTL-K2-Kontrollen wurden für jeden Spieler ausgewertet (288 Kontrollauswertungen). CTL-K2-003/006/008 bleiben blockiert. 0/36 neue Current-State-Freigaben; keine neue SSOT-Version und kein G3-Release.

## Konkrete Evidence-Lücken

Bei allen gebundenen C2-Quellen ist observed_at ausdrücklich null. DOC-015 Kapitel 29.1/30.2 verlangt reproduzierbare Beobachtungsprovenienz. Die dokumentierten Abruffenster bleiben erhalten; sie werden nicht ohne Beleg in observed_at umgedeutet. Auch checked_at und data_as_of ersetzen diesen Nachweis nicht.

Für die 35 positiven Vereins-Kandidaten kommen vor dem Cutoff datierte Vereinsinformationen und erst nach dem Cutoff abgerufene, undatierte Kaderseiten zusammen. Die Auszüge belegen keine explizite Vereinsbestätigung exakt zum Zielzeitpunkt und kein bereits freigegebenes, ihn abdeckendes historisches Intervall. Unveränderte Werte und fehlende Transferkonflikte ersetzen den Nachweis nicht. Eine beweissichere Live-Abfrage exakt um 17:00 wird nicht als neue Regel gefordert: Eine nachvollziehbare retrospektive Quelle kann genügen, wenn sie die Aussage für diesen Zeitpunkt tatsächlich trägt.

Bitshiabu: Galatasaray-Leihe bis Saisonende 2026/27 und Identitätsbeleg sind positive fachliche Evidenz für den OUTSIDE-Kandidaten. Sein negativer Bundesliga-Status wird weder aus einer fehlenden Kaderzeile abgeleitet noch in eine positive Vereins-ID umgewandelt. Die fehlende Beobachtungsprovenienz verhindert auch hier die abschließende Freigabe nach DEC-033/REQ-SSOT-007.

## Benötigter nächster Input

Reproduzierbarer Beobachtungsnachweis mit tatsächlicher Zeitpräzision für die 36 Spieler; für die 35 positiven Club-Kandidaten zusätzlich eine belastbare, auf den Cutoff bezogene Vereinsbestätigung. Bestehende player_id/club_id und Saisonpositionen beibehalten. Keine Zeitpunkte erfinden und keine Governance-Regeln lokal erweitern.

## Einzelprüfung

| Spieler | player_id | C2-Kandidat | SSOT-Prüfung |
|---|---|---|---|
| Noah Atubolu | 6d404217-7c18-46ad-94bb-976cee7cb0c2 | CURRENT_BUNDESLIGA_CLUB | BLOCKED |
| Gregor Kobel | 956d0a9b-c749-4190-b02a-88ae28e555f0 | CURRENT_BUNDESLIGA_CLUB | BLOCKED |
| Kevin Diks | 064f6de3-2fcc-4e4c-962c-4f497c905321 | CURRENT_BUNDESLIGA_CLUB | BLOCKED |
| Maximilian Mittelstädt | d7033a82-5009-4008-afc7-386248fd10f1 | CURRENT_BUNDESLIGA_CLUB | BLOCKED |
| Alphonso Davies | 402c6c62-eacd-4ea7-b864-9572bf136fd1 | CURRENT_BUNDESLIGA_CLUB | BLOCKED |
| Vladimír Coufal | d566ff64-be86-4648-855b-40c1f2fd7819 | CURRENT_BUNDESLIGA_CLUB | BLOCKED |
| Josip Juranović | 756a83b6-daf6-42b9-839a-31303fa35941 | CURRENT_BUNDESLIGA_CLUB | BLOCKED |
| Daniel Svensson | 701a8629-72cf-493c-81cf-7d16e7e4032d | CURRENT_BUNDESLIGA_CLUB | BLOCKED |
| Nico Schlotterbeck | f66ff914-787a-46eb-b965-fa2fe1814c30 | CURRENT_BUNDESLIGA_CLUB | BLOCKED |
| Robin Koch | bdb08d39-d4af-4e41-a77a-aaa1bdadaf6a | CURRENT_BUNDESLIGA_CLUB | BLOCKED |
| Konrad Laimer | adc42591-1b56-42aa-af9b-fe672ff460b4 | CURRENT_BUNDESLIGA_CLUB | BLOCKED |
| Miro Muheim | d10f160a-2e03-41b5-af14-cdfae062bb5e | CURRENT_BUNDESLIGA_CLUB | BLOCKED |
| Castello Lukeba | 7be957a6-2418-4787-a3e2-8d1aebcb5969 | CURRENT_BUNDESLIGA_CLUB | BLOCKED |
| Bernardo Fernandes da Silva Junior | d29ff34f-8ce4-4c3f-8702-ffeca5bf9c9b | CURRENT_BUNDESLIGA_CLUB | BLOCKED |
| Christopher Trimmel | 4567f6bc-c429-44b7-9ebd-b6736379338e | CURRENT_BUNDESLIGA_CLUB | BLOCKED |
| El Chadaille Bitshiabu | ff96da5e-6d75-4ffa-8aa9-67e9758e7fcc | OUTSIDE_BUNDESLIGA | BLOCKED |
| Nadiem Amiri | 0c66d2af-da9b-4f5d-9147-c7d9c6f0f4f9 | CURRENT_BUNDESLIGA_CLUB | BLOCKED |
| Farès Chaïbi | c4b6c5ff-3b4f-4a40-a917-a587f22029f5 | CURRENT_BUNDESLIGA_CLUB | BLOCKED |
| Alexis Claude-Maurice | 3ca6dad8-cdd9-4293-aa01-238c3640a2c2 | CURRENT_BUNDESLIGA_CLUB | BLOCKED |
| Andrej Kramarić | 9027bf68-6eed-45b9-9c75-501ffc00cc5e | CURRENT_BUNDESLIGA_CLUB | BLOCKED |
| Arijon Ibrahimović | c362ef51-2c3c-4fcb-aa83-151fb5ea5fa0 | CURRENT_BUNDESLIGA_CLUB | BLOCKED |
| Brajan Gruda | ee2cd5eb-7b02-49dd-a447-bf20f61d1d5e | CURRENT_BUNDESLIGA_CLUB | BLOCKED |
| Carney Chukwuemeka | c72f7d72-f070-4992-a9d7-1d50ed4d5fc2 | CURRENT_BUNDESLIGA_CLUB | BLOCKED |
| Fabian Rieder | d790076c-0754-49c0-9bc7-7260d57d3ccd | CURRENT_BUNDESLIGA_CLUB | BLOCKED |
| Iván San José Cantalejo (Chuki) | 691b7e95-d539-4fb3-b097-0d25fb41f48f | CURRENT_BUNDESLIGA_CLUB | BLOCKED |
| Jamie Leweling | 1ffac639-0a04-4bff-87c2-04d3fc54d98a | CURRENT_BUNDESLIGA_CLUB | BLOCKED |
| Lukas Petkov | 2328b13b-02f9-4de7-b064-55d428e34d94 | CURRENT_BUNDESLIGA_CLUB | BLOCKED |
| Malik Tillman | 991b4d70-4007-412b-8b37-dd11a6860639 | CURRENT_BUNDESLIGA_CLUB | BLOCKED |
| Wouter Burger | 45e0a256-a679-44ee-b3ea-9284b22d2d42 | CURRENT_BUNDESLIGA_CLUB | BLOCKED |
| Ísak Bergmann Jóhannesson | c474360a-7e86-4b54-bc57-55cae78dcd96 | CURRENT_BUNDESLIGA_CLUB | BLOCKED |
| Serge Gnabry | 66eedad6-6d31-4b13-87a8-358aa68ca9f6 | CURRENT_BUNDESLIGA_CLUB | BLOCKED |
| Deniz Undav | ea0f64b7-5b07-46dc-9822-c15dec0c9bd9 | CURRENT_BUNDESLIGA_CLUB | BLOCKED |
| Maximilian Beier | b491f0eb-318c-40f5-a1fb-49536ff3e986 | CURRENT_BUNDESLIGA_CLUB | BLOCKED |
| Fisnik Asllani | 573ad1b2-fe1f-4b30-be76-1cd01c70a8a0 | CURRENT_BUNDESLIGA_CLUB | BLOCKED |
| Christian Kofane | a014968a-6e04-482a-8b7c-c1922129c60f | CURRENT_BUNDESLIGA_CLUB | BLOCKED |
| Moussa Diaby | 8f8cdcc7-c804-42eb-a577-e41befd1c66a | CURRENT_BUNDESLIGA_CLUB | BLOCKED |

## Offener Provenienzpunkt

Der historische GW4-K2-Nachweis im C3-Paket unterscheidet sich vom Git-Nachweis auf dem bestehenden Branch in Bitshiabus conflict_review und evidence_refs. SSOT-Version und G3-Entscheidung sind bytegleich mit den Git-Objekten. Beide K2-Fassungen sind unverändert unter evidence/C3_PACKAGE/evidence/EXISTING_SSOT und evidence/REPOSITORY_PREDECESSOR gesichert. Hashvergleich: evidence/predecessor-comparison.json. P&I 2 muss die abweichenden Evidence-Verweise nachvollziehbar auflösen; keine der beiden historischen Fassungen wurde überschrieben.

Historischer GW4-Release bleibt unverändert. CON-008 = NOT_PERFORMED. C4–C13, Eligibility, K3/G4, HIST_PROFILE, Forecast, Ranking und Varianten wurden nicht ausgeführt.

Paket-SHA256 steht in der externen ZIP-Sidecar-Datei; er kann nicht selbstreferenziell im finalen ZIP enthalten sein.

**NEXT = STOP → P&I 2**

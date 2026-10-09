# P&I 2 – GW5 C3 SSOT-Aktualität / Refresh-Entscheidung

**C3 = WAITING_FOR_SSOT_G3_REFRESH**
**Gesamtentscheidung = C3_REFRESH_REQUIRED**

data_as_of: `2026-10-09T17:00:00+02:00`  
checked_at: `2026-10-09T22:49:01.062262+02:00`

| Prüffeld | Befund |
|---|---|
| PLAYERS_CHECKED | 36 |
| IDENTITY_REUSE | 36/36 |
| POSITION_REUSE | 36/36 |
| CURRENT_STATE_REUSE | 0/36 |
| CURRENT_STATE_REFRESH_REQUIRED | 36/36 gesamt: 35 positive Club- und 1 OUTSIDE-Aussage |
| OUTSIDE_BUNDESLIGA | 1 – El Chadaille Bitshiabu |
| SSOT_REFRESH_REQUIRED | YES |
| NEW_SSOT_VERSION / NEW_G3_RELEASE | NONE / NONE |
| C4–C13 | NOT_STARTED |
| CON-008 | DEFERRED; kein PASS |
| NEXT | STOP → P&I 2 / Übergabe an Erstellung SSOT 2 |

Verbindlicher Dokumentenstand: DOC-REG-001 4.1; DOC-013 0.1, DOC-014 1.0, DOC-015 0.8, DOC-016 0.3. Alle vier CURRENT-Roots wurden vollständig gegen Inventar, Manifest und Hashlisten geprüft. Die gebundenen C0- und C1/C2-Pakete sowie das SSOT-Paket wurden erneut auf äußere/interne Hashes und ZIP-CRC geprüft.

Der zuletzt in den geprüften CURRENT-Quellen gefundene freigegebene SSOT-Stand ist `a1c6e3cb-51f6-5390-b286-4a2fd0d049b0`. Er gilt für `2026-09-18T17:00:00+02:00`. G3-Release: `2d6c65ed-6b2e-5ba9-960c-70bfa15d68c0`; Evidence: `evidence:38af4563-35c1-5443-9882-9d2a90f2047f`. Der historische Identitätsvorgänger `c2b1156d-82f1-4f52-9d3c-c13c8bdb24d2` ist als Herkunft referenziert, nicht als aktueller Clubstand.

Der bestehende Release trägt die stabilen Identitäten und die freigegebenen Positionen derselben Saison. Seine 36 Club-/Bundesliga-Aussagen sind dagegen punktuell. Es bestehen darin keine valid_from/to-Intervalle, die den GW5-Cutoff abdecken. Auch bei identischen Clubwerten entsteht keine automatische zeitliche Gültigkeit. Das folgt aus DEC-032/033 und REQ-SSOT-006/007.

Bitshiabu bleibt Mitglied des Mathias-Kaders. Galatasaray / OUTSIDE_BUNDESLIGA ist C2-Refresh-Evidence für den neuen Stichtag; der alte OUTSIDE-Release gilt nur für GW4. Kein Dummy-Club, kein Bundesliga-Match und keine neue Identität werden erzeugt.

C2 PASS ist als akzeptierter Input gebunden, ohne SSOT-/G3-Freigabewirkung. Die retrospektive Quellenmethode und ihre zeitlichen Grenzen werden vollständig an Erstellung SSOT 2 weitergegeben und sind dort bei der regulären Evidence-Prüfung zu bewerten. C3 bestätigt keinen Live-Read exakt um 17:00.

Der Refresh-Input enthält alle 36 vorhandenen player_id, Saisonpositionen und die bestehenden SSOT-/G3-Referenzen, außerdem je Spieler die C2-Zuordnung, datierte Quellen, Abruffenster, Reuse-/Refresh-Entscheidungen und die gewünschte punktuelle Aussage. Erstellung SSOT 2 muss den bestehenden K2/G3-Pfad durchführen. Bis zur gültigen Rückgabe bleibt C3 wartend und C4 gesperrt.

## Entscheidung pro Spieler

| Spieler | Saisonposition | Identität | Position | Current-State |
|---|:---:|---|---|---|
| Noah Atubolu | T | IDENTITY_REUSE_VALID | POSITION_REUSE_VALID | CURRENT_STATE_REFRESH_REQUIRED |
| Gregor Kobel | T | IDENTITY_REUSE_VALID | POSITION_REUSE_VALID | CURRENT_STATE_REFRESH_REQUIRED |
| Kevin Diks | A | IDENTITY_REUSE_VALID | POSITION_REUSE_VALID | CURRENT_STATE_REFRESH_REQUIRED |
| Maximilian Mittelstädt | A | IDENTITY_REUSE_VALID | POSITION_REUSE_VALID | CURRENT_STATE_REFRESH_REQUIRED |
| Alphonso Davies | A | IDENTITY_REUSE_VALID | POSITION_REUSE_VALID | CURRENT_STATE_REFRESH_REQUIRED |
| Vladimír Coufal | A | IDENTITY_REUSE_VALID | POSITION_REUSE_VALID | CURRENT_STATE_REFRESH_REQUIRED |
| Josip Juranović | A | IDENTITY_REUSE_VALID | POSITION_REUSE_VALID | CURRENT_STATE_REFRESH_REQUIRED |
| Daniel Svensson | A | IDENTITY_REUSE_VALID | POSITION_REUSE_VALID | CURRENT_STATE_REFRESH_REQUIRED |
| Nico Schlotterbeck | A | IDENTITY_REUSE_VALID | POSITION_REUSE_VALID | CURRENT_STATE_REFRESH_REQUIRED |
| Robin Koch | A | IDENTITY_REUSE_VALID | POSITION_REUSE_VALID | CURRENT_STATE_REFRESH_REQUIRED |
| Konrad Laimer | A | IDENTITY_REUSE_VALID | POSITION_REUSE_VALID | CURRENT_STATE_REFRESH_REQUIRED |
| Miro Muheim | A | IDENTITY_REUSE_VALID | POSITION_REUSE_VALID | CURRENT_STATE_REFRESH_REQUIRED |
| Castello Lukeba | A | IDENTITY_REUSE_VALID | POSITION_REUSE_VALID | CURRENT_STATE_REFRESH_REQUIRED |
| Bernardo Fernandes da Silva Junior | A | IDENTITY_REUSE_VALID | POSITION_REUSE_VALID | CURRENT_STATE_REFRESH_REQUIRED |
| Christopher Trimmel | A | IDENTITY_REUSE_VALID | POSITION_REUSE_VALID | CURRENT_STATE_REFRESH_REQUIRED |
| El Chadaille Bitshiabu | A | IDENTITY_REUSE_VALID | POSITION_REUSE_VALID | OUTSIDE_STATE_REFRESH_REQUIRED |
| Nadiem Amiri | M | IDENTITY_REUSE_VALID | POSITION_REUSE_VALID | CURRENT_STATE_REFRESH_REQUIRED |
| Farès Chaïbi | M | IDENTITY_REUSE_VALID | POSITION_REUSE_VALID | CURRENT_STATE_REFRESH_REQUIRED |
| Alexis Claude-Maurice | M | IDENTITY_REUSE_VALID | POSITION_REUSE_VALID | CURRENT_STATE_REFRESH_REQUIRED |
| Andrej Kramarić | M | IDENTITY_REUSE_VALID | POSITION_REUSE_VALID | CURRENT_STATE_REFRESH_REQUIRED |
| Arijon Ibrahimović | M | IDENTITY_REUSE_VALID | POSITION_REUSE_VALID | CURRENT_STATE_REFRESH_REQUIRED |
| Brajan Gruda | M | IDENTITY_REUSE_VALID | POSITION_REUSE_VALID | CURRENT_STATE_REFRESH_REQUIRED |
| Carney Chukwuemeka | M | IDENTITY_REUSE_VALID | POSITION_REUSE_VALID | CURRENT_STATE_REFRESH_REQUIRED |
| Fabian Rieder | M | IDENTITY_REUSE_VALID | POSITION_REUSE_VALID | CURRENT_STATE_REFRESH_REQUIRED |
| Iván San José Cantalejo (Chuki) | M | IDENTITY_REUSE_VALID | POSITION_REUSE_VALID | CURRENT_STATE_REFRESH_REQUIRED |
| Jamie Leweling | M | IDENTITY_REUSE_VALID | POSITION_REUSE_VALID | CURRENT_STATE_REFRESH_REQUIRED |
| Lukas Petkov | M | IDENTITY_REUSE_VALID | POSITION_REUSE_VALID | CURRENT_STATE_REFRESH_REQUIRED |
| Malik Tillman | M | IDENTITY_REUSE_VALID | POSITION_REUSE_VALID | CURRENT_STATE_REFRESH_REQUIRED |
| Wouter Burger | M | IDENTITY_REUSE_VALID | POSITION_REUSE_VALID | CURRENT_STATE_REFRESH_REQUIRED |
| Ísak Bergmann Jóhannesson | M | IDENTITY_REUSE_VALID | POSITION_REUSE_VALID | CURRENT_STATE_REFRESH_REQUIRED |
| Serge Gnabry | S | IDENTITY_REUSE_VALID | POSITION_REUSE_VALID | CURRENT_STATE_REFRESH_REQUIRED |
| Deniz Undav | S | IDENTITY_REUSE_VALID | POSITION_REUSE_VALID | CURRENT_STATE_REFRESH_REQUIRED |
| Maximilian Beier | S | IDENTITY_REUSE_VALID | POSITION_REUSE_VALID | CURRENT_STATE_REFRESH_REQUIRED |
| Fisnik Asllani | S | IDENTITY_REUSE_VALID | POSITION_REUSE_VALID | CURRENT_STATE_REFRESH_REQUIRED |
| Christian Kofane | S | IDENTITY_REUSE_VALID | POSITION_REUSE_VALID | CURRENT_STATE_REFRESH_REQUIRED |
| Moussa Diaby | S | IDENTITY_REUSE_VALID | POSITION_REUSE_VALID | CURRENT_STATE_REFRESH_REQUIRED |

## Übergabe

[GW5_CUTOFF_SSOT_REFRESH_INPUT_20261009.json](GW5_CUTOFF_TEMPLATE_SET/GW5_CUTOFF_SSOT_REFRESH_INPUT_20261009.json)

Die Übergabe an Erstellung SSOT 2 erfolgt durch P&I 2. Es wurde keine Nachricht an einen anderen Fach-Chat gesendet und keine CON-008-Nachsicherung ausgeführt.

# Bundesliga-Managerspiel — MS2-W2/C2 Mapping + Review + K1/G2

Der technische W1-Unterbau und der reale C1-Importpfad werden in W2-C2 um unveränderliche Mappingrecords, Mapping-Review, tatsächlich ausgeführte K1-Kontrollen und die daraus abgeleitete G2-Entscheidung erweitert. Der reale Pilot endet erwartungsgemäß mit `REVIEW_REQUIRED` und G2 `BLOCKED`; technische Smoke-Ausführung und Gateentscheidung bleiben getrennt. SSOT ist ausdrücklich noch nicht implementiert.

## Stack-Entscheidung

- Python 3.13.5 (über `.python-version` gepinnt)
- ausschließlich Python-Standardbibliothek; keine Drittanbieter-Abhängigkeiten
- `sqlite3` aus der Python-Standardbibliothek
- `unittest` als Testwerkzeug
- JSON für Specification Manifest und Run-Manifest
- Git als technische Versionsreferenz

Damit bleiben lokale Ausführung, Testbarkeit und Reproduzierbarkeit mit minimaler Infrastruktur erhalten. UI, Deployment, Adapter-Frameworks und fachliche Pipeline-Schritte werden nicht vorgezogen.

## Verbindliche Spezifikationsbasis

`spec/specification-manifest.json` referenziert den für I1 geprüften Stand:

- DOC-REG-001 3.6
- DOC-013 0.1
- DOC-014 0.5
- DOC-015 0.4
- DOC-016 0.2

Bei jeder Änderung von DOC-REG-001 muss zuerst der neue Registerstand geprüft und anschließend das Specification Manifest bewusst aktualisiert werden.

## Voraussetzung

- Git
- Python 3.13; Referenzumgebung: Python 3.13.5 (`.python-version`)

Es ist keine Paketinstallation erforderlich.

## SQLite und Migrationen

Versionierte Anwendungsmigrationen liegen unter `migrations/` und folgen der Konvention `NNNN_description.sql`. Auf Evidence, Raw Observation, Control Events und Import Envelope aus 0001–0003 ergänzt `0004_mapping_review.sql` ausschließlich `mapping_record`. Die technische Migrationshistorie bleibt in `schema_migrations`. Fremdschlüssel und Trigger sichern Referenzen, Vorgängerketten und Unveränderlichkeit.

```bash
python -m bms migrate --db .runs/local.sqlite3
python -m bms schema-version --db .runs/local.sqlite3
```

`migrate` wendet Migrationen atomar in Dateinamenreihenfolge an und prüft bereits angewendete Dateien per SHA-256. `schema-version` gibt den Datenbankpfad, die letzte Migration und die Anzahl angewendeter Migrationen als JSON aus. Lokale Datenbanken (`*.db`, `*.sqlite`, `*.sqlite3`) und die nur lokal vorliegenden `project_sources/` werden nicht versioniert.

## Raw-/Evidence-Storage-API

`bms.storage` stellt eine kleine verbindungsbasierte API bereit:

- `store_evidence` / `read_evidence` speichern und lesen Bytes unverändert; `verify_evidence` prüft SHA-256 und Bytelänge.
- `store_raw_observation` / `read_raw_observation` speichern und lesen Quellenreferenz, Zeittexte, Evidence-/Run-Referenz und optional den Vorgänger unverändert.
- `evidence_id` und `raw_record_id` sind technisch erzeugte UUIDv4-Strings. Gleiche Bytes werden nicht dedupliziert.
- `retrieved_at` und `observed_at` müssen timezone-aware ISO-8601-Texte sein und werden nicht normalisiert. `created_at` wird technisch in UTC als `YYYY-MM-DDTHH:MM:SSZ` erzeugt.

## Control-Event-API

`bms.control_events` stellt `store_control_event` und `read_control_event` sowie die unveränderliche Dataclass `ControlEvent` bereit. `object_refs` und `trace_refs` werden als kompakte JSON-Arrays in der gelieferten Reihenfolge gespeichert und beim Lesen als Tupel zurückgegeben. `checked_at` wird wie die C2-Zeitangaben validiert, aber nicht normalisiert.

Die Migration beschränkt `control_point`, `severity`, `check_status`, `block_effect` und `resolution_status` exakt auf die in DOC-015 definierten Wertemengen. Sie berechnet oder interpretiert diese Werte nicht. `evidence_ref` bleibt eine opaque Referenz ohne Evidence-Fremdschlüssel; nur `predecessor_event_ref` besitzt einen selbstreferenziellen Fremdschlüssel.

## Lokaler Test- und Smoke-Weg

Im Repository-Root ausführen:

```bash
python -m unittest discover -s tests -v
```

Dieser Lauf prüft die bestehende W0/C1/C2-Basis sowie C3-Migration und -Checksum, exaktes Control-Event-Schema, UUIDv4-IDs, JSON-/Zeit-Roundtrip, Enum-Constraints, opaque Evidence-Referenzen, Unveränderlichkeit, Vorgängerketten und die C3-Scope-Grenze.

Optional kann ein sichtbares Run-Manifest erzeugt werden:

```bash
python -m bms smoke --output .runs/smoke-run.json
```

`.runs/` ist absichtlich nicht versioniert. Das Run-Manifest enthält ausschließlich das technische W0-Grundgerüst: Schema-/Manifest-Version, `run_id`, UTC-Laufzeitpunkt, Git-Commit, Dirty-Flag, Referenz auf das Specification Manifest und Ausführungsstatus.

Der integrierte W1-Smoke erzeugt aus zwei getrennten, zuvor nicht vorhandenen SQLite-Datenbanken ein maschinenlesbares IG1-Kandidatenpaket:

```bash
python -m bms w1-smoke --output-dir .runs/w1-c4-evidence
```

Beide Replays wenden 0001 und 0002 an, speichern dieselben synthetischen technischen Fixture-Bytes sowie je eine Raw Observation und ein synthetisch geliefertes Control Event, prüfen die Relationen und vergleichen anschließend alle nichtflüchtigen Strukturwerte. Alte `replay-a`-/`replay-b`-Ausgaben oder Datenbanken werden weder gelöscht noch wiederverwendet. Das erzeugte `ig1-evidence-index.json` kennzeichnet das Paket ausdrücklich nur als Kandidat und trifft keine IG1-Entscheidung.

Das W1-Manifest `bms.w1-run-manifest` ergänzt den bestehenden leichten Run-Manifest-Typ additiv um Specification-Manifest-Hash, Python-/SQLite-Version, Migrationen mit Checksums und die drei technischen Artefakt-IDs. W2-Felder wie Mapping-, SSOT-, Monitoring-, Modell-, Snapshot- oder Ergebnisversionen werden nicht vorgezogen.

Die vollständige technische IG1-Kandidaten-Evidence einschließlich Repository-Preflight, leichtem Smoke, Gesamttestbericht, `git diff --check`, Git-Status und dem unveränderten integrierten W1-Smoke wird reproduzierbar mit einem neuen Ausgabeverzeichnis erzeugt:

```bash
python -m bms w1-ig1-evidence --output-dir .runs/w1-ig1-candidate
```

Der Lauf zeichnet einen Dirty-Worktree wahrheitsgemäß auf, ohne deshalb im Entwicklungsmodus fehlzuschlagen. Für einen finalen Post-Commit-Kandidaten erzwingt `--require-clean` zusätzlich einen sauberen Worktree. Auch diese Orchestrierung erzeugt ausschließlich technische Kandidaten-Evidence; `ig1_decision` bleibt `NOT_MADE`.

## W2-C1 Source-Smoke

Der C1-Pfad arbeitet ausschließlich offline mit der archivierten Pilotfixture. Er prüft Contract, SHA-256, Bytelänge und `entities.Q969725.id`, speichert die Originalbytes unverändert, erzeugt Raw Observation und Import Envelope und führt CTL-K0-001, -002, -003, -004, -005 und -008 tatsächlich aus. G1 wird anschließend aus den persistierten Control Events abgeleitet.

```bash
python -m bms w2-c1-smoke \
  --fixture-dir pilot_data/w2/fixtures/w2-pilot-01 \
  --output-dir .runs/w2-c1-review
```

Der Lauf verwendet eine frische SQLite-Datenbank und erzeugt `fixture-validation.json`, `import-report.json`, `k0-control-report.json`, `g1-decision.json`, `run-manifest.json`, `migration-report.json`, `scope-guard.json`, `smoke-report.json` und `evidence-index.json`. Ein nichtleeres Ausgabeverzeichnis wird nicht wiederverwendet.

## W2-C2 Mapping-Smoke

Der integrierte C2-Smoke führt auf einer frischen Datenbank den realen Pfad Fixture → C1 → Mapping → K1 → G2 aus:

```bash
python -m bms w2-c2-smoke \
  --fixture-dir pilot_data/w2/fixtures/w2-pilot-01 \
  --output-dir .runs/w2-c2-review
```

Für Pilot 01 wird keine interne Spieleridentität erfunden. Die unbekannte Wikidata-ID erzeugt genau einen Mapping-Prüfdatensatz mit `REVIEW_REQUIRED`, CTL-K1-001 und G2 `BLOCKED`; der Smoke meldet bei diesem fachlich erwarteten Blockadepfad `PASS`. Zusätzliche Evidence-Artefakte dokumentieren Mapping, K1 und G2 maschinenlesbar.

## Repositorystruktur

```text
.
├── .gitignore
├── .python-version
├── AGENTS.md
├── README.md
├── pyproject.toml
├── bms/
│   ├── __init__.py
│   ├── __main__.py
│   ├── control_events.py
│   ├── imports.py
│   ├── mapping.py
│   ├── manifests.py
│   ├── persistence.py
│   ├── storage.py
│   ├── w1_ig1_evidence.py
│   ├── w1_smoke.py
│   ├── w2_c1.py
│   └── w2_c2.py
├── migrations/
│   ├── 0001_raw_evidence.sql
│   ├── 0002_control_event.sql
│   ├── 0003_import_envelope.sql
│   └── 0004_mapping_review.sql
├── spec/
│   └── specification-manifest.json
└── tests/
    ├── test_environment.py
    ├── test_control_events.py
    ├── test_manifests.py
    ├── test_migrations.py
    ├── test_smoke.py
    ├── test_storage.py
    ├── test_w1_ig1_evidence.py
    ├── test_w1_smoke.py
    ├── test_w2_c1_source.py
    └── test_w2_c2_mapping.py
```

## Scope-Grenze W2-C2

W2-C2 endet nach Mapping, Review, K1 und G2. Nicht enthalten sind Netzwerkabruf, generische Adapter-/Gate-Architektur, SSOT-Produktionsobjekte oder -Versionen, K2/G3, Monitoring, Eligibility, Prognose/Empfehlung, Snapshot, Managerentscheidung, Ergebnis/Evaluation, UI oder Deployment.

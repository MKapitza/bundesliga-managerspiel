# Bundesliga-Managerspiel — MS2-W1/C3 Control Event Persistence

Minimaler technischer Bootstrap aus MS2-W0/I1 mit dem SQLite-/Migrationsfundament aus **MS2-W1/C1**, der unveränderlichen Raw-/Evidence-Persistenz aus **C2** und der persistenten Control-Event-Grundlage aus **C3**. Dieser Stand führt bewusst keine Kontrolle K0–K7 und kein Gate G1–G7 aus.

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

Versionierte Anwendungsmigrationen liegen unter `migrations/` und folgen der Konvention `NNNN_description.sql`. `0001_raw_evidence.sql` erzeugt `evidence_artifact` und `raw_observation`; `0002_control_event.sql` ergänzt ausschließlich `control_event`. Die technische Migrationshistorie bleibt in `schema_migrations`. Fremdschlüssel werden pro Verbindung aktiviert, und Datenbanktrigger verhindern UPDATE und DELETE der unveränderlichen C2-/C3-Datensätze.

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
│   ├── manifests.py
│   ├── persistence.py
│   └── storage.py
├── migrations/
│   ├── 0001_raw_evidence.sql
│   └── 0002_control_event.sql
├── spec/
│   └── specification-manifest.json
└── tests/
    ├── test_environment.py
    ├── test_control_events.py
    ├── test_manifests.py
    ├── test_migrations.py
    ├── test_smoke.py
    └── test_storage.py
```

## Scope-Grenze C3

C3 ergänzt ausschließlich die Persistenz bereits bestimmter Control Events. Es enthält keinen Kontrollkatalog-Executor, keine Ableitung von Severity, Check-Status oder Blockwirkung und keine tatsächliche Blockade-/Gate-/Release-Entscheidung. Ebenfalls nicht enthalten sind reale Quellenadapter oder Parser, Import-Batches, Mapping, SSOT, Monitoring, Prognose/Empfehlung, Snapshot, Managerentscheidung, Ergebnis/Evaluation, UI, Deployment oder vorsorgliche Plattformarchitektur.

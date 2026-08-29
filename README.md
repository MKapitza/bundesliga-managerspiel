# Bundesliga-Managerspiel — MS2-W1/C2 Raw Observation + Evidence

Minimaler technischer Bootstrap aus MS2-W0/I1 mit dem SQLite-/Migrationsfundament aus **MS2-W1/C1** und der unveränderlichen Raw-/Evidence-Persistenz aus **MS2-W1/C2**. Dieser Stand implementiert bewusst noch keine fachliche Managerspiel-Pipeline, K0-Ausführung oder G1-Logik.

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

Versionierte Anwendungsmigrationen liegen unter `migrations/` und folgen der Konvention `NNNN_description.sql`. `0001_raw_evidence.sql` erzeugt ausschließlich `evidence_artifact` und `raw_observation`; die technische Migrationshistorie bleibt in `schema_migrations`. Fremdschlüssel werden pro Verbindung aktiviert, und Datenbanktrigger verhindern UPDATE und DELETE beider C2-Tabellen.

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

## Lokaler Test- und Smoke-Weg

Im Repository-Root ausführen:

```bash
python -m unittest discover -s tests -v
```

Dieser Lauf prüft die bestehende W0/C1-Basis sowie Migration, Byte-Roundtrip, Integrität, fehlende Hash-Deduplizierung, Referenzen, Unveränderlichkeit, Korrekturkette, Run-Traceability, exakte Zeittext-Erhaltung und die C2-Scope-Grenze.

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
│   ├── manifests.py
│   ├── persistence.py
│   └── storage.py
├── migrations/
│   └── 0001_raw_evidence.sql
├── spec/
│   └── specification-manifest.json
└── tests/
    ├── test_environment.py
    ├── test_manifests.py
    ├── test_migrations.py
    ├── test_smoke.py
    └── test_storage.py
```

## Scope-Grenze C2

C2 enthält nur die technische Speicherung unveränderlicher Evidence-Bytes und minimaler Raw Observations. Nicht enthalten sind reale Quellenadapter oder Parser, Import-Batches, fachliche Rohwerte oder Statusräume, Control Events, Mapping, SSOT, Monitoring, Prognose/Empfehlung, Snapshot, Managerentscheidung, Ergebnis/Evaluation, K0–K7-/G1–G7-Ausführung, UI, Deployment oder vorsorgliche Plattformarchitektur.

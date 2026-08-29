# Bundesliga-Managerspiel — MS2-W1/C1 Fundament

Minimaler technischer Bootstrap aus MS2-W0/I1 mit dem SQLite- und Migrationsfundament aus **MS2-W1/C1**. Dieser Stand implementiert bewusst noch keine fachliche Managerspiel-Pipeline oder Produkttabellen.

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

Versionierte Anwendungsmigrationen liegen künftig unter `migrations/` und folgen der Konvention `NNNN_description.sql`. C1 enthält noch keine Anwendungsmigration: Ein Fresh Setup erzeugt ausschließlich die technische Tabelle `schema_migrations`. Insbesondere werden keine Raw-/Evidence-, Control-Event- oder sonstigen Fachtabellen angelegt.

```bash
python -m bms migrate --db .runs/local.sqlite3
python -m bms schema-version --db .runs/local.sqlite3
```

`migrate` wendet Migrationen atomar in Dateinamenreihenfolge an und prüft bereits angewendete Dateien per SHA-256. `schema-version` gibt den Datenbankpfad, die letzte Migration und die Anzahl angewendeter Migrationen als JSON aus. Lokale Datenbanken (`*.db`, `*.sqlite`, `*.sqlite3`) und die nur lokal vorliegenden `project_sources/` werden nicht versioniert.

## Lokaler Test- und Smoke-Weg

Im Repository-Root ausführen:

```bash
python -m unittest discover -s tests -v
```

Dieser Lauf prüft die bestehende W0-Basis sowie Reihenfolge, Idempotenz, Checksum-Schutz, Rollback, Fresh Rebuild, Schema-Version und Scope-Grenze der C1-Migrationen.

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
│   └── persistence.py
├── spec/
│   └── specification-manifest.json
└── tests/
    ├── test_environment.py
    ├── test_manifests.py
    ├── test_migrations.py
    └── test_smoke.py
```

## Scope-Grenze C1

C1 enthält nur die minimale SQLite-Persistenzbasis, versionierbare SQL-Migrationen, die technische Migrationshistorie, CLI und Tests. Nicht enthalten sind Produkttabellen oder reale Rohdatenimporte, Evidence/Control Events, Mapping, SSOT, Monitoring, Prognose/Empfehlung, Snapshot, Managerentscheidung, Ergebnis/Evaluation, K0–K7-/G1–G7-Ausführung, UI, Deployment oder vorsorgliche Plattformarchitektur.

# Bundesliga-Managerspiel — MS2-W0/I1 Bootstrap

Minimaler technischer Bootstrap für **MS2-W0 / I1**. Dieser Stand implementiert bewusst noch keine fachliche Managerspiel-Pipeline.

## Stack-Entscheidung

- Python 3.13 (lokal auf `3.13.5` gepinnt)
- ausschließlich Python-Standardbibliothek; keine Drittanbieter-Abhängigkeiten
- `unittest` als Testwerkzeug
- JSON für Specification Manifest und Run-Manifest
- Git als technische Versionsreferenz

Damit bleiben lokale Ausführung, Testbarkeit und Reproduzierbarkeit mit minimaler Infrastruktur erhalten. Eine Datenbank, Migrationen, UI, Deployment, Adapter-Frameworks und fachliche Pipeline-Schritte werden in I1 ausdrücklich nicht vorgezogen.

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

## Einziger IG0-Start-/Testweg

Im Repository-Root ausführen:

```bash
python -m unittest discover -s tests -v
```

Dieser Lauf prüft automatisiert, dass das Projekt geladen werden kann, das Specification Manifest gültig ist, die registrierten Spezifikationsversionen dem I1-Soll entsprechen, eine eindeutige Run-ID und ein minimales Run-Manifest erzeugt werden können und der CLI-Smoke-Test erfolgreich durchläuft.

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
│   └── manifests.py
├── spec/
│   └── specification-manifest.json
└── tests/
    ├── test_manifests.py
    └── test_smoke.py
```

## Scope-Grenze I1

Nicht enthalten sind reale Rohdatenimporte, Mapping, SSOT, Monitoring, Prognose/Empfehlung, Snapshot, Managerentscheidung, Ergebnis/Evaluation, vollständige Control Events, K0–K7-/G1–G7-Ausführung, produktive Persistenz, UI, Deployment oder vorsorgliche Plattformarchitektur.

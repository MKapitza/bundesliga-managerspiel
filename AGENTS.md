# AGENTS.md — Technische Umsetzung MS2

## Verbindliche Arbeitsregeln

- Vor jeder inhaltlichen Verwendung versionierter Projektquellen ist zuerst `DOC-REG-001` zu prüfen.
- Nur die in `DOC-REG-001` aktuell registrierten Projektquellen sind verbindlich; ältere Fassungen dienen ausschließlich der Historie.
- Keine fachliche Regel, Datenhoheit, Blockade- oder Freigabelogik ohne den vorgesehenen Governance-Prozess ändern oder ergänzen.
- Keine stille SSOT-Überschreibung. Externe oder technische Abweichungen dürfen bestätigte SSOT-Werte nicht in-place ersetzen.
- Pilotrelevante Daten, Korrekturen und Zustände historisieren bzw. versionieren; keine in-place-Überschreibung historisch relevanter Stände.
- Statusräume strikt getrennt halten. Insbesondere `MISSING`, `PENDING`, `ACTUAL_ZERO`, `NOT_APPLICABLE` und fachliche Sonderstatus niemals gleichsetzen oder still ineinander überführen.
- Jeder relevante technische Schritt soll automatisiert testbar sein.
- Kleine, klar abgegrenzte Änderungen sind großen Umbauten vorzuziehen.
- Vor Änderungen vorhandenen Code, Tests und Strukturen prüfen; bestehende Strukturen nicht ohne konkreten Bedarf ersetzen.
- Bei Widerspruch, Spezifikationslücke oder notwendiger fachlicher Abweichung stoppen, den Befund mit betroffenen DOC-/DEC-/REQ-/CON-/MS2-K-/IG-Bezügen formulieren und an Projektsteuerung bzw. zuständigen Fach-Chat eskalieren.
- Keine Architektur, Infrastruktur oder Abstraktionsschicht außerhalb des aktuell beauftragten Inkrements vorziehen.
- Technische Nachweise soweit möglich automatisch aus Code, Tests und Runs erzeugen ("Evidence by execution"). Manuelle Nacherzählung ersetzt keine maschinenlesbaren Nachweise.

## Aktueller I1-Scope

I1 umfasst ausschließlich Repository-Bootstrap, Specification Manifest, minimales Run-ID-/Run-Manifest-Grundgerüst, lokalen Start und Smoke-/Akzeptanztests. Fachpipeline, SSOT, Monitoring, Empfehlung, Snapshot, Ergebnis/Evaluation, vollständige Control Events, produktive Datenbank, UI, Deployment und generische Frameworks sind nicht Bestandteil von I1.

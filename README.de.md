# Scanorama — DIY 3D-LiDAR-Scanner

*Deutsche Version — English version: [README.md](README.md)*

DIY 3D-Laserscanner auf Raspberry Pi 4: Ein **STL27L** 360°-DTOF-LiDAR
ist vertikal montiert (scannt eine Vertikalebene) und wird von einem
**NEMA17**-Stepper um die Stehachse gedreht (Riemenantrieb 3:1,
TMC2209-Treiber).

**Designprinzip von v2:** Der Pi ist ein reines **Aufnahmegerät**. Er
zeichnet den unveränderten LiDAR-Bytestrom, die Motor-Zeitleiste und
Metadaten auf — verlustfrei, ein Ordner pro Scan. Punktwolken-Erzeugung,
Filterung, Registrierung und Fusion passieren später am PC aus den
Rohdaten. Auf dem Pi gibt es keine UI (geplant: 1–2 GPIO-Buttons zum
Scan-Start).

## Schnellstart (auf dem Pi)

```bash
git clone https://github.com/ferengi82/LiDar.git scanorama
cd scanorama
python3 -m venv --system-site-packages venv   # RPi.GPIO kommt vom System
./venv/bin/pip install -e .

# LiDAR-Check (2 s Statistik)
./venv/bin/scanorama selftest

# Standard-Scan: 0–180° Azimut, kontinuierlich 1°/s (~3 min)
./venv/bin/scanorama scan

# Schneller / weniger dicht
./venv/bin/scanorama scan --speed 5

# Schrittmodus: pro Position N LiDAR-Umdrehungen verweilen
./venv/bin/scanorama scan --mode step --az-step 1 --rounds 10

# Motor-Verkabelungstest (10° vor und zurück)
./venv/bin/scanorama motor-test --degrees 10 --back

# Scan-Ordner (erneut) dekodieren (points.npz aus Rohdaten)
./venv/bin/scanorama decode ~/scans/2026-07-02_scan_01_001
```

Scans landen in `~/scans/yyyy-mm-dd_scan_XX_NNN/` — Formatspezifikation:
[docs/DATAFORMAT.de.md](docs/DATAFORMAT.de.md).

## Scan-Modi

| Modus | Funktionsweise | Wann |
|---|---|---|
| **stream** (Default) | Stepper dreht kontinuierlich (`--speed` °/s), Aufnahme läuft parallel | schnell, mechanisch sanft; Dichte über Geschwindigkeit |
| **step** | fahren–verweilen–fahren; Verweildauer = `--rounds` LiDAR-Umdrehungen pro Position | maximale Dichte pro Position |

In beiden Fällen entsteht derselbe verlustfreie Rohdaten-Ordner; der
Azimut wird offline über die Korrelation von Host-Zeitstempeln mit der
Bewegungs-Zeitleiste zugeordnet.

## Repository-Struktur

```
scanorama/            Python-Paket (CLI: "scanorama")
  lidar/            STL27L-Protokoll, verlustfreie Aufnahme, Mock
  motor/            TMC2209 (Default), STSPIN220 (Fallback), Mock, Zeitleiste
  scan/             Session-Ordner, Recorder (stream/step), Offline-Dekodierung
docs/               Hardware, Datenformat, Setup — Englisch + Deutsch
docs/dev/           Arbeitsstand: Entscheidungen, Roadmap, Status
tests/              pytest-Suite, läuft ohne Hardware (inkl. echter Fixture)
scripts/deploy.sh   rsync auf den Pi + editable install
```

## Dokumentation

- [docs/HARDWARE.de.md](docs/HARDWARE.de.md) — Komponenten, Verkabelung, Protokoll
- [docs/DATAFORMAT.de.md](docs/DATAFORMAT.de.md) — Rohdatenformat (PC-Pipeline!)
- [docs/SETUP.de.md](docs/SETUP.de.md) — Raspberry-Pi-Einrichtung
- [docs/dev/ROADMAP.md](docs/dev/ROADMAP.md) — was als Nächstes kommt (Buttons, Kameras, PC-Auswertung)

## Entwicklung

```bash
python3 -m venv venv && ./venv/bin/pip install -e ".[dev]"
./venv/bin/pytest             # Tests, keine Hardware nötig
scripts/deploy.sh --test      # Sync auf den Pi + Tests dort ausführen
```

## Lizenz

MIT — siehe [LICENSE](LICENSE).

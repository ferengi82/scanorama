# Arbeitsstand

> Diese Datei wird laufend gepflegt, damit die Arbeit jederzeit ohne
> Kontextverlust fortgesetzt werden kann. Neuester Eintrag oben.

## 2026-07-02 (abends) — v1 auf dem Gerät validiert ✓

**Gerätetests (alle bestanden):**
- Deploy per `scripts/deploy.sh` (venv braucht `--system-site-packages`
  für RPi.GPIO!), pytest auf dem Pi: alle Tests grün
- `pilidar selftest`: 1804 Frames/s, Rotor 9.9 Hz, CRC-Quote ~0.03 %
- Echte 3-s-Fixture aufgenommen → `tests/fixtures/stl27l_3s.bin` + Tests
- `pilidar motor-test`: TMC2209 erkannt (IC 0x21), 1/64 Microsteps,
  10° vor/zurück exakt
- 30°-Stream-Scan (2°/s): 339 358 Punkte, Azimut monoton 0→30°,
  100 % Elevations-Bin-Abdeckung
- Schrittmodus (3 Positionen): funktioniert, Verweildauer aus gemessener
  Rotordrehzahl
- **Referenzscan 180° @ 1°/s** (`pi:~/scans-v2/2026-07-02_scan_01_003/`):
  184 s, 15.6 MB roh, 331 320 Frames, **1 CRC-Fehler gesamt (3e-6)**,
  3 926 604 Punkte @ 21 331 Punkte/s, Decode auf dem Pi ~16 s

**Bekannte Eigenheiten (unschädlich, dokumentiert):**
- Reale Drehrate ~4 % unter Soll (sleep-Overhead pro Step). Die
  Zeitleiste zeichnet Ist-Zeiten/Positionen auf → Azimut-Zuordnung
  bleibt korrekt. Falls exakte Rate mal wichtig wird: Busy-Wait oder
  Delay-Kalibrierung.
- Mock-LiDAR berechnet eine Rotor-Umdrehung vor (Python-CRC zu langsam
  für Echtzeit-Erzeugung bei time_scale 60).

**Nächste Schritte:** siehe ROADMAP.md v1.x (GPIO-Buttons, Homing) und
v3 (PC-Auswertung der Rohdaten).

## 2026-07-02 — Projektstart, Kern implementiert

**Erledigt:**
- Kickoff-Interview geführt, Entscheidungen in `DECISIONS.md`
- SSH-Zugang zum Pi eingerichtet (`ssh pilidar`, Key `id_pilidar`);
  Pi-Umgebung geprüft: Python 3.11.2, dialout/gpio-Gruppen ok,
  `/dev/ttyUSB0` vorhanden, UART aktiv, 92 GB frei
- Repo `ferengi82/LiDar` nach `/storage/projekte/LiDar2` geklont
- Paket `pilidar` implementiert:
  - `lidar/protocol.py` — STL27L-Frames, CRC8, vektorisierte Extraktion/Dekodierung
  - `lidar/reader.py` — verlustfreie Rohstrom-Aufnahme (lidar_raw.bin + Chunk-Index)
  - `lidar/mock.py` — synthetischer STL27L für Tests
  - `motor/` — TMC2209 (UART-Treiber aus v1 übernommen), STSPIN220, Mock,
    Bewegungs-Zeitleiste
  - `scan/session.py` — Scan-Ordner-Schema + meta.json
  - `scan/recorder.py` — Stream- + Schrittmodus
  - `scan/decode.py` — Rohdaten → points.npz
  - `cli.py` — Subcommands scan / selftest / lidar-test / motor-test / decode
- pytest-Suite (Protokoll, Session, Decode, Recorder end-to-end mit Mocks)

**Nächste Schritte:**
1. Tests lokal grün bekommen, Grundgerüst committen/pushen
2. Deploy auf den Pi (`scripts/deploy.sh`), venv anlegen
3. `pilidar selftest` + `pilidar lidar-test --save` (echte Frame-Fixture holen)
4. `pilidar motor-test` (kleine Drehung, Richtung prüfen)
5. Kurz-Scan 30° Stream + Schrittmodus-Test, Rohdaten zurückholen, Plausibilität
6. Referenz-Scan 180°, Doku fertigstellen

**Offene Fragen / Risiken:**
- Rotordrehzahl STL27L laut Datenblatt 10 Hz — v1-Kommentare erwähnten
  teils ~75 Hz (vermutlich Verwechslung mit Frame-Rate). Auf dem Gerät
  verifizieren (Selftest zeigt `motor_hz_mean`).
- CPU-Last der Offline-Dekodierung auf dem Pi bei großen Scans prüfen
  (vektorisiert, sollte <30 s für 180°-Scan sein).

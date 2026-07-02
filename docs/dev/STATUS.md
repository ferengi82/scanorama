# Arbeitsstand

> Diese Datei wird laufend gepflegt, damit die Arbeit jederzeit ohne
> Kontextverlust fortgesetzt werden kann. Neuester Eintrag oben.

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

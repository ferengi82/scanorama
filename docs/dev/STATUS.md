# Arbeitsstand

## 2026-07-04 — Strahlkalibrierung (Naht-Fehler gelöst)

- **Befund**: Die Naht-Differenz bei 180°-Scans (einige cm) kommt NICHT
  von Motor/Mechanik (Foto-Beweis: 360°-Drehung auf 0,02° exakt,
  3× reproduzierbar) und nicht von Exzentrizität (<0,5 mm!), sondern
  vom **Strahl selbst**: Der STL27L-Strahl liegt nicht exakt in der
  Rotorebene (Skew ~0,4° + Wobble ~0,9° + Halbebenen-Versatz ~−1,4°).
- Diagnose per Zwei-Lagen-Analyse (3× 360°-Scan): jede Richtung wird
  von vorderer UND hinterer Halbebene gemessen, Differenzfeld verrät
  die Fehlerform. Naht: 38,8 mm → **2,9 mm** nach Kalibrierung.
- Neu: `scanorama/lidar/calibration.py` (Loader wie cameras.json),
  meta.json-Block `calibration` (+ `model`-Formel), Doku DATAFORMAT
- Werte auf dem Pi installiert: `~/.config/scanorama/calibration.json`
  (gefittet aus 2026-07-04_scan_01_002)
- Studio: volles Strahlmodell in `transform.py`, Auto-Anwendung aus
  meta.json, `scanorama-studio-cli calibrate <360°-Scan>`, Panel-Felder

## 2026-07-03 — v2: Kamera-Integration (Fotorunde + Mounts in meta.json)

- Neues Paket `scanorama/camera/` (Controller-Port aus v1, Mounts mit
  kalibrierten Defaults + `~/.config/scanorama/cameras.json`, Mock)
- Fotorunde im Recorder: Default an, 10° = 36 Positionen (User-Anforderung
  ≥80 % Überlappung bei ~66° HFOV), Kamera-Ausfall bricht Scan nicht ab
- meta.json: `cameras`-Block (mounts, locked_params, pose_recipe) +
  `photos[]` (file, cam_id, azimuth_deg, t_ns)
- CLI: `--no-photos/--photo-step/--photo-settle/--usb-cam`, neu `camera-test`
- Studio: Transfer lädt jetzt rekursiv (photos/-Unterordner)
- Tests: Mock-Fotorunde, Mounts, Ausfall — Gerätetest steht aus

> Diese Datei wird laufend gepflegt, damit die Arbeit jederzeit ohne
> Kontextverlust fortgesetzt werden kann. Neuester Eintrag oben.

## 2026-07-03 — Umbenennung pilidar → scanorama

- Paket, CLI, Doku, Tests, deploy.sh vollständig umbenannt; alle
  Referenzen auf fremde Projekte entfernt (inkl. README-Credits)
- Dev-Maschine: SSH-Alias `scanorama`, Key `~/.ssh/id_scanorama`
- **Pi war offline** — dort steht noch das alte `~/pilidar`. Beim
  nächsten Kontakt: `scripts/deploy.sh --test` (legt `~/scanorama` an),
  danach altes `~/pilidar` löschen. Optional: Pi-Hostname `PiLiDAR`
  umbenennen (Entscheidung des Users).

## 2026-07-02 (abends) — v1 auf dem Gerät validiert ✓

**Gerätetests (alle bestanden):**
- Deploy per `scripts/deploy.sh` (venv braucht `--system-site-packages`
  für RPi.GPIO!), pytest auf dem Pi: alle Tests grün
- `scanorama selftest`: 1804 Frames/s, Rotor 9.9 Hz, CRC-Quote ~0.03 %
- Echte 3-s-Fixture aufgenommen → `tests/fixtures/stl27l_3s.bin` + Tests
- `scanorama motor-test`: TMC2209 erkannt (IC 0x21), 1/64 Microsteps,
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
- SSH-Zugang zum Pi eingerichtet (`ssh scanorama`, Key `id_scanorama`);
  Pi-Umgebung geprüft: Python 3.11.2, dialout/gpio-Gruppen ok,
  `/dev/ttyUSB0` vorhanden, UART aktiv, 92 GB frei
- Repo `ferengi82/LiDar` nach `/storage/projekte/LiDar2` geklont
- Paket `scanorama` implementiert:
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
3. `scanorama selftest` + `scanorama lidar-test --save` (echte Frame-Fixture holen)
4. `scanorama motor-test` (kleine Drehung, Richtung prüfen)
5. Kurz-Scan 30° Stream + Schrittmodus-Test, Rohdaten zurückholen, Plausibilität
6. Referenz-Scan 180°, Doku fertigstellen

**Offene Fragen / Risiken:**
- Rotordrehzahl STL27L laut Datenblatt 10 Hz — v1-Kommentare erwähnten
  teils ~75 Hz (vermutlich Verwechslung mit Frame-Rate). Auf dem Gerät
  verifizieren (Selftest zeigt `motor_hz_mean`).
- CPU-Last der Offline-Dekodierung auf dem Pi bei großen Scans prüfen
  (vektorisiert, sollte <30 s für 180°-Scan sein).

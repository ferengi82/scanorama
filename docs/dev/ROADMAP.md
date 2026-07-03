# Roadmap

## v1 — Saubere Rohdaten vom Pi (AKTUELL)

- [x] Paketstruktur `scanorama/` (lidar / motor / scan / cli)
- [x] STL27L-Protokoll + vektorisierte Offline-Dekodierung
- [x] Verlustfreie Rohstrom-Aufnahme mit Chunk-Zeitstempeln
- [x] Motor: TMC2209 (Default), STSPIN220 (Fallback), Mock; Bewegungs-Zeitleiste
- [x] Recorder: Stream- und Schrittmodus, Scan-Ordner + meta.json
- [x] pytest-Suite ohne Hardware (Mocks)
- [x] Gerätetests auf dem Pi (Selftest, Motor, Kurz-Scans, Plausibilität)
- [x] Referenz-Scan 180° als Validierungsdatensatz (pi:~/scans-v2/2026-07-02_scan_01_003)
- [x] Doku DE/EN vollständig

## v1.x — Betriebskomfort

- [ ] GPIO-Buttons (1–2 Stück) zum Scan-Start ohne SSH
      (Button-Daemon ruft einfach `scanorama scan` auf; systemd-Unit)
- [ ] Status-LED oder Buzzer (Scan läuft / fertig / Fehler)
- [ ] Endschalter + Referenzfahrt (Homing) für reproduzierbaren Azimut-Nullpunkt
- [ ] `scanorama`-Selbstdiagnose erweitern (TMC2209 DRV_STATUS in meta.json)

## v2 — Kameras

- [x] Fotorunde mit 3× IMX179 (Port aus v1; Default an, 10°-Schritte ≥80 % Überlappung)
- [x] Kamera-Metadaten (Mount-Geometrie, AE/AWB-Locks, pose_recipe) in meta.json
- [x] Fotos im Scan-Ordner (photos/), Azimut+Zeit pro Foto

## v3 — PC-Auswertung (separates Modul/Repo-Teil)

- [ ] Rohdaten → Punktwolke (PLY/E57/LAS) mit Filtern
      (Stativ-Bereich, Nahbereich, Ausreißer), el_offset-Kalibrierung
- [ ] Registrierung/Fusion mehrerer Standpunkte (Nachfolger merge_scans.py)
- [ ] Metashape-Export (Nachfolger export_metashape.py)

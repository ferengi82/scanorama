# Entscheidungen (Interview + Architektur)

Ergebnis des Kickoff-Interviews vom 2026-07-02 und der daraus abgeleiteten
Architekturentscheidungen. Diese Datei ist die Referenz, wenn Arbeit an
diesem Projekt fortgesetzt wird.

## Interview-Ergebnisse (User-Entscheidungen)

| Thema | Entscheidung |
|---|---|
| Architektur | **Nur CLI, keine UI auf dem Pi.** Später 1–2 GPIO-Buttons zum Scan-Start. Der Pi zeichnet LiDAR-Daten, (später) Fotos und Metadaten auf — die Auswertung erfolgt am PC. |
| Ziele der Neuentwicklung | Datenqualität, Rohdaten-Speicherung, Code-Struktur |
| Umfang v1 | Nur LiDAR (Kamera-Fotorunde folgt später) |
| Pi-Output | **Nur Rohdaten** — keine PLY-/Punktwolkenberechnung auf dem Pi |
| Rohformat | **Beides**: binäre Roh-Daten (Master) + dekodierte Punkttabelle (Komfort) |
| Scan-Modi | Stream (kontinuierlich, Default) **und** Schrittmodus |
| Repo | Entwicklung in `/storage/projekte/LiDar2`, Push auf `ferengi82/LiDar` main. Altes Projekt bleibt lokal unter `/storage/projekte/LiDar`. |
| Doku | `README.md` (EN) + `README.de.md` (DE), docs ebenso zweisprachig. Code-Kommentare und Logs auf Deutsch. |
| Lizenz | MIT. Es wurde kein fremder Code übernommen (eigener Code + portierter v1-Code). |
| Tests auf dem Pi | Claude darf **selbständig** testen, inklusive Motor-Drehung. |

## Architekturentscheidungen

### A1: Roher Bytestrom statt extrahierter Frames

**Entscheidung:** Die Aufnahme schreibt den unveränderten seriellen
Bytestrom (`lidar_raw.bin`) plus einen Chunk-Index mit Host-Zeitstempeln
(`lidar_index.npz`). Frame-Extraktion, CRC-Prüfung und Dekodierung passieren
**offline** (`scanorama/scan/decode.py`).

**Warum:** Die Capture-Schleife macht dadurch nichts außer `read()` +
`write()` — kein Parsing, kein Datenverlust-Risiko, maximal ehrliche
Rohdaten (sogar CRC-fehlerhafte Frames bleiben erhalten). Der Plan sah
ursprünglich extrahierte 47-Byte-Frames vor; der Stream-Dump ist die
konsequentere Variante desselben Gedankens.

### A2: Azimut über Zeitkorrelation, nicht über Mitschreiben pro Punkt

Der Motor protokolliert Bewegungs-Ereignisse (`motor_timeline.csv`:
t_ns, event, azimuth_deg). Da zwischen den Ereignissen konstante
Geschwindigkeit herrscht, ist Azimut(t) per linearer Interpolation exakt.
Jeder Lese-Chunk bekommt einen `time.monotonic_ns()`-Stempel; bei 1°/s
Drehgeschwindigkeit entspricht 1 ms Zeitfehler nur 0.001° Azimut.

### A3: Keine Filter auf dem Pi

Stativ-Bereich (alt: el 165°–195°), Nahbereich (alt: <0.30 m) und
Ausreißer bleiben in den Rohdaten. Filterung ist Sache der PC-Pipeline.
Die Geometrie-Konvention (Elevation 0° = oben, Umrechnungsformel) steht
in jeder `meta.json`, damit die Rohdaten selbsterklärend sind.

### A4: Schrittmodus = durchgehende Aufnahme + Zeitleiste

Auch im Schrittmodus wird durchgehend aufgezeichnet (inkl. Fahrphasen).
Die Verweildauer pro Position wird aus der im Selftest gemessenen
Rotordrehzahl berechnet (`rounds / rotor_hz × 1.1`). Die PC-Auswertung
trennt Steh- und Fahrphasen über die move_start/move_end-Ereignisse.

### A5: Bewährten Code portieren statt neu erfinden

- `tmc2209_uart.py` (funktionierender UART-Treiber) → unverändert übernommen
- CRC-Tabelle + Frame-Format aus v1 → `scanorama/lidar/protocol.py` (vektorisiert)
- Stream-Stepper-Logik (STEP/DIR-Pulse per Thread) → `scanorama/motor/base.py`
- Ordner-Namensschema `yyyy-mm-dd_scan_XX_NNN` → `scanorama/scan/session.py`

### A6: Kein Homing in v1

Azimut ist relativ zur Startposition beim Programmstart (wie v1).
Endschalter/Referenzfahrt steht auf der Roadmap.

### A7: Name "scanorama" (2026-07-03)

Das Paket hieß zunächst "pilidar" — das klang wie das fremde
PiLiDAR-Projekt. Der User wünscht keinerlei Referenzen auf andere
Projekte (auch keine Credits im README). Neuer Name: **scanorama**
(Scan + Panorama), Paket + CLI. SSH-Alias und Key der Dev-Maschine
wurden auf `scanorama`/`id_scanorama` umbenannt.

## Hardware-Zugang (für Entwicklung)

- Pi: `ssh scanorama` (Host-Eintrag in `~/.ssh/config` der Dev-Maschine,
  Key `~/.ssh/id_scanorama`, IP 10.0.234.34, User `pi`)
- Passwörter werden **nicht** in Dateien gespeichert.
- LiDAR: `/dev/ttyUSB0` @ 921600 · TMC2209-UART: `/dev/ttyAMA0`
- Deployment: `scripts/deploy.sh` (rsync nach `~/scanorama` + editable install)

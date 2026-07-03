# Rohdatenformat (ein Ordner pro Scan)

*Deutsche Version — English version: [DATAFORMAT.md](DATAFORMAT.md)*

Jeder Scan erzeugt einen Ordner nach dem Schema
`yyyy-mm-dd_scan_XX_NNN/` (XX = Session, NNN = Standpunkt; neue Session
nach >5 min Pause, neuer Tag setzt alles zurück).

```
2026-07-02_scan_01_001/
├── lidar_raw.bin       Roh-Bytestrom des STL27L (Master-Daten)
├── lidar_index.npz     Chunk-Index: Byte-Offsets + Host-Zeitstempel
├── motor_timeline.csv  Bewegungs-Ereignisse des Drehtellers
├── points.npz          dekodierte Punkttabelle (Komfortformat)
├── meta.json           Parameter, Gerät, Zeitanker, Statistik
└── scan.log            Logausgabe des Scans
```

**Grundprinzip:** `lidar_raw.bin` + `lidar_index.npz` + `motor_timeline.csv`
sind die verlustfreien Master-Daten. `points.npz` ist daraus jederzeit
reproduzierbar (`scanorama decode <ordner>`) und darf gelöscht/neu erzeugt
werden.

## lidar_raw.bin

Der **unveränderte** serielle Bytestrom des STL27L (921600 Baud), wie er
während der Aufnahme ankam — inklusive eventuell unvollständiger oder
CRC-fehlerhafter Pakete. Paketformat (47 Bytes): siehe
[HARDWARE.de.md](HARDWARE.de.md#stl27l-protokoll). Frame-Extraktion =
Suche nach der Signatur `0x54 0x2C`, dann CRC8-Prüfung über Byte 0–45
gegen Byte 46.

## lidar_index.npz (NumPy-Archiv)

| Array | dtype | Bedeutung |
|---|---|---|
| `chunk_end_offset` | int64 | Byte-Offset in `lidar_raw.bin` **nach** jedem Lese-Chunk |
| `chunk_t_ns` | int64 | `time.monotonic_ns()` des Chunk-Empfangs |

Ein Frame mit Endoffset `e` gilt als empfangen im ersten Chunk mit
`chunk_end_offset ≥ e`. Damit bekommt jedes Frame einen Host-Zeitstempel
mit ~1 ms Genauigkeit (bei 1°/s Drehung = 0.001° Azimutfehler).

## motor_timeline.csv

```csv
t_ns,event,azimuth_deg
123456789,init,0.000000
123456999,seg_start,0.000000
303456789,seg_end,180.000000
```

- `t_ns` — `time.monotonic_ns()` (gleiche Uhr wie `chunk_t_ns`!)
- `event` — `init`, `seg_start`/`seg_end` (kontinuierliche Fahrt),
  `move_start`/`move_end` (Positionierfahrt im Schrittmodus)
- `azimuth_deg` — Drehteller-Position am Abtrieb, relativ zur Position
  beim Scan-Start (kein Homing in v1)

Zwischen zwei Ereignissen fährt der Motor mit konstanter Geschwindigkeit
→ **Azimut(t) = lineare Interpolation** über alle Ereignispunkte.
Im Schrittmodus stehen zwischen `move_end` und dem nächsten `move_start`
die Verweilphasen (Azimut konstant).

## points.npz (NumPy-Archiv, Komfortformat)

Ein Eintrag pro gültigem Messpunkt (CRC ok, Distanz > 0), **ungefiltert**
(Stativ-Bereich, Nahbereich und Ausreißer enthalten!):

| Array | dtype | Bedeutung |
|---|---|---|
| `t_ns` | int64 | Host-Empfangszeit (monotonic) |
| `elevation_deg` | float32 | nativer LiDAR-Winkel, 0° = oben (s.u.) |
| `azimuth_deg` | float32 | interpolierte Drehteller-Position |
| `distance_mm` | uint16 | Distanz in Millimetern |
| `intensity` | uint8 | Rückstrahlstärke |

## meta.json

Selbsterklärend; wichtigste Blöcke:

- `time_anchor` — Wandzeit + `monotonic_ns` im selben Moment: damit
  lassen sich alle `t_ns`-Werte in absolute Zeit umrechnen.
- `config` — vollständige Scanner-Konfiguration (Ports, Pins,
  Übersetzung, Scan-Parameter).
- `geometry` — Geometrie-Konvention (siehe unten), damit der Ordner
  ohne Zusatzwissen auswertbar ist.
- `selftest`, `capture`, `decode` — Statistik (Frames, CRC-Quote,
  Punktzahl, Rotordrehzahl …).

## Geometrie-Konvention

- LiDAR **vertikal** montiert, scannt eine Vertikalebene.
- `elevation_deg`: 0° = direkt nach **oben** (Z+), 90° = horizontal
  vorwärts, 180° = unten, 270° = horizontal rückwärts.
  (Feinkalibrierung `el_offset` ist Sache der PC-Pipeline.)
- `azimuth_deg`: Drehung um die Stehachse (Z), positiv in
  Motor-Drehrichtung (Aufbau: nicht invertiert).
- Kartesisch (rechtshändig, X=rechts, Y=vorne bei az=0, Z=oben,
  Ursprung = Schnittpunkt Drehachse/Scanebene):

```
r = distance_mm / 1000            # Meter
z = r · cos(elevation)
h = r · sin(elevation)            # Horizontalabstand
x = h · sin(azimuth)
y = h · cos(azimuth)
```

- 180° Azimut genügen für eine Vollkugel: der vertikale 360°-Scan
  deckt pro Stellung beide Seiten ab.

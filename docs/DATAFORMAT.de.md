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
├── photos/             Fotorunde: JPEGs der 3 USB-Kameras
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
- `calibration` — Strahlkalibrierung des Geräts (siehe unten).
- `selftest`, `capture`, `decode` — Statistik (Frames, CRC-Quote,
  Punktzahl, Rotordrehzahl …).

## Geometrie-Konvention

- LiDAR **vertikal** montiert, scannt eine Vertikalebene.
- `elevation_deg`: 0° = direkt nach **oben** (Z+), 90° = horizontal
  vorwärts, 180° = unten, 270° = horizontal rückwärts.
  (Feinkorrektur: siehe `calibration`-Block.)
- `azimuth_deg`: Drehung um die Stehachse (Z). Mit `invert_dir=true`
  (Default seit 2026-07-04) ist das System realitätstreu; ältere Scans
  (invert_dir=false in der meta.json) sind spiegelverkehrt.
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

## Strahlkalibrierung (`calibration`-Block)

Der reale Laserstrahl weicht leicht von der idealen Vertikalebene ab —
ohne Korrektur passen die beiden Halbebenen (vorn el≤180°, hinten
el>180°) azimutal nicht exakt aufeinander („Naht" bei 180°-Scans,
einige cm an schrägen Flächen). Vier Winkel (Grad) beschreiben das:

| Feld | Bedeutung |
|---|---|
| `el_offset_deg` | Rotor-Nullpunkt: wahre Elevation = el + Offset |
| `beam_skew_deg` | Strahl zeigt konstant seitlich aus der Rotorebene (ω0) |
| `beam_wobble_deg` | elevationsabhängiger Seitwärtsanteil: ω(el) = ω0 + ω1·cos(el) |
| `halfplane_split_deg` | Azimut-Versatz der Halbebenen: el>180° um +split/2, el≤180° um −split/2 um Z gedreht |

Präzises Strahlmodell (ersetzt die einfache Formel oben; `model`-Feld
im Block dokumentiert es maschinenlesbar):

```
el' = el + el_offset
ω   = beam_skew + beam_wobble·cos(el)
d   = cos ω·(cos el'·ẑ + sin el'·ŷ) + sin ω·x̂     (Plattform-Frame)
d   um ±halfplane_split/2 um ẑ gedreht (+ für el>180°)
P   = r · R_z(azimuth) · d
```

Bestimmung: `scanorama-studio-cli calibrate <360°-Scan>` (Zwei-Lagen-
Analyse wie beim Theodolit — bei einem vollen 360°-Scan wird jede
Richtung von beiden Halbebenen gemessen). Ablage auf dem Pi:
`~/.config/scanorama/calibration.json` — der Scanner trägt die Werte
dann in jede meta.json ein, die PC-Auswertung wendet sie automatisch an.

## photos/ + Kamera-Blöcke in meta.json

Nach dem LiDAR-Scan fährt der Teller 360° in `photo_step_deg`-Schritten
ab (Default 10° = 36 Positionen) und löst an jedem Stopp alle Kameras
aus: `photos/photo_{NN}_az{AAA}_{cam_id}.jpg`. Belichtung/Weißabgleich
werden vor der Runde auf der ersten Kamera gemessen und für alle
gelockt (`cameras.locked_params`).

meta.json enthält dazu:

- **`cameras.mounts`** — Einbaulage jeder Kamera relativ zur Drehachse
  (kalibrierte Werte): `r_cam_m`, `z_cam_m`, `az_offset_deg`,
  `yaw/pitch/roll_mount_deg`, `device`
- **`cameras.pose_recipe`** — Formel, mit der die PC-Auswertung aus
  Foto-Azimut + Mount die globale Kamerapose berechnet:
  Position x=r·sin(az+az_off), y=r·cos(az+az_off), z=z_cam;
  Orientierung yaw=az+az_off+yaw_mount, pitch=pitch_mount, roll=roll_mount
- **`photos[]`** — pro Foto: `file`, `cam_id`, `index`,
  `azimuth_deg` (Plattform-Azimut, gleiche Referenz wie die
  LiDAR-Azimute!) und `t_ns`
- `cameras.status` — `ok` / `failed` (Kameras nicht verfügbar; der
  LiDAR-Scan bleibt gültig) / `disabled` (`--no-photos`)

Mount-Overrides auf dem Pi: `~/.config/scanorama/cameras.json`.

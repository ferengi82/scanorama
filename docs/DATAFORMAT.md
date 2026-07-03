# Raw Data Format (one folder per scan)

*English version — deutsche Version: [DATAFORMAT.de.md](DATAFORMAT.de.md)*

Each scan produces a folder named
`yyyy-mm-dd_scan_XX_NNN/` (XX = session, NNN = station; a new session
starts after a >5 min pause, a new day resets everything).

```
2026-07-02_scan_01_001/
├── lidar_raw.bin       raw STL27L byte stream (master data)
├── lidar_index.npz     chunk index: byte offsets + host timestamps
├── motor_timeline.csv  turntable motion events
├── points.npz          decoded point table (convenience format)
├── meta.json           parameters, device, time anchor, statistics
├── photos/             photo round: JPEGs from the 3 USB cameras
└── scan.log            log output of the scan
```

**Core principle:** `lidar_raw.bin` + `lidar_index.npz` +
`motor_timeline.csv` are the lossless master data. `points.npz` can be
reproduced from them at any time (`scanorama decode <folder>`) and may be
deleted/regenerated.

## lidar_raw.bin

The **unmodified** serial byte stream of the STL27L (921600 baud) as it
arrived during capture — including incomplete or CRC-corrupt packets.
Packet format (47 bytes): see [HARDWARE.md](HARDWARE.md#stl27l-protocol).
Frame extraction = search for the signature `0x54 0x2C`, then CRC8 check
of bytes 0–45 against byte 46.

## lidar_index.npz (NumPy archive)

| Array | dtype | Meaning |
|---|---|---|
| `chunk_end_offset` | int64 | byte offset into `lidar_raw.bin` **after** each read chunk |
| `chunk_t_ns` | int64 | `time.monotonic_ns()` when the chunk was received |

A frame ending at byte offset `e` counts as received in the first chunk
with `chunk_end_offset ≥ e`. This gives every frame a host timestamp
with ~1 ms accuracy (at 1°/s rotation that is 0.001° of azimuth error).

## motor_timeline.csv

```csv
t_ns,event,azimuth_deg
123456789,init,0.000000
123456999,seg_start,0.000000
303456789,seg_end,180.000000
```

- `t_ns` — `time.monotonic_ns()` (same clock as `chunk_t_ns`!)
- `event` — `init`, `seg_start`/`seg_end` (continuous motion),
  `move_start`/`move_end` (positioning moves in step mode)
- `azimuth_deg` — turntable position at the output shaft, relative to
  the position at scan start (no homing in v1)

Between two events the motor runs at constant speed →
**azimuth(t) = linear interpolation** across all event points.
In step mode, dwell phases (constant azimuth) lie between `move_end`
and the next `move_start`.

## points.npz (NumPy archive, convenience format)

One entry per valid measurement (CRC ok, distance > 0), **unfiltered**
(tripod region, close range and outliers included!):

| Array | dtype | Meaning |
|---|---|---|
| `t_ns` | int64 | host receive time (monotonic) |
| `elevation_deg` | float32 | native LiDAR angle, 0° = up (see below) |
| `azimuth_deg` | float32 | interpolated turntable position |
| `distance_mm` | uint16 | distance in millimetres |
| `intensity` | uint8 | return signal strength |

## meta.json

Self-describing; the most important blocks:

- `time_anchor` — wall time + `monotonic_ns` captured at the same
  instant: converts all `t_ns` values to absolute time.
- `config` — full scanner configuration (ports, pins, gear ratio,
  scan parameters).
- `geometry` — geometry convention (see below) so the folder can be
  processed without external knowledge.
- `selftest`, `capture`, `decode` — statistics (frames, CRC rate,
  point count, rotor speed …).

## Geometry convention

- LiDAR mounted **vertically**, scanning a vertical plane.
- `elevation_deg`: 0° = straight **up** (Z+), 90° = horizontal forward,
  180° = down, 270° = horizontal backward.
  (Fine calibration `el_offset` is the PC pipeline's job.)
- `azimuth_deg`: rotation around the vertical axis (Z), positive in
  motor direction (this build: not inverted).
- Cartesian (right-handed, X=right, Y=forward at az=0, Z=up, origin =
  intersection of rotation axis and scan plane):

```
r = distance_mm / 1000            # metres
z = r · cos(elevation)
h = r · sin(elevation)            # horizontal distance
x = h · sin(azimuth)
y = h · cos(azimuth)
```

- 180° of azimuth suffices for a full sphere: each vertical 360° scan
  covers both sides per position.

## photos/ + camera blocks in meta.json

After the LiDAR scan the turntable sweeps 360° in `photo_step_deg`
steps (default 10° = 36 positions), triggering all cameras at each
stop: `photos/photo_{NN}_az{AAA}_{cam_id}.jpg`. Exposure/white balance
are measured on the first camera and locked for all
(`cameras.locked_params`).

meta.json additionally contains:

- **`cameras.mounts`** — each camera's mounting pose relative to the
  rotation axis (calibrated values): `r_cam_m`, `z_cam_m`,
  `az_offset_deg`, `yaw/pitch/roll_mount_deg`, `device`
- **`cameras.pose_recipe`** — formula for computing each photo's global
  camera pose from photo azimuth + mount: position
  x=r·sin(az+az_off), y=r·cos(az+az_off), z=z_cam; orientation
  yaw=az+az_off+yaw_mount, pitch=pitch_mount, roll=roll_mount
- **`photos[]`** — per photo: `file`, `cam_id`, `index`,
  `azimuth_deg` (platform azimuth, same reference as the LiDAR
  azimuths!) and `t_ns`
- `cameras.status` — `ok` / `failed` (cameras unavailable; the LiDAR
  scan remains valid) / `disabled` (`--no-photos`)

Mount overrides on the Pi: `~/.config/scanorama/cameras.json`.

# Scanorama — DIY 3D LiDAR Scanner

*English — deutsche Version: [README.de.md](README.de.md)*

DIY 3D laser scanner on a Raspberry Pi 4: an **STL27L** 360° DTOF LiDAR
is mounted vertically (scanning a vertical plane) and rotated around the
vertical axis by a **NEMA17** stepper (belt drive 3:1, TMC2209 driver).

**Design principle of v2:** the Pi is a pure **recording device**. It
captures the unmodified LiDAR byte stream, the motor motion timeline and
metadata — losslessly, one folder per scan. Point cloud generation,
filtering, registration and fusion happen later on a PC from the raw
data. There is no UI on the Pi (planned: 1–2 GPIO buttons to trigger
scans).

## Quick start (on the Pi)

```bash
git clone https://github.com/ferengi82/LiDar.git scanorama
cd scanorama
python3 -m venv --system-site-packages venv   # RPi.GPIO comes from the OS
./venv/bin/pip install -e .

# LiDAR check (2 s statistics)
./venv/bin/scanorama selftest

# Standard scan: 0–180° azimuth, continuous 1°/s (~3 min)
./venv/bin/scanorama scan

# Faster / less dense
./venv/bin/scanorama scan --speed 5

# Step mode: dwell at each position for N LiDAR revolutions
./venv/bin/scanorama scan --mode step --az-step 1 --rounds 10

# Motor wiring test (10° forward and back)
./venv/bin/scanorama motor-test --degrees 10 --back

# Re-decode a scan folder (points.npz from raw data)
./venv/bin/scanorama decode ~/scans/2026-07-02_scan_01_001
```

Scans land in `~/scans/yyyy-mm-dd_scan_XX_NNN/` — format specification:
[docs/DATAFORMAT.md](docs/DATAFORMAT.md).

## Scan modes

| Mode | How it works | When to use |
|---|---|---|
| **stream** (default) | stepper rotates continuously (`--speed` °/s), capture runs in parallel | fast, mechanically smooth; density via speed |
| **step** | move–dwell–move; dwell = `--rounds` LiDAR revolutions per position | maximum density per position |

Either way the same lossless raw folder is produced; azimuth is assigned
offline by correlating host timestamps with the motion timeline.

## Repository layout

```
scanorama/            Python package (CLI: "scanorama")
  lidar/            STL27L protocol, lossless capture, mock
  motor/            TMC2209 (default), STSPIN220 (fallback), mock, timeline
  scan/             session folders, recorder (stream/step), offline decode
docs/               hardware, data format, setup — English + German
docs/dev/           working state: decisions, roadmap, status
tests/              pytest suite, runs without hardware (incl. real fixture)
scripts/deploy.sh   rsync to the Pi + editable install
```

## Documentation

- [docs/HARDWARE.md](docs/HARDWARE.md) — components, wiring, protocol
- [docs/DATAFORMAT.md](docs/DATAFORMAT.md) — raw data format (PC pipeline!)
- [docs/SETUP.md](docs/SETUP.md) — Raspberry Pi setup
- [docs/dev/ROADMAP.md](docs/dev/ROADMAP.md) — what's next (buttons, cameras, PC evaluation)

## Development

```bash
python3 -m venv venv && ./venv/bin/pip install -e ".[dev]"
./venv/bin/pytest             # tests, no hardware required
scripts/deploy.sh --test      # sync to the Pi + run tests there
```

## License

MIT — see [LICENSE](LICENSE).

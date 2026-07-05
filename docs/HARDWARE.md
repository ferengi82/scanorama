# Hardware

*English version — deutsche Version: [HARDWARE.de.md](HARDWARE.de.md)*

## Overview

| Component | Description |
|---|---|
| Raspberry Pi 4B | control + recording |
| STL27L | 360° DTOF LiDAR (LDRobot/Waveshare), 25 m, 21,600 points/s, ~10 Hz rotor |
| Adapter board | Waveshare (ESP8266 + CP2102) → `/dev/ttyUSB0` @ 921600 baud, powers the LiDAR with 5 V |
| TMC2209 (default) | stepper driver, STEP/DIR via GPIO + configuration via UART, VM 8–24 V |
| Adafruit STSPIN220 (fallback) | GPIO-only, fixed 1/16 microsteps, VIN **max 10 V!** |
| NEMA17 | stepper, rotates the LiDAR around the vertical axis (azimuth) |
| Belt drive | 20T (motor) → 60T (turntable) = **3:1** (`gear_ratio = 3.0`) |

The STL27L is mounted **vertically** and scans a vertical plane; the
stepper rotates that plane around the vertical axis. 180° of azimuth is
enough for a full sphere.

## Wiring TMC2209 (default driver)

| TMC2209 | Raspberry Pi / power |
|---|---|
| VCC_IO | 3.3 V |
| GND | GND (logic + motor supply common!) |
| STEP | GPIO23 |
| DIR | GPIO24 |
| EN | GPIO25 (active-low) |
| PDN_UART | ← Pi TX (GPIO14) **through 1 kΩ** — single-wire does not work without it! |
| PDN_UART | → Pi RX (GPIO15) directly |
| VM | 8–24 V motor supply |
| A1/A2/B1/B2 | motor coils |

**Enable the Pi UART:** `raspi-config` → Interface Options → Serial →
login shell **off**, hardware UART **on** (`/dev/ttyAMA0`).

UART configuration (done automatically by `scanorama` at startup):
microstepping (default 1/64), StealthChop, current scaling (IRUN=31 =
full potentiometer current → fine-tune via the VREF pot on the board).

## Wiring STSPIN220 (fallback, `--driver stspin220`)

| STSPIN220 | Raspberry Pi / power |
|---|---|
| VCC | 3.3 V |
| GND | GND |
| STEP (STCK) | GPIO23 |
| DIR | GPIO24 |
| EN/FAULT | GPIO25 (active-low) |
| VIN | 5–10 V supply — **max 10 V, never 12 V!** |
| A1/A2/B1/B2 | motor coils |

Fixed 1/16 microstepping (MS pins open), current limit via pot.

## Stepper mechanics

```
steps_per_deg = (200 full steps × microsteps × 3.0 gear) / 360
```

TMC2209 @ 1/64: 106.67 steps/° · STSPIN220 @ 1/16: 26.67 steps/°.
Rotation direction is **inverted** (default since 2026-07-04) — the
Metashape camera calibration proved that scans with the old direction
were mirror images of reality. `--no-invert-dir` restores the old
convention.

## STL27L protocol

- UART 921600 baud 8N1, unidirectional — the LiDAR transmits by itself
  after power-on (~3 s spin-up).
- 47-byte packets with 12 measurement points each:

| Field | Bytes | Description |
|---|---|---|
| Header | 1 | always `0x54` |
| VerLen | 1 | always `0x2C` |
| Speed | 2 LE | rotor speed in °/s (÷360 = Hz) |
| Start angle | 2 LE | start angle × 0.01° |
| Data 12× | 36 | each: distance (2 LE, mm) + intensity (1) |
| End angle | 2 LE | end angle × 0.01° |
| Timestamp | 2 LE | ms counter, wraps at 30000 |
| CRC8 | 1 | lookup table over bytes 0–45 |

Angles of the 12 points: linear interpolation start→end (wraparound at
360°). Implementation: `scanorama/lidar/protocol.py`.

## STL27L connector (ZH1.5T-4P)

| Pin | Signal | Description |
|---|---|---|
| 1 | TX | data output (3.3 V UART) |
| 2 | PWM | motor control (tied to GND = internal ~10 Hz) |
| 3 | GND | ground |
| 4 | P5V | 5 V, ~290 mA |

## Known pitfalls

1. **1 kΩ between Pi TX and PDN_UART** is mandatory (single-wire echo).
2. **The LiDAR needs ~3 s spin-up** before the first valid data.
3. **STSPIN220 max 10 V** motor voltage.
4. User `pi` must be in the `dialout` group (`/dev/ttyUSB0`, `/dev/ttyAMA0`).
5. Direction inverted (true to reality); old scans with
   invert_dir=false are mirrored.

## Cameras (photo round)

3× Sonix GXI-IMX179 USB modules (8 MP, MJPG 3264×2448) on a Ø 100 mm
sphere whose centre sits 50 mm below the LiDAR scan plane:

| cam_id | position | pitch | by-path port |
|---|---|---|---|
| usb0 | top    | +50° | …usb-0:1.1… |
| usb1 | middle | +15° | …usb-0:1.3… |
| usb2 | bottom | −20° | …usb-0:1.4… |

Address them via `/dev/v4l/by-path/…` only (all modules report the same
serial SN0001). Re-plugged a cable → verify the mapping with `scanorama
camera-test`. Requires `python3-opencv` and `v4l-utils` on the Pi.
Calibrated mounts: `scanorama/camera/mounts.py`, overrides in
`~/.config/scanorama/cameras.json`.

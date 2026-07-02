# Raspberry Pi Setup

*English version — deutsche Version: [SETUP.de.md](SETUP.de.md)*

Tested on Raspberry Pi 4B, Raspberry Pi OS Bookworm (64 bit),
Python 3.11.

## 1. Base system

```bash
# add the user to the required groups (re-login afterwards)
sudo usermod -a -G dialout,gpio pi
```

## 2. Enable the UART for the TMC2209

```bash
sudo raspi-config
# → Interface Options → Serial Port
#   → login shell over serial:  NO
#   → serial hardware enabled:  YES
sudo reboot
```

Afterwards `/dev/ttyAMA0` exists (TMC2209 configuration). The LiDAR
itself uses the USB adapter board (`/dev/ttyUSB0`, the CP2102 driver is
part of the kernel — just plug it in).

## 3. Install pilidar

```bash
git clone https://github.com/ferengi82/LiDar.git pilidar
cd pilidar
# --system-site-packages: RPi.GPIO comes from the OS package
python3 -m venv --system-site-packages venv
./venv/bin/pip install -e .
```

## 4. Function test

```bash
./venv/bin/pilidar selftest                      # LiDAR delivering data?
./venv/bin/pilidar motor-test --degrees 5 --back # motor turns + direction ok?
./venv/bin/pilidar scan --az-end 10 --speed 5    # mini scan (~2 s)
```

Expected selftest result: ~3600 frames in 2 s, rotor ⌀ ~10 Hz,
CRC errors near 0.

## 5. Developing from a PC

On the development machine (`~/.ssh/config`):

```
Host pilidar
    HostName <IP-of-the-Pi>
    User pi
    IdentityFile ~/.ssh/id_pilidar
```

Then `scripts/deploy.sh` rsyncs the working tree to `~/pilidar` on the
Pi (`--test` additionally runs pytest there).

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `Permission denied: /dev/ttyUSB0` | user not in `dialout` → step 1, re-login |
| selftest: 0 bytes | check LiDAR USB cable/adapter board; allow ~3 s spin-up |
| `TMC2209 UART not responding` | 1 kΩ resistor Pi-TX→PDN_UART missing? UART enabled (step 2)? |
| motor hums but does not turn | check VM supply; raise current at the VREF pot |
| scan mirrored | use `--invert-dir` |
| `ModuleNotFoundError: RPi` | venv created without `--system-site-packages` → recreate |

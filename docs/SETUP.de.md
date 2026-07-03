# Raspberry-Pi-Einrichtung

*Deutsche Version — English version: [SETUP.md](SETUP.md)*

Getestet mit Raspberry Pi 4B, Raspberry Pi OS Bookworm (64 bit),
Python 3.11.

## 1. Grundsystem

```bash
# User in die nötigen Gruppen (danach neu einloggen)
sudo usermod -a -G dialout,gpio pi
```

## 2. UART für den TMC2209 aktivieren

```bash
sudo raspi-config
# → Interface Options → Serial Port
#   → Login-Shell über Serial:  NEIN
#   → Serial-Hardware aktiv:    JA
sudo reboot
```

Danach existiert `/dev/ttyAMA0` (TMC2209-Konfiguration). Der LiDAR
selbst läuft über das USB-Adapterboard (`/dev/ttyUSB0`, Treiber CP2102
ist im Kernel enthalten — einfach einstecken).

## 3. scanorama installieren

```bash
git clone https://github.com/ferengi82/LiDar.git scanorama
cd scanorama
# --system-site-packages: RPi.GPIO kommt aus dem OS-Paket
python3 -m venv --system-site-packages venv
./venv/bin/pip install -e .
```

## 4. Funktionstest

```bash
./venv/bin/scanorama selftest                      # LiDAR liefert Daten?
./venv/bin/scanorama motor-test --degrees 5 --back # Motor dreht + Richtung ok?
./venv/bin/scanorama scan --az-end 10 --speed 5    # Mini-Scan (~2 s)
```

Erwartung beim Selftest: ~3600 Frames in 2 s, Rotor ⌀ ~10 Hz,
CRC-Fehler nahe 0.

## 5. Entwicklung vom PC aus

Auf der Entwicklungsmaschine (`~/.ssh/config`):

```
Host scanorama
    HostName <IP-des-Pi>
    User pi
    IdentityFile ~/.ssh/id_scanorama
```

Dann deployt `scripts/deploy.sh` das Arbeitsverzeichnis per rsync nach
`~/scanorama` auf dem Pi (`--test` führt dort zusätzlich pytest aus).

## Fehlersuche

| Symptom | Ursache / Lösung |
|---|---|
| `Permission denied: /dev/ttyUSB0` | User nicht in `dialout` → Schritt 1, neu einloggen |
| Selftest: 0 Bytes | LiDAR-USB-Kabel/Adapterboard prüfen; ~3 s Hochlauf abwarten |
| `TMC2209 UART antwortet nicht` | 1-kΩ-Widerstand Pi-TX→PDN_UART fehlt? UART aktiviert (Schritt 2)? |
| Motor brummt, dreht nicht | VM-Versorgung prüfen; Strom am VREF-Poti erhöhen |
| Scan gespiegelt | `--invert-dir` verwenden |
| `ModuleNotFoundError: RPi` | venv ohne `--system-site-packages` angelegt → neu anlegen |

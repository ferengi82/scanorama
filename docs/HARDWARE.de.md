# Hardware

*Deutsche Version — English version: [HARDWARE.md](HARDWARE.md)*

## Überblick

| Komponente | Beschreibung |
|---|---|
| Raspberry Pi 4B | Steuerung + Aufzeichnung (Hostname `PiLiDAR`) |
| STL27L | 360°-DTOF-LiDAR (LDRobot/Waveshare), 25 m, 21 600 Punkte/s, ~10 Hz Rotor |
| Adapterboard | Waveshare (ESP8266 + CP2102) → `/dev/ttyUSB0` @ 921600 Baud, versorgt den LiDAR mit 5 V |
| TMC2209 (Default) | Stepper-Treiber, STEP/DIR per GPIO + Konfiguration per UART, VM 8–24 V |
| Adafruit STSPIN220 (Fallback) | GPIO-only, fest 1/16 Microsteps, VIN **max 10 V!** |
| NEMA17 | Stepper, dreht den LiDAR um die Stehachse (Azimut) |
| Riemenantrieb | 20T (Motor) → 60T (Teller) = **3:1** (`gear_ratio = 3.0`) |

Der STL27L ist **vertikal** montiert und scannt eine Vertikalebene;
der Stepper dreht die Ebene um die Stehachse. 180° Azimut genügen für
eine Vollkugel.

## Verkabelung TMC2209 (Default-Treiber)

| TMC2209 | Raspberry Pi / Versorgung |
|---|---|
| VCC_IO | 3.3 V |
| GND | GND (Logik + Motor-Netzteil gemeinsam!) |
| STEP | GPIO23 |
| DIR | GPIO24 |
| EN | GPIO25 (active-low) |
| PDN_UART | ← Pi TX (GPIO14) **über 1 kΩ** — ohne Widerstand geht Single-Wire nicht! |
| PDN_UART | → Pi RX (GPIO15) direkt |
| VM | 8–24 V Motor-Versorgung |
| A1/A2/B1/B2 | Motor-Spulen |

**Pi-UART aktivieren:** `raspi-config` → Interface Options → Serial →
Login-Shell **aus**, Hardware-UART **an** (`/dev/ttyAMA0`).

Konfiguration per UART (macht `pilidar` beim Start automatisch):
Microstepping (Default 1/64), StealthChop, Stromskalierung (IRUN=31 =
voller Poti-Strom → Feineinstellung per VREF-Poti am Board).

## Verkabelung STSPIN220 (Fallback, `--driver stspin220`)

| STSPIN220 | Raspberry Pi / Versorgung |
|---|---|
| VCC | 3.3 V |
| GND | GND |
| STEP (STCK) | GPIO23 |
| DIR | GPIO24 |
| EN/FAULT | GPIO25 (active-low) |
| VIN | 5–10 V Netzteil — **max 10 V, niemals 12 V!** |
| A1/A2/B1/B2 | Motor-Spulen |

Fest 1/16 Microstepping (MS-Pins offen), Strombegrenzung per Poti.

## Stepper-Mechanik

```
steps_per_deg = (200 Fullsteps × Microsteps × 3.0 Gear) / 360
```

TMC2209 @ 1/64: 106.67 Steps/° · STSPIN220 @ 1/16: 26.67 Steps/°.
Drehrichtung ist im aktuellen Aufbau **nicht invertiert**
(`--invert-dir` falls der Scan gespiegelt erscheint).

## STL27L-Protokoll

- UART 921600 Baud 8N1, unidirektional — der LiDAR sendet nach
  Power-On von selbst (~3 s Hochlaufzeit).
- 47-Byte-Pakete mit je 12 Messpunkten:

| Feld | Bytes | Beschreibung |
|---|---|---|
| Header | 1 | immer `0x54` |
| VerLen | 1 | immer `0x2C` |
| Speed | 2 LE | Rotor-Geschwindigkeit in °/s (÷360 = Hz) |
| Start Angle | 2 LE | Startwinkel × 0.01° |
| Data 12× | 36 | je: Distanz (2 LE, mm) + Intensität (1) |
| End Angle | 2 LE | Endwinkel × 0.01° |
| Timestamp | 2 LE | ms-Zähler, Wrap bei 30000 |
| CRC8 | 1 | Lookup-Table über Byte 0–45 |

Winkel der 12 Punkte: lineare Interpolation Start→End (Wraparound bei
360°). Implementierung: `pilidar/lidar/protocol.py`.

## STL27L-Anschluss (ZH1.5T-4P)

| Pin | Signal | Beschreibung |
|---|---|---|
| 1 | TX | Datenausgang (3.3 V UART) |
| 2 | PWM | Motorsteuerung (auf GND = intern ~10 Hz) |
| 3 | GND | Masse |
| 4 | P5V | 5 V, ~290 mA |

## Bekannte Stolpersteine

1. **1 kΩ zwischen Pi-TX und PDN_UART** ist Pflicht (Single-Wire-Echo).
2. **LiDAR braucht ~3 s Hochlauf** vor den ersten gültigen Daten.
3. **STSPIN220 max 10 V** Motorspannung.
4. User `pi` muss in der Gruppe `dialout` sein (`/dev/ttyUSB0`, `/dev/ttyAMA0`).
5. Drehrichtung nicht invertiert; gespiegelter Scan → `--invert-dir`.

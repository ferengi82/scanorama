"""Zentrale Konfiguration des Scanners.

Alle Hardware- und Scan-Parameter mit den Defaults des aktuellen Aufbaus
(siehe docs/HARDWARE.de.md). Die CLI überschreibt einzelne Felder per
Argument; es gibt bewusst keine Konfigurationsdatei — die Defaults hier
sind die "Single Source of Truth" für den konkreten Scanner-Aufbau.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path


@dataclass
class LidarConfig:
    """STL27L über Waveshare-Adapterboard (CP2102)."""
    port: str = "/dev/ttyUSB0"
    baud: int = 921600
    # Der LiDAR braucht nach Power-On ~3 s bis stabile Daten kommen.
    startup_wait_s: float = 3.0


@dataclass
class MotorConfig:
    """NEMA17 + Riemenantrieb 20T→60T, Treiber TMC2209 (Fallback STSPIN220)."""
    driver: str = "tmc2209"          # tmc2209 | stspin220 | mock
    pin_step: int = 23               # BCM-Nummerierung
    pin_dir: int = 24
    pin_en: int = 25
    steps_per_rev: int = 200         # NEMA17 Fullsteps
    microsteps: int = 64             # TMC2209 per UART; STSPIN220 fest 1/16
    gear_ratio: float = 3.0          # Riemen 60T/20T
    invert_dir: bool = False         # aktueller Aufbau: nicht invertiert
    # Nur TMC2209 (UART):
    uart_port: str = "/dev/ttyAMA0"
    motor_current_ma: int = 800
    stealthchop: bool = True         # False = SpreadCycle (mehr Drehmoment)

    @property
    def steps_per_deg(self) -> float:
        """Microsteps pro Grad Azimut am Abtrieb (Drehteller)."""
        return (self.steps_per_rev * self.microsteps * self.gear_ratio) / 360.0


def _default_usb_cams() -> list[str]:
    from .camera.controller import DEFAULT_USB_CAMS
    return list(DEFAULT_USB_CAMS)


@dataclass
class CameraConfig:
    """Fotorunde mit den 3× IMX179-USB-Cams (läuft nach dem LiDAR-Scan)."""
    enabled: bool = True             # Default an; CLI --no-photos schaltet ab
    devices: list[str] = field(default_factory=_default_usb_cams)
    width: int = 3264                # IMX179-Maximum (MJPG)
    height: int = 2448
    photo_step_deg: float = 10.0     # 36 Positionen → ≥80 % Überlappung
    settle_s: float = 0.3            # Ausschwingzeit nach jedem Stopp
    exposure_lock: bool = True       # AE/AWB der ersten Cam für alle locken
    move_speed_deg_s: float = 20.0   # Verfahrgeschwindigkeit zwischen Stopps


@dataclass
class ScanConfig:
    """Parameter eines Scan-Durchlaufs."""
    mode: str = "stream"             # stream | step
    az_start_deg: float = 0.0
    az_end_deg: float = 180.0
    # Stream-Modus: kontinuierliche Drehgeschwindigkeit.
    # STL27L dreht mit ~10 Hz → bei 1°/s ≈ 10 LiDAR-Umdrehungen pro Grad.
    stream_speed_deg_s: float = 1.0
    # Schrittmodus: Schrittweite und Verweildauer pro Position.
    az_step_deg: float = 1.0
    rounds_per_position: int = 10    # LiDAR-Umdrehungen pro Position
    # Nach der Aufnahme automatisch points.npz erzeugen (Komfortformat).
    decode_after_scan: bool = True


@dataclass
class Config:
    """Gesamtkonfiguration = Hardware + Scan + Ausgabe."""
    lidar: LidarConfig = field(default_factory=LidarConfig)
    motor: MotorConfig = field(default_factory=MotorConfig)
    scan: ScanConfig = field(default_factory=ScanConfig)
    camera: CameraConfig = field(default_factory=CameraConfig)
    output_dir: str = str(Path.home() / "scans")

    def to_dict(self) -> dict:
        """Für meta.json — vollständige Konfiguration als dict."""
        return asdict(self)

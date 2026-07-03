"""Kamera-Subsystem: 3× IMX179-USB-Cams für die Fotorunde.

controller.py — UVC-Wrapper (MJPEG-Capture, AE/AWB-Lock), Port aus v1
mounts.py     — Einbaulage (Mount-Geometrie) pro Kamera, kalibrierte
                Defaults + Override per ~/.config/scanorama/cameras.json
mock.py       — Mock-Kameras für Tests ohne Hardware
"""

from .controller import DEFAULT_USB_CAMS, UsbCameraController
from .mounts import CameraMount, load_mounts

__all__ = ["DEFAULT_USB_CAMS", "UsbCameraController", "CameraMount",
           "load_mounts"]

"""Mock-Kameras für Tests ohne Hardware.

Verhält sich wie :class:`UsbCameraController` (open/close, Locking,
capture_jpeg), schreibt aber ein minimales, gültiges JPEG. Optional
kann das Öffnen fehlschlagen (Ausfalltest der Fotorunde).
"""

from __future__ import annotations

from pathlib import Path

from .controller import LockedParams

# Kleinstes gültiges JPEG (1×1 Pixel, grau) — reicht für Datei-Checks.
_TINY_JPEG = bytes.fromhex(
    "ffd8ffe000104a46494600010100000100010000ffdb004300080606070605080707"
    "07090908080a0c140d0c0b0b0c1912130f141d1a1f1e1d1a1c1c20242e2720222c23"
    "1c1c2837292c30313434341f27393d38323c2e333432ffc0000b0800010001010111"
    "00ffc40014000100000000000000000000000000000009ffc40014100100000000000"
    "00000000000000000000000ffda0008010100003f0054dfffd9"
)


class MockCamera:
    """Simulierte UVC-Kamera (Interface wie UsbCameraController)."""

    def __init__(self, device: str, cam_id: str,
                 width: int = 3264, height: int = 2448,
                 fail_on_open: bool = False):
        self.device = device
        self.cam_id = cam_id
        self.width = width
        self.height = height
        self.fail_on_open = fail_on_open
        self.locked: LockedParams | None = None
        self.captured: list[str] = []
        self._open = False

    def open(self) -> None:
        if self.fail_on_open:
            raise RuntimeError(f"Mock-Kamera {self.cam_id}: Öffnen fehlgeschlagen")
        self._open = True

    def close(self) -> None:
        self._open = False

    def estimate_and_lock(self) -> LockedParams:
        self.locked = LockedParams(exposure_absolute=100, gain=32,
                                   white_balance_temperature=4600)
        return self.locked

    def apply_locked(self, params: LockedParams) -> None:
        self.locked = params

    def capture_jpeg(self, filename: str) -> None:
        if not self._open:
            raise RuntimeError("capture_jpeg: erst open() aufrufen")
        Path(filename).write_bytes(_TINY_JPEG)
        self.captured.append(filename)


def make_mock_cams(n: int = 3, fail_on_open: bool = False) -> list[MockCamera]:
    return [MockCamera(device=f"/dev/mock{i}", cam_id=f"usb{i}",
                       fail_on_open=fail_on_open) for i in range(n)]

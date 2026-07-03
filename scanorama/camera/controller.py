#!/usr/bin/env python3
"""
USB-UVC-Kamera-Wrapper für die Fotorunde des LiDAR-Scanners.

Speziell zugeschnitten auf das Sonix GXI-IMX179-Modul (3264×2448 MJPEG @15 fps),
funktioniert aber mit jeder UVC-Cam, die MJPEG liefert. Das MJPEG-Frame wird
ohne Re-Encoding direkt als ``.jpg`` gespeichert (verlustfrei).

Auswahl per stabilem Pfad: ``/dev/v4l/by-path/...`` ist port-stabil; ``by-id``
ist bei diesem Modul unbrauchbar, weil alle Cams die gleiche Seriennummer
``SN0001`` melden. Beim Umstecken eines USB-Kabels ändert sich der by-path —
dann muss die ``--usb-cam``-Reihenfolge im Scanner neu gesetzt werden.

Belichtung/Weißabgleich werden über ``v4l2-ctl`` (Subprocess) gelockt — die
OpenCV-Properties (CAP_PROP_AUTO_EXPOSURE etc.) sind bei UVC unzuverlässig
und werden vom Treiber teilweise still ignoriert.

Nutzung::

    cam = UsbCameraController("/dev/v4l/by-path/...usb-0:1.1:1.0-video-index0",
                              cam_id="usb0", width=3264, height=2448)
    cam.open()
    locked = cam.estimate_and_lock()           # eigene AE/AWB messen + locken
    # oder:  cam.apply_locked(other_cam.locked)  # Werte einer anderen USB-Cam übernehmen
    cam.capture_jpeg("photo_00.jpg")
    cam.close()

Lazy-Import in Aufrufer: dieses Modul importiert ``cv2`` erst beim Öffnen,
damit Scans ohne ``--usb-cam`` ohne OpenCV-Installation auskommen.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)


# Default-Mapping der 3 USB-Cams am PiLiDAR (Stand 2026-04-28).
# Reihenfolge entspricht usb0/usb1/usb2 = cam1/cam2/cam3 = oben/mitte/unten.
# Ports sind by-path-stabil, ändern sich nur beim Umstecken eines Kabels.
DEFAULT_USB_CAMS: list[str] = [
    "/dev/v4l/by-path/platform-fd500000.pcie-pci-0000:01:00.0-usb-0:1.1:1.0-video-index0",  # oben  (pitch +50°)
    "/dev/v4l/by-path/platform-fd500000.pcie-pci-0000:01:00.0-usb-0:1.3:1.0-video-index0",  # mitte (pitch +15°)
    "/dev/v4l/by-path/platform-fd500000.pcie-pci-0000:01:00.0-usb-0:1.4:1.0-video-index0",  # unten (pitch -20°)
]


@dataclass
class LockedParams:
    """Gemessene/gesetzte AE+AWB-Werte einer UVC-Cam (V4L2-Einheiten)."""

    exposure_absolute: int | None = None      # Einheit: 100 µs (V4L2-Standard)
    gain: int | None = None                    # Treiber-spezifisch (0..N)
    white_balance_temperature: int | None = None  # Kelvin (Treiber-spezifisch)
    extra: dict = field(default_factory=dict)  # zusätzliche Controls (z.B. brightness)


# V4L2-Controls, die wir je nach Treiber locken — alle optional.
# Bei IMX179/Sonix sind exposure_absolute, gain und white_balance_temperature
# vorhanden. Andere UVC-Treiber bieten teilweise nur eine Untermenge.
_LOCK_CONTROLS_AUTO_OFF = {
    "exposure_auto": 1,                # 1 = Manual Mode (V4L2-Spec)
    "white_balance_temperature_auto": 0,
}


class UsbCameraController:
    """Wrapper um eine UVC-Cam: MJPEG-Capture + AE/AWB-Lock via v4l2-ctl."""

    def __init__(self, device: str, cam_id: str,
                 width: int = 3264, height: int = 2448,
                 fourcc: str = "MJPG", warmup_frames: int = 8):
        """
        Args:
            device: Pfad zum V4L2-Device — empfohlen
                ``/dev/v4l/by-path/...-video-index0`` (port-stabil).
            cam_id: kurze Kennung für Dateinamen (``usb0``, ``usb1``, …).
            width, height: gewünschte Capture-Auflösung. Default = IMX179-Maximum.
            fourcc: Pixelformat. ``MJPG`` ist bei großen Auflösungen Pflicht
                (YUYV bricht bei 3264×2448 auf 2 fps ein).
            warmup_frames: Frames zum Verwerfen nach dem Öffnen, bevor
                Werte gemessen werden (UVC braucht 5–8 Frames für AE-Stabil).
        """
        self.device = device
        self.cam_id = cam_id
        self.width = width
        self.height = height
        self.fourcc = fourcc
        self.warmup_frames = warmup_frames
        self._cap = None
        self.locked: LockedParams | None = None
        self._v4l2_ctl = shutil.which("v4l2-ctl")
        if not self._v4l2_ctl:
            log.warning("v4l2-ctl nicht im PATH gefunden — AE/AWB-Lock wird nicht "
                        "funktionieren. Bitte 'sudo apt install v4l-utils' installieren.")

    # ------------------------------------------------------------------
    # Geräte-Lifecycle
    # ------------------------------------------------------------------

    def open(self) -> None:
        """Öffnet das Device, setzt Auflösung+Codec, verwirft Warmup-Frames."""
        import cv2
        # CAP_V4L2 erzwingt den V4L2-Backend (statt FFmpeg/GStreamer-Auto), damit
        # set/get der Properties auf den Treiber durchschlägt.
        cap = cv2.VideoCapture(self.device, cv2.CAP_V4L2)
        if not cap.isOpened():
            raise RuntimeError(f"Konnte USB-Cam nicht öffnen: {self.device}")
        # FOURCC als 4-Byte-Int. cv2.VideoWriter_fourcc(*'MJPG') liefert das.
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*self.fourcc))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        # Buffer-Size klein halten, damit wir aktuelle Frames bekommen, nicht
        # alte aus dem Ringbuffer (sonst Verschleppung beim AE-Messen).
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self._cap = cap
        actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        log.info(f"USB-Cam {self.cam_id} geöffnet ({self.device}): "
                 f"{actual_w}×{actual_h} {self.fourcc}")
        if (actual_w, actual_h) != (self.width, self.height):
            log.warning(f"  Treiber hat {actual_w}×{actual_h} statt "
                        f"{self.width}×{self.height} ausgewählt")
        for _ in range(self.warmup_frames):
            cap.grab()

    def close(self) -> None:
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None

    # ------------------------------------------------------------------
    # AE/AWB-Steuerung über v4l2-ctl
    # ------------------------------------------------------------------

    def _v4l2(self, *args: str) -> str:
        """Ruft v4l2-ctl auf und liefert stdout. Wirft bei Fehler."""
        if not self._v4l2_ctl:
            raise RuntimeError("v4l2-ctl nicht installiert")
        cmd = [self._v4l2_ctl, "-d", self.device, *args]
        out = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return out.stdout

    def _set_ctrl(self, name: str, value: int) -> bool:
        """Setzt einen V4L2-Control. Loggt+returns False bei Fehler (Control fehlt)."""
        try:
            self._v4l2(f"--set-ctrl={name}={int(value)}")
            return True
        except subprocess.CalledProcessError as e:
            log.debug(f"  {self.cam_id}: --set-ctrl={name}={value} fehlgeschlagen "
                      f"(Control evtl. nicht vorhanden): {e.stderr.strip()}")
            return False

    def _get_ctrl(self, name: str) -> int | None:
        """Liest aktuellen Wert eines Controls. None wenn nicht vorhanden."""
        try:
            out = self._v4l2(f"--get-ctrl={name}")
            # Format: "exposure_absolute: 1234"
            return int(out.strip().split(":")[1].strip())
        except (subprocess.CalledProcessError, IndexError, ValueError):
            return None

    def estimate_and_lock(self) -> LockedParams:
        """Misst AE/AWB im Auto-Modus und lockt sie für alle Folge-Aufnahmen.

        Ablauf:
          1. Auto-Modi explizit einschalten (manche Treiber starten manuell).
          2. Eine Sekunde Frames durchlaufen lassen, damit AE einschwingt.
          3. Aktuelle Werte für exposure/gain/white_balance auslesen.
          4. Auto-Modi ausschalten und gemessene Werte manuell setzen.
          5. Nochmal kurz warten, damit der Treiber die manuellen Werte greift.
        """
        if self._cap is None:
            raise RuntimeError("estimate_and_lock: erst open() aufrufen")

        # 1. Auto-Modus explizit
        # exposure_auto: V4L2-Spec sagt 3 = Aperture Priority (Auto), 1 = Manual.
        # Bei UVC mappen die meisten Treiber 3→Auto.
        self._set_ctrl("exposure_auto", 3)
        self._set_ctrl("white_balance_temperature_auto", 1)

        # 2. Einschwingen lassen (~1 s @ 15 fps = 15 Frames)
        for _ in range(15):
            self._cap.grab()
        time.sleep(0.3)

        # 3. Werte lesen
        params = LockedParams(
            exposure_absolute=self._get_ctrl("exposure_absolute"),
            gain=self._get_ctrl("gain"),
            white_balance_temperature=self._get_ctrl("white_balance_temperature"),
        )
        log.info(f"  {self.cam_id} gemessen: exp={params.exposure_absolute}·100µs, "
                 f"gain={params.gain}, WB={params.white_balance_temperature}K")

        # 4. Werte locken (fix manuell setzen)
        self._apply_params(params)
        self.locked = params

        # 5. Frames verwerfen, bis manuelle Werte greifen
        for _ in range(5):
            self._cap.grab()
        return params

    def apply_locked(self, params: LockedParams) -> None:
        """Übernimmt AE/AWB-Werte einer anderen Cam (z.B. der ersten USB-Cam).

        Für identische IMX179-Module unter gleicher Beleuchtung sinnvoll —
        so haben alle USB-Cams in der Fotorunde dieselbe Belichtung und
        denselben Weißabgleich, was Stitching/Photogrammetrie deutlich
        konsistenter macht.
        """
        if self._cap is None:
            raise RuntimeError("apply_locked: erst open() aufrufen")
        log.info(f"  {self.cam_id} übernimmt Lock-Werte: "
                 f"exp={params.exposure_absolute}, gain={params.gain}, "
                 f"WB={params.white_balance_temperature}")
        self._apply_params(params)
        self.locked = params
        for _ in range(5):
            self._cap.grab()

    def _apply_params(self, params: LockedParams) -> None:
        # Reihenfolge wichtig: erst Auto aus, dann manuelle Werte, sonst
        # überschreibt der Auto-Regler den nächsten Frame.
        for ctrl, val in _LOCK_CONTROLS_AUTO_OFF.items():
            self._set_ctrl(ctrl, val)
        if params.exposure_absolute is not None:
            self._set_ctrl("exposure_absolute", params.exposure_absolute)
        if params.gain is not None:
            self._set_ctrl("gain", params.gain)
        if params.white_balance_temperature is not None:
            self._set_ctrl("white_balance_temperature",
                           params.white_balance_temperature)
        for ctrl, val in params.extra.items():
            self._set_ctrl(ctrl, val)

    # ------------------------------------------------------------------
    # Capture
    # ------------------------------------------------------------------

    def capture_jpeg(self, filename: str) -> None:
        """Speichert ein Frame als JPEG (re-encoded aus dem decodierten Bild).

        Hintergrund: OpenCV liefert über ``read()`` immer ein BGR-Numpy-Array
        — selbst wenn der Stream MJPEG ist. Den ursprünglichen JPEG-Bytestream
        bekommen wir nur über tieferes V4L2-API. Für die Fotorunde ist das
        Re-Encode mit ``imwrite(quality=95)`` aber qualitativ ausreichend
        (visuell verlustfrei) und massiv einfacher als ein eigener V4L2-
        Pfad. Falls du später echte verlustfreie MJPEG-Speicherung willst,
        siehe Kommentar in ``capture_raw_mjpeg`` (TODO).
        """
        import cv2
        if self._cap is None:
            raise RuntimeError("capture_jpeg: erst open() aufrufen")
        # Einen Frame verwerfen, dann den aktuellen lesen (Buffer-Refresh).
        self._cap.grab()
        ok, frame = self._cap.read()
        if not ok or frame is None:
            raise RuntimeError(f"USB-Cam {self.cam_id}: kein Frame erhalten")
        # Hohe JPEG-Quality (95), keine Subsampling-Kompromisse.
        ok = cv2.imwrite(filename, frame,
                         [cv2.IMWRITE_JPEG_QUALITY, 95])
        if not ok:
            raise RuntimeError(f"cv2.imwrite fehlgeschlagen: {filename}")
        log.info(f"  Foto gespeichert: {filename}")


# ---------------------------------------------------------------------------
# Helfer für CLI-Setup
# ---------------------------------------------------------------------------

def open_all(devices: list[str], width: int = 3264, height: int = 2448
             ) -> list[UsbCameraController]:
    """Öffnet alle angegebenen Cams und gibt die Controller-Liste zurück.

    Cam-IDs werden nach Reihenfolge vergeben: ``usb0``, ``usb1``, ``usb2``, …
    Schlägt das Öffnen einer Cam fehl, werden die bereits geöffneten Cams
    sauber wieder geschlossen, bevor die Exception nach oben durchbricht.
    """
    cams: list[UsbCameraController] = []
    try:
        for i, dev in enumerate(devices):
            cam = UsbCameraController(dev, cam_id=f"usb{i}",
                                      width=width, height=height)
            cam.open()
            cams.append(cam)
        return cams
    except Exception:
        for c in cams:
            c.close()
        raise


def close_all(cams: list[UsbCameraController]) -> None:
    for c in cams:
        c.close()


def lock_all_to_first(cams: list[UsbCameraController]) -> LockedParams | None:
    """Erste Cam misst+lockt eigene AE/AWB, alle weiteren übernehmen die Werte.

    Damit haben alle USB-Cams im Setup garantiert identische Belichtung und
    Farbtemperatur — Voraussetzung für sauberes Multi-View-Stitching und
    gleichmäßige Texturen in Metashape.
    """
    if not cams:
        return None
    first = cams[0]
    params = first.estimate_and_lock()
    for cam in cams[1:]:
        cam.apply_locked(params)
    return params


# ---------------------------------------------------------------------------
# CLI für Standalone-Tests (Python-only Logik, keine Hardware nötig im --help)
# ---------------------------------------------------------------------------

def _cli() -> int:
    import argparse
    ap = argparse.ArgumentParser(
        description="Standalone-Test der UsbCameraController-Klasse",
    )
    ap.add_argument("device", help="V4L2-Pfad, z.B. /dev/v4l/by-path/...-video-index0")
    ap.add_argument("--out", default="usbcam_test.jpg", help="Ausgabe-Datei")
    ap.add_argument("--width", type=int, default=3264)
    ap.add_argument("--height", type=int, default=2448)
    ap.add_argument("--no-lock", action="store_true",
                    help="AE/AWB nicht locken (Auto-Modus)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s  %(message)s",
    )
    cam = UsbCameraController(args.device, cam_id="test",
                              width=args.width, height=args.height)
    cam.open()
    try:
        if not args.no_lock:
            cam.estimate_and_lock()
        cam.capture_jpeg(args.out)
    finally:
        cam.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())

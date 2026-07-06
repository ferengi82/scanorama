"""Einbaulage (Mount-Geometrie) der Kameras.

Die 3 IMX179-Module sitzen auf einer Kugel Ø 100 mm, deren Mittelpunkt
50 mm unter dem Scannerzentrum (= LiDAR-Scanebene) liegt. Pro Kamera
beschreibt ein :class:`CameraMount` die Lage des Nodalpunkts relativ
zur Drehachse und die Blickrichtung relativ zur Plattform.

Diese Werte wandern in die meta.json jedes Scans (Block ``cameras``),
damit die PC-Auswertung die globale Pose jedes Fotos berechnen kann:

    Position:     x = r·sin(az + az_offset)
                  y = r·cos(az + az_offset)
                  z = z_cam
    Orientierung: yaw   = az + az_offset + yaw_mount
                  pitch = pitch_mount
                  roll  = roll_mount

(az = Plattform-Azimut des Fotos; Koordinaten wie in DATAFORMAT.md.)

Die Defaults sind die **kalibrierten v1-Werte** (Stand 2026-04-28);
``~/.config/scanorama/cameras.json`` auf dem Pi überschreibt einzelne
Kameras (gleiches JSON-Schema wie :func:`CameraMount` als dict).
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

log = logging.getLogger(__name__)

CONFIG_PATH = Path.home() / ".config" / "scanorama" / "cameras.json"

# Einbaulagen für den invert_dir=false-Frame (Stand 2026-07-06). az_offset/
# pitch/roll aus Metashape-Alignment + Foto-Overlay Auto-Fit gegen die
# realitätstreue Wolke (scan_03_001); r/z aus der Kugelgeometrie (Ø 100 mm,
# Mittelpunkt 50 mm unter Scannerzentrum). Die Module sind HOCHKANT verbaut
# (roll ≈ ±90°). Mapping: usb0 = oben (+48,5°), usb1 = Seite (+16°),
# usb2 = unten (−16°).
# OFFEN (2026-07-06, weiter zu optimieren): usb1-pitch — Auto-Fit bevorzugt
# ~27° statt 16°; usb2 — Auto-Fit konnte den Down-Blick nicht validieren
# (wenig Wolke im Bild); usb0 nur mittlere Konfidenz.
CALIBRATED_MOUNTS: dict[str, dict] = {
    "usb0": {"r_cam_m": 0.03294, "z_cam_m": -0.01239, "az_offset_deg": 19.8,
             "yaw_mount_deg": 0.0, "pitch_mount_deg": 48.54,
             "roll_mount_deg": 93.72},
    "usb1": {"r_cam_m": 0.04857, "z_cam_m": -0.03814, "az_offset_deg": 212.0,
             "yaw_mount_deg": 0.0, "pitch_mount_deg": 16.0,
             "roll_mount_deg": 89.0},
    "usb2": {"r_cam_m": 0.04736, "z_cam_m": -0.06604, "az_offset_deg": 324.0,
             "yaw_mount_deg": 0.0, "pitch_mount_deg": -16.0,
             "roll_mount_deg": -88.0},
}


@dataclass
class CameraMount:
    """Mechanische Einbaulage einer Kamera (Längen in Metern, Winkel in Grad)."""
    r_cam_m: float = 0.0           # radialer Abstand Nodalpunkt ↔ Drehachse
    z_cam_m: float = 0.0           # Höhe Nodalpunkt über der LiDAR-Scanebene
    az_offset_deg: float = 0.0     # Winkel der Kamera-Blickrichtung zu Az=0
    yaw_mount_deg: float = 0.0     # zusätzlicher Yaw (Montagetoleranz)
    pitch_mount_deg: float = 0.0   # Neigung nach oben (+) / unten (−)
    roll_mount_deg: float = 0.0    # Rollwinkel

    def to_dict(self) -> dict:
        return asdict(self)


def load_mounts(config_path: Path | None = None) -> dict[str, CameraMount]:
    """Lädt die Mount-Profile: kalibrierte Defaults + User-Overrides.

    Args:
        config_path: abweichender Pfad (für Tests); Default CONFIG_PATH

    Returns:
        dict cam_id → CameraMount
    """
    path = config_path if config_path is not None else CONFIG_PATH
    mounts = {cid: CameraMount(**vals) for cid, vals in CALIBRATED_MOUNTS.items()}

    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            log.warning(f"{path} unlesbar ({e}) — nutze kalibrierte Defaults")
            return mounts
        for cid, vals in data.items():
            try:
                mounts[cid] = CameraMount(**vals)
            except TypeError as e:
                log.warning(f"{path}: Profil '{cid}' ungültig ({e}) — übersprungen")
        log.info(f"Mount-Overrides geladen: {path} ({', '.join(data)})")
    return mounts


POSE_RECIPE = (
    "Kameraposition: x=r_cam_m*sin(az+az_offset_deg), "
    "y=r_cam_m*cos(az+az_offset_deg), z=z_cam_m; "
    "Orientierung: yaw=az+az_offset_deg+yaw_mount_deg, "
    "pitch=pitch_mount_deg, roll=roll_mount_deg — "
    "az = azimuth_deg des Fotos, Koordinaten/Konvention siehe geometry-Block"
)

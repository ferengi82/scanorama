"""Fotorunde: Stop-and-Shoot mit den USB-Kameras nach dem LiDAR-Scan.

Ablauf (Port aus v1, angepasst an die Recorder-Philosophie):
  1. Kameras öffnen; die erste misst AE/AWB und lockt, alle weiteren
     übernehmen die Werte (identische Belichtung über die ganze Runde —
     Voraussetzung für konsistente Photogrammetrie).
  2. 360° in ``photo_step_deg``-Schritten abfahren: anhalten, ausschwingen
     lassen (``settle_s``), alle Kameras auslösen.
  3. Pro Foto werden Datei, cam_id, Index, **Plattform-Azimut**
     (``stepper.current_deg`` — dieselbe Referenz wie die LiDAR-Azimute)
     und Host-Zeit gespeichert.

Fotos landen in ``<scanordner>/photos/``; die Beschreibung der
Kamera-Einbaulagen (Mounts) und die Foto-Liste kommen in die meta.json,
sodass die PC-Auswertung jede Foto-Pose ohne Zusatzwissen berechnen kann
(Formel: :data:`scanorama.camera.mounts.POSE_RECIPE`).

Ein Kamera-Fehler bricht den Scan NICHT ab — die LiDAR-Daten sind
bereits sicher; die Fotorunde wird mit Warnung übersprungen und in der
meta.json als ``"status": "failed"`` vermerkt.
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict
from pathlib import Path

from ..camera.mounts import POSE_RECIPE, load_mounts
from ..config import Config

log = logging.getLogger(__name__)

PHOTOS_DIRNAME = "photos"


def _open_cameras(cfg: Config) -> list:
    """Öffnet die konfigurierten USB-Kameras (echte Hardware)."""
    from ..camera.controller import open_all
    return open_all(cfg.camera.devices,
                    width=cfg.camera.width, height=cfg.camera.height)


def run_photo_round(cfg: Config, stepper, scan_dir: Path,
                    cameras: list | None = None) -> tuple[dict, list[dict]]:
    """Führt die Fotorunde aus.

    Args:
        cfg: Gesamtkonfiguration (camera-Block)
        stepper: Stepper mit ``move_degrees``/``current_deg`` (steht auf
            der Endposition des LiDAR-Scans; von dort 360° weiter)
        scan_dir: Scan-Ordner (photos/ wird darunter angelegt)
        cameras: vorgeöffnete Kamera-Objekte (Tests/Mocks); None = echte
            Kameras aus der Konfiguration öffnen

    Returns:
        (cameras_block, photos_list) für die meta.json.
        Bei deaktivierter Runde: ({"status": "disabled"}, []).
        Bei Kamera-Fehler:      ({"status": "failed", "error": …}, []).
    """
    if not cfg.camera.enabled or not cfg.camera.devices:
        return {"status": "disabled"}, []

    step = cfg.camera.photo_step_deg
    count = int(round(360.0 / step))

    own_cameras = cameras is None
    if own_cameras:
        try:
            cameras = _open_cameras(cfg)
        except Exception as e:
            log.warning(f"Fotorunde übersprungen — Kameras nicht verfügbar: {e}")
            return {"status": "failed", "error": str(e)}, []

    log.info("=" * 60)
    log.info(f"Fotorunde: {count} Positionen × {len(cameras)} Kamera(s), "
             f"alle {step:.1f}° (≈{count * (cfg.camera.settle_s + 0.6):.0f}s)")

    photos_dir = scan_dir / PHOTOS_DIRNAME
    photos_dir.mkdir(exist_ok=True)

    locked = None
    photos: list[dict] = []
    try:
        if cfg.camera.exposure_lock and cameras:
            locked = cameras[0].estimate_and_lock()
            for cam in cameras[1:]:
                cam.apply_locked(locked)

        for i in range(count):
            time.sleep(cfg.camera.settle_s)
            azimuth = float(stepper.current_deg)
            az_label = int(round(azimuth)) % 360
            for cam in cameras:
                name = f"photo_{i:02d}_az{az_label:03d}_{cam.cam_id}.jpg"
                cam.capture_jpeg(str(photos_dir / name))
                photos.append({
                    "file": f"{PHOTOS_DIRNAME}/{name}",
                    "cam_id": cam.cam_id,
                    "index": i,
                    "azimuth_deg": round(azimuth, 4),
                    "t_ns": time.monotonic_ns(),
                })
            log.info(f"  [{i + 1:02d}/{count}] Az {azimuth:7.1f}° — "
                     f"{len(cameras)} Foto(s)")
            if i < count - 1:
                stepper.move_degrees(step,
                                     speed_deg_s=cfg.camera.move_speed_deg_s)
    except Exception as e:
        log.warning(f"Fotorunde abgebrochen: {e} — "
                    f"{len(photos)} Foto(s) bleiben erhalten")
        cameras_block = _cameras_block(cfg, cameras, locked)
        cameras_block.update({"status": "failed", "error": str(e)})
        return cameras_block, photos
    finally:
        if own_cameras:
            for cam in cameras:
                cam.close()

    log.info(f"Fotorunde abgeschlossen: {len(photos)} Fotos")
    log.info("=" * 60)
    cameras_block = _cameras_block(cfg, cameras, locked)
    cameras_block["status"] = "ok"
    return cameras_block, photos


def _cameras_block(cfg: Config, cameras: list, locked) -> dict:
    """Baut den cameras-Block für die meta.json (Mounts + Aufnahme-Setup)."""
    mounts = load_mounts()
    used = {}
    for i, cam in enumerate(cameras):
        m = mounts.get(cam.cam_id)
        entry = m.to_dict() if m is not None else {}
        entry["device"] = getattr(cam, "device", cfg.camera.devices[i]
                                  if i < len(cfg.camera.devices) else "?")
        used[cam.cam_id] = entry
    return {
        "photo_step_deg": cfg.camera.photo_step_deg,
        "resolution": [cfg.camera.width, cfg.camera.height],
        "locked_params": asdict(locked) if locked is not None else None,
        "mounts": used,
        "pose_recipe": POSE_RECIPE,
    }

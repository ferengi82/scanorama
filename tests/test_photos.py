"""Tests: Fotorunde (Mock-Kameras), Mount-Profile, Ausfallverhalten."""

import json

import pytest

from scanorama.camera.mock import make_mock_cams
from scanorama.camera.mounts import CALIBRATED_MOUNTS, load_mounts
from scanorama.config import Config
from scanorama.scan.recorder import run_scan


def _cfg(tmp_path, photo_step=45.0) -> Config:
    cfg = Config()
    cfg.motor.driver = "mock"
    cfg.lidar.startup_wait_s = 0.0
    cfg.scan.mode = "stream"
    cfg.scan.az_end_deg = 10.0
    cfg.scan.stream_speed_deg_s = 5.0
    cfg.camera.photo_step_deg = photo_step
    cfg.camera.settle_s = 0.0
    cfg.camera.move_speed_deg_s = 3600.0   # Mock: schnell durchdrehen
    cfg.output_dir = str(tmp_path)
    return cfg


def test_scan_with_photo_round(tmp_path):
    cams = make_mock_cams(3)
    for cam in cams:
        cam.open()   # API-Vertrag: injizierte Kameras sind vorgeöffnet
    scan_dir = run_scan(_cfg(tmp_path, photo_step=45.0),
                        use_mock_lidar=True, cameras=cams)

    meta = json.loads((scan_dir / "meta.json").read_text())
    assert meta["cameras"]["status"] == "ok"
    assert meta["cameras"]["photo_step_deg"] == 45.0
    assert meta["cameras"]["locked_params"]["exposure_absolute"] == 100
    assert "pose_recipe" in meta["cameras"]

    # Mounts: kalibrierte v1-Werte pro Kamera + Gerätepfad
    mounts = meta["cameras"]["mounts"]
    assert set(mounts) == {"usb0", "usb1", "usb2"}
    assert mounts["usb0"]["pitch_mount_deg"] == 48.79
    assert mounts["usb0"]["az_offset_deg"] == 9.8
    assert mounts["usb2"]["z_cam_m"] == pytest.approx(-0.06604)
    assert "device" in mounts["usb0"]

    # 8 Positionen (360/45) × 3 Cams = 24 Fotos, Dateien existieren
    photos = meta["photos"]
    assert len(photos) == 24
    for p in photos:
        assert (scan_dir / p["file"]).is_file()
        assert p["t_ns"] > 0

    # Azimute steigen pro Position um 45° (Start = Ende des LiDAR-Scans)
    az = [p["azimuth_deg"] for p in photos if p["cam_id"] == "usb0"]
    assert az[0] == pytest.approx(10.0, abs=0.5)
    diffs = [az[i + 1] - az[i] for i in range(len(az) - 1)]
    assert all(abs(d - 45.0) < 0.5 for d in diffs)

    # Zeitleiste enthält die Foto-Positionierfahrten (7 Moves nach Runde 1)
    timeline = (scan_dir / "motor_timeline.csv").read_text()
    assert timeline.count("move_start") >= 7


def test_photo_round_disabled(tmp_path):
    cfg = _cfg(tmp_path)
    cfg.camera.enabled = False
    scan_dir = run_scan(cfg, use_mock_lidar=True)
    meta = json.loads((scan_dir / "meta.json").read_text())
    assert meta["cameras"] == {"status": "disabled"}
    assert meta["photos"] == []
    assert not (scan_dir / "photos").exists()


def test_camera_failure_keeps_scan(tmp_path, monkeypatch):
    """Kameras nicht verfügbar → Scan trotzdem gültig, Status failed."""
    import scanorama.scan.photos as photos_mod

    def boom(cfg):
        raise RuntimeError("Konnte USB-Cam nicht öffnen: /dev/mock")

    monkeypatch.setattr(photos_mod, "_open_cameras", boom)
    scan_dir = run_scan(_cfg(tmp_path), use_mock_lidar=True)

    meta = json.loads((scan_dir / "meta.json").read_text())
    assert meta["cameras"]["status"] == "failed"
    assert "USB-Cam" in meta["cameras"]["error"]
    # LiDAR-Daten sind vollständig da
    assert (scan_dir / "lidar_raw.bin").stat().st_size > 0
    assert meta["decode"]["points_valid"] > 0


def test_load_mounts_defaults_and_override(tmp_path):
    mounts = load_mounts(tmp_path / "gibtsnicht.json")
    assert mounts["usb1"].az_offset_deg == 241.0

    override = tmp_path / "cameras.json"
    override.write_text(json.dumps({
        "usb1": {"r_cam_m": 0.05, "z_cam_m": -0.04, "az_offset_deg": 40.0,
                 "yaw_mount_deg": 1.0, "pitch_mount_deg": 15.0,
                 "roll_mount_deg": 0.0},
    }))
    mounts = load_mounts(override)
    assert mounts["usb1"].az_offset_deg == 40.0      # überschrieben
    assert mounts["usb0"].az_offset_deg == 9.8       # Default bleibt
    assert set(CALIBRATED_MOUNTS) <= set(mounts)

"""End-to-End-Test des Recorders mit Mock-LiDAR und Mock-Stepper.

Simuliert einen kompletten Kurz-Scan (Stream- und Schrittmodus) ohne
Hardware und prüft, dass ein vollständiger, konsistenter Scan-Ordner
entsteht.
"""

import json

import numpy as np
import pytest

from scanorama.config import Config
from scanorama.scan import session
from scanorama.scan.recorder import run_scan


def _base_config(tmp_path) -> Config:
    cfg = Config()
    cfg.motor.driver = "mock"
    cfg.lidar.startup_wait_s = 0.0
    cfg.camera.enabled = False   # LiDAR-Tests ohne Fotorunde (auf dem
                                 # Pi würden sonst echte Kameras auslösen!)
    cfg.output_dir = str(tmp_path)
    return cfg


def _check_scan_dir(scan_dir, az_expected_max):
    assert (scan_dir / "lidar_raw.bin").exists()
    assert (scan_dir / "lidar_index.npz").exists()
    assert (scan_dir / session.TIMELINE_NAME).exists()
    assert (scan_dir / session.POINTS_NAME).exists()
    assert (scan_dir / session.LOG_NAME).exists()

    meta = json.loads((scan_dir / "meta.json").read_text())
    assert meta["schema_version"] == 1
    assert meta["capture"]["total_bytes"] > 0
    assert meta["decode"]["points_valid"] > 0
    assert meta["selftest"]["points_valid"] > 0
    assert "raw" not in meta["selftest"]

    pts = np.load(scan_dir / session.POINTS_NAME)
    az = pts["azimuth_deg"]
    assert az.min() >= -0.5
    assert az.max() == pytest.approx(az_expected_max, abs=1.0)
    # Mock-Szene: Distanzen im erwarteten Band
    assert pts["distance_mm"].min() >= 1400
    assert pts["distance_mm"].max() <= 2600
    return meta


def test_stream_scan_with_mocks(tmp_path):
    cfg = _base_config(tmp_path)
    cfg.scan.mode = "stream"
    cfg.scan.az_start_deg = 0.0
    cfg.scan.az_end_deg = 30.0
    cfg.scan.stream_speed_deg_s = 5.0  # bei time_scale 60 → ~0.1 s real

    scan_dir = run_scan(cfg, use_mock_lidar=True)
    meta = _check_scan_dir(scan_dir, az_expected_max=30.0)
    assert meta["mode"] == "stream"


def test_step_scan_with_mocks(tmp_path):
    cfg = _base_config(tmp_path)
    cfg.scan.mode = "step"
    cfg.scan.az_start_deg = 0.0
    cfg.scan.az_end_deg = 4.0
    cfg.scan.az_step_deg = 2.0
    cfg.scan.rounds_per_position = 2

    scan_dir = run_scan(cfg, use_mock_lidar=True)
    meta = _check_scan_dir(scan_dir, az_expected_max=4.0)
    assert meta["mode"] == "step"

    # Zeitleiste muss die Positionsfahrten enthalten (2 Moves à 2°)
    timeline = (scan_dir / session.TIMELINE_NAME).read_text()
    assert timeline.count("move_start") == 2
    assert timeline.count("move_end") == 2

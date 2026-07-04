"""Tests für die LiDAR-Gerätekalibrierung (calibration.json → meta.json)."""

import json

from scanorama.lidar import calibration
from scanorama.scan import session


def test_defaults_ohne_datei(tmp_path):
    calib = calibration.load_calibration(tmp_path / "gibtsnicht.json")
    assert calib == calibration.DEFAULT_CALIBRATION
    assert calib["beam_skew_deg"] == 0.0


def test_override_und_zusatzfelder(tmp_path):
    path = tmp_path / "calibration.json"
    path.write_text(json.dumps({
        "beam_skew_deg": 0.562,
        "halfplane_split_deg": -1.168,
        "fitted": "2026-07-04",
    }), encoding="utf-8")
    calib = calibration.load_calibration(path)
    assert calib["beam_skew_deg"] == 0.562
    assert calib["halfplane_split_deg"] == -1.168
    assert calib["el_offset_deg"] == 0.0          # Default bleibt
    assert calib["fitted"] == "2026-07-04"        # Zusatzfeld durchgereicht


def test_kaputte_datei_faellt_auf_defaults(tmp_path):
    path = tmp_path / "calibration.json"
    path.write_text("{kaputt", encoding="utf-8")
    assert calibration.load_calibration(path) == calibration.DEFAULT_CALIBRATION


def test_nicht_numerische_werte_ignoriert(tmp_path):
    path = tmp_path / "calibration.json"
    path.write_text(json.dumps({"beam_skew_deg": "viel"}), encoding="utf-8")
    calib = calibration.load_calibration(path)
    assert calib["beam_skew_deg"] == 0.0


def test_meta_enthaelt_calibration():
    meta = session.build_meta({}, mode="stream")
    assert "calibration" in meta
    for key in calibration.DEFAULT_CALIBRATION:
        assert key in meta["calibration"]
    assert "model" in meta["calibration"]

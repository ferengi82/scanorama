"""Tests für Scan-Ordner-Namensschema und Metadaten."""

import os
import time
from datetime import date

from scanorama.scan import session


def _today():
    return date.today().strftime("%Y-%m-%d")


def test_first_scan_dir(tmp_path):
    d = session.create_scan_dir(tmp_path)
    assert d.name == f"{_today()}_scan_01_001"
    assert d.is_dir()


def test_same_session_increments_standpoint(tmp_path):
    d1 = session.create_scan_dir(tmp_path)
    d2 = session.create_scan_dir(tmp_path)
    assert d1.name.endswith("_01_001")
    assert d2.name.endswith("_01_002")


def test_new_session_after_timeout(tmp_path):
    d1 = session.create_scan_dir(tmp_path)
    # Letzten Scan künstlich >5 min altern lassen
    old = time.time() - 400
    os.utime(d1, (old, old))
    d2 = session.create_scan_dir(tmp_path)
    assert d2.name.endswith("_02_001")


def test_meta_roundtrip(tmp_path):
    meta = session.build_meta({"foo": 1}, mode="stream")
    session.write_meta(tmp_path, meta)
    loaded = session.read_meta(tmp_path)
    assert loaded["schema_version"] == 1
    assert loaded["mode"] == "stream"
    assert loaded["config"] == {"foo": 1}
    assert "geometry" in loaded
    assert loaded["time_anchor"]["monotonic_ns"] > 0

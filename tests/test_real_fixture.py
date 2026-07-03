"""Tests gegen eine echte STL27L-Aufzeichnung (3 s, vom Gerät).

Die Fixture wurde mit ``scanorama lidar-test --save`` auf dem Scanner-Pi
aufgenommen (2026-07-02). Sie stellt sicher, dass Extraktion und
Dekodierung mit echten Gerätedaten funktionieren — nicht nur mit dem
synthetischen Mock.
"""

from pathlib import Path

import numpy as np
import pytest

from scanorama.lidar import protocol

FIXTURE = Path(__file__).parent / "fixtures" / "stl27l_3s.bin"


@pytest.fixture(scope="module")
def frames():
    raw = FIXTURE.read_bytes()
    frames, offsets = protocol.extract_frames(raw)
    assert len(frames) > 5000  # ~1800 Frames/s × 3 s
    return frames


def test_crc_error_rate_low(frames):
    ok = protocol.check_crc_many(frames)
    error_rate = 1.0 - ok.mean()
    assert error_rate < 0.01  # deutlich unter 1 %


def test_decoded_values_plausible(frames):
    ok = protocol.check_crc_many(frames)
    d = protocol.decode_frames(frames[ok])

    # Rotor: STL27L nominal ~10 Hz
    rotor_hz = d["frame_speed_deg_s"].mean() / 360.0
    assert 8.0 < rotor_hz < 12.0

    # Winkel decken (fast) den vollen Kreis ab
    angles = d["angle_deg"]
    assert angles.min() < 5.0
    assert angles.max() > 355.0

    # Gültige Distanzen im Sensorbereich (STL27L: bis 25 m)
    dist = d["distance_mm"][d["distance_mm"] > 0]
    assert len(dist) > 10000
    assert dist.max() <= 25000

    # Interner ms-Timestamp läuft monoton (mit Wrap bei 30000)
    ts = d["frame_timestamp_ms"].astype(np.int64)
    delta = np.diff(ts) % protocol.TIMESTAMP_WRAP_MS
    # nominal ~0.55 ms Frame-Abstand → Lücken >5 ms sind Paketverluste
    gap_rate = (delta > 5).mean()
    assert gap_rate < 0.01

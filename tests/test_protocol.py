"""Tests für das STL27L-Protokoll (CRC, Kodierung, Extraktion, Dekodierung)."""

import numpy as np
import pytest

from pilidar.lidar import protocol


def _sample_frame(start=10.0, end=12.0, ts=123):
    dists = [1000 + 10 * i for i in range(12)]
    intens = list(range(100, 112))
    return protocol.build_frame(start, end, dists, intens,
                                speed_deg_s=3600, timestamp_ms=ts)


def test_build_and_parse_roundtrip():
    frame = _sample_frame()
    parsed = protocol.parse_frame(frame)
    assert parsed is not None
    assert parsed.start_angle_deg == pytest.approx(10.0)
    assert parsed.end_angle_deg == pytest.approx(12.0)
    assert parsed.timestamp_ms == 123
    assert parsed.motor_hz == pytest.approx(10.0)
    assert parsed.distances_mm == [1000 + 10 * i for i in range(12)]
    assert parsed.intensities == list(range(100, 112))


def test_parse_rejects_bad_crc():
    frame = bytearray(_sample_frame())
    frame[-1] ^= 0xFF
    assert protocol.parse_frame(bytes(frame)) is None


def test_parse_rejects_wrong_length_and_header():
    assert protocol.parse_frame(b"\x54\x2c") is None
    frame = bytearray(_sample_frame())
    frame[0] = 0x55
    assert protocol.parse_frame(bytes(frame)) is None


def test_point_angles_wraparound():
    frame = protocol.parse_frame(_sample_frame(start=359.0, end=1.2))
    angles = frame.point_angles_deg()
    assert angles[0] == pytest.approx(359.0)
    assert angles[-1] == pytest.approx(1.2, abs=0.01)
    # Winkel müssen modulo 360 monoton steigen
    unwrapped = np.unwrap(np.radians(angles))
    assert np.all(np.diff(unwrapped) > 0)


def test_extract_frames_with_garbage_and_partials():
    f1, f2, f3 = _sample_frame(0, 2), _sample_frame(2, 4), _sample_frame(4, 6)
    stream = b"\xde\xad" + f1 + b"\x00\x54" + f2 + f3[:20]  # f3 unvollständig
    frames, offsets = protocol.extract_frames(stream)
    assert len(frames) == 2
    assert offsets[0] == 2
    assert bytes(frames[0]) == f1
    assert bytes(frames[1]) == f2


def test_extract_frames_resync_after_corruption():
    # Frame mit zerstörtem Header wird übersprungen, danach Resync
    f1, f2 = _sample_frame(0, 2), _sample_frame(2, 4)
    broken = b"\x11" + f1[1:]  # Header kaputt
    frames, _ = protocol.extract_frames(broken + f2)
    assert len(frames) == 1
    assert bytes(frames[0]) == f2


def test_check_crc_many_matches_scalar():
    good = np.frombuffer(_sample_frame(), dtype=np.uint8)
    bad = good.copy()
    bad[-1] ^= 0xFF
    frames = np.stack([good, bad, good])
    ok = protocol.check_crc_many(frames)
    assert ok.tolist() == [True, False, True]


def test_decode_frames_matches_parse_frame():
    raw = _sample_frame(350.0, 355.5, ts=42)
    frames, _ = protocol.extract_frames(raw)
    d = protocol.decode_frames(frames)

    ref = protocol.parse_frame(raw)
    assert d["distance_mm"].tolist() == ref.distances_mm
    assert d["intensity"].tolist() == ref.intensities
    np.testing.assert_allclose(d["angle_deg"], ref.point_angles_deg(), atol=1e-9)
    assert d["frame_timestamp_ms"][0] == 42
    assert d["frame_speed_deg_s"][0] == pytest.approx(3600)
    assert d["frame_idx"].tolist() == [0] * 12


def test_decode_frames_empty():
    d = protocol.decode_frames(np.empty((0, protocol.FRAME_SIZE), dtype=np.uint8))
    assert len(d["angle_deg"]) == 0

"""Tests für die Offline-Dekodierung (Rohdaten-Ordner → points.npz)."""

import numpy as np
import pytest

from pilidar.lidar import protocol
from pilidar.scan import decode, session


def _make_scan_dir(tmp_path, n_frames=100, corrupt_idx=()):
    """Baut einen synthetischen Rohdaten-Ordner.

    Frames laufen zeitlich äquidistant über 1 s (t = 0 … 1e9 ns),
    der Motor dreht in derselben Zeit linear von 0° auf 10°.
    """
    frames = []
    deg_per_frame = 2.0
    for i in range(n_frames):
        start = (i * deg_per_frame) % 360.0
        end = (start + deg_per_frame) % 360.0
        dists = [1000 + i] * protocol.POINTS_PER_FRAME
        frame = bytearray(protocol.build_frame(
            start, end, dists, [50] * 12, timestamp_ms=i))
        if i in corrupt_idx:
            frame[-1] ^= 0xFF
        frames.append(bytes(frame))

    raw = b"".join(frames)
    (tmp_path / "lidar_raw.bin").write_bytes(raw)

    # Ein Chunk pro Frame mit äquidistanten Zeitstempeln
    offsets = np.arange(1, n_frames + 1) * protocol.FRAME_SIZE
    t_ns = np.linspace(0, 1e9, n_frames).astype(np.int64)
    np.savez_compressed(tmp_path / "lidar_index.npz",
                        chunk_end_offset=offsets, chunk_t_ns=t_ns)

    # Motor: 0° → 10° über die volle Sekunde
    with open(tmp_path / session.TIMELINE_NAME, "w") as f:
        f.write("t_ns,event,azimuth_deg\n")
        f.write("0,seg_start,0.0\n")
        f.write("1000000000,seg_end,10.0\n")
    return raw


def test_decode_scan_basic(tmp_path):
    _make_scan_dir(tmp_path)
    stats = decode.decode_scan(tmp_path)

    assert stats["frames_total"] == 100
    assert stats["frames_crc_ok"] == 100
    assert stats["crc_error_rate"] == 0
    assert stats["points_valid"] == 100 * 12
    assert stats["rotor_hz_mean"] == pytest.approx(10.0, abs=0.1)

    pts = np.load(tmp_path / session.POINTS_NAME)
    # Azimut: erster Frame bei t=0 → 0°, letzter bei t=1s → 10°
    assert pts["azimuth_deg"][0] == pytest.approx(0.0, abs=0.01)
    assert pts["azimuth_deg"][-1] == pytest.approx(10.0, abs=0.2)
    # Azimut monoton steigend (Motor dreht nur vorwärts)
    assert np.all(np.diff(pts["azimuth_deg"]) >= 0)
    # Distanzen wie kodiert
    assert pts["distance_mm"][0] == 1000
    assert pts["distance_mm"][-1] == 1099
    # Elevationswinkel im gültigen Bereich
    assert pts["elevation_deg"].min() >= 0.0
    assert pts["elevation_deg"].max() < 360.0


def test_decode_scan_counts_crc_errors(tmp_path):
    _make_scan_dir(tmp_path, corrupt_idx={3, 50})
    stats = decode.decode_scan(tmp_path)
    # Kaputte Frames fallen raus, Rest bleibt nutzbar
    assert stats["frames_crc_ok"] == 98
    assert stats["points_valid"] == 98 * 12
    assert stats["crc_error_rate"] == pytest.approx(2 / 100, abs=1e-6)


def test_decode_drops_zero_distance(tmp_path):
    # Ein Frame komplett ohne Messungen (Distanz 0)
    frames = [
        protocol.build_frame(0, 2, [0] * 12, [0] * 12),
        protocol.build_frame(2, 4, [500] * 12, [10] * 12),
    ]
    raw = b"".join(frames)
    (tmp_path / "lidar_raw.bin").write_bytes(raw)
    np.savez_compressed(
        tmp_path / "lidar_index.npz",
        chunk_end_offset=np.array([len(raw)], dtype=np.int64),
        chunk_t_ns=np.array([0], dtype=np.int64))
    with open(tmp_path / session.TIMELINE_NAME, "w") as f:
        f.write("t_ns,event,azimuth_deg\n0,init,0.0\n")

    stats = decode.decode_scan(tmp_path)
    assert stats["points_valid"] == 12
    assert stats["points_zero_distance"] == 12


def test_decode_empty_raw_raises(tmp_path):
    (tmp_path / "lidar_raw.bin").write_bytes(b"\x00" * 100)
    np.savez_compressed(
        tmp_path / "lidar_index.npz",
        chunk_end_offset=np.array([100], dtype=np.int64),
        chunk_t_ns=np.array([0], dtype=np.int64))
    with open(tmp_path / session.TIMELINE_NAME, "w") as f:
        f.write("t_ns,event,azimuth_deg\n0,init,0.0\n")
    with pytest.raises(ValueError, match="Keine LiDAR-Frames"):
        decode.decode_scan(tmp_path)

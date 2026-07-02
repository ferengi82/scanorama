"""Offline-Dekodierung: Rohdaten-Ordner → points.npz.

Läuft nach der Aufnahme auf dem Pi (Komfortformat) und kann jederzeit
am PC wiederholt werden (``pilidar decode <ordner>``) — die Rohdaten
bleiben die Master-Quelle.

Ablauf:
  1. ``lidar_raw.bin`` einlesen, Frames extrahieren (Header-Suche),
     CRC prüfen, ungültige Frames verwerfen (nur Statistik).
  2. Jedem Frame den Host-Zeitstempel seines Lese-Chunks zuordnen
     (``lidar_index.npz``, searchsorted über Byte-Offsets).
  3. Azimut(t) aus ``motor_timeline.csv`` linear interpolieren und
     jedem Punkt zuweisen.
  4. Punkte mit Distanz 0 (keine Messung) verwerfen, Rest als
     ``points.npz`` speichern.

points.npz-Felder (alle Arrays gleich lang, ein Eintrag pro Punkt):
    t_ns          int64   Host-Empfangszeit (monotonic; Anker in meta.json)
    elevation_deg float32 nativer LiDAR-Winkel (Konvention: siehe meta.json)
    azimuth_deg   float32 interpolierte Plattform-Drehung
    distance_mm   uint16  Distanz in Millimetern
    intensity     uint8   Rückstrahlstärke
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path

import numpy as np

from ..lidar import protocol
from . import session

log = logging.getLogger(__name__)


def load_timeline(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Liest motor_timeline.csv → (t_ns, azimuth_deg) Arrays."""
    t, az = [], []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            t.append(int(row["t_ns"]))
            az.append(float(row["azimuth_deg"]))
    return np.asarray(t, dtype=np.int64), np.asarray(az, dtype=np.float64)


def decode_scan(scan_dir: str | Path) -> dict:
    """Dekodiert einen Scan-Ordner und schreibt points.npz.

    Returns:
        Statistik-Dict (Frames, CRC-Fehler, Punkte, Rotor-Hz, …)
    """
    scan_dir = Path(scan_dir)
    raw_path = scan_dir / "lidar_raw.bin"
    index_path = scan_dir / "lidar_index.npz"
    timeline_path = scan_dir / session.TIMELINE_NAME

    raw = raw_path.read_bytes()
    index = np.load(index_path)
    chunk_end = index["chunk_end_offset"]
    chunk_t = index["chunk_t_ns"]

    # --- 1. Frames extrahieren + CRC ---
    frames, offsets = protocol.extract_frames(raw)
    crc_ok = protocol.check_crc_many(frames) if len(frames) else np.empty(0, bool)
    n_bad = int(len(frames) - crc_ok.sum())
    frames_ok = frames[crc_ok]
    offsets_ok = offsets[crc_ok]
    if len(frames) == 0:
        raise ValueError(f"Keine LiDAR-Frames in {raw_path} gefunden!")
    crc_error_rate = n_bad / len(frames)
    log.info(f"Frames: {len(frames)} extrahiert, {n_bad} CRC-Fehler "
             f"({crc_error_rate * 100:.3f}%)")

    # --- 2. Host-Zeit pro Frame (Chunk-Zuordnung) ---
    # Ein Frame ist vollständig empfangen, sobald sein letztes Byte da ist →
    # erster Chunk, dessen End-Offset das Frame-Ende abdeckt.
    chunk_idx = np.searchsorted(chunk_end, offsets_ok + protocol.FRAME_SIZE,
                                side="left")
    chunk_idx = np.clip(chunk_idx, 0, len(chunk_t) - 1)
    frame_t_ns = chunk_t[chunk_idx]

    # --- 3. Dekodieren + Azimut interpolieren ---
    decoded = protocol.decode_frames(frames_ok)
    point_t_ns = np.repeat(frame_t_ns, protocol.POINTS_PER_FRAME)

    tl_t, tl_az = load_timeline(timeline_path)
    if len(tl_t) == 0:
        raise ValueError(f"Leere Motor-Zeitleiste: {timeline_path}")
    azimuth = np.interp(point_t_ns, tl_t, tl_az)

    # --- 4. Ungültige Messungen (Distanz 0) verwerfen, speichern ---
    valid = decoded["distance_mm"] > 0
    n_dropped = int((~valid).sum())

    points_path = scan_dir / session.POINTS_NAME
    np.savez_compressed(
        points_path,
        t_ns=point_t_ns[valid],
        elevation_deg=decoded["angle_deg"][valid].astype(np.float32),
        azimuth_deg=azimuth[valid].astype(np.float32),
        distance_mm=decoded["distance_mm"][valid],
        intensity=decoded["intensity"][valid],
    )

    n_points = int(valid.sum())
    rotor_hz = float(np.mean(decoded["frame_speed_deg_s"]) / 360.0)
    duration_s = float((frame_t_ns[-1] - frame_t_ns[0]) / 1e9) if len(frame_t_ns) > 1 else 0.0
    stats = {
        "frames_total": int(len(frames)),
        "frames_crc_ok": int(crc_ok.sum()),
        "crc_error_rate": round(crc_error_rate, 6),
        "points_valid": n_points,
        "points_zero_distance": n_dropped,
        "rotor_hz_mean": round(rotor_hz, 2),
        "capture_span_s": round(duration_s, 2),
        "azimuth_min_deg": round(float(azimuth[valid].min()), 3) if n_points else None,
        "azimuth_max_deg": round(float(azimuth[valid].max()), 3) if n_points else None,
    }
    log.info(f"points.npz: {n_points} Punkte, Rotor ⌀{rotor_hz:.1f} Hz, "
             f"Azimut {stats['azimuth_min_deg']}°–{stats['azimuth_max_deg']}°")
    return stats


def decode_and_update_meta(scan_dir: str | Path) -> dict:
    """Dekodiert und trägt die Statistik in meta.json ein (falls vorhanden)."""
    scan_dir = Path(scan_dir)
    stats = decode_scan(scan_dir)
    try:
        meta = session.read_meta(scan_dir)
    except FileNotFoundError:
        log.warning("meta.json nicht gefunden — Decode-Statistik nicht gespeichert")
        return stats
    meta["decode"] = stats
    session.write_meta(scan_dir, meta)
    return stats

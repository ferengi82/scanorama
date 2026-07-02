"""STL27L-Protokoll: Frame-Format, CRC8, Kodierung und Dekodierung.

Der STL27L sendet nach Power-On unaufgefordert 47-Byte-Pakete
(921600 Baud, 8N1, unidirektional):

    | Feld        | Bytes | Beschreibung                                  |
    |-------------|-------|-----------------------------------------------|
    | Header      | 1     | immer 0x54                                    |
    | VerLen      | 1     | immer 0x2C (Typ 1, 12 Punkte)                 |
    | Speed       | 2 LE  | Drehgeschwindigkeit in 0.01 U/s? → raw/360=Hz |
    | Start Angle | 2 LE  | Startwinkel × 0.01°                           |
    | Data (12×)  | 36    | je 3 Bytes: Distanz (2 LE, mm) + Intensität   |
    | End Angle   | 2 LE  | Endwinkel × 0.01°                             |
    | Timestamp   | 2 LE  | ms-Zähler des Controllers, Wrap bei 30000     |
    | CRC8        | 1     | über alle 46 vorherigen Bytes (Lookup-Table)  |

Winkel pro Punkt entstehen durch lineare Interpolation zwischen Start-
und Endwinkel (11 Schritte für 12 Punkte, Wraparound bei 360°).

Dieses Modul ist bewusst hardwarefrei (keine serial-Imports) und
vollständig per pytest testbar. Die vektorisierten Funktionen
(extract_frames, check_crc_many, decode_frames) verarbeiten ganze
Aufzeichnungen auf einmal — schnell genug für den Pi.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

HEADER = 0x54
VERLEN = 0x2C
POINTS_PER_FRAME = 12
FRAME_SIZE = 47
TIMESTAMP_WRAP_MS = 30000

# CRC8-Lookup-Table aus dem STL27L-Datenblatt (übernommen aus v1).
CRC_TABLE = bytes([
    0x00, 0x4d, 0x9a, 0xd7, 0x79, 0x34, 0xe3, 0xae, 0xf2, 0xbf, 0x68, 0x25, 0x8b, 0xc6, 0x11, 0x5c,
    0xa9, 0xe4, 0x33, 0x7e, 0xd0, 0x9d, 0x4a, 0x07, 0x5b, 0x16, 0xc1, 0x8c, 0x22, 0x6f, 0xb8, 0xf5,
    0x1f, 0x52, 0x85, 0xc8, 0x66, 0x2b, 0xfc, 0xb1, 0xed, 0xa0, 0x77, 0x3a, 0x94, 0xd9, 0x0e, 0x43,
    0xb6, 0xfb, 0x2c, 0x61, 0xcf, 0x82, 0x55, 0x18, 0x44, 0x09, 0xde, 0x93, 0x3d, 0x70, 0xa7, 0xea,
    0x3e, 0x73, 0xa4, 0xe9, 0x47, 0x0a, 0xdd, 0x90, 0xcc, 0x81, 0x56, 0x1b, 0xb5, 0xf8, 0x2f, 0x62,
    0x97, 0xda, 0x0d, 0x40, 0xee, 0xa3, 0x74, 0x39, 0x65, 0x28, 0xff, 0xb2, 0x1c, 0x51, 0x86, 0xcb,
    0x21, 0x6c, 0xbb, 0xf6, 0x58, 0x15, 0xc2, 0x8f, 0xd3, 0x9e, 0x49, 0x04, 0xaa, 0xe7, 0x30, 0x7d,
    0x88, 0xc5, 0x12, 0x5f, 0xf1, 0xbc, 0x6b, 0x26, 0x7a, 0x37, 0xe0, 0xad, 0x03, 0x4e, 0x99, 0xd4,
    0x7c, 0x31, 0xe6, 0xab, 0x05, 0x48, 0x9f, 0xd2, 0x8e, 0xc3, 0x14, 0x59, 0xf7, 0xba, 0x6d, 0x20,
    0xd5, 0x98, 0x4f, 0x02, 0xac, 0xe1, 0x36, 0x7b, 0x27, 0x6a, 0xbd, 0xf0, 0x5e, 0x13, 0xc4, 0x89,
    0x63, 0x2e, 0xf9, 0xb4, 0x1a, 0x57, 0x80, 0xcd, 0x91, 0xdc, 0x0b, 0x46, 0xe8, 0xa5, 0x72, 0x3f,
    0xca, 0x87, 0x50, 0x1d, 0xb3, 0xfe, 0x29, 0x64, 0x38, 0x75, 0xa2, 0xef, 0x41, 0x0c, 0xdb, 0x96,
    0x42, 0x0f, 0xd8, 0x95, 0x3b, 0x76, 0xa1, 0xec, 0xb0, 0xfd, 0x2a, 0x67, 0xc9, 0x84, 0x53, 0x1e,
    0xeb, 0xa6, 0x71, 0x3c, 0x92, 0xdf, 0x08, 0x45, 0x19, 0x54, 0x83, 0xce, 0x60, 0x2d, 0xfa, 0xb7,
    0x5d, 0x10, 0xc7, 0x8a, 0x24, 0x69, 0xbe, 0xf3, 0xaf, 0xe2, 0x35, 0x78, 0xd6, 0x9b, 0x4c, 0x01,
    0xf4, 0xb9, 0x6e, 0x23, 0x8d, 0xc0, 0x17, 0x5a, 0x06, 0x4b, 0x9c, 0xd1, 0x7f, 0x32, 0xe5, 0xa8,
])

_CRC_TABLE_NP = np.frombuffer(CRC_TABLE, dtype=np.uint8)

# Strukturiertes dtype für die vektorisierte Frame-Dekodierung.
FRAME_DTYPE = np.dtype([
    ("header", "u1"),
    ("verlen", "u1"),
    ("speed", "<u2"),
    ("start_angle", "<u2"),
    ("points", [("distance_mm", "<u2"), ("intensity", "u1")], (POINTS_PER_FRAME,)),
    ("end_angle", "<u2"),
    ("timestamp_ms", "<u2"),
    ("crc8", "u1"),
])
assert FRAME_DTYPE.itemsize == FRAME_SIZE


def calc_crc8(data: bytes) -> int:
    """CRC8 über einen Byte-String (skalare Referenzimplementierung)."""
    crc = 0
    for b in data:
        crc = CRC_TABLE[(crc ^ b) & 0xFF]
    return crc


@dataclass
class Frame:
    """Ein dekodiertes STL27L-Paket (für Einzelframe-Nutzung/Tests)."""
    speed_deg_s: float          # Rotor-Geschwindigkeit in °/s
    start_angle_deg: float
    end_angle_deg: float
    timestamp_ms: int
    distances_mm: list[int]     # 12 Werte, 0 = keine Messung
    intensities: list[int]      # 12 Werte

    @property
    def motor_hz(self) -> float:
        return self.speed_deg_s / 360.0

    def point_angles_deg(self) -> list[float]:
        """Winkel der 12 Punkte per linearer Interpolation (mit Wraparound)."""
        diff = self.end_angle_deg - self.start_angle_deg
        if diff < 0:
            diff += 360.0
        step = diff / (POINTS_PER_FRAME - 1)
        return [(self.start_angle_deg + step * i) % 360.0
                for i in range(POINTS_PER_FRAME)]


def parse_frame(frame: bytes) -> Frame | None:
    """Dekodiert ein einzelnes 47-Byte-Paket. None bei ungültigem Frame."""
    if len(frame) != FRAME_SIZE:
        return None
    if frame[0] != HEADER or frame[1] != VERLEN:
        return None
    if calc_crc8(frame[:-1]) != frame[-1]:
        return None

    speed_raw = struct.unpack_from("<H", frame, 2)[0]
    start_angle = struct.unpack_from("<H", frame, 4)[0] * 0.01
    end_angle = struct.unpack_from("<H", frame, 42)[0] * 0.01
    timestamp_ms = struct.unpack_from("<H", frame, 44)[0]

    distances, intensities = [], []
    for i in range(POINTS_PER_FRAME):
        off = 6 + i * 3
        distances.append(struct.unpack_from("<H", frame, off)[0])
        intensities.append(frame[off + 2])

    return Frame(
        speed_deg_s=float(speed_raw),
        start_angle_deg=start_angle,
        end_angle_deg=end_angle,
        timestamp_ms=timestamp_ms,
        distances_mm=distances,
        intensities=intensities,
    )


def build_frame(start_angle_deg: float, end_angle_deg: float,
                distances_mm: list[int], intensities: list[int],
                speed_deg_s: float = 3600.0, timestamp_ms: int = 0) -> bytes:
    """Baut ein gültiges STL27L-Paket (für Tests und Mock-LiDAR)."""
    if len(distances_mm) != POINTS_PER_FRAME or len(intensities) != POINTS_PER_FRAME:
        raise ValueError(f"Genau {POINTS_PER_FRAME} Punkte erwartet")
    buf = bytearray()
    buf.append(HEADER)
    buf.append(VERLEN)
    buf += struct.pack("<H", int(round(speed_deg_s)) & 0xFFFF)
    buf += struct.pack("<H", int(round(start_angle_deg * 100)) % 36000)
    for d, i in zip(distances_mm, intensities):
        buf += struct.pack("<H", d & 0xFFFF)
        buf.append(i & 0xFF)
    buf += struct.pack("<H", int(round(end_angle_deg * 100)) % 36000)
    buf += struct.pack("<H", timestamp_ms % TIMESTAMP_WRAP_MS)
    buf.append(calc_crc8(bytes(buf)))
    assert len(buf) == FRAME_SIZE
    return bytes(buf)


# ---------------------------------------------------------------------------
# Vektorisierte Verarbeitung ganzer Aufzeichnungen (Offline-Dekodierung)
# ---------------------------------------------------------------------------

def extract_frames(raw: bytes | np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Extrahiert alle Frame-Kandidaten aus einem rohen Bytestrom.

    Sucht Header-Signaturen (0x54 0x2C), wählt daraus gierig nicht
    überlappende 47-Byte-Frames (Resynchronisation nach Byte-Verlust
    passiert automatisch, weil die nächste Signatur genommen wird).

    CRC wird hier NICHT geprüft — dafür check_crc_many() verwenden.

    Returns:
        (frames, offsets): frames als (N, 47) uint8-Array,
        offsets als (N,) int64 Byte-Offsets im Eingangsstrom.
    """
    buf = np.frombuffer(bytes(raw), dtype=np.uint8) if not isinstance(raw, np.ndarray) else raw
    n = len(buf)
    if n < FRAME_SIZE:
        return np.empty((0, FRAME_SIZE), dtype=np.uint8), np.empty(0, dtype=np.int64)

    # Alle Positionen mit Header+VerLen-Signatur (vektorisiert).
    candidates = np.flatnonzero((buf[:-1] == HEADER) & (buf[1:] == VERLEN))
    candidates = candidates[candidates + FRAME_SIZE <= n]

    # Gierige Auswahl nicht überlappender Frames.
    offsets: list[int] = []
    pos = 0
    for c in candidates:
        if c >= pos:
            offsets.append(int(c))
            pos = int(c) + FRAME_SIZE

    if not offsets:
        return np.empty((0, FRAME_SIZE), dtype=np.uint8), np.empty(0, dtype=np.int64)

    off = np.asarray(offsets, dtype=np.int64)
    frames = buf[off[:, None] + np.arange(FRAME_SIZE)]
    return frames, off


def check_crc_many(frames: np.ndarray) -> np.ndarray:
    """CRC8-Prüfung für viele Frames auf einmal.

    Args:
        frames: (N, 47) uint8-Array

    Returns:
        (N,) bool-Array — True wenn CRC stimmt
    """
    crc = np.zeros(len(frames), dtype=np.uint8)
    for col in range(FRAME_SIZE - 1):
        crc = _CRC_TABLE_NP[crc ^ frames[:, col]]
    return crc == frames[:, FRAME_SIZE - 1]


def decode_frames(frames: np.ndarray) -> dict[str, np.ndarray]:
    """Dekodiert (N, 47)-Frames vektorisiert in Punkt-Arrays.

    Pro Frame entstehen 12 Punkte; Winkel per linearer Interpolation
    zwischen Start- und Endwinkel (Wraparound bei 360°).
    Punkte mit Distanz 0 (keine Messung) werden NICHT entfernt —
    das entscheidet der Aufrufer (frame_idx erlaubt die Zuordnung).

    Returns:
        dict mit Arrays der Länge N*12:
          angle_deg (f8), distance_mm (u2), intensity (u1), frame_idx (i8)
        sowie Frame-Arrays der Länge N:
          frame_speed_deg_s (f8), frame_timestamp_ms (u2)
    """
    n = len(frames)
    if n == 0:
        return {
            "angle_deg": np.empty(0), "distance_mm": np.empty(0, np.uint16),
            "intensity": np.empty(0, np.uint8), "frame_idx": np.empty(0, np.int64),
            "frame_speed_deg_s": np.empty(0), "frame_timestamp_ms": np.empty(0, np.uint16),
        }

    rec = np.ascontiguousarray(frames).view(FRAME_DTYPE).reshape(n)

    start = rec["start_angle"].astype(np.float64) * 0.01
    end = rec["end_angle"].astype(np.float64) * 0.01
    diff = end - start
    diff[diff < 0] += 360.0
    step = diff / (POINTS_PER_FRAME - 1)

    i = np.arange(POINTS_PER_FRAME, dtype=np.float64)
    angles = (start[:, None] + step[:, None] * i[None, :]) % 360.0

    return {
        "angle_deg": angles.ravel(),
        "distance_mm": rec["points"]["distance_mm"].ravel(),
        "intensity": rec["points"]["intensity"].ravel(),
        "frame_idx": np.repeat(np.arange(n, dtype=np.int64), POINTS_PER_FRAME),
        "frame_speed_deg_s": rec["speed"].astype(np.float64),
        "frame_timestamp_ms": rec["timestamp_ms"].copy(),
    }

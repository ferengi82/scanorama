"""Verlustfreie Aufnahme des STL27L-Bytestroms.

Kernidee: Während der Aufnahme wird NICHTS geparst. Jeder vom seriellen
Port gelesene Chunk wird unverändert in ``lidar_raw.bin`` geschrieben;
parallel merkt sich ein Index pro Chunk den Byte-Offset am Chunk-Ende
und den Host-Zeitstempel (``time.monotonic_ns()``). Damit lässt sich
später jedem Frame ein Empfangszeitpunkt mit Millisekunden-Genauigkeit
zuordnen — mehr braucht die Azimut-Interpolation nicht (bei 1°/s
Drehgeschwindigkeit entspricht 1 ms gerade 0.001° Azimut).

Frame-Extraktion, CRC-Prüfung und Dekodierung passieren offline in
``scanorama.scan.decode`` (auf dem Pi nach dem Scan und/oder am PC).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Callable, Protocol

import numpy as np

from . import protocol

log = logging.getLogger(__name__)


class ByteSource(Protocol):
    """Minimales Interface, das serial.Serial und der Mock erfüllen."""
    in_waiting: int
    def read(self, size: int = 1) -> bytes: ...
    def reset_input_buffer(self) -> None: ...
    def close(self) -> None: ...


@dataclass
class CaptureResult:
    """Ergebnis einer Aufnahme (Statistik für Log und meta.json)."""
    raw_path: Path
    index_path: Path
    total_bytes: int = 0
    num_chunks: int = 0
    t_start_ns: int = 0
    t_end_ns: int = 0

    @property
    def duration_s(self) -> float:
        return (self.t_end_ns - self.t_start_ns) / 1e9


def open_lidar_serial(port: str, baud: int) -> ByteSource:
    """Öffnet den seriellen Port zum LiDAR-Adapterboard."""
    import serial
    ser = serial.Serial(port, baud, timeout=0.05)
    ser.reset_input_buffer()
    return ser


class LidarRecorder:
    """Schreibt den rohen LiDAR-Bytestrom chunk-weise auf Platte.

    Verwendung::

        rec = LidarRecorder(source, scan_dir)
        rec.start()                 # ab jetzt wird aufgezeichnet
        ...                         # Motor fahren lassen
        result = rec.stop()         # Dateien abschließen

    ``start()``/``stop()`` laufen im Aufrufer-Kontext; die eigentliche
    Leseschleife muss der Aufrufer treiben (``pump()`` zyklisch aufrufen)
    oder bequem ``record_until(condition)`` verwenden. Das hält die
    Kontrolle über das Timing beim Recorder-Orchestrator.
    """

    RAW_NAME = "lidar_raw.bin"
    INDEX_NAME = "lidar_index.npz"

    def __init__(self, source: ByteSource, scan_dir: Path):
        self.source = source
        self.scan_dir = Path(scan_dir)
        self._file: BinaryIO | None = None
        self._offsets: list[int] = []      # Byte-Offset NACH jedem Chunk
        self._times_ns: list[int] = []     # monotonic_ns pro Chunk
        self._total = 0
        self._t_start_ns = 0

    def start(self) -> None:
        """Aufnahme beginnen: Datei öffnen, Eingangspuffer verwerfen."""
        self._file = open(self.scan_dir / self.RAW_NAME, "wb")
        self.source.reset_input_buffer()
        self._t_start_ns = time.monotonic_ns()

    def pump(self) -> int:
        """Einen Lese-Zyklus ausführen. Rückgabe: gelesene Bytes."""
        data = self.source.read(self.source.in_waiting or 1)
        if not data:
            return 0
        assert self._file is not None, "start() wurde nicht aufgerufen"
        self._file.write(data)
        self._total += len(data)
        self._offsets.append(self._total)
        self._times_ns.append(time.monotonic_ns())
        return len(data)

    def record_until(self, done: Callable[[], bool],
                     progress: Callable[[int], None] | None = None,
                     progress_interval_s: float = 2.0) -> None:
        """Leseschleife bis ``done()`` True liefert.

        Liest danach noch kurz nach (Restdaten im Kernel-Puffer).
        ``progress`` bekommt zyklisch die Gesamt-Bytezahl.
        """
        last_progress = time.monotonic()
        while not done():
            self.pump()
            now = time.monotonic()
            if progress and now - last_progress >= progress_interval_s:
                progress(self._total)
                last_progress = now
        # Nachlauf: Puffer leeren (max. 0.3 s)
        deadline = time.monotonic() + 0.3
        while time.monotonic() < deadline:
            if self.pump() == 0:
                break

    def stop(self) -> CaptureResult:
        """Aufnahme beenden, Index schreiben, Statistik zurückgeben."""
        assert self._file is not None, "start() wurde nicht aufgerufen"
        t_end = time.monotonic_ns()
        self._file.close()
        self._file = None

        index_path = self.scan_dir / self.INDEX_NAME
        np.savez_compressed(
            index_path,
            chunk_end_offset=np.asarray(self._offsets, dtype=np.int64),
            chunk_t_ns=np.asarray(self._times_ns, dtype=np.int64),
        )
        result = CaptureResult(
            raw_path=self.scan_dir / self.RAW_NAME,
            index_path=index_path,
            total_bytes=self._total,
            num_chunks=len(self._offsets),
            t_start_ns=self._t_start_ns,
            t_end_ns=t_end,
        )
        log.info(f"Aufnahme beendet: {result.total_bytes/1e6:.1f} MB in "
                 f"{result.duration_s:.1f} s ({result.num_chunks} Chunks)")
        return result


def quick_check(source: ByteSource, seconds: float = 2.0) -> dict:
    """Kurzer Live-Test: liest ``seconds`` lang und dekodiert im Speicher.

    Für Selftest und ``scanorama lidar-test`` — prüft, ob plausible Daten
    ankommen, ohne etwas auf Platte zu schreiben.

    Returns:
        dict mit bytes, frames, crc_ok, crc_errors, points_valid,
        motor_hz_mean, raw (die gelesenen Rohbytes)
    """
    source.reset_input_buffer()
    buf = bytearray()
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        data = source.read(source.in_waiting or 1)
        if data:
            buf.extend(data)

    frames, _offsets = protocol.extract_frames(bytes(buf))
    crc_ok = protocol.check_crc_many(frames) if len(frames) else np.empty(0, bool)
    good = frames[crc_ok] if len(frames) else frames
    decoded = protocol.decode_frames(good)
    valid_points = int((decoded["distance_mm"] > 0).sum())
    motor_hz = (float(np.mean(decoded["frame_speed_deg_s"])) / 360.0
                if len(good) else 0.0)

    return {
        "bytes": len(buf),
        "frames": int(len(frames)),
        "crc_ok": int(crc_ok.sum()) if len(frames) else 0,
        "crc_errors": int(len(frames) - crc_ok.sum()) if len(frames) else 0,
        "points_valid": valid_points,
        "motor_hz_mean": motor_hz,
        "raw": bytes(buf),
    }

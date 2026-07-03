"""Aufnahme-Orchestrierung: Motor + LiDAR-Rohstrom → Scan-Ordner.

Zwei Modi:

**Stream** (Default): Der Stepper dreht kontinuierlich von az_start
nach az_end, der LiDAR-Bytestrom wird durchgehend aufgezeichnet.
Schnell und mechanisch sanft; Punktdichte über die Geschwindigkeit
steuerbar (STL27L ~10 Hz Rotor → bei 1°/s ≈ 10 Umdrehungen pro Grad).

**Schritt**: Der Stepper fährt Position für Position an und verweilt
dort für ``rounds_per_position`` LiDAR-Umdrehungen. Aufgezeichnet wird
durchgehend (auch während der Fahrt) — die Motor-Zeitleiste erlaubt
der Auswertung, Verweil- und Fahrphasen exakt zu trennen. Maximale
Punktdichte pro Position, dafür langsamer.

In beiden Fällen entsteht derselbe Rohdaten-Ordner (siehe session.py).
Es wird bewusst NICHT gefiltert — Stativ-Bereich, Nahbereich und
Ausreißer bleiben in den Rohdaten und werden erst am PC behandelt.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from ..config import Config
from ..lidar import mock as lidar_mock
from ..lidar import reader as lidar_reader
from ..motor import create_stepper
from . import decode, session

log = logging.getLogger(__name__)


def _open_lidar(cfg: Config, use_mock: bool) -> lidar_reader.ByteSource:
    if use_mock:
        log.info("Mock-LiDAR aktiv (kein /dev/ttyUSB0 nötig)")
        return lidar_mock.MockLidarSource(time_scale=60.0)
    source = lidar_reader.open_lidar_serial(cfg.lidar.port, cfg.lidar.baud)
    log.info(f"LiDAR verbunden: {cfg.lidar.port} @ {cfg.lidar.baud} Baud — "
             f"warte {cfg.lidar.startup_wait_s:.0f}s auf Hochlauf …")
    time.sleep(cfg.lidar.startup_wait_s)
    return source


def _selftest(source: lidar_reader.ByteSource) -> dict:
    """Kurzer Datencheck vor dem Scan. Bricht bei totem LiDAR ab."""
    check = lidar_reader.quick_check(source, seconds=2.0)
    if check["points_valid"] == 0:
        raise RuntimeError(
            "Keine gültigen LiDAR-Daten! Verkabelung/Port prüfen "
            f"(gelesen: {check['bytes']} Bytes, {check['frames']} Frames)"
        )
    log.info(f"LiDAR OK: {check['points_valid']} Punkte in 2s, "
             f"Rotor ⌀{check['motor_hz_mean']:.1f} Hz, "
             f"{check['crc_errors']} CRC-Fehler")
    check.pop("raw", None)  # Rohbytes nicht in meta.json schleppen
    return check


def run_scan(cfg: Config, use_mock_lidar: bool = False) -> Path:
    """Führt einen kompletten Scan aus. Rückgabe: Pfad des Scan-Ordners."""
    scan_dir = session.create_scan_dir(cfg.output_dir)
    log_handler = session.attach_file_logger(scan_dir)
    try:
        return _run_scan_inner(cfg, scan_dir, use_mock_lidar)
    finally:
        session.detach_file_logger(log_handler)


def _run_scan_inner(cfg: Config, scan_dir: Path, use_mock_lidar: bool) -> Path:
    total_deg = cfg.scan.az_end_deg - cfg.scan.az_start_deg
    mode = cfg.scan.mode
    log.info("=" * 60)
    log.info(f"scanorama-Scan ({mode}-Modus): Azimut "
             f"{cfg.scan.az_start_deg:.1f}° → {cfg.scan.az_end_deg:.1f}°")

    meta = session.build_meta(cfg.to_dict(), mode=mode)
    meta["mock_lidar"] = use_mock_lidar

    lidar = _open_lidar(cfg, use_mock_lidar)
    stepper = None
    try:
        meta["selftest"] = _selftest(lidar)

        stepper = create_stepper(cfg.motor)
        meta["motor"] = stepper.describe()

        # Zur Startposition fahren (Aufzeichnung beginnt erst danach).
        if cfg.scan.az_start_deg != 0:
            log.info(f"Fahre zur Startposition ({cfg.scan.az_start_deg:.1f}°) …")
            stepper.move_degrees(cfg.scan.az_start_deg, speed_deg_s=10.0)
            time.sleep(0.5)

        recorder = lidar_reader.LidarRecorder(lidar, scan_dir)
        recorder.start()

        t0 = time.monotonic()

        def progress(total_bytes: int) -> None:
            az = stepper.current_deg
            pct = ((az - cfg.scan.az_start_deg) / total_deg * 100
                   if total_deg else 100.0)
            elapsed = time.monotonic() - t0
            eta = elapsed / max(pct, 0.1) * (100 - pct) if pct > 0 else 0
            log.info(f"Aufnahme: Az {az:+7.2f}° | {pct:5.1f}% | "
                     f"{total_bytes / 1e6:6.1f} MB | ETA {eta:.0f}s")

        if mode == "stream":
            _run_stream(cfg, stepper, recorder, total_deg, progress)
        elif mode == "step":
            _run_step(cfg, stepper, recorder, meta["selftest"]["motor_hz_mean"],
                      progress)
        else:
            raise ValueError(f"Unbekannter Scan-Modus: {mode!r}")

        capture = recorder.stop()
        stepper.timeline.save_csv(scan_dir / session.TIMELINE_NAME)

        meta["capture"] = {
            "total_bytes": capture.total_bytes,
            "num_chunks": capture.num_chunks,
            "t_start_ns": capture.t_start_ns,
            "t_end_ns": capture.t_end_ns,
            "duration_s": round(capture.duration_s, 2),
        }
        session.write_meta(scan_dir, meta)

    finally:
        if stepper is not None:
            stepper.disable()
            stepper.cleanup()
        lidar.close()

    # --- Komfortformat: points.npz (Rohdaten bleiben Master) ---
    if cfg.scan.decode_after_scan:
        log.info("Dekodiere Rohdaten → points.npz …")
        stats = decode.decode_and_update_meta(scan_dir)
        log.info(f"Decode: {stats['points_valid']} Punkte, "
                 f"CRC-Fehlerquote {stats['crc_error_rate'] * 100:.3f}%")

    log.info("=" * 60)
    log.info(f"Scan abgeschlossen: {scan_dir}/")
    return scan_dir


def _run_stream(cfg: Config, stepper, recorder: lidar_reader.LidarRecorder,
                total_deg: float, progress) -> None:
    """Stream-Modus: Motor kontinuierlich, Aufnahme läuft parallel."""
    speed = cfg.scan.stream_speed_deg_s
    est = abs(total_deg) / speed
    log.info(f"Stream: {total_deg:+.1f}° @ {speed:.2f}°/s "
             f"(≈{est:.0f}s, Rotor-Umdrehungen pro Grad ≈{10.0 / speed:.0f})")
    done = stepper.start_continuous(total_deg, speed)
    recorder.record_until(done.is_set, progress=progress)


def _run_step(cfg: Config, stepper, recorder: lidar_reader.LidarRecorder,
              rotor_hz: float, progress) -> None:
    """Schrittmodus: Position anfahren, verweilen, weiter.

    Die Verweildauer pro Position ergibt sich aus der gemessenen
    Rotordrehzahl: rounds/rotor_hz plus 10 % Reserve. Aufgezeichnet
    wird durchgehend — die Zeitleiste trennt Fahrt- und Standphasen.
    """
    rotor_hz = max(rotor_hz, 1.0)  # Schutz gegen kaputte Selftest-Werte
    dwell_s = cfg.scan.rounds_per_position / rotor_hz * 1.1
    total_deg = cfg.scan.az_end_deg - cfg.scan.az_start_deg
    positions = int(round(abs(total_deg) / cfg.scan.az_step_deg)) + 1
    step = cfg.scan.az_step_deg * (1 if total_deg >= 0 else -1)
    est = positions * (dwell_s + 0.3)
    log.info(f"Schrittmodus: {positions} Positionen à {cfg.scan.az_step_deg:.2f}°, "
             f"{cfg.scan.rounds_per_position} Umdrehungen ≈{dwell_s:.1f}s/Position "
             f"(gesamt ≈{est:.0f}s)")

    for i in range(positions):
        deadline = time.monotonic() + dwell_s
        recorder.record_until(lambda: time.monotonic() >= deadline,
                              progress=progress)
        if i < positions - 1:
            stepper.move_degrees(step, speed_deg_s=10.0)

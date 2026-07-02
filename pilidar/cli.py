"""Kommandozeilen-Interface des Scanners.

Subcommands:
    scan        Kompletten Scan aufzeichnen (Stream- oder Schrittmodus)
    selftest    LiDAR-Kurztest (2 s lesen, Statistik ausgeben)
    lidar-test  LiDAR N Sekunden lesen, optional Roh-Fixture speichern
    motor-test  Stepper um N Grad drehen (Verkabelungs-/Richtungstest)
    decode      Rohdaten-Ordner (erneut) zu points.npz dekodieren

Beispiele:
    pilidar scan                          # 0–180° Stream @ 1°/s
    pilidar scan --speed 5                # schneller, weniger dicht
    pilidar scan --mode step --az-step 1 --rounds 10
    pilidar scan --driver stspin220       # Fallback-Treiber
    pilidar motor-test --degrees 10
    pilidar decode ~/scans/2026-07-02_scan_01_001
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import __version__
from .config import Config

log = logging.getLogger("pilidar")


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )


def _add_hardware_args(p: argparse.ArgumentParser, motor: bool = True) -> None:
    """Gemeinsame Hardware-Argumente (Defaults aus config.py)."""
    cfg = Config()
    g = p.add_argument_group("Hardware")
    g.add_argument("--lidar-port", default=cfg.lidar.port,
                   help="Serial-Port des LiDAR-Adapterboards")
    if motor:
        g.add_argument("--driver", choices=["tmc2209", "stspin220", "mock"],
                       default=cfg.motor.driver,
                       help="Stepper-Treiber (mock = ohne Hardware)")
        g.add_argument("--gear-ratio", type=float, default=cfg.motor.gear_ratio,
                       help="Getriebeübersetzung Stepper → Drehteller "
                            "(Riemen 60T/20T = 3.0)")
        g.add_argument("--microsteps", type=int, default=cfg.motor.microsteps,
                       choices=[1, 2, 4, 8, 16, 32, 64, 128, 256],
                       help="Microstepping (nur TMC2209; STSPIN220 fest 1/16)")
        g.add_argument("--invert-dir", action="store_true",
                       help="Drehrichtung invertieren (Default: nicht invertiert)")
        g.add_argument("--spreadcycle", action="store_true",
                       help="SpreadCycle statt StealthChop (mehr Drehmoment, lauter)")
        g.add_argument("--uart-port", default=cfg.motor.uart_port,
                       help="UART-Port zum TMC2209")


def _config_from_args(args: argparse.Namespace) -> Config:
    cfg = Config()
    cfg.lidar.port = args.lidar_port
    if hasattr(args, "driver"):
        cfg.motor.driver = args.driver
        cfg.motor.gear_ratio = args.gear_ratio
        cfg.motor.microsteps = args.microsteps
        cfg.motor.invert_dir = args.invert_dir
        cfg.motor.stealthchop = not args.spreadcycle
        cfg.motor.uart_port = args.uart_port
    return cfg


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_scan(args: argparse.Namespace) -> int:
    from .scan.recorder import run_scan

    cfg = _config_from_args(args)
    cfg.scan.mode = args.mode
    cfg.scan.az_start_deg = args.az_start
    cfg.scan.az_end_deg = args.az_end
    cfg.scan.stream_speed_deg_s = args.speed
    cfg.scan.az_step_deg = args.az_step
    cfg.scan.rounds_per_position = args.rounds
    cfg.scan.decode_after_scan = not args.no_decode
    cfg.output_dir = args.output_dir

    try:
        scan_dir = run_scan(cfg, use_mock_lidar=args.mock_lidar)
    except KeyboardInterrupt:
        log.info("Abbruch durch Benutzer (Ctrl+C)")
        return 130
    except Exception as e:
        log.exception(f"Scan fehlgeschlagen: {e}")
        return 1
    print(scan_dir)
    return 0


def cmd_selftest(args: argparse.Namespace) -> int:
    import time

    from .lidar import reader

    cfg = _config_from_args(args)
    log.info(f"Öffne {cfg.lidar.port} — warte {cfg.lidar.startup_wait_s:.0f}s "
             f"auf LiDAR-Hochlauf …")
    source = reader.open_lidar_serial(cfg.lidar.port, cfg.lidar.baud)
    try:
        time.sleep(cfg.lidar.startup_wait_s)
        check = reader.quick_check(source, seconds=2.0)
    finally:
        source.close()

    log.info(f"Bytes: {check['bytes']}, Frames: {check['frames']}, "
             f"CRC-Fehler: {check['crc_errors']}, "
             f"gültige Punkte: {check['points_valid']}, "
             f"Rotor: ⌀{check['motor_hz_mean']:.1f} Hz")
    if check["points_valid"] > 0:
        log.info("Selftest OK ✓")
        return 0
    log.error("Selftest FEHLGESCHLAGEN — keine gültigen Daten")
    return 1


def cmd_lidar_test(args: argparse.Namespace) -> int:
    import time

    from .lidar import reader

    cfg = _config_from_args(args)
    source = reader.open_lidar_serial(cfg.lidar.port, cfg.lidar.baud)
    try:
        log.info(f"Warte {cfg.lidar.startup_wait_s:.0f}s auf LiDAR-Hochlauf …")
        time.sleep(cfg.lidar.startup_wait_s)
        log.info(f"Lese {args.seconds:.1f}s vom LiDAR …")
        check = reader.quick_check(source, seconds=args.seconds)
    finally:
        source.close()

    rate = check["bytes"] / args.seconds
    log.info(f"Bytes: {check['bytes']} ({rate / 1000:.0f} kB/s), "
             f"Frames: {check['frames']}, CRC-Fehler: {check['crc_errors']}, "
             f"gültige Punkte: {check['points_valid']}, "
             f"Rotor: ⌀{check['motor_hz_mean']:.1f} Hz")

    if args.save:
        Path(args.save).write_bytes(check["raw"])
        log.info(f"Rohstrom gespeichert: {args.save} ({check['bytes']} Bytes)")
    return 0 if check["points_valid"] > 0 else 1


def cmd_motor_test(args: argparse.Namespace) -> int:
    from .motor import create_stepper

    cfg = _config_from_args(args)
    stepper = create_stepper(cfg.motor)
    try:
        log.info(f"Drehe {args.degrees:+.1f}° @ {args.speed:.1f}°/s …")
        stepper.move_degrees(args.degrees, speed_deg_s=args.speed)
        if args.back:
            log.info("Und zurück …")
            stepper.move_degrees(-args.degrees, speed_deg_s=args.speed)
        log.info(f"Fertig — Position laut Zähler: {stepper.current_deg:+.2f}°")
    finally:
        stepper.disable()
        stepper.cleanup()
    return 0


def cmd_decode(args: argparse.Namespace) -> int:
    from .scan.decode import decode_and_update_meta

    for scan_dir in args.scan_dirs:
        p = Path(scan_dir)
        if not (p / "lidar_raw.bin").exists():
            log.error(f"Kein Rohdaten-Ordner: {p} (lidar_raw.bin fehlt)")
            return 1
        log.info(f"Dekodiere {p} …")
        stats = decode_and_update_meta(p)
        log.info(f"  → {stats['points_valid']} Punkte, "
                 f"CRC-Fehlerquote {stats['crc_error_rate'] * 100:.3f}%, "
                 f"Azimut {stats['azimuth_min_deg']}°–{stats['azimuth_max_deg']}°")
    return 0


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    cfg = Config()
    parser = argparse.ArgumentParser(
        prog="pilidar",
        description="3D-LiDAR-Scanner (STL27L + Stepper) — reines Aufnahmegerät: "
                    "zeichnet verlustfreie Rohdaten auf, Auswertung erfolgt am PC.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--version", action="version",
                        version=f"pilidar {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    # --- scan ---
    p = sub.add_parser("scan", help="Kompletten Scan aufzeichnen",
                       formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    g = p.add_argument_group("Scan-Geometrie")
    g.add_argument("--mode", choices=["stream", "step"], default=cfg.scan.mode,
                   help="stream = kontinuierliche Drehung, "
                        "step = Position für Position")
    g.add_argument("--az-start", type=float, default=cfg.scan.az_start_deg,
                   help="Azimut-Startwinkel in Grad")
    g.add_argument("--az-end", type=float, default=cfg.scan.az_end_deg,
                   help="Azimut-Endwinkel in Grad (180° genügt: der vertikale "
                        "360°-Scan deckt beide Seiten ab)")
    g.add_argument("--speed", type=float, default=cfg.scan.stream_speed_deg_s,
                   help="Drehgeschwindigkeit im Stream-Modus in °/s "
                        "(langsamer = dichter)")
    g.add_argument("--az-step", type=float, default=cfg.scan.az_step_deg,
                   help="Schrittweite im Schrittmodus in Grad")
    g.add_argument("--rounds", type=int, default=cfg.scan.rounds_per_position,
                   help="LiDAR-Umdrehungen pro Position im Schrittmodus")
    p.add_argument("--output-dir", default=cfg.output_dir,
                   help="Basisordner für Scan-Ordner")
    p.add_argument("--no-decode", action="store_true",
                   help="points.npz nach dem Scan NICHT erzeugen (nur Rohdaten)")
    p.add_argument("--mock-lidar", action="store_true",
                   help="Mock-LiDAR statt echter Hardware (Test ohne Gerät)")
    _add_hardware_args(p)
    p.set_defaults(func=cmd_scan)

    # --- selftest ---
    p = sub.add_parser("selftest", help="LiDAR-Kurztest (2 s)",
                       formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    _add_hardware_args(p, motor=False)
    p.set_defaults(func=cmd_selftest)

    # --- lidar-test ---
    p = sub.add_parser("lidar-test", help="LiDAR N Sekunden lesen, Statistik "
                                          "ausgeben, optional Rohstrom speichern",
                       formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("--seconds", type=float, default=5.0,
                   help="Lesedauer in Sekunden")
    p.add_argument("--save", metavar="DATEI",
                   help="Rohstrom als Binärdatei speichern (z.B. für Test-Fixtures)")
    _add_hardware_args(p, motor=False)
    p.set_defaults(func=cmd_lidar_test)

    # --- motor-test ---
    p = sub.add_parser("motor-test", help="Stepper-Testbewegung",
                       formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("--degrees", type=float, default=10.0,
                   help="Drehwinkel in Grad (am Drehteller)")
    p.add_argument("--speed", type=float, default=5.0,
                   help="Geschwindigkeit in °/s")
    p.add_argument("--back", action="store_true",
                   help="Anschließend zur Ausgangsposition zurückdrehen")
    _add_hardware_args(p)
    p.set_defaults(func=cmd_motor_test)

    # --- decode ---
    p = sub.add_parser("decode", help="Rohdaten-Ordner (erneut) dekodieren",
                       formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("scan_dirs", nargs="+", metavar="SCAN_ORDNER",
                   help="Ein oder mehrere Scan-Ordner mit lidar_raw.bin")
    p.set_defaults(func=cmd_decode)

    return parser


def main(argv: list[str] | None = None) -> int:
    _setup_logging()
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

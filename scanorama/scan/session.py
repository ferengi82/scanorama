"""Scan-Ordner und Metadaten.

Namensschema (übernommen aus v1, jetzt ein Ordner pro Scan):

    <output_dir>/yyyy-mm-dd_scan_XX_NNN/

    XX  = Session (01, 02, …). Neuer Tag → wieder 01. Innerhalb eines
          Tages: letzter Scan älter als 5 Minuten → neue Session.
    NNN = Standpunkt innerhalb der Session (001, 002, …).

Im Ordner liegen ausschließlich Rohdaten + Metadaten:

    lidar_raw.bin       unveränderter serieller Bytestrom des STL27L
    lidar_index.npz     Byte-Offset + Host-Zeitstempel pro Lese-Chunk
    motor_timeline.csv  Azimut-Ereignisse (t_ns, event, azimuth_deg)
    points.npz          dekodierte Punkttabelle (Komfortformat)
    meta.json           Parameter, Gerät, Zeitanker, Statistik
    scan.log            Logausgabe des Scans
"""

from __future__ import annotations

import json
import logging
import re
import socket
import subprocess
import time
from datetime import datetime, date
from pathlib import Path

from .. import __version__

log = logging.getLogger(__name__)

SESSION_TIMEOUT_S = 300  # >5 min Pause → neue Session
META_NAME = "meta.json"
TIMELINE_NAME = "motor_timeline.csv"
LOG_NAME = "scan.log"
POINTS_NAME = "points.npz"


def create_scan_dir(output_dir: str | Path) -> Path:
    """Legt den nächsten Scan-Ordner nach dem Namensschema an."""
    today_str = date.today().strftime("%Y-%m-%d")
    base = Path(output_dir)
    base.mkdir(parents=True, exist_ok=True)

    pattern = re.compile(rf"^{re.escape(today_str)}_scan_(\d+)_(\d+)$")
    candidates: list[tuple[float, int, int]] = []  # (mtime, session, standpunkt)
    for p in base.iterdir():
        if p.is_dir():
            m = pattern.match(p.name)
            if m:
                candidates.append((p.stat().st_mtime, int(m.group(1)), int(m.group(2))))

    if not candidates:
        session, standpoint = 1, 1
    else:
        candidates.sort()
        last_mtime, last_session, last_standpoint = candidates[-1]
        age_s = (datetime.now() - datetime.fromtimestamp(last_mtime)).total_seconds()
        if age_s > SESSION_TIMEOUT_S:
            session, standpoint = last_session + 1, 1
        else:
            session, standpoint = last_session, last_standpoint + 1

    name = f"{today_str}_scan_{session:02d}_{standpoint:03d}"
    while (base / name).exists():
        standpoint += 1
        name = f"{today_str}_scan_{session:02d}_{standpoint:03d}"

    scan_dir = base / name
    scan_dir.mkdir(parents=True, exist_ok=False)
    log.info(f"Scan-Ordner: {scan_dir}/ (Session {session:02d}, "
             f"Standpunkt {standpoint:03d})")
    return scan_dir


def attach_file_logger(scan_dir: Path) -> logging.Handler:
    """Hängt einen FileHandler für scan.log an den Root-Logger."""
    handler = logging.FileHandler(scan_dir / LOG_NAME, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logging.getLogger().addHandler(handler)
    return handler


def detach_file_logger(handler: logging.Handler) -> None:
    logging.getLogger().removeHandler(handler)
    handler.close()


def _git_commit() -> str | None:
    """Git-Commit des Pakets, falls aus einem Repo installiert/deployt."""
    try:
        out = subprocess.run(
            ["git", "-C", str(Path(__file__).resolve().parent), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        return out.stdout.strip() if out.returncode == 0 else None
    except Exception:
        return None


# Geometrie-Konvention des Aufbaus — wird in jede meta.json geschrieben,
# damit die PC-Auswertung die Rohdaten ohne Zusatzwissen interpretieren kann.
GEOMETRY_CONVENTION = {
    "lidar_mount": "vertikal — der STL27L scannt eine Vertikalebene",
    "elevation_deg": "nativer LiDAR-Winkel; 0° = direkt nach oben (Z+), "
                     "90° = horizontal vorwärts, 180° = nach unten, "
                     "270° = horizontal rückwärts. Feinkorrektur: "
                     "calibration-Block.",
    "azimuth_deg": "Plattform-Drehung um die Stehachse (Z), relativ zur "
                   "Position beim Scan-Start (kein Homing). Mit "
                   "invert_dir=true (Default seit 2026-07-04) ist das "
                   "Koordinatensystem realitätstreu (rechtshändig); Scans "
                   "mit invert_dir=false sind spiegelverkehrt.",
    "to_cartesian": "r=dist/1000; z=r*cos(el); h=r*sin(el); "
                    "x=h*sin(az); y=h*cos(az)  (rechtshändig, X=rechts, "
                    "Y=vorne bei az=0, Z=oben; Ursprung = Schnittpunkt "
                    "Drehachse/Scanebene). Präzise mit Strahlmodell aus "
                    "dem calibration-Block rechnen!",
    "unfiltered": "Rohdaten sind UNGEFILTERT: Stativ-Bereich, Nahbereich "
                  "und Ausreißer sind enthalten — Filterung ist Sache der "
                  "PC-Auswertung.",
}


def build_meta(config_dict: dict, mode: str) -> dict:
    """Grundgerüst der meta.json zu Scan-Beginn (Zeitanker!)."""
    from ..lidar import calibration

    calib = calibration.load_calibration()
    calib["model"] = calibration.MODEL_RECIPE
    return {
        "schema_version": 1,
        "software": {
            "name": "scanorama",
            "version": __version__,
            "git_commit": _git_commit(),
        },
        "host": {"hostname": socket.gethostname()},
        "time_anchor": {
            # Wandzeit und Monotonic-Zeit im selben Moment — damit lassen
            # sich alle t_ns-Werte (monotonic) in Wandzeit umrechnen.
            "wall_iso": datetime.now().astimezone().isoformat(),
            "wall_ns": time.time_ns(),
            "monotonic_ns": time.monotonic_ns(),
        },
        "mode": mode,
        "config": config_dict,
        "geometry": GEOMETRY_CONVENTION,
        "calibration": calib,
        "files": {
            "lidar_raw": "lidar_raw.bin",
            "lidar_index": "lidar_index.npz",
            "motor_timeline": TIMELINE_NAME,
            "points": POINTS_NAME,
            "log": LOG_NAME,
        },
    }


def write_meta(scan_dir: Path, meta: dict) -> None:
    with open(scan_dir / META_NAME, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)


def read_meta(scan_dir: Path) -> dict:
    with open(scan_dir / META_NAME, encoding="utf-8") as f:
        return json.load(f)

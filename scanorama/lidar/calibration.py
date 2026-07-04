"""LiDAR-Gerätekalibrierung: Strahlgeometrie des STL27L im Aufbau.

Der reale Laserstrahl weicht von der idealen Vertikalebene ab. Vier
Winkel (in Grad) beschreiben die Abweichung — bestimmt per
Zwei-Lagen-Analyse eines 360°-Scans (jede Weltrichtung wird von der
vorderen UND hinteren Halbebene gemessen, wie die Zwei-Lagen-Messung
beim Theodolit):

    el_offset_deg        Rotor-Nullpunkt: wahre Elevation = el + el_offset
    beam_skew_deg        Strahl zeigt konstant seitlich aus der
                         Rotorebene heraus (ω0)
    beam_wobble_deg      elevationsabhängiger Anteil des Seitwärtswinkels:
                         ω(el) = ω0 + ω1·cos(el)   (ω1; äquivalent zu
                         einer Kippung der Rotorachse)
    halfplane_split_deg  konstanter Azimut-Versatz zwischen den beiden
                         Halbebenen: el>180° wird um +split/2, el≤180°
                         um −split/2 um die Stehachse gedreht

Vollständiges Strahlmodell (Plattform-Frame: ŷ=vorn, x̂=rechts, ẑ=oben;
Welt = Drehung um ẑ mit az; x=h·sin(az)-Konvention wie geometry-Block):

    el' = el + el_offset
    ω   = beam_skew + beam_wobble·cos(el)
    d_p = cos ω·(cos el'·ẑ + sin el'·ŷ) + sin ω·x̂
    d_p um ±halfplane_split/2 um ẑ gedreht (+ für el>180°)
    Punkt = r · R_z(az) · d_p

Die Werte werden am PC bestimmt (``scanorama-studio-cli calibrate``)
und auf dem Pi in ``~/.config/scanorama/calibration.json`` hinterlegt;
jeder Scan trägt sie dann in seiner meta.json (Block ``calibration``),
sodass die PC-Auswertung sie automatisch anwendet.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

CONFIG_PATH = Path.home() / ".config" / "scanorama" / "calibration.json"

DEFAULT_CALIBRATION: dict = {
    "el_offset_deg": 0.0,
    "beam_skew_deg": 0.0,
    "beam_wobble_deg": 0.0,
    "halfplane_split_deg": 0.0,
}

MODEL_RECIPE = (
    "el'=el+el_offset_deg; omega=beam_skew_deg+beam_wobble_deg*cos(el); "
    "d=cos(omega)*(cos(el')*z + sin(el')*y) + sin(omega)*x; "
    "d um +halfplane_split_deg/2 (el>180) bzw. -halfplane_split_deg/2 "
    "(el<=180) um z gedreht; Punkt = r * R_z(az) * d — Achsen/Konvention "
    "siehe geometry-Block"
)


def load_calibration(config_path: Path | None = None) -> dict:
    """Lädt die Gerätekalibrierung (Defaults + calibration.json).

    Unbekannte Zusatzfelder der Datei (z.B. ``fitted``, ``source``)
    werden durchgereicht — sie dokumentieren die Herkunft der Werte.
    """
    path = config_path if config_path is not None else CONFIG_PATH
    calib = dict(DEFAULT_CALIBRATION)
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            log.warning(f"{path} unlesbar ({e}) — nutze Null-Kalibrierung")
            return calib
        bad = [k for k, v in data.items()
               if k in DEFAULT_CALIBRATION and not isinstance(v, (int, float))]
        for k in bad:
            log.warning(f"{path}: '{k}' ist keine Zahl — ignoriert")
            data.pop(k)
        calib.update(data)
        log.info(f"LiDAR-Kalibrierung geladen: {path} "
                 f"(skew {calib['beam_skew_deg']:+.3f}° "
                 f"wobble {calib['beam_wobble_deg']:+.3f}° "
                 f"split {calib['halfplane_split_deg']:+.3f}° "
                 f"el_off {calib['el_offset_deg']:+.3f}°)")
    return calib

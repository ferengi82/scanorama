"""Stepper-Basisklasse mit Bewegungs-Zeitleiste.

Die Zeitleiste ist das Herzstück der Rohdaten-Aufzeichnung: Jedes
Bewegungs-Ereignis wird mit ``time.monotonic_ns()`` und der Azimut-
Position am Abtrieb (Drehteller, in Grad) protokolliert. Da der Motor
zwischen den Ereignissen mit konstanter Geschwindigkeit fährt, ergibt
lineare Interpolation zwischen den Ereignissen die exakte Funktion
Azimut(t) — genau das, was die Offline-Dekodierung braucht, um jedem
LiDAR-Punkt seinen Azimut zuzuordnen.

Konvention: Azimut ist die Plattform-Drehung relativ zur Position beim
Programmstart (kein Homing in v1 — der Scanner startet bei 0°).
"""

from __future__ import annotations

import csv
import logging
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)


class Timeline:
    """Protokolliert (t_ns, event, azimut_deg) für die Offline-Auswertung."""

    def __init__(self):
        self.events: list[tuple[int, str, float]] = []
        self._lock = threading.Lock()

    def record(self, event: str, azimuth_deg: float, t_ns: int | None = None) -> None:
        with self._lock:
            self.events.append(
                (t_ns if t_ns is not None else time.monotonic_ns(),
                 event, azimuth_deg)
            )

    def save_csv(self, path: Path) -> None:
        """Schreibt die Zeitleiste als CSV (t_ns, event, azimuth_deg)."""
        with self._lock:
            rows = list(self.events)
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["t_ns", "event", "azimuth_deg"])
            for t_ns, event, az in rows:
                w.writerow([t_ns, event, f"{az:.6f}"])


class StepperBase:
    """Gemeinsame Logik aller Stepper-Treiber (Bewegung + Zeitleiste).

    Unterklassen implementieren die Hardware-Hooks ``_set_direction()``
    und ``_pulse()``; die Schritt-Mathematik (Steps pro Grad, Timing,
    Hintergrund-Thread für kontinuierliche Fahrt) lebt hier.
    """

    def __init__(self, steps_per_deg: float, invert_dir: bool = False):
        self.steps_per_deg = steps_per_deg
        self.invert_dir = invert_dir
        self.current_deg = 0.0
        self.timeline = Timeline()
        self.timeline.record("init", 0.0)

    # --- Hardware-Hooks (Unterklassen) ---------------------------------
    def _set_direction(self, forward: bool) -> None:
        raise NotImplementedError

    def _pulse(self, half_delay_s: float) -> None:
        """Ein STEP-Puls (HIGH-halb-LOW-halb)."""
        raise NotImplementedError

    # --- Bewegung --------------------------------------------------------
    def move_degrees(self, degrees: float, speed_deg_s: float = 10.0) -> None:
        """Blockierende Bewegung um ``degrees`` (am Abtrieb) mit ``speed_deg_s``."""
        steps = int(round(abs(degrees) * self.steps_per_deg))
        if steps == 0:
            return
        actual_deg = steps / self.steps_per_deg * (1 if degrees >= 0 else -1)
        forward = degrees >= 0
        if self.invert_dir:
            forward = not forward
        self._set_direction(forward)

        step_delay = 1.0 / (speed_deg_s * self.steps_per_deg)
        self.timeline.record("move_start", self.current_deg)
        half = step_delay / 2
        deg_per_step = actual_deg / steps
        for _ in range(steps):
            self._pulse(half)
            self.current_deg += deg_per_step
        self.timeline.record("move_end", self.current_deg)

    def start_continuous(self, total_deg: float, speed_deg_s: float) -> threading.Event:
        """Kontinuierliche Fahrt im Hintergrund-Thread.

        ``current_deg`` wird nach jedem Microstep aktualisiert; die
        Zeitleiste bekommt seg_start/seg_end. Rückgabe: Event, das bei
        Abschluss gesetzt wird.
        """
        done = threading.Event()
        total_steps = int(round(abs(total_deg) * self.steps_per_deg))
        if total_steps == 0:
            done.set()
            return done

        deg_per_step = total_deg / total_steps
        step_delay = 1.0 / (speed_deg_s * self.steps_per_deg)
        forward = total_deg >= 0
        if self.invert_dir:
            forward = not forward

        def _run():
            self._set_direction(forward)
            self.timeline.record("seg_start", self.current_deg)
            half = step_delay / 2
            for _ in range(total_steps):
                self._pulse(half)
                self.current_deg += deg_per_step
            self.timeline.record("seg_end", self.current_deg)
            done.set()

        threading.Thread(target=_run, daemon=True, name="stepper-continuous").start()
        log.info(f"Stepper: kontinuierlich {total_deg:+.1f}° @ {speed_deg_s:.2f}°/s "
                 f"({total_steps} Steps, ~{abs(total_deg)/speed_deg_s:.0f}s)")
        return done

    # --- Verwaltung -------------------------------------------------------
    def disable(self) -> None:
        """Motor stromlos schalten (falls EN-Pin vorhanden)."""

    def cleanup(self) -> None:
        """GPIO/UART freigeben."""

    def describe(self) -> dict:
        """Treiber-Info für meta.json."""
        return {
            "driver": type(self).__name__,
            "steps_per_deg": self.steps_per_deg,
            "invert_dir": self.invert_dir,
        }

"""Mock-Stepper für Tests ohne Hardware.

Simuliert die Bewegung zeitbasiert (mit optionalem ``time_scale``,
damit Tests nicht real warten). Zeitleiste und ``current_deg``
verhalten sich wie bei den echten Treibern.
"""

from __future__ import annotations

import threading
import time

from .base import StepperBase


class MockStepper(StepperBase):
    """Simulierter Stepper — keine GPIO-Zugriffe.

    Args:
        steps_per_deg: wie beim echten Treiber (Default: TMC2209-Setup)
        time_scale: >1 = Bewegung läuft schneller als Echtzeit
    """

    def __init__(self, steps_per_deg: float = 106.67, invert_dir: bool = False,
                 time_scale: float = 1.0):
        super().__init__(steps_per_deg=steps_per_deg, invert_dir=invert_dir)
        self.time_scale = time_scale
        self.disabled = False

    def _set_direction(self, forward: bool) -> None:
        pass

    def _pulse(self, half_delay_s: float) -> None:
        time.sleep(2 * half_delay_s / self.time_scale)

    def move_degrees(self, degrees: float, speed_deg_s: float = 10.0) -> None:
        # Statt Einzelpulsen: eine skalierte Wartezeit, Timeline wie echt.
        self.timeline.record("move_start", self.current_deg)
        time.sleep(abs(degrees) / speed_deg_s / self.time_scale)
        self.current_deg += degrees
        self.timeline.record("move_end", self.current_deg)

    def start_continuous(self, total_deg: float, speed_deg_s: float) -> threading.Event:
        done = threading.Event()
        duration = abs(total_deg) / speed_deg_s / self.time_scale
        start_deg = self.current_deg
        t0 = time.monotonic()

        def _run():
            self.timeline.record("seg_start", start_deg)
            while True:
                elapsed = (time.monotonic() - t0) * self.time_scale
                deg = elapsed * speed_deg_s
                if deg >= abs(total_deg):
                    break
                self.current_deg = start_deg + deg * (1 if total_deg >= 0 else -1)
                time.sleep(0.001)
            self.current_deg = start_deg + total_deg
            self.timeline.record("seg_end", self.current_deg)
            done.set()

        threading.Thread(target=_run, daemon=True, name="mock-stepper").start()
        return done

    def disable(self) -> None:
        self.disabled = True

"""Adafruit STSPIN220 — GPIO-only Stepper-Treiber (Fallback).

STEP/DIR/EN per RPi.GPIO, festes 1/16-Microstepping (MS-Pins offen),
Strombegrenzung per Poti auf dem Board. Motorspannung VIN max 10 V!
"""

from __future__ import annotations

import logging
import time

from ..config import MotorConfig
from .base import StepperBase

log = logging.getLogger(__name__)

STSPIN220_MICROSTEPS = 16  # fest verdrahtet (MS-Pins offen)


class Stspin220Stepper(StepperBase):
    """STEP/DIR-Steuerung des STSPIN220 per RPi.GPIO."""

    def __init__(self, cfg: MotorConfig):
        # STSPIN220 kann Microstepping nicht per Software — immer 1/16.
        steps_per_deg = (cfg.steps_per_rev * STSPIN220_MICROSTEPS * cfg.gear_ratio) / 360.0
        super().__init__(steps_per_deg=steps_per_deg, invert_dir=cfg.invert_dir)
        self.cfg = cfg

        import RPi.GPIO as GPIO
        self.GPIO = GPIO
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(cfg.pin_step, GPIO.OUT, initial=GPIO.LOW)
        GPIO.setup(cfg.pin_dir, GPIO.OUT, initial=GPIO.LOW)
        # EN/FAULT ist active-low → LOW = Motor bestromt
        GPIO.setup(cfg.pin_en, GPIO.OUT, initial=GPIO.LOW)
        log.info(f"STSPIN220 initialisiert (STEP={cfg.pin_step} DIR={cfg.pin_dir} "
                 f"EN={cfg.pin_en}, 1/16 Microsteps, {steps_per_deg:.2f} Steps/°)")

    def _set_direction(self, forward: bool) -> None:
        self.GPIO.output(self.cfg.pin_dir,
                         self.GPIO.HIGH if forward else self.GPIO.LOW)
        time.sleep(0.000005)  # DIR-Setup-Zeit (min. 1 µs laut Datenblatt)

    def _pulse(self, half_delay_s: float) -> None:
        self.GPIO.output(self.cfg.pin_step, self.GPIO.HIGH)
        time.sleep(half_delay_s)
        self.GPIO.output(self.cfg.pin_step, self.GPIO.LOW)
        time.sleep(half_delay_s)

    def disable(self) -> None:
        # active-low → HIGH = stromlos
        self.GPIO.output(self.cfg.pin_en, self.GPIO.HIGH)

    def cleanup(self) -> None:
        try:
            self.GPIO.cleanup()
        except Exception:
            pass

    def describe(self) -> dict:
        d = super().describe()
        d.update({
            "microsteps": STSPIN220_MICROSTEPS,
            "gear_ratio": self.cfg.gear_ratio,
            "pins": {"step": self.cfg.pin_step, "dir": self.cfg.pin_dir,
                     "en": self.cfg.pin_en},
        })
        return d

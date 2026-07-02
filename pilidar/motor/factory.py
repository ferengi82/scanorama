"""Treiber-Auswahl anhand der Konfiguration."""

from __future__ import annotations

from ..config import MotorConfig
from .base import StepperBase


def create_stepper(cfg: MotorConfig) -> StepperBase:
    """Erzeugt den passenden Stepper-Treiber (tmc2209 | stspin220 | mock)."""
    if cfg.driver == "tmc2209":
        from .tmc2209 import Tmc2209Stepper
        return Tmc2209Stepper(cfg)
    if cfg.driver == "stspin220":
        from .stspin220 import Stspin220Stepper
        return Stspin220Stepper(cfg)
    if cfg.driver == "mock":
        from .mock import MockStepper
        steps_per_deg = (cfg.steps_per_rev * cfg.microsteps * cfg.gear_ratio) / 360.0
        return MockStepper(steps_per_deg=steps_per_deg, invert_dir=cfg.invert_dir,
                           time_scale=60.0)
    raise ValueError(f"Unbekannter Treiber: {cfg.driver!r} "
                     f"(erwartet: tmc2209, stspin220, mock)")

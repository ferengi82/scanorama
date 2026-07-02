"""TMC2209 — Default-Treiber: STEP/DIR per GPIO + Konfiguration per UART.

Bewegung identisch zum STSPIN220 (STEP/DIR-Pulse), zusätzlich setzt
UART: Microstepping (MRES), Chopper-Modus (StealthChop/SpreadCycle)
und Stromskalierung. Verdrahtung: Pi TX → 1kΩ → PDN_UART, PDN_UART →
Pi RX direkt. Pi-UART muss aktiviert sein (raspi-config → Serial →
Login-Shell aus, Hardware-UART an).
"""

from __future__ import annotations

import logging

from ..config import MotorConfig
from .stspin220 import Stspin220Stepper

log = logging.getLogger(__name__)


class Tmc2209Stepper(Stspin220Stepper):
    """STEP/DIR wie STSPIN220, plus UART-Konfiguration beim Start."""

    # MRES-Wert in CHOPCONF Bits 27..24 pro Microstepping-Auflösung
    _MRES_MAP = {256: 0, 128: 1, 64: 2, 32: 3, 16: 4, 8: 5, 4: 6, 2: 7, 1: 8}

    def __init__(self, cfg: MotorConfig):
        # GPIO-Setup über Elternklasse, aber Steps/° mit dem per UART
        # konfigurierten Microstepping neu rechnen.
        super().__init__(cfg)
        self.steps_per_deg = (cfg.steps_per_rev * cfg.microsteps * cfg.gear_ratio) / 360.0
        self.uart_ok = False

        from .tmc2209_uart import TMC2209UART
        self.tmc = TMC2209UART(port=cfg.uart_port)
        if self.tmc.test_connection():
            self._configure(cfg)
            self.uart_ok = True
        else:
            log.warning("TMC2209 UART-Kommunikation fehlgeschlagen — Motor läuft "
                        "mit Chip-Defaults (STEP/DIR ohne UART-Konfiguration). "
                        "ACHTUNG: Microstepping entspricht dann NICHT der Annahme!")

    def _configure(self, cfg: MotorConfig) -> None:
        """Register setzen: GCONF, CHOPCONF (MRES), IHOLD_IRUN, VACTUAL=0."""
        from .tmc2209_uart import (REG_GCONF, REG_CHOPCONF, REG_IHOLD_IRUN,
                                   REG_VACTUAL, REG_TPWMTHRS,
                                   GCONF_I_SCALE_ANALOG, GCONF_PDN_DISABLE,
                                   GCONF_MSTEP_REG_SELECT,
                                   GCONF_EN_SPREADCYCLE,
                                   GCONF_MULTISTEP_FILT, CHOPCONF_DEFAULT)

        # GCONF: VREF-Poti als Stromreferenz (Adafruit-Board!), UART-Modus,
        # MRES per Register, Pulsfilter. Drehrichtung machen wir per GPIO
        # (DIR-Pin), nicht per SHAFT-Bit — eine Quelle der Wahrheit.
        gconf = (GCONF_I_SCALE_ANALOG | GCONF_PDN_DISABLE |
                 GCONF_MSTEP_REG_SELECT | GCONF_MULTISTEP_FILT)
        if not cfg.stealthchop:
            gconf |= GCONF_EN_SPREADCYCLE
        self.tmc.write_reg(REG_GCONF, gconf)

        # CHOPCONF: MRES-Bits (27..24) + Interpolation auf 256 µSteps (Bit 28)
        chopconf = self.tmc.read_reg(REG_CHOPCONF)
        if chopconf is None:
            chopconf = CHOPCONF_DEFAULT
        mres = self._MRES_MAP.get(cfg.microsteps, 4)
        chopconf = (chopconf & ~(0xF << 24)) | (mres << 24)
        chopconf |= (1 << 28)
        self.tmc.write_reg(REG_CHOPCONF, chopconf)

        # IHOLD_IRUN: Bei I_scale_analog=1 skaliert IRUN relativ zum Poti.
        # IRUN=31 = voller Poti-Strom, IHOLD=16 ≈ 50 % Haltestrom.
        ihold_irun = 16 | (31 << 8) | (6 << 16)
        self.tmc.write_reg(REG_IHOLD_IRUN, ihold_irun)

        # VACTUAL=0: STEP/DIR-Modus (kein interner Pulsgenerator)
        self.tmc.write_reg(REG_VACTUAL, 0)

        if cfg.stealthchop:
            self.tmc.write_reg(REG_TPWMTHRS, 0)  # 0 = immer StealthChop

        chopper = "StealthChop" if cfg.stealthchop else "SpreadCycle"
        log.info(f"TMC2209 konfiguriert: 1/{cfg.microsteps} Microsteps, {chopper}, "
                 f"{self.steps_per_deg:.2f} Steps/° (Strom per Poti am Board)")

        status = self.tmc.read_drv_status()
        if "error" not in status:
            log.info(f"TMC2209 Status: CS_actual={status['cs_actual']}, "
                     f"stst={status['stst']}, stealth={status['stealth']}")
            if status.get("ot") or status.get("otpw"):
                log.warning("TMC2209 Übertemperatur-Warnung!")

    def cleanup(self) -> None:
        if hasattr(self, "tmc"):
            self.tmc.close()
        super().cleanup()

    def describe(self) -> dict:
        d = super().describe()
        d.update({
            "microsteps": self.cfg.microsteps,
            "uart_port": self.cfg.uart_port,
            "uart_ok": self.uart_ok,
            "stealthchop": self.cfg.stealthchop,
        })
        return d

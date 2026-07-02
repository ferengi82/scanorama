#!/usr/bin/env python3
"""
TMC2209 UART-Kommunikation — Low-Level Registerzugriff per pyserial.

Single-Wire-Protokoll: Pi TX → 1kΩ → PDN_UART, PDN_UART → Pi RX.
Der TMC2209 erkennt die Baudrate automatisch am Sync-Nibble.

Datagramm-Format (Write): [0x05, addr, 0x80|reg, d3, d2, d1, d0, CRC]
Datagramm-Format (Read):  [0x05, addr, reg, CRC] → Antwort 8 Bytes

CRC: CRC8-ATM (x^8 + x^2 + x + 1), LSB-first, Initial=0.

Referenz: TMC2209 Datasheet Rev 1.09, Kapitel 4 (UART Single Wire Interface).
"""

import logging
import time
from typing import Optional

import serial

log = logging.getLogger("tmc2209")

# ---------------------------------------------------------------------------
# Register-Adressen
# ---------------------------------------------------------------------------
REG_GCONF       = 0x00
REG_GSTAT       = 0x01
REG_IFCNT       = 0x02
REG_NODECONF    = 0x03
REG_IOIN        = 0x06
REG_IHOLD_IRUN  = 0x10
REG_TPOWERDOWN  = 0x11
REG_TSTEP       = 0x12
REG_TPWMTHRS    = 0x13
REG_VACTUAL     = 0x22
REG_TCOOLTHRS   = 0x14
REG_SGTHRS      = 0x40
REG_SG_RESULT   = 0x41
REG_COOLCONF    = 0x42
REG_MSCNT       = 0x6A
REG_CHOPCONF    = 0x6C
REG_DRV_STATUS  = 0x6F
REG_PWMCONF     = 0x70

# GCONF-Bits
GCONF_I_SCALE_ANALOG   = 1 << 0
GCONF_INTERNAL_RSENSE  = 1 << 1
GCONF_EN_SPREADCYCLE   = 1 << 2
GCONF_SHAFT            = 1 << 3
GCONF_INDEX_OTPW       = 1 << 4
GCONF_INDEX_STEP       = 1 << 5
GCONF_PDN_DISABLE      = 1 << 6
GCONF_MSTEP_REG_SELECT = 1 << 7
GCONF_MULTISTEP_FILT   = 1 << 8

# CHOPCONF Reset-Default
CHOPCONF_DEFAULT = 0x10000053

# Sync-Byte (obere 4 Bit = Sync-Nibble 0101)
SYNC_BYTE = 0x05

# Master-Adresse für Read-Replies
MASTER_ADDR = 0xFF


class TMC2209UART:
    """Niedrigste UART-Schicht zum TMC2209 — Registerzugriff per pyserial.

    Verwendung:
        tmc = TMC2209UART("/dev/ttyAMA0")
        tmc.write_reg(REG_GCONF, GCONF_PDN_DISABLE | GCONF_MSTEP_REG_SELECT)
        status = tmc.read_reg(REG_DRV_STATUS)
        tmc.close()
    """

    def __init__(self, port: str = "/dev/ttyAMA0", baudrate: int = 115200,
                 node_addr: int = 0):
        """UART-Verbindung zum TMC2209 öffnen.

        Args:
            port: Serieller Port (z.B. /dev/ttyAMA0 oder /dev/ttyAMA0)
            baudrate: Baudrate (9600–500000, TMC2209 erkennt automatisch)
            node_addr: Knotenadresse 0–3 (MS1/MS2 Pins am TMC2209)
        """
        self.node_addr = node_addr & 0x03
        self.ser = serial.Serial(
            port=port,
            baudrate=baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.1,      # 100ms Read-Timeout
            write_timeout=0.1,
        )
        # Eingangspuffer leeren (evtl. Altdaten)
        self.ser.reset_input_buffer()
        log.debug(f"TMC2209 UART geöffnet: {port} @ {baudrate} Baud, Adresse {node_addr}")

    # ------------------------------------------------------------------
    # CRC8-ATM
    # ------------------------------------------------------------------
    @staticmethod
    def _crc8(data: bytes) -> int:
        """CRC8-ATM: Polynom x^8 + x^2 + x + 1, LSB-first, Initial=0.

        Verarbeitet jedes Byte LSB-first durch das Polynom 0x07.
        Identisch mit dem C-Code-Beispiel im TMC2209-Datenblatt (Kap. 4.2).
        """
        crc = 0
        for byte in data:
            for _ in range(8):
                if (crc >> 7) ^ (byte & 0x01):
                    crc = ((crc << 1) ^ 0x07) & 0xFF
                else:
                    crc = (crc << 1) & 0xFF
                byte >>= 1
        return crc

    # ------------------------------------------------------------------
    # Write-Zugriff
    # ------------------------------------------------------------------
    def write_reg(self, reg: int, value: int, verify: bool = True) -> bool:
        """32-Bit-Wert in TMC2209-Register schreiben.

        Baut ein 8-Byte Write-Datagramm auf, sendet es, liest das
        Single-Wire-Echo zurück und prüft optional via IFCNT ob der
        Schreibzugriff angekommen ist.

        Args:
            reg: Register-Adresse (0x00–0x7F)
            value: 32-Bit-Wert
            verify: IFCNT vor/nach Schreiben prüfen (Default: True)

        Returns:
            True wenn erfolgreich (oder verify=False), False bei Fehler
        """
        # IFCNT vorher lesen (für Verifikation)
        ifcnt_before = None
        if verify and reg != REG_IFCNT:
            ifcnt_before = self._read_reg_raw(REG_IFCNT)

        # Datagramm aufbauen: [sync, addr, reg|0x80, d3, d2, d1, d0, crc]
        value = value & 0xFFFFFFFF
        datagram = bytearray([
            SYNC_BYTE,
            self.node_addr,
            (reg & 0x7F) | 0x80,   # Bit 7 = Write
            (value >> 24) & 0xFF,
            (value >> 16) & 0xFF,
            (value >> 8) & 0xFF,
            value & 0xFF,
            0x00,                   # Platzhalter CRC
        ])
        datagram[7] = self._crc8(bytes(datagram[:7]))

        # Senden
        self.ser.reset_input_buffer()
        self.ser.write(datagram)
        self.ser.flush()

        # Single-Wire-Echo lesen und verwerfen (wir sehen unsere eigenen TX-Bytes)
        time.sleep(0.001)  # Kurze Pause für Echo
        echo = self.ser.read(8)
        if len(echo) != 8:
            log.warning(f"TMC2209 Write Echo unvollständig: {len(echo)}/8 Bytes "
                        f"(Register 0x{reg:02X})")

        # IFCNT prüfen
        if verify and ifcnt_before is not None and reg != REG_IFCNT:
            time.sleep(0.001)
            ifcnt_after = self._read_reg_raw(REG_IFCNT)
            if ifcnt_after is None:
                log.warning(f"TMC2209 IFCNT nicht lesbar nach Write auf 0x{reg:02X}")
                return False
            expected = (ifcnt_before + 1) & 0xFF
            if (ifcnt_after & 0xFF) != expected:
                log.warning(f"TMC2209 IFCNT nicht inkrementiert: "
                            f"{ifcnt_before} → {ifcnt_after & 0xFF} (erwartet {expected}), "
                            f"Register 0x{reg:02X}")
                return False

        log.debug(f"TMC2209 Write 0x{reg:02X} = 0x{value:08X}")
        return True

    # ------------------------------------------------------------------
    # Read-Zugriff
    # ------------------------------------------------------------------
    def _read_reg_raw(self, reg: int) -> Optional[int]:
        """Register lesen ohne Logging (intern für IFCNT-Prüfung)."""
        # Read-Request: [sync, addr, reg, crc] = 4 Bytes
        request = bytearray([
            SYNC_BYTE,
            self.node_addr,
            reg & 0x7F,   # Bit 7 = 0 → Read
            0x00,
        ])
        request[3] = self._crc8(bytes(request[:3]))

        self.ser.reset_input_buffer()
        self.ser.write(request)
        self.ser.flush()

        # Echo der eigenen 4 TX-Bytes lesen + verwerfen
        time.sleep(0.001)
        echo = self.ser.read(4)

        # Antwort: [sync, master_addr(0xFF), reg, d3, d2, d1, d0, crc] = 8 Bytes
        reply = self.ser.read(8)
        if len(reply) != 8:
            return None

        # CRC der Antwort prüfen
        crc_calc = self._crc8(bytes(reply[:7]))
        if crc_calc != reply[7]:
            return None

        # 32-Bit-Wert extrahieren (MSB first)
        value = (reply[3] << 24) | (reply[4] << 16) | (reply[5] << 8) | reply[6]
        return value

    def read_reg(self, reg: int) -> Optional[int]:
        """32-Bit-Wert aus TMC2209-Register lesen.

        Args:
            reg: Register-Adresse (0x00–0x7F)

        Returns:
            32-Bit-Wert oder None bei Kommunikationsfehler
        """
        value = self._read_reg_raw(reg)
        if value is None:
            log.warning(f"TMC2209 Read 0x{reg:02X} fehlgeschlagen (keine Antwort/CRC-Fehler)")
        else:
            log.debug(f"TMC2209 Read 0x{reg:02X} = 0x{value:08X}")
        return value

    # ------------------------------------------------------------------
    # Diagnose-Helfer
    # ------------------------------------------------------------------
    def read_drv_status(self) -> dict:
        """DRV_STATUS-Register lesen und aufschlüsseln.

        Returns:
            Dict mit Status-Flags, oder {"error": "..."} bei Lesefehler
        """
        val = self.read_reg(REG_DRV_STATUS)
        if val is None:
            return {"error": "Keine Antwort vom TMC2209"}
        return {
            "stst":       bool(val & (1 << 31)),   # Stillstand erkannt
            "stealth":    bool(val & (1 << 30)),   # StealthChop aktiv
            "cs_actual":  (val >> 16) & 0x1F,      # Tatsächlicher Strom (0–31)
            "t157":       bool(val & (1 << 11)),   # Temperatur > 157°C
            "t150":       bool(val & (1 << 10)),   # Temperatur > 150°C
            "t143":       bool(val & (1 << 9)),    # Temperatur > 143°C
            "t120":       bool(val & (1 << 8)),    # Temperatur > 120°C
            "olb":        bool(val & (1 << 7)),    # Offene Last Phase B
            "ola":        bool(val & (1 << 6)),    # Offene Last Phase A
            "s2vsb":      bool(val & (1 << 5)),    # Low-Side Kurzschluss Phase B
            "s2vsa":      bool(val & (1 << 4)),    # Low-Side Kurzschluss Phase A
            "s2gb":       bool(val & (1 << 3)),    # Kurzschluss nach GND Phase B
            "s2ga":       bool(val & (1 << 2)),    # Kurzschluss nach GND Phase A
            "ot":         bool(val & (1 << 1)),    # Übertemperatur-Abschaltung
            "otpw":       bool(val & (1 << 0)),    # Übertemperatur-Warnung
        }

    def read_version(self) -> Optional[int]:
        """IC-Version aus IOIN-Register lesen (Bits 31..24).

        TMC2209 sollte 0x21 zurückgeben.
        """
        val = self.read_reg(REG_IOIN)
        if val is None:
            return None
        return (val >> 24) & 0xFF

    def test_connection(self) -> bool:
        """Verbindung testen: IC-Version lesen und prüfen.

        Returns:
            True wenn TMC2209 antwortet und Version 0x21 meldet
        """
        version = self.read_version()
        if version is None:
            log.error("TMC2209 UART antwortet nicht — Verkabelung prüfen!")
            log.error("  Erwartete Verdrahtung: Pi TX → 1kΩ → PDN_UART, "
                      "PDN_UART → Pi RX")
            return False
        if version != 0x21:
            log.warning(f"TMC2209 unerwartete IC-Version: 0x{version:02X} "
                        f"(erwartet 0x21)")
        else:
            log.info(f"TMC2209 erkannt (IC-Version 0x{version:02X})")
        return True

    # ------------------------------------------------------------------
    # Aufräumen
    # ------------------------------------------------------------------
    def close(self):
        """Seriellen Port schließen."""
        try:
            if self.ser and self.ser.is_open:
                self.ser.close()
                log.debug("TMC2209 UART geschlossen")
        except Exception:
            pass

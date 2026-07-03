"""Mock-LiDAR für Tests ohne Hardware.

Erfüllt das ByteSource-Interface aus ``reader.py`` und liefert einen
synthetischen STL27L-Bytestrom: Der virtuelle Rotor dreht mit
konstanter Frequenz, die Distanzen folgen einer einfachen Szene
(Funktion des Elevationswinkels), sodass Tests dekodierte Werte
gegen die Erwartung prüfen können.

Performance: Eine komplette Rotor-Umdrehung wird einmal vorberechnet
(Frame-Bau inkl. CRC ist in Python teuer) und dann zyklisch
wiederholt — der interne Frame-Timestamp bleibt dadurch konstant 0,
was für die Auswertung irrelevant ist (Host-Zeitstempel zählen).

Der Strom entsteht in Echtzeit (``in_waiting`` wächst mit der
verstrichenen Zeit), optional mit ``time_scale`` beschleunigt, damit
Tests nicht real warten müssen.
"""

from __future__ import annotations

import math
import time

from . import protocol


def scene_distance_mm(angle_deg: float) -> int:
    """Einfache deterministische Test-Szene: Distanz als Funktion des Winkels."""
    return int(2000 + 500 * math.sin(math.radians(angle_deg) * 2))


class MockLidarSource:
    """Simulierter STL27L als ByteSource.

    Args:
        rotor_hz: Rotordrehzahl (STL27L: ~10 Hz)
        time_scale: >1 = Datenstrom läuft schneller als Echtzeit (für Tests)
        corrupt_every: jedes n-te Frame bekommt ein kaputtes CRC-Byte
                       (0 = keine Fehler) — zum Testen der CRC-Statistik
    """

    def __init__(self, rotor_hz: float = 10.0, time_scale: float = 1.0,
                 corrupt_every: int = 0):
        self.rotor_hz = rotor_hz
        self.time_scale = time_scale
        self.corrupt_every = corrupt_every
        self._t0 = time.monotonic()
        self._generated_frames = 0
        self._pending = bytearray()
        # 12 Punkte pro Frame bei 21600 Punkten/s
        self._frames_per_s = 21600.0 / protocol.POINTS_PER_FRAME
        deg_per_frame = 360.0 * rotor_hz / self._frames_per_s

        # Eine volle Umdrehung vorberechnen (Frame-Bau ist teuer).
        self._rotation: list[bytes] = []
        n_frames = int(round(360.0 / deg_per_frame))
        for k in range(n_frames):
            start = (k * deg_per_frame) % 360.0
            end = (start + deg_per_frame) % 360.0
            step = deg_per_frame / (protocol.POINTS_PER_FRAME - 1)
            angles = [(start + step * i) % 360.0
                      for i in range(protocol.POINTS_PER_FRAME)]
            self._rotation.append(protocol.build_frame(
                start_angle_deg=start,
                end_angle_deg=end,
                distances_mm=[scene_distance_mm(a) for a in angles],
                intensities=[200] * protocol.POINTS_PER_FRAME,
                speed_deg_s=rotor_hz * 360.0,
                timestamp_ms=0,
            ))

    def _next_frame(self) -> bytes:
        frame = self._rotation[self._generated_frames % len(self._rotation)]
        if (self.corrupt_every
                and (self._generated_frames + 1) % self.corrupt_every == 0):
            b = bytearray(frame)
            b[-1] ^= 0xFF  # CRC kaputt machen
            frame = bytes(b)
        return frame

    def _generate_due(self) -> None:
        """Erzeugt alle Frames, die laut simulierter Zeit fällig sind."""
        elapsed = (time.monotonic() - self._t0) * self.time_scale
        due = int(elapsed * self._frames_per_s)
        while self._generated_frames < due:
            self._pending += self._next_frame()
            self._generated_frames += 1

    # --- ByteSource-Interface -------------------------------------------
    @property
    def in_waiting(self) -> int:
        self._generate_due()
        return len(self._pending)

    def read(self, size: int = 1) -> bytes:
        self._generate_due()
        if not self._pending:
            # Wie serial.Serial mit timeout: kurz warten, dann leer zurück
            time.sleep(0.001)
            self._generate_due()
        data = bytes(self._pending[:size])
        del self._pending[:size]
        return data

    def reset_input_buffer(self) -> None:
        self._pending.clear()

    def close(self) -> None:
        pass

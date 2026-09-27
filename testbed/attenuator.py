"""Programmable RF attenuator for range-vs-rate (RvR) runs.

DESIGNED, NOT RUN: written without the hardware. HttpAttenuator follows the HTTP control style
of Mini-Circuits RCDAT/RUDAT units (GET /SETATT=<dB> returns "1" on success, GET /ATT? returns the
current value); confirm against the unit's manual. In a conducted setup the attenuator sits on
the cable between AP and client inside shielded enclosures, so dB steps stand in for distance.
"""

from __future__ import annotations

import urllib.request
from dataclasses import dataclass


class AttenuatorError(RuntimeError):
    pass


@dataclass
class HttpAttenuator:
    base_url: str               # e.g. http://192.168.9.61
    max_db: float = 95.0
    timeout: float = 5.0

    def _get(self, path: str) -> str:
        with urllib.request.urlopen(f"{self.base_url.rstrip('/')}/{path}", timeout=self.timeout) as r:
            return r.read().decode().strip()

    def set(self, db: float) -> None:
        if not 0 <= db <= self.max_db:
            raise AttenuatorError(f"{db} dB outside 0..{self.max_db}")
        reply = self._get(f"SETATT={db:g}")
        if reply != "1":
            raise AttenuatorError(f"SETATT={db:g} answered {reply!r}")

    def get(self) -> float:
        return float(self._get("ATT?"))


def rvr_steps(start: float = 0, stop: float = 60, step: float = 5) -> list[float]:
    """Attenuation steps for one sweep, low to high (near to far)."""
    n = int((stop - start) / step)
    return [start + i * step for i in range(n + 1)]

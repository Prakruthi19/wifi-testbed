"""Loads lab/inventory.yaml: radios, APs, clients and the lab network plan."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from testbed import LAB_DIR


@dataclass(frozen=True)
class ClientRadio:
    name: str
    iface: str
    namespace: str


@dataclass(frozen=True)
class Inventory:
    raw: dict

    @property
    def lab(self) -> dict:
        return self.raw["lab"]

    @property
    def ap_iface(self) -> str:
        return self.raw["ap_radio"]["iface"]

    @property
    def clients(self) -> list[ClientRadio]:
        return [ClientRadio(c["name"], c["iface"], c["namespace"]) for c in self.raw["client_radios"]]

    def client(self, name: str) -> ClientRadio:
        return next(c for c in self.clients if c.name == name)

    @property
    def aps(self) -> list[dict]:
        return self.raw.get("aps", [])

    @property
    def vlans(self) -> list[dict]:
        return self.raw["vlans"]


def load(path: Path | None = None) -> Inventory:
    path = path or LAB_DIR / "inventory.yaml"
    return Inventory(yaml.safe_load(path.read_text()))

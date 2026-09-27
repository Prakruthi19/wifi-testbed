"""Module 1 test matrix: AP configurations, client profiles, compliance rules and expected results.

Expected results live here (and are copied into docs/test-plan.md) so they are written down
before anything runs. A case that passes when it is expected to fail is a bug.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from itertools import product

SECURITY_KEY_MGMT = {
    "open": None,
    "wpa2": "WPA-PSK",
    "wpa3": "SAE",
    "transition": "WPA-PSK SAE",
}
SECURITY_LABEL = {
    "open": "Open",
    "wpa2": "WPA2-PSK",
    "wpa3": "WPA3-SAE",
    "transition": "WPA2/WPA3",
}
PMF_LABEL = {0: "PMF disabled", 1: "PMF optional", 2: "PMF required"}
CHANNELS = {"g": [1, 6, 11], "a": [36, 44]}


def band_for_channel(channel: int) -> str:
    return "g" if channel <= 14 else "a"


@dataclass(frozen=True)
class ApConfig:
    security: str
    pmf: int
    channel: int
    ssid: str = "lab-matrix"
    passphrase: str = "labpassword123"

    @property
    def hw_mode(self) -> str:
        return band_for_channel(self.channel)

    @property
    def key_mgmt(self) -> str | None:
        return SECURITY_KEY_MGMT[self.security]

    @property
    def id(self) -> str:
        return f"{self.security}-pmf{self.pmf}-ch{self.channel}"

    @property
    def label(self) -> str:
        band = "2.4 GHz" if self.hw_mode == "g" else "5 GHz"
        return f"{SECURITY_LABEL[self.security]} / {PMF_LABEL[self.pmf]} / ch{self.channel} ({band})"

    def template_params(self) -> dict:
        return {
            "ssid": self.ssid,
            "hw_mode": self.hw_mode,
            "channel": self.channel,
            "key_mgmt": self.key_mgmt,
            "pmf": self.pmf,
            "passphrase": self.passphrase,
            "sae_password": None,
            "deny_macs": [],
        }


@dataclass(frozen=True)
class ClientProfile:
    """What a client supports. WPA2-only models a legacy client without PMF."""

    name: str
    key_mgmt: str
    ieee80211w: int

    def network_for(self, ap: ApConfig) -> dict:
        if ap.security == "open":
            return {"key_mgmt": "NONE", "ieee80211w": 0, "psk": None, "sae_password": None}
        return {
            "key_mgmt": self.key_mgmt,
            "ieee80211w": self.ieee80211w,
            "psk": ap.passphrase,
            "sae_password": None,
        }


CLIENT_PROFILES = {
    "wpa2-only": ClientProfile("wpa2-only", key_mgmt="WPA-PSK", ieee80211w=0),
    "wpa3-capable": ClientProfile("wpa3-capable", key_mgmt="WPA-PSK SAE", ieee80211w=1),
}


def compliance_violations(ap: ApConfig) -> list[str]:
    """WPA3-Personal rules (Wi-Fi Alliance WPA3 spec): flag configs a certified AP must not ship."""
    problems = []
    if ap.security == "wpa3" and ap.pmf != 2:
        problems.append("WPA3-Personal Only mode requires PMF required (MFPC=1, MFPR=1); "
                        f"got ieee80211w={ap.pmf}")
    if ap.security == "transition" and ap.pmf != 1:
        problems.append("WPA3-Personal Transition mode requires PMF capable, not required "
                        f"(MFPC=1, MFPR=0); got ieee80211w={ap.pmf}")
    if ap.security == "open" and ap.pmf != 0:
        problems.append("PMF has no effect on an Open network")
    return problems


@dataclass(frozen=True)
class Expectation:
    outcome: str  # "pass", "fail" or "noncompliant" (join result recorded but not asserted)
    stage: str | None = None
    reason: str = ""


def expected(ap: ApConfig, client: ClientProfile) -> Expectation:
    if compliance_violations(ap):
        return Expectation("noncompliant", reason="; ".join(compliance_violations(ap)))
    if ap.security == "open":
        return Expectation("pass", reason="Open network, no security negotiation")
    supports_sae = "SAE" in client.key_mgmt.split()
    supports_psk = "WPA-PSK" in client.key_mgmt.split()
    if ap.security == "wpa3" and not supports_sae:
        return Expectation("fail", "network_selection",
                           "WPA2-only client has no AKM in common with a WPA3-only AP")
    if ap.pmf == 2 and client.ieee80211w == 0:
        return Expectation("fail", "network_selection",
                           "AP requires PMF; client does not support it")
    if ap.security in ("wpa2", "transition") and not supports_psk and not supports_sae:
        return Expectation("fail", "network_selection", "no common AKM")
    return Expectation("pass", reason="compatible AKM and PMF settings")


@dataclass
class MatrixCase:
    ap: ApConfig
    client: ClientProfile
    expectation: Expectation = field(init=False)

    def __post_init__(self):
        self.expectation = expected(self.ap, self.client)

    @property
    def id(self) -> str:
        return f"{self.ap.id}__{self.client.name}"


def ap_configs(channels: list[int] | None = None) -> list[ApConfig]:
    channels = channels or CHANNELS["g"] + CHANNELS["a"]
    configs = []
    for security, channel in product(SECURITY_KEY_MGMT, channels):
        pmfs = [0] if security == "open" else [0, 1, 2]
        configs.extend(ApConfig(security, pmf, channel) for pmf in pmfs)
    return configs


def build_matrix(channels: list[int] | None = None) -> list[MatrixCase]:
    """AP config is the outer loop so each AP is started once for all its clients."""
    return [MatrixCase(ap, client) for ap in ap_configs(channels) for client in CLIENT_PROFILES.values()]


def markdown_table(channels: list[int] | None = None) -> str:
    """Expected results per security/PMF combo (channel does not change the expectation)."""
    rows = ["| AP config | " + " | ".join(CLIENT_PROFILES) + " | Notes |",
            "|---|" + "---|" * len(CLIENT_PROFILES) + "---|"]
    seen = set()
    for ap in ap_configs(channels or [6]):
        key = (ap.security, ap.pmf)
        if key in seen:
            continue
        seen.add(key)
        cells, notes = [], set()
        for client in CLIENT_PROFILES.values():
            exp = expected(ap, client)
            cells.append({"pass": "PASS", "noncompliant": "NON-COMPLIANT"}.get(
                exp.outcome, f"FAIL ({exp.stage})"))
            if exp.outcome != "pass":
                notes.add(exp.reason)
        label = f"{SECURITY_LABEL[ap.security]} / {PMF_LABEL[ap.pmf]}"
        rows.append(f"| {label} | " + " | ".join(cells) + f" | {'; '.join(sorted(notes))} |")
    return "\n".join(rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Print the Module 1 matrix")
    parser.add_argument("--markdown", action="store_true", help="expected-results table")
    args = parser.parse_args()
    if args.markdown:
        print(markdown_table())
    else:
        for case in build_matrix():
            exp = case.expectation
            print(f"{case.id:40s} {exp.outcome:12s} {exp.stage or '':12s} {exp.reason}")

"""802.1X (WPA2/WPA3-Enterprise) in the lab: users, a server certificate, client settings.

A real enterprise network has three parties: the client, the AP, and an authentication server
(RADIUS) that checks usernames and passwords. Here hostapd's built-in EAP server plays RADIUS, so
the login still happens over the air (EAP inside EAPOL frames) but no separate server is needed.

Methods used by the tests:
  PWD   password-only method, no certificates. Simplest to set up.
  PEAP  the common corporate one: a TLS tunnel to the server (the client checks the server's
        certificate), then MSCHAPv2 username/password inside the tunnel.
"""

from __future__ import annotations

from pathlib import Path

from testbed.util import run

METHODS = ("PWD", "PEAP")


def user_file_text(method: str, identity: str, password: str) -> str:
    """hostapd eap_user file allowing one user with one method.

    PEAP needs two lines: phase 1 (outer, which method to tunnel with) and phase 2 ([2], the
    password check inside the tunnel).
    """
    if method == "PWD":
        return f'"{identity}" PWD "{password}"\n'
    if method == "PEAP":
        return f'"{identity}" PEAP\n"{identity}" MSCHAPV2 "{password}" [2]\n'
    raise ValueError(f"unsupported EAP method {method}")


def write_user_file(path: Path, method: str, identity: str, password: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(user_file_text(method, identity, password))
    return path


def make_cert(workdir: Path, name: str = "radius", cn: str = "radius.lab") -> dict:
    """Self-signed certificate + key (valid 2 days). Used both as the server certificate and as
    the CA the client trusts. A second one with another name is an *untrusted* server."""
    workdir.mkdir(parents=True, exist_ok=True)
    cert, key = workdir / f"{name}.pem", workdir / f"{name}.key"
    if not (cert.exists() and key.exists()):
        run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2",
             "-subj", f"/CN={cn}", "-keyout", str(key), "-out", str(cert)])
    return {"cert": str(cert), "key": str(key)}


def client_settings(method: str, identity: str, password: str, ca_cert: str | None = None) -> dict:
    """The `eap` argument for WifiClient.associate (rendered into the network block)."""
    if method == "PWD":
        return {"method": "PWD", "identity": identity, "password": password}
    if method == "PEAP":
        return {"method": "PEAP", "identity": identity, "password": password,
                "phase2": "auth=MSCHAPV2", "ca_cert": ca_cert}
    raise ValueError(f"unsupported EAP method {method}")

"""Emulated Wi-Fi test bed: drivers for hostapd, wpa_supplicant, captures, lab networking and ADB."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIGS_DIR = REPO_ROOT / "configs"
LAB_DIR = REPO_ROOT / "lab"
REPORTS_DIR = REPO_ROOT / "reports"

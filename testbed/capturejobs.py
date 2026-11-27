"""Capture jobs for the web panel: record N seconds of frames on hwsim0 (or analyse an uploaded pcap),
then analyse the file. The browser starts a job and then polls GET /api/captures/{id} until it ends.

A job moves through:  capturing -> analysing -> done   (or failed, with the reason in `error`)
An uploaded file skips "capturing".

Each job runs in a background thread, so the HTTP request that starts it returns at once. Both steps
are separate programs (dumpcap for the capture, `python -m testbed.pcap_analysis` for the analysis),
so a crash or a hang in either one cannot take the API down, and both have a time limit.

Files: reports/captures/<id>.pcap and <id>.json (the job, with the analysis once it is done).
The newest KEEP captures are kept; older ones are deleted when a new one starts.

Frames on hwsim0 come from the emulated radios (mac80211_hwsim), not from real Wi-Fi hardware.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException

from testbed import REPO_ROOT

KEEP = 20
MAX_SECONDS = 300
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
ANALYSE_TIMEOUT_S = 300
PCAP_MAGIC = (b"\xd4\xc3\xb2\xa1", b"\xa1\xb2\xc3\xd4", b"\x4d\x3c\xb2\xa1", b"\xa1\xb2\x3c\x4d",
              b"\x0a\x0d\x0d\x0a")  # pcap (both byte orders, micro- and nanosecond) and pcapng


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def is_pcap(head: bytes) -> bool:
    return head[:4] in PCAP_MAGIC


class CaptureJobs:
    """At most one capture or analysis at a time: two dumpcaps on one interface would only duplicate work,
    and the analysis is the slow part, so a queue would just make people wait without knowing why."""

    def __init__(self, out_dir: Path, iface: str = "hwsim0",
                 capture_cmd=None, analyse_cmd=None, iface_exists=None):
        self.out_dir = out_dir
        self.iface = iface
        # Swappable so tests can run without dumpcap, tshark or a lab.
        self.capture_cmd = capture_cmd or (lambda iface, seconds, path: [
            "dumpcap", "-q", "-P", "-i", iface, "-a", f"duration:{seconds}", "-w", str(path)])
        self.analyse_cmd = analyse_cmd or (lambda pcap, out, wpa_pwd: [
            sys.executable, "-m", "testbed.pcap_analysis", str(pcap), "--out", str(out)]
            + (["--wpa-pwd", wpa_pwd] if wpa_pwd else []))
        self.iface_exists = iface_exists or (lambda name: Path("/sys/class/net", name).exists())
        self.jobs: dict[str, dict] = {}
        self.lock = threading.Lock()

    # -- starting ------------------------------------------------------------------------------

    def _new(self, source: str, **extra) -> dict:
        """Register a job, refusing if one is still going. Caller holds the lock."""
        if any(j["status"] in ("capturing", "analysing") for j in self.jobs.values()):
            raise HTTPException(409, "A capture is already running. Wait for it to finish.")
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._own(self.out_dir)
        job_id = uuid.uuid4().hex[:8]
        job = {"id": job_id, "source": source, "status": "capturing", "started": _now(), "finished": None,
               "error": None, "bytes": 0, "seconds": None, "iface": None, "filename": None, "decrypt": None,
               "result": None, "_t0": time.monotonic(), "_wpa": None}
        job.update(extra)
        self.jobs[job_id] = job
        return job

    def start_live(self, seconds: int, decrypt: str | None = None, wpa_pwd: str | None = None) -> dict:
        if not 1 <= seconds <= MAX_SECONDS:
            raise HTTPException(400, f"seconds must be between 1 and {MAX_SECONDS}")
        if not self.iface_exists(self.iface):
            raise HTTPException(409, f"{self.iface} is missing, so there is nothing to capture. "
                                     "After a VM reboot run: sudo bash lab/setup_lab.sh")
        with self.lock:
            job = self._new("live", seconds=seconds, iface=self.iface, decrypt=decrypt, _wpa=wpa_pwd)
        threading.Thread(target=self._run_live, args=(job,), daemon=True).start()
        return self.view(job)

    def start_upload(self, data: bytes, filename: str, decrypt: str | None = None, wpa_pwd: str | None = None) -> dict:
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, f"File is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
        if not is_pcap(data):
            raise HTTPException(400, "That is not a pcap or pcapng file.")
        with self.lock:
            job = self._new("upload", status="analysing", filename=Path(filename).name[:100] or "upload.pcap",
                            bytes=len(data), decrypt=decrypt, _wpa=wpa_pwd)
            self._pcap(job).write_bytes(data)
            self._own(self._pcap(job))
        threading.Thread(target=self._analyse, args=(job,), daemon=True).start()
        return self.view(job)

    # -- running -------------------------------------------------------------------------------

    def _pcap(self, job: dict) -> Path:
        return self.out_dir / f"{job['id']}.pcap"

    def _run_live(self, job: dict) -> None:
        # dumpcap writes to /tmp first: run as root it drops its powers right after opening the
        # interface and then may not be allowed to write inside the repo folder.
        spool = Path(tempfile.gettempdir()) / f"wifi-capture-{job['id']}.pcap"
        job["_spool"] = spool
        try:
            proc = subprocess.run(self.capture_cmd(job["iface"], job["seconds"], spool),
                                  stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                                  timeout=job["seconds"] + 30)
            if proc.returncode != 0 or not spool.exists():
                err = (proc.stderr or "").strip().splitlines()
                raise RuntimeError(_capture_error(err[-1] if err else f"dumpcap exited with {proc.returncode}"))
            shutil.move(str(spool), self._pcap(job))
            self._own(self._pcap(job))
            job["bytes"] = self._pcap(job).stat().st_size
        except Exception as e:  # noqa: BLE001 - any failure ends the job with a readable reason
            return self._fail(job, e)
        finally:
            job.pop("_spool", None)
            spool.unlink(missing_ok=True)
        job["status"] = "analysing"
        self._analyse(job)

    def _analyse(self, job: dict) -> None:
        out = self.out_dir / f"{job['id']}.analysis.tmp"
        try:
            proc = subprocess.run(self.analyse_cmd(self._pcap(job), out, job["_wpa"]), cwd=REPO_ROOT,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                                  timeout=ANALYSE_TIMEOUT_S)
            if proc.returncode != 0:
                err = (proc.stderr or "").strip().splitlines()
                raise RuntimeError("Analysis failed: " + (err[-1] if err else f"exit code {proc.returncode}"))
            job["result"] = json.loads(out.read_text())
        except subprocess.TimeoutExpired:
            return self._fail(job, RuntimeError(f"Analysis took longer than {ANALYSE_TIMEOUT_S} s."))
        except Exception as e:  # noqa: BLE001
            return self._fail(job, e)
        finally:
            out.unlink(missing_ok=True)
        job["status"] = "done"
        job["finished"] = _now()
        self._save(job)

    def _fail(self, job: dict, e: Exception) -> None:
        job["status"] = "failed"
        job["error"] = str(e)
        job["finished"] = _now()
        self._save(job)

    def _save(self, job: dict) -> None:
        path = self.out_dir / f"{job['id']}.json"
        path.write_text(json.dumps(self._public(job)))
        self._own(path)
        self._prune()

    def _prune(self) -> None:
        saved = sorted(self.out_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in saved[KEEP:]:
            old.unlink(missing_ok=True)
            old.with_suffix(".pcap").unlink(missing_ok=True)

    def _own(self, path: Path) -> None:
        """Run as root (sudo), new files would belong to root and the normal user could no longer
        change them (the same trap as a root-owned plans.db). Give them to whoever owns reports/."""
        if os.geteuid() != 0:
            return
        st = self.out_dir.parent.stat()
        try:
            os.chown(path, st.st_uid, st.st_gid)
        except OSError:
            pass

    # -- reading -------------------------------------------------------------------------------

    def _public(self, job: dict) -> dict:
        return {k: v for k, v in job.items() if not k.startswith("_")}

    def view(self, job: dict) -> dict:
        """What the browser polls: the job, plus how far a live capture has got."""
        v = self._public(job)
        if job["status"] == "capturing" and "_t0" in job:
            v["elapsed_s"] = min(job["seconds"], round(time.monotonic() - job["_t0"], 1))
            spool = job.get("_spool")
            try:
                v["bytes"] = spool.stat().st_size if spool else 0
            except OSError:
                v["bytes"] = 0  # dumpcap has not created the file yet, or root made it unreadable
        return v

    def get(self, job_id: str) -> dict | None:
        job = self.jobs.get(job_id)
        if job:
            return self.view(job)
        path = self.out_dir / f"{job_id}.json"
        if not job_id.isalnum() or not path.is_file():
            return None
        return json.loads(path.read_text())

    def current(self) -> dict | None:
        """The capture still going, so a page opened (or refreshed) mid-capture finds it again."""
        going = [j for j in self.jobs.values() if j["status"] in ("capturing", "analysing")]
        return self.view(going[0]) if going else None

    def recent(self, n: int = KEEP) -> list[dict]:
        """Finished captures, newest first, without the analysis (the list does not need it)."""
        if not self.out_dir.is_dir():
            return []
        out = []
        for p in sorted(self.out_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:n]:
            try:
                j = json.loads(p.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            r = j.pop("result", None) or {}
            out.append(j | {"frames": r.get("frames"), "devices": len(r.get("devices", [])),
                            "disconnects": len(r.get("disconnects", []))})
        return out

    def pcap_path(self, job_id: str) -> Path | None:
        p = self.out_dir / f"{job_id}.pcap"
        return p if job_id.isalnum() and p.is_file() else None


def _capture_error(line: str) -> str:
    if "permission" in line.lower() or "don't have" in line.lower():
        return ("dumpcap is not allowed to capture. Either start the API with sudo -E, or add yourself to the "
                "wireshark group once (sudo usermod -aG wireshark $USER, then log out and in). " + line)
    return line

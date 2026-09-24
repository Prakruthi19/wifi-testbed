"""Small helpers shared by the drivers: command execution, polling, template rendering."""

from __future__ import annotations

import logging
import shlex
import subprocess
import time
from pathlib import Path
from typing import Callable, Sequence, TypeVar

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from testbed import CONFIGS_DIR

log = logging.getLogger("testbed")

T = TypeVar("T")


class CommandError(RuntimeError):
    def __init__(self, cmd: Sequence[str], proc: subprocess.CompletedProcess):
        self.cmd = list(cmd)
        self.proc = proc
        super().__init__(
            f"command failed ({proc.returncode}): {shlex.join(self.cmd)}\n"
            f"stdout: {proc.stdout.strip()}\nstderr: {proc.stderr.strip()}"
        )


def ns_prefix(namespace: str | None) -> list[str]:
    """Prefix that runs a command inside a network namespace (or nothing for the root namespace)."""
    return ["ip", "netns", "exec", namespace] if namespace else []


def run(
    cmd: Sequence[str],
    namespace: str | None = None,
    check: bool = True,
    timeout: float = 30,
) -> subprocess.CompletedProcess:
    full = ns_prefix(namespace) + list(cmd)
    log.debug("run: %s", shlex.join(full))
    proc = subprocess.run(full, capture_output=True, text=True, timeout=timeout)
    if check and proc.returncode != 0:
        raise CommandError(full, proc)
    return proc


def wait_for(
    predicate: Callable[[], T],
    timeout: float,
    interval: float = 0.1,
) -> T | None:
    """Poll `predicate` until it returns a truthy value or the timeout expires."""
    deadline = time.monotonic() + timeout
    while True:
        value = predicate()
        if value:
            return value
        if time.monotonic() >= deadline:
            return None
        time.sleep(interval)


_env = Environment(
    loader=FileSystemLoader(str(CONFIGS_DIR)),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
)


def render(template: str, dest: Path | None = None, **params) -> str:
    """Render a template under configs/ and optionally write it to `dest`."""
    text = _env.get_template(template).render(**params)
    if dest is not None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text)
    return text


def tail(path: Path, lines: int = 80) -> str:
    try:
        return "\n".join(path.read_text(errors="replace").splitlines()[-lines:])
    except FileNotFoundError:
        return f"<{path} not found>"

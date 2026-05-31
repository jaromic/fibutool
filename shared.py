"""shared — utilities common to all fibutool entry points."""

import sys
from datetime import datetime
from pathlib import Path


def default_config_path() -> Path:
    """Return the default config path: next to the EXE (frozen) or next to the script (dev)."""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent / "config.yaml"
    return Path(__file__).parent / "config.yaml"


class Tee:
    """Forward writes to multiple streams — copies console output to a log file."""

    def __init__(self, *streams):
        self._streams = streams

    def write(self, text):
        for s in self._streams:
            s.write(text)
            s.flush()

    def flush(self):
        for s in self._streams:
            s.flush()


def setup_logging(workdir: Path, prefix: str) -> None:
    """Open a timestamped log file in workdir and tee stdout/stderr to it.

    Falls back to console-only if the log file cannot be opened.
    """
    ts = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    log_path = workdir / f"{ts}_{prefix}.log"

    # force utf-8 encoding, as fallback convert unicode characters to backslash encoded entities:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='backslashreplace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='backslashreplace')

    try:
        log_file = open(log_path, "w", encoding="utf-8")
        sys.stdout = Tee(sys.__stdout__, log_file)
        sys.stderr = Tee(sys.__stderr__, log_file)
    except OSError as e:
        print(f"{prefix}: warning — could not open log file {log_path}: {e}", file=sys.stderr)

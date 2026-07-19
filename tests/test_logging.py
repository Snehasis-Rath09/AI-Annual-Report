"""Tests for the process-wide application logging architecture."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_logging_is_centralized_idempotent_and_rotates(tmp_path: Path) -> None:
    """All module records should use one handler and rotate without locking."""
    log_file = tmp_path / "application.log"
    script = f"""
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from config.settings import LOGGING_CONFIG

LOGGING_CONFIG.update({{
    "level": "DEBUG",
    "file_path": Path({str(log_file)!r}),
    "max_bytes": 512,
    "backup_count": 3,
    "console_enabled": True,
    "file_enabled": True,
}})

from src.utils.logger import get_logger

first = get_logger("tests.logging.first")
second = get_logger("tests.logging.second")
assert get_logger("tests.logging.first") is first

for index in range(40):
    (first if index % 2 == 0 else second).debug(
        "rotation-record-%02d-%s", index, "x" * 80
    )

marker = "single-record-marker"
second.warning(marker)

root = logging.getLogger()
file_handlers = []
for candidate in [root, *logging.Logger.manager.loggerDict.values()]:
    if isinstance(candidate, logging.Logger):
        file_handlers.extend(
            handler
            for handler in candidate.handlers
            if isinstance(handler, RotatingFileHandler)
        )

assert len(file_handlers) == 1
assert first.handlers == []
assert second.handlers == []
assert first.propagate is True
assert second.propagate is True

file_handlers[0].flush()
paths = [Path({str(log_file)!r}), *sorted(Path({str(tmp_path)!r}).glob("application.log.*"))]
assert len(paths) >= 2
content = "".join(path.read_text(encoding="utf-8") for path in paths)
assert content.count(marker) == 1
print("logging-verification-ok")
"""

    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "logging-verification-ok" in completed.stdout
    assert completed.stderr.count("single-record-marker") == 1
    assert "Logging error" not in completed.stderr

"""Centralized, process-wide logging configuration."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import RLock
from typing import Iterator

from config.settings import LOGGING_CONFIG


_CONFIGURATION_LOCK = RLock()
_HANDLER_MARKER = "_ai_annual_report_handler"
_FILE_HANDLER_KIND = "file"
_CONSOLE_HANDLER_KIND = "console"


def _resolve_log_level(level: str | int) -> int:
    """Resolve a logging level from string or integer input."""
    if isinstance(level, int):
        return level

    resolved_level = logging.getLevelName(level.upper())
    if isinstance(resolved_level, int):
        return resolved_level

    return logging.INFO


def _build_formatter() -> logging.Formatter:
    """Build the project logging formatter."""
    return logging.Formatter(
        fmt=str(LOGGING_CONFIG["format"]),
        datefmt=str(LOGGING_CONFIG["date_format"]),
    )


def _registered_loggers() -> Iterator[logging.Logger]:
    """Yield every instantiated non-root logger."""
    for candidate in logging.Logger.manager.loggerDict.values():
        if isinstance(candidate, logging.Logger):
            yield candidate


def _is_target_file_handler(
    handler: logging.Handler,
    log_file: Path,
) -> bool:
    """Return whether a handler rotates the configured application log."""
    if not isinstance(handler, RotatingFileHandler):
        return False
    return Path(handler.baseFilename).resolve() == log_file.resolve()


def _handler_kind(handler: logging.Handler) -> str | None:
    """Return the project marker stored on a managed handler."""
    return getattr(handler, _HANDLER_MARKER, None)


def _mark_handler(handler: logging.Handler, kind: str) -> None:
    """Mark a handler as owned by this logging configuration."""
    setattr(handler, _HANDLER_MARKER, kind)


def _detach_and_close(
    logger: logging.Logger,
    handler: logging.Handler,
) -> None:
    """Detach and close a handler so it no longer owns an OS resource."""
    logger.removeHandler(handler)
    handler.close()


def _remove_legacy_module_handlers(log_file: Path) -> None:
    """Remove handlers created by the former per-module configuration.

    Earlier releases attached a console handler and a rotating file handler to
    every module logger. During an in-process reload (notably under Streamlit),
    those logger objects can survive the code reload. This migration closes all
    rotating handlers that target the application log and removes their paired
    module console handlers before records are routed to the root logger.
    """
    for logger in _registered_loggers():
        legacy_file_handlers = [
            handler
            for handler in logger.handlers
            if _is_target_file_handler(handler, log_file)
            or _handler_kind(handler) == _FILE_HANDLER_KIND
        ]
        if not legacy_file_handlers:
            continue

        for handler in legacy_file_handlers:
            _detach_and_close(logger, handler)

        for handler in list(logger.handlers):
            if (
                type(handler) is logging.StreamHandler
                or _handler_kind(handler) == _CONSOLE_HANDLER_KIND
            ):
                _detach_and_close(logger, handler)

        logger.propagate = True


def _configure_file_handler(
    root_logger: logging.Logger,
    formatter: logging.Formatter,
    log_level: int,
    log_file: Path,
) -> None:
    """Ensure the root logger owns exactly one application file handler."""
    managed_handlers = [
        handler
        for handler in root_logger.handlers
        if _handler_kind(handler) == _FILE_HANDLER_KIND
    ]
    matching_handlers = [
        handler
        for handler in managed_handlers
        if _is_target_file_handler(handler, log_file)
    ]
    file_handler = matching_handlers[0] if matching_handlers else None

    for handler in list(root_logger.handlers):
        if handler is file_handler:
            continue
        if (
            _handler_kind(handler) == _FILE_HANDLER_KIND
            or _is_target_file_handler(handler, log_file)
        ):
            _detach_and_close(root_logger, handler)

    if not bool(LOGGING_CONFIG["file_enabled"]):
        if file_handler is not None:
            _detach_and_close(root_logger, file_handler)
        return

    log_file.parent.mkdir(parents=True, exist_ok=True)
    if file_handler is None:
        file_handler = RotatingFileHandler(
            filename=log_file,
            maxBytes=int(LOGGING_CONFIG["max_bytes"]),
            backupCount=int(LOGGING_CONFIG["backup_count"]),
            encoding="utf-8",
            delay=True,
        )
        _mark_handler(file_handler, _FILE_HANDLER_KIND)
        root_logger.addHandler(file_handler)
    else:
        file_handler.maxBytes = int(LOGGING_CONFIG["max_bytes"])
        file_handler.backupCount = int(LOGGING_CONFIG["backup_count"])

    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)


def _configure_console_handler(
    root_logger: logging.Logger,
    formatter: logging.Formatter,
    log_level: int,
) -> None:
    """Ensure the root logger owns at most one project console handler."""
    managed_handlers = [
        handler
        for handler in root_logger.handlers
        if _handler_kind(handler) == _CONSOLE_HANDLER_KIND
    ]
    console_handler = managed_handlers[0] if managed_handlers else None

    for handler in managed_handlers[1:]:
        _detach_and_close(root_logger, handler)

    if not bool(LOGGING_CONFIG["console_enabled"]):
        if console_handler is not None:
            _detach_and_close(root_logger, console_handler)
        return

    if console_handler is None:
        console_handler = logging.StreamHandler()
        _mark_handler(console_handler, _CONSOLE_HANDLER_KIND)
        root_logger.addHandler(console_handler)

    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)


def _configure_application_logging() -> None:
    """Configure the shared handlers once and keep configuration idempotent."""
    with _CONFIGURATION_LOCK:
        log_level = _resolve_log_level(LOGGING_CONFIG["level"])
        formatter = _build_formatter()
        log_file = Path(LOGGING_CONFIG["file_path"]).expanduser().resolve()
        root_logger = logging.getLogger()

        _remove_legacy_module_handlers(log_file)
        _configure_file_handler(root_logger, formatter, log_level, log_file)
        _configure_console_handler(root_logger, formatter, log_level)


def get_logger(name: str) -> logging.Logger:
    """Return a module logger routed through the shared application handlers.

    The root logger is the sole owner of the application's rotating file and
    console handlers. Module loggers own no handlers and propagate each record
    exactly once. Repeated calls for any number of names are idempotent.

    Args:
        name: Logger name, typically ``__name__``.

    Returns:
        Configured module logger.
    """
    _configure_application_logging()

    logger = logging.getLogger(name)
    logger.setLevel(_resolve_log_level(LOGGING_CONFIG["level"]))

    # Defensive cleanup supports hot reloads from the legacy implementation.
    for handler in list(logger.handlers):
        if (
            _handler_kind(handler) is not None
            or _is_target_file_handler(
                handler,
                Path(LOGGING_CONFIG["file_path"]).expanduser().resolve(),
            )
        ):
            _detach_and_close(logger, handler)

    logger.propagate = True
    return logger

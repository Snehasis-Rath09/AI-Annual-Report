"""Reusable filesystem utilities for the AI-Annual-Report project."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.utils.constants import (
    DEFAULT_ENCODING,
    ERROR_MESSAGES,
    FALLBACK_ENCODINGS,
    REGEX_PATTERNS,
    SUPPORTED_PDF_EXTENSIONS,
)
from src.utils.logger import get_logger


logger = get_logger(__name__)


def ensure_directory(path: str | Path) -> Path:
    """Create a directory if it does not already exist.

    Args:
        path: Directory path.

    Returns:
        Resolved directory path.

    Raises:
        OSError: If the directory cannot be created.
    """
    directory = Path(path).expanduser().resolve()
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError:
        logger.exception(
            "%s Path: %s",
            ERROR_MESSAGES["directory_create_failed"],
            directory,
        )
        raise
    return directory


def read_text_file(
    file_path: str | Path,
    encoding: str = DEFAULT_ENCODING,
    fallback_encodings: tuple[str, ...] = FALLBACK_ENCODINGS,
) -> str:
    """Read a text file with encoding fallbacks.

    Args:
        file_path: Text file path.
        encoding: Preferred encoding.
        fallback_encodings: Encodings to try if preferred encoding fails.

    Returns:
        File contents.

    Raises:
        FileNotFoundError: If the file does not exist.
        UnicodeDecodeError: If no encoding can decode the file.
        OSError: If the file cannot be read.
    """
    path = Path(file_path).expanduser().resolve()
    encodings = (encoding, *(item for item in fallback_encodings if item != encoding))

    if not path.is_file():
        logger.error("%s Path: %s", ERROR_MESSAGES["file_not_found"], path)
        raise FileNotFoundError(f"{ERROR_MESSAGES['file_not_found']} Path: {path}")

    last_decode_error: UnicodeDecodeError | None = None
    for candidate_encoding in encodings:
        try:
            return path.read_text(encoding=candidate_encoding)
        except UnicodeDecodeError as exc:
            last_decode_error = exc
            logger.debug(
                "Failed to decode %s with encoding %s.",
                path,
                candidate_encoding,
            )
        except OSError:
            logger.exception("%s Path: %s", ERROR_MESSAGES["read_failed"], path)
            raise

    if last_decode_error is not None:
        logger.exception("%s Path: %s", ERROR_MESSAGES["read_failed"], path)
        raise last_decode_error

    return ""


def write_text_file(
    file_path: str | Path,
    content: str,
    encoding: str = DEFAULT_ENCODING,
    overwrite: bool = True,
) -> Path:
    """Write text content to a file.

    Args:
        file_path: Destination file path.
        content: Text content to write.
        encoding: Output encoding.
        overwrite: Whether an existing file may be replaced.

    Returns:
        Resolved destination file path.

    Raises:
        FileExistsError: If the file exists and overwrite is False.
        OSError: If the file cannot be written.
    """
    path = Path(file_path).expanduser().resolve()
    ensure_directory(path.parent)

    if path.exists() and not overwrite:
        message = f"File already exists and overwrite is disabled. Path: {path}"
        logger.error(message)
        raise FileExistsError(message)

    try:
        path.write_text(content, encoding=encoding)
    except OSError:
        logger.exception("%s Path: %s", ERROR_MESSAGES["write_failed"], path)
        raise

    return path


def save_json(
    file_path: str | Path,
    data: Any,
    encoding: str = DEFAULT_ENCODING,
    indent: int = 2,
    overwrite: bool = True,
) -> Path:
    """Serialize data to a JSON file.

    Args:
        file_path: Destination JSON path.
        data: JSON-serializable object.
        encoding: Output encoding.
        indent: Indentation level.
        overwrite: Whether an existing file may be replaced.

    Returns:
        Resolved destination file path.

    Raises:
        TypeError: If data is not JSON serializable.
        FileExistsError: If the file exists and overwrite is False.
        OSError: If the file cannot be written.
    """
    path = Path(file_path).expanduser().resolve()
    ensure_directory(path.parent)

    if path.exists() and not overwrite:
        message = f"File already exists and overwrite is disabled. Path: {path}"
        logger.error(message)
        raise FileExistsError(message)

    try:
        json_content = json.dumps(data, ensure_ascii=False, indent=indent)
    except TypeError:
        logger.exception("%s Path: %s", ERROR_MESSAGES["json_encode_failed"], path)
        raise

    try:
        path.write_text(f"{json_content}\n", encoding=encoding)
    except OSError:
        logger.exception("%s Path: %s", ERROR_MESSAGES["write_failed"], path)
        raise

    return path


def load_json(file_path: str | Path, encoding: str = DEFAULT_ENCODING) -> Any:
    """Load and parse a JSON file.

    Args:
        file_path: JSON file path.
        encoding: File encoding.

    Returns:
        Parsed JSON object.

    Raises:
        FileNotFoundError: If the file does not exist.
        json.JSONDecodeError: If the JSON is invalid.
        OSError: If the file cannot be read.
    """
    path = Path(file_path).expanduser().resolve()
    try:
        content = read_text_file(path, encoding=encoding)
        return json.loads(content)
    except json.JSONDecodeError:
        logger.exception("%s Path: %s", ERROR_MESSAGES["json_decode_failed"], path)
        raise


def list_pdf_files(directory: str | Path, recursive: bool = True) -> list[Path]:
    """List PDF files in a directory.

    Args:
        directory: Directory to search.
        recursive: Whether to search nested directories.

    Returns:
        Sorted list of PDF paths.

    Raises:
        NotADirectoryError: If the path is not a directory.
    """
    path = Path(directory).expanduser().resolve()
    if not path.is_dir():
        logger.error("Directory does not exist. Path: %s", path)
        raise NotADirectoryError(f"Directory does not exist. Path: {path}")

    iterator = path.rglob("*") if recursive else path.glob("*")
    return sorted(
        item
        for item in iterator
        if item.is_file() and item.suffix.lower() in SUPPORTED_PDF_EXTENSIONS
    )


def sanitize_filename(
    filename: str,
    replacement: str = "_",
    max_length: int = 180,
) -> str:
    """Sanitize a string for safe use as a filename.

    Args:
        filename: Raw filename or title.
        replacement: Replacement for unsafe characters.
        max_length: Maximum filename length excluding path.

    Returns:
        Sanitized filename.
    """
    sanitized = re.sub(REGEX_PATTERNS["filename_unsafe_chars"], replacement, filename)
    sanitized = re.sub(REGEX_PATTERNS["multiple_whitespace"], " ", sanitized)
    sanitized = sanitized.strip(" .")
    sanitized = re.sub(rf"{re.escape(replacement)}+", replacement, sanitized)

    if not sanitized:
        sanitized = "untitled"

    return sanitized[:max_length].rstrip(" .")


def file_exists(file_path: str | Path) -> bool:
    """Check whether a path exists and is a file.

    Args:
        file_path: Path to inspect.

    Returns:
        True when the path exists and is a file.
    """
    return Path(file_path).expanduser().is_file()


def create_timestamp(include_timezone: bool = False) -> str:
    """Create a filesystem-friendly UTC timestamp.

    Args:
        include_timezone: Whether to append the UTC timezone marker.

    Returns:
        Timestamp string in ``YYYYMMDD_HHMMSS`` format.
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    if include_timezone:
        return f"{timestamp}_UTC"
    return timestamp


def safe_delete(path: str | Path) -> bool:
    """Delete a file or empty directory safely.

    Args:
        path: File or empty directory path.

    Returns:
        True if a path was deleted, False if it did not exist.

    Raises:
        OSError: If deletion fails.
    """
    target = Path(path).expanduser().resolve()
    if not target.exists():
        return False

    try:
        if target.is_file() or target.is_symlink():
            target.unlink()
        elif target.is_dir():
            target.rmdir()
        else:
            logger.error("Unsupported path type for deletion. Path: %s", target)
            return False
    except OSError:
        logger.exception("%s Path: %s", ERROR_MESSAGES["delete_failed"], target)
        raise

    return True


def get_file_size_mb(file_path: str | Path) -> float:
    """Return a file size in megabytes.

    Args:
        file_path: File path.

    Returns:
        File size in megabytes rounded to three decimals.

    Raises:
        FileNotFoundError: If the file does not exist.
        OSError: If file metadata cannot be read.
    """
    path = Path(file_path).expanduser().resolve()
    if not path.is_file():
        logger.error("%s Path: %s", ERROR_MESSAGES["file_not_found"], path)
        raise FileNotFoundError(f"{ERROR_MESSAGES['file_not_found']} Path: {path}")

    try:
        return round(path.stat().st_size / (1024 * 1024), 3)
    except OSError:
        logger.exception("Unable to read file metadata. Path: %s", path)
        raise

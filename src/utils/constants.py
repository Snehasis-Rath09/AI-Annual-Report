"""Shared constants for the AI-Annual-Report project."""

from __future__ import annotations

from typing import Final


# Project metadata
PROJECT_NAME: Final[str] = "AI-Annual-Report"
PROJECT_VERSION: Final[str] = "1.0.0"
AUTHOR: Final[str] = "AI-Annual-Report Research Team"
PYTHON_VERSION: Final[str] = "3.12"

# Encodings
DEFAULT_ENCODING: Final[str] = "utf-8"
UTF_8_SIG_ENCODING: Final[str] = "utf-8-sig"
FALLBACK_ENCODINGS: Final[tuple[str, ...]] = (
    DEFAULT_ENCODING,
    UTF_8_SIG_ENCODING,
    "cp1252",
    "latin-1",
)

# Supported file extensions
SUPPORTED_PDF_EXTENSIONS: Final[tuple[str, ...]] = (".pdf",)
SUPPORTED_TEXT_EXTENSIONS: Final[tuple[str, ...]] = (".txt", ".text", ".md")
SUPPORTED_JSON_EXTENSIONS: Final[tuple[str, ...]] = (".json",)
SUPPORTED_EXCEL_EXTENSIONS: Final[tuple[str, ...]] = (".xlsx", ".xlsm", ".xls")

# Regular expression patterns
REGEX_PATTERNS: Final[dict[str, str]] = {
    "multiple_whitespace": r"\s+",
    "line_breaks": r"(\r\n|\r|\n)+",
    "page_number": r"(?im)^\s*(page\s*)?\d+\s*(of\s+\d+)?\s*$",
    "financial_year": (
        r"\b(?:FY|F\.Y\.|financial year)\s*[-:]?\s*"
        r"(20\d{2})(?:[-/](\d{2,4}))?\b"
    ),
    "year": r"\b(?:19|20)\d{2}\b",
    "cin": r"\b[LU]\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6}\b",
    "isin": r"\bIN[A-Z0-9]{10}\b",
    "email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
    "url": r"\bhttps?://[^\s<>()]+",
    "heading_number": r"^\s*(?:\d+|[IVXLCDM]+|[A-Z])(?:[\.\)]|\s+-)\s+",
    "non_word_boundary": r"[^\w\s&.-]",
    "filename_unsafe_chars": r'[<>:"/\\|?*\x00-\x1f]',
}

# Excel sheet names
EXCEL_SHEET_NAMES: Final[dict[str, str]] = {
    "scores": "Disclosure Scores",
    "company_summary": "Company Summary",
    "keyword_counts": "Keyword Counts",
    "category_counts": "Category Counts",
    "section_matches": "Section Matches",
    "extraction_quality": "Extraction Quality",
    "validation": "Validation",
    "metadata": "Metadata",
}

# Dashboard constants
DASHBOARD_TITLE: Final[str] = PROJECT_NAME
DASHBOARD_DEFAULT_PAGE_SIZE: Final[int] = 25
DASHBOARD_PAGE_SIZE_OPTIONS: Final[tuple[int, ...]] = (10, 25, 50, 100)
DASHBOARD_SCORE_DECIMALS: Final[int] = 3
DASHBOARD_DATE_FORMAT: Final[str] = "%Y-%m-%d"

# Default thresholds
DEFAULT_THRESHOLDS: Final[dict[str, float]] = {
    "min_text_length": 500.0,
    "min_page_text_length": 50.0,
    "min_keyword_count": 1.0,
    "min_section_confidence": 0.65,
    "min_extraction_quality": 0.80,
    "high_disclosure_score": 0.75,
    "medium_disclosure_score": 0.40,
}

# Error messages
ERROR_MESSAGES: Final[dict[str, str]] = {
    "file_not_found": "The requested file does not exist.",
    "invalid_file_extension": "The file extension is not supported.",
    "read_failed": "Unable to read file.",
    "write_failed": "Unable to write file.",
    "json_encode_failed": "Unable to serialize object as JSON.",
    "json_decode_failed": "Unable to parse JSON file.",
    "directory_create_failed": "Unable to create directory.",
    "delete_failed": "Unable to delete path safely.",
    "pdf_extraction_failed": "Unable to extract text from PDF.",
    "ocr_failed": "Unable to complete OCR extraction.",
    "validation_failed": "Validation failed.",
}

# Scoring labels
DISCLOSURE_SCORE_LABELS: Final[dict[str, str]] = {
    "high": "High Disclosure",
    "medium": "Medium Disclosure",
    "low": "Low Disclosure",
    "none": "No Disclosure",
}

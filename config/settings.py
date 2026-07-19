"""Application settings for the AI-Annual-Report project.

This module centralizes project paths, extraction options, dashboard defaults,
validation thresholds, export settings, and domain dictionaries used by the
research pipeline.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final


def _detect_project_root() -> Path:
    """Detect the repository root from this settings file.

    Returns:
        Absolute path to the project root directory.
    """
    current_path = Path(__file__).resolve()
    markers = {"README.md", ".gitignore", "src", "data"}

    for parent in (current_path.parent, *current_path.parents):
        if sum((parent / marker).exists() for marker in markers) >= 2:
            return parent

    return current_path.parents[1]


# Project metadata
PROJECT_NAME: Final[str] = "AI-Annual-Report"
PROJECT_VERSION: Final[str] = "1.0.0"
PROJECT_DESCRIPTION: Final[str] = (
    "Research pipeline for extracting and scoring AI and innovation disclosures "
    "from annual reports of Indian listed companies."
)

# Project directories
PROJECT_ROOT: Final[Path] = _detect_project_root()
CONFIG_DIR: Final[Path] = PROJECT_ROOT / "config"
SRC_DIR: Final[Path] = PROJECT_ROOT / "src"
DASHBOARD_DIR: Final[Path] = PROJECT_ROOT / "dashboard"
SCRIPTS_DIR: Final[Path] = PROJECT_ROOT / "scripts"
TESTS_DIR: Final[Path] = PROJECT_ROOT / "tests"
NOTEBOOKS_DIR: Final[Path] = PROJECT_ROOT / "notebooks"
DOCUMENTATION_DIR: Final[Path] = PROJECT_ROOT / "documentation"

DATA_DIR: Final[Path] = PROJECT_ROOT / "data"
RAW_DATA_DIR: Final[Path] = DATA_DIR / "raw_reports"
ANNUAL_REPORTS_DIR: Final[Path] = RAW_DATA_DIR
PROCESSED_DATA_DIR: Final[Path] = DATA_DIR / "processed"
EXTRACTED_TEXT_DIR: Final[Path] = PROCESSED_DATA_DIR / "extracted_text"
SECTION_OUTPUT_DIR: Final[Path] = PROCESSED_DATA_DIR / "sections"
SCORES_DIR: Final[Path] = PROCESSED_DATA_DIR / "scores"
DICTIONARIES_DIR: Final[Path] = DATA_DIR / "dictionaries"
METADATA_DIR: Final[Path] = DATA_DIR / "metadata"
VALIDATION_DIR: Final[Path] = DATA_DIR / "validation"
EXPORTS_DIR: Final[Path] = PROJECT_ROOT / "outputs"
EXCEL_EXPORT_DIR: Final[Path] = EXPORTS_DIR / "excel"
LOG_DIR: Final[Path] = PROJECT_ROOT / "logs"
TEMP_DIR: Final[Path] = PROJECT_ROOT / "tmp"

# Important files
INNOVATION_DICTIONARY_FILE: Final[Path] = (
    DICTIONARIES_DIR / "Innovation_Dictionary.xlsx"
)
COMPANY_MASTER_FILE: Final[Path] = METADATA_DIR / "Company_Master.xlsx"
VALIDATION_FILE: Final[Path] = VALIDATION_DIR / "Validation.xlsx"
DISCLOSURE_SCORES_FILE: Final[Path] = EXCEL_EXPORT_DIR / "disclosure_scores.xlsx"
EXTRACTION_SUMMARY_FILE: Final[Path] = EXCEL_EXPORT_DIR / "extraction_summary.xlsx"
APPLICATION_LOG_FILE: Final[Path] = LOG_DIR / "ai_annual_report.log"

# Supported files
SUPPORTED_PDF_EXTENSIONS: Final[tuple[str, ...]] = (".pdf",)
SUPPORTED_TEXT_EXTENSIONS: Final[tuple[str, ...]] = (".txt", ".text", ".md")
SUPPORTED_EXCEL_EXTENSIONS: Final[tuple[str, ...]] = (".xlsx", ".xlsm", ".xls")
SUPPORTED_JSON_EXTENSIONS: Final[tuple[str, ...]] = (".json",)
SUPPORTED_FILE_EXTENSIONS: Final[tuple[str, ...]] = (
    *SUPPORTED_PDF_EXTENSIONS,
    *SUPPORTED_TEXT_EXTENSIONS,
    *SUPPORTED_EXCEL_EXTENSIONS,
    *SUPPORTED_JSON_EXTENSIONS,
)

# OCR configuration
OCR_CONFIG: Final[dict[str, object]] = {
    "enabled": True,
    "language": "eng",
    "dpi": 300,
    "page_segmentation_mode": 6,
    "engine_mode": 3,
    "timeout_seconds": 300,
    "min_text_length_for_native_extraction": 500,
}

# PDF extraction configuration
PDF_EXTRACTION_CONFIG: Final[dict[str, object]] = {
    "prefer_native_text": True,
    "use_ocr_fallback": True,
    "max_pages": None,
    "start_page": 1,
    "preserve_layout": True,
    "remove_headers_footers": True,
    "min_page_text_length": 50,
}

# Dashboard configuration
DASHBOARD_CONFIG: Final[dict[str, object]] = {
    "page_title": PROJECT_NAME,
    "page_icon": "📊",
    "layout": "wide",
    "initial_sidebar_state": "expanded",
    "default_rows_per_page": 25,
    "max_rows_per_page": 200,
    "chart_height": 420,
}

# Logging configuration
LOGGING_CONFIG: Final[dict[str, object]] = {
    "level": "INFO",
    "format": "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    "date_format": "%Y-%m-%d %H:%M:%S",
    "file_path": APPLICATION_LOG_FILE,
    "max_bytes": 5_242_880,
    "backup_count": 5,
    "console_enabled": True,
    "file_enabled": True,
}

# Validation configuration
VALIDATION_CONFIG: Final[dict[str, object]] = {
    "sample_size": 50,
    "min_extraction_quality_score": 0.80,
    "min_keyword_precision": 0.75,
    "min_keyword_recall": 0.70,
    "min_section_match_score": 0.65,
    "empty_text_failure_threshold": 0.05,
}

# Excel export configuration
EXCEL_EXPORT_CONFIG: Final[dict[str, object]] = {
    "engine": "openpyxl",
    "index": False,
    "freeze_panes": (1, 0),
    "date_format": "yyyy-mm-dd",
    "datetime_format": "yyyy-mm-dd hh:mm:ss",
    "default_sheet_name": "Disclosure Scores",
    "auto_filter": True,
}

# Annual report headings relevant for disclosure extraction
SUPPORTED_REPORT_HEADINGS: Final[tuple[str, ...]] = (
    "Board's Report",
    "Directors' Report",
    "Management Discussion and Analysis",
    "Business Responsibility and Sustainability Report",
    "Corporate Governance Report",
    "Integrated Report",
    "Strategy",
    "Risk Management",
    "Research and Development",
    "Technology",
    "Digital Transformation",
    "Innovation",
    "Human Resources",
    "Sustainability",
)

# Keyword category constants
KEYWORD_CATEGORIES: Final[dict[str, tuple[str, ...]]] = {
    "artificial_intelligence": (
        "artificial intelligence",
        "ai",
        "machine learning",
        "deep learning",
        "generative ai",
        "natural language processing",
        "computer vision",
    ),
    "automation": (
        "automation",
        "robotic process automation",
        "rpa",
        "intelligent automation",
        "process automation",
    ),
    "analytics": (
        "data analytics",
        "advanced analytics",
        "big data",
        "predictive analytics",
        "data science",
        "business intelligence",
    ),
    "digital_transformation": (
        "digital transformation",
        "digitalization",
        "digitisation",
        "cloud",
        "platform",
        "digital initiatives",
    ),
    "innovation": (
        "innovation",
        "research and development",
        "r&d",
        "patent",
        "new product development",
        "technology adoption",
    ),
}

REQUIRED_DIRECTORIES: Final[tuple[Path, ...]] = (
    DATA_DIR,
    RAW_DATA_DIR,
    ANNUAL_REPORTS_DIR,
    PROCESSED_DATA_DIR,
    EXTRACTED_TEXT_DIR,
    SECTION_OUTPUT_DIR,
    SCORES_DIR,
    DICTIONARIES_DIR,
    METADATA_DIR,
    VALIDATION_DIR,
    EXPORTS_DIR,
    EXCEL_EXPORT_DIR,
    LOG_DIR,
    TEMP_DIR,
)


def ensure_directories_exist() -> None:
    """Create all required project directories.

    Raises:
        OSError: If a directory cannot be created.
    """
    for directory in REQUIRED_DIRECTORIES:
        directory.mkdir(parents=True, exist_ok=True)

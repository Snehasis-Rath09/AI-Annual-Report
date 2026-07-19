"""OCR extraction utilities for scanned annual report PDFs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from config.settings import OCR_CONFIG
from src.utils.file_utils import get_file_size_mb
from src.utils.logger import get_logger


logger = get_logger(__name__)


class OCRExtractionError(RuntimeError):
    """Raised when OCR extraction cannot be completed."""


@dataclass(frozen=True)
class OCRPageResult:
    """Text extracted from a single OCR page.

    Attributes:
        page_number: One-based PDF page number.
        text: Extracted page text.
        character_count: Number of non-whitespace characters extracted.
    """

    page_number: int
    text: str
    character_count: int


class OCRExtractor:
    """Extract text from scanned PDF pages using pdf2image and pytesseract."""

    def __init__(
        self,
        language: str | None = None,
        dpi: int | None = None,
        timeout_seconds: int | None = None,
    ) -> None:
        """Initialize the OCR extractor.

        Args:
            language: Tesseract language code. Defaults to settings.
            dpi: Image conversion DPI. Defaults to settings.
            timeout_seconds: OCR timeout per page in seconds. Defaults to settings.
        """
        self.language = language or str(OCR_CONFIG["language"])
        self.dpi = dpi or int(OCR_CONFIG["dpi"])
        self.timeout_seconds = timeout_seconds or int(OCR_CONFIG["timeout_seconds"])

    @staticmethod
    def _load_pdf2image() -> Any:
        """Load pdf2image at runtime.

        Returns:
            The ``convert_from_path`` callable.

        Raises:
            OCRExtractionError: If pdf2image is unavailable.
        """
        try:
            from pdf2image import convert_from_path
        except ImportError as exc:
            message = "pdf2image is required for OCR extraction."
            logger.exception(message)
            raise OCRExtractionError(message) from exc

        return convert_from_path

    @staticmethod
    def _load_pytesseract() -> Any:
        """Load pytesseract at runtime.

        Returns:
            The pytesseract module.

        Raises:
            OCRExtractionError: If pytesseract is unavailable.
        """
        try:
            import pytesseract
        except ImportError as exc:
            message = "pytesseract is required for OCR extraction."
            logger.exception(message)
            raise OCRExtractionError(message) from exc

        return pytesseract

    @staticmethod
    def _normalize_text(text: str) -> str:
        """Normalize OCR text line endings and surrounding whitespace.

        Args:
            text: Raw OCR text.

        Returns:
            Normalized text.
        """
        return text.replace("\r\n", "\n").replace("\r", "\n").strip()

    def image_to_text(self, image: Any, page_number: int | None = None) -> str:
        """Extract text from a single image with pytesseract.

        Args:
            image: PIL image object.
            page_number: Optional page number for logging.

        Returns:
            Extracted text.

        Raises:
            OCRExtractionError: If pytesseract fails.
        """
        pytesseract = self._load_pytesseract()
        page_label = page_number if page_number is not None else "unknown"

        try:
            logger.info("Running OCR for page %s.", page_label)
            text = pytesseract.image_to_string(
                image,
                lang=self.language,
                timeout=self.timeout_seconds,
            )
        except RuntimeError as exc:
            message = f"OCR timed out or failed for page {page_label}."
            logger.exception(message)
            raise OCRExtractionError(message) from exc
        except Exception as exc:
            message = f"Unexpected OCR failure for page {page_label}."
            logger.exception(message)
            raise OCRExtractionError(message) from exc

        return self._normalize_text(text)

    def extract_page(self, pdf_path: str | Path, page_number: int) -> OCRPageResult:
        """Extract OCR text from a single PDF page.

        Args:
            pdf_path: Source PDF path.
            page_number: One-based page number.

        Returns:
            OCR page result.

        Raises:
            FileNotFoundError: If the PDF does not exist.
            ValueError: If the page number is invalid.
            OCRExtractionError: If conversion or OCR fails.
        """
        path = Path(pdf_path).expanduser().resolve()
        if not path.is_file():
            logger.error("PDF file does not exist. Path: %s", path)
            raise FileNotFoundError(f"PDF file does not exist. Path: {path}")
        if page_number < 1:
            raise ValueError("page_number must be one or greater.")

        convert_from_path = self._load_pdf2image()

        with TemporaryDirectory(prefix="ai_annual_report_ocr_") as temp_dir:
            try:
                logger.info(
                    "Converting PDF page %s to image at %s DPI. Path: %s",
                    page_number,
                    self.dpi,
                    path,
                )
                images = convert_from_path(
                    pdf_path=str(path),
                    dpi=self.dpi,
                    first_page=page_number,
                    last_page=page_number,
                    output_folder=temp_dir,
                    fmt="png",
                    thread_count=1,
                )
            except Exception as exc:
                message = f"Failed to convert PDF page {page_number} to image."
                logger.exception("%s Path: %s", message, path)
                raise OCRExtractionError(message) from exc

            if not images:
                message = f"No image was generated for PDF page {page_number}."
                logger.error("%s Path: %s", message, path)
                raise OCRExtractionError(message)

            text = self.image_to_text(images[0], page_number=page_number)

        return OCRPageResult(
            page_number=page_number,
            text=text,
            character_count=len(text.strip()),
        )

    def extract(
        self,
        pdf_path: str | Path,
        start_page: int = 1,
        end_page: int | None = None,
    ) -> str:
        """Extract OCR text from a PDF.

        Args:
            pdf_path: Source PDF path.
            start_page: One-based first page to process.
            end_page: Optional one-based final page to process.

        Returns:
            Combined OCR text in page order.

        Raises:
            FileNotFoundError: If the PDF does not exist.
            ValueError: If the page range is invalid.
            OCRExtractionError: If OCR cannot be completed.
        """
        path = Path(pdf_path).expanduser().resolve()
        if not path.is_file():
            logger.error("PDF file does not exist. Path: %s", path)
            raise FileNotFoundError(f"PDF file does not exist. Path: {path}")
        if start_page < 1:
            raise ValueError("start_page must be one or greater.")
        if end_page is not None and end_page < start_page:
            raise ValueError("end_page must be greater than or equal to start_page.")

        logger.info(
            "Starting OCR extraction. Path: %s | Size MB: %.3f | Start: %s | End: %s",
            path,
            get_file_size_mb(path),
            start_page,
            end_page,
        )

        convert_from_path = self._load_pdf2image()
        page_texts: list[str] = []

        with TemporaryDirectory(prefix="ai_annual_report_ocr_") as temp_dir:
            try:
                images = convert_from_path(
                    pdf_path=str(path),
                    dpi=self.dpi,
                    first_page=start_page,
                    last_page=end_page,
                    output_folder=temp_dir,
                    fmt="png",
                    thread_count=1,
                )
            except Exception as exc:
                message = "Failed to convert PDF pages to images."
                logger.exception("%s Path: %s", message, path)
                raise OCRExtractionError(message) from exc

            logger.info(
                "Converted %s page image(s) for OCR. Path: %s",
                len(images),
                path,
            )

            for offset, image in enumerate(images):
                page_number = start_page + offset
                try:
                    text = self.image_to_text(image, page_number=page_number)
                except OCRExtractionError:
                    logger.warning(
                        "Skipping page %s because OCR failed. Path: %s",
                        page_number,
                        path,
                    )
                    continue

                if text.strip():
                    page_texts.append(text)

        combined_text = "\n\n".join(page_texts).strip()
        if not combined_text:
            message = "OCR completed but no text was extracted."
            logger.error("%s Path: %s", message, path)
            raise OCRExtractionError(message)

        logger.info(
            "Completed OCR extraction. Path: %s | Characters: %s",
            path,
            len(combined_text),
        )
        return combined_text

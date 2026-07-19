"""PDF text extraction for annual report disclosures."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config.settings import PDF_EXTRACTION_CONFIG
from src.extraction.ocr_extractor import OCRExtractionError, OCRExtractor
from src.utils.file_utils import get_file_size_mb, write_text_file
from src.utils.logger import get_logger


logger = get_logger(__name__)


class PDFExtractionError(RuntimeError):
    """Raised when PDF text extraction fails."""


class PDFValidationError(RuntimeError):
    """Raised when a PDF is invalid, encrypted, or corrupted."""


@dataclass(frozen=True)
class PDFValidationResult:
    """Validation status for a PDF.

    Attributes:
        is_valid: Whether the PDF can be read.
        is_encrypted: Whether the PDF requires a password.
        is_corrupted: Whether the PDF appears corrupted or unreadable.
        page_count: Number of pages detected.
        message: Human-readable validation message.
    """

    is_valid: bool
    is_encrypted: bool
    is_corrupted: bool
    page_count: int
    message: str


@dataclass(frozen=True)
class PDFPageText:
    """Text extracted from a single PDF page.

    Attributes:
        page_number: One-based page number.
        text: Extracted text.
        parser: Parser that produced the text.
    """

    page_number: int
    text: str
    parser: str


class PDFExtractor:
    """Extract text from PDFs using PyMuPDF, pdfplumber, and OCR fallback."""

    def __init__(
        self,
        use_ocr_fallback: bool | None = None,
        min_text_length: int | None = None,
        min_page_text_length: int | None = None,
        empty_page_ratio_threshold: float = 0.60,
        ocr_extractor: OCRExtractor | None = None,
    ) -> None:
        """Initialize the PDF extractor.

        Args:
            use_ocr_fallback: Whether OCR should be used for scanned PDFs.
            min_text_length: Minimum total characters before treating as scanned.
            min_page_text_length: Minimum page characters before page is empty.
            empty_page_ratio_threshold: Empty-page ratio that indicates scanning.
            ocr_extractor: Optional OCR extractor instance.
        """
        self.use_ocr_fallback = (
            bool(PDF_EXTRACTION_CONFIG["use_ocr_fallback"])
            if use_ocr_fallback is None
            else use_ocr_fallback
        )
        self.min_text_length = (
            int(PDF_EXTRACTION_CONFIG["min_page_text_length"]) * 10
            if min_text_length is None
            else min_text_length
        )
        self.min_page_text_length = (
            int(PDF_EXTRACTION_CONFIG["min_page_text_length"])
            if min_page_text_length is None
            else min_page_text_length
        )
        self.empty_page_ratio_threshold = empty_page_ratio_threshold
        self.ocr_extractor = ocr_extractor or OCRExtractor()

    @staticmethod
    def _load_fitz() -> Any:
        """Load PyMuPDF at runtime.

        Returns:
            The fitz module.

        Raises:
            PDFExtractionError: If PyMuPDF is unavailable.
        """
        try:
            import fitz
        except ImportError as exc:
            message = "PyMuPDF (fitz) is required for primary PDF extraction."
            logger.exception(message)
            raise PDFExtractionError(message) from exc

        return fitz

    @staticmethod
    def _load_pdfplumber() -> Any:
        """Load pdfplumber at runtime.

        Returns:
            The pdfplumber module.

        Raises:
            PDFExtractionError: If pdfplumber is unavailable.
        """
        try:
            import pdfplumber
        except ImportError as exc:
            message = "pdfplumber is required for secondary PDF extraction."
            logger.exception(message)
            raise PDFExtractionError(message) from exc

        return pdfplumber

    @staticmethod
    def _normalize_text(text: str) -> str:
        """Normalize line endings and trim extracted text.

        Args:
            text: Raw extracted text.

        Returns:
            Normalized text.
        """
        return text.replace("\r\n", "\n").replace("\r", "\n").strip()

    @staticmethod
    def _validate_path(pdf_path: str | Path) -> Path:
        """Validate and resolve a PDF path.

        Args:
            pdf_path: Input PDF path.

        Returns:
            Resolved PDF path.

        Raises:
            FileNotFoundError: If the PDF does not exist.
            ValueError: If the file is not a PDF.
        """
        path = Path(pdf_path).expanduser().resolve()
        if not path.is_file():
            logger.error("PDF file does not exist. Path: %s", path)
            raise FileNotFoundError(f"PDF file does not exist. Path: {path}")
        if path.suffix.lower() != ".pdf":
            logger.error(
                "Unsupported file extension for PDF extraction. Path: %s",
                path,
            )
            raise ValueError(f"Expected a .pdf file. Path: {path}")
        return path

    def validate_pdf(self, pdf_path: str | Path) -> PDFValidationResult:
        """Validate whether a PDF can be opened and read safely.

        Args:
            pdf_path: Source PDF path.

        Returns:
            PDF validation result.
        """
        path = self._validate_path(pdf_path)
        fitz = self._load_fitz()

        try:
            with fitz.open(path) as document:
                page_count = int(document.page_count)
                is_encrypted = bool(document.needs_pass)

                if is_encrypted:
                    logger.warning("Encrypted PDF detected. Path: %s", path)
                    return PDFValidationResult(
                        is_valid=False,
                        is_encrypted=True,
                        is_corrupted=False,
                        page_count=page_count,
                        message="PDF is encrypted and requires a password.",
                    )

                if page_count <= 0:
                    logger.warning("PDF has no pages. Path: %s", path)
                    return PDFValidationResult(
                        is_valid=False,
                        is_encrypted=False,
                        is_corrupted=True,
                        page_count=0,
                        message="PDF has no pages.",
                    )

        except Exception as exc:
            logger.exception("Corrupted or unreadable PDF detected. Path: %s", path)
            return PDFValidationResult(
                is_valid=False,
                is_encrypted=False,
                is_corrupted=True,
                page_count=0,
                message=f"PDF could not be opened: {exc}",
            )

        return PDFValidationResult(
            is_valid=True,
            is_encrypted=False,
            is_corrupted=False,
            page_count=page_count,
            message="PDF is valid.",
        )

    def get_page_count(self, pdf_path: str | Path) -> int:
        """Return the number of pages in a PDF.

        Args:
            pdf_path: Source PDF path.

        Returns:
            Page count.

        Raises:
            PDFValidationError: If the PDF is invalid.
        """
        validation = self.validate_pdf(pdf_path)
        if not validation.is_valid:
            raise PDFValidationError(validation.message)
        return validation.page_count

    def _extract_page_with_pymupdf(self, path: Path, page_number: int) -> PDFPageText:
        """Extract one page using PyMuPDF.

        Args:
            path: Source PDF path.
            page_number: One-based page number.

        Returns:
            Extracted page text.

        Raises:
            PDFExtractionError: If PyMuPDF extraction fails.
        """
        fitz = self._load_fitz()
        try:
            with fitz.open(path) as document:
                if page_number < 1 or page_number > document.page_count:
                    raise ValueError(
                        f"page_number must be between 1 and {document.page_count}."
                    )
                page = document.load_page(page_number - 1)
                text = page.get_text("text")
        except ValueError:
            raise
        except Exception as exc:
            message = f"PyMuPDF extraction failed for page {page_number}."
            logger.exception("%s Path: %s", message, path)
            raise PDFExtractionError(message) from exc

        return PDFPageText(
            page_number=page_number,
            text=self._normalize_text(text),
            parser="pymupdf",
        )

    def _extract_page_with_pdfplumber(
        self,
        path: Path,
        page_number: int,
    ) -> PDFPageText:
        """Extract one page using pdfplumber.

        Args:
            path: Source PDF path.
            page_number: One-based page number.

        Returns:
            Extracted page text.

        Raises:
            PDFExtractionError: If pdfplumber extraction fails.
        """
        pdfplumber = self._load_pdfplumber()
        try:
            with pdfplumber.open(path) as pdf:
                if page_number < 1 or page_number > len(pdf.pages):
                    raise ValueError(
                        f"page_number must be between 1 and {len(pdf.pages)}.",
                    )
                text = pdf.pages[page_number - 1].extract_text() or ""
        except ValueError:
            raise
        except Exception as exc:
            message = f"pdfplumber extraction failed for page {page_number}."
            logger.exception("%s Path: %s", message, path)
            raise PDFExtractionError(message) from exc

        return PDFPageText(
            page_number=page_number,
            text=self._normalize_text(text),
            parser="pdfplumber",
        )

    def extract_page(self, pdf_path: str | Path, page_number: int) -> str:
        """Extract text from a single PDF page.

        Args:
            pdf_path: Source PDF path.
            page_number: One-based page number.

        Returns:
            Extracted page text.

        Raises:
            PDFValidationError: If the PDF is invalid.
            PDFExtractionError: If both parsers fail.
        """
        path = self._validate_path(pdf_path)
        validation = self.validate_pdf(path)
        if not validation.is_valid:
            raise PDFValidationError(validation.message)

        try:
            page_text = self._extract_page_with_pymupdf(path, page_number)
            logger.info("Extracted page %s with PyMuPDF. Path: %s", page_number, path)
            return page_text.text
        except Exception as pymupdf_error:
            logger.warning(
                "PyMuPDF failed for page %s; trying pdfplumber. Path: %s",
                page_number,
                path,
            )
            try:
                page_text = self._extract_page_with_pdfplumber(path, page_number)
                logger.info(
                    "Extracted page %s with pdfplumber. Path: %s",
                    page_number,
                    path,
                )
                return page_text.text
            except Exception as pdfplumber_error:
                message = f"All PDF parsers failed for page {page_number}."
                raise PDFExtractionError(message) from pdfplumber_error or pymupdf_error

    def _extract_all_with_pymupdf(self, path: Path) -> list[PDFPageText]:
        """Extract all pages using PyMuPDF.

        Args:
            path: Source PDF path.

        Returns:
            Page text results.

        Raises:
            PDFExtractionError: If extraction fails.
        """
        fitz = self._load_fitz()
        pages: list[PDFPageText] = []

        try:
            with fitz.open(path) as document:
                for index in range(document.page_count):
                    raw_text = document.load_page(index).get_text("text")
                    text = self._normalize_text(raw_text)
                    pages.append(
                        PDFPageText(
                            page_number=index + 1,
                            text=text,
                            parser="pymupdf",
                        )
                    )
        except Exception as exc:
            message = "PyMuPDF extraction failed for the PDF."
            logger.exception("%s Path: %s", message, path)
            raise PDFExtractionError(message) from exc

        return pages

    def _extract_all_with_pdfplumber(self, path: Path) -> list[PDFPageText]:
        """Extract all pages using pdfplumber.

        Args:
            path: Source PDF path.

        Returns:
            Page text results.

        Raises:
            PDFExtractionError: If extraction fails.
        """
        pdfplumber = self._load_pdfplumber()
        pages: list[PDFPageText] = []

        try:
            with pdfplumber.open(path) as pdf:
                for index, page in enumerate(pdf.pages):
                    text = self._normalize_text(page.extract_text() or "")
                    pages.append(
                        PDFPageText(
                            page_number=index + 1,
                            text=text,
                            parser="pdfplumber",
                        )
                    )
        except Exception as exc:
            message = "pdfplumber extraction failed for the PDF."
            logger.exception("%s Path: %s", message, path)
            raise PDFExtractionError(message) from exc

        return pages

    def is_scanned_pdf(self, pdf_path: str | Path) -> bool:
        """Detect whether a PDF is likely scanned.

        The detection uses native extraction results: very little extracted text
        or a high ratio of empty pages indicates a scanned PDF.

        Args:
            pdf_path: Source PDF path.

        Returns:
            True when the PDF is likely scanned.

        Raises:
            PDFValidationError: If the PDF is invalid.
        """
        path = self._validate_path(pdf_path)
        validation = self.validate_pdf(path)
        if not validation.is_valid:
            raise PDFValidationError(validation.message)

        try:
            pages = self._extract_all_with_pymupdf(path)
        except PDFExtractionError:
            pages = self._extract_all_with_pdfplumber(path)

        return self._pages_indicate_scanned_pdf(pages)

    def _pages_indicate_scanned_pdf(self, pages: list[PDFPageText]) -> bool:
        """Evaluate native page text to infer scanned-document status.

        Args:
            pages: Page extraction results.

        Returns:
            True if native text is too sparse.
        """
        if not pages:
            return True

        character_count = sum(len(page.text.strip()) for page in pages)
        empty_pages = sum(
            1 for page in pages if len(page.text.strip()) < self.min_page_text_length
        )
        empty_ratio = empty_pages / len(pages)

        logger.info(
            "Scanned PDF check: characters=%s empty_pages=%s total_pages=%s ratio=%.2f",
            character_count,
            empty_pages,
            len(pages),
            empty_ratio,
        )

        return (
            character_count < self.min_text_length
            or empty_ratio >= self.empty_page_ratio_threshold
        )

    def extract_text(self, pdf_path: str | Path) -> str:
        """Extract complete PDF text in page order.

        PyMuPDF is used first. If it fails, pdfplumber is used. If native text is
        too sparse, OCR is automatically used when enabled.

        Args:
            pdf_path: Source PDF path.

        Returns:
            Combined extracted text.

        Raises:
            PDFValidationError: If the PDF is invalid or encrypted.
            PDFExtractionError: If extraction fails.
        """
        path = self._validate_path(pdf_path)
        validation = self.validate_pdf(path)
        if not validation.is_valid:
            logger.error(
                "PDF validation failed. Path: %s | %s",
                path,
                validation.message,
            )
            raise PDFValidationError(validation.message)

        logger.info(
            "Starting PDF extraction. Path: %s | Pages: %s | Size MB: %.3f",
            path,
            validation.page_count,
            get_file_size_mb(path),
        )

        parser_name = "pymupdf"
        try:
            pages = self._extract_all_with_pymupdf(path)
        except PDFExtractionError:
            logger.warning("PyMuPDF failed; falling back to pdfplumber. Path: %s", path)
            parser_name = "pdfplumber"
            pages = self._extract_all_with_pdfplumber(path)

        is_scanned = self._pages_indicate_scanned_pdf(pages)
        if is_scanned and self.use_ocr_fallback:
            logger.info("PDF appears scanned; starting OCR fallback. Path: %s", path)
            try:
                return self.ocr_extractor.extract(path)
            except OCRExtractionError as exc:
                native_text = self._combine_pages(pages)
                if native_text:
                    logger.warning(
                        "OCR failed; returning sparse native text. Path: %s",
                        path,
                    )
                    return native_text
                raise PDFExtractionError(
                    "OCR fallback failed for scanned PDF.",
                ) from exc

        combined_text = self._combine_pages(pages)
        if not combined_text:
            message = "PDF extraction completed but no text was extracted."
            logger.error("%s Path: %s", message, path)
            raise PDFExtractionError(message)

        logger.info(
            "Completed PDF extraction with %s. Path: %s | Characters: %s",
            parser_name,
            path,
            len(combined_text),
        )
        return combined_text

    @staticmethod
    def _combine_pages(pages: list[PDFPageText]) -> str:
        """Combine non-blank page text while preserving order.

        Args:
            pages: Page extraction results.

        Returns:
            Combined text.
        """
        ordered_pages = sorted(pages, key=lambda page: page.page_number)
        return "\n\n".join(
            page.text for page in ordered_pages if page.text.strip()
        ).strip()

    def save_text(
        self,
        pdf_path: str | Path,
        output_path: str | Path,
        overwrite: bool = True,
    ) -> Path:
        """Extract text from a PDF and save it to disk.

        Args:
            pdf_path: Source PDF path.
            output_path: Destination text file path.
            overwrite: Whether an existing output file may be replaced.

        Returns:
            Resolved output path.

        Raises:
            PDFValidationError: If the PDF is invalid.
            PDFExtractionError: If extraction fails.
            OSError: If writing fails.
        """
        text = self.extract_text(pdf_path)
        saved_path = write_text_file(output_path, text, overwrite=overwrite)
        logger.info("Saved extracted PDF text. Path: %s", saved_path)
        return saved_path

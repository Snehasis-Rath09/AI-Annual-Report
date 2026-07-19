"""Text cleaning utilities for extracted annual report text."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

try:  # Prefer the third-party regex engine when available.
    import regex as re
except ImportError:  # pragma: no cover - stdlib fallback.
    import re  # type: ignore[no-redef]

from config.settings import PDF_EXTRACTION_CONFIG, SUPPORTED_REPORT_HEADINGS
from src.utils.logger import get_logger


logger = get_logger(__name__)


@dataclass(frozen=True)
class TextCleanerConfig:
    """Configuration for annual report text cleaning."""

    min_repeated_line_occurrences: int = 3
    repeated_line_ratio: float = 0.35
    max_repeated_line_length: int = 120
    max_header_footer_lines: int = 3
    remove_headers_footers: bool = bool(
        PDF_EXTRACTION_CONFIG.get("remove_headers_footers", True),
    )


class TextCleaner:
    """Clean noisy raw text extracted from annual report PDFs.

    The cleaner removes common PDF extraction artifacts while preserving
    paragraphs, section headings, punctuation, numbers, and wording needed by
    downstream section extraction and keyword analysis.
    """

    _PAGE_BREAK_PATTERN = re.compile(
        r"\f|\n\s*[-–—]*\s*page\s+break\s*[-–—]*\s*\n",
        re.I,
    )
    _PAGE_NUMBER_PATTERN = re.compile(
        r"^\s*(?:page\s*)?(?:\d{1,4}|[ivxlcdm]{1,12})"
        r"(?:\s*(?:of|/|-)\s*(?:\d{1,4}|[ivxlcdm]{1,12}))?\s*$",
        re.I,
    )
    _TOC_TITLE_PATTERN = re.compile(
        r"^\s*(?:table\s+of\s+contents|contents|index)\s*$",
        re.I,
    )
    _TOC_ENTRY_PATTERN = re.compile(
        r"^\s*.{2,120}?(?:\.{2,}|\s{2,})\s*\d{1,4}\s*$",
    )
    _NON_PRINTABLE_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
    _SPECIAL_CHARACTER_PATTERN = re.compile(
        r"[^\S\r\n]+|[^\w\s.,;:!?%&@(){}\[\]/\\+\-=*'\"`₹$€£#<>|^~–—-]",
        re.UNICODE,
    )
    _MULTIPLE_BLANK_LINES_PATTERN = re.compile(r"\n{3,}")
    _MULTIPLE_SPACES_PATTERN = re.compile(r"[ ]{2,}")
    _TAB_PATTERN = re.compile(r"\t+")
    _COMPANY_SUFFIX_PATTERN = re.compile(
        r"\b(?:limited|ltd|private|pvt|plc|inc|corp|corporation|"
        r"company|co\.?)\b\.?$",
        re.I,
    )

    def __init__(self, config: TextCleanerConfig | None = None) -> None:
        """Initialize a text cleaner.

        Args:
            config: Optional cleaning configuration.
        """
        self.config = config or TextCleanerConfig()
        self.section_headings = tuple(SUPPORTED_REPORT_HEADINGS)

    def clean(self, text: str | None) -> str:
        """Run the complete cleaning pipeline.

        Args:
            text: Raw extracted text.

        Returns:
            Cleaned text.
        """
        if not text:
            return ""

        original_length = len(text)
        logger.info("Cleaning started")

        try:
            cleaned_text = str(text)
            cleaned_text = self.remove_extra_tabs(cleaned_text)
            cleaned_text = self.remove_table_of_contents_if_present(cleaned_text)

            if self.config.remove_headers_footers:
                cleaned_text = self.remove_headers(cleaned_text)
                cleaned_text = self.remove_footers(cleaned_text)

            cleaned_text = self.remove_page_numbers(cleaned_text)
            cleaned_text = self.remove_repeated_headers(cleaned_text)
            cleaned_text = self.remove_duplicate_lines(cleaned_text)
            cleaned_text = self.remove_special_characters(cleaned_text)
            cleaned_text = self.remove_non_printable_characters(cleaned_text)
            cleaned_text = self.remove_multiple_spaces(cleaned_text)
            cleaned_text = self.remove_multiple_blank_lines(cleaned_text)
            cleaned_text = cleaned_text.strip()

            characters_removed = original_length - len(cleaned_text)
            logger.info("Characters removed: %s", max(characters_removed, 0))
            logger.info("Cleaning completed")
            return cleaned_text
        except Exception as exc:
            logger.exception("Errors encountered during cleaning: %s", exc)
            raise

    def clean_file(self, source_path: str | Path) -> str:
        """Read and clean a UTF-8 text file.

        Args:
            source_path: Path to the extracted text file.

        Returns:
            Cleaned text.
        """
        path = Path(source_path)
        return self.clean(path.read_text(encoding="utf-8", errors="ignore"))

    def remove_headers(self, text: str) -> str:
        """Remove repeated page header lines.

        Args:
            text: Text to clean.

        Returns:
            Text without repeated header candidates.
        """
        pages = self._split_pages(text)
        if len(pages) < 2:
            return text

        repeated_headers = self._find_repeated_edge_lines(pages, at_start=True)
        return self._remove_lines(text, repeated_headers)

    def remove_footers(self, text: str) -> str:
        """Remove repeated page footer lines.

        Args:
            text: Text to clean.

        Returns:
            Text without repeated footer candidates.
        """
        pages = self._split_pages(text)
        if len(pages) < 2:
            return text

        repeated_footers = self._find_repeated_edge_lines(pages, at_start=False)
        return self._remove_lines(text, repeated_footers)

    def remove_page_numbers(self, text: str) -> str:
        """Remove standalone page numbers and page count markers.

        Args:
            text: Text to clean.

        Returns:
            Text without standalone page numbers.
        """
        lines = [
            line
            for line in text.splitlines()
            if not self._PAGE_NUMBER_PATTERN.fullmatch(line.strip())
        ]
        return "\n".join(lines)

    def remove_multiple_blank_lines(self, text: str) -> str:
        """Collapse excessive blank lines while preserving paragraphs."""
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        return self._MULTIPLE_BLANK_LINES_PATTERN.sub("\n\n", normalized)

    def remove_multiple_spaces(self, text: str) -> str:
        """Collapse repeated spaces within each line."""
        return "\n".join(
            self._MULTIPLE_SPACES_PATTERN.sub(" ", line).strip()
            for line in text.splitlines()
        )

    def remove_special_characters(self, text: str) -> str:
        """Remove noisy symbols while preserving meaningful punctuation."""
        cleaned_lines: list[str] = []
        for line in text.splitlines():
            line = self._SPECIAL_CHARACTER_PATTERN.sub(
                lambda match: " " if match.group(0).strip() else match.group(0),
                line,
            )
            cleaned_lines.append(line)
        return "\n".join(cleaned_lines)

    def remove_non_printable_characters(self, text: str) -> str:
        """Remove non-printable control characters except newlines and tabs."""
        return self._NON_PRINTABLE_PATTERN.sub("", text)

    def remove_extra_tabs(self, text: str) -> str:
        """Convert tabs to single spaces."""
        return self._TAB_PATTERN.sub(" ", text)

    def remove_duplicate_lines(self, text: str) -> str:
        """Remove consecutive duplicate non-heading lines."""
        cleaned_lines: list[str] = []
        previous_key = ""

        for line in text.splitlines():
            key = self._canonical_line(line)
            if key and key == previous_key and not self._is_section_heading(line):
                continue
            cleaned_lines.append(line)
            previous_key = key

        return "\n".join(cleaned_lines)

    def remove_repeated_headers(self, text: str) -> str:
        """Remove lines that recur often enough to be page furniture."""
        lines = text.splitlines()
        non_empty_keys = [
            self._canonical_line(line)
            for line in lines
            if self._is_repeated_line_candidate(line)
        ]
        counts = Counter(key for key in non_empty_keys if key)
        if not counts:
            return text

        threshold = max(
            self.config.min_repeated_line_occurrences,
            int(len(self._split_pages(text)) * self.config.repeated_line_ratio),
        )
        repeated_keys = {key for key, count in counts.items() if count >= threshold}

        cleaned_lines = [
            line
            for line in lines
            if self._canonical_line(line) not in repeated_keys
            or self._is_section_heading(line)
        ]
        return "\n".join(cleaned_lines)

    def remove_table_of_contents_if_present(self, text: str) -> str:
        """Remove a table of contents block near the beginning of the report."""
        lines = text.splitlines()
        search_limit = min(len(lines), 250)

        for index in range(search_limit):
            if not self._TOC_TITLE_PATTERN.fullmatch(lines[index].strip()):
                continue

            end_index = self._find_toc_end(lines, index)
            if end_index > index:
                return "\n".join([*lines[:index], *lines[end_index:]])

        return text

    def _split_pages(self, text: str) -> list[str]:
        """Split text into likely page chunks."""
        pages = [page for page in self._PAGE_BREAK_PATTERN.split(text) if page.strip()]
        if len(pages) > 1:
            return pages

        marker_pattern = re.compile(r"\n\s*(?:page\s+)?\d{1,4}\s*\n", re.I)
        return [page for page in marker_pattern.split(text) if page.strip()]

    def _find_repeated_edge_lines(self, pages: list[str], at_start: bool) -> set[str]:
        """Find repeated lines at page starts or ends."""
        candidates: list[str] = []

        for page in pages:
            page_lines = [line for line in page.splitlines() if line.strip()]
            if not page_lines:
                continue

            edge_lines = (
                page_lines[: self.config.max_header_footer_lines]
                if at_start
                else page_lines[-self.config.max_header_footer_lines :]
            )
            candidates.extend(
                self._canonical_line(line)
                for line in edge_lines
                if self._is_repeated_line_candidate(line)
            )

        counts = Counter(candidate for candidate in candidates if candidate)
        threshold = max(
            self.config.min_repeated_line_occurrences,
            int(len(pages) * self.config.repeated_line_ratio),
        )
        return {line for line, count in counts.items() if count >= threshold}

    def _find_toc_end(self, lines: list[str], start_index: int) -> int:
        """Find the end of a likely table of contents block."""
        toc_entries = 0
        last_toc_index = start_index + 1
        blank_run = 0

        for index in range(start_index + 1, min(len(lines), start_index + 180)):
            stripped = lines[index].strip()

            if not stripped:
                blank_run += 1
                if blank_run >= 2 and toc_entries >= 3:
                    return index + 1
                continue

            blank_run = 0
            if self._TOC_ENTRY_PATTERN.match(stripped):
                toc_entries += 1
                last_toc_index = index + 1
                continue

            if toc_entries >= 3:
                return last_toc_index

        return last_toc_index if toc_entries >= 3 else start_index

    def _remove_lines(self, text: str, canonical_lines: Iterable[str]) -> str:
        """Remove lines matching canonical line values."""
        removable = set(canonical_lines)
        if not removable:
            return text

        return "\n".join(
            line
            for line in text.splitlines()
            if self._canonical_line(line) not in removable
            or self._is_section_heading(line)
        )

    def _is_repeated_line_candidate(self, line: str) -> bool:
        """Return whether a line is a safe candidate for repeated-noise removal."""
        stripped = line.strip()
        if not stripped or self._is_section_heading(stripped):
            return False

        has_alpha = bool(re.search(r"[A-Za-z]", stripped))
        return has_alpha and len(stripped) <= self.config.max_repeated_line_length

    def _is_section_heading(self, line: str) -> bool:
        """Return whether a line looks like a meaningful section heading."""
        stripped = line.strip()
        if not stripped:
            return False
        if self._COMPANY_SUFFIX_PATTERN.search(stripped):
            return False

        lowered = stripped.casefold().strip(":")
        supported = {heading.casefold() for heading in self.section_headings}
        if lowered in supported:
            return True

        if len(stripped) > 120 or stripped.endswith((".", ",", ";")):
            return False

        words = re.findall(r"[A-Za-z&']+", stripped)
        if not words:
            return False

        title_like = sum(word[:1].isupper() or word.isupper() for word in words)
        return title_like >= max(1, int(len(words) * 0.7))

    @staticmethod
    def _canonical_line(line: str) -> str:
        """Canonicalize a line for duplicate and repetition checks."""
        return re.sub(r"\s+", " ", line).strip().casefold()

"""Text normalization utilities for cleaned annual report text."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

try:  # Prefer the third-party regex engine when available.
    import regex as re
except ImportError:  # pragma: no cover - stdlib fallback.
    import re  # type: ignore[no-redef]

from config.settings import SUPPORTED_REPORT_HEADINGS
from src.utils.logger import get_logger


logger = get_logger(__name__)


@dataclass(frozen=True)
class TextNormalizerConfig:
    """Configuration for text normalization."""

    default_lowercase: bool = False
    known_acronyms: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {
                "AI",
                "ML",
                "ESG",
                "R&D",
                "RPA",
                "NLP",
                "IoT",
                "API",
                "IT",
                "CSR",
                "BRSR",
                "CEO",
                "CFO",
                "COO",
                "CTO",
            },
        ),
    )


class TextNormalizer:
    """Normalize cleaned annual report text for downstream processing."""

    _QUOTE_TRANSLATION = str.maketrans(
        {
            "\u2018": "'",
            "\u2019": "'",
            "\u201a": "'",
            "\u201b": "'",
            "\u2032": "'",
            "\u2035": "'",
            "\u201c": '"',
            "\u201d": '"',
            "\u201e": '"',
            "\u201f": '"',
            "\u2033": '"',
            "\u2036": '"',
        },
    )
    _HYPHEN_TRANSLATION = str.maketrans(
        {
            "\u2010": "-",
            "\u2011": "-",
            "\u2012": "-",
            "\u2013": "-",
            "\u2212": "-",
            "\u00ad": "",
            "\u2014": " - ",
            "\u2015": " - ",
        },
    )
    _BULLET_PATTERN = re.compile(r"^\s*[•●▪▫◦‣⁃]\s+", re.MULTILINE)
    _MULTIPLE_SPACES_PATTERN = re.compile(r"[^\S\r\n]{2,}")
    _MULTIPLE_BLANK_LINES_PATTERN = re.compile(r"\n{3,}")
    _HEADING_NUMBER_PATTERN = re.compile(
        r"^\s*(?P<number>(?:\d+|[A-Z])(?:[.)]\d+)*[.)]?)\s+"
        r"(?P<title>[A-Z][A-Za-z0-9&,\-/'() ]{2,120})\s*$",
    )
    _ACRONYM_PATTERN = re.compile(r"\b[A-Z][A-Z0-9]*(?:&[A-Z0-9]+)?\b")

    def __init__(self, config: TextNormalizerConfig | None = None) -> None:
        """Initialize a text normalizer.

        Args:
            config: Optional normalization configuration.
        """
        self.config = config or TextNormalizerConfig()
        self.section_headings = tuple(SUPPORTED_REPORT_HEADINGS)

    def normalize(self, text: str | None, lowercase: bool | None = None) -> str:
        """Run the complete normalization pipeline.

        Args:
            text: Cleaned annual report text.
            lowercase: Optional override for lowercasing.

        Returns:
            Normalized text.
        """
        if not text:
            return ""

        logger.info("Text normalization started")

        try:
            normalized_text = str(text)
            normalized_text = self.normalize_unicode(normalized_text)
            normalized_text = self.normalize_quotes(normalized_text)
            normalized_text = self.normalize_hyphens(normalized_text)
            normalized_text = self.normalize_bullets(normalized_text)
            normalized_text = self.normalize_newlines(normalized_text)
            normalized_text = self.normalize_spaces(normalized_text)
            normalized_text = self.normalize_headings(normalized_text)
            normalized_text = self.remove_duplicate_whitespace(normalized_text)

            should_lowercase = (
                self.config.default_lowercase if lowercase is None else lowercase
            )
            if should_lowercase:
                normalized_text = self.convert_to_lowercase(
                    normalized_text,
                    optional=True,
                )

            normalized_text = self.preserve_acronyms(normalized_text).strip()
            logger.info(
                "Sections normalized: %s",
                self._count_headings(normalized_text),
            )
            logger.info("Text normalization completed")
            return normalized_text
        except Exception as exc:
            logger.exception("Errors encountered during normalization: %s", exc)
            raise

    def normalize_file(self, source_path: str | Path) -> str:
        """Read and normalize a UTF-8 text file.

        Args:
            source_path: Path to a cleaned text file.

        Returns:
            Normalized text.
        """
        path = Path(source_path)
        return self.normalize(path.read_text(encoding="utf-8", errors="ignore"))

    def normalize_quotes(self, text: str) -> str:
        """Normalize curly quotes to straight quotes."""
        return text.translate(self._QUOTE_TRANSLATION)

    def normalize_hyphens(self, text: str) -> str:
        """Normalize dash and hyphen variants."""
        return text.translate(self._HYPHEN_TRANSLATION)

    def normalize_unicode(self, text: str) -> str:
        """Normalize Unicode compatibility forms."""
        return unicodedata.normalize("NFKC", text)

    def normalize_newlines(self, text: str) -> str:
        """Normalize newline style and paragraph spacing."""
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        normalized = re.sub(r"[ \t]+\n", "\n", normalized)
        return self._MULTIPLE_BLANK_LINES_PATTERN.sub("\n\n", normalized)

    def normalize_spaces(self, text: str) -> str:
        """Normalize repeated inline whitespace."""
        return "\n".join(
            self._MULTIPLE_SPACES_PATTERN.sub(" ", line).strip()
            for line in text.splitlines()
        )

    def normalize_bullets(self, text: str) -> str:
        """Normalize bullet symbols to hyphen bullets."""
        return self._BULLET_PATTERN.sub("- ", text)

    def normalize_headings(self, text: str) -> str:
        """Normalize heading whitespace and known heading capitalization."""
        normalized_lines: list[str] = []
        known_headings = {
            self._canonical_heading(heading): heading
            for heading in self.section_headings
        }

        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                normalized_lines.append("")
                continue

            canonical = self._canonical_heading(stripped)
            if canonical in known_headings:
                normalized_lines.append(known_headings[canonical])
                continue

            match = self._HEADING_NUMBER_PATTERN.match(stripped)
            if match and self._is_heading_like(match.group("title")):
                number = match.group("number").rstrip(".")
                title = self._normalize_heading_title(match.group("title"))
                normalized_lines.append(f"{number}. {title}")
                continue

            if self._is_heading_like(stripped):
                normalized_lines.append(self._normalize_heading_title(stripped))
                continue

            normalized_lines.append(stripped)

        return "\n".join(normalized_lines)

    def convert_to_lowercase(self, text: str, optional: bool = False) -> str:
        """Convert text to lowercase while preserving known acronyms.

        Args:
            text: Text to convert.
            optional: When False, return text unchanged.

        Returns:
            Lowercase text if requested, with acronyms restored.
        """
        if not optional:
            return text

        protected: dict[str, str] = {}

        def protect(match: re.Match[str]) -> str:
            value = match.group(0)
            if value in self.config.known_acronyms:
                token = f"__ACRONYM_{len(protected)}__"
                protected[token.lower()] = value
                return token
            return value

        protected_text = self._ACRONYM_PATTERN.sub(protect, text)
        lowered = protected_text.lower()

        for token, acronym in protected.items():
            lowered = lowered.replace(token, acronym)

        return lowered

    def preserve_acronyms(self, text: str) -> str:
        """Restore common acronym casing without changing other wording."""
        normalized_text = text
        for acronym in sorted(self.config.known_acronyms, key=len, reverse=True):
            pattern = re.compile(rf"(?<!\w){re.escape(acronym)}(?!\w)", re.I)
            normalized_text = pattern.sub(acronym, normalized_text)
        return normalized_text

    def remove_duplicate_whitespace(self, text: str) -> str:
        """Remove duplicate whitespace while preserving paragraph boundaries."""
        text = self.normalize_spaces(text)
        return self.normalize_newlines(text)

    def _normalize_heading_title(self, heading: str) -> str:
        """Normalize a heading while preserving acronyms and abbreviations."""
        return self.preserve_acronyms(heading).strip(" :")

    def _is_heading_like(self, line: str) -> bool:
        """Return whether a line resembles a section heading."""
        stripped = line.strip()
        if not stripped or len(stripped) > 120:
            return False
        if stripped.endswith((".", ",", ";")):
            return False

        words = re.findall(r"[A-Za-z&']+", stripped)
        if not words:
            return False

        known = {
            self._canonical_heading(heading) for heading in self.section_headings
        }
        if self._canonical_heading(stripped) in known:
            return True

        title_like = sum(word[:1].isupper() or word.isupper() for word in words)
        return title_like >= max(1, int(len(words) * 0.7))

    def _count_headings(self, text: str) -> int:
        """Count lines that look like normalized report section headings."""
        return sum(1 for line in text.splitlines() if self._is_heading_like(line))

    @staticmethod
    def _canonical_heading(value: str) -> str:
        """Canonicalize heading text for matching."""
        value = value.strip().strip(":")
        value = re.sub(r"\s+", " ", value)
        return value.casefold()

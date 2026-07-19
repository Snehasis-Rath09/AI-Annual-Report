"""Section extraction for annual report disclosure analysis."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

try:  # Prefer the third-party regex engine when available.
    import regex as re
except ImportError:  # pragma: no cover - stdlib fallback.
    import re  # type: ignore[no-redef]

from config.settings import SECTION_OUTPUT_DIR
from src.section_extraction.heading_detector import HeadingDetector, HeadingMatch
from src.utils.logger import get_logger


logger = get_logger(__name__)


@dataclass(frozen=True)
class SectionExtractorConfig:
    """Configuration for section extraction."""

    min_section_length: int = 40
    max_section_length: int | None = None
    include_heading_in_section: bool = True
    merge_separator: str = "\n\n"


@dataclass(frozen=True)
class ExtractedSection:
    """Metadata and text for one extracted section."""

    name: str
    text: str
    start_index: int
    end_index: int
    confidence_score: float
    source_heading: str


class SectionExtractor:
    """Extract disclosure sections from cleaned annual report text."""

    DEFAULT_TARGET_SECTIONS: tuple[str, ...] = (
        "MD&A",
        "Innovation",
        "Digital Transformation",
        "AI",
        "Machine Learning",
        "Automation",
        "Technology",
        "Patents",
        "Future Strategy",
        "Research & Development",
    )

    _WHITESPACE_PATTERN = re.compile(r"[ \t]+")
    _BLANK_LINES_PATTERN = re.compile(r"\n{3,}")

    def __init__(
        self,
        heading_detector: HeadingDetector | None = None,
        config: SectionExtractorConfig | None = None,
    ) -> None:
        """Initialize a section extractor.

        Args:
            heading_detector: Optional detector instance.
            config: Optional section extraction configuration.
        """
        self.heading_detector = heading_detector or HeadingDetector()
        self.config = config or SectionExtractorConfig()

    def extract_sections(
        self,
        text: str | None,
        target_sections: Iterable[str] | None = None,
    ) -> dict[str, str]:
        """Extract all requested disclosure sections.

        Args:
            text: Cleaned and normalized annual report text.
            target_sections: Optional canonical section names to extract.

        Returns:
            Mapping of section names to extracted section text.
        """
        if not text:
            logger.warning("Extraction skipped because text is empty")
            return {}

        logger.info("Extraction started")
        requested_sections = tuple(target_sections or self.DEFAULT_TARGET_SECTIONS)

        try:
            headings = self.heading_detector.find_heading_positions(text)
            logger.info("Detected headings: %s", len(headings))

            if not headings:
                logger.warning("No headings detected; no sections extracted")
                return {}

            extracted: list[ExtractedSection] = []
            ordered_headings = sorted(headings, key=lambda item: item.start_index)

            for index, heading in enumerate(ordered_headings):
                if heading.heading not in requested_sections:
                    continue

                next_heading = self._find_next_heading(ordered_headings, index)
                section = self.extract_single_section(text, heading, next_heading)
                if section is not None:
                    extracted.append(section)

            merged_sections = self.merge_duplicate_sections(extracted)
            cleaned_sections = self.remove_empty_sections(merged_sections)

            logger.info("Extracted section names: %s", list(cleaned_sections.keys()))
            for name, section_text in cleaned_sections.items():
                logger.info("Section length: %s | %s", name, len(section_text))

            return cleaned_sections
        except Exception as exc:
            logger.exception("Errors encountered during section extraction: %s", exc)
            raise

    def extract_single_section(
        self,
        text: str,
        heading: HeadingMatch,
        next_heading: HeadingMatch | None = None,
    ) -> ExtractedSection | None:
        """Extract text for a single heading until the next detected heading.

        Args:
            text: Full report text.
            heading: Heading that starts the section.
            next_heading: Next detected heading, if any.

        Returns:
            Extracted section with metadata, or None when empty.
        """
        start_index = (
            heading.start_index
            if self.config.include_heading_in_section
            else heading.end_index
        )
        end_index = next_heading.start_index if next_heading else len(text)

        if end_index <= start_index:
            logger.warning("Invalid section span for heading: %s", heading.heading)
            return None

        section_text = self._clean_section_text(text[start_index:end_index])
        if self.config.max_section_length is not None:
            section_text = section_text[: self.config.max_section_length].rstrip()

        if len(section_text) < self.config.min_section_length:
            logger.warning(
                "Skipping short section: %s | length=%s",
                heading.heading,
                len(section_text),
            )
            return None

        logger.info(
            "Extracted section: %s | confidence=%.3f | length=%s",
            heading.heading,
            heading.confidence_score,
            len(section_text),
        )
        return ExtractedSection(
            name=heading.heading,
            text=section_text,
            start_index=start_index,
            end_index=end_index,
            confidence_score=heading.confidence_score,
            source_heading=heading.source_text,
        )

    def extract_by_heading(self, text: str | None, heading_name: str) -> str:
        """Extract one section by canonical heading name or heading variation.

        Args:
            text: Cleaned and normalized annual report text.
            heading_name: Target heading name or variation.

        Returns:
            Extracted section text, or an empty string when not found.
        """
        if not text:
            return ""

        matched_heading = self.heading_detector.match_heading(heading_name)
        target = matched_heading.heading if matched_heading else heading_name
        sections = self.extract_sections(text, target_sections=(target,))
        return sections.get(target, "")

    def merge_duplicate_sections(
        self,
        sections: Iterable[ExtractedSection] | dict[str, str],
    ) -> dict[str, str]:
        """Merge repeated sections under the same canonical heading.

        Args:
            sections: Extracted section objects or an existing mapping.

        Returns:
            Mapping with duplicate section names merged.
        """
        if isinstance(sections, dict):
            return {
                name: self._clean_section_text(section_text)
                for name, section_text in sections.items()
            }

        merged: dict[str, list[str]] = {}
        for section in sections:
            if section.name not in merged:
                merged[section.name] = []
            if section.text not in merged[section.name]:
                merged[section.name].append(section.text)

        return {
            name: self.config.merge_separator.join(parts).strip()
            for name, parts in merged.items()
        }

    def remove_empty_sections(self, sections: dict[str, str]) -> dict[str, str]:
        """Remove empty or too-short extracted sections.

        Args:
            sections: Section mapping.

        Returns:
            Filtered section mapping.
        """
        filtered: dict[str, str] = {}
        for name, section_text in sections.items():
            cleaned_text = self._clean_section_text(section_text)
            if len(cleaned_text) < self.config.min_section_length:
                logger.warning(
                    "Removing empty or short section: %s | length=%s",
                    name,
                    len(cleaned_text),
                )
                continue
            filtered[name] = cleaned_text
        return filtered

    def save_sections(
        self,
        sections: dict[str, str],
        output_path: str | Path | None = None,
    ) -> Path:
        """Save extracted sections as UTF-8 JSON.

        Args:
            sections: Mapping of section names to text.
            output_path: Optional output JSON path. Defaults to project section
                output directory.

        Returns:
            Path to the saved JSON file.
        """
        destination = Path(output_path) if output_path else (
            SECTION_OUTPUT_DIR / "extracted_sections.json"
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(sections, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("Saved sections: %s", destination)
        return destination

    def _find_next_heading(
        self,
        headings: list[HeadingMatch],
        current_index: int,
    ) -> HeadingMatch | None:
        """Return the next heading after the current heading."""
        if current_index + 1 >= len(headings):
            return None
        return headings[current_index + 1]

    def _clean_section_text(self, text: str) -> str:
        """Normalize whitespace inside an extracted section."""
        lines = [
            self._WHITESPACE_PATTERN.sub(" ", line).strip()
            for line in text.replace("\r\n", "\n").replace("\r", "\n").splitlines()
        ]
        cleaned = "\n".join(lines).strip()
        return self._BLANK_LINES_PATTERN.sub("\n\n", cleaned)

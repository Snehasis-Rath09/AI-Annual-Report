"""Heading detection for cleaned annual report text."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from typing import Iterable

try:  # Prefer the third-party regex engine when available.
    import regex as re
except ImportError:  # pragma: no cover - stdlib fallback.
    import re  # type: ignore[no-redef]

try:
    from rapidfuzz import fuzz, process
except ImportError:  # pragma: no cover - exercised only without dependency.
    fuzz = None  # type: ignore[assignment]
    process = None  # type: ignore[assignment]

from config.settings import SUPPORTED_REPORT_HEADINGS
from src.utils.logger import get_logger


logger = get_logger(__name__)


@dataclass(frozen=True)
class HeadingMatch:
    """Detected heading metadata.

    Attributes:
        heading: Canonical heading name.
        start_index: Character index where the heading starts.
        end_index: Character index where the heading ends.
        confidence_score: Match confidence from 0.0 to 1.0.
        matched_pattern: Candidate pattern that matched the source heading.
        source_text: Exact heading text found in the report.
    """

    heading: str
    start_index: int
    end_index: int
    confidence_score: float
    matched_pattern: str
    source_text: str

    def to_dict(self) -> dict[str, str | int | float]:
        """Return a serializable representation using requested field names."""
        return {
            "Heading": self.heading,
            "Start Index": self.start_index,
            "End Index": self.end_index,
            "Confidence Score": self.confidence_score,
            "Matched Pattern": self.matched_pattern,
            "Source Text": self.source_text,
        }


@dataclass(frozen=True)
class HeadingDetectorConfig:
    """Configuration for heading detection."""

    fuzzy_threshold: float = 0.84
    min_heading_length: int = 2
    max_heading_length: int = 140
    max_heading_words: int = 14
    include_supported_report_headings: bool = True


class HeadingDetector:
    """Detect disclosure section headings in cleaned annual report text."""

    _NUMBER_PREFIX_PATTERN = re.compile(
        r"^\s*(?:section|chapter|part)?\s*"
        r"(?:[0-9]+(?:\.[0-9]+)*|[A-Z]|[IVXLCDM]+)?"
        r"[\s.)-]*",
        re.I,
    )
    _PUNCTUATION_PATTERN = re.compile(r"[^\w\s&/+-]", re.UNICODE)
    _SPACES_PATTERN = re.compile(r"\s+")

    _SECTION_PATTERNS: dict[str, tuple[str, ...]] = {
        "MD&A": (
            "Management Discussion and Analysis",
            "Management Discussion & Analysis",
            "Management Discussion",
            "Management Analysis",
            "MD&A",
            "MDA",
        ),
        "Innovation": (
            "Innovation",
            "Innovation Strategy",
            "Innovation Initiatives",
            "Innovation and Technology",
            "Innovation & Technology",
            "Research Innovation",
        ),
        "Digital Transformation": (
            "Digital Transformation",
            "Digital Strategy",
            "Digital Initiatives",
            "Digitalisation",
            "Digitisation",
            "Digitalization",
            "Digital Business",
        ),
        "AI": (
            "Artificial Intelligence",
            "AI",
            "Generative AI",
            "Gen AI",
            "AI Initiatives",
            "AI and Analytics",
            "Artificial Intelligence Initiatives",
        ),
        "Machine Learning": (
            "Machine Learning",
            "ML",
            "Deep Learning",
            "Predictive Models",
            "Predictive Analytics",
        ),
        "Automation": (
            "Automation",
            "Process Automation",
            "Robotic Process Automation",
            "RPA",
            "Intelligent Automation",
        ),
        "Technology": (
            "Technology",
            "Technology Initiatives",
            "Technology Strategy",
            "Information Technology",
            "Technology Transformation",
            "Technology and Innovation",
        ),
        "Patents": (
            "Patents",
            "Patent",
            "Intellectual Property",
            "IPR",
            "IP Rights",
            "Intellectual Property Rights",
        ),
        "Future Strategy": (
            "Future Strategy",
            "Business Outlook",
            "Future Outlook",
            "Strategic Priorities",
            "Corporate Strategy",
            "Outlook",
            "Strategy",
            "Future Plans",
            "Way Forward",
        ),
        "Research & Development": (
            "Research & Development",
            "Research and Development",
            "R&D",
            "Research Development",
            "Research and Innovation",
            "Product Development",
        ),
    }

    def __init__(self, config: HeadingDetectorConfig | None = None) -> None:
        """Initialize a heading detector.

        Args:
            config: Optional heading detector configuration.
        """
        self.config = config or HeadingDetectorConfig()
        self.heading_patterns = self._build_heading_patterns()
        self._normalized_pattern_lookup = self._build_normalized_pattern_lookup()

    def detect_headings(self, text: str | None) -> list[dict[str, str | int | float]]:
        """Detect headings and return serializable metadata dictionaries.

        Args:
            text: Cleaned annual report text.

        Returns:
            List of heading metadata dictionaries ordered by start index.
        """
        return [match.to_dict() for match in self.find_heading_positions(text)]

    def find_heading_positions(self, text: str | None) -> list[HeadingMatch]:
        """Find matched heading positions in text.

        Args:
            text: Cleaned annual report text.

        Returns:
            Ordered heading matches with character offsets and confidence scores.
        """
        if not text:
            logger.warning("Heading detection skipped because text is empty")
            return []

        logger.info("Heading detection started")
        matches: list[HeadingMatch] = []
        cursor = 0

        try:
            for raw_line in text.splitlines(keepends=True):
                line_start = cursor
                cursor += len(raw_line)
                candidate = raw_line.strip()

                if not self.is_valid_heading(candidate):
                    continue

                match = self.match_heading(candidate)
                if match is None:
                    continue

                leading_offset = len(raw_line) - len(raw_line.lstrip())
                start_index = line_start + leading_offset
                end_index = start_index + len(candidate)
                matches.append(
                    HeadingMatch(
                        heading=match.heading,
                        start_index=start_index,
                        end_index=end_index,
                        confidence_score=match.confidence_score,
                        matched_pattern=match.matched_pattern,
                        source_text=candidate,
                    ),
                )

            deduplicated = self._deduplicate_matches(matches)
            logger.info("Detected headings: %s", len(deduplicated))
            for match in deduplicated:
                logger.info(
                    "Heading detected: %s | confidence=%.3f | pattern=%s",
                    match.heading,
                    match.confidence_score,
                    match.matched_pattern,
                )
            return deduplicated
        except Exception as exc:
            logger.exception("Errors encountered during heading detection: %s", exc)
            raise

    def match_heading(self, heading_text: str) -> HeadingMatch | None:
        """Match a candidate heading to a canonical supported section.

        Args:
            heading_text: Candidate heading line.

        Returns:
            Heading match without offsets, or None when no match is reliable.
        """
        candidate = self._normalize_heading(heading_text)
        if not candidate:
            return None

        exact_match = self._normalized_pattern_lookup.get(candidate)
        if exact_match is not None:
            canonical_heading, pattern = exact_match
            return HeadingMatch(
                heading=canonical_heading,
                start_index=0,
                end_index=0,
                confidence_score=1.0,
                matched_pattern=pattern,
                source_text=heading_text,
            )

        pattern_choices = list(self._normalized_pattern_lookup.keys())
        fuzzy = self._extract_best_fuzzy_match(candidate, pattern_choices)
        if fuzzy is None:
            return None

        matched_normalized, score = fuzzy
        canonical_heading, pattern = self._normalized_pattern_lookup[matched_normalized]
        confidence = round(score / 100, 4)

        return HeadingMatch(
            heading=canonical_heading,
            start_index=0,
            end_index=0,
            confidence_score=confidence,
            matched_pattern=pattern,
            source_text=heading_text,
        )

    def is_valid_heading(self, heading_text: str) -> bool:
        """Return whether a line is a plausible heading candidate.

        Args:
            heading_text: Candidate heading line.

        Returns:
            True when the line is worth matching as a heading.
        """
        candidate = heading_text.strip()
        if not candidate:
            return False
        if len(candidate) < self.config.min_heading_length:
            return False
        if len(candidate) > self.config.max_heading_length:
            return False
        if len(candidate.split()) > self.config.max_heading_words:
            return False
        if candidate.endswith((".", ",", ";")):
            return False
        if not re.search(r"[A-Za-z]", candidate):
            return False

        normalized = self._normalize_heading(candidate)
        if normalized in self._normalized_pattern_lookup:
            return True

        words = re.findall(r"[A-Za-z&]+", candidate)
        if len(words) <= 4:
            return True

        title_like_count = sum(
            word.isupper() or word[:1].isupper()
            for word in words
            if word
        )
        return title_like_count >= max(1, int(len(words) * 0.6))

    def extract_heading_metadata(
        self,
        heading_text: str,
        start_index: int = 0,
        end_index: int | None = None,
    ) -> dict[str, str | int | float] | None:
        """Extract metadata for one heading candidate.

        Args:
            heading_text: Candidate heading text.
            start_index: Character index where heading starts.
            end_index: Character index where heading ends.

        Returns:
            Serializable heading metadata, or None when unmatched.
        """
        match = self.match_heading(heading_text)
        if match is None:
            return None

        resolved_end = end_index if end_index is not None else start_index + len(
            heading_text.strip(),
        )
        return HeadingMatch(
            heading=match.heading,
            start_index=start_index,
            end_index=resolved_end,
            confidence_score=match.confidence_score,
            matched_pattern=match.matched_pattern,
            source_text=heading_text.strip(),
        ).to_dict()

    def get_supported_headings(self) -> tuple[str, ...]:
        """Return canonical headings supported by this detector."""
        return tuple(self.heading_patterns.keys())

    def _build_heading_patterns(self) -> dict[str, tuple[str, ...]]:
        """Build canonical heading groups."""
        patterns: dict[str, tuple[str, ...]] = dict(self._SECTION_PATTERNS)

        if self.config.include_supported_report_headings:
            for heading in SUPPORTED_REPORT_HEADINGS:
                patterns.setdefault(heading, (heading,))

        return patterns

    def _build_normalized_pattern_lookup(self) -> dict[str, tuple[str, str]]:
        """Create normalized pattern lookup for exact and fuzzy matching."""
        lookup: dict[str, tuple[str, str]] = {}
        for canonical_heading, patterns in self.heading_patterns.items():
            for pattern in self._expand_patterns(patterns):
                normalized = self._normalize_heading(pattern)
                if normalized:
                    lookup.setdefault(normalized, (canonical_heading, pattern))
        return lookup

    def _expand_patterns(self, patterns: Iterable[str]) -> set[str]:
        """Expand heading patterns with punctuation-normalized variations."""
        expanded: set[str] = set()
        for pattern in patterns:
            expanded.add(pattern)
            expanded.add(pattern.replace("&", "and"))
            expanded.add(pattern.replace("and", "&"))
            expanded.add(pattern.replace("/", " "))
            expanded.add(pattern.replace("-", " "))
            expanded.add(pattern.rstrip(":"))
        return expanded

    def _deduplicate_matches(self, matches: list[HeadingMatch]) -> list[HeadingMatch]:
        """Remove duplicate matches at the same text location."""
        best_by_location: dict[tuple[int, int], HeadingMatch] = {}
        for match in matches:
            key = (match.start_index, match.end_index)
            current = best_by_location.get(key)
            if current is None or match.confidence_score > current.confidence_score:
                best_by_location[key] = match

        return sorted(best_by_location.values(), key=lambda item: item.start_index)

    def _extract_best_fuzzy_match(
        self,
        candidate: str,
        choices: list[str],
    ) -> tuple[str, float] | None:
        """Return the best fuzzy heading match.

        RapidFuzz is used when installed. A standard-library fallback keeps the
        module importable in minimal environments.
        """
        score_cutoff = self.config.fuzzy_threshold * 100

        if process is not None and fuzz is not None:
            fuzzy_match = process.extractOne(
                candidate,
                choices,
                scorer=fuzz.WRatio,
                score_cutoff=score_cutoff,
            )
            if fuzzy_match is None:
                return None
            matched_value, score, _ = fuzzy_match
            return matched_value, float(score)

        logger.warning(
            "RapidFuzz is not installed; using standard-library fuzzy matching",
        )
        best_choice = ""
        best_score = 0.0
        for choice in choices:
            score = SequenceMatcher(None, candidate, choice).ratio() * 100
            if score > best_score:
                best_choice = choice
                best_score = score

        if best_score < score_cutoff:
            return None
        return best_choice, best_score

    def _normalize_heading(self, value: str) -> str:
        """Normalize heading text for matching."""
        normalized = value.strip().strip(":")
        normalized = self._NUMBER_PREFIX_PATTERN.sub("", normalized)
        normalized = normalized.replace("&", " and ")
        normalized = normalized.replace("+", " plus ")
        normalized = self._PUNCTUATION_PATTERN.sub(" ", normalized)
        normalized = self._SPACES_PATTERN.sub(" ", normalized)
        return normalized.strip().casefold()

    @staticmethod
    def matches_to_dicts(matches: Iterable[HeadingMatch]) -> list[dict[str, object]]:
        """Convert heading matches to plain dictionaries.

        Args:
            matches: Heading matches.

        Returns:
            List of dataclass dictionaries.
        """
        return [asdict(match) for match in matches]

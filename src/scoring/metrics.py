"""Transparent disclosure metric calculations."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Mapping

try:  # Prefer the third-party regex engine when available.
    import regex as re
except ImportError:  # pragma: no cover - stdlib fallback.
    import re  # type: ignore[no-redef]

from config.settings import KEYWORD_CATEGORIES
from src.utils.logger import get_logger


logger = get_logger(__name__)


@dataclass(frozen=True)
class DisclosureMetricsConfig:
    """Configuration for disclosure metric calculations."""

    density_per_words: int = 1000
    decimals: int = 4
    expected_sections: tuple[str, ...] = (
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


class DisclosureMetrics:
    """Calculate reproducible metrics from keyword and section outputs."""

    _WORD_PATTERN = re.compile(r"[^\W_]+(?:[&'-][^\W_]+)*", re.UNICODE)

    def __init__(self, config: DisclosureMetricsConfig | None = None) -> None:
        """Initialize the metric calculator.

        Args:
            config: Optional metric configuration.
        """
        self.config = config or DisclosureMetricsConfig()

    def calculate_total_keywords(
        self,
        keyword_counts: Mapping[str, Mapping[str, int]] | Mapping[str, int],
    ) -> int:
        """Calculate total keyword occurrences.

        Args:
            keyword_counts: Either section-level keyword counts or a flat keyword
                count mapping.

        Returns:
            Total keyword occurrence count.
        """
        total = sum(self._flatten_keyword_counts(keyword_counts).values())
        logger.info("Total keyword count calculated: %s", total)
        return total

    def calculate_total_word_count(self, sections: Mapping[str, str] | str) -> int:
        """Calculate total document word count from extracted sections.

        Args:
            sections: Section text mapping or a single text string.

        Returns:
            Total word count.
        """
        text = sections if isinstance(sections, str) else " ".join(sections.values())
        return len(self._WORD_PATTERN.findall(text or ""))

    def calculate_density(self, keyword_count: int, word_count: int) -> float:
        """Calculate keyword density per configured word count.

        Formula:
            ``density = (keyword_count / word_count) * density_per_words``

        Args:
            keyword_count: Number of keyword occurrences.
            word_count: Number of words in the analyzed text.

        Returns:
            Rounded keyword density.
        """
        if word_count <= 0:
            logger.warning("Density set to 0 because word count is zero")
            return 0.0
        density = (keyword_count / word_count) * self.config.density_per_words
        return round(density, self.config.decimals)

    def calculate_category_count(
        self,
        keyword_counts: Mapping[str, Mapping[str, int]] | Mapping[str, int],
        keyword_categories: Mapping[str, tuple[str, ...]] | None = None,
    ) -> dict[str, int]:
        """Calculate category-wise keyword counts.

        Args:
            keyword_counts: Section-level or flat keyword counts.
            keyword_categories: Mapping of category names to keywords.

        Returns:
            Mapping of category names to keyword counts.
        """
        categories = keyword_categories or KEYWORD_CATEGORIES
        flat_counts = self._flatten_keyword_counts(keyword_counts)
        normalized_counts = Counter(
            {self._normalize_keyword(key): value for key, value in flat_counts.items()},
        )

        category_counts: dict[str, int] = {}
        for category, keywords in categories.items():
            category_counts[category] = sum(
                normalized_counts.get(self._normalize_keyword(keyword), 0)
                for keyword in keywords
            )
        return category_counts

    def calculate_category_density(
        self,
        category_counts: Mapping[str, int],
        word_count: int,
    ) -> dict[str, float]:
        """Calculate category-wise keyword density."""
        return {
            category: self.calculate_density(count, word_count)
            for category, count in category_counts.items()
        }

    def calculate_presence(self, category_counts: Mapping[str, int]) -> dict[str, bool]:
        """Calculate category presence or absence."""
        return {category: count > 0 for category, count in category_counts.items()}

    def calculate_percentage(
        self,
        category_counts: Mapping[str, int],
        total_keywords: int | None = None,
    ) -> dict[str, float]:
        """Calculate percentage contribution of each category.

        Formula:
            ``percentage = (category_count / total_keyword_count) * 100``
        """
        denominator = (
            sum(category_counts.values()) if total_keywords is None else total_keywords
        )
        if denominator <= 0:
            return {category: 0.0 for category in category_counts}
        return {
            category: round((count / denominator) * 100, self.config.decimals)
            for category, count in category_counts.items()
        }

    def calculate_section_coverage(
        self,
        sections: Mapping[str, str],
        expected_sections: tuple[str, ...] | None = None,
    ) -> dict[str, int | float | list[str]]:
        """Calculate how many expected disclosure sections were detected.

        Formula:
            ``coverage = detected_expected_sections / expected_sections * 100``
        """
        expected = expected_sections or self.config.expected_sections
        present_sections = {
            section.casefold()
            for section, text in sections.items()
            if str(text).strip()
        }
        detected = [
            section
            for section in expected
            if section.casefold() in present_sections
        ]
        missing = [section for section in expected if section not in detected]
        coverage = 0.0
        if expected:
            coverage = round(
                (len(detected) / len(expected)) * 100,
                self.config.decimals,
            )

        return {
            "detected_sections": len(detected),
            "expected_sections": len(expected),
            "section_coverage": coverage,
            "present_sections": detected,
            "missing_sections": missing,
        }

    def calculate_summary(
        self,
        sections: Mapping[str, str],
        keyword_counts: Mapping[str, Mapping[str, int]] | Mapping[str, int],
        keyword_categories: Mapping[str, tuple[str, ...]] | None = None,
        expected_sections: tuple[str, ...] | None = None,
    ) -> dict[str, object]:
        """Calculate a complete metric summary.

        Args:
            sections: Extracted section text mapping.
            keyword_counts: Section-level or flat keyword counts.
            keyword_categories: Optional category-to-keywords mapping.
            expected_sections: Optional expected disclosure sections.

        Returns:
            Structured metrics dictionary.
        """
        try:
            total_keywords = self.calculate_total_keywords(keyword_counts)
            word_count = self.calculate_total_word_count(sections)
            density = self.calculate_density(total_keywords, word_count)
            category_counts = self.calculate_category_count(
                keyword_counts,
                keyword_categories,
            )
            category_density = self.calculate_category_density(
                category_counts,
                word_count,
            )
            category_presence = self.calculate_presence(category_counts)
            category_percentage = self.calculate_percentage(
                category_counts,
                total_keywords,
            )
            section_coverage = self.calculate_section_coverage(
                sections,
                expected_sections,
            )
            unique_keywords = sum(
                1 for count in self._flatten_keyword_counts(keyword_counts).values()
                if count > 0
            )

            summary = {
                "total_keyword_count": total_keywords,
                "total_word_count": word_count,
                "keyword_density": density,
                "category_counts": category_counts,
                "category_density": category_density,
                "category_presence": category_presence,
                "category_percentage": category_percentage,
                "number_of_detected_sections": section_coverage["detected_sections"],
                "section_coverage": section_coverage,
                "unique_keyword_count": unique_keywords,
            }
            logger.info("Metrics calculated")
            return summary
        except Exception as exc:
            logger.exception("Errors encountered while calculating metrics: %s", exc)
            raise

    def _flatten_keyword_counts(
        self,
        keyword_counts: Mapping[str, Mapping[str, int]] | Mapping[str, int],
    ) -> Counter[str]:
        """Flatten section-level keyword counts into one counter."""
        flattened: Counter[str] = Counter()
        for key, value in keyword_counts.items():
            if isinstance(value, Mapping):
                flattened.update(
                    {str(item): int(count) for item, count in value.items()},
                )
            else:
                flattened[str(key)] += int(value)
        return flattened

    @staticmethod
    def _normalize_keyword(keyword: str) -> str:
        """Normalize a keyword key for category lookup."""
        return re.sub(
            r"\s+",
            " ",
            str(keyword).replace("&", " and "),
        ).strip().casefold()

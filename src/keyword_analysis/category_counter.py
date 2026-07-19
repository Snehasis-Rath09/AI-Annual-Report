"""Category-level keyword statistics for annual report disclosure analysis."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Mapping

try:  # Prefer the third-party regex engine when available.
    import regex as re
except ImportError:  # pragma: no cover - stdlib fallback.
    import re  # type: ignore[no-redef]

from src.keyword_analysis.dictionary_loader import KeywordDictionaryLoader
from src.keyword_analysis.keyword_counter import KeywordCounter
from src.utils.logger import get_logger


logger = get_logger(__name__)


@dataclass(frozen=True)
class CategoryCounterConfig:
    """Configuration for category statistics."""

    density_per_words: int = 1000
    decimals: int = 4


class CategoryCounter:
    """Calculate category-level keyword disclosure statistics."""

    _WORD_PATTERN = re.compile(r"[^\W_]+(?:[&'-][^\W_]+)*", re.UNICODE)

    def __init__(
        self,
        dictionary_loader: KeywordDictionaryLoader | None = None,
        keyword_counter: KeywordCounter | None = None,
        config: CategoryCounterConfig | None = None,
    ) -> None:
        """Initialize a category counter.

        Args:
            dictionary_loader: Optional keyword dictionary loader.
            keyword_counter: Optional keyword counter.
            config: Optional statistics configuration.
        """
        self.dictionary_loader = dictionary_loader or KeywordDictionaryLoader()
        self.keyword_counter = keyword_counter or KeywordCounter(self.dictionary_loader)
        self.config = config or CategoryCounterConfig()

    def calculate_category_statistics(
        self,
        sections: Mapping[str, str],
        keyword_counts: Mapping[str, Mapping[str, int]] | None = None,
    ) -> dict[str, dict[str, int | float | bool]]:
        """Calculate category statistics for one company/report.

        Args:
            sections: Mapping of section names to extracted section text.
            keyword_counts: Optional precomputed section-keyword counts.

        Returns:
            Mapping of categories to count, density, presence, and contribution.
        """
        try:
            dictionary = {
                category: self.dictionary_loader.get_keywords(category)
                for category in self.dictionary_loader.get_categories()
            }
            counts_by_section = keyword_counts or self.keyword_counter.count_keywords(
                sections,
                dictionary,
            )
            aggregate_keyword_counts = self._aggregate_keyword_counts(counts_by_section)
            total_keyword_count = sum(aggregate_keyword_counts.values())
            total_words = self._count_words(" ".join(sections.values()))

            statistics: dict[str, dict[str, int | float | bool]] = {}
            for category, keywords in dictionary.items():
                category_count = sum(
                    aggregate_keyword_counts.get(keyword, 0)
                    for keyword in keywords
                )
                density = self._calculate_density(category_count, total_words)
                contribution = self._calculate_percentage(
                    category_count,
                    total_keyword_count,
                )
                statistics[category] = {
                    "count": category_count,
                    "density": density,
                    "present": category_count > 0,
                    "percentage_contribution": contribution,
                    "total_keyword_count": total_keyword_count,
                    "word_count": total_words,
                }

            logger.info("Category statistics generated")
            logger.info("Total keyword count: %s", total_keyword_count)
            return statistics
        except Exception as exc:
            logger.exception(
                "Errors encountered generating category statistics: %s",
                exc,
            )
            raise

    def count_categories(
        self,
        sections: Mapping[str, str],
    ) -> dict[str, dict[str, int | float | bool]]:
        """Alias for calculating category-level statistics."""
        return self.calculate_category_statistics(sections)

    def category_counts(
        self,
        sections: Mapping[str, str],
        keyword_counts: Mapping[str, Mapping[str, int]] | None = None,
    ) -> Counter[str]:
        """Return category-wise raw keyword counts.

        Args:
            sections: Mapping of section names to extracted section text.
            keyword_counts: Optional precomputed section-keyword counts.

        Returns:
            Counter mapping category names to counts.
        """
        stats = self.calculate_category_statistics(sections, keyword_counts)
        return Counter(
            {
                category: int(values["count"])
                for category, values in stats.items()
            },
        )

    def to_excel_records(
        self,
        statistics: Mapping[str, Mapping[str, int | float | bool]],
        company_id: str | None = None,
    ) -> list[dict[str, int | float | bool | str]]:
        """Convert statistics into flat records suitable for Excel export.

        Args:
            statistics: Category statistics mapping.
            company_id: Optional company identifier.

        Returns:
            List of flat row dictionaries.
        """
        records: list[dict[str, int | float | bool | str]] = []
        for category, values in statistics.items():
            record: dict[str, int | float | bool | str] = {"category": category}
            if company_id is not None:
                record["company_id"] = company_id
            record.update(values)
            records.append(record)
        return records

    def _aggregate_keyword_counts(
        self,
        keyword_counts: Mapping[str, Mapping[str, int]],
    ) -> Counter[str]:
        """Aggregate section-level keyword counts."""
        aggregate: Counter[str] = Counter()
        for section_name, section_counts in keyword_counts.items():
            aggregate.update(section_counts)
            logger.info(
                "Section analyzed for category stats: %s | count=%s",
                section_name,
                sum(section_counts.values()),
            )
        return aggregate

    def _count_words(self, text: str) -> int:
        """Count words in section text."""
        return len(self._WORD_PATTERN.findall(text or ""))

    def _calculate_density(self, count: int, word_count: int) -> float:
        """Calculate keyword density per configured word count."""
        if word_count <= 0:
            return 0.0
        density = (count / word_count) * self.config.density_per_words
        return round(density, self.config.decimals)

    def _calculate_percentage(self, count: int, total: int) -> float:
        """Calculate percentage contribution to total keyword count."""
        if total <= 0:
            return 0.0
        return round((count / total) * 100, self.config.decimals)

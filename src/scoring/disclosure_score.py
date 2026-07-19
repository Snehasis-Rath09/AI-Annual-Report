"""Transparent disclosure score calculation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from src.scoring.metrics import DisclosureMetrics
from src.utils.logger import get_logger


logger = get_logger(__name__)


@dataclass(frozen=True)
class DisclosureScoreConfig:
    """Configuration for transparent disclosure scoring.

    Weights sum to 1.0:
        keyword_density_weight: 40% of the overall score.
        category_coverage_weight: 30% of the overall score.
        section_coverage_weight: 20% of the overall score.
        keyword_diversity_weight: 10% of the overall score.

    keyword_density_benchmark is the density per 1,000 words that receives the
    full keyword-density component score.
    """

    keyword_density_weight: float = 0.40
    category_coverage_weight: float = 0.30
    section_coverage_weight: float = 0.20
    keyword_diversity_weight: float = 0.10
    keyword_density_benchmark: float = 10.0
    decimals: int = 4


class DisclosureScoreCalculator:
    """Calculate reproducible disclosure scores from explicit formulas."""

    def __init__(
        self,
        metrics_calculator: DisclosureMetrics | None = None,
        config: DisclosureScoreConfig | None = None,
    ) -> None:
        """Initialize the score calculator."""
        self.metrics_calculator = metrics_calculator or DisclosureMetrics()
        self.config = config or DisclosureScoreConfig()
        self._validate_weights()

    def calculate_score(
        self,
        sections: Mapping[str, str],
        keyword_counts: Mapping[str, Mapping[str, int]] | Mapping[str, int],
        keyword_categories: Mapping[str, tuple[str, ...]] | None = None,
        expected_sections: tuple[str, ...] | None = None,
    ) -> dict[str, object]:
        """Calculate the overall disclosure score.

        Formula:
            ``overall_score =
            0.40 * keyword_density_score +
            0.30 * category_coverage_score +
            0.20 * section_coverage_score +
            0.10 * keyword_diversity_score``

        No model-generated values are used. Every component is derived from
        keyword counts, category coverage, extracted sections, and word count.
        """
        try:
            raw_metrics = self.metrics_calculator.calculate_summary(
                sections=sections,
                keyword_counts=keyword_counts,
                keyword_categories=keyword_categories,
                expected_sections=expected_sections,
            )
            component_scores = self.calculate_component_scores(
                raw_metrics,
                keyword_categories,
            )
            overall_score = round(
                (
                    component_scores["keyword_density_score"]
                    * self.config.keyword_density_weight
                )
                + (
                    component_scores["category_coverage_score"]
                    * self.config.category_coverage_weight
                )
                + (
                    component_scores["section_coverage_score"]
                    * self.config.section_coverage_weight
                )
                + (
                    component_scores["keyword_diversity_score"]
                    * self.config.keyword_diversity_weight
                ),
                self.config.decimals,
            )

            result = {
                "overall_score": overall_score,
                "component_scores": component_scores,
                "raw_metrics": raw_metrics,
                "explanation": self.generate_summary(overall_score, component_scores),
            }
            logger.info("Disclosure score generated: %s", overall_score)
            return result
        except Exception as exc:
            logger.exception(
                "Errors encountered while generating disclosure score: %s",
                exc,
            )
            raise

    def calculate_component_scores(
        self,
        raw_metrics: Mapping[str, object],
        keyword_categories: Mapping[str, tuple[str, ...]] | None = None,
    ) -> dict[str, float]:
        """Calculate normalized component scores from raw metrics.

        Component formulas:
            keyword_density_score = min(density / benchmark, 1) * 100
            category_coverage_score = present_categories / total_categories * 100
            section_coverage_score = (
                detected_expected_sections / expected_sections * 100
            )
            keyword_diversity_score = unique_found_keywords / known_keywords * 100
        """
        category_presence = raw_metrics.get("category_presence", {})
        if not isinstance(category_presence, Mapping):
            category_presence = {}

        present_categories = sum(1 for present in category_presence.values() if present)
        total_categories = len(category_presence)
        category_coverage_score = self.normalize_score(
            present_categories,
            total_categories,
        )

        section_coverage = raw_metrics.get("section_coverage", {})
        section_coverage_score = 0.0
        if isinstance(section_coverage, Mapping):
            section_coverage_score = float(
                section_coverage.get("section_coverage", 0.0),
            )

        keyword_density = float(raw_metrics.get("keyword_density", 0.0))
        keyword_density_score = self.normalize_score(
            keyword_density,
            self.config.keyword_density_benchmark,
        )

        unique_keyword_count = int(raw_metrics.get("unique_keyword_count", 0))
        known_keyword_count = self._count_known_keywords(
            keyword_categories,
            raw_metrics,
        )
        keyword_diversity_score = self.normalize_score(
            unique_keyword_count,
            known_keyword_count,
        )

        return {
            "keyword_density_score": keyword_density_score,
            "category_coverage_score": category_coverage_score,
            "section_coverage_score": round(
                section_coverage_score,
                self.config.decimals,
            ),
            "keyword_diversity_score": keyword_diversity_score,
        }

    def normalize_score(self, value: float, benchmark: float) -> float:
        """Normalize a positive value against a benchmark to a 0-100 score.

        Formula:
            ``normalized = min(max(value / benchmark, 0), 1) * 100``
        """
        if benchmark <= 0:
            return 0.0
        normalized = min(max(value / benchmark, 0.0), 1.0) * 100
        return round(normalized, self.config.decimals)

    def generate_summary(
        self,
        overall_score: float,
        component_scores: Mapping[str, float],
    ) -> str:
        """Generate a human-readable formula explanation."""
        return (
            "Overall Disclosure Score is a weighted mathematical score: "
            f"40% keyword density ({component_scores['keyword_density_score']}), "
            f"30% category coverage ({component_scores['category_coverage_score']}), "
            f"20% section coverage ({component_scores['section_coverage_score']}), "
            f"and 10% keyword diversity "
            f"({component_scores['keyword_diversity_score']}). "
            f"The final reproducible score is {overall_score} out of 100."
        )

    def _count_known_keywords(
        self,
        keyword_categories: Mapping[str, tuple[str, ...]] | None,
        raw_metrics: Mapping[str, object],
    ) -> int:
        """Count known keywords for diversity normalization."""
        if keyword_categories:
            return len(
                {
                    keyword
                    for keywords in keyword_categories.values()
                    for keyword in keywords
                },
            )

        category_counts = raw_metrics.get("category_counts", {})
        if isinstance(category_counts, Mapping):
            return max(1, len(category_counts))
        return 1

    def _validate_weights(self) -> None:
        """Validate scoring weights."""
        weight_sum = (
            self.config.keyword_density_weight
            + self.config.category_coverage_weight
            + self.config.section_coverage_weight
            + self.config.keyword_diversity_weight
        )
        if round(weight_sum, 6) != 1.0:
            raise ValueError("Disclosure score weights must sum to 1.0.")

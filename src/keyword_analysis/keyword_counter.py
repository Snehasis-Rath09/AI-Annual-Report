"""Keyword occurrence counting for extracted annual report sections."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Mapping

try:  # Prefer the third-party regex engine when available.
    import regex as re
except ImportError:  # pragma: no cover - stdlib fallback.
    import re  # type: ignore[no-redef]

try:
    from rapidfuzz import fuzz
except ImportError:  # pragma: no cover - exercised only without dependency.
    fuzz = None  # type: ignore[assignment]

from src.keyword_analysis.dictionary_loader import KeywordDictionaryLoader
from src.utils.logger import get_logger


logger = get_logger(__name__)


@dataclass(frozen=True)
class KeywordCounterConfig:
    """Configuration for keyword counting."""

    enable_fuzzy_matching: bool = False
    fuzzy_threshold: float = 0.90
    max_ngram_size: int = 6


class KeywordCounter:
    """Count dictionary keyword occurrences in extracted report sections."""

    _WORD_PATTERN = re.compile(r"[^\W_]+(?:[&'-][^\W_]+)*", re.UNICODE)
    _DASH_PATTERN = re.compile(r"[-\u2010-\u2015\u2212]")
    _QUOTE_PATTERN = re.compile(r"[\u2018\u2019\u201a\u201b\u2032\u2035]")
    _WHITESPACE_PATTERN = re.compile(r"\s+")

    def __init__(
        self,
        dictionary_loader: KeywordDictionaryLoader | None = None,
        config: KeywordCounterConfig | None = None,
    ) -> None:
        """Initialize a keyword counter.

        Args:
            dictionary_loader: Optional loaded dictionary provider.
            config: Optional counting configuration.
        """
        self.dictionary_loader = dictionary_loader or KeywordDictionaryLoader()
        self.config = config or KeywordCounterConfig()

    def count_keywords(
        self,
        sections: Mapping[str, str],
        keywords: Mapping[str, tuple[str, ...]] | None = None,
    ) -> dict[str, dict[str, int]]:
        """Count keyword occurrences independently for every section.

        Args:
            sections: Mapping of section names to extracted section text.
            keywords: Optional category-keyword mapping. When omitted, the
                configured dictionary loader is used.

        Returns:
            Mapping of section names to keyword occurrence counts.
        """
        logger.info("Keyword counting started")
        keyword_list = self._resolve_keywords(keywords)
        if not keyword_list:
            logger.warning("No keywords available for counting")
            return {section_name: {} for section_name in sections}

        try:
            results: dict[str, dict[str, int]] = {}
            for section_name, section_text in sections.items():
                section_counts = self.count_section(section_text, keyword_list)
                results[section_name] = dict(section_counts)
                logger.info(
                    "Section analyzed: %s | keywords_found=%s",
                    section_name,
                    sum(section_counts.values()),
                )
            return results
        except Exception as exc:
            logger.exception("Errors encountered during keyword counting: %s", exc)
            raise

    def count_section(
        self,
        section_text: str | None,
        keywords: tuple[str, ...] | list[str] | None = None,
    ) -> Counter[str]:
        """Count keyword occurrences within one section.

        Args:
            section_text: Extracted section text.
            keywords: Optional keyword list. Defaults to all dictionary keywords.

        Returns:
            Counter of keyword to occurrence count.
        """
        if not section_text:
            return Counter()

        keyword_list = tuple(keywords) if keywords is not None else (
            self.dictionary_loader.get_all_keywords()
        )
        normalized_text = self.normalize_text(section_text)
        counts: Counter[str] = Counter()

        for keyword in keyword_list:
            count = self.count_keyword(normalized_text, keyword)
            if count:
                counts[keyword] = count

        return counts

    def count_keyword(self, section_text: str, keyword: str) -> int:
        """Count one keyword in normalized section text.

        Args:
            section_text: Section text. Raw text is accepted and normalized.
            keyword: Keyword to count.

        Returns:
            Number of occurrences.
        """
        normalized_text = self.normalize_text(section_text)
        normalized_keyword = KeywordDictionaryLoader.normalize_keyword(keyword)
        if not normalized_text or not normalized_keyword:
            return 0

        exact_count = self._count_exact_keyword(normalized_text, normalized_keyword)
        if exact_count or not self.config.enable_fuzzy_matching:
            return exact_count

        return self._count_fuzzy_keyword(normalized_text, normalized_keyword)

    def keyword_frequency(
        self,
        sections: Mapping[str, str],
        keywords: Mapping[str, tuple[str, ...]] | None = None,
    ) -> Counter[str]:
        """Return aggregate keyword frequencies across all sections.

        Args:
            sections: Mapping of section names to extracted section text.
            keywords: Optional category-keyword mapping.

        Returns:
            Aggregate keyword frequency counter.
        """
        aggregate: Counter[str] = Counter()
        for section_counts in self.count_keywords(sections, keywords).values():
            aggregate.update(section_counts)
        return aggregate

    def normalize_text(self, value: str | None) -> str:
        """Normalize text for punctuation-insensitive keyword matching."""
        if not value:
            return ""
        text = str(value)
        text = self._DASH_PATTERN.sub(" ", text)
        text = self._QUOTE_PATTERN.sub("'", text)
        text = text.replace("&", " and ")
        text = text.replace("/", " ")
        tokens = self._WORD_PATTERN.findall(text.casefold())
        return " ".join(tokens)

    def _resolve_keywords(
        self,
        keywords: Mapping[str, tuple[str, ...]] | None,
    ) -> tuple[str, ...]:
        """Resolve keyword mapping into one deduplicated keyword tuple."""
        if keywords is None:
            return self.dictionary_loader.get_all_keywords()

        seen: set[str] = set()
        resolved: list[str] = []
        for category_keywords in keywords.values():
            for keyword in category_keywords:
                normalized_keyword = KeywordDictionaryLoader.normalize_keyword(keyword)
                if normalized_keyword and normalized_keyword not in seen:
                    seen.add(normalized_keyword)
                    resolved.append(normalized_keyword)
        return tuple(resolved)

    def _count_exact_keyword(
        self,
        normalized_text: str,
        normalized_keyword: str,
    ) -> int:
        """Count whole-keyword occurrences with whitespace boundaries."""
        pattern = re.compile(
            rf"(?<![^\W_])"
            rf"{re.escape(normalized_keyword)}"
            rf"(?![^\W_])",
            re.I,
        )
        return len(pattern.findall(normalized_text))

    def _count_fuzzy_keyword(
        self,
        normalized_text: str,
        normalized_keyword: str,
    ) -> int:
        """Count likely misspelled keyword occurrences using token n-grams."""
        keyword_tokens = normalized_keyword.split()
        if not keyword_tokens:
            return 0

        token_count = min(len(keyword_tokens), self.config.max_ngram_size)
        text_tokens = normalized_text.split()
        if len(text_tokens) < token_count:
            return 0

        threshold = self.config.fuzzy_threshold
        matches = 0
        index = 0

        while index <= len(text_tokens) - token_count:
            ngram = " ".join(text_tokens[index : index + token_count])
            score = self._similarity(ngram, normalized_keyword)
            if score >= threshold:
                matches += 1
                index += token_count
                continue
            index += 1

        return matches

    def _similarity(self, left: str, right: str) -> float:
        """Compute fuzzy similarity from 0.0 to 1.0."""
        if fuzz is not None:
            return fuzz.WRatio(left, right) / 100

        logger.warning(
            "RapidFuzz is not installed; using standard-library fuzzy matching",
        )
        return SequenceMatcher(None, left, right).ratio()

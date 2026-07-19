"""Load and validate keyword dictionaries for disclosure analysis."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd

try:  # Prefer the third-party regex engine when available.
    import regex as re
except ImportError:  # pragma: no cover - stdlib fallback.
    import re  # type: ignore[no-redef]

from config.settings import INNOVATION_DICTIONARY_FILE
from src.utils.logger import get_logger


logger = get_logger(__name__)


@dataclass(frozen=True)
class KeywordEntry:
    """One normalized dictionary keyword entry."""

    category: str
    keyword: str
    rationale: str = ""


@dataclass(frozen=True)
class KeywordDictionaryConfig:
    """Configuration for loading keyword dictionaries."""

    dictionary_path: Path = INNOVATION_DICTIONARY_FILE
    required_columns: tuple[str, ...] = ("Category", "Keyword")
    rationale_column: str = "Rationale"


class KeywordDictionaryLoader:
    """Load, validate, normalize, and group keyword dictionary entries."""

    _WHITESPACE_PATTERN = re.compile(r"\s+")
    _DASH_PATTERN = re.compile(r"[-\u2010-\u2015\u2212]")
    _QUOTE_PATTERN = re.compile(r"[\u2018\u2019\u201a\u201b\u2032\u2035]")

    def __init__(self, config: KeywordDictionaryConfig | None = None) -> None:
        """Initialize a keyword dictionary loader.

        Args:
            config: Optional loader configuration.
        """
        self.config = config or KeywordDictionaryConfig()
        self.dictionary_path = Path(self.config.dictionary_path)
        self._entries: tuple[KeywordEntry, ...] = ()
        self._keywords_by_category: dict[str, tuple[str, ...]] = {}
        self._loaded = False

    def load_dictionary(
        self,
        dictionary_path: str | Path | None = None,
    ) -> dict[str, tuple[str, ...]]:
        """Load and group keywords from the Excel dictionary.

        Args:
            dictionary_path: Optional dictionary path override.

        Returns:
            Mapping of category names to normalized keyword tuples.

        Raises:
            FileNotFoundError: If the dictionary file is missing.
            ValueError: If required columns are missing or no keywords are valid.
        """
        path = Path(dictionary_path) if dictionary_path else self.dictionary_path
        logger.info("Loading keyword dictionary: %s", path)

        if not path.is_file():
            logger.error("Keyword dictionary file not found: %s", path)
            raise FileNotFoundError(f"Keyword dictionary file not found: {path}")

        try:
            frame = pd.read_excel(path)
            self.validate_dictionary(frame)
            entries = self._build_entries(frame)
            if not entries:
                raise ValueError("Keyword dictionary contains no valid keywords.")

            self._entries = tuple(entries)
            self._keywords_by_category = self._group_keywords(entries)
            self._loaded = True

            logger.info("Dictionary loaded: %s", path)
            logger.info("Categories found: %s", list(self._keywords_by_category))
            logger.info("Keywords loaded: %s", len(self.get_all_keywords()))
            return self._keywords_by_category
        except Exception as exc:
            logger.exception("Errors encountered while loading dictionary: %s", exc)
            raise

    def validate_dictionary(self, dictionary_frame: pd.DataFrame) -> None:
        """Validate the loaded dictionary dataframe.

        Args:
            dictionary_frame: Dictionary dataframe.

        Raises:
            ValueError: If required columns are missing.
        """
        normalized_columns = {
            self._normalize_column_name(column): column
            for column in dictionary_frame.columns
        }
        missing_columns = [
            column
            for column in self.config.required_columns
            if self._normalize_column_name(column) not in normalized_columns
        ]
        if missing_columns:
            message = f"Dictionary missing required columns: {missing_columns}"
            logger.error(message)
            raise ValueError(message)

    def get_categories(self) -> tuple[str, ...]:
        """Return categories in the loaded dictionary."""
        self._ensure_loaded()
        return tuple(self._keywords_by_category.keys())

    def get_keywords(self, category: str) -> tuple[str, ...]:
        """Return normalized keywords for a category.

        Args:
            category: Category name.

        Returns:
            Tuple of normalized keywords, empty when category is unknown.
        """
        self._ensure_loaded()
        category_lookup = {
            self._normalize_category(name): name
            for name in self._keywords_by_category
        }
        resolved_category = category_lookup.get(self._normalize_category(category))
        if resolved_category is None:
            logger.warning("Unknown keyword category requested: %s", category)
            return ()
        return self._keywords_by_category[resolved_category]

    def get_all_keywords(self) -> tuple[str, ...]:
        """Return all normalized keywords across categories."""
        self._ensure_loaded()
        seen: set[str] = set()
        keywords: list[str] = []
        for category_keywords in self._keywords_by_category.values():
            for keyword in category_keywords:
                if keyword not in seen:
                    seen.add(keyword)
                    keywords.append(keyword)
        return tuple(keywords)

    def reload_dictionary(self) -> dict[str, tuple[str, ...]]:
        """Reload the configured dictionary from disk."""
        self._loaded = False
        self._entries = ()
        self._keywords_by_category = {}
        return self.load_dictionary(self.dictionary_path)

    def get_entries(self) -> tuple[KeywordEntry, ...]:
        """Return normalized dictionary entries."""
        self._ensure_loaded()
        return self._entries

    def _build_entries(self, dictionary_frame: pd.DataFrame) -> list[KeywordEntry]:
        """Create normalized entries from dictionary rows."""
        column_map = {
            self._normalize_column_name(column): column
            for column in dictionary_frame.columns
        }
        category_column = column_map[self._normalize_column_name("Category")]
        keyword_column = column_map[self._normalize_column_name("Keyword")]
        rationale_column = column_map.get(
            self._normalize_column_name(self.config.rationale_column),
        )

        seen: set[tuple[str, str]] = set()
        entries: list[KeywordEntry] = []

        for row in dictionary_frame.itertuples(index=False):
            row_data = dict(zip(dictionary_frame.columns, row, strict=False))
            category = self._normalize_category(row_data.get(category_column, ""))
            keyword = self.normalize_keyword(row_data.get(keyword_column, ""))

            if not category or not keyword:
                continue

            key = (self._normalize_category(category), keyword)
            if key in seen:
                logger.warning(
                    "Duplicate keyword ignored: category=%s keyword=%s",
                    category,
                    keyword,
                )
                continue

            rationale = ""
            if rationale_column is not None:
                rationale = self._safe_string(row_data.get(rationale_column, ""))

            seen.add(key)
            entries.append(
                KeywordEntry(
                    category=category,
                    keyword=keyword,
                    rationale=rationale,
                ),
            )

        return entries

    def _group_keywords(
        self,
        entries: Iterable[KeywordEntry],
    ) -> dict[str, tuple[str, ...]]:
        """Group normalized keywords by category."""
        grouped: dict[str, list[str]] = defaultdict(list)
        for entry in entries:
            grouped[entry.category].append(entry.keyword)

        return {
            category: tuple(sorted(set(keywords), key=lambda item: (len(item), item)))
            for category, keywords in grouped.items()
        }

    def _ensure_loaded(self) -> None:
        """Load the dictionary lazily when needed."""
        if not self._loaded:
            self.load_dictionary()

    @classmethod
    def normalize_keyword(cls, value: object) -> str:
        """Normalize a keyword for matching.

        Args:
            value: Raw keyword value.

        Returns:
            Normalized lowercase keyword.
        """
        text = cls._safe_string(value)
        if not text:
            return ""
        text = cls._DASH_PATTERN.sub(" ", text)
        text = cls._QUOTE_PATTERN.sub("'", text)
        text = text.replace("&", " and ")
        text = text.replace("/", " ")
        text = cls._WHITESPACE_PATTERN.sub(" ", text)
        return text.strip().casefold()

    @classmethod
    def _normalize_category(cls, value: object) -> str:
        """Normalize a category while preserving readable capitalization."""
        text = cls._safe_string(value)
        text = cls._WHITESPACE_PATTERN.sub(" ", text)
        return text.strip()

    @staticmethod
    def _normalize_column_name(value: object) -> str:
        """Normalize dataframe column names for validation."""
        return str(value).strip().casefold().replace(" ", "").replace("_", "")

    @staticmethod
    def _safe_string(value: object) -> str:
        """Convert non-empty scalar values to strings."""
        if value is None:
            return ""
        try:
            if pd.isna(value):
                return ""
        except TypeError:
            pass
        return str(value).strip()

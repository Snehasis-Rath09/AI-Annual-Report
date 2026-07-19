"""Tests for dictionary, keyword, and category analysis components."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.keyword_analysis.category_counter import CategoryCounter
from src.keyword_analysis.dictionary_loader import (
    KeywordDictionaryConfig,
    KeywordDictionaryLoader,
)
from src.keyword_analysis.keyword_counter import KeywordCounter


def _dictionary_loader(path: Path) -> KeywordDictionaryLoader:
    """Create a dictionary loader configured for a test path."""
    return KeywordDictionaryLoader(KeywordDictionaryConfig(dictionary_path=path))


def test_dictionary_loading_groups_and_normalizes_keywords(tmp_path: Path) -> None:
    """Dictionary rows should be normalized and grouped by category."""
    dictionary_path = tmp_path / "dictionary.xlsx"
    dictionary_path.touch()
    frame = pd.DataFrame(
        {
            "Category": ["AI", "AI", "Innovation"],
            "Keyword": ["Artificial Intelligence", "Machine-Learning", "R&D"],
            "Rationale": ["Core AI", "Predictive systems", "Research"],
        },
    )
    loader = _dictionary_loader(dictionary_path)
    with patch("pandas.read_excel", return_value=frame) as read_excel:
        dictionary = loader.load_dictionary()

    read_excel.assert_called_once_with(dictionary_path)
    assert dictionary == {
        "AI": ("machine learning", "artificial intelligence"),
        "Innovation": ("r and d",),
    }
    assert loader.get_categories() == ("AI", "Innovation")
    assert set(loader.get_all_keywords()) == {
        "artificial intelligence",
        "machine learning",
        "r and d",
    }


def test_duplicate_keywords_are_removed(tmp_path: Path) -> None:
    """Duplicate normalized category/keyword pairs should appear once."""
    dictionary_path = tmp_path / "dictionary.xlsx"
    dictionary_path.touch()
    frame = pd.DataFrame(
        {
            "Category": ["AI", "AI", "AI"],
            "Keyword": [
                "Machine Learning",
                "machine-learning",
                " MACHINE LEARNING ",
            ],
        },
    )
    loader = _dictionary_loader(dictionary_path)
    with patch("pandas.read_excel", return_value=frame):
        dictionary = loader.load_dictionary()

    assert dictionary == {"AI": ("machine learning",)}
    assert len(loader.get_entries()) == 1


def test_empty_dictionary_raises_value_error(tmp_path: Path) -> None:
    """A dictionary with headers but no usable rows should be rejected."""
    dictionary_path = tmp_path / "empty.xlsx"
    dictionary_path.touch()
    frame = pd.DataFrame(columns=["Category", "Keyword"])
    loader = _dictionary_loader(dictionary_path)
    with patch("pandas.read_excel", return_value=frame):
        with pytest.raises(ValueError, match="no valid keywords"):
            loader.load_dictionary()


def test_dictionary_missing_required_columns_raises_value_error(
    tmp_path: Path,
) -> None:
    """Malformed dictionary schemas should report missing required columns."""
    dictionary_path = tmp_path / "invalid.xlsx"
    dictionary_path.touch()
    loader = _dictionary_loader(dictionary_path)
    with patch(
        "pandas.read_excel",
        return_value=pd.DataFrame({"Term": ["AI"]}),
    ):
        with pytest.raises(ValueError, match="missing required columns"):
            loader.load_dictionary()


def test_keyword_counting_across_sections() -> None:
    """Counts should remain separated by source section."""
    loader = MagicMock()
    loader.get_all_keywords.return_value = ("ai", "innovation")
    counter = KeywordCounter(loader)
    sections = {
        "Strategy": "AI and innovation guide our AI strategy.",
        "Research": "Innovation enables delivery.",
    }

    counts = counter.count_keywords(sections)

    assert counts == {
        "Strategy": {"ai": 2, "innovation": 1},
        "Research": {"innovation": 1},
    }


def test_multi_word_keyword_uses_whole_phrase_boundaries() -> None:
    """Multi-word phrases should count exactly without partial-word matches."""
    counter = KeywordCounter(MagicMock())
    text = (
        "Machine learning improves decisions. MACHINE LEARNING scales, while "
        "machine learning-based wording is also normalized as a phrase."
    )

    assert counter.count_keyword(text, "machine learning") == 3
    assert (
        counter.count_keyword(
            "Artificially intelligent",
            "artificial intelligence",
        )
        == 0
    )


def test_keyword_counting_is_case_insensitive() -> None:
    """Keyword matching should be independent of source capitalization."""
    counter = KeywordCounter(MagicMock())
    text = "Innovation INNOVATION innovation InNoVaTiOn"
    assert counter.count_keyword(text, "innovation") == 4


def test_keyword_matching_uses_word_boundaries() -> None:
    """Short keywords should not match inside longer words."""
    counter = KeywordCounter(MagicMock())
    assert counter.count_keyword("AI supports fair systems in retail.", "ai") == 1


def test_category_density_is_calculated_per_thousand_words() -> None:
    """Category density should use the configured per-1,000-word formula."""
    loader = MagicMock()
    loader.get_categories.return_value = ("AI",)
    loader.get_keywords.return_value = ("ai",)
    counter = CategoryCounter(loader, MagicMock())
    sections = {"Innovation": " ".join(["word"] * 100)}
    keyword_counts = {"Innovation": {"ai": 2}}

    statistics = counter.calculate_category_statistics(sections, keyword_counts)

    assert statistics["AI"]["count"] == 2
    assert statistics["AI"]["word_count"] == 100
    assert statistics["AI"]["density"] == pytest.approx(20.0)


def test_category_statistics_include_presence_and_percentage() -> None:
    """Category summaries should include counts, presence, and contribution."""
    loader = MagicMock()
    loader.get_categories.return_value = ("AI", "Patents", "Automation")
    loader.get_keywords.side_effect = lambda category: {
        "AI": ("ai", "machine learning"),
        "Patents": ("patent",),
        "Automation": ("automation",),
    }[category]
    category_counter = CategoryCounter(loader, MagicMock())
    counts = {
        "Innovation": {
            "ai": 2,
            "machine learning": 1,
            "patent": 1,
        },
    }

    statistics = category_counter.calculate_category_statistics(
        {"Innovation": "AI machine learning patent disclosure"},
        counts,
    )

    assert statistics["AI"]["count"] == 3
    assert statistics["AI"]["present"] is True
    assert statistics["AI"]["percentage_contribution"] == pytest.approx(75.0)
    assert statistics["Patents"]["count"] == 1
    assert statistics["Patents"]["percentage_contribution"] == pytest.approx(25.0)
    assert statistics["Automation"]["count"] == 0
    assert statistics["Automation"]["present"] is False


def test_category_excel_records_include_company_identifier() -> None:
    """Tabular category records should retain the supplied company identity."""
    counter = CategoryCounter(MagicMock(), MagicMock())
    records = counter.to_excel_records(
        {"AI": {"count": 3, "density": 1.5, "present": True}},
        company_id="TCS",
    )
    assert records == [
        {
            "category": "AI",
            "company_id": "TCS",
            "count": 3,
            "density": 1.5,
            "present": True,
        },
    ]


def test_loader_accepts_temporary_directory_path() -> None:
    """Dictionary configuration should support standard temporary paths."""
    with TemporaryDirectory() as directory:
        path = Path(directory) / "dictionary.xlsx"
        loader = _dictionary_loader(path)
        assert loader.dictionary_path == path

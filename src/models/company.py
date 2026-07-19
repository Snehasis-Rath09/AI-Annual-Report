"""Company data model used throughout the annual-report pipeline."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse


CountMapping = dict[str, int]
KeywordCountMapping = dict[str, int | CountMapping]
SectionMapping = dict[str, str]


@dataclass
class Company:
    """Represent a company and its annual-report processing results.

    Args:
        company_name: Registered or commonly used company name.
        ticker: Stock-exchange ticker symbol.
        industry: Industry classification.
        report_year: Financial year represented by the annual report.
        report_path: Local path to the source annual report.
        source_url: HTTP(S) URL from which the report was obtained.
        extracted_text_path: Optional path to extracted plain text.
        extracted_sections: Optional mapping of section names to extracted text.
        keyword_counts: Optional flat keyword counts or section-level counts.
        category_counts: Optional mapping of categories to occurrence counts.
        disclosure_score: Optional disclosure score on a 0--100 scale.

    Raises:
        TypeError: If a field has an incompatible type.
        ValueError: If a field contains an invalid value.
    """

    company_name: str
    ticker: str
    industry: str
    report_year: int
    report_path: Path | str
    source_url: str
    extracted_text_path: Path | str | None = None
    extracted_sections: SectionMapping = field(default_factory=dict)
    keyword_counts: KeywordCountMapping = field(default_factory=dict)
    category_counts: CountMapping = field(default_factory=dict)
    disclosure_score: float | None = None

    def __post_init__(self) -> None:
        """Normalize field values and validate the initialized model."""
        self.company_name = self._clean_required_text(
            self.company_name,
            "company_name",
        )
        self.ticker = self._clean_required_text(self.ticker, "ticker").upper()
        self.industry = self._clean_required_text(self.industry, "industry")
        self.report_path = self._coerce_path(self.report_path, "report_path")
        if self.extracted_text_path is not None:
            self.extracted_text_path = self._coerce_path(
                self.extracted_text_path,
                "extracted_text_path",
            )
        self.source_url = self._clean_required_text(self.source_url, "source_url")
        self.extracted_sections = self._validate_sections(self.extracted_sections)
        self.keyword_counts = self._validate_keyword_counts(self.keyword_counts)
        self.category_counts = self._validate_counts(
            self.category_counts,
            "category_counts",
        )
        if self.disclosure_score is not None:
            if isinstance(self.disclosure_score, bool) or not isinstance(
                self.disclosure_score,
                (int, float),
            ):
                raise TypeError("disclosure_score must be a number or None.")
            self.disclosure_score = float(self.disclosure_score)
        self.validate()

    def validate(self, *, require_report_exists: bool = False) -> None:
        """Validate model invariants.

        Args:
            require_report_exists: Require the local annual-report path to exist.

        Raises:
            TypeError: If ``report_year`` is not an integer.
            ValueError: If a year, URL, score, or required path is invalid.
            FileNotFoundError: If the report is required but does not exist.
        """
        if isinstance(self.report_year, bool) or not isinstance(self.report_year, int):
            raise TypeError("report_year must be an integer.")
        maximum_year = date.today().year + 1
        if not 1900 <= self.report_year <= maximum_year:
            raise ValueError(
                f"report_year must be between 1900 and {maximum_year}.",
            )

        parsed_url = urlparse(self.source_url)
        if parsed_url.scheme.lower() not in {"http", "https"} or not parsed_url.netloc:
            raise ValueError("source_url must be a valid HTTP(S) URL.")

        if (
            self.disclosure_score is not None
            and not 0.0 <= self.disclosure_score <= 100.0
        ):
            raise ValueError("disclosure_score must be between 0 and 100.")

        if require_report_exists and not self.report_path.is_file():
            raise FileNotFoundError(
                f"Annual report does not exist or is not a file: {self.report_path}",
            )

    def to_dict(self) -> dict[str, Any]:
        """Serialize the company to JSON-compatible built-in values.

        Returns:
            A new dictionary containing all model fields.
        """
        return {
            "company_name": self.company_name,
            "ticker": self.ticker,
            "industry": self.industry,
            "report_year": self.report_year,
            "report_path": str(self.report_path),
            "source_url": self.source_url,
            "extracted_text_path": (
                str(self.extracted_text_path)
                if self.extracted_text_path is not None
                else None
            ),
            "extracted_sections": deepcopy(self.extracted_sections),
            "keyword_counts": deepcopy(self.keyword_counts),
            "category_counts": deepcopy(self.category_counts),
            "disclosure_score": self.disclosure_score,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Company:
        """Deserialize a company from a mapping.

        Args:
            data: Mapping containing serialized company fields.

        Returns:
            A validated ``Company`` instance.

        Raises:
            TypeError: If ``data`` is not a mapping.
            ValueError: If required or unknown fields are present incorrectly.
        """
        if not isinstance(data, Mapping):
            raise TypeError("data must be a mapping.")

        required = {
            "company_name",
            "ticker",
            "industry",
            "report_year",
            "report_path",
            "source_url",
        }
        optional = {
            "extracted_text_path",
            "extracted_sections",
            "keyword_counts",
            "category_counts",
            "disclosure_score",
        }
        missing = required.difference(data)
        unknown = set(data).difference(required | optional)
        if missing:
            raise ValueError(f"Missing required fields: {', '.join(sorted(missing))}.")
        if unknown:
            raise ValueError(f"Unknown fields: {', '.join(sorted(unknown))}.")
        return cls(**deepcopy(dict(data)))

    def __str__(self) -> str:
        """Return a concise human-readable company description."""
        return f"{self.company_name} ({self.ticker}) - Annual Report {self.report_year}"

    def __repr__(self) -> str:
        """Return an unambiguous representation of the core model fields."""
        return (
            f"Company(company_name={self.company_name!r}, ticker={self.ticker!r}, "
            f"industry={self.industry!r}, report_year={self.report_year!r}, "
            f"report_path={self.report_path!r}, source_url={self.source_url!r}, "
            f"extracted_text_path={self.extracted_text_path!r}, "
            f"extracted_sections={self.extracted_sections!r}, "
            f"keyword_counts={self.keyword_counts!r}, "
            f"category_counts={self.category_counts!r}, "
            f"disclosure_score={self.disclosure_score!r})"
        )

    @staticmethod
    def _clean_required_text(value: object, field_name: str) -> str:
        """Return stripped required text or raise a descriptive error."""
        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be a string.")
        cleaned = value.strip()
        if not cleaned:
            raise ValueError(f"{field_name} cannot be empty.")
        return cleaned

    @staticmethod
    def _coerce_path(value: Path | str, field_name: str) -> Path:
        """Convert a non-empty string or path-like value to ``Path``."""
        if not isinstance(value, (str, Path)):
            raise TypeError(f"{field_name} must be a string or Path.")
        if not str(value).strip():
            raise ValueError(f"{field_name} cannot be empty.")
        return Path(value).expanduser()

    @classmethod
    def _validate_sections(cls, sections: Mapping[str, str]) -> SectionMapping:
        """Validate and copy extracted section data."""
        if not isinstance(sections, Mapping):
            raise TypeError("extracted_sections must be a mapping.")
        validated: SectionMapping = {}
        for name, text in sections.items():
            clean_name = cls._clean_required_text(name, "section name")
            if not isinstance(text, str):
                raise TypeError(f"Text for section {clean_name!r} must be a string.")
            validated[clean_name] = text
        return validated

    @classmethod
    def _validate_counts(
        cls,
        counts: Mapping[str, int],
        field_name: str,
    ) -> CountMapping:
        """Validate and copy a non-negative integer count mapping."""
        if not isinstance(counts, Mapping):
            raise TypeError(f"{field_name} must be a mapping.")
        validated: CountMapping = {}
        for name, count in counts.items():
            clean_name = cls._clean_required_text(name, f"{field_name} key")
            if isinstance(count, bool) or not isinstance(count, int):
                raise TypeError(f"Count for {clean_name!r} must be an integer.")
            if count < 0:
                raise ValueError(f"Count for {clean_name!r} cannot be negative.")
            validated[clean_name] = count
        return validated

    @classmethod
    def _validate_keyword_counts(
        cls,
        counts: Mapping[str, int | Mapping[str, int]],
    ) -> KeywordCountMapping:
        """Validate flat or section-level keyword counts without flattening."""
        if not isinstance(counts, Mapping):
            raise TypeError("keyword_counts must be a mapping.")
        validated: KeywordCountMapping = {}
        for name, value in counts.items():
            clean_name = cls._clean_required_text(name, "keyword_counts key")
            if isinstance(value, Mapping):
                validated[clean_name] = cls._validate_counts(
                    value,
                    f"keyword_counts[{clean_name!r}]",
                )
                continue
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"Count for {clean_name!r} must be an integer.")
            if value < 0:
                raise ValueError(f"Count for {clean_name!r} cannot be negative.")
            validated[clean_name] = value
        return validated

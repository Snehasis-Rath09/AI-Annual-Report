"""Validation framework for manual and automated disclosure counts."""

from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from config import settings
from src.models.company import Company
from src.utils.logger import get_logger


logger = get_logger(__name__)

CountInput = Mapping[str, int | Mapping[str, int]]
CompanyCountInput = Mapping[str, CountInput]


@dataclass(frozen=True)
class ValidationMetrics:
    """Occurrence-level confusion counts and derived validation metrics."""

    true_positives: int
    false_positives: int
    false_negatives: int
    true_negatives: int = 0
    precision: float = 0.0
    recall: float = 0.0
    f1_score: float = 0.0
    accuracy: float = 0.0


class DisclosureValidator:
    """Compare automated keyword counts with manually verified counts.

    Counts are evaluated at occurrence level. For each keyword, the lower of
    the manual and automated counts is treated as correctly detected; excess
    automated occurrences are false positives and excess manual occurrences
    are false negatives. Accuracy is the Jaccard-style count agreement when no
    explicit true-negative count is available.
    """

    _COMPANY_COLUMNS = ("company", "company_name", "ticker")
    _KEYWORD_COLUMNS = ("keyword", "term", "phrase")
    _MANUAL_COUNT_COLUMNS = (
        "manual_count",
        "verified_count",
        "manual_keyword_count",
        "count",
    )

    def __init__(
        self,
        manual_validation_path: str | Path | None = None,
        *,
        decimals: int = 4,
    ) -> None:
        """Initialize the validator.

        Args:
            manual_validation_path: Default source of manual validation data.
            decimals: Decimal places used for reported metrics.

        Raises:
            ValueError: If ``decimals`` is negative.
        """
        if decimals < 0:
            raise ValueError("decimals cannot be negative.")
        self.manual_validation_path = Path(
            manual_validation_path or settings.VALIDATION_FILE,
        )
        self.decimals = decimals
        self.manual_counts: dict[str, dict[str, int]] = {}
        self.validation_results: list[dict[str, Any]] = []

    def load_manual_validation(
        self,
        source: str | Path | pd.DataFrame | CompanyCountInput | None = None,
    ) -> dict[str, dict[str, int]]:
        """Load and normalize manually verified keyword counts.

        Supported files are CSV, JSON, XLS, XLSX, and XLSM. Tabular data can be
        long form (company, keyword, manual_count) or wide form (one company
        row with keyword columns).

        Args:
            source: File path, dataframe, nested mapping, or the configured path.

        Returns:
            Company names mapped to normalized keyword-count dictionaries.

        Raises:
            FileNotFoundError: If a requested input file does not exist.
            ValueError: If the input format or values are invalid.
            TypeError: If ``source`` has an unsupported type.
        """
        logger.info("Validation started")
        try:
            selected = self.manual_validation_path if source is None else source
            if isinstance(selected, pd.DataFrame):
                loaded = self._dataframe_to_company_counts(selected)
            elif isinstance(selected, Mapping):
                loaded = self._normalize_company_counts(selected)
            elif isinstance(selected, (str, Path)):
                path = Path(selected)
                if not path.is_file():
                    raise FileNotFoundError(f"Manual validation file not found: {path}")
                loaded = self._load_validation_file(path)
            else:
                raise TypeError(
                    "source must be a path, DataFrame, nested mapping, or None.",
                )

            if not loaded:
                logger.warning("Manual validation data is empty")
            for company_name in loaded:
                logger.info("Company loaded: %s", company_name)
            self.manual_counts = loaded
            return {name: dict(counts) for name, counts in loaded.items()}
        except Exception as exc:
            logger.exception("Errors loading manual validation data: %s", exc)
            raise

    def compare_counts(
        self,
        manual_counts: CountInput,
        automated_counts: CountInput,
    ) -> dict[str, dict[str, int | bool]]:
        """Compare manual and automated counts keyword by keyword.

        Args:
            manual_counts: Manually verified flat or section-level counts.
            automated_counts: Automated flat or section-level counts.

        Returns:
            Per-keyword counts, differences, and exact-match indicators.
        """
        manual = self._flatten_counts(manual_counts)
        automated = self._flatten_counts(automated_counts)
        comparison: dict[str, dict[str, int | bool]] = {}
        for keyword in sorted(set(manual) | set(automated)):
            manual_count = manual.get(keyword, 0)
            automated_count = automated.get(keyword, 0)
            comparison[keyword] = {
                "manual_count": manual_count,
                "automated_count": automated_count,
                "difference": automated_count - manual_count,
                "matched_count": min(manual_count, automated_count),
                "is_exact_match": manual_count == automated_count,
            }
        return comparison

    def calculate_precision(
        self,
        true_positives: int,
        false_positives: int,
    ) -> float:
        """Calculate precision as ``TP / (TP + FP)``."""
        self._validate_confusion_counts(true_positives, false_positives)
        denominator = true_positives + false_positives
        return self._round(true_positives / denominator) if denominator else 0.0

    def calculate_recall(self, true_positives: int, false_negatives: int) -> float:
        """Calculate recall as ``TP / (TP + FN)``."""
        self._validate_confusion_counts(true_positives, false_negatives)
        denominator = true_positives + false_negatives
        return self._round(true_positives / denominator) if denominator else 0.0

    def calculate_f1_score(self, precision: float, recall: float) -> float:
        """Calculate the harmonic mean of precision and recall."""
        for name, value in (("precision", precision), ("recall", recall)):
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise TypeError(f"{name} must be numeric.")
            if not 0.0 <= float(value) <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1.")
        denominator = precision + recall
        if not denominator:
            return 0.0
        return self._round((2 * precision * recall) / denominator)

    def calculate_accuracy(
        self,
        true_positives: int,
        false_positives: int,
        false_negatives: int,
        true_negatives: int = 0,
    ) -> float:
        """Calculate count-level accuracy.

        With true negatives, this is standard classification accuracy. Without
        them, it is occurrence-level Jaccard agreement: ``TP / (TP + FP + FN)``.
        """
        self._validate_confusion_counts(
            true_positives,
            false_positives,
            false_negatives,
            true_negatives,
        )
        denominator = (
            true_positives + false_positives + false_negatives + true_negatives
        )
        numerator = true_positives + true_negatives
        return self._round(numerator / denominator) if denominator else 1.0

    def find_missing_keywords(
        self,
        manual_counts: CountInput,
        automated_counts: CountInput,
    ) -> list[str]:
        """Return keywords with fewer automated than manual occurrences."""
        comparison = self.compare_counts(manual_counts, automated_counts)
        return [
            keyword
            for keyword, values in comparison.items()
            if int(values["manual_count"]) > int(values["automated_count"])
        ]

    def find_false_matches(
        self,
        manual_counts: CountInput,
        automated_counts: CountInput,
    ) -> list[str]:
        """Return keywords with excess automated occurrences."""
        comparison = self.compare_counts(manual_counts, automated_counts)
        return [
            keyword
            for keyword, values in comparison.items()
            if int(values["automated_count"]) > int(values["manual_count"])
        ]

    def validate_company(
        self,
        company: Company | str,
        automated_counts: CountInput | None = None,
        manual_counts: CountInput | None = None,
    ) -> dict[str, Any]:
        """Validate automated results for one company.

        Args:
            company: Company model or company identifier.
            automated_counts: Counts to validate. Defaults to model counts.
            manual_counts: Optional manual counts overriding loaded data.

        Returns:
            Structured validation result.

        Raises:
            KeyError: If no manual counts exist for the company.
            ValueError: If automated counts are not supplied for a string name.
        """
        company_name = (
            company.company_name
            if isinstance(company, Company)
            else str(company).strip()
        )
        if not company_name:
            raise ValueError("company cannot be empty.")
        if automated_counts is None:
            if not isinstance(company, Company):
                raise ValueError("automated_counts are required for a company name.")
            automated_counts = company.keyword_counts
        selected_manual = manual_counts
        if selected_manual is None:
            identifiers = (
                (company.company_name, company.ticker)
                if isinstance(company, Company)
                else (company_name,)
            )
            selected_manual = self._get_first_company_counts(identifiers)

        comparison = self.compare_counts(selected_manual, automated_counts)
        true_positives = sum(int(row["matched_count"]) for row in comparison.values())
        false_positives = sum(
            max(int(row["difference"]), 0) for row in comparison.values()
        )
        false_negatives = sum(
            max(-int(row["difference"]), 0) for row in comparison.values()
        )
        precision = self.calculate_precision(true_positives, false_positives)
        recall = self.calculate_recall(true_positives, false_negatives)
        f1_score = self.calculate_f1_score(precision, recall)
        accuracy = self.calculate_accuracy(
            true_positives,
            false_positives,
            false_negatives,
        )
        metrics = ValidationMetrics(
            true_positives=true_positives,
            false_positives=false_positives,
            false_negatives=false_negatives,
            precision=precision,
            recall=recall,
            f1_score=f1_score,
            accuracy=accuracy,
        )
        result: dict[str, Any] = {
            "company": company_name,
            "precision": metrics.precision,
            "recall": metrics.recall,
            "f1_score": metrics.f1_score,
            "accuracy": metrics.accuracy,
            "missing_keywords": self.find_missing_keywords(
                selected_manual,
                automated_counts,
            ),
            "false_matches": self.find_false_matches(
                selected_manual,
                automated_counts,
            ),
            "comments": self._generate_observation(metrics),
        }
        logger.info("Metrics calculated for company: %s", company_name)
        return result

    def generate_validation_report(
        self,
        automated_results: CompanyCountInput | Sequence[Company],
        manual_data: CompanyCountInput | None = None,
    ) -> list[dict[str, Any]]:
        """Generate a validation report for multiple companies.

        Args:
            automated_results: Company/count mapping or sequence of models.
            manual_data: Optional manual data replacing previously loaded data.

        Returns:
            One structured validation result per company.
        """
        logger.info("Validation started")
        try:
            if manual_data is not None:
                self.manual_counts = self._normalize_company_counts(manual_data)
            elif not self.manual_counts:
                self.load_manual_validation()

            results: list[dict[str, Any]] = []
            if isinstance(automated_results, Mapping):
                for company_name, counts in automated_results.items():
                    logger.info("Company loaded: %s", company_name)
                    results.append(self.validate_company(str(company_name), counts))
            elif isinstance(automated_results, Sequence) and not isinstance(
                automated_results,
                (str, bytes),
            ):
                for company in automated_results:
                    if not isinstance(company, Company):
                        raise TypeError(
                            "automated_results sequences must contain Company models.",
                        )
                    logger.info("Company loaded: %s", company.company_name)
                    results.append(self.validate_company(company))
            else:
                raise TypeError(
                    "automated_results must be a company/count mapping or "
                    "Company sequence.",
                )

            self.validation_results = results
            logger.info("Validation completed for %s companies", len(results))
            return [dict(result) for result in results]
        except Exception as exc:
            logger.exception("Errors generating validation report: %s", exc)
            raise

    def export_validation_summary(
        self,
        summary: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None = None,
        output_path: str | Path | None = None,
    ) -> Path:
        """Export validation results to Excel, CSV, or JSON.

        Args:
            summary: Results to export. Defaults to the latest report.
            output_path: Destination path. Defaults to an Excel file in the
                configured validation directory.

        Returns:
            Path to the exported summary.
        """
        selected = self.validation_results if summary is None else summary
        records = [selected] if isinstance(selected, Mapping) else list(selected)
        if not records:
            raise ValueError("No validation results are available for export.")
        destination = Path(
            output_path or settings.VALIDATION_DIR / "validation_summary.xlsx",
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        frame = pd.DataFrame(records)
        for column in ("missing_keywords", "false_matches"):
            if column in frame.columns:
                frame[column] = frame[column].apply(
                    lambda value: ", ".join(map(str, value))
                    if isinstance(value, (list, tuple, set))
                    else value,
                )
        try:
            suffix = destination.suffix.lower()
            if suffix == ".csv":
                frame.to_csv(destination, index=False)
            elif suffix == ".json":
                frame.to_json(destination, orient="records", indent=2)
            elif suffix in {".xlsx", ".xlsm"}:
                frame.to_excel(destination, index=False)
            else:
                raise ValueError(
                    "Output must have an .xlsx, .xlsm, .csv, or .json "
                    "extension.",
                )
            logger.info("Validation completed; summary exported: %s", destination)
            return destination
        except Exception as exc:
            logger.exception("Errors exporting validation summary: %s", exc)
            raise

    def _load_validation_file(self, path: Path) -> dict[str, dict[str, int]]:
        """Load manual data from a supported local file."""
        suffix = path.suffix.lower()
        if suffix == ".csv":
            return self._dataframe_to_company_counts(pd.read_csv(path))
        if suffix in settings.SUPPORTED_EXCEL_EXTENSIONS:
            return self._dataframe_to_company_counts(pd.read_excel(path))
        if suffix == ".json":
            with path.open("r", encoding="utf-8") as file_handle:
                payload = json.load(file_handle)
            if isinstance(payload, Mapping):
                return self._normalize_company_counts(payload)
            if isinstance(payload, list):
                return self._dataframe_to_company_counts(pd.DataFrame(payload))
            raise ValueError("JSON validation data must be an object or array.")
        raise ValueError(f"Unsupported manual validation file type: {suffix}")

    def _dataframe_to_company_counts(
        self,
        frame: pd.DataFrame,
    ) -> dict[str, dict[str, int]]:
        """Convert long- or wide-form validation data to nested counts."""
        if frame.empty:
            return {}
        normalized = frame.copy()
        normalized.columns = [
            str(column).strip().casefold().replace(" ", "_")
            for column in normalized.columns
        ]
        company_column = self._first_column(normalized, self._COMPANY_COLUMNS)
        if company_column is None:
            raise ValueError(
                "Validation data requires a company, company_name, or ticker "
                "column.",
            )
        keyword_column = self._first_column(normalized, self._KEYWORD_COLUMNS)
        count_column = self._first_column(normalized, self._MANUAL_COUNT_COLUMNS)

        records: dict[str, Counter[str]] = {}
        if keyword_column and count_column:
            for _, row in normalized.iterrows():
                company = self._clean_label(row[company_column], "company")
                keyword = self._clean_label(
                    row[keyword_column],
                    "keyword",
                ).casefold()
                count = self._coerce_count(row[count_column], keyword)
                records.setdefault(company, Counter())[keyword] += count
        else:
            metadata = set(self._COMPANY_COLUMNS) | {
                "industry",
                "report_year",
                "year",
                "source_url",
                "report_path",
            }
            keyword_columns = [
                column for column in normalized.columns if column not in metadata
            ]
            if not keyword_columns:
                raise ValueError(
                    "Wide validation data does not contain keyword columns.",
                )
            for _, row in normalized.iterrows():
                company = self._clean_label(row[company_column], "company")
                company_counts = records.setdefault(company, Counter())
                for column in keyword_columns:
                    company_counts[column] += self._coerce_count(row[column], column)
        return {company: dict(counts) for company, counts in records.items()}

    def _normalize_company_counts(
        self,
        data: Mapping[str, CountInput],
    ) -> dict[str, dict[str, int]]:
        """Validate a company-to-counts mapping."""
        normalized: dict[str, dict[str, int]] = {}
        for company, counts in data.items():
            company_name = self._clean_label(company, "company")
            if not isinstance(counts, Mapping):
                raise TypeError(f"Counts for {company_name!r} must be a mapping.")
            normalized[company_name] = dict(self._flatten_counts(counts))
        return normalized

    def _flatten_counts(self, counts: CountInput) -> Counter[str]:
        """Flatten section-level or flat counts using normalized keywords."""
        if not isinstance(counts, Mapping):
            raise TypeError("counts must be a mapping.")
        flattened: Counter[str] = Counter()
        for key, value in counts.items():
            if isinstance(value, Mapping):
                for keyword, count in value.items():
                    label = self._clean_label(keyword, "keyword").casefold()
                    flattened[label] += self._coerce_count(count, label)
            else:
                label = self._clean_label(key, "keyword").casefold()
                flattened[label] += self._coerce_count(value, label)
        return flattened

    def _get_company_counts(self, company_name: str) -> dict[str, int]:
        """Find loaded manual counts with case-insensitive company matching."""
        normalized_name = company_name.casefold()
        for loaded_name, counts in self.manual_counts.items():
            if loaded_name.casefold() == normalized_name:
                return dict(counts)
        raise KeyError(f"No manual validation data found for company: {company_name}")

    def _get_first_company_counts(
        self,
        identifiers: Sequence[str],
    ) -> dict[str, int]:
        """Find manual counts using the first matching company identifier.

        Args:
            identifiers: Company names or ticker symbols in preference order.

        Returns:
            A copy of the matching manual keyword counts.

        Raises:
            KeyError: If none of the identifiers exists in loaded manual data.
        """
        for identifier in identifiers:
            try:
                return self._get_company_counts(identifier)
            except KeyError:
                continue
        joined = ", ".join(identifiers)
        raise KeyError(f"No manual validation data found for: {joined}")

    def _generate_observation(self, metrics: ValidationMetrics) -> str:
        """Generate a concise quality observation from configured thresholds."""
        minimum_precision = float(
            settings.VALIDATION_CONFIG["min_keyword_precision"],
        )
        minimum_recall = float(settings.VALIDATION_CONFIG["min_keyword_recall"])
        if metrics.precision >= 0.9 and metrics.recall >= 0.9:
            return "High extraction quality"
        if metrics.precision >= minimum_precision and metrics.recall >= minimum_recall:
            return "Acceptable extraction quality; review count differences"
        if metrics.precision < minimum_precision and metrics.recall < minimum_recall:
            return "Low extraction quality; review false matches and missing keywords"
        if metrics.precision < minimum_precision:
            return "Precision below threshold; review false matches"
        return "Recall below threshold; review missing keywords"

    def _round(self, value: float) -> float:
        """Round a metric using validator precision."""
        return round(float(value), self.decimals)

    @staticmethod
    def _validate_confusion_counts(*values: int) -> None:
        """Validate non-negative integer confusion counts."""
        for value in values:
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError("Confusion counts must be integers.")
            if value < 0:
                raise ValueError("Confusion counts cannot be negative.")

    @staticmethod
    def _first_column(frame: pd.DataFrame, candidates: Sequence[str]) -> str | None:
        """Return the first candidate column present in a dataframe."""
        return next((column for column in candidates if column in frame.columns), None)

    @staticmethod
    def _clean_label(value: object, field_name: str) -> str:
        """Normalize a non-empty label."""
        if pd.isna(value):
            raise ValueError(f"{field_name} cannot be missing.")
        label = " ".join(str(value).strip().split())
        if not label:
            raise ValueError(f"{field_name} cannot be empty.")
        return label

    @staticmethod
    def _coerce_count(value: object, keyword: str) -> int:
        """Coerce a finite, non-negative integer-like count."""
        if pd.isna(value):
            return 0
        if isinstance(value, bool):
            raise TypeError(f"Count for {keyword!r} must be an integer.")
        if isinstance(value, int):
            count = value
        elif isinstance(value, float) and math.isfinite(value) and value.is_integer():
            count = int(value)
        else:
            try:
                numeric = float(str(value).strip())
            except (TypeError, ValueError) as exc:
                raise TypeError(f"Count for {keyword!r} must be an integer.") from exc
            if not math.isfinite(numeric) or not numeric.is_integer():
                raise ValueError(f"Count for {keyword!r} must be a finite integer.")
            count = int(numeric)
        if count < 0:
            raise ValueError(f"Count for {keyword!r} cannot be negative.")
        return count

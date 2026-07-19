"""End-to-end orchestration for annual-report disclosure analysis."""

from __future__ import annotations

import re
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from config import settings
from src.export.excel_exporter import ExcelExporter, ExcelExporterConfig
from src.extraction.pdf_extractor import PDFExtractor
from src.keyword_analysis.category_counter import CategoryCounter
from src.keyword_analysis.dictionary_loader import (
    KeywordDictionaryConfig,
    KeywordDictionaryLoader,
)
from src.keyword_analysis.keyword_counter import KeywordCounter
from src.models.company import Company
from src.preprocessing.clean_text import TextCleaner
from src.preprocessing.normalize_text import TextNormalizer
from src.scoring.disclosure_score import DisclosureScoreCalculator
from src.scoring.metrics import DisclosureMetrics
from src.section_extraction.heading_detector import HeadingDetector
from src.section_extraction.section_extractor import SectionExtractor
from src.utils.logger import get_logger
from src.validation.validator import DisclosureValidator


logger = get_logger(__name__)


class AnnualReportPipeline:
    """Coordinate annual-report extraction, analysis, scoring, and export."""

    _COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
        "company_name": ("companyname", "company", "name"),
        "ticker": ("ticker", "symbol", "stocksymbol", "nseticker"),
        "industry": ("industry", "sector", "industryclassification"),
        "report_year": ("reportyear", "year", "financialyear", "fiscalyear"),
        "report_path": ("reportpath", "pdfpath", "filepath", "annualreport"),
        "source_url": ("sourceurl", "url", "reporturl", "downloadurl"),
    }

    def __init__(
        self,
        company_master_path: str | Path | None = None,
        dictionary_path: str | Path | None = None,
        output_dir: str | Path | None = None,
        *,
        pdf_extractor: PDFExtractor | None = None,
        text_cleaner: TextCleaner | None = None,
        text_normalizer: TextNormalizer | None = None,
        heading_detector: HeadingDetector | None = None,
        section_extractor: SectionExtractor | None = None,
        dictionary_loader: KeywordDictionaryLoader | None = None,
        keyword_counter: KeywordCounter | None = None,
        category_counter: CategoryCounter | None = None,
        metrics_calculator: DisclosureMetrics | None = None,
        score_calculator: DisclosureScoreCalculator | None = None,
        validator: DisclosureValidator | None = None,
    ) -> None:
        """Initialize pipeline configuration and injectable collaborators.

        Args:
            company_master_path: Company Master workbook or CSV path.
            dictionary_path: Innovation Dictionary workbook path.
            output_dir: Root directory for generated artifacts.
            pdf_extractor: Optional configured PDF extractor.
            text_cleaner: Optional text cleaner.
            text_normalizer: Optional text normalizer.
            heading_detector: Optional heading detector.
            section_extractor: Optional section extractor.
            dictionary_loader: Optional dictionary loader.
            keyword_counter: Optional keyword counter.
            category_counter: Optional category statistics calculator.
            metrics_calculator: Optional disclosure metrics calculator.
            score_calculator: Optional disclosure score calculator.
            validator: Optional manual validation service.
        """
        self.company_master_path = Path(
            company_master_path or settings.COMPANY_MASTER_FILE,
        )
        self.dictionary_path = Path(
            dictionary_path or settings.INNOVATION_DICTIONARY_FILE,
        )
        self.output_dir = Path(output_dir or settings.EXPORTS_DIR)
        self.text_output_dir = self.output_dir / "extracted_text"
        self.excel_output_dir = self.output_dir / "excel"
        self.report_output_dir = self.output_dir / "reports"

        self.pdf_extractor = pdf_extractor or PDFExtractor()
        self.text_cleaner = text_cleaner or TextCleaner()
        self.text_normalizer = text_normalizer or TextNormalizer()
        self.heading_detector = heading_detector or HeadingDetector()
        self.section_extractor = section_extractor or SectionExtractor(
            self.heading_detector,
        )
        self.dictionary_loader = dictionary_loader or KeywordDictionaryLoader(
            KeywordDictionaryConfig(dictionary_path=self.dictionary_path),
        )
        self.keyword_counter = keyword_counter or KeywordCounter(
            self.dictionary_loader,
        )
        self.category_counter = category_counter or CategoryCounter(
            self.dictionary_loader,
            self.keyword_counter,
        )
        self.metrics_calculator = metrics_calculator or DisclosureMetrics()
        self.score_calculator = score_calculator or DisclosureScoreCalculator(
            self.metrics_calculator,
        )
        self.validator = validator or DisclosureValidator()

        self.companies: list[Company] = []
        self.keyword_dictionary: dict[str, tuple[str, ...]] = {}
        self._initialized = False

    def initialize(self) -> None:
        """Load reference files and prepare output directories.

        Raises:
            FileNotFoundError: If a required reference file is missing.
            ValueError: If a reference file is empty or malformed.
        """
        if self._initialized:
            logger.info("Pipeline initialized")
            return
        try:
            for directory in (
                self.output_dir,
                self.text_output_dir,
                self.excel_output_dir,
                self.report_output_dir,
            ):
                directory.mkdir(parents=True, exist_ok=True)
            self.companies = self.load_company_master(self.company_master_path)
            self.keyword_dictionary = self.dictionary_loader.load_dictionary(
                self.dictionary_path,
            )
            self._initialized = True
            logger.info(
                "Pipeline initialized: companies=%s categories=%s keywords=%s",
                len(self.companies),
                len(self.keyword_dictionary),
                sum(len(values) for values in self.keyword_dictionary.values()),
            )
        except Exception as exc:
            logger.exception("Errors encountered while initializing pipeline: %s", exc)
            raise

    def load_company_master(
        self,
        source: str | Path | pd.DataFrame | None = None,
    ) -> list[Company]:
        """Load Company models from a Company Master table.

        Args:
            source: Excel/CSV path, dataframe, or configured master path.

        Returns:
            Validated company records in source order.
        """
        selected = self.company_master_path if source is None else source
        if isinstance(selected, pd.DataFrame):
            frame = selected.copy()
            base_dir = settings.PROJECT_ROOT
        else:
            path = Path(selected)
            if not path.is_file():
                raise FileNotFoundError(f"Company Master file not found: {path}")
            if path.stat().st_size == 0:
                raise ValueError(f"Company Master file is empty: {path}")
            if path.suffix.lower() == ".csv":
                frame = pd.read_csv(path)
            elif path.suffix.lower() in settings.SUPPORTED_EXCEL_EXTENSIONS:
                frame = pd.read_excel(path)
            else:
                raise ValueError("Company Master must be an Excel or CSV file.")
            base_dir = path.resolve().parent

        if frame.empty:
            raise ValueError("Company Master contains no company records.")
        column_map = self._resolve_company_columns(frame.columns)
        companies: list[Company] = []
        seen: set[tuple[str, int]] = set()
        for row_number, (_, row) in enumerate(frame.iterrows(), start=2):
            if row.isna().all():
                continue
            try:
                report_path = self._resolve_report_path(
                    self._required_cell(row[column_map["report_path"]], "report_path"),
                    base_dir,
                )
                company = Company(
                    company_name=self._required_cell(
                        row[column_map["company_name"]],
                        "company_name",
                    ),
                    ticker=self._required_cell(row[column_map["ticker"]], "ticker"),
                    industry=self._required_cell(
                        row[column_map["industry"]],
                        "industry",
                    ),
                    report_year=self._parse_year(row[column_map["report_year"]]),
                    report_path=report_path,
                    source_url=self._required_cell(
                        row[column_map["source_url"]],
                        "source_url",
                    ),
                )
                identity = (company.ticker.casefold(), company.report_year)
                if identity in seen:
                    logger.warning(
                        "Duplicate company/year ignored at row %s: %s %s",
                        row_number,
                        company.ticker,
                        company.report_year,
                    )
                    continue
                seen.add(identity)
                companies.append(company)
                logger.info("Company loaded: %s", company)
            except Exception as exc:
                raise ValueError(
                    f"Invalid Company Master row {row_number}: {exc}",
                ) from exc
        if not companies:
            raise ValueError("Company Master contains no valid company records.")
        return companies

    def process_company(self, company: Company) -> dict[str, Any]:
        """Process one annual report and produce all configured artifacts.

        Args:
            company: Company and annual-report metadata.

        Returns:
            Structured success or failure result. Processing exceptions are
            captured so a batch can continue with remaining companies.
        """
        started = time.perf_counter()
        logger.info("Company processing started: %s", company)
        try:
            self._ensure_initialized()
            company.validate(require_report_exists=True)
            logger.info("PDF loaded: %s", company.report_path)

            raw_text = self.pdf_extractor.extract_text(company.report_path)
            if not raw_text.strip():
                raise ValueError("PDF extraction returned empty text.")
            logger.info("Extraction completed: %s", company.ticker)

            cleaned_text = self.text_cleaner.clean(raw_text)
            normalized_text = self.text_normalizer.normalize(cleaned_text)
            if not normalized_text:
                raise ValueError("Text preprocessing returned empty text.")

            detected_headings = self.heading_detector.detect_headings(normalized_text)
            extracted_sections = self.section_extractor.extract_sections(
                normalized_text,
            )
            analysis_sections = extracted_sections
            used_full_report_fallback = False
            if not analysis_sections:
                logger.warning(
                    "No target sections found for %s; analyzing the full report",
                    company.ticker,
                )
                analysis_sections = {"Full Report": normalized_text}
                used_full_report_fallback = True

            keyword_counts = self.keyword_counter.count_keywords(
                analysis_sections,
                self.keyword_dictionary,
            )
            category_statistics = self.category_counter.calculate_category_statistics(
                analysis_sections,
                keyword_counts,
            )
            metrics = self.metrics_calculator.calculate_summary(
                analysis_sections,
                keyword_counts,
                self.keyword_dictionary,
            )
            logger.info("Keyword analysis completed: %s", company.ticker)

            score = self.score_calculator.calculate_score(
                analysis_sections,
                keyword_counts,
                self.keyword_dictionary,
            )
            overall_score = float(score["overall_score"])
            logger.info(
                "Disclosure score calculated: %s = %.4f",
                company.ticker,
                overall_score,
            )

            company.extracted_sections = dict(extracted_sections)
            company.keyword_counts = {
                section: dict(counts)
                for section, counts in keyword_counts.items()
            }
            company.category_counts = {
                category: int(values["count"])
                for category, values in category_statistics.items()
            }
            company.disclosure_score = overall_score

            text_path = self.save_extracted_text(company, normalized_text)
            company.extracted_text_path = text_path
            validation_ready = self._build_validation_ready_data(
                company,
                keyword_counts,
            )
            excel_path = self._export_workbook(
                company,
                score,
                metrics,
                category_statistics,
                extracted_sections,
                validation_ready,
            )
            logger.info("Excel exported: %s", excel_path)
            markdown_path = self.save_markdown_report(
                company,
                category_statistics,
                detected_headings,
                metrics,
            )
            logger.info("Markdown generated: %s", markdown_path)

            validation_result = self._run_optional_validation(company)
            elapsed = time.perf_counter() - started
            return {
                "company": company.company_name,
                "ticker": company.ticker,
                "report_year": company.report_year,
                "status": "SUCCESS",
                "disclosure_score": overall_score,
                "excel_path": excel_path,
                "text_path": text_path,
                "markdown_path": markdown_path,
                "validation_ready": True,
                "validation": validation_result,
                "metrics": metrics,
                "keyword_counts": company.keyword_counts,
                "category_statistics": category_statistics,
                "detected_sections": list(extracted_sections),
                "detected_headings": detected_headings,
                "used_full_report_fallback": used_full_report_fallback,
                "execution_seconds": round(elapsed, 3),
            }
        except Exception as exc:
            elapsed = time.perf_counter() - started
            logger.exception(
                "Errors processing company %s: %s",
                company.ticker,
                exc,
            )
            return {
                "company": company.company_name,
                "ticker": company.ticker,
                "report_year": company.report_year,
                "status": "FAILED",
                "error": str(exc),
                "validation_ready": False,
                "execution_seconds": round(elapsed, 3),
            }

    def process_multiple_companies(
        self,
        companies: Sequence[Company],
    ) -> list[dict[str, Any]]:
        """Process company reports sequentially while isolating failures."""
        results = [self.process_company(company) for company in companies]
        logger.info(
            "Pipeline completed: processed=%s success=%s failed=%s",
            len(results),
            sum(result["status"] == "SUCCESS" for result in results),
            sum(result["status"] == "FAILED" for result in results),
        )
        return results

    def save_extracted_text(self, company: Company, text: str) -> Path:
        """Save processed text using a deterministic company/year filename."""
        if not text:
            raise ValueError("Cannot save empty extracted text.")
        destination = self.text_output_dir / (
            f"{self._company_slug(company)}_extracted.txt"
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text, encoding="utf-8")
        return destination

    def save_markdown_report(
        self,
        company: Company,
        category_statistics: Mapping[str, Mapping[str, int | float | bool]],
        detected_headings: Sequence[Mapping[str, object]],
        metrics: Mapping[str, object],
    ) -> Path:
        """Create a readable Markdown summary for one processed report."""
        destination = self.report_output_dir / (
            f"{self._company_slug(company)}_report.md"
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        keyword_lines = [
            f"- {category}: {int(values.get('count', 0))}"
            for category, values in category_statistics.items()
        ] or ["- No dictionary keywords detected"]
        section_names = list(company.extracted_sections)
        if not section_names:
            section_names = [
                str(heading.get("Heading", "Unknown"))
                for heading in detected_headings
            ]
        section_lines = [f"- {name}" for name in dict.fromkeys(section_names)]
        if not section_lines:
            section_lines = ["- No target sections detected"]
        recommendations = self._generate_recommendations(category_statistics)
        score = (
            company.disclosure_score
            if company.disclosure_score is not None
            else 0.0
        )
        content = "\n".join(
            [
                f"# {company.company_name} Annual Report Analysis",
                "",
                f"Report Year: {company.report_year}",
                "",
                f"Disclosure Score: {score:.2f}",
                "",
                f"Total Words Analyzed: {int(metrics.get('total_word_count', 0))}",
                "",
                "## Keyword Summary",
                "",
                *keyword_lines,
                "",
                "## Detected Sections",
                "",
                *section_lines,
                "",
                "## Recommendations",
                "",
                *[f"- {item}" for item in recommendations],
                "",
            ],
        )
        destination.write_text(content, encoding="utf-8")
        return destination

    def run(
        self,
        company: str | None = None,
        year: int | None = None,
        *,
        process_all: bool = False,
    ) -> list[dict[str, Any]]:
        """Initialize, filter, and process configured company reports.

        Args:
            company: Optional ticker or company-name filter.
            year: Optional report-year filter.
            process_all: Explicitly process all records. This is also the
                default behavior when no filters are supplied.

        Returns:
            Structured processing results for selected records.
        """
        del process_all  # Selection defaults to all when filters are absent.
        self.initialize()
        selected = self._filter_companies(company, year)
        if not selected:
            filters = f"company={company!r}, year={year!r}"
            raise ValueError(f"No Company Master records matched {filters}.")
        return self.process_multiple_companies(selected)

    def _export_workbook(
        self,
        company: Company,
        score: Mapping[str, object],
        metrics: Mapping[str, object],
        categories: Mapping[str, Mapping[str, int | float | bool]],
        sections: Mapping[str, str],
        validation_ready: Sequence[Mapping[str, object]],
    ) -> Path:
        """Export a company-specific, multi-sheet Excel workbook."""
        destination = self.excel_output_dir / (
            f"{self._company_slug(company)}_analysis.xlsx"
        )
        score_record = {
            "company": company.company_name,
            "ticker": company.ticker,
            "report_year": company.report_year,
            **dict(score),
            "pipeline_metrics": dict(metrics),
        }
        exporter = ExcelExporter(
            ExcelExporterConfig(output_path=destination),
        )
        return exporter.export_complete_workbook(
            scores=score_record,
            categories=categories,
            sections=sections,
            validation=validation_ready,
            output_path=destination,
        )

    def _build_validation_ready_data(
        self,
        company: Company,
        keyword_counts: Mapping[str, Mapping[str, int]],
    ) -> list[dict[str, object]]:
        """Flatten automated counts for subsequent manual verification."""
        aggregate: Counter[str] = Counter()
        for counts in keyword_counts.values():
            aggregate.update(counts)
        keywords = self.dictionary_loader.get_all_keywords()
        return [
            {
                "company": company.company_name,
                "ticker": company.ticker,
                "report_year": company.report_year,
                "keyword": keyword,
                "automated_count": aggregate.get(keyword, 0),
                "manual_count": None,
                "review_status": "Pending",
            }
            for keyword in keywords
        ]

    def _run_optional_validation(self, company: Company) -> dict[str, Any] | None:
        """Validate when a populated manual validation file is available."""
        validation_path = self.validator.manual_validation_path
        if not validation_path.is_file() or validation_path.stat().st_size == 0:
            return None
        try:
            if not self.validator.manual_counts:
                self.validator.load_manual_validation(validation_path)
            return self.validator.validate_company(company)
        except KeyError:
            logger.warning("No manual validation row for company: %s", company.ticker)
            return None
        except Exception as exc:
            logger.warning("Manual validation skipped for %s: %s", company.ticker, exc)
            return None

    def _filter_companies(
        self,
        company: str | None,
        year: int | None,
    ) -> list[Company]:
        """Apply case-insensitive company and exact year filters."""
        selected = self.companies
        if company:
            query = company.strip().casefold()
            exact = [
                item
                for item in selected
                if query in {item.ticker.casefold(), item.company_name.casefold()}
            ]
            selected = exact or [
                item
                for item in selected
                if query in item.company_name.casefold()
                or query in item.ticker.casefold()
            ]
        if year is not None:
            selected = [item for item in selected if item.report_year == year]
        return list(selected)

    def _ensure_initialized(self) -> None:
        """Initialize lazily for direct ``process_company`` calls."""
        if not self._initialized:
            self.initialize()

    @classmethod
    def _resolve_company_columns(
        cls,
        columns: Sequence[object],
    ) -> dict[str, object]:
        """Resolve flexible Company Master headers to canonical fields."""
        normalized = {cls._normalize_column(column): column for column in columns}
        resolved: dict[str, object] = {}
        for field_name, aliases in cls._COLUMN_ALIASES.items():
            original = next(
                (normalized[alias] for alias in aliases if alias in normalized),
                None,
            )
            if original is None:
                raise ValueError(
                    f"Company Master is missing required column: {field_name}",
                )
            resolved[field_name] = original
        return resolved

    @staticmethod
    def _normalize_column(value: object) -> str:
        """Normalize a tabular column name for alias matching."""
        return re.sub(r"[^a-z0-9]", "", str(value).strip().casefold())

    @staticmethod
    def _required_cell(value: object, field_name: str) -> str:
        """Read a required scalar cell as stripped text."""
        if pd.isna(value) or not str(value).strip():
            raise ValueError(f"{field_name} cannot be empty.")
        return str(value).strip()

    @staticmethod
    def _parse_year(value: object) -> int:
        """Parse integer and financial-year values such as ``2024-25``."""
        if pd.isna(value):
            raise ValueError("report_year cannot be empty.")
        if isinstance(value, bool):
            raise TypeError("report_year must be a year.")
        if isinstance(value, (int, float)) and float(value).is_integer():
            return int(value)
        match = re.search(r"(?:19|20)\d{2}", str(value))
        if not match:
            raise ValueError(f"Invalid report_year: {value!r}")
        return int(match.group())

    @staticmethod
    def _resolve_report_path(value: str, base_dir: Path) -> Path:
        path = Path(value).expanduser()
    
        if path.is_absolute():
            return path
    
        # If only a filename is given, always look in annual_reports
        if len(path.parts) == 1:
            return settings.ANNUAL_REPORTS_DIR / path.name
    
        candidates = (
            base_dir / path,
            settings.PROJECT_ROOT / path,
            settings.ANNUAL_REPORTS_DIR / path,
        )
    
        for candidate in candidates:
            if candidate.is_file():
                return candidate
    
        return settings.ANNUAL_REPORTS_DIR / path.name

    @staticmethod
    def _generate_recommendations(
        categories: Mapping[str, Mapping[str, int | float | bool]],
    ) -> list[str]:
        """Generate deterministic disclosure recommendations from category counts."""
        if not categories:
            return ["Expand disclosure across the configured innovation categories"]
        recommendations: list[str] = []
        for category, values in categories.items():
            count = int(values.get("count", 0))
            readable = category.replace("_", " ")
            if count == 0:
                recommendations.append(f"Strengthen {readable} disclosure")
            elif count < 5:
                recommendations.append(f"Moderate {readable} disclosure")
            else:
                recommendations.append(f"Strong {readable} disclosure")
        return recommendations

    @staticmethod
    def _company_slug(company: Company) -> str:
        """Build a safe, stable artifact stem for a company report."""
        identity = company.ticker or company.company_name
        slug = re.sub(r"[^a-z0-9]+", "_", identity.casefold()).strip("_")
        return f"{slug}_{company.report_year}"

    @staticmethod
    def build_run_summary(
        results: Sequence[Mapping[str, object]],
        started_at: float,
    ) -> dict[str, object]:
        """Build aggregate counts and elapsed time for a pipeline execution."""
        processed = len(results)
        success = sum(result.get("status") == "SUCCESS" for result in results)
        return {
            "processed": processed,
            "success": success,
            "failed": processed - success,
            "execution_seconds": max(time.perf_counter() - started_at, 0.0),
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }

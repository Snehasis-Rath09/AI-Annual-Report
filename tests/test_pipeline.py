"""Tests for the end-to-end annual-report pipeline orchestration."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.extraction.pdf_extractor import (
    PDFPageText,
    PDFValidationError,
    PDFValidationResult,
    PDFExtractor,
)
from src.models.company import Company
from src.services.pipeline import AnnualReportPipeline


@pytest.fixture
def company(tmp_path: Path) -> Company:
    """Create a company with a local PDF fixture."""
    report_path = tmp_path / "tcs_2024.pdf"
    report_path.write_bytes(b"%PDF-1.4\n% test fixture")
    return Company(
        company_name="Tata Consultancy Services",
        ticker="TCS",
        industry="Information Technology",
        report_year=2024,
        report_path=report_path,
        source_url="https://example.com/tcs-2024.pdf",
    )


@pytest.fixture
def collaborators(tmp_path: Path) -> dict[str, MagicMock]:
    """Create deterministic collaborators for pipeline unit tests."""
    dictionary_loader = MagicMock()
    dictionary_loader.load_dictionary.return_value = {
        "AI": ("artificial intelligence",),
        "Innovation": ("innovation",),
    }
    dictionary_loader.get_all_keywords.return_value = (
        "artificial intelligence",
        "innovation",
    )
    pdf_extractor = MagicMock()
    pdf_extractor.extract_text.return_value = (
        "INNOVATION\nArtificial intelligence supports innovation initiatives "
        "across the enterprise."
    )
    text_cleaner = MagicMock()
    text_cleaner.clean.return_value = pdf_extractor.extract_text.return_value
    text_normalizer = MagicMock()
    text_normalizer.normalize.return_value = text_cleaner.clean.return_value
    heading_detector = MagicMock()
    heading_detector.detect_headings.return_value = [
        {
            "Heading": "Innovation",
            "Start Index": 0,
            "End Index": 10,
            "Confidence Score": 1.0,
        },
    ]
    section_extractor = MagicMock()
    section_extractor.extract_sections.return_value = {
        "Innovation": text_normalizer.normalize.return_value,
    }
    keyword_counter = MagicMock()
    keyword_counter.count_keywords.return_value = {
        "Innovation": {"artificial intelligence": 1, "innovation": 2},
    }
    category_counter = MagicMock()
    category_counter.calculate_category_statistics.return_value = {
        "AI": {
            "count": 1,
            "density": 10.0,
            "present": True,
            "percentage_contribution": 33.3333,
            "total_keyword_count": 3,
            "word_count": 100,
        },
        "Innovation": {
            "count": 2,
            "density": 20.0,
            "present": True,
            "percentage_contribution": 66.6667,
            "total_keyword_count": 3,
            "word_count": 100,
        },
    }
    metrics_calculator = MagicMock()
    metrics_calculator.calculate_summary.return_value = {
        "total_keyword_count": 3,
        "total_word_count": 100,
        "keyword_density": 30.0,
        "section_coverage": {"section_coverage": 10.0},
    }
    score_calculator = MagicMock()
    score_calculator.calculate_score.return_value = {
        "overall_score": 84.6,
        "component_scores": {"section_coverage_score": 10.0},
        "raw_metrics": metrics_calculator.calculate_summary.return_value,
        "explanation": "Deterministic disclosure score.",
    }
    validator = MagicMock()
    validator.manual_validation_path = tmp_path / "missing_validation.xlsx"
    validator.manual_counts = {}
    return {
        "dictionary_loader": dictionary_loader,
        "pdf_extractor": pdf_extractor,
        "text_cleaner": text_cleaner,
        "text_normalizer": text_normalizer,
        "heading_detector": heading_detector,
        "section_extractor": section_extractor,
        "keyword_counter": keyword_counter,
        "category_counter": category_counter,
        "metrics_calculator": metrics_calculator,
        "score_calculator": score_calculator,
        "validator": validator,
    }


@pytest.fixture
def pipeline(
    tmp_path: Path,
    collaborators: dict[str, MagicMock],
) -> AnnualReportPipeline:
    """Build an initialized pipeline with mocked analytical collaborators."""
    instance = AnnualReportPipeline(
        company_master_path=tmp_path / "company_master.xlsx",
        dictionary_path=tmp_path / "dictionary.xlsx",
        output_dir=tmp_path / "outputs",
        **collaborators,
    )
    instance.keyword_dictionary = collaborators[
        "dictionary_loader"
    ].load_dictionary.return_value
    instance._initialized = True
    return instance


def test_pipeline_initialization_creates_directories_and_loads_inputs(
    tmp_path: Path,
    company: Company,
    collaborators: dict[str, MagicMock],
) -> None:
    """Initialization should load reference data and prepare output folders."""
    instance = AnnualReportPipeline(
        company_master_path=tmp_path / "company_master.xlsx",
        dictionary_path=tmp_path / "dictionary.xlsx",
        output_dir=tmp_path / "generated",
        **collaborators,
    )
    with patch.object(instance, "load_company_master", return_value=[company]) as load:
        instance.initialize()

    load.assert_called_once_with(instance.company_master_path)
    collaborators["dictionary_loader"].load_dictionary.assert_called_once_with(
        instance.dictionary_path,
    )
    assert instance.companies == [company]
    assert instance._initialized is True
    assert instance.text_output_dir.is_dir()
    assert instance.excel_output_dir.is_dir()
    assert instance.report_output_dir.is_dir()


def test_process_single_company_generates_structured_result(
    pipeline: AnnualReportPipeline,
    company: Company,
    tmp_path: Path,
) -> None:
    """A valid report should traverse every analytical stage successfully."""
    excel_path = tmp_path / "outputs" / "excel" / "tcs_2024.xlsx"

    def export_workbook(*_: Any, **__: Any) -> Path:
        excel_path.parent.mkdir(parents=True, exist_ok=True)
        excel_path.write_bytes(b"workbook")
        return excel_path

    with patch.object(
        pipeline,
        "_export_workbook",
        side_effect=export_workbook,
    ) as export:
        result = pipeline.process_company(company)

    assert result["status"] == "SUCCESS"
    assert result["disclosure_score"] == pytest.approx(84.6)
    assert result["validation_ready"] is True
    assert result["detected_sections"] == ["Innovation"]
    assert Path(result["text_path"]).is_file()
    assert Path(result["markdown_path"]).is_file()
    assert Path(result["excel_path"]).is_file()
    pipeline.pdf_extractor.extract_text.assert_called_once_with(company.report_path)
    pipeline.text_cleaner.clean.assert_called_once()
    pipeline.text_normalizer.normalize.assert_called_once()
    pipeline.keyword_counter.count_keywords.assert_called_once()
    pipeline.score_calculator.calculate_score.assert_called_once()
    export.assert_called_once()


def test_process_multiple_companies_preserves_all_results(
    pipeline: AnnualReportPipeline,
    company: Company,
) -> None:
    """Batch processing should retain successful and failed company results."""
    second = Company.from_dict(
        {
            **company.to_dict(),
            "company_name": "Infosys Limited",
            "ticker": "INFY",
        },
    )
    expected = [
        {"ticker": "TCS", "status": "SUCCESS"},
        {"ticker": "INFY", "status": "FAILED"},
    ]
    with patch.object(pipeline, "process_company", side_effect=expected) as process:
        results = pipeline.process_multiple_companies([company, second])

    assert results == expected
    assert process.call_count == 2


def test_missing_pdf_returns_failure(
    pipeline: AnnualReportPipeline,
    company: Company,
) -> None:
    """A missing report should fail before PDF extraction is attempted."""
    company.report_path = company.report_path.with_name("missing.pdf")
    result = pipeline.process_company(company)
    assert result["status"] == "FAILED"
    assert "does not exist" in str(result["error"])
    pipeline.pdf_extractor.extract_text.assert_not_called()


def test_invalid_pdf_returns_failure(
    pipeline: AnnualReportPipeline,
    company: Company,
) -> None:
    """PDF validation exceptions should become structured failures."""
    pipeline.pdf_extractor.extract_text.side_effect = PDFValidationError(
        "PDF is corrupted.",
    )
    result = pipeline.process_company(company)
    assert result["status"] == "FAILED"
    assert result["error"] == "PDF is corrupted."
    assert result["validation_ready"] is False


def test_missing_dictionary_fails_initialization(
    tmp_path: Path,
    company: Company,
    collaborators: dict[str, MagicMock],
) -> None:
    """A missing Innovation Dictionary should stop initialization."""
    instance = AnnualReportPipeline(
        company_master_path=tmp_path / "company_master.xlsx",
        dictionary_path=tmp_path / "missing_dictionary.xlsx",
        output_dir=tmp_path / "outputs",
        **collaborators,
    )
    collaborators["dictionary_loader"].load_dictionary.side_effect = (
        FileNotFoundError("Keyword dictionary file not found")
    )
    with patch.object(instance, "load_company_master", return_value=[company]):
        with pytest.raises(FileNotFoundError, match="dictionary"):
            instance.initialize()
    assert instance._initialized is False


def test_empty_report_returns_failure(
    pipeline: AnnualReportPipeline,
    company: Company,
) -> None:
    """Whitespace-only extraction should not enter downstream analysis."""
    pipeline.pdf_extractor.extract_text.return_value = " \n\t "
    result = pipeline.process_company(company)
    assert result["status"] == "FAILED"
    assert "empty text" in str(result["error"])
    pipeline.text_cleaner.clean.assert_not_called()


def test_pdf_extractor_uses_ocr_fallback(tmp_path: Path) -> None:
    """Sparse native text should trigger the configured OCR extractor."""
    report = tmp_path / "scanned.pdf"
    report.write_bytes(b"%PDF-1.4\n% scanned fixture")
    ocr = MagicMock()
    ocr.extract.return_value = "Text recovered through OCR."
    extractor = PDFExtractor(use_ocr_fallback=True, ocr_extractor=ocr)
    validation = PDFValidationResult(
        is_valid=True,
        is_encrypted=False,
        is_corrupted=False,
        page_count=1,
        message="PDF is valid.",
    )
    sparse_pages = [PDFPageText(1, "", "pymupdf")]
    with patch.object(extractor, "validate_pdf", return_value=validation), patch.object(
        extractor,
        "_extract_all_with_pymupdf",
        return_value=sparse_pages,
    ):
        text = extractor.extract_text(report)
    assert text == "Text recovered through OCR."
    ocr.extract.assert_called_once_with(report.resolve())


def test_output_generation_writes_text_and_markdown(
    pipeline: AnnualReportPipeline,
    company: Company,
) -> None:
    """Output helpers should create deterministic UTF-8 artifacts."""
    extracted = pipeline.save_extracted_text(company, "Normalized report text")
    company.disclosure_score = 72.5
    company.extracted_sections = {"Innovation": "Innovation disclosure text"}
    markdown = pipeline.save_markdown_report(
        company,
        {"Innovation": {"count": 4, "density": 2.0, "present": True}},
        [{"Heading": "Innovation"}],
        {"total_word_count": 100},
    )
    assert extracted.read_text(encoding="utf-8") == "Normalized report text"
    report_text = markdown.read_text(encoding="utf-8")
    assert "# Tata Consultancy Services Annual Report Analysis" in report_text
    assert "Disclosure Score: 72.50" in report_text
    assert "- Innovation" in report_text


def test_processing_exception_is_captured(
    pipeline: AnnualReportPipeline,
    company: Company,
) -> None:
    """Unexpected collaborator errors should not escape company processing."""
    pipeline.text_cleaner.clean.side_effect = RuntimeError("cleaning failed")
    result = pipeline.process_company(company)
    assert result["status"] == "FAILED"
    assert result["error"] == "cleaning failed"
    assert result["execution_seconds"] >= 0


def test_temporary_directory_is_supported_for_pipeline_outputs() -> None:
    """Pipeline output roots should accept standard-library temporary paths."""
    with TemporaryDirectory() as directory:
        instance = AnnualReportPipeline(output_dir=Path(directory))
        assert instance.output_dir == Path(directory)
        assert instance.excel_output_dir == Path(directory) / "excel"

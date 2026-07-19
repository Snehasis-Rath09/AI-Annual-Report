"""Command-line entry point for the annual-report processing pipeline."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import settings  # noqa: E402
from src.services.pipeline import AnnualReportPipeline  # noqa: E402
from src.utils.logger import get_logger  # noqa: E402


logger = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser.

    Returns:
        Configured argument parser.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Extract, analyze, score, and export Indian annual-report "
            "innovation disclosures."
        ),
    )
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument(
        "--company",
        help="Company name or ticker from the Company Master.",
    )
    selection.add_argument(
        "--all",
        action="store_true",
        help="Process all Company Master records (the default without filters).",
    )
    parser.add_argument(
        "--year",
        type=_valid_year,
        help="Only process reports for this four-digit year.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=settings.EXPORTS_DIR,
        help=f"Output root directory (default: {settings.EXPORTS_DIR}).",
    )
    parser.add_argument(
        "--company-master",
        type=Path,
        default=settings.COMPANY_MASTER_FILE,
        help="Company Master Excel or CSV path.",
    )
    parser.add_argument(
        "--dictionary",
        type=Path,
        default=settings.INNOVATION_DICTIONARY_FILE,
        help="Innovation Dictionary Excel path.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Execute the annual-report pipeline CLI.

    Args:
        argv: Optional argument sequence. Uses process arguments when omitted.

    Returns:
        Process exit code: zero for complete success, one for processing
        failures, and two for initialization or selection errors.
    """
    args = build_parser().parse_args(argv)
    started_at = time.perf_counter()
    _print_header("Annual Report Processing Started")
    try:
        settings.ensure_directories_exist()
        logging.getLogger(__name__).debug("Settings initialized")
        pipeline = AnnualReportPipeline(
            company_master_path=args.company_master,
            dictionary_path=args.dictionary,
            output_dir=args.output,
        )
        results = pipeline.run(
            company=args.company,
            year=args.year,
            process_all=args.all,
        )
    except Exception as exc:
        logger.exception("Pipeline execution failed: %s", exc)
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 2

    for result in results:
        _display_company_result(result)
    summary = pipeline.build_run_summary(results, started_at)
    _display_summary(summary)
    return 0 if int(summary["failed"]) == 0 else 1


def _valid_year(value: str) -> int:
    try:
        year = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("year must be an integer") from exc
    if not 1900 <= year <= 9999:
        raise argparse.ArgumentTypeError("year must be a four-digit value")
    return year


def _print_header(title: str) -> None:
    print("-" * 40)
    print()
    print(title)
    print()
    print("-" * 40)


def _display_company_result(result: dict[str, object]) -> None:
    print()
    print(f"Company: {result.get('ticker') or result.get('company')}")
    print(f"Status: {result.get('status')}")
    if result.get("status") == "SUCCESS":
        print(f"Disclosure Score: {float(result['disclosure_score']):.2f}")
        print("Excel Generated")
        print("Validation Ready")
    else:
        print(f"Error: {result.get('error', 'Unknown processing error')}")
    print("-" * 40)


def _display_summary(summary: dict[str, object]) -> None:
    print()
    print(f"Processed: {summary['processed']}")
    print(f"Success: {summary['success']}")
    print(f"Failed: {summary['failed']}")
    print(f"Execution Time: {_format_duration(float(summary['execution_seconds']))}")


def _format_duration(seconds: float) -> str:
    total_seconds = max(int(round(seconds)), 0)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds_part = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds_part:02d}"


if __name__ == "__main__":
    raise SystemExit(main())

"""Streamlit dashboard for annual-report disclosure analysis outputs."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd
import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import settings  # noqa: E402
from dashboard.pages.company_analysis import render_company_analysis  # noqa: E402
from dashboard.pages.comparison import render_comparison  # noqa: E402
from dashboard.pages.overview import render_overview  # noqa: E402
from src.utils.logger import get_logger  # noqa: E402


logger = get_logger(__name__)

SHEET_NAMES = {
    "scores": "Disclosure Scores",
    "categories": "Category Counts",
    "sections": "Section Summary",
    "validation": "Validation Ready",
}


def main() -> None:
    st.set_page_config(
        page_title=str(settings.DASHBOARD_CONFIG.get("page_title", "AI Reports")),
        page_icon="📊",
        layout=str(settings.DASHBOARD_CONFIG.get("layout", "wide")),
        initial_sidebar_state=str(
            settings.DASHBOARD_CONFIG.get("initial_sidebar_state", "expanded"),
        ),
    )
    _apply_styles()
    logger.info("Dashboard started")

    signatures = _discover_workbooks()
    data = load_dashboard_data(signatures)
    page, view_data = _render_sidebar(data)

    if page == "Overview":
        _render_home(view_data)
        render_overview(view_data)
    elif page == "Company Analysis":
        render_company_analysis(view_data)
    elif page == "Comparison":
        render_comparison(view_data)
    else:
        _render_about()


@st.cache_data(show_spinner="Loading disclosure workbooks...")
def load_dashboard_data(
    signatures: tuple[tuple[str, int, int], ...],
) -> dict[str, Any]:
    """Load and consolidate generated workbooks.

    File modification times and sizes are included in ``signatures`` so the
    Streamlit cache refreshes automatically after a new pipeline execution.

    Args:
        signatures: Workbook path, modification time in nanoseconds, and size.

    Returns:
        Consolidated score, category, section, and validation dataframes plus
        workbook loading diagnostics.
    """
    frames: dict[str, list[pd.DataFrame]] = {
        key: [] for key in SHEET_NAMES
    }
    errors: list[str] = []
    loaded_files: list[str] = []

    for path_text, _, _ in signatures:
        path = Path(path_text)
        record_id = path.resolve().as_posix().casefold()
        try:
            workbook = pd.ExcelFile(path)
            available_sheets = set(workbook.sheet_names)
            score_frame = (
                _read_sheet(workbook, SHEET_NAMES["scores"])
                if SHEET_NAMES["scores"] in available_sheets
                else pd.DataFrame()
            )
            identity = _workbook_identity(score_frame, path)
            for key, sheet_name in SHEET_NAMES.items():
                if sheet_name not in available_sheets:
                    continue
                frame = _read_sheet(workbook, sheet_name)
                if frame.empty:
                    continue
                frame = _attach_identity(frame, record_id, path, identity)
                frames[key].append(frame)
            loaded_files.append(str(path))
            logger.info("Workbook loaded: %s", path)
        except Exception as exc:
            message = f"{path.name}: {exc}"
            errors.append(message)
            logger.exception("Errors loading workbook %s: %s", path, exc)

    consolidated = {
        key: pd.concat(items, ignore_index=True, sort=False)
        if items
        else pd.DataFrame()
        for key, items in frames.items()
    }
    scores = consolidated["scores"]
    if not scores.empty:
        scores = _enrich_industry(scores)
        scores = _attach_report_paths(scores)
        consolidated["scores"] = scores
    return {
        **consolidated,
        "loaded_files": loaded_files,
        "errors": errors,
        "latest_execution": _latest_execution(signatures),
    }


def _discover_workbooks() -> tuple[tuple[str, int, int], ...]:
    directories = (
        settings.EXCEL_EXPORT_DIR,
        settings.PROJECT_ROOT / "output" / "excel",
    )
    discovered: dict[str, Path] = {}
    for directory in directories:
        if not directory.is_dir():
            continue
        for pattern in ("*.xlsx", "*.xlsm", "*.xls"):
            for path in directory.glob(pattern):
                if path.name.startswith("~$") or not path.is_file():
                    continue
                discovered[str(path.resolve()).casefold()] = path.resolve()
    signatures = []
    for path in sorted(discovered.values(), key=lambda item: str(item).casefold()):
        try:
            stat = path.stat()
            signatures.append((str(path), stat.st_mtime_ns, stat.st_size))
        except OSError as exc:
            logger.warning("Workbook skipped during discovery %s: %s", path, exc)
    return tuple(signatures)


def _read_sheet(workbook: pd.ExcelFile, sheet_name: str) -> pd.DataFrame:
    frame = pd.read_excel(workbook, sheet_name=sheet_name)
    frame.columns = [str(column).strip() for column in frame.columns]
    return frame.dropna(how="all")


def _workbook_identity(
    score_frame: pd.DataFrame,
    path: Path,
) -> dict[str, object]:
    identity: dict[str, object] = {
        "company": path.stem,
        "ticker": path.stem.split("_")[0].upper(),
        "report_year": pd.NA,
    }
    if score_frame.empty:
        return identity
    first = score_frame.iloc[0]
    for key, candidates in {
        "company": ("company", "company_name"),
        "ticker": ("ticker", "symbol"),
        "report_year": ("report_year", "year"),
    }.items():
        column = _first_column(score_frame, candidates)
        if column is not None and pd.notna(first[column]):
            identity[key] = first[column]
    return identity


def _attach_identity(
    frame: pd.DataFrame,
    record_id: str,
    workbook_path: Path,
    identity: Mapping[str, object],
) -> pd.DataFrame:
    attached = frame.copy()
    attached["_record_id"] = record_id
    attached["_workbook_path"] = str(workbook_path)
    for column, value in identity.items():
        if column not in attached.columns:
            attached[column] = value
        else:
            attached[column] = attached[column].fillna(value)
    return attached


def _enrich_industry(scores: pd.DataFrame) -> pd.DataFrame:
    enriched = scores.copy()
    if "industry" in enriched.columns and enriched["industry"].notna().any():
        return enriched
    master_path = settings.COMPANY_MASTER_FILE
    if not master_path.is_file() or master_path.stat().st_size == 0:
        enriched["industry"] = "Not available"
        return enriched
    try:
        master = pd.read_excel(master_path)
        ticker_column = _first_column(master, ("ticker", "symbol", "nse_ticker"))
        industry_column = _first_column(master, ("industry", "sector"))
        score_ticker = _first_column(enriched, ("ticker", "symbol"))
        if ticker_column is None or industry_column is None or score_ticker is None:
            enriched["industry"] = "Not available"
            return enriched
        lookup = (
            master[[ticker_column, industry_column]]
            .dropna(subset=[ticker_column])
            .drop_duplicates(subset=[ticker_column])
            .rename(columns={industry_column: "_master_industry"})
        )
        lookup["_ticker_key"] = lookup[ticker_column].astype(str).str.casefold()
        enriched["_ticker_key"] = enriched[score_ticker].astype(str).str.casefold()
        enriched = enriched.merge(
            lookup[["_ticker_key", "_master_industry"]],
            on="_ticker_key",
            how="left",
        )
        enriched["industry"] = enriched["_master_industry"].fillna(
            "Not available",
        )
        return enriched.drop(
            columns=["_ticker_key", "_master_industry"],
            errors="ignore",
        )
    except Exception as exc:
        logger.warning("Industry enrichment skipped: %s", exc)
        enriched["industry"] = "Not available"
        return enriched


def _attach_report_paths(scores: pd.DataFrame) -> pd.DataFrame:
    attached = scores.copy()
    report_directories = (
        settings.EXPORTS_DIR / "reports",
        settings.PROJECT_ROOT / "output" / "reports",
    )
    reports: dict[str, Path] = {}
    for directory in report_directories:
        if directory.is_dir():
            reports.update(
                {
                    path.stem.casefold(): path
                    for path in directory.glob("*.md")
                    if path.is_file()
                },
            )
    paths: list[str | None] = []
    for workbook in attached["_workbook_path"].astype(str):
        stem = Path(workbook).stem
        expected = stem.removesuffix("_analysis") + "_report"
        report = reports.get(expected.casefold())
        paths.append(str(report) if report else None)
    attached["_report_path"] = paths
    return attached


def _render_sidebar(data: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    with st.sidebar:
        st.title("AI Annual Reports")
        page = st.radio(
            "Navigation",
            ("Overview", "Company Analysis", "Comparison", "About"),
        )
        st.divider()
        scores = data.get("scores", pd.DataFrame())
        search_query = ""
        selected_years: list[str] = []
        selected_industries: list[str] = []
        if isinstance(scores, pd.DataFrame) and not scores.empty:
            st.subheader("Filters")
            search_query = st.text_input(
                "Search company or ticker",
                placeholder="e.g. TCS",
            )
            year_column = _first_column(scores, ("report_year", "year"))
            if year_column is not None:
                year_options = sorted(
                    {
                        _format_filter_value(value)
                        for value in scores[year_column]
                        if pd.notna(value)
                    },
                    reverse=True,
                )
                selected_years = st.multiselect("Report year", year_options)
            industry_column = _first_column(scores, ("industry", "sector"))
            if industry_column is not None:
                industry_options = sorted(
                    {
                        str(value)
                        for value in scores[industry_column]
                        if pd.notna(value) and str(value) != "Not available"
                    },
                )
                selected_industries = st.multiselect(
                    "Industry",
                    industry_options,
                )
        filtered = _filter_dashboard_data(
            data,
            search_query,
            selected_years,
            selected_industries,
        )
        loaded = len(data.get("loaded_files", []))
        st.caption(f"Loaded workbooks: {loaded}")
        filtered_scores = filtered.get("scores", pd.DataFrame())
        if isinstance(filtered_scores, pd.DataFrame):
            st.caption(f"Visible records: {len(filtered_scores)}")
        if st.button("Refresh data", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
        errors = data.get("errors", [])
        if errors:
            with st.expander(f"Load warnings ({len(errors)})"):
                for error in errors:
                    st.warning(error)
        return page, filtered


def _filter_dashboard_data(
    data: Mapping[str, Any],
    search_query: str,
    selected_years: Sequence[str],
    selected_industries: Sequence[str],
) -> dict[str, Any]:
    """Filter every consolidated sheet using score-record identities.

    Args:
        data: Unfiltered dashboard data.
        search_query: Case-insensitive company or ticker search text.
        selected_years: Selected display-form report years.
        selected_industries: Selected industry names.

    Returns:
        Dashboard data with record-based sheets filtered consistently.
    """
    filtered = dict(data)
    scores = data.get("scores", pd.DataFrame())
    if not isinstance(scores, pd.DataFrame) or scores.empty:
        return filtered
    visible = scores.copy()
    query = search_query.strip().casefold()
    if query:
        searchable_columns = [
            column
            for column in (
                _first_column(visible, ("company", "company_name")),
                _first_column(visible, ("ticker", "symbol")),
            )
            if column is not None
        ]
        if searchable_columns:
            mask = pd.Series(False, index=visible.index)
            for column in searchable_columns:
                values = visible[column].fillna("").astype(str).str.casefold()
                mask |= values.str.contains(query, regex=False)
            visible = visible.loc[mask]
    if selected_years:
        year_column = _first_column(visible, ("report_year", "year"))
        if year_column is not None:
            visible = visible.loc[
                visible[year_column].map(_format_filter_value).isin(selected_years)
            ]
    if selected_industries:
        industry_column = _first_column(visible, ("industry", "sector"))
        if industry_column is not None:
            visible = visible.loc[
                visible[industry_column].astype(str).isin(selected_industries)
            ]
    filtered["scores"] = visible
    record_ids = set(visible.get("_record_id", pd.Series(dtype=str)).astype(str))
    for key in ("categories", "sections", "validation"):
        frame = data.get(key)
        if isinstance(frame, pd.DataFrame) and "_record_id" in frame.columns:
            filtered[key] = frame.loc[
                frame["_record_id"].astype(str).isin(record_ids)
            ].copy()
    return filtered


def _format_filter_value(value: object) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.notna(numeric) and float(numeric).is_integer():
        return str(int(numeric))
    return str(value)


def _render_home(data: Mapping[str, Any]) -> None:
    st.title(settings.PROJECT_NAME)
    st.write(settings.PROJECT_DESCRIPTION)
    scores = data.get("scores", pd.DataFrame())
    if not isinstance(scores, pd.DataFrame) or scores.empty:
        if data.get("loaded_files"):
            st.info("No company records match the current sidebar filters.")
        else:
            st.info(
                "No processed disclosure workbooks were found. Run the backend "
                f"pipeline and place workbooks in `{settings.EXCEL_EXPORT_DIR}`.",
            )
        return
    score_column = _first_column(scores, ("overall_score", "disclosure_score"))
    numeric_scores = (
        pd.to_numeric(scores[score_column], errors="coerce").dropna()
        if score_column
        else pd.Series(dtype=float)
    )
    latest = data.get("latest_execution")
    latest_text = latest.strftime("%d %b %Y, %H:%M") if latest else "Not available"
    columns = st.columns(5)
    columns[0].metric("Processed Companies", int(scores["_record_id"].nunique()))
    columns[1].metric(
        "Average Score",
        f"{numeric_scores.mean():.2f}" if not numeric_scores.empty else "N/A",
    )
    columns[2].metric(
        "Highest Score",
        f"{numeric_scores.max():.2f}" if not numeric_scores.empty else "N/A",
    )
    columns[3].metric(
        "Lowest Score",
        f"{numeric_scores.min():.2f}" if not numeric_scores.empty else "N/A",
    )
    columns[4].metric("Last Pipeline Run", latest_text)


def _render_about() -> None:
    st.title("About")
    st.subheader("Project Objective")
    st.write(settings.PROJECT_DESCRIPTION)
    st.subheader("Workflow")
    st.markdown(
        "PDF extraction and OCR → text cleaning and normalization → section "
        "detection → keyword and category analysis → disclosure scoring → "
        "validation and export. This dashboard only reads generated outputs.",
    )
    left, right = st.columns(2)
    with left:
        st.subheader("Technologies Used")
        st.markdown(
            "- Python 3.12\n- pandas\n- Streamlit\n- Plotly\n"
            "- PyMuPDF and OCR tooling\n- openpyxl",
        )
    with right:
        st.subheader("Folder Structure")
        st.code(
            "data/          Source and validation data\n"
            "src/           Analysis pipeline\n"
            "outputs/excel/ Generated workbooks\n"
            "outputs/reports/ Markdown reports\n"
            "dashboard/     Visualization application",
            language="text",
        )
    st.subheader("Project Information")
    metadata = st.columns(2)
    metadata[0].metric("Author", "AI Annual Report Research Team")
    metadata[1].metric("Version", settings.PROJECT_VERSION)


def _latest_execution(
    signatures: Sequence[tuple[str, int, int]],
) -> datetime | None:
    if not signatures:
        return None
    newest_nanoseconds = max(signature[1] for signature in signatures)
    return datetime.fromtimestamp(newest_nanoseconds / 1_000_000_000)


def _first_column(
    frame: pd.DataFrame,
    candidates: Sequence[str],
) -> str | None:
    columns = {
        str(column).strip().casefold().replace(" ", "_"): str(column)
        for column in frame.columns
    }
    return next(
        (
            columns[name.casefold()]
            for name in candidates
            if name.casefold() in columns
        ),
        None,
    )


def _apply_styles() -> None:
    st.markdown(
        """
        <style>
        .block-container {padding-top: 1.8rem; padding-bottom: 2rem;}
        [data-testid="stSidebarNav"] {display: none;}
        [data-testid="stMetric"] {
            background: rgba(49, 51, 63, 0.06);
            border: 1px solid rgba(49, 51, 63, 0.12);
            border-radius: 0.65rem;
            padding: 0.8rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()

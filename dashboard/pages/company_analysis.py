"""Detailed single-company disclosure analysis page."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd
import plotly.express as px
import streamlit as st

from config.settings import DASHBOARD_CONFIG
from src.utils.logger import get_logger


logger = get_logger(__name__)
CHART_HEIGHT = int(DASHBOARD_CONFIG.get("chart_height", 420))


def render_company_analysis(data: Mapping[str, Any]) -> None:
    """Render detailed analysis and downloads for one company record.

    Args:
        data: Consolidated dashboard data loaded by ``dashboard.app``.
    """
    st.title("Company Analysis")
    scores = _frame(data, "scores")
    if scores.empty:
        st.info("No company workbooks are available for analysis.")
        return
    scores = scores.drop_duplicates(subset=["_record_id"], keep="last").copy()
    scores["_label"] = _labels(scores)
    options = dict(zip(scores["_label"], scores["_record_id"], strict=False))
    selected_label = st.selectbox("Select company", tuple(options))
    record_id = options[selected_label]
    selected = scores.loc[scores["_record_id"] == record_id].iloc[0]
    logger.info("Company selected: %s", selected_label)

    score_column = _first_column(scores, ("overall_score", "disclosure_score"))
    company_name = _row_value(selected, ("company", "company_name"), selected_label)
    ticker = _row_value(selected, ("ticker", "symbol"), "N/A")
    industry = _row_value(selected, ("industry", "sector"), "Not available")
    year = _row_value(selected, ("report_year", "year"), "N/A")
    score = _number(selected.get(score_column)) if score_column else None

    st.subheader(str(company_name))
    cards = st.columns(4)
    cards[0].metric("Ticker", str(ticker))
    cards[1].metric("Industry", str(industry))
    cards[2].metric("Report Year", _format_year(year))
    cards[3].metric("Disclosure Score", f"{score:.2f}" if score is not None else "N/A")

    categories = _for_record(_frame(data, "categories"), record_id)
    sections = _for_record(_frame(data, "sections"), record_id)
    validation = _for_record(_frame(data, "validation"), record_id)
    keyword_tab, category_tab, section_tab, recommendation_tab = st.tabs(
        (
            "Keyword Counts",
            "Category Statistics",
            "Detected Sections",
            "Recommendations",
        ),
    )
    with keyword_tab:
        _render_keywords(validation)
    with category_tab:
        _render_categories(categories)
    with section_tab:
        _render_sections(sections)
    with recommendation_tab:
        report = _report_path(selected)
        recommendations = _read_recommendations(report)
        if not recommendations:
            recommendations = _derive_recommendations(categories)
        for recommendation in recommendations:
            st.markdown(f"- {recommendation}")

    _render_report_download(selected, company_name, year)


def _render_keywords(validation: pd.DataFrame) -> None:
    keyword_column = _first_column(validation, ("keyword", "term", "phrase"))
    count_column = _first_column(
        validation,
        ("automated_count", "keyword_count", "count"),
    )
    if validation.empty or keyword_column is None or count_column is None:
        st.info("Keyword-level validation-ready counts are not available.")
        return
    display = validation[[keyword_column, count_column]].copy()
    display[count_column] = pd.to_numeric(
        display[count_column],
        errors="coerce",
    ).fillna(0)
    display = display.sort_values(count_column, ascending=False)
    positive = display[display[count_column] > 0].head(20)
    if not positive.empty:
        figure = px.bar(
            positive,
            x=count_column,
            y=keyword_column,
            orientation="h",
            title="Top Keyword Counts",
            text_auto=True,
            color=count_column,
            color_continuous_scale="Blues",
        )
        figure.update_layout(
            height=CHART_HEIGHT,
            coloraxis_showscale=False,
            yaxis={"categoryorder": "total ascending"},
        )
        st.plotly_chart(figure, use_container_width=True)
    st.dataframe(display, use_container_width=True, hide_index=True)


def _render_categories(categories: pd.DataFrame) -> None:
    category_column = _first_column(categories, ("category", "name"))
    count_column = _first_column(categories, ("count", "keyword_count"))
    if categories.empty or category_column is None or count_column is None:
        st.info("Category statistics are not available.")
        return
    display = categories.drop(
        columns=["_record_id", "_workbook_path"],
        errors="ignore",
    ).copy()
    display[count_column] = pd.to_numeric(
        display[count_column],
        errors="coerce",
    ).fillna(0)
    figure = px.bar(
        display.sort_values(count_column),
        x=count_column,
        y=category_column,
        orientation="h",
        title="Category-wise Keyword Counts",
        text_auto=True,
        color=count_column,
        color_continuous_scale="Teal",
    )
    figure.update_layout(height=CHART_HEIGHT, coloraxis_showscale=False)
    st.plotly_chart(figure, use_container_width=True)
    st.dataframe(display, use_container_width=True, hide_index=True)


def _render_sections(sections: pd.DataFrame) -> None:
    section_column = _first_column(sections, ("section", "section_name"))
    if sections.empty or section_column is None:
        st.info("No target sections were detected for this report.")
        return
    display = sections.drop(
        columns=["_record_id", "_workbook_path", "preview"],
        errors="ignore",
    )
    st.dataframe(display, use_container_width=True, hide_index=True)
    preview_column = _first_column(sections, ("preview", "text", "section_text"))
    for _, row in sections.iterrows():
        section_name = str(row[section_column])
        with st.expander(section_name):
            if preview_column and pd.notna(row[preview_column]):
                st.write(str(row[preview_column]))
            else:
                st.caption("A text preview was not included in the workbook.")


def _render_report_download(
    selected: pd.Series,
    company_name: object,
    year: object,
) -> None:
    st.divider()
    report = _report_path(selected)
    if report is None:
        st.info("The generated Markdown report is not available for this record.")
        return
    try:
        content = report.read_bytes()
    except OSError as exc:
        logger.exception("Errors reading company report %s: %s", report, exc)
        st.error("The report exists but could not be read.")
        return
    filename = f"{_slug(str(company_name))}_{_format_year(year)}_report.md"
    st.download_button(
        "Download company report",
        data=content,
        file_name=filename,
        mime="text/markdown",
        use_container_width=True,
    )


def _read_recommendations(report: Path | None) -> list[str]:
    if report is None:
        return []
    try:
        text = report.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("Recommendations could not be read from %s: %s", report, exc)
        return []
    recommendations: list[str] = []
    in_section = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.casefold() == "## recommendations":
            in_section = True
            continue
        if in_section and stripped.startswith("## "):
            break
        if in_section and stripped.startswith("-"):
            recommendations.append(stripped.lstrip("- "))
    return recommendations


def _derive_recommendations(categories: pd.DataFrame) -> list[str]:
    category_column = _first_column(categories, ("category", "name"))
    count_column = _first_column(categories, ("count", "keyword_count"))
    if categories.empty or category_column is None or count_column is None:
        return ["Generate a pipeline report to view disclosure recommendations"]
    recommendations = []
    for _, row in categories.iterrows():
        category = str(row[category_column]).replace("_", " ")
        count = _number(row[count_column]) or 0
        if count == 0:
            recommendations.append(f"Strengthen {category} disclosure")
        elif count < 5:
            recommendations.append(f"Moderate {category} disclosure")
        else:
            recommendations.append(f"Strong {category} disclosure")
    return recommendations


def _report_path(selected: pd.Series) -> Path | None:
    value = selected.get("_report_path")
    if value is None or pd.isna(value):
        return None
    path = Path(str(value))
    return path if path.is_file() else None


def _labels(frame: pd.DataFrame) -> pd.Series:
    company_column = _first_column(frame, ("company", "company_name", "ticker"))
    ticker_column = _first_column(frame, ("ticker", "symbol"))
    year_column = _first_column(frame, ("report_year", "year"))
    labels = []
    for _, row in frame.iterrows():
        company = str(row[company_column]) if company_column else "Company"
        ticker = str(row[ticker_column]) if ticker_column else ""
        year = _format_year(row[year_column]) if year_column else ""
        detail = " · ".join(item for item in (ticker, year) if item)
        labels.append(f"{company} ({detail})" if detail else company)
    return pd.Series(labels, index=frame.index)


def _for_record(frame: pd.DataFrame, record_id: str) -> pd.DataFrame:
    if frame.empty or "_record_id" not in frame.columns:
        return pd.DataFrame()
    return frame.loc[frame["_record_id"] == record_id].copy()


def _row_value(
    row: pd.Series,
    candidates: Sequence[str],
    default: object,
) -> object:
    lookup = {str(column).casefold(): column for column in row.index}
    for candidate in candidates:
        column = lookup.get(candidate.casefold())
        if column is not None and pd.notna(row[column]):
            return row[column]
    return default


def _number(value: object) -> float | None:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return float(numeric) if pd.notna(numeric) else None


def _format_year(value: object) -> str:
    numeric = _number(value)
    return str(int(numeric)) if numeric is not None else str(value)


def _slug(value: str) -> str:
    return "_".join(value.casefold().split()) or "company"


def _frame(data: Mapping[str, Any], key: str) -> pd.DataFrame:
    value = data.get(key)
    return value.copy() if isinstance(value, pd.DataFrame) else pd.DataFrame()


def _first_column(frame: pd.DataFrame, candidates: Sequence[str]) -> str | None:
    lookup = {
        str(column).strip().casefold().replace(" ", "_"): str(column)
        for column in frame.columns
    }
    return next(
        (
            lookup[item.casefold()]
            for item in candidates
            if item.casefold() in lookup
        ),
        None,
    )

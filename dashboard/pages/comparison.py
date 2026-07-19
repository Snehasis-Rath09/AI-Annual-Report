"""Multi-company disclosure comparison page."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from config.settings import DASHBOARD_CONFIG
from src.utils.logger import get_logger


logger = get_logger(__name__)
CHART_HEIGHT = int(DASHBOARD_CONFIG.get("chart_height", 420))


def render_comparison(data: Mapping[str, Any]) -> None:
    """Render score, category, density, and coverage comparisons.

    Args:
        data: Consolidated dashboard data loaded by ``dashboard.app``.
    """
    st.title("Company Comparison")
    scores = _frame(data, "scores")
    if scores.empty:
        st.info("No company workbooks are available for comparison.")
        return
    scores = scores.drop_duplicates(subset=["_record_id"], keep="last").copy()
    scores["_label"] = _labels(scores)
    label_to_id = dict(zip(scores["_label"], scores["_record_id"], strict=False))
    defaults = list(label_to_id)[: min(3, len(label_to_id))]
    selected_labels = st.multiselect(
        "Select two or more companies",
        options=tuple(label_to_id),
        default=defaults,
        max_selections=8,
    )
    if len(selected_labels) < 2:
        st.info("Select at least two company records to generate a comparison.")
        return
    record_ids = [label_to_id[label] for label in selected_labels]
    selected = scores[scores["_record_id"].isin(record_ids)].copy()
    selected["_label"] = pd.Categorical(
        selected["_label"],
        categories=selected_labels,
        ordered=True,
    )
    selected = selected.sort_values("_label")
    logger.info("Comparison generated: %s", ", ".join(selected_labels))

    score_tab, category_tab, metric_tab, table_tab = st.tabs(
        ("Disclosure Scores", "Category Counts", "Metrics", "Data Tables"),
    )
    with score_tab:
        _render_score_comparison(selected)
    categories = _for_records(_frame(data, "categories"), record_ids)
    label_lookup = selected.set_index("_record_id")["_label"].astype(str).to_dict()
    with category_tab:
        _render_category_comparison(categories, label_lookup)
    with metric_tab:
        _render_metric_comparison(selected)
    with table_tab:
        _render_tables(selected, categories, label_lookup)


def _render_score_comparison(scores: pd.DataFrame) -> None:
    score_column = _first_column(scores, ("overall_score", "disclosure_score"))
    if score_column is None:
        st.warning("Disclosure score data is unavailable.")
        return
    chart = scores[["_label", score_column]].copy()
    chart[score_column] = pd.to_numeric(chart[score_column], errors="coerce")
    figure = px.bar(
        chart,
        x="_label",
        y=score_column,
        color="_label",
        barmode="group",
        title="Disclosure Score Comparison",
        text_auto=".2f",
        labels={"_label": "Company", score_column: "Disclosure Score"},
    )
    figure.update_layout(height=CHART_HEIGHT, showlegend=False)
    st.plotly_chart(figure, use_container_width=True)


def _render_category_comparison(
    categories: pd.DataFrame,
    labels: Mapping[str, str],
) -> None:
    category_column = _first_column(categories, ("category", "name"))
    count_column = _first_column(categories, ("count", "keyword_count"))
    if categories.empty or category_column is None or count_column is None:
        st.info("Category count data is not available for these records.")
        return
    chart = categories[["_record_id", category_column, count_column]].copy()
    chart["Company"] = chart["_record_id"].map(labels)
    chart[count_column] = pd.to_numeric(chart[count_column], errors="coerce").fillna(0)
    grouped = px.bar(
        chart,
        x=category_column,
        y=count_column,
        color="Company",
        barmode="group",
        title="Grouped Category Counts",
        labels={count_column: "Keyword Count", category_column: "Category"},
    )
    grouped.update_layout(height=CHART_HEIGHT)
    st.plotly_chart(grouped, use_container_width=True)

    pivot = chart.pivot_table(
        index=category_column,
        columns="Company",
        values=count_column,
        aggfunc="sum",
        fill_value=0,
    )
    if pivot.empty:
        return
    radar = go.Figure()
    radar_categories = [*pivot.index.astype(str), str(pivot.index[0])]
    for company in pivot.columns:
        values = [*pivot[company].astype(float), float(pivot[company].iloc[0])]
        radar.add_trace(
            go.Scatterpolar(
                r=values,
                theta=radar_categories,
                fill="toself",
                name=str(company),
                opacity=0.68,
            ),
        )
    radar.update_layout(
        title="Category Profile Radar",
        height=CHART_HEIGHT + 80,
        polar={"radialaxis": {"visible": True, "rangemode": "tozero"}},
    )
    st.plotly_chart(radar, use_container_width=True)


def _render_metric_comparison(scores: pd.DataFrame) -> None:
    density_column = _first_column(
        scores,
        ("keyword_density", "pipeline_metrics_keyword_density"),
    )
    coverage_column = _first_column(
        scores,
        (
            "component_section_coverage_score",
            "pipeline_metrics_section_coverage_section_coverage",
            "section_coverage",
        ),
    )
    metric_columns = [
        column for column in (density_column, coverage_column) if column is not None
    ]
    if not metric_columns:
        st.info("Keyword density and section coverage metrics are unavailable.")
        return
    chart = scores[["_label", *metric_columns]].copy()
    for column in metric_columns:
        chart[column] = pd.to_numeric(chart[column], errors="coerce")
    renamed = {
        density_column: "Keyword Density",
        coverage_column: "Section Coverage",
    }
    chart = chart.rename(columns={key: value for key, value in renamed.items() if key})
    long = chart.melt(id_vars="_label", var_name="Metric", value_name="Value")
    figure = px.line(
        long,
        x="_label",
        y="Value",
        color="Metric",
        markers=True,
        title="Keyword Density and Section Coverage",
        labels={"_label": "Company"},
    )
    figure.update_layout(height=CHART_HEIGHT)
    st.plotly_chart(figure, use_container_width=True)
    st.dataframe(chart, use_container_width=True, hide_index=True)


def _render_tables(
    scores: pd.DataFrame,
    categories: pd.DataFrame,
    labels: Mapping[str, str],
) -> None:
    score_columns = [
        column
        for column in (
            "_label",
            _first_column(scores, ("industry", "sector")),
            _first_column(scores, ("overall_score", "disclosure_score")),
            _first_column(scores, ("keyword_density",)),
            _first_column(scores, ("component_section_coverage_score",)),
        )
        if column is not None
    ]
    st.subheader("Score and Metric Data")
    st.dataframe(scores[score_columns], use_container_width=True, hide_index=True)
    if categories.empty:
        return
    table = categories.copy()
    table["Company"] = table["_record_id"].map(labels)
    table = table.drop(
        columns=["_record_id", "_workbook_path", "company", "ticker", "report_year"],
        errors="ignore",
    )
    st.subheader("Category Data")
    st.dataframe(table, use_container_width=True, hide_index=True)


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


def _format_year(value: object) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return str(int(numeric)) if pd.notna(numeric) else str(value)


def _for_records(frame: pd.DataFrame, record_ids: Sequence[str]) -> pd.DataFrame:
    if frame.empty or "_record_id" not in frame.columns:
        return pd.DataFrame()
    return frame.loc[frame["_record_id"].isin(record_ids)].copy()


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

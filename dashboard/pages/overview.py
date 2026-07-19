"""Portfolio overview visualizations for disclosure analysis."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import pandas as pd
import plotly.express as px
import streamlit as st

from config.settings import DASHBOARD_CONFIG
from src.utils.logger import get_logger


logger = get_logger(__name__)
CHART_HEIGHT = int(DASHBOARD_CONFIG.get("chart_height", 420))


def render_overview(data: Mapping[str, Any]) -> None:
    """Render aggregate score, category, and industry visualizations.

    Args:
        data: Consolidated dashboard data loaded by ``dashboard.app``.
    """
    scores = _frame(data, "scores")
    if scores.empty:
        return
    score_column = _first_column(scores, ("overall_score", "disclosure_score"))
    if score_column is None:
        st.warning("The workbooks do not contain a disclosure score column.")
        return
    chart_scores = scores.copy()
    chart_scores[score_column] = pd.to_numeric(
        chart_scores[score_column],
        errors="coerce",
    )
    chart_scores = chart_scores.dropna(subset=[score_column])
    if chart_scores.empty:
        st.warning("Disclosure scores are present but are not numeric.")
        return
    chart_scores["_label"] = _labels(chart_scores)

    st.header("Portfolio Overview")
    distribution_tab, ranking_tab = st.tabs(("Distribution", "Rankings"))
    with distribution_tab:
        left, right = st.columns(2)
        with left:
            figure = px.histogram(
                chart_scores,
                x=score_column,
                nbins=min(max(len(chart_scores), 5), 20),
                title="Disclosure Score Distribution",
                labels={score_column: "Disclosure Score"},
                color_discrete_sequence=["#2563EB"],
            )
            figure.update_layout(height=CHART_HEIGHT, bargap=0.08)
            st.plotly_chart(figure, use_container_width=True)
        with right:
            _render_score_line(chart_scores, score_column)
    with ranking_tab:
        top_column, bottom_column = st.columns(2)
        ranking = chart_scores.sort_values(score_column, ascending=False)
        with top_column:
            _ranking_chart(
                ranking.head(10),
                score_column,
                "Top 10 Companies",
                "#16A34A",
            )
        with bottom_column:
            _ranking_chart(
                ranking.tail(10).sort_values(score_column),
                score_column,
                "Bottom 10 Companies",
                "#DC2626",
            )

    st.subheader("Disclosure Drivers")
    category_column, industry_column = st.columns(2)
    with category_column:
        _render_category_pie(_frame(data, "categories"))
    with industry_column:
        _render_industry_scores(chart_scores, score_column)


def _ranking_chart(
    frame: pd.DataFrame,
    score_column: str,
    title: str,
    color: str,
) -> None:
    figure = px.bar(
        frame,
        x=score_column,
        y="_label",
        orientation="h",
        title=title,
        labels={score_column: "Disclosure Score", "_label": "Company"},
        text_auto=".2f",
        color_discrete_sequence=[color],
    )
    figure.update_layout(
        height=CHART_HEIGHT,
        yaxis={"categoryorder": "total ascending"},
    )
    st.plotly_chart(figure, use_container_width=True)


def _render_category_pie(categories: pd.DataFrame) -> None:
    category_column = _first_column(categories, ("category", "name"))
    count_column = _first_column(categories, ("count", "keyword_count"))
    if categories.empty or category_column is None or count_column is None:
        st.info("Category count data is not available.")
        return
    summary = categories[[category_column, count_column]].copy()
    summary[count_column] = pd.to_numeric(summary[count_column], errors="coerce")
    summary = summary.groupby(category_column, as_index=False)[count_column].sum()
    summary = summary[summary[count_column] > 0]
    if summary.empty:
        st.info("No positive category counts are available for the pie chart.")
        return
    figure = px.pie(
        summary,
        names=category_column,
        values=count_column,
        title="Category-wise Keyword Counts",
        hole=0.38,
    )
    figure.update_layout(height=CHART_HEIGHT)
    st.plotly_chart(figure, use_container_width=True)


def _render_industry_scores(scores: pd.DataFrame, score_column: str) -> None:
    industry_column = _first_column(scores, ("industry", "sector"))
    if industry_column is None:
        st.info("Industry metadata is not available.")
        return
    industry = scores[[industry_column, score_column]].dropna().copy()
    industry = industry[industry[industry_column].astype(str) != "Not available"]
    if industry.empty:
        st.info("Add industry metadata to Company Master for industry analysis.")
        return
    summary = industry.groupby(industry_column, as_index=False)[score_column].mean()
    summary = summary.sort_values(score_column, ascending=True)
    figure = px.bar(
        summary,
        x=score_column,
        y=industry_column,
        orientation="h",
        title="Industry-wise Average Disclosure Score",
        text_auto=".2f",
        color=score_column,
        color_continuous_scale="Blues",
    )
    figure.update_layout(height=CHART_HEIGHT, coloraxis_showscale=False)
    st.plotly_chart(figure, use_container_width=True)


def _render_score_line(scores: pd.DataFrame, score_column: str) -> None:
    year_column = _first_column(scores, ("report_year", "year"))
    if year_column is not None and scores[year_column].nunique(dropna=True) > 1:
        trend = scores[[year_column, score_column]].copy()
        trend[year_column] = pd.to_numeric(trend[year_column], errors="coerce")
        trend = trend.dropna().groupby(year_column, as_index=False)[score_column].mean()
        x_column = year_column
        title = "Average Disclosure Score by Year"
    else:
        trend = scores.sort_values(score_column).reset_index(drop=True).copy()
        trend["Rank"] = trend.index + 1
        x_column = "Rank"
        title = "Disclosure Score Line Comparison"
    figure = px.line(
        trend,
        x=x_column,
        y=score_column,
        markers=True,
        title=title,
        labels={score_column: "Disclosure Score"},
    )
    figure.update_layout(height=CHART_HEIGHT)
    st.plotly_chart(figure, use_container_width=True)


def _labels(frame: pd.DataFrame) -> pd.Series:
    company = _series(frame, ("ticker", "company", "company_name"), "Company")
    year_column = _first_column(frame, ("report_year", "year"))
    if year_column is None:
        return company
    year = frame[year_column].apply(
        lambda value: str(int(value))
        if pd.notna(value) and str(value).replace(".0", "").isdigit()
        else str(value),
    )
    return company + " · " + year


def _frame(data: Mapping[str, Any], key: str) -> pd.DataFrame:
    value = data.get(key)
    return value.copy() if isinstance(value, pd.DataFrame) else pd.DataFrame()


def _series(
    frame: pd.DataFrame,
    candidates: Sequence[str],
    default: str,
) -> pd.Series:
    column = _first_column(frame, candidates)
    if column is None:
        return pd.Series([default] * len(frame), index=frame.index)
    return frame[column].fillna(default).astype(str)


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

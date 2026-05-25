"""
ui/charts.py
~~~~~~~~~~~~
Shared Plotly chart builders for all UI tabs.
All functions return a plotly.graph_objects.Figure.

Colour palette is Okabe–Ito (colour-blind safe). No red/green pairing.
"""

from __future__ import annotations

from typing import Sequence

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots

# Okabe–Ito palette
_PALETTE = [
    "#E69F00",  # orange
    "#56B4E9",  # sky blue
    "#009E73",  # bluish green
    "#F0E442",  # yellow
    "#0072B2",  # blue
    "#D55E00",  # vermilion
    "#CC79A7",  # reddish purple
    "#555555",  # grey
]

_PERCENTILE_COLOURS = {
    50: "#56B4E9",
    70: "#E69F00",
    85: "#D55E00",
    95: "#CC79A7",
}

_LEGEND_FONT = dict(size=11)
_AXIS_FONT   = dict(size=11)


def _palette_colour(idx: int) -> str:
    return _PALETTE[idx % len(_PALETTE)]


# ── Cycle Time Scatterplot ─────────────────────────────────────────────────────

def cycle_time_scatter(
    df: pd.DataFrame,
    percentiles: Sequence[int] = (50, 70, 85, 95),
    group_col: str = "type",
) -> go.Figure:
    """
    Cycle time scatterplot: x = resolved date, y = cycle time in days.
    Percentile lines are drawn as horizontal reference lines.
    """
    from core.metrics import cycle_time_series

    ct = cycle_time_series(df).dropna()
    if ct.empty:
        return _empty_fig("No resolved items with cycle-time data in the selected range.")

    plot_df = df.loc[ct.index].copy()
    plot_df["cycle_time_days"] = ct

    fig = go.Figure()

    types = plot_df[group_col].dropna().unique()
    for i, t in enumerate(types):
        subset = plot_df[plot_df[group_col] == t]
        colour = _palette_colour(i)
        fig.add_trace(go.Scatter(
            x=subset["resolved"],
            y=subset["cycle_time_days"],
            mode="markers",
            name=str(t),
            marker=dict(color=colour, size=7, opacity=0.75,
                        line=dict(width=0.5, color="white")),
            hovertemplate=(
                "<b>%{customdata[0]}</b><br>"
                "%{customdata[1]}<br>"
                "Cycle time: %{y:.1f} days<br>"
                "Resolved: %{x|%d %b %Y}<extra></extra>"
            ),
            customdata=list(zip(
                subset["key"].astype(str),
                subset["title"].astype(str).str[:50],
            )),
        ))

    # Percentile lines
    ct_vals = plot_df["cycle_time_days"].dropna()
    for pct in percentiles:
        val = float(np.percentile(ct_vals, pct))
        colour = _PERCENTILE_COLOURS.get(pct, "#555555")
        fig.add_hline(
            y=val,
            line_dash="dash",
            line_color=colour,
            annotation_text=f"p{pct}: {val:.1f}d",
            annotation_position="top right",
            annotation_font=dict(size=10, color=colour),
        )

    fig.update_layout(
        title="Cycle Time",
        xaxis_title="Resolved date",
        yaxis_title="Cycle time (calendar days)",
        legend=dict(font=_LEGEND_FONT),
        hovermode="closest",
        height=450,
    )
    return fig


# ── Throughput Run Chart ───────────────────────────────────────────────────────

def throughput_run_chart(
    weekly_series: pd.Series,
    rolling_window: int = 4,
) -> go.Figure:
    """Weekly throughput bars with rolling-mean overlay."""
    if weekly_series.empty:
        return _empty_fig("No resolved items for throughput chart.")

    x = weekly_series.index.astype(str)
    y = weekly_series.values

    rolling = pd.Series(y).rolling(rolling_window, min_periods=1).mean()

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=x, y=y,
        name="Weekly items completed",
        marker_color=_PALETTE[1],
        opacity=0.8,
    ))
    fig.add_trace(go.Scatter(
        x=x, y=rolling,
        mode="lines",
        name=f"{rolling_window}-week rolling mean",
        line=dict(color=_PALETTE[4], width=2.5),
    ))

    mean_val = float(np.mean(y))
    fig.add_hline(
        y=mean_val,
        line_dash="dot",
        line_color=_PALETTE[0],
        annotation_text=f"Mean: {mean_val:.1f}",
        annotation_position="bottom right",
    )

    fig.update_layout(
        title="Weekly Throughput",
        xaxis_title="Week ending",
        yaxis_title="Items completed",
        legend=dict(font=_LEGEND_FONT),
        height=380,
        barmode="overlay",
    )
    return fig


def throughput_histogram(weekly_series: pd.Series) -> go.Figure:
    """Histogram of weekly throughput for distributional shape."""
    if weekly_series.empty:
        return _empty_fig("No data for throughput histogram.")

    vals = weekly_series.dropna().astype(int).tolist()
    fig = px.histogram(
        x=vals,
        nbins=max(5, len(set(vals))),
        color_discrete_sequence=[_PALETTE[1]],
        labels={"x": "Items completed per week", "count": "Frequency"},
        title="Throughput Distribution",
    )
    fig.update_traces(opacity=0.85)
    fig.update_layout(height=320, showlegend=False)
    return fig


# ── WIP Over Time ─────────────────────────────────────────────────────────────

def wip_over_time_chart(
    wip_df: pd.DataFrame,
    wip_limits: dict[str, int] | None = None,
) -> go.Figure:
    """Stacked area chart of WIP per state over time."""
    if wip_df is None or wip_df.empty:
        return _empty_fig("No WIP data available.")

    fig = go.Figure()
    for i, col in enumerate(wip_df.columns):
        fig.add_trace(go.Scatter(
            x=wip_df.index,
            y=wip_df[col],
            name=col,
            mode="lines",
            stackgroup="one",
            line=dict(width=0.5, color=_palette_colour(i)),
            fillcolor=_palette_colour(i),
            opacity=0.7,
        ))

    # WIP limit lines
    if wip_limits:
        for state, limit in wip_limits.items():
            if state in wip_df.columns:
                fig.add_hline(
                    y=limit,
                    line_dash="dash",
                    line_color=_PALETTE[5],
                    annotation_text=f"{state} limit: {limit}",
                    annotation_position="top left",
                )

    fig.update_layout(
        title="WIP Over Time",
        xaxis_title="Week",
        yaxis_title="Items in flight",
        legend=dict(font=_LEGEND_FONT),
        height=400,
        hovermode="x unified",
    )
    return fig


# ── Ageing WIP ───────────────────────────────────────────────────────────────

def ageing_wip_chart(ageing_items: list) -> go.Figure:
    """
    Scatter chart of in-flight items by status, y = age in days.

    Items with identical (status, age) values are separated by a small
    deterministic horizontal jitter (seed=42) so no dot hides another.
    Markers are semi-transparent with a contrasting stroke so any
    residual stacking is immediately visible.

    Percentile reference lines for p50, p85, p95.
    """
    from core.models import AgeingItem

    if not ageing_items:
        return _empty_fig("No in-flight items.")

    items: list[AgeingItem] = ageing_items

    statuses = sorted(set(i.status for i in items))
    status_x = {s: idx for idx, s in enumerate(statuses)}

    # Fixed seed → deterministic jitter; identical across reloads / screenshots
    np.random.seed(42)
    jitter = np.random.uniform(-0.15, 0.15, len(items))

    x_vals:      list[float] = []
    y_vals:      list[float] = []
    colours:     list[str]   = []
    strokes:     list[str]   = []
    symbols:     list[str]   = []
    hover:       list[str]   = []

    for idx, item in enumerate(items):
        x_vals.append(status_x.get(item.status, 0) + jitter[idx])
        y_vals.append(item.age_days)

        if item.is_blocked:
            colours.append(_PALETTE[5])      # vermilion fill
            strokes.append("#7B0000")         # dark red stroke
            symbols.append("x")
        elif item.is_flagged:
            colours.append(_PALETTE[0])      # orange fill
            strokes.append("darkblue")
            symbols.append("diamond")
        else:
            colours.append(_PALETTE[1])      # sky blue fill
            strokes.append("darkblue")
            symbols.append("circle")

        flags = (
            (" 🚫 BLOCKED" if item.is_blocked else "")
            + (" ⚑ FLAGGED" if item.is_flagged else "")
        )
        hover.append(
            f"<b>{item.key}</b><br>"
            f"{item.title[:55]}<br>"
            f"Type: {item.item_type}<br>"
            f"Status: {item.status}<br>"
            f"Age: <b>{item.age_days:.0f} days</b>"
            + (f"<br>{flags.strip()}" if flags else "")
        )

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=x_vals,
        y=y_vals,
        mode="markers",
        marker=dict(
            color=colours,
            symbol=symbols,
            size=10,
            opacity=0.55,
            line=dict(width=1, color=strokes),
        ),
        hovertemplate="%{text}<extra></extra>",
        text=hover,
        name="In-flight items",
    ))

    # Percentile reference lines — all items share the same historical basis
    ref = items[0]
    for val, label, colour in [
        (ref.p50_reference, "p50", _PERCENTILE_COLOURS[50]),
        (ref.p85_reference, "p85", _PERCENTILE_COLOURS[85]),
        (ref.p95_reference, "p95", _PERCENTILE_COLOURS[95]),
    ]:
        if val > 0:
            fig.add_hline(
                y=val, line_dash="dash", line_color=colour,
                annotation_text=f"{label}: {val:.0f}d",
                annotation_position="top right",
                annotation_font=dict(size=10, color=colour),
            )

    fig.update_layout(
        title="Ageing WIP",
        xaxis=dict(
            tickmode="array",
            tickvals=list(status_x.values()),
            ticktext=list(status_x.keys()),
            title="Current status",
            # Pad edges so jittered markers at column 0 aren't clipped
            range=[-0.6, len(statuses) - 0.4],
        ),
        yaxis_title="Age (calendar days)",
        height=440,
        showlegend=False,
        hovermode="closest",
    )
    return fig


# ── Monte Carlo ───────────────────────────────────────────────────────────────

def mc_histogram(
    raw_samples: list[int],
    percentile_values: dict[int, float],
    mode: str,
    title: str = "",
) -> go.Figure:
    """
    Histogram of MC simulation results with percentile annotations.
    mode="when" → x-axis = weeks; mode="how_many" → x-axis = items.
    """
    if not raw_samples:
        return _empty_fig("No Monte Carlo results.")

    x_label = "Weeks to completion" if mode == "when" else "Items completed"

    fig = px.histogram(
        x=raw_samples,
        nbins=60,
        color_discrete_sequence=[_PALETTE[1]],
        labels={"x": x_label},
        title=title or ("Monte Carlo: When?" if mode == "when" else "Monte Carlo: How Many?"),
    )
    fig.update_traces(opacity=0.8)

    for pct, val in sorted(percentile_values.items()):
        colour = _PERCENTILE_COLOURS.get(pct, "#555555")
        fig.add_vline(
            x=val,
            line_dash="dash",
            line_color=colour,
            annotation_text=f"p{pct}: {val:.0f}",
            annotation_position="top right",
            annotation_font=dict(size=10, color=colour),
        )

    fig.update_layout(
        xaxis_title=x_label,
        yaxis_title="Frequency",
        height=380,
        showlegend=False,
    )
    return fig


# ── Constraint: Age by Status ─────────────────────────────────────────────────

def age_by_status_box(age_by_status: dict[str, list[float]]) -> go.Figure:
    """Box-plot of in-flight item ages grouped by workflow state."""
    if not age_by_status:
        return _empty_fig("No in-flight items for constraint analysis.")

    fig = go.Figure()
    for i, (state, ages) in enumerate(age_by_status.items()):
        if ages:
            n = len(ages)
            colour = _palette_colour(i)
            # Include item count in the box label so sparse states are obvious
            label = f"{state}<br><sub>n={n}</sub>"
            fig.add_trace(go.Box(
                y=ages,
                name=label,
                marker_color=colour,
                boxmean=True,
                # Always show individual points so sparse states are readable
                boxpoints="all",
                jitter=0.3,
                pointpos=0,
                marker=dict(
                    color=colour,
                    size=7,
                    opacity=0.7,
                    line=dict(color="white", width=1),
                ),
                hovertemplate=(
                    f"<b>{state}</b><br>"
                    "Age: %{y:.1f} days<br>"
                    f"n = {n} item{'s' if n != 1 else ''}<extra></extra>"
                ),
            ))

    fig.update_layout(
        title="Item Age by Workflow State",
        yaxis_title="Age (calendar days)",
        xaxis_title="Workflow state",
        height=420,
        showlegend=False,
        hovermode="closest",
    )
    return fig


# ── Plan Accuracy Scatter ─────────────────────────────────────────────────────

def plan_accuracy_scatter(records: list) -> go.Figure:
    """Scatter: target end date (x) vs slip days (y)."""
    from core.models import PlanAccuracyRecord

    if not records:
        return _empty_fig("No plan accuracy data (requires Advanced Roadmaps CSV).")

    x = [r.target_end for r in records]
    y = [r.slip_days for r in records]
    keys = [r.key for r in records]
    titles = [r.title[:40] for r in records]
    colours = [
        _PALETTE[2] if abs(v) <= 3       # on time — bluish green
        else (_PALETTE[5] if v > 3       # late — vermilion
              else _PALETTE[1])          # early — sky blue
        for v in y
    ]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=x, y=y,
        mode="markers",
        marker=dict(color=colours, size=8, opacity=0.8),
        hovertemplate="<b>%{customdata[0]}</b><br>%{customdata[1]}<br>Slip: %{y:.0f} days<extra></extra>",
        customdata=list(zip(keys, titles)),
    ))
    fig.add_hline(y=0, line_dash="dot", line_color="#555555",
                  annotation_text="Target date", annotation_position="bottom right")
    fig.add_hline(y=3, line_dash="dash", line_color=_PALETTE[0],
                  annotation_text="+3d tolerance", annotation_position="top right")
    fig.add_hline(y=-3, line_dash="dash", line_color=_PALETTE[0],
                  annotation_text="-3d tolerance", annotation_position="bottom right")

    fig.update_layout(
        title="Plan Accuracy: Slip Days vs Target End Date",
        xaxis_title="Target end date",
        yaxis_title="Slip (days) — positive = late",
        height=400,
        hovermode="closest",
    )
    return fig


# ── Utility ───────────────────────────────────────────────────────────────────

def _empty_fig(message: str) -> go.Figure:
    """Return a blank figure with a centred annotation."""
    fig = go.Figure()
    fig.add_annotation(
        text=message,
        xref="paper", yref="paper",
        x=0.5, y=0.5,
        showarrow=False,
        font=dict(size=14, color="#888888"),
    )
    fig.update_layout(
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        height=300,
    )
    return fig

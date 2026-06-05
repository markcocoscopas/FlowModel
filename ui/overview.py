"""ui/overview.py — Overview tab."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from core.metrics import (
    cycle_time_stats,
    throughput_stats,
    throughput_weekly,
    wip_snapshot,
    ageing_items,
)
from core.constraints import constraint_report
from config.schema import AppConfig


def render(df: pd.DataFrame, config: AppConfig) -> None:
    st.header("Overview")

    with st.expander("ℹ️ What this tells you", expanded=False):
        st.markdown(
            "The Overview tab gives you a single-screen health check for the "
            "selected squad(s). Metric cards show the headline numbers; "
            "a text summary highlights any patterns worth investigating. "
            "Use the tabs below for deeper analysis."
        )

    if df.empty:
        st.info("No data to display. Load a CSV or click **Load sample data** in the sidebar.")
        return

    # ── KPI cards ─────────────────────────────────────────────────────────────
    ct = cycle_time_stats(df)
    weekly = throughput_weekly(df)
    tp = throughput_stats(weekly)
    wip = wip_snapshot(df, config)
    total_wip = sum(v for k, v in wip.items() if not k.startswith("["))

    ageing = ageing_items(df, config)
    n_blocked = sum(1 for i in ageing if i.is_blocked)
    n_over_p85 = sum(1 for i in ageing if i.age_days > i.p85_reference and i.p85_reference > 0)

    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("Median cycle time", f"{ct.p50:.1f} d", help="50th percentile, calendar days")
    with col2:
        st.metric("85th-pct cycle time", f"{ct.p85:.1f} d", help="85th percentile, calendar days")
    with col3:
        st.metric("Avg throughput", f"{tp.mean_per_week:.1f} /wk", help="Mean items completed per week")
    with col4:
        st.metric("Current WIP", str(total_wip), help="In-flight items right now")
    with col5:
        st.metric("Ageing items (> p85)", str(n_over_p85),
                  delta=f"{n_blocked} blocked" if n_blocked else None,
                  delta_color="inverse")

    st.divider()

    # ── Auto-commentary ───────────────────────────────────────────────────────
    st.subheader("Summary")
    commentary = _build_commentary(df, config, ct, tp, wip, ageing, total_wip)
    st.markdown(commentary)

    st.divider()

    # ── WIP snapshot ──────────────────────────────────────────────────────────
    st.subheader("Current WIP by state")
    wip_display = {k: v for k, v in wip.items() if v > 0}
    if wip_display:
        wip_df = pd.DataFrame(
            {"State": list(wip_display.keys()), "Items": list(wip_display.values())}
        )
        # Colour breach rows
        def _row_style(row: pd.Series) -> list[str]:
            limit = config.wip_limits.get(row["State"])
            if limit and row["Items"] > limit:
                return ["background-color: #fff3cd; font-weight: bold"] * 2
            return [""] * 2

        st.dataframe(
            wip_df.style.apply(_row_style, axis=1),
            use_container_width=True,
            hide_index=True,
        )
        if any(config.wip_limits.get(s, 999) < v for s, v in wip_display.items()):
            st.caption("⚠️ Highlighted rows exceed the configured WIP limit.")

        # ── Ticket drill-down ─────────────────────────────────────────────────
        in_flight = df[df["resolved"].isna() & df["created"].notna()].copy()
        if not in_flight.empty:
            today = pd.Timestamp.now().normalize()
            in_flight["Age (days)"] = (today - in_flight["created"]).dt.days

            with st.expander("📋 View in-flight tickets", expanded=False):
                cols = {}
                for c, label in [
                    ("key",    "Key"),
                    ("title",  "Title"),
                    ("type",   "Type"),
                    ("squad",  "Squad"),
                    ("status", "Status"),
                ]:
                    if c in in_flight.columns:
                        cols[c] = label
                cols["Age (days)"] = "Age (days)"

                display = in_flight[list(cols.keys())].rename(columns=cols)
                display = display.sort_values("Age (days)", ascending=False)
                st.dataframe(display, use_container_width=True, hide_index=True)
    else:
        st.info("No in-flight items.")


def _build_commentary(df, config, ct, tp, wip, ageing, total_wip) -> str:
    """Auto-generate a short plain-English summary paragraph."""
    lines = []

    # Cycle time trend (rough: compare last 4 weeks to previous 4 weeks)
    from core.metrics import cycle_time_series
    ct_series = cycle_time_series(df).dropna()
    resolved = df.loc[ct_series.index, "resolved"].dropna()
    if not resolved.empty:
        mid = resolved.sort_values().iloc[len(resolved) // 2]
        recent_ct = ct_series[resolved >= mid]
        older_ct  = ct_series[resolved < mid]
        if len(recent_ct) >= 3 and len(older_ct) >= 3:
            import numpy as np
            delta = recent_ct.median() - older_ct.median()
            if abs(delta) >= 1:
                direction = "upward" if delta > 0 else "downward"
                lines.append(
                    f"Cycle time has trended **{direction}** over the latter half of the "
                    f"selected date range (median {recent_ct.median():.1f} d vs "
                    f"{older_ct.median():.1f} d previously)."
                )

    # Throughput
    if tp.mean_per_week > 0:
        lines.append(
            f"Mean weekly throughput is **{tp.mean_per_week:.1f} items/week** "
            f"(range {tp.min_per_week}–{tp.max_per_week})."
        )

    # WIP
    breach_states = [
        s for s, v in wip.items()
        if config.wip_limits.get(s, 999) < v
    ]
    if breach_states:
        lines.append(
            f"WIP limits are **breached** in: {', '.join(breach_states)}. "
            "High WIP is a leading indicator of longer cycle times."
        )

    # Ageing
    n_over_p85 = sum(1 for i in ageing if i.age_days > i.p85_reference and i.p85_reference > 0)
    n_blocked  = sum(1 for i in ageing if i.is_blocked)
    if n_over_p85 > 0:
        lines.append(
            f"**{n_over_p85}** in-flight item(s) have aged beyond the 85th-percentile "
            "historical cycle time — these are overdue by historical standards."
        )
    if n_blocked > 0:
        lines.append(f"**{n_blocked}** item(s) are currently flagged as blocked.")

    # Constraint hint
    cr = constraint_report(df, config)
    if cr.candidate_constraint_state:
        lines.append(
            f"The candidate constraint is **{cr.candidate_constraint_state}** — "
            f"it has the highest median in-flight age at "
            f"{cr.candidate_constraint_median_days:.1f} days."
        )

    if not lines:
        lines.append("No significant flow issues detected in the current date range.")

    return "\n\n".join(lines)

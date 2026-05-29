"""ui/plan_accuracy.py — Plan Accuracy & Sprint Slippage tab."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from pathlib import Path

from core.plan_accuracy import (
    date_drift_summary,
    delivery_risk_summary,
    plan_accuracy_records,
    plan_accuracy_summary,
    sprint_slippage_summary,
)
from config.schema import AppConfig
from core.ingest import load_roadmaps
from ui.charts import plan_accuracy_scatter

_HIERARCHY_ORDER = ["Capability", "Initiative", "Theme", "Epic", "Story",
                    "Sub-task", "Task", "Bug", "Spike"]
_RAG_COLOUR = {"Red": "🔴", "Amber": "🟠", "Green": "🟢", "": "⚪"}


def _s(val, default: str = "") -> str:
    """Safe str() that returns *default* for any NaN/None/empty variant."""
    if val is None:
        return default
    try:
        import math
        if isinstance(val, float) and math.isnan(val):
            return default
    except (TypeError, ValueError):
        pass
    s = str(val).strip()
    return s if s and s.lower() != "nan" else default


def _render_epic_progress(df: pd.DataFrame) -> None:
    """
    Show an Epic / Capability progress table from the roadmaps data.
    Only rendered when the roadmaps CSV is loaded and Epics/Capabilities
    are present in the current data.
    """
    if "rm_target_end" not in df.columns:
        return

    _EPIC_TYPES = {"Epic", "Capability", "Initiative", "Theme"}

    # Use the `hierarchy` column (from roadmaps) when available; fall back
    # to the Jira `type` column so the section still works without roadmaps.
    if "hierarchy" in df.columns:
        mask = df["hierarchy"].isin(_EPIC_TYPES) | df["type"].isin(_EPIC_TYPES)
    else:
        mask = df["type"].isin(_EPIC_TYPES)

    epics_df = df[mask].copy()

    if epics_df.empty:
        return

    st.subheader("📋 Epic / Capability Progress")
    st.caption(
        "Roll-up view of Epics and Capabilities from the Advanced Roadmaps CSV — "
        "showing target date, delivery risk, and story-count progress. "
        "See the **Delivery Risk** section above for a breakdown across all work item types including Stories."
    )

    today = pd.Timestamp.now().normalize()

    rows = []
    for _, row in epics_df.iterrows():
        target_end = row.get("rm_target_end")
        if pd.isna(target_end):
            days_rem = None
            due_str  = "—"
        else:
            days_rem = int((target_end - today).total_seconds() // 86400)
            due_str  = target_end.strftime("%d %b %Y")

        progress = row.get("rm_progress_pct")
        done_ic  = row.get("rm_done_ic")
        total_ic = row.get("rm_total_ic")
        rag      = _s(row.get("rm_rag"))
        rag_icon = _RAG_COLOUR.get(rag, "⚪")

        hier = _s(row.get("hierarchy")) or _s(row.get("type"))

        if days_rem is None:
            risk_label = "—"
        elif days_rem < 0:
            risk_label = f"🔴 {abs(days_rem)}d overdue"
        elif days_rem <= 14:
            risk_label = f"🟠 {days_rem}d left"
        else:
            risk_label = f"🟢 {days_rem}d left"

        ic_str = (
            f"{int(done_ic)}/{int(total_ic)}"
            if pd.notna(done_ic) and pd.notna(total_ic) else "—"
        )

        rows.append({
            "Key":          _s(row.get("key")),
            "Title":        _s(row.get("title"))[:60],
            "Level":        hier,
            "Status":       _s(row.get("status")),
            "Target end":   due_str,
            "Delivery":     risk_label,
            "Progress %":   f"{int(progress)}%" if pd.notna(progress) else "—",
            "Done / Total": ic_str,
            "RAG":          f"{rag_icon} {rag}" if rag else "—",
        })

    if not rows:
        st.info("No Epics/Capabilities with roadmaps data in the current filters.")
        return

    # Sort by hierarchy order then by target end date
    def _sort_key(r):
        lvl = _HIERARCHY_ORDER.index(r["Level"]) if r["Level"] in _HIERARCHY_ORDER else 99
        return (lvl, r["Target end"])

    rows.sort(key=_sort_key)
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

_ON_TIME_COLOUR  = "#009E73"   # bluish green
_LATE_COLOUR     = "#D55E00"   # vermilion
_EARLY_COLOUR    = "#56B4E9"   # sky blue
_OVERDUE_COLOUR  = "#D55E00"   # vermilion (red)
_AT_RISK_COLOUR  = "#E69F00"   # orange
_OK_COLOUR       = "#009E73"   # green


# ── Delivery Risk helper ──────────────────────────────────────────────────────

def _render_delivery_risk(df: pd.DataFrame, title_prefix: str = "") -> None:
    """
    Render the in-flight delivery risk section.
    Shows items that have a target end date but are not yet resolved.
    """
    risk = delivery_risk_summary(df)
    if not risk:
        st.info(
            "No in-flight items have a target end date. "
            "Upload an Advanced Roadmaps CSV with *Target end date* values to see delivery risk."
        )
        return

    heading = f"{title_prefix}Delivery Risk — In-Flight Items"
    st.subheader(heading)
    st.caption(
        "Items that are not yet resolved, grouped by how they track against their "
        "Advanced Roadmaps target end date."
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Items tracked",  risk["n_tracked"],
              help="In-flight items with a target end date from the Roadmaps CSV")
    c2.metric(
        "🔴 Overdue",           risk["n_overdue"],
        delta=f"-{risk['n_overdue']}" if risk["n_overdue"] else None,
        delta_color="inverse",
        help="Target end date has already passed",
    )
    c3.metric(
        "🟠 At risk (≤14 d)",   risk["n_at_risk"],
        help="Target end date is within the next 14 days",
    )
    c4.metric(
        "🟢 On track",          risk["n_on_track"],
        help="Target end date is more than 14 days away",
    )

    records_df = risk["records"]

    # ── Gantt-style bar chart: items by days remaining ────────────────────────
    colours = records_df["risk"].map({
        "overdue":  _OVERDUE_COLOUR,
        "at_risk":  _AT_RISK_COLOUR,
        "on_track": _OK_COLOUR,
    }).tolist()

    label_col = "hierarchy" if "hierarchy" in records_df.columns else "type"
    hover_texts = [
        f"<b>{_s(row.get('key'))}</b><br>"
        f"{_s(row.get('title'))[:60]}<br>"
        f"Type: {_s(row.get(label_col)) or _s(row.get('type'))}<br>"
        f"Status: {_s(row.get('status'))}<br>"
        f"Target: {str(row['rm_target_end'])[:10]}<br>"
        f"Days remaining: {int(row['days_remaining'])}"
        for _, row in records_df.iterrows()
    ]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=records_df["days_remaining"].tolist(),
        y=(records_df["key"] + "  ").tolist(),
        orientation="h",
        marker_color=colours,
        text=records_df["rm_target_end"].dt.strftime("%d %b %y").tolist(),
        textposition="outside",
        hovertext=hover_texts,
        hoverinfo="text",
    ))
    fig.add_vline(x=0, line_dash="dash", line_color="#555555", line_width=1.5)
    fig.add_vline(x=14, line_dash="dot", line_color=_AT_RISK_COLOUR, line_width=1)
    fig.update_layout(
        xaxis_title="Days remaining until target end date  (negative = overdue)",
        yaxis_title=None,
        yaxis_autorange="reversed",
        height=max(300, 28 * len(records_df) + 80),
        margin=dict(l=10, r=80, t=30, b=40),
        plot_bgcolor="white",
        xaxis=dict(gridcolor="#e8e8e8", zeroline=False),
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption(
        "🔴 Overdue (past target) · 🟠 At risk (≤14 days) · 🟢 On track  |  "
        "Dashed line = today, dotted = 14-day warning threshold."
    )

    # ── Detail table ──────────────────────────────────────────────────────────
    with st.expander("📋 Delivery risk detail table"):
        display_cols = {
            "key":            "Key",
            "title":          "Title",
            "status":         "Status",
            "rm_target_end":  "Target end",
            "days_remaining": "Days remaining",
            "risk":           "Risk",
        }
        if "hierarchy" in records_df.columns:
            display_cols = {"key": "Key", "title": "Title", "hierarchy": "Hierarchy",
                            "status": "Status", "rm_target_end": "Target end",
                            "days_remaining": "Days remaining", "risk": "Risk"}

        show_df = records_df[[c for c in display_cols if c in records_df.columns]].copy()
        show_df = show_df.rename(columns=display_cols)
        if "Target end" in show_df.columns:
            show_df["Target end"] = show_df["Target end"].dt.strftime("%d %b %Y")
        st.dataframe(show_df, use_container_width=True, hide_index=True)


# ── Date Drift ────────────────────────────────────────────────────────────────

_DRIFT_COLOURS = {
    "major":      "#D55E00",   # vermilion
    "moderate":   "#E69F00",   # orange
    "minor":      "#F0E442",   # yellow
    "pulled_in":  "#56B4E9",   # sky blue
    "unchanged":  "#CCCCCC",   # grey
}


def _render_date_drift(config: AppConfig) -> None:
    """
    Self-contained section: uploads a baseline Roadmaps CSV, compares it with
    the current roadmaps data stored in session state, and renders a drift chart.
    """
    st.subheader("📅 Date Drift Analysis")
    with st.expander("ℹ️ What is date drift?", expanded=False):
        st.markdown(
            "When a story or epic reaches its target end date without being "
            "completed, teams often quietly push the date out rather than "
            "recording a miss. Over many iterations this *soft slip* can hide "
            "significant schedule risk.\n\n"
            "**How to use this:** upload a copy of the Advanced Roadmaps CSV "
            "from an earlier point in time (your original plan). The chart "
            "compares every item's baseline target date with its current target "
            "date and shows how many days each has drifted.\n\n"
            "| Colour | Drift |\n"
            "|--------|-------|\n"
            "| 🔴 Major | > 30 days |\n"
            "| 🟠 Moderate | 8 – 30 days |\n"
            "| 🟡 Minor | 1 – 7 days |\n"
            "| 🔵 Pulled in | date moved earlier |\n"
            "| ⚫ Unchanged | no change |"
        )

    baseline_file = st.file_uploader(
        "Upload baseline Roadmaps CSV (your original plan)",
        type=["csv"],
        key="baseline_roadmaps_upload",
        help=(
            "Export the Advanced Roadmaps CSV from Jira at the start of the PI / "
            "sprint cycle and upload it here. The app will compare target end dates "
            "between that baseline and the current roadmaps export."
        ),
    )

    # Cache baseline in session state so it survives Streamlit re-runs
    if baseline_file is not None:
        tmp_dir = Path(st.session_state.get("tmp_dir", "/tmp/squad_flow"))
        tmp_dir.mkdir(parents=True, exist_ok=True)
        baseline_path = tmp_dir / "baseline_roadmaps.csv"
        baseline_path.write_bytes(baseline_file.read())
        st.session_state["_baseline_rm_path"] = str(baseline_path)

    baseline_path_str = st.session_state.get("_baseline_rm_path")
    current_rm_df     = st.session_state.get("_current_rm_df")  # set below after load

    if not baseline_path_str:
        st.info(
            "Upload a baseline Roadmaps CSV above to see how much target dates "
            "have drifted since the original plan."
        )
        return

    if current_rm_df is None:
        st.warning(
            "Current Roadmaps CSV not loaded. "
            "Upload it via the sidebar first, then load the baseline here."
        )
        return

    try:
        baseline_rm_df = load_roadmaps(baseline_path_str, config)
    except Exception as exc:
        st.error(f"Could not read baseline CSV: {exc}")
        return

    drift = date_drift_summary(baseline_rm_df, current_rm_df)

    if not drift:
        st.warning(
            "No overlapping items with target end dates found in both CSVs. "
            "Make sure both files come from the same Jira project and contain "
            "`Target end date` values."
        )
        return

    # ── Summary metrics ───────────────────────────────────────────────────────
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Items compared",    drift["n_compared"])
    c2.metric(
        "🔴 Dates drifted later",  drift["n_drifted"],
        help="Items whose target end date is later in the current export than in the baseline",
    )
    c3.metric(
        "Avg drift (drifted items)",
        f"+{drift['avg_drift_days']:.1f} d" if drift["n_drifted"] else "—",
    )
    c4.metric(
        "Worst single drift",
        f"+{drift['max_drift_days']} d" if drift["n_drifted"] else "—",
    )
    c5.metric(
        "🔵 Pulled in earlier",    drift["n_pulled_in"],
        help="Items whose target end date was moved earlier — a positive signal",
    )

    if drift["n_drifted"] == 0:
        st.success("✅ No target date drift detected — all dates are unchanged or pulled in.")
        return

    st.caption(
        f"**Total soft slip across all drifted items: "
        f"{drift['total_drift_days']:,} days** — the cumulative cost of date extensions."
    )

    st.divider()

    # ── Drift bar chart ───────────────────────────────────────────────────────
    records = drift["records"]
    drifted_only = records[records["drift_days"] != 0].head(50)  # cap at 50 for readability

    colours = drifted_only["drift_class"].map(_DRIFT_COLOURS).tolist()
    hover = [
        f"<b>{row['key']}</b><br>"
        f"Baseline: {row['baseline_end_str']}<br>"
        f"Current:  {row['current_end_str']}<br>"
        f"Drift: <b>{'+' if row['drift_days'] > 0 else ''}{int(row['drift_days'])} days</b>"
        for _, row in drifted_only.iterrows()
    ]

    import plotly.graph_objects as go
    fig = go.Figure(go.Bar(
        x=drifted_only["drift_days"].tolist(),
        y=(drifted_only["key"] + "  ").tolist(),
        orientation="h",
        marker_color=colours,
        hovertext=hover,
        hoverinfo="text",
        text=[
            f"{'+' if d > 0 else ''}{int(d)} d"
            for d in drifted_only["drift_days"]
        ],
        textposition="outside",
    ))
    fig.add_vline(x=0, line_dash="solid", line_color="#555555", line_width=1)
    fig.update_layout(
        xaxis_title="Drift (days) — positive = date pushed later",
        yaxis_title=None,
        yaxis_autorange="reversed",
        height=max(300, 28 * len(drifted_only) + 80),
        margin=dict(l=10, r=80, t=30, b=40),
        plot_bgcolor="white",
        xaxis=dict(gridcolor="#e8e8e8", zeroline=False),
    )
    st.plotly_chart(fig, use_container_width=True)
    if len(records[records["drift_days"] != 0]) > 50:
        st.caption("Showing top 50 items by drift. See the detail table below for the full list.")

    # ── By hierarchy level ────────────────────────────────────────────────────
    st.divider()
    st.subheader("Drift summary by level")
    by_hier = drift["by_hierarchy"].copy()
    by_hier.columns = ["Level", "Items compared", "Items drifted",
                       "Avg drift (d)", "Max drift (d)", "Total drift (d)"]
    st.dataframe(by_hier, use_container_width=True, hide_index=True)

    # ── Detail table ──────────────────────────────────────────────────────────
    with st.expander("📋 Full drift detail"):
        show = records[[
            "key", "hierarchy", "baseline_end_str", "current_end_str",
            "drift_days", "drift_class",
        ]].rename(columns={
            "key":               "Key",
            "hierarchy":         "Level",
            "baseline_end_str":  "Baseline target",
            "current_end_str":   "Current target",
            "drift_days":        "Drift (days)",
            "drift_class":       "Classification",
        })
        st.dataframe(show, use_container_width=True, hide_index=True)


# ── Main render ───────────────────────────────────────────────────────────────

def render(df: pd.DataFrame, config: AppConfig) -> None:
    st.header("Plan Accuracy")

    with st.expander("ℹ️ What this tells you", expanded=False):
        st.markdown(
            "**Delivery Risk** shows in-flight items (not yet done) against their "
            "Advanced Roadmaps target end dates — letting you spot what's already "
            "overdue or close to its deadline.\n\n"
            "**Historical Accuracy** compares the *target end date* with the *actual "
            "resolution date* for completed items. Positive slip = delivered late; "
            "negative = delivered early.\n\n"
            "**Sprint Slippage** counts how many items were delivered in a later sprint "
            "than originally planned.\n\n"
            "**Requires:** the Advanced Roadmaps CSV to be loaded alongside the "
            "snapshot CSV."
        )

    if "rm_target_end" not in df.columns:
        st.warning(
            "Advanced Roadmaps CSV not loaded. "
            "Upload it via the sidebar to enable plan accuracy metrics."
        )
        return

    squads = sorted(df["squad"].dropna().unique().tolist())

    # ── Sub-tabs: Overall vs By Squad ─────────────────────────────────────────
    if len(squads) > 1:
        overall_tab, by_squad_tab = st.tabs(["📊 Overall", "👥 By Squad"])
    else:
        overall_tab = st.container()
        by_squad_tab = None

    # ── Overall ───────────────────────────────────────────────────────────────
    with overall_tab:

        # Section 1: In-flight delivery risk (always shown when roadmaps CSV loaded)
        _render_delivery_risk(df)

        st.divider()

        # Section 2: Epic / Capability progress
        _render_epic_progress(df)

        st.divider()

        # Section 3: Historical accuracy for resolved items
        st.subheader("Historical Accuracy — Completed Items")
        records = plan_accuracy_records(df)

        if not records:
            st.info(
                "No completed items have a target end date yet — "
                "historical accuracy will appear here once items are resolved.\n\n"
                "**Tip:** if your Jira snapshot export was filtered to in-progress "
                "items only, re-export it to include **Done** items so past accuracy "
                "can be measured."
            )
        else:
            summary = plan_accuracy_summary(records)

            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Items analysed", summary.get("n_items", 0))
            c2.metric("On time (±3d)",
                      f"{summary.get('pct_on_time', 0)}%",
                      help=f"{summary.get('n_on_time', 0)} items delivered within ±3 days of target")
            c3.metric("Late",
                      summary.get("n_late", 0),
                      help="Delivered more than 3 days after target end date")
            c4.metric("Early",
                      summary.get("n_early", 0),
                      help="Delivered more than 3 days before target end date")
            c5.metric("Median slip",
                      f"{summary.get('median_slip_days', 0):+.0f} d",
                      help="Positive = late on average, negative = early on average")

            st.divider()

            fig = plan_accuracy_scatter(records)
            st.plotly_chart(fig, use_container_width=True)
            st.caption(
                "Colours: 🟢 on time (within ±3 days), 🔴 late, 🔵 early. "
                "Dashed lines show the ±3-day tolerance band."
            )

            with st.expander("📋 Plan accuracy detail"):
                rows = [{
                    "Key":               r.key,
                    "Title":             r.title,
                    "Type":              r.item_type,
                    "Squad":             r.squad,
                    "Target end":        str(r.target_end)[:10] if r.target_end else "",
                    "Resolved":          str(r.resolved)[:10]   if r.resolved   else "",
                    "Slip (days)":       r.slip_days,
                    "Sprint planned":    r.sprint_planned,
                    "Sprint delivered":  r.sprint_delivered,
                } for r in sorted(records, key=lambda r: r.slip_days, reverse=True)]
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        st.divider()

        # Section 4: Date drift (baseline vs current roadmaps)
        _render_date_drift(config)

        st.divider()
        st.subheader("Sprint Slippage")
        slip = sprint_slippage_summary(df)
        if slip:
            if not slip.get("data_reliable", True):
                st.warning(
                    "⚠️ **Sprint slippage data is unreliable for this dataset.**\n\n"
                    + slip.get("data_warning", "")
                )
            else:
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Items with sprint data", slip.get("n_items_with_sprint_data", 0))
                c2.metric("No slip",
                          f"{slip.get('n_no_slip', 0)} ({slip.get('pct_no_slip', 0)}%)")
                c3.metric("Slipped 1 sprint",       slip.get("n_slipped_1", 0))
                c4.metric("Slipped 2+ sprints",     slip.get("n_slipped_2plus", 0))
        else:
            st.info("Sprint data not available or insufficient for slippage analysis.")

    # ── By Squad ──────────────────────────────────────────────────────────────
    if by_squad_tab is None:
        return

    with by_squad_tab:

        # Delivery risk per squad
        for squad in squads:
            sdf = df[df["squad"] == squad]
            _render_delivery_risk(sdf, title_prefix=f"{squad} — ")
            st.divider()

        # Epic/Capability progress (all squads combined — roadmaps is cross-squad)
        _render_epic_progress(df)

        st.divider()

        # Historical accuracy summary table
        st.subheader("Historical Accuracy by Squad")
        pa_rows = []
        for squad in squads:
            sdf     = df[df["squad"] == squad]
            records = plan_accuracy_records(sdf)
            if not records:
                continue
            s    = plan_accuracy_summary(records)
            slip = sprint_slippage_summary(sdf)
            pa_rows.append({
                "Squad":           squad,
                "Items":           s.get("n_items", 0),
                "On time %":       f"{s.get('pct_on_time', 0)}%",
                "On time (n)":     s.get("n_on_time", 0),
                "Late":            s.get("n_late", 0),
                "Early":           s.get("n_early", 0),
                "Median slip (d)": f"{s.get('median_slip_days', 0):+.0f}",
                "Sprint slip %":   f"{slip.get('pct_slipped', '—')}%" if slip else "—",
            })

        if not pa_rows:
            st.info(
                "No completed items have a target end date yet. "
                "Historical accuracy will appear here once resolved items with "
                "target dates exist in the data."
            )
        else:
            st.dataframe(pd.DataFrame(pa_rows), use_container_width=True, hide_index=True)
            st.caption("Median slip: positive = late on average, negative = early on average.")

            st.divider()

            # Small-multiples scatter: one panel per squad
            n      = len(pa_rows)
            n_cols = min(n, 3)
            n_rows = (n + n_cols - 1) // n_cols
            pa_squads = [r["Squad"] for r in pa_rows]

            fig = make_subplots(
                rows=n_rows, cols=n_cols,
                subplot_titles=pa_squads,
                shared_yaxes=True,
            )

            for idx, squad in enumerate(pa_squads):
                row = idx // n_cols + 1
                col = idx % n_cols + 1
                sdf     = df[df["squad"] == squad]
                records = plan_accuracy_records(sdf)
                if not records:
                    continue

                x       = [r.target_end  for r in records]
                y       = [r.slip_days   for r in records]
                keys    = [r.key         for r in records]
                titles_ = [r.title[:35]  for r in records]
                colours = [
                    _ON_TIME_COLOUR if abs(v) <= 3
                    else (_LATE_COLOUR if v > 3 else _EARLY_COLOUR)
                    for v in y
                ]

                fig.add_trace(
                    go.Scatter(
                        x=x, y=y,
                        mode="markers",
                        marker=dict(color=colours, size=7, opacity=0.8),
                        hovertemplate=(
                            "<b>%{customdata[0]}</b><br>"
                            "%{customdata[1]}<br>"
                            "Slip: %{y:+.0f}d<extra></extra>"
                        ),
                        customdata=list(zip(keys, titles_)),
                        showlegend=False,
                    ),
                    row=row, col=col,
                )
                fig.add_hline(y=0,  line_dash="dot",  line_color="#555555", row=row, col=col)
                fig.add_hline(y=3,  line_dash="dash", line_color="#E69F00", row=row, col=col)
                fig.add_hline(y=-3, line_dash="dash", line_color="#E69F00", row=row, col=col)

            fig.update_layout(
                height=340 * n_rows,
                title_text="Slip days vs target end date  (🟢 on time  🔴 late  🔵 early)",
                hovermode="closest",
                yaxis_title="Slip (days)",
            )
            st.plotly_chart(fig, use_container_width=True)

        # Sprint slippage per squad
        st.divider()
        st.subheader("Sprint Slippage by Squad")
        slip_rows = []
        unreliable_squads = []
        for squad in squads:
            sdf  = df[df["squad"] == squad]
            slip = sprint_slippage_summary(sdf)
            if not slip:
                continue
            if not slip.get("data_reliable", True):
                unreliable_squads.append(squad)
                continue
            slip_rows.append({
                "Squad":              squad,
                "Items w/ sprint":    slip.get("n_items_with_sprint_data", 0),
                "No slip":            f"{slip.get('n_no_slip', 0)} ({slip.get('pct_no_slip', 0)}%)",
                "Slipped 1 sprint":   slip.get("n_slipped_1", 0),
                "Slipped 2+ sprints": slip.get("n_slipped_2plus", 0),
                "Slip %":             f"{slip.get('pct_slipped', 0)}%",
            })
        if unreliable_squads:
            st.warning(
                "⚠️ **Sprint slippage data is unreliable** for: "
                + ", ".join(f"**{s}**" for s in unreliable_squads)
                + ". Jira appears to have replaced the Sprint field rather than keeping "
                "history — so every item shows the same planned and delivered sprint. "
                "Reliable slippage data requires the Jira API changelog."
            )
        if slip_rows:
            st.dataframe(pd.DataFrame(slip_rows), use_container_width=True, hide_index=True)
        else:
            st.info("Sprint data not available for any squad.")

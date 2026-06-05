"""ui/plan_accuracy.py — Plan Accuracy & Sprint Slippage tab."""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from core.plan_accuracy import (
    date_drift_summary,
    drift_adjusted_targets,
    drift_velocity,
    delivery_risk_summary,
    plan_accuracy_records,
    plan_accuracy_summary,
    sprint_slippage_summary,
)
from config.schema import AppConfig
from core.ingest import load_roadmaps, load_for_drift
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

def _render_delivery_risk(df: pd.DataFrame, title_prefix: str = "", chart_key: str = "all") -> None:
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
    st.plotly_chart(fig, use_container_width=True, key=f"delivery_risk_chart_{chart_key}")
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
    "major":      "#D55E00",
    "moderate":   "#E69F00",
    "minor":      "#F0E442",
    "pulled_in":  "#56B4E9",
    "unchanged":  "#CCCCCC",
}

_DRIFT_LABELS = {
    "major":     "🔴 Major (>30 d)",
    "moderate":  "🟠 Moderate (8–30 d)",
    "minor":     "🟡 Minor (1–7 d)",
    "pulled_in": "🔵 Pulled in",
    "unchanged": "⚫ Unchanged",
}


def _parse_date_from_filename(name: str) -> "pd.Timestamp | None":
    """Try to extract an export date from a Jira-style filename."""
    # DDMMYYYY (e.g. "27052026")
    m = re.search(r"(\d{2})(\d{2})(\d{4})", name)
    if m:
        try:
            return pd.Timestamp(year=int(m.group(3)), month=int(m.group(2)), day=int(m.group(1)))
        except ValueError:
            pass
    # YYYY-MM-DD
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", name)
    if m:
        try:
            return pd.Timestamp(m.group(0))
        except ValueError:
            pass
    return None


def _drift_bar_chart(records: pd.DataFrame, label: str = "", chart_key: str = "0") -> None:
    """Render the horizontal drift bar chart for a set of records."""
    show = records[records["drift_days"] != 0].head(50)
    if show.empty:
        st.success("✅ No drift detected — all target dates are unchanged or pulled in.")
        return

    colours = show["drift_class"].map(_DRIFT_COLOURS).tolist()
    hover = [
        f"<b>{_s(row.get('key'))}</b><br>"
        f"Squad: {_s(row.get('squad'))}<br>"
        f"Level: {_s(row.get('hierarchy'))}<br>"
        f"Baseline: {_s(row.get('baseline_end_str'))}<br>"
        f"Current:  {_s(row.get('current_end_str'))}<br>"
        f"Drift: <b>{'+' if row['drift_days'] > 0 else ''}{int(row['drift_days'])} days</b>"
        for _, row in show.iterrows()
    ]

    fig = go.Figure(go.Bar(
        x=show["drift_days"].tolist(),
        y=(show["key"] + "  ").tolist(),
        orientation="h",
        marker_color=colours,
        hovertext=hover,
        hoverinfo="text",
        text=[f"{'+' if d > 0 else ''}{int(d)} d" for d in show["drift_days"]],
        textposition="outside",
    ))
    fig.add_vline(x=0, line_dash="solid", line_color="#555555", line_width=1)
    fig.update_layout(
        title=label or None,
        xaxis_title="Drift (days) — positive = date pushed later",
        yaxis_title=None,
        yaxis_autorange="reversed",
        height=max(300, 28 * len(show) + 80),
        margin=dict(l=10, r=80, t=40 if label else 20, b=40),
        plot_bgcolor="white",
        xaxis=dict(gridcolor="#e8e8e8", zeroline=False),
    )
    st.plotly_chart(fig, use_container_width=True, key=f"drift_bar_{chart_key}")
    if len(records[records["drift_days"] != 0]) > 50:
        st.caption("Showing top 50 items. See the detail table below for the full list.")


def _render_date_drift(config: AppConfig) -> None:
    """
    Date Drift Analysis — three sub-tabs:
      1. Snapshot comparison  (baseline vs current, with squad breakdown)
      2. Drift velocity        (multiple snapshots over time)
      3. Adjusted forecast     (project future drift at current rate)
    """
    st.subheader("📅 Date Drift Analysis")
    with st.expander("ℹ️ What is date drift?", expanded=False):
        st.markdown(
            "When a story or epic reaches its target end date without being completed, "
            "teams often quietly extend the date rather than record a miss. Over many "
            "iterations this *soft slip* compounds into significant hidden schedule risk.\n\n"
            "**Three views:**\n"
            "- **Snapshot comparison** — how much have dates moved since your original plan?\n"
            "- **Drift velocity** — is drift accelerating or slowing? Upload multiple historical "
            "exports to see the trend.\n"
            "- **Adjusted forecast** — if drift continues at its current rate, when will each "
            "item *actually* land?\n\n"
            "| Colour | Classification |\n|--------|----------------|\n"
            "| 🔴 | Major — > 30 days |\n"
            "| 🟠 | Moderate — 8–30 days |\n"
            "| 🟡 | Minor — 1–7 days |\n"
            "| 🔵 | Pulled in — date moved earlier |\n"
            "| ⚫ | Unchanged |"
        )

    # Accept either a roadmaps CSV (has "Target end date") or a regular Jira
    # snapshot CSV (uses "Custom field (Target end)" or similar).
    current_rm_df = st.session_state.get("_current_rm_df")
    if current_rm_df is None:
        st.info(
            "Load the **current** Jira export via the sidebar first "
            "(either an Advanced Roadmaps CSV or a regular snapshot CSV that "
            "contains a target end date field), then upload the older baseline here."
        )
        return

    tab_snap, tab_vel, tab_forecast = st.tabs([
        "📸 Snapshot comparison",
        "📈 Drift velocity",
        "🔮 Adjusted forecast",
    ])

    # ── 1. Snapshot comparison ────────────────────────────────────────────────
    with tab_snap:
        tmp_dir = Path(st.session_state.get("tmp_dir", "/tmp/squad_flow"))
        tmp_dir.mkdir(parents=True, exist_ok=True)

        baseline_files = st.file_uploader(
            "Baseline CSV(s) — one per squad (original plan)",
            type=["csv"],
            key="baseline_roadmaps_upload",
            accept_multiple_files=True,
            help=(
                "Upload one baseline per squad — either an Advanced Roadmaps CSV or a "
                "regular snapshot CSV with a target end date field. "
                "The app auto-detects the format and matches each baseline to the "
                "correct squad in the current data by squad name."
            ),
        )

        # Save each uploaded baseline; track by index so re-runs don't re-read
        if baseline_files:
            saved = {}
            guesses = {}
            for i, f in enumerate(baseline_files):
                p = tmp_dir / f"baseline_roadmaps_{i}.csv"
                p.write_bytes(f.read())
                saved[i]  = str(p)
                guesses[i] = _parse_date_from_filename(f.name)
            st.session_state["_baseline_rm_paths"]  = saved
            st.session_state["_baseline_date_guesses"] = guesses

        saved_paths  = st.session_state.get("_baseline_rm_paths", {})
        date_guesses = st.session_state.get("_baseline_date_guesses", {})

        if not saved_paths:
            st.info(
                "Upload one baseline CSV per squad above to compare with the current export.\n\n"
                "**Tip:** for PI planning, export each squad's CSV on day 1 of PI planning "
                "and upload them all here — the app will match each to its squad automatically."
            )
            return

        # Single shared baseline date (PI planning day is the same for all squads)
        first_guess   = next(iter(date_guesses.values()), None)
        default_date  = first_guess.date() if first_guess else pd.Timestamp.now().date()
        baseline_date = st.date_input(
            "When were these baseline CSVs exported?",
            value=default_date,
            key="baseline_export_date",
            help="Usually the last day of PI planning. Used to calculate the drift rate.",
        )
        baseline_ts = pd.Timestamp(baseline_date)

        # Load all baselines and detect their squad names
        baseline_dfs: list[tuple[str, pd.DataFrame]] = []
        for i, path_str in saved_paths.items():
            try:
                bdf = load_for_drift(path_str, config)
                squad_name = (
                    bdf["rm_squad"].dropna().mode().iloc[0]
                    if not bdf["rm_squad"].dropna().empty
                    else f"Baseline {i + 1}"
                )
                baseline_dfs.append((_s(squad_name), bdf))
            except Exception as exc:
                st.error(f"Could not read baseline {i + 1}: {exc}")

        if not baseline_dfs:
            return

        # ── Render results — one section per squad ─────────────────────────────
        # Collect all drift results first so we can show a combined summary header
        results: list[tuple[str, dict]] = []
        today = pd.Timestamp.now().normalize()

        for squad_name, baseline_rm_df in baseline_dfs:
            # Filter current data to this squad (or use all if only one squad)
            if "rm_squad" in current_rm_df.columns:
                curr_squad = current_rm_df[
                    current_rm_df["rm_squad"].fillna("").str.strip() == squad_name.strip()
                ]
                if curr_squad.empty:
                    curr_squad = current_rm_df   # fallback: compare against everything
            else:
                curr_squad = current_rm_df

            drift = date_drift_summary(baseline_rm_df, curr_squad, baseline_date=baseline_ts)
            if drift:
                results.append((squad_name, drift))

        if not results:
            st.warning("No overlapping items with target end dates found in any baseline.")
            return

        # Store drift rate from first result for Adjusted Forecast tab
        first_drift = results[0][1]
        if first_drift.get("drift_rate_per_day"):
            st.session_state["_drift_rate_per_day"] = first_drift["drift_rate_per_day"]

        elapsed_days = max(int((today - baseline_ts).total_seconds() / 86400), 1)
        window_short = elapsed_days < 14

        # ── Combined header metrics across all squads ──────────────────────────
        if len(results) > 1:
            total_compared = sum(r["n_compared"]    for _, r in results)
            total_drifted  = sum(r["n_drifted"]     for _, r in results)
            total_slip     = sum(r["total_drift_days"] for _, r in results)
            worst_drift    = max(r["max_drift_days"] for _, r in results)
            st.markdown(
                f"**All squads combined** — {total_compared} items compared · "
                f"🔴 {total_drifted} drifted · {total_slip} days total slip · "
                f"worst single item: +{worst_drift} d"
            )
            st.divider()

        # ── Per-squad results ──────────────────────────────────────────────────
        for squad_name, drift in results:
            header = f"### {squad_name}" if len(results) > 1 else ""
            if header:
                st.markdown(header)

            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Items compared",    drift["n_compared"])
            c2.metric("🔴 Drifted later",   drift["n_drifted"])
            c3.metric(
                "Avg drift",
                f"+{drift['avg_drift_days']:.1f} d" if drift["n_drifted"] else "—",
            )
            c4.metric(
                "Worst drift",
                f"+{drift['max_drift_days']} d" if drift["n_drifted"] else "—",
            )
            c5.metric("🔵 Pulled in", drift["n_pulled_in"])

            if drift["n_drifted"] == 0:
                st.success(f"✅ No drift detected for {squad_name}.")
            else:
                st.caption(
                    f"**Total soft slip: {drift['total_drift_days']:,} days** across "
                    f"{drift['n_drifted']} items.  "
                    f"Measurement window: {elapsed_days} day{'s' if elapsed_days != 1 else ''}."
                )

                # Plain-English summary
                with st.expander(
                    f"💬 How to explain {squad_name} drift to your product owner",
                    expanded=(len(results) == 1),
                ):
                    rate  = drift.get("drift_rate_per_day")
                    n_d   = drift["n_drifted"]
                    total_d = drift["total_drift_days"]
                    max_d = drift["max_drift_days"]
                    avg_d = drift["avg_drift_days"]

                    if window_short:
                        st.warning(
                            f"⚠️ **{elapsed_days}-day window — drift rate not reliable.** "
                            f"Focus on absolute numbers; compare exports ≥ 14 days apart for a meaningful rate."
                        )
                    st.markdown(
                        f"Between {baseline_ts.strftime('%d %b %Y')} and today, "
                        f"**{n_d} item{'s have' if n_d != 1 else ' has'} had {'their' if n_d != 1 else 'its'} "
                        f"target end date quietly pushed out**, adding up to **{total_d} days of hidden slip**. "
                        f"The worst single item moved **{max_d} days further out**.\n\n"
                        + (f"On average, each drifted item moved **{avg_d:.0f} days** — "
                           f"{'roughly {:.0f} sprint{}'.format(avg_d/14, 's' if avg_d/14 >= 2 else '') if avg_d >= 7 else 'less than one sprint'}.\n\n")
                        + (f"Drift rate: **{rate:.2f} d/calendar day ({rate*7:.1f} d/week)**."
                           + (" ⚠️ Inflated by short window — treat as indicative." if window_short else
                              f" An item with 60 days remaining is expected to drift a further **{rate*60:.0f} days**.")
                           if rate else "")
                        + f"\n\n**Questions to ask the team:** Why did these items move? "
                          f"Are the original dates realistic? Is this pattern repeating?"
                    )

                st.divider()
                _drift_bar_chart(drift["records"], label=squad_name if len(results) > 1 else "",
                                 chart_key=squad_name.replace(" ", "_").lower())

            if len(results) > 1:
                st.divider()

        # Hierarchy table (combined)
        all_hier = pd.concat(
            [r["by_hierarchy"].assign(squad=sq) for sq, r in results],
            ignore_index=True,
        )
        if not all_hier.empty:
            st.subheader("Drift by hierarchy level")
            all_hier.columns = [c if c != "squad" else "Squad" for c in all_hier.columns]
            display_cols = ["Squad"] + [c for c in all_hier.columns if c != "Squad"] if len(results) > 1 else [c for c in all_hier.columns if c != "Squad"]
            st.dataframe(all_hier[display_cols], use_container_width=True, hide_index=True)

        # Full detail table (combined across all squads)
        all_records = pd.concat([r["records"] for _, r in results], ignore_index=True)
        with st.expander("📋 Full drift detail"):
            show_cols = ["key", "hierarchy", "squad", "baseline_end_str",
                         "current_end_str", "drift_days", "drift_class"]
            show_cols = [c for c in show_cols if c in all_records.columns]
            col_names = {
                "key": "Key", "hierarchy": "Level", "squad": "Squad",
                "baseline_end_str": "Baseline", "current_end_str": "Current",
                "drift_days": "Drift (d)", "drift_class": "Class",
            }
            st.dataframe(
                all_records.sort_values("drift_days", ascending=False)[show_cols]
                .rename(columns=col_names),
                use_container_width=True, hide_index=True,
            )

    # ── 2. Drift velocity ─────────────────────────────────────────────────────
    with tab_vel:
        st.markdown(
            "Upload **multiple** historic Roadmaps exports to see how drift "
            "has accumulated over time. Each file represents a snapshot of the "
            "plan at a specific point. The chart shows total drift vs current "
            "at each point in time — a rising line means dates are being pushed "
            "out faster than they are being delivered."
        )
        snap_files = st.file_uploader(
            "Historic Roadmaps CSVs (oldest first)",
            type=["csv"],
            key="velocity_snap_upload",
            accept_multiple_files=True,
            help="Upload 2+ historic exports. Dates will be parsed from filenames if possible.",
        )

        if not snap_files:
            st.info("Upload two or more historic Roadmaps CSVs above to see the velocity chart.")
            return  # nothing more to render

        tmp_dir = Path(st.session_state.get("tmp_dir", "/tmp/squad_flow"))
        tmp_dir.mkdir(parents=True, exist_ok=True)

        snapshots = []
        date_inputs = []
        for i, f in enumerate(snap_files):
            guessed = _parse_date_from_filename(f.name)
            default  = guessed.date() if guessed else pd.Timestamp.now().date()
            d = st.date_input(
                f"Export date — {f.name[:40]}",
                value=default,
                key=f"vel_snap_date_{i}",
            )
            p = tmp_dir / f"vel_snap_{i}.csv"
            # Only write if new upload (avoid re-reading on every re-run)
            snap_key = f"_vel_snap_path_{i}"
            if st.session_state.get(snap_key) is None:
                p.write_bytes(f.read())
                st.session_state[snap_key] = str(p)
            date_inputs.append(pd.Timestamp(d))

        if st.button("▶️ Calculate velocity", key="vel_calc_btn"):
            snap_dfs = []
            for i in range(len(snap_files)):
                path_str = st.session_state.get(f"_vel_snap_path_{i}")
                if path_str:
                    try:
                        snap_dfs.append((date_inputs[i], load_for_drift(path_str, config)))
                    except Exception as exc:
                        st.warning(f"Could not read snapshot {i+1}: {exc}")

            if len(snap_dfs) < 2:
                st.warning("Need at least 2 valid snapshots to calculate velocity.")
                return

            vel_df = drift_velocity(snap_dfs, current_rm_df)
            if vel_df.empty:
                st.warning("Not enough overlapping data to calculate velocity.")
                return

            st.session_state["_vel_df"] = vel_df

        vel_df = st.session_state.get("_vel_df")
        if vel_df is None or vel_df.empty:
            return

        # ── Velocity line chart
        fig_v = go.Figure()
        fig_v.add_trace(go.Scatter(
            x=vel_df["snapshot_date"],
            y=vel_df["total_drift_days"],
            mode="lines+markers",
            name="Total drift (days)",
            line=dict(color="#D55E00", width=2),
            marker=dict(size=8),
            hovertemplate=(
                "<b>%{x|%d %b %Y}</b><br>"
                "Total drift: %{y} days<br>"
                "<extra></extra>"
            ),
        ))
        fig_v.add_trace(go.Scatter(
            x=vel_df["snapshot_date"],
            y=vel_df["n_drifted"],
            mode="lines+markers",
            name="Items drifted",
            line=dict(color="#E69F00", width=2, dash="dot"),
            marker=dict(size=8),
            yaxis="y2",
            hovertemplate=(
                "<b>%{x|%d %b %Y}</b><br>"
                "Items drifted: %{y}<br>"
                "<extra></extra>"
            ),
        ))
        fig_v.update_layout(
            title="Cumulative drift vs current plan — measured from each historic snapshot",
            xaxis_title="Snapshot date",
            yaxis=dict(title="Total drift (days)", gridcolor="#eeeeee"),
            yaxis2=dict(
                title="Items drifted (count)",
                overlaying="y",
                side="right",
                showgrid=False,
            ),
            height=380,
            hovermode="x unified",
            plot_bgcolor="white",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        )
        st.plotly_chart(fig_v, use_container_width=True, key="drift_velocity_chart")
        st.caption(
            "🔴 Total drift days (left axis) — how far dates have moved in aggregate. "
            "🟠 Items drifted (right axis) — how many items have moved at all. "
            "A rising slope means the programme is accumulating soft slip."
        )

        # Rate table
        st.divider()
        rate_df = vel_df[["snapshot_date", "n_compared", "n_drifted",
                           "avg_drift_days", "drift_rate_per_week"]].copy()
        rate_df["snapshot_date"] = rate_df["snapshot_date"].dt.strftime("%d %b %Y")
        rate_df.columns = ["Snapshot", "Compared", "Drifted",
                           "Avg drift (d)", "Rate (d/week)"]
        st.dataframe(rate_df, use_container_width=True, hide_index=True)

    # ── 3. Adjusted forecast ──────────────────────────────────────────────────
    with tab_forecast:
        drift_rate = st.session_state.get("_drift_rate_per_day")

        st.markdown(
            "Based on the observed drift rate (from the Snapshot Comparison tab), "
            "this forecast projects how much additional drift each in-flight item "
            "is likely to accumulate before it reaches its current target date.\n\n"
            f"> **Current drift rate:** "
            f"{'`{:.3f}` days of drift per elapsed day ({:.2f} d/week)'.format(drift_rate, drift_rate * 7) if drift_rate else 'not yet calculated — complete the Snapshot Comparison tab first.'}"
        )

        if drift_rate is None:
            st.info(
                "Complete the **Snapshot Comparison** tab first to establish a drift rate, "
                "then return here."
            )
            return

        # Allow manual override
        drift_rate_input = st.number_input(
            "Drift rate (days of drift per elapsed calendar day)",
            min_value=0.0,
            max_value=2.0,
            value=float(drift_rate),
            step=0.001,
            format="%.3f",
            key="drift_rate_override",
            help=(
                "Auto-filled from the snapshot comparison. Adjust manually if needed. "
                "A value of 0.1 means 1 day of drift accumulates for every 10 elapsed days."
            ),
        )

        adjusted = drift_adjusted_targets(current_rm_df, drift_rate_input)
        if adjusted.empty:
            st.info("No in-flight items with future target end dates found.")
            return

        # Summary
        total_expected = int(adjusted["expected_additional_drift"].sum())
        max_expected   = int(adjusted["expected_additional_drift"].max())
        n_affected     = int((adjusted["expected_additional_drift"] > 0).sum())

        c1, c2, c3 = st.columns(3)
        c1.metric("In-flight items projected", len(adjusted))
        c2.metric("Items expecting further drift", n_affected)
        c3.metric("Total expected additional slip", f"{total_expected} days")

        st.caption(
            f"Worst case: **{max_expected} days** of additional drift on a single item. "
            "Items with more remaining time accumulate more expected drift at the same rate."
        )

        st.divider()

        # Forecast scatter: current target (x) vs expected drift (y), size = remaining days
        x = adjusted["adjusted_target"].tolist()
        y = adjusted["expected_additional_drift"].tolist()
        keys = adjusted["key"].tolist()
        hover_adj = [
            f"<b>{k}</b><br>"
            f"Current target: {row['current_target_str']}<br>"
            f"Adjusted target: {row['adjusted_target_str']}<br>"
            f"Expected additional drift: +{int(row['expected_additional_drift'])} d"
            for k, (_, row) in zip(keys, adjusted.iterrows())
        ]
        fig_adj = go.Figure(go.Scatter(
            x=x, y=y,
            mode="markers",
            marker=dict(
                size=adjusted["remaining_days"].clip(upper=60).tolist(),
                sizemode="area",
                sizeref=2.0 * 60 / (20 ** 2),
                color=adjusted["expected_additional_drift"].tolist(),
                colorscale=[[0, "#009E73"], [0.4, "#E69F00"], [1.0, "#D55E00"]],
                showscale=True,
                colorbar=dict(title="Extra drift (d)"),
            ),
            hovertext=hover_adj,
            hoverinfo="text",
        ))
        fig_adj.update_layout(
            xaxis_title="Adjusted target date",
            yaxis_title="Expected additional drift (days)",
            height=420,
            hovermode="closest",
            plot_bgcolor="white",
            xaxis=dict(gridcolor="#eeeeee"),
            yaxis=dict(gridcolor="#eeeeee"),
        )
        st.plotly_chart(fig_adj, use_container_width=True, key="drift_adjusted_chart")
        st.caption(
            "Each bubble is one in-flight item. Bubble size = days remaining. "
            "Colour = expected additional drift. Items in the top-right are both "
            "far from their target AND expected to drift the most."
        )

        st.divider()
        display_cols = {
            "key":                       "Key",
            "hierarchy":                 "Level",
            "current_target_str":        "Current target",
            "remaining_days":            "Days remaining",
            "expected_additional_drift": "Expected extra drift (d)",
            "adjusted_target_str":       "Adjusted target",
        }
        if "rm_squad" in adjusted.columns:
            display_cols = {"key": "Key", "rm_squad": "Squad", "hierarchy": "Level",
                            "current_target_str": "Current target",
                            "remaining_days": "Days remaining",
                            "expected_additional_drift": "Expected extra drift (d)",
                            "adjusted_target_str": "Adjusted target"}
        show_adj = adjusted[[c for c in display_cols if c in adjusted.columns]].rename(
            columns=display_cols
        )
        st.dataframe(show_adj, use_container_width=True, hide_index=True)


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
        _render_delivery_risk(df, chart_key="overall")

        st.divider()

        # Section 2: Epic / Capability progress
        _render_epic_progress(df)

        st.divider()

        # Section 3: Historical accuracy for resolved items
        st.subheader("Historical Accuracy — Completed Items")
        records = plan_accuracy_records(df)

        _MIN_ACCURACY_ITEMS = 5   # below this, stats are not meaningful

        if not records:
            st.info(
                "No completed items have a target end date yet — "
                "historical accuracy will appear here once items are resolved.\n\n"
                "**Tip:** if your Jira snapshot export was filtered to in-progress "
                "items only, re-export it to include **Done** items so past accuracy "
                "can be measured."
            )
        elif len(records) < _MIN_ACCURACY_ITEMS:
            st.info(
                f"Only **{len(records)} completed item(s)** have a target end date — "
                f"at least **{_MIN_ACCURACY_ITEMS}** are needed for meaningful accuracy stats.\n\n"
                "This section will populate as more items are resolved against roadmap targets. "
                "If you are at the start of a PI, come back at the end of the first sprint."
            )
            # Still show the raw detail table so the data isn't hidden entirely
            with st.expander(f"📋 Show {len(records)} item(s) anyway"):
                rows = [{
                    "Key":          r.key,
                    "Title":        r.title,
                    "Target end":   str(r.target_end)[:10] if r.target_end else "",
                    "Resolved":     str(r.resolved)[:10]   if r.resolved   else "",
                    "Slip (days)":  r.slip_days,
                } for r in sorted(records, key=lambda r: r.slip_days, reverse=True)]
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
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
            st.plotly_chart(fig, use_container_width=True, key="plan_accuracy_scatter_overall")
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
            _render_delivery_risk(sdf, title_prefix=f"{squad} — ",
                                  chart_key=squad.replace(" ", "_").lower())
            st.divider()

        # Epic/Capability progress (all squads combined — roadmaps is cross-squad)
        _render_epic_progress(df)

        st.divider()

        # Historical accuracy summary table
        st.subheader("Historical Accuracy by Squad")
        pa_rows = []
        pa_low_data = []   # squads with data but below threshold
        for squad in squads:
            sdf     = df[df["squad"] == squad]
            records = plan_accuracy_records(sdf)
            if not records:
                continue
            if len(records) < _MIN_ACCURACY_ITEMS:
                pa_low_data.append((squad, len(records)))
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

        if pa_low_data:
            names = ", ".join(f"{sq} ({n})" for sq, n in pa_low_data)
            st.info(
                f"Not enough completed items yet for: **{names}**. "
                f"Need at least {_MIN_ACCURACY_ITEMS} per squad — stats will appear as items are resolved."
            )

        if not pa_rows:
            if not pa_low_data:
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
            st.plotly_chart(fig, use_container_width=True, key="plan_accuracy_scatter_by_squad")

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

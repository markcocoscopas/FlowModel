"""ui/data_quality.py — Data Quality tab."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from core.data_quality import format_report, quality_score
from core.models import DataQualityReport
from config.schema import AppConfig


def render(report: DataQualityReport | None, config: AppConfig, df: pd.DataFrame | None = None) -> None:
    st.header("Data Quality")

    with st.expander("ℹ️ What this tells you", expanded=False):
        st.markdown(
            "This tab shows what proportion of your data contributed to each metric "
            "and explains what was excluded and why. Nothing is silently dropped — "
            "every exclusion is accounted for here. Use this tab to validate that "
            "the dashboard is using the data you expect."
        )

    if report is None:
        st.info("No data loaded.")
        return

    # ── Score ─────────────────────────────────────────────────────────────────
    score = quality_score(report)

    if score >= 80:
        colour = "green"
        verdict = "🟢 Excellent — all core metrics are reliable."
        advice  = "Your data is in great shape. Cycle time, throughput, WIP, and forecasts will all be meaningful."
    elif score >= 60:
        colour = "orange"
        verdict = "🟡 Good — most metrics are reliable."
        advice  = "Core flow metrics are solid. Check the breakdown below to see what's missing."
    elif score >= 40:
        colour = "orange"
        verdict = "🟠 Fair — some metrics may be incomplete."
        advice  = "Cycle time and throughput will work but may be based on a limited sample. Review the breakdown below."
    else:
        colour = "red"
        verdict = "🔴 Poor — limited data for meaningful analysis."
        advice  = "Many items are missing dates or being excluded. Check column mapping and filters."

    st.markdown(f"### Data readiness score: :{colour}[{score:.0f} / 100]")
    st.progress(int(score) / 100)
    st.markdown(f"**{verdict}**  \n{advice}")

    # ── Score breakdown ───────────────────────────────────────────────────────
    with st.expander("📋 How the score is calculated", expanded=score < 70):
        ct_pct = report.pct_contributing_cycle_time
        ct_pts = min(60.0, ct_pct * 0.6)
        state_excl = sum(
            v for k, v in report.exclusion_reasons.items()
            if k.startswith("Excluded workflow state")
        )
        filter_excl     = max(0, report.rows_excluded - state_excl)
        excl_pct        = round(100 * report.rows_excluded / max(report.total_rows_read, 1), 1)
        filter_excl_pct = round(100 * filter_excl / max(report.total_rows_read, 1), 1)
        excl_pts = 20.0 if filter_excl_pct < 5 else (10.0 if filter_excl_pct < 20 else 0.0)
        blocked_pts = 10.0 if report.has_blocked_flag > 0 else 0.0
        plan_pts = 10.0 if report.has_target_end > 0 else 0.0

        def _tick(pts, max_pts):
            return "✅" if pts >= max_pts else ("⚠️" if pts > 0 else "❌")

        st.markdown(
            f"| Component | Score | Max | What it means |\n"
            f"|-----------|------:|----:|---------------|\n"
            f"| **Completed items (cycle-time eligible)** | {ct_pts:.0f} | 60 | "
            f"{_tick(ct_pts, 60)} **{ct_pct}% of items have a Resolved date** — "
            f"only completed (Done) items have a resolved date, so this shows what proportion of "
            f"your data has already been delivered. Cycle time, throughput, and Monte Carlo forecasts "
            f"are calculated from these items. In-flight items contribute to WIP and ageing only. |\n"
            f"| **Low exclusion rate** | {excl_pts:.0f} | 20 | "
            f"{_tick(excl_pts, 20)} **{excl_pct}% of rows excluded in total** "
            f"({state_excl} by workflow state e.g. Funnel/To Do — expected and not penalised; "
            f"{filter_excl} by type/squad/date filter). "
            f"A high *filter* exclusion rate (>{filter_excl_pct}% shown here) usually means "
            f"the filters are too narrow. Pre-work state exclusions are intentional and do not affect this score. |\n"
            f"| **Blocked flag data present** | {blocked_pts:.0f} | 10 | "
            f"{_tick(blocked_pts, 10)} "
            f"{'**Blocked custom field is populated** — the Constraints tab can identify blocked items and estimate lost time.' if blocked_pts else '**Blocked field not found** — the `Custom field (Blocked)` column is empty or absent. The Constraints tab will only detect items in the *Blocked* workflow state, not those flagged via the custom field.'} |\n"
            f"| **Plan accuracy data (Roadmaps CSV)** | {plan_pts:.0f} | 10 | "
            f"{_tick(plan_pts, 10)} "
            f"{'**Advanced Roadmaps CSV loaded** — target end dates are available for delivery risk and plan accuracy analysis.' if plan_pts else '**No Roadmaps CSV loaded** — upload an Advanced Roadmaps export via the sidebar to enable the Plan Accuracy tab.'} |\n"
            f"| **Total** | **{score:.0f}** | **100** | |\n"
        )
        st.caption(
            "💡 The score is a data *readiness* indicator — it measures whether the right data "
            "is available for each metric. It says nothing about your team's performance. "
            "A low score almost always means column mapping needs adjusting or filters are too narrow, "
            "not that the team has poor flow data."
        )

    st.divider()

    # ── Bullets ───────────────────────────────────────────────────────────────
    bullets = format_report(report)
    for b in bullets:
        st.markdown(b)

    st.divider()

    # ── Squad / component mapping debug ──────────────────────────────────────
    if df is not None and not df.empty and "squad" in df.columns:
        with st.expander("🔍 Squad mapping — verify Component/s is correct"):
            st.caption(
                f"The **squad** field is read from the `{config.columns.get('squad', 'Component/s')}` "
                "column in your Jira CSV. The table below shows how many items of each type belong "
                "to each squad value. If you see label names or product-area names here that shouldn't "
                "be squads, those items likely have an unexpected value in their `Component/s` field "
                "in Jira — check the export or use a custom config YAML to remap the squad column."
            )
            _squad_type = (
                df.groupby(["squad", "type"])
                .size()
                .reset_index(name="count")
                .sort_values(["squad", "count"], ascending=[True, False])
            )
            st.dataframe(_squad_type, use_container_width=True, hide_index=True)

    # ── Raw numbers ──────────────────────────────────────────────────────────
    with st.expander("📊 Raw quality numbers"):
        metrics = {
            "Total rows read": report.total_rows_read,
            "Rows accepted": report.rows_accepted,
            "Rows excluded": report.rows_excluded,
            "Has Created date": report.has_created,
            "Has Resolved date": report.has_resolved,
            "Has both dates (cycle-time eligible)": report.has_both_dates,
            "Has Blocked flag": report.has_blocked_flag,
            "Has Roadmaps target end date": report.has_target_end,
            "% contributing to cycle time": f"{report.pct_contributing_cycle_time}%",
        }
        st.table(pd.DataFrame(metrics.items(), columns=["Metric", "Value"]))

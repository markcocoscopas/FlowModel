"""ui/forecasts.py — Forecasts tab (Monte Carlo)."""
from __future__ import annotations

from datetime import timedelta

import pandas as pd
import streamlit as st

from core.metrics import throughput_weekly, throughput_samples
from core.monte_carlo import how_many, when, when_risk_adjusted
from config.schema import AppConfig
from ui.charts import mc_histogram


def render(df: pd.DataFrame, config: AppConfig, n_sims: int = 10_000,
           mc_window_weeks: int = 12, capacity_pct: int = 80) -> None:
    st.header("Forecasts")

    with st.expander("ℹ️ What this tells you", expanded=False):
        st.markdown(
            "Probabilistic forecasts based on your team's actual historical throughput. "
            "No story points. No velocity. Just: how has the team delivered in the past, "
            "and what does that imply about the future?\n\n"
            "**'How Many'** — given a time horizon, how many items will be completed? "
            "An 85% confidence result means 85% of simulations completed at least that many items.\n\n"
            "**'When'** — given a backlog size, when will it be complete? "
            "An 85% result means 85% of simulations finished within that many weeks.\n\n"
            "**Squad capacity** scales the throughput samples to reflect that not all team "
            "time goes to feature delivery — ceremonies, unplanned work, and overhead reduce "
            "effective capacity. 80% means the team delivers at 80% of raw throughput.\n\n"
            "Results are distributions, not commitments. The wider the spread, "
            "the less predictable your throughput."
        )

    if df.empty:
        st.info("No data loaded.")
        return

    weekly = throughput_weekly(df)
    if weekly.empty:
        st.warning("No resolved items found — cannot run a forecast without throughput data.")
        return

    raw_samples = throughput_samples(weekly, window_weeks=mc_window_weeks)
    conf_levels  = config.monte_carlo.confidence_levels

    # Apply capacity adjustment — scale each weekly throughput sample
    factor  = capacity_pct / 100.0
    samples = [max(0, round(s * factor)) for s in raw_samples]

    raw_mean  = sum(raw_samples) / max(len(raw_samples), 1)
    adj_mean  = sum(samples)     / max(len(samples), 1)
    capacity_note = (
        f" · **{capacity_pct}% capacity** applied "
        f"(raw mean {raw_mean:.1f} → adjusted mean **{adj_mean:.1f}** items/week)"
        if capacity_pct != 100 else ""
    )

    st.info(
        f"Sampling from last **{mc_window_weeks} weeks** of throughput. "
        f"Adjusted mean: **{adj_mean:.1f} items/week**, "
        f"Range: **{min(samples)}–{max(samples)}**. "
        f"Running **{n_sims:,}** simulations."
        + capacity_note
    )

    if all(s == 0 for s in samples):
        st.warning(
            f"⚠️ At {capacity_pct}% capacity the adjusted throughput rounds to zero "
            f"for all weeks — increase the capacity % or use a longer throughput window."
        )
        return

    tab1, tab2, tab3 = st.tabs(["How Many?", "When?", "Risk-Adjusted When?"])

    # ── How Many ──────────────────────────────────────────────────────────────
    with tab1:
        col1, col2 = st.columns([1, 2])
        with col1:
            n_days = st.number_input(
                "Forecast horizon (days)", min_value=7, max_value=365,
                value=90, step=7, key="mc_how_many_days",
            )
            if st.button("Run 'How Many'", key="run_how_many", use_container_width=True):
                with st.spinner("Running simulation…"):
                    result = how_many(samples, n_days=n_days, n_sims=n_sims,
                                      confidence_levels=conf_levels)
                st.session_state["mc_how_many_result"] = result

        with col2:
            result = st.session_state.get("mc_how_many_result")
            if result:
                fig = mc_histogram(
                    result.raw_samples,
                    result.percentile_values,
                    mode="how_many",
                    title=f"How Many in {n_days} days?",
                )
                st.plotly_chart(fig, use_container_width=True)

        result = st.session_state.get("mc_how_many_result")
        if result:
            _show_percentile_table(result.percentile_values, mode="how_many")

    # ── When ──────────────────────────────────────────────────────────────────
    with tab2:
        col1, col2 = st.columns([1, 2])
        with col1:
            backlog = st.number_input(
                "Backlog size (items)", min_value=1, max_value=5000,
                value=20, step=1, key="mc_when_backlog",
            )
            if st.button("Run 'When'", key="run_when", use_container_width=True):
                with st.spinner("Running simulation…"):
                    result = when(samples, backlog=backlog, n_sims=n_sims,
                                  confidence_levels=conf_levels)
                st.session_state["mc_when_result"] = result

        with col2:
            result = st.session_state.get("mc_when_result")
            if result:
                fig = mc_histogram(
                    result.raw_samples,
                    result.percentile_values,
                    mode="when",
                    title=f"When will {backlog} items be done?",
                )
                st.plotly_chart(fig, use_container_width=True)

        result = st.session_state.get("mc_when_result")
        if result:
            _show_percentile_table(result.percentile_values, mode="when")
            _show_date_estimates(result.percentile_values)

    # ── Risk-adjusted When ────────────────────────────────────────────────────
    with tab3:
        st.caption(
            "Model scope uncertainty by specifying a range for the backlog size. "
            "The engine draws a random backlog size for each simulation, "
            "capturing the reality that scope rarely stays fixed."
        )
        col1, col2 = st.columns([1, 2])
        with col1:
            low  = st.number_input("Backlog min", min_value=1, value=15, key="mc_ra_low")
            high = st.number_input("Backlog max", min_value=1, value=30, key="mc_ra_high")
            if st.button("Run risk-adjusted forecast", key="run_ra", use_container_width=True):
                if low > high:
                    st.error("Backlog min must be ≤ max.")
                else:
                    with st.spinner("Running simulation…"):
                        result = when_risk_adjusted(
                            samples, backlog_low=low, backlog_high=high,
                            n_sims=n_sims, confidence_levels=conf_levels,
                        )
                    st.session_state["mc_ra_result"] = result

        with col2:
            result = st.session_state.get("mc_ra_result")
            if result:
                fig = mc_histogram(
                    result.raw_samples,
                    result.percentile_values,
                    mode="when",
                    title=f"Risk-adjusted When? (backlog {low}–{high})",
                )
                st.plotly_chart(fig, use_container_width=True)

        result = st.session_state.get("mc_ra_result")
        if result:
            _show_percentile_table(result.percentile_values, mode="when")
            _show_date_estimates(result.percentile_values)


def _show_percentile_table(pv: dict[int, float], mode: str) -> None:
    unit = "weeks" if mode == "when" else "items"
    label = "Weeks to completion" if mode == "when" else "Items completed (at least)"
    rows = [{"Confidence": f"{c}%", label: int(v)} for c, v in sorted(pv.items())]
    st.dataframe(pd.DataFrame(rows), use_container_width=False, hide_index=True)


def _fmt_date_portable(dt: "pd.Timestamp") -> str:
    """Format a date as '8 May 2026' without %-d (Linux-only strftime flag)."""
    return f"{dt.day} {dt.strftime('%B %Y')}"


def _show_date_estimates(pv: dict[int, float]) -> None:
    today = pd.Timestamp.now().normalize()
    st.caption("Estimated completion dates from today:")
    dates = {
        f"{c}% confidence": _fmt_date_portable(today + timedelta(weeks=int(v)))
        for c, v in sorted(pv.items())
    }
    st.json(dates)

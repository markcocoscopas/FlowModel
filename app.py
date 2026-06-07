"""
app.py
~~~~~~
Streamlit entry point for Squad Flow Metrics.

Run with:
    streamlit run app.py

Architecture: this file only wires things together.  All logic lives in
core/ (pure functions) and ui/ (thin Streamlit views).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import streamlit as st

# ── Path setup ────────────────────────────────────────────────────────────────
# Add the project root to sys.path so that `core`, `ui`, `config` are importable
# regardless of the working directory used to launch streamlit.
_ROOT = Path(__file__).parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("/tmp/squad_flow.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# ── Imports (after path setup) ────────────────────────────────────────────────
import pandas as pd

from config.schema import load_config
from core.ingest import load_snapshot, load_roadmaps, load_for_drift, merge_datasets, apply_filters
from ui.sidebar import render_sidebar

import ui.overview      as tab_overview
import ui.cycle_time    as tab_cycle_time
import ui.throughput    as tab_throughput
import ui.ageing_wip    as tab_ageing
import ui.forecasts     as tab_forecasts
import ui.constraints   as tab_constraints
import ui.plan_accuracy as tab_plan
import ui.compare       as tab_compare
import ui.data_quality  as tab_quality
import ui.export        as tab_export


# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Squad Flow Metrics",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ── Session state helpers ─────────────────────────────────────────────────────
def _load_data(
    snapshot_path: "str | list[str]",
    roadmaps_path: str | None,
    config,
) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    """Load and merge CSVs, caching by file path(s).

    snapshot_path may be a single path string or a list of paths.
    Multiple snapshot CSVs are concatenated and de-duplicated by Issue key.
    """
    paths = [snapshot_path] if isinstance(snapshot_path, str) else snapshot_path
    frames = [load_snapshot(p, config) for p in paths]

    if len(frames) == 1:
        snap_df = frames[0]
    else:
        # Concatenate all frames and de-duplicate by Issue key.
        # When the same squad is exported at different times (e.g. a May 25 and
        # a May 28 snapshot), both files will carry the same Component/s squad
        # name — that's fine and correct.  We keep the FIRST file's version of
        # any duplicate key (upload order = newest-first is the user's
        # responsibility, but either way only one copy is kept).
        squad_sets = [set(f["squad"].dropna().unique()) - {""} for f in frames]
        all_squad_names = set().union(*squad_sets)

        combined = pd.concat(frames, ignore_index=True)
        before = len(combined)
        combined = combined.drop_duplicates(subset=["key"], keep="first")
        dupes = before - len(combined)

        if dupes:
            log.info("  Dropped %d duplicate rows after merging %d snapshot files.", dupes, len(frames))
            st.sidebar.info(
                f"ℹ️ {dupes} duplicate issue keys removed after merging "
                f"{len(frames)} files — most recent version of each item kept."
            )

        n_squads = len(all_squad_names)
        log.info(
            "  Combined %d snapshot files → %d rows, %d distinct squad(s): %s",
            len(frames), len(combined), n_squads, sorted(all_squad_names),
        )
        snap_df = combined

    rm_df = None
    if roadmaps_path:
        try:
            rm_paths = [roadmaps_path] if isinstance(roadmaps_path, str) else roadmaps_path
            rm_frames = [load_roadmaps(p, config) for p in rm_paths]
            if len(rm_frames) == 1:
                rm_df = rm_frames[0]
            else:
                combined = pd.concat(rm_frames, ignore_index=True)
                rm_df = combined.drop_duplicates(subset=["key"], keep="first")
                log.info("Combined %d roadmap files → %d rows.", len(rm_frames), len(rm_df))
        except Exception as exc:
            log.warning("Could not load roadmaps CSV: %s", exc)
            st.sidebar.warning(f"Roadmaps CSV skipped: {exc}")

    return snap_df, rm_df


def _get_or_load(state: "SidebarState") -> tuple[pd.DataFrame | None, object | None]:
    """
    Load data if the file paths or config have changed, otherwise reuse cached.
    Returns (merged_df, quality_report).
    """
    # Normalise snapshot_path to a tuple so it's hashable for the cache key
    snap_key = tuple(state.snapshot_path) if isinstance(state.snapshot_path, list) else (state.snapshot_path,)
    rm_key   = tuple(state.roadmaps_path) if isinstance(state.roadmaps_path, list) else (state.roadmaps_path,)
    cache_key = (snap_key, rm_key)

    if (
        state.refreshed
        or st.session_state.get("_data_cache_key") != cache_key
        or st.session_state.get("_raw_df") is None
    ):
        if not state.snapshot_path:
            return None, None
        try:
            snap_df, rm_df = _load_data(
                state.snapshot_path, state.roadmaps_path, state.config
            )
            merged = merge_datasets(snap_df, rm_df)
            st.session_state["_raw_df"]        = merged
            # Store normalised drift-ready df for the Date Drift tab.
            # For roadmaps uploads rm_df is already in the right format.
            # For snapshot-only workflows the snapshot itself is used (it may
            # contain a "Custom field (Target end)" column that load_for_drift
            # will pick up).  We try roadmaps first; fall back to snapshot.
            if rm_df is not None:
                st.session_state["_current_rm_df"] = rm_df
            else:
                # Attempt to build a drift-ready df from the snapshot CSVs
                try:
                    drift_paths = [state.snapshot_path] if isinstance(state.snapshot_path, str) else state.snapshot_path
                    drift_frames = [load_for_drift(p, state.config) for p in drift_paths]
                    drift_combined = pd.concat(drift_frames, ignore_index=True).drop_duplicates(subset=["key"])
                    st.session_state["_current_rm_df"] = drift_combined
                except Exception:
                    st.session_state["_current_rm_df"] = None
            st.session_state["_data_cache_key"] = cache_key
            log.info("Data loaded and cached. %d rows.", len(merged))
        except Exception as exc:
            log.exception("Failed to load data: %s", exc)
            st.error(f"Failed to load data: {exc}")
            return None, None
    else:
        merged = st.session_state["_raw_df"]

    # Apply filters
    filtered, report = apply_filters(
        merged,
        config=state.config,
        squads=state.selected_squads or None,
        item_types=state.selected_types or None,
        date_from=state.date_from,
        date_to=state.date_to,
    )

    return filtered, report


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    # Render sidebar first (needs raw df for filter options)
    raw_df = st.session_state.get("_raw_df")
    sidebar_state = render_sidebar(df=raw_df)

    # Load / refresh data
    filtered_df, quality_report = _get_or_load(sidebar_state)

    # Persist file paths in session so they survive re-runs
    if sidebar_state.snapshot_path:
        st.session_state["snapshot_path"] = sidebar_state.snapshot_path
    if sidebar_state.roadmaps_path:
        st.session_state["roadmaps_path"] = sidebar_state.roadmaps_path

    config = sidebar_state.config

    # Apply sidebar WIP limit overrides on top of the config defaults.
    # wip_limit_overrides contains ALL states shown in the sidebar, including
    # zeros — a zero means the user explicitly removed that limit.
    # We only skip this block if the sidebar never rendered any WIP controls
    # (i.e. no data loaded yet), indicated by an empty dict.
    if sidebar_state.wip_limit_overrides is not None and config is not None:
        import copy
        config = copy.copy(config)
        merged_limits = dict(config.wip_limits)
        merged_limits.update(sidebar_state.wip_limit_overrides)
        # Zero = user explicitly cleared this limit — remove it
        config.wip_limits = {k: v for k, v in merged_limits.items() if v > 0}

    # No data yet — show welcome
    if filtered_df is None or filtered_df.empty:
        if sidebar_state.snapshot_path:
            st.warning("No data matches the current filters.")
        else:
            _show_welcome()
        return

    # ── Squad view selector ───────────────────────────────────────────────────
    # Use the same valid-squad list computed by the sidebar (threshold-filtered,
    # "None"-excluded) so the radio and the dropdown always show the same squads.
    _valid_squads = st.session_state.get("_valid_squads") or []
    squads_in_data = sorted(
        filtered_df["squad"]
        .dropna()
        .loc[lambda s: s.str.strip().str.lower() != "none"]
        .unique()
        .tolist()
    )
    # Keep only squads that are both in the data AND in the valid list.
    # Fall back to all squads in data if the valid list is empty (e.g. first run).
    squads_loaded = (
        [s for s in squads_in_data if s in _valid_squads]
        if _valid_squads else squads_in_data
    )
    if len(squads_loaded) > 1:
        view_options = ["📊 All Squads"] + squads_loaded
        selected_view = st.radio(
            "Squad view",
            options=view_options,
            horizontal=True,
            key="squad_view",
            label_visibility="collapsed",
        )
        if selected_view != "📊 All Squads":
            display_df = filtered_df[filtered_df["squad"] == selected_view].copy()
        else:
            display_df = filtered_df
    else:
        display_df = filtered_df

    # ── Tabs ──────────────────────────────────────────────────────────────────
    tabs = st.tabs([
        "📊 Overview",
        "⏱ Cycle Time",
        "🚀 Throughput",
        "⏳ Ageing WIP",
        "🔮 Forecasts",
        "🔍 Constraints",
        "🎯 Plan Accuracy",
        "👥 Compare Squads",
        "🔬 Data Quality",
        "📥 Export",
    ])

    with tabs[0]:
        tab_overview.render(display_df, config)
    with tabs[1]:
        tab_cycle_time.render(display_df, config)
    with tabs[2]:
        tab_throughput.render(display_df, config)
    with tabs[3]:
        tab_ageing.render(display_df, config)
    with tabs[4]:
        tab_forecasts.render(
            display_df, config,
            n_sims=sidebar_state.n_sims,
            mc_window_weeks=sidebar_state.mc_window_weeks,
            capacity_pct=sidebar_state.capacity_pct,
        )
    with tabs[5]:
        tab_constraints.render(display_df, config)
    with tabs[6]:
        tab_plan.render(display_df, config)
    with tabs[7]:
        tab_compare.render(filtered_df, config)   # always full dataset — needs all squads
    with tabs[8]:
        tab_quality.render(quality_report, config, df=display_df)
    with tabs[9]:
        tab_export.render(display_df, config, quality_report)


def _show_welcome() -> None:
    st.title("📊 Squad Flow Metrics")
    st.markdown(
        """
        Welcome! This tool analyses flow metrics for one or more Agile squads.

        ### Getting started

        1. **Upload your Jira CSV** — use the 'Jira snapshot CSV' uploader in the sidebar.
           This is the standard *Created vs Resolved* export from Jira.

        2. **Optionally upload an Advanced Roadmaps CSV** to unlock plan accuracy
           and sprint slippage metrics.

        3. **Or click 'Load sample data'** in the sidebar to explore with synthetic data.

        ### What you'll get

        | Tab | What it shows |
        |-----|--------------|
        | Overview | Headline KPIs + auto-generated commentary |
        | Cycle Time | Scatterplot with configurable percentile lines |
        | Throughput | Weekly run chart + histogram |
        | Ageing WIP | In-flight items vs historical cycle-time percentiles |
        | Forecasts | Monte Carlo How Many / When |
        | Constraints | Bottleneck signals from age-by-state + blocked items |
        | Plan Accuracy | Target vs actual dates, sprint slippage |
        | Compare Squads | Small-multiples side-by-side view |
        | Data Quality | Exclusion log and data readiness score |
        | Export | Download CSV, full HTML report, or per-chart PNG |

        ---
        *Built on Actionable Agile / Vacanti flow principles.*
        *Forecasts use historical throughput, not story points.*
        """
    )


if __name__ == "__main__":
    main()

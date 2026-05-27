"""
ui/sidebar.py
~~~~~~~~~~~~~
Streamlit sidebar: file upload, squad filter, type filter, date range,
config upload, and refresh.

Returns a SidebarState dataclass consumed by app.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
import yaml

from config.schema import AppConfig, load_config, load_config_from_dict
from core.updater import check_for_update, current_version, download_and_apply


@dataclass
class SidebarState:
    snapshot_path:  str | list | None = None   # str (single) or list[str] (multi)
    roadmaps_path:  str | list | None = None   # str (single) or list[str] (multi)
    config:         AppConfig | None = None
    selected_squads: list[str]       = field(default_factory=list)
    selected_types:  list[str]       = field(default_factory=list)
    date_from: pd.Timestamp | None   = None
    date_to:   pd.Timestamp | None   = None
    n_sims:    int                   = 10_000
    mc_window_weeks: int             = 12
    refreshed: bool                  = False


def render_sidebar(df: pd.DataFrame | None = None) -> SidebarState:
    """
    Render the sidebar and return the current SidebarState.
    *df* is the currently loaded DataFrame (used to populate squad / type filters).
    """
    state = SidebarState()

    st.sidebar.title("Squad Flow Metrics")
    st.sidebar.caption(f"Version {current_version()}")

    # ── Update check (once per session) ──────────────────────────────────────
    if "update_check_done" not in st.session_state:
        available, latest_tag, release_url = check_for_update()
        st.session_state["update_check_done"] = True
        st.session_state["update_available"]  = available
        st.session_state["update_tag"]        = latest_tag
        st.session_state["update_url"]        = release_url
        st.session_state["update_applied"]    = False

    if st.session_state.get("update_applied"):
        st.sidebar.success(
            "✅ **Update applied!**  \n"
            "Close and reopen the app to start using the new version."
        )
    elif st.session_state.get("update_available"):
        latest_tag  = st.session_state["update_tag"]
        st.sidebar.warning(f"🆕 **Version {latest_tag} available**")
        if st.sidebar.button("⬆️ Upgrade now", use_container_width=True):
            progress_placeholder = st.sidebar.empty()
            def _progress(msg):
                progress_placeholder.caption(f"⏳ {msg}")
            with st.spinner(f"Upgrading to {latest_tag}…"):
                ok, msg = download_and_apply(progress_fn=_progress)
            progress_placeholder.empty()
            if ok:
                st.session_state["update_applied"]   = True
                st.session_state["update_available"] = False
                st.rerun()
            else:
                st.sidebar.error(f"Upgrade failed: {msg}")

    st.sidebar.markdown("---")

    # ── Data source ───────────────────────────────────────────────────────────
    st.sidebar.subheader("📂 Data Source")

    snap_files = st.sidebar.file_uploader(
        "Jira snapshot CSV(s)",
        type=["csv"],
        key="snapshot_upload",
        accept_multiple_files=True,
        help=(
            "Upload one or more 'Created vs Resolved' Jira exports. "
            "Upload a separate file per squad if needed — they will be merged automatically."
        ),
    )
    rm_files = st.sidebar.file_uploader(
        "Advanced Roadmaps CSV(s) (optional)",
        type=["csv"],
        key="roadmaps_upload",
        accept_multiple_files=True,
        help="Upload one or more Advanced Roadmaps exports. Upload one per squad if needed — they will be merged automatically.",
    )

    # Save uploaded files to a temp location so core functions can read them
    tmp_dir = Path(st.session_state.get("tmp_dir", "/tmp/squad_flow"))
    tmp_dir.mkdir(parents=True, exist_ok=True)

    # Normalise to list regardless of whether 0, 1 or many files were uploaded
    if isinstance(snap_files, list):
        snap_files_list = snap_files
    elif snap_files is not None:
        snap_files_list = [snap_files]
    else:
        snap_files_list = []

    if snap_files_list:
        snap_paths = []
        for i, f in enumerate(snap_files_list):
            p = tmp_dir / f"snapshot_{i}.csv"
            p.write_bytes(f.read())
            snap_paths.append(str(p))
        state.snapshot_path = snap_paths  # list of paths
        # Reset date pickers when the set of uploaded files changes so stale
        # session-state values from a previous upload don't silently hide rows.
        new_names = tuple(sorted(f.name for f in snap_files_list))
        if st.session_state.get("_last_snap_names") != new_names:
            st.session_state.pop("date_from",       None)
            st.session_state.pop("date_to",         None)
            # Bust the data cache — temp paths are always snapshot_0.csv etc.
            # so the cache key never changes when different files are uploaded.
            st.session_state.pop("_data_cache_key", None)
            st.session_state.pop("_raw_df",         None)
            # Reset filters so they default to ALL squads/types in the new data
            # rather than retaining the previous upload's selection.
            st.session_state.pop("squad_filter",    None)
            st.session_state.pop("type_filter",     None)
            st.session_state["_last_snap_names"] = new_names
        if len(snap_files_list) > 1:
            st.sidebar.caption(f"✅ {len(snap_files_list)} files loaded — squads will be merged.")
    elif "snapshot_path" in st.session_state:
        state.snapshot_path = st.session_state["snapshot_path"]

    if isinstance(rm_files, list):
        rm_files_list = rm_files
    elif rm_files is not None:
        rm_files_list = [rm_files]
    else:
        rm_files_list = []

    if rm_files_list:
        rm_paths = []
        for i, f in enumerate(rm_files_list):
            p = tmp_dir / f"roadmaps_{i}.csv"
            p.write_bytes(f.read())
            rm_paths.append(str(p))
        state.roadmaps_path = rm_paths
        if len(rm_files_list) > 1:
            st.sidebar.caption(f"✅ {len(rm_files_list)} roadmap files loaded — will be merged.")
    elif "roadmaps_path" in st.session_state:
        state.roadmaps_path = st.session_state["roadmaps_path"]

    # ── Config ────────────────────────────────────────────────────────────────
    st.sidebar.subheader("⚙️ Configuration")
    cfg_file = st.sidebar.file_uploader(
        "Custom config YAML (optional)",
        type=["yaml", "yml"],
        key="config_upload",
        help="Upload a custom column-mapping config. Defaults to built-in Jira mapping.",
    )

    try:
        if cfg_file:
            raw_cfg = yaml.safe_load(cfg_file.read())
            state.config = load_config_from_dict(raw_cfg)
            st.sidebar.success("Custom config loaded.")
        else:
            state.config = load_config()
    except Exception as exc:
        st.sidebar.error(f"Config error: {exc}")
        state.config = load_config()

    # ── Squad filter ──────────────────────────────────────────────────────────
    if df is not None and not df.empty:
        # Build squad list from team-level work items only.
        # Epics and Capabilities are often tagged with product-area Component/s
        # values (e.g. "TMA", "Towing & Hitching") rather than team names, which
        # would otherwise pollute the squad dropdown with feature names.
        _TEAM_TYPES = {"Story", "Bug", "Task", "Spike", "Sub-task"}
        _squad_src  = df[df["type"].isin(_TEAM_TYPES)]
        if _squad_src.empty:           # fall back to full df if no team-level items
            _squad_src = df
        available_squads = sorted(_squad_src["squad"].dropna().unique().tolist())
        available_types  = sorted(df["type"].dropna().unique().tolist())

        st.sidebar.subheader("🏃 Filters")
        selected_squads = st.sidebar.multiselect(
            "Squad(s)",
            options=available_squads,
            default=available_squads,
            key="squad_filter",
        )
        selected_types = st.sidebar.multiselect(
            "Work-item type(s)",
            options=available_types,
            default=available_types,   # show everything in the data; user narrows down
            key="type_filter",
        )

        min_date  = df["created"].min()
        today     = pd.Timestamp.now().normalize()
        if pd.notna(min_date):
            col1, col2 = st.sidebar.columns(2)
            with col1:
                date_from = st.date_input(
                    "From", value=min_date.date(), min_value=min_date.date(),
                    max_value=today.date(), key="date_from"
                )
            with col2:
                date_to = st.date_input(
                    "To", value=today.date(), min_value=min_date.date(),
                    max_value=today.date(), key="date_to"
                )
            state.date_from = pd.Timestamp(date_from)
            state.date_to   = pd.Timestamp(date_to)

        state.selected_squads = selected_squads
        state.selected_types  = selected_types

    # ── Monte Carlo settings ──────────────────────────────────────────────────
    st.sidebar.subheader("🎲 Forecast Settings")
    state.n_sims = st.sidebar.select_slider(
        "Simulations",
        options=[1_000, 5_000, 10_000, 20_000, 50_000],
        value=10_000,
        key="n_sims",
    )
    state.mc_window_weeks = st.sidebar.number_input(
        "Throughput window (weeks)",
        min_value=4, max_value=52, value=12, step=1,
        key="mc_window",
        help="How many weeks of historical throughput to use for MC sampling.",
    )

    # ── Refresh ───────────────────────────────────────────────────────────────
    st.sidebar.markdown("---")
    state.refreshed = st.sidebar.button("🔄 Refresh", use_container_width=True)

    # ── Sample data shortcut ──────────────────────────────────────────────────
    st.sidebar.markdown("---")
    st.sidebar.caption("No data yet? Try the bundled sample:")
    if st.sidebar.button("Load sample data", use_container_width=True):
        sample_dir = Path(__file__).parent.parent / "data" / "sample"
        state.snapshot_path = str(sample_dir / "sample_squads.csv")
        state.roadmaps_path = str(sample_dir / "sample_roadmaps.csv")
        st.session_state["snapshot_path"] = state.snapshot_path
        st.session_state["roadmaps_path"]  = state.roadmaps_path
        st.rerun()

    return state

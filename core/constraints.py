"""
core/constraints.py
~~~~~~~~~~~~~~~~~~~
Constraint and bottleneck analysis using only data available in the Jira
snapshot CSV (no status-change history required).

What IS available without history
----------------------------------
  - Current status of each item                 → WIP breach detection
  - Age of in-flight items (days since Created) → age-by-status distribution
  - Blocked flag / Flagged flag                 → blocked-time analysis
  - Resolved items with cycle time             → high-cycle-time flag

What is NOT available (deferred to Phase 2)
--------------------------------------------
  - Time spent in each individual state per item (requires changelog API)
  - Queue vs activity decomposition
  - State residency distributions

Public API
----------
  constraint_report(df, config, ref_date)  → ConstraintReport
"""

from __future__ import annotations

import logging
from datetime import datetime

import numpy as np
import pandas as pd

from config.schema import AppConfig
from core.metrics import cycle_time_series
from core.models import ConstraintReport

log = logging.getLogger(__name__)

_SECS_PER_DAY = 86_400.0


def constraint_report(
    df: pd.DataFrame,
    config: AppConfig,
    ref_date: "pd.Timestamp | None" = None,
) -> ConstraintReport:
    """
    Build a ConstraintReport from the filtered DataFrame.

    Parameters
    ----------
    df       : filtered DataFrame (output of ingest.apply_filters)
    config   : AppConfig (for WIP limits and workflow state order)
    ref_date : point-in-time for in-flight WIP calculations (default: now)
    """
    if ref_date is None:
        ref_date = pd.Timestamp.now(tz=None)

    # ── 1. Blocked-item analysis ──────────────────────────────────────────────
    # Count items that are blocked by EITHER the custom flag OR workflow state.
    total = len(df)
    n_blocked = 0
    total_blocked_days = 0.0
    avg_blocked_days = 0.0

    flag_blocked  = df["is_blocked"] == True if "is_blocked" in df.columns else pd.Series(False, index=df.index)  # noqa: E712
    state_blocked = df["status"].str.lower() == "blocked" if "status" in df.columns else pd.Series(False, index=df.index)
    blocked_mask  = flag_blocked | state_blocked
    blocked_items = df[blocked_mask]
    n_blocked = int(len(blocked_items))

    if n_blocked > 0 and "created" in blocked_items.columns:
        # Proxy for blocked duration: current age of blocked items
        # (true blocked duration requires changelog — flagged as lower bound)
        ages = (ref_date - blocked_items["created"]).dt.total_seconds() / _SECS_PER_DAY
        ages = ages[ages >= 0].dropna()
        total_blocked_days = float(ages.sum())
        avg_blocked_days   = float(ages.mean()) if not ages.empty else 0.0

    pct_blocked = round(100 * n_blocked / max(total, 1), 1)

    # ── 2. Age-by-status distribution ────────────────────────────────────────
    in_flight = df[df["resolved"].isna() & df["created"].notna()].copy()
    in_flight["_age"] = (
        (ref_date - in_flight["created"]).dt.total_seconds() / _SECS_PER_DAY
    )

    age_by_status: dict[str, list[float]] = {}
    for state in config.state_order:
        subset = in_flight[in_flight["status"] == state]["_age"].dropna()
        if not subset.empty:
            age_by_status[state] = [round(float(v), 1) for v in subset.tolist()]

    # Untracked statuses — only include if they have enough items to be
    # statistically significant (≥ 3) AND the status is not obviously a
    # pre-work / staging state.  States like "Draft", "Backlog", "Icebox"
    # shouldn't pollute the constraints chart; significant unknown active
    # states (high item count) are worth surfacing.
    _PRE_WORK_STATES = {"draft", "backlog", "icebox", "idea", "new", "open", "triage"}
    untracked_mask = ~in_flight["status"].isin(config.state_order)
    for status, grp in in_flight[untracked_mask].groupby("status"):
        if str(status).strip().lower() in _PRE_WORK_STATES:
            continue
        vals = grp["_age"].dropna().tolist()
        if len(vals) >= 3:   # only show if there's enough data to be meaningful
            age_by_status[str(status)] = [round(float(v), 1) for v in vals]

    # ── 3. WIP breach detection ───────────────────────────────────────────────
    wip_breaches: list[dict] = []
    # Current WIP per state
    current_wip: dict[str, int] = {}
    if not in_flight.empty:
        for state in config.state_order:
            current_wip[state] = int((in_flight["status"] == state).sum())

    for state, limit in config.wip_limits.items():
        cw = current_wip.get(state, 0)
        if cw > limit:
            wip_breaches.append({
                "state":       state,
                "wip_limit":   limit,
                "current_wip": cw,
                "excess":      cw - limit,
            })

    # ── 4. Candidate constraint state ─────────────────────────────────────────
    # Highest median age among in-flight active/queue states
    candidate_state = ""
    candidate_median = 0.0

    active_queue_states = [
        s.name for s in config.workflow_states
        if s.category in ("active", "queue")
    ]
    for state in active_queue_states:
        ages = age_by_status.get(state, [])
        if ages:
            med = float(np.median(ages))
            if med > candidate_median:
                candidate_median = med
                candidate_state  = state

    return ConstraintReport(
        n_blocked=n_blocked,
        pct_blocked=pct_blocked,
        total_blocked_days=round(total_blocked_days, 1),
        avg_blocked_days=round(avg_blocked_days, 1),
        age_by_status=age_by_status,
        wip_breaches=wip_breaches,
        candidate_constraint_state=candidate_state,
        candidate_constraint_median_days=round(candidate_median, 1),
    )

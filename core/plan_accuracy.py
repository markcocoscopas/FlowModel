"""
core/plan_accuracy.py
~~~~~~~~~~~~~~~~~~~~~
Bonus v1 features unlocked by joining the Advanced Roadmaps CSV.

Plan accuracy
  How close were the target end dates to actual resolution dates?
  Positive slip = delivered late.  Negative slip = delivered early.

Sprint slippage
  How many items were delivered in a later sprint than planned?
  Requires the compound sprint field to have at least one [COMPLETED] sprint.

Public API
----------
  plan_accuracy_records(df)          → list[PlanAccuracyRecord]
  plan_accuracy_summary(records)     → dict  (summary stats)
  sprint_slippage_summary(df)        → dict  (slippage stats)
"""

from __future__ import annotations

import logging
import re

import numpy as np
import pandas as pd

from core.models import PlanAccuracyRecord

log = logging.getLogger(__name__)

_SECS_PER_DAY    = 86_400.0
_RISK_AT_RISK_DAYS = 14   # items due within this many days are flagged "at risk"

# Drift thresholds (days)
_DRIFT_MINOR    = 7
_DRIFT_MODERATE = 30


# ── Date drift (baseline vs current roadmaps comparison) ──────────────────────

def _drift_merge(
    baseline_df: pd.DataFrame,
    current_df: pd.DataFrame,
) -> pd.DataFrame | None:
    """
    Inner join baseline and current roadmaps DataFrames on key,
    compute drift_days and drift_class.  Returns None if no overlap.
    """
    squad_col_base = "rm_squad" if "rm_squad" in baseline_df.columns else None
    squad_col_curr = "rm_squad" if "rm_squad" in current_df.columns else None

    base_cols = ["key", "rm_target_end", "hierarchy"]
    if squad_col_base:
        base_cols.append("rm_squad")

    base = (
        baseline_df[base_cols]
        .rename(columns={"rm_target_end": "baseline_end"})
        .dropna(subset=["baseline_end"])
    )

    curr_cols = ["key", "rm_target_end"]
    if squad_col_curr:
        curr_cols.append("rm_squad")

    curr = (
        current_df[curr_cols]
        .rename(columns={"rm_target_end": "current_end",
                         "rm_squad":       "squad_curr"})
        .dropna(subset=["current_end"])
    )

    merged = base.merge(curr, on="key", how="inner")
    if merged.empty:
        return None

    merged["drift_days"] = (
        (merged["current_end"] - merged["baseline_end"])
        .dt.total_seconds()
        .div(_SECS_PER_DAY)
        .round()
        .astype(int)
    )

    def _cls(d: int) -> str:
        if d > _DRIFT_MODERATE:  return "major"
        if d > _DRIFT_MINOR:     return "moderate"
        if d > 0:                return "minor"
        if d < 0:                return "pulled_in"
        return "unchanged"

    merged["drift_class"] = merged["drift_days"].apply(_cls)

    # Prefer squad from current export (more up-to-date team assignment)
    if "squad_curr" in merged.columns:
        merged["squad"] = merged["squad_curr"].fillna(
            merged.get("rm_squad", "")
        )
    elif "rm_squad" in merged.columns:
        merged["squad"] = merged["rm_squad"]
    else:
        merged["squad"] = ""

    return merged


def date_drift_summary(
    baseline_df: pd.DataFrame,
    current_df: pd.DataFrame,
    baseline_date: "pd.Timestamp | None" = None,
    current_date:  "pd.Timestamp | None" = None,
) -> dict:
    """
    Compare target end dates between two Advanced Roadmaps exports to expose
    "soft slip": items whose deadlines have been quietly pushed out.

    Parameters
    ----------
    baseline_df   : roadmaps DataFrame from the original/baseline export
    current_df    : roadmaps DataFrame from the most recent export
    baseline_date : date the baseline CSV was exported (used for drift-rate calc)
    current_date  : date the current CSV was exported (defaults to today)

    Returns a dict with:
        n_compared, n_drifted, n_pulled_in, n_unchanged,
        total_drift_days, avg_drift_days, max_drift_days,
        drift_rate_per_day  — avg drift per elapsed calendar day (None if no dates)
        records             — DataFrame sorted by drift desc
        by_hierarchy        — drift aggregated by hierarchy level
        by_squad            — drift aggregated by squad/team

    Returns {} when not enough data to compare.
    """
    if baseline_df is None or current_df is None:
        return {}

    merged = _drift_merge(baseline_df, current_df)
    if merged is None:
        log.warning("date_drift_summary: no overlapping keys with target dates.")
        return {}

    n_compared  = len(merged)
    n_drifted   = int((merged["drift_days"] > 0).sum())
    n_pulled_in = int((merged["drift_days"] < 0).sum())
    n_unchanged = int((merged["drift_days"] == 0).sum())

    drifted     = merged[merged["drift_days"] > 0]
    total_drift = int(drifted["drift_days"].sum()) if not drifted.empty else 0
    avg_drift   = round(float(drifted["drift_days"].mean()), 1) if not drifted.empty else 0.0
    max_drift   = int(drifted["drift_days"].max()) if not drifted.empty else 0

    # Drift rate: how many days of drift per elapsed calendar day
    drift_rate: float | None = None
    if baseline_date is not None and n_drifted > 0:
        ref = current_date or pd.Timestamp.now().normalize()
        elapsed = (ref - baseline_date).total_seconds() / _SECS_PER_DAY
        if elapsed > 0:
            drift_rate = round(avg_drift / elapsed, 4)

    # Readable date columns for display
    records = merged.copy()
    records["baseline_end_str"] = records["baseline_end"].dt.strftime("%d %b %Y")
    records["current_end_str"]  = records["current_end"].dt.strftime("%d %b %Y")
    records = records.sort_values("drift_days", ascending=False).reset_index(drop=True)

    def _agg(grp_col: str) -> pd.DataFrame:
        return (
            merged.groupby(grp_col)
            .agg(
                items        =("key", "count"),
                drifted      =("drift_days", lambda x: int((x > 0).sum())),
                avg_drift    =("drift_days", lambda x: round(float(x[x > 0].mean()), 1) if (x > 0).any() else 0.0),
                max_drift    =("drift_days", "max"),
                total_drift  =("drift_days", lambda x: int(x[x > 0].sum())),
            )
            .reset_index()
            .sort_values("total_drift", ascending=False)
        )

    by_hier  = _agg("hierarchy")
    by_squad = _agg("squad") if "squad" in merged.columns else pd.DataFrame()

    log.info(
        "date_drift_summary: %d compared, %d drifted, avg %.1f d, max %d d, rate %s d/d",
        n_compared, n_drifted, avg_drift, max_drift,
        f"{drift_rate:.4f}" if drift_rate else "n/a",
    )

    return {
        "n_compared":       n_compared,
        "n_drifted":        n_drifted,
        "n_pulled_in":      n_pulled_in,
        "n_unchanged":      n_unchanged,
        "total_drift_days": total_drift,
        "avg_drift_days":   avg_drift,
        "max_drift_days":   max_drift,
        "drift_rate_per_day": drift_rate,
        "records":          records,
        "by_hierarchy":     by_hier,
        "by_squad":         by_squad,
    }


def drift_velocity(
    snapshots: "list[tuple[pd.Timestamp, pd.DataFrame]]",
    current_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Compute how total drift has accumulated over time across a series of
    roadmaps snapshots compared against the current export.

    Parameters
    ----------
    snapshots  : list of (snapshot_date, roadmaps_df) tuples, oldest first
    current_df : the most recent roadmaps DataFrame

    Returns a DataFrame with one row per snapshot:
        snapshot_date, n_compared, n_drifted, total_drift_days,
        avg_drift_days, drift_rate_per_week
    """
    rows = []
    today = pd.Timestamp.now().normalize()

    for snap_date, snap_df in sorted(snapshots, key=lambda t: t[0]):
        merged = _drift_merge(snap_df, current_df)
        if merged is None:
            continue

        drifted     = merged[merged["drift_days"] > 0]
        total_drift = int(drifted["drift_days"].sum()) if not drifted.empty else 0
        avg_drift   = round(float(drifted["drift_days"].mean()), 1) if not drifted.empty else 0.0
        elapsed_d   = (today - snap_date).total_seconds() / _SECS_PER_DAY
        rate_pw     = round(avg_drift / (elapsed_d / 7), 2) if elapsed_d > 0 and not drifted.empty else 0.0

        rows.append({
            "snapshot_date":      snap_date,
            "n_compared":         len(merged),
            "n_drifted":          int((merged["drift_days"] > 0).sum()),
            "total_drift_days":   total_drift,
            "avg_drift_days":     avg_drift,
            "drift_rate_per_week": rate_pw,
        })

    return pd.DataFrame(rows) if rows else pd.DataFrame()


def drift_adjusted_targets(
    current_df: pd.DataFrame,
    drift_rate_per_day: float,
    today: "pd.Timestamp | None" = None,
) -> pd.DataFrame:
    """
    For every in-flight item with a future target end date, project how much
    additional drift is expected if the current drift rate continues.

    adjusted_target = current_target + (remaining_days × drift_rate_per_day)

    Parameters
    ----------
    current_df          : roadmaps DataFrame (output of load_roadmaps)
    drift_rate_per_day  : avg drift per calendar day, from date_drift_summary
    today               : reference date (defaults to now)

    Returns a DataFrame with columns:
        key, hierarchy, rm_squad, current_target, remaining_days,
        expected_additional_drift, adjusted_target, adjusted_target_str
    """
    if drift_rate_per_day is None or drift_rate_per_day <= 0:
        return pd.DataFrame()

    ref = (today or pd.Timestamp.now().normalize()).normalize()

    inflight = current_df[
        current_df["rm_target_end"].notna() &
        (current_df["rm_target_end"] > ref)
    ].copy()

    if inflight.empty:
        return pd.DataFrame()

    inflight["remaining_days"] = (
        (inflight["rm_target_end"] - ref)
        .dt.total_seconds()
        .div(_SECS_PER_DAY)
        .round()
        .astype(int)
    )
    inflight["expected_additional_drift"] = (
        (inflight["remaining_days"] * drift_rate_per_day)
        .round()
        .astype(int)
    )
    inflight["adjusted_target"] = (
        inflight["rm_target_end"] +
        pd.to_timedelta(inflight["expected_additional_drift"], unit="D")
    )
    inflight["adjusted_target_str"] = inflight["adjusted_target"].dt.strftime("%d %b %Y")
    inflight["current_target_str"]  = inflight["rm_target_end"].dt.strftime("%d %b %Y")

    keep = ["key", "hierarchy", "current_target_str", "remaining_days",
            "expected_additional_drift", "adjusted_target_str", "adjusted_target"]
    if "rm_squad" in inflight.columns:
        keep.insert(2, "rm_squad")

    return (
        inflight[keep]
        .sort_values("expected_additional_drift", ascending=False)
        .reset_index(drop=True)
    )


# ── Delivery risk (in-flight items vs target dates) ───────────────────────────

def delivery_risk_summary(df: pd.DataFrame) -> dict:
    """
    For in-flight items (not yet resolved) that have a rm_target_end date,
    calculate how many days remain until the target and classify each item.

    Classification:
        overdue   — target end date has passed (days_remaining < 0)
        at_risk   — target is within the next 14 days (0 ≤ days_remaining ≤ 14)
        on_track  — target is more than 14 days away

    Returns a dict with keys:
        n_tracked, n_overdue, n_at_risk, n_on_track, records (DataFrame)
    Returns {} if rm_target_end column is absent or no eligible rows exist.
    """
    if "rm_target_end" not in df.columns:
        return {}

    eligible = df[
        df["resolved"].isna() &
        df["rm_target_end"].notna()
    ].copy()

    if eligible.empty:
        return {}

    today = pd.Timestamp.now().normalize()
    eligible["days_remaining"] = (
        (eligible["rm_target_end"] - today)
        .dt.total_seconds()
        .div(_SECS_PER_DAY)
        .round()
        .astype(int)
    )

    def _classify(d: int) -> str:
        if d < 0:
            return "overdue"
        if d <= _RISK_AT_RISK_DAYS:
            return "at_risk"
        return "on_track"

    eligible["risk"] = eligible["days_remaining"].apply(_classify)

    n_total   = len(eligible)
    n_overdue = int((eligible["risk"] == "overdue").sum())
    n_at_risk = int((eligible["risk"] == "at_risk").sum())
    n_on_track = int((eligible["risk"] == "on_track").sum())

    # Select the most useful columns for the UI table
    keep_cols = ["key", "title", "type", "squad", "status",
                 "rm_target_end", "days_remaining", "risk"]
    if "hierarchy" in eligible.columns:
        keep_cols = ["key", "title", "hierarchy", "type", "squad",
                     "status", "rm_target_end", "days_remaining", "risk"]

    records_df = (
        eligible[keep_cols]
        .sort_values("days_remaining")
        .reset_index(drop=True)
    )

    log.debug(
        "delivery_risk_summary: %d tracked, %d overdue, %d at_risk, %d on_track",
        n_total, n_overdue, n_at_risk, n_on_track,
    )

    return {
        "n_tracked":  n_total,
        "n_overdue":  n_overdue,
        "n_at_risk":  n_at_risk,
        "n_on_track": n_on_track,
        "records":    records_df,
    }


# ── Plan accuracy ─────────────────────────────────────────────────────────────

def plan_accuracy_records(df: pd.DataFrame) -> list[PlanAccuracyRecord]:
    """
    Build a PlanAccuracyRecord for every resolved item that has a
    rm_target_end date (from the Advanced Roadmaps join).

    Items without both resolved and rm_target_end are skipped.
    """
    required = {"key", "title", "type", "squad", "resolved"}
    if not required.issubset(df.columns) or "rm_target_end" not in df.columns:
        log.info("plan_accuracy_records: required columns not present — returning empty list.")
        return []

    eligible = df[
        df["resolved"].notna() &
        df["rm_target_end"].notna()
    ].copy()

    if eligible.empty:
        return []

    records: list[PlanAccuracyRecord] = []
    for _, row in eligible.iterrows():
        slip = (row["resolved"] - row["rm_target_end"]).total_seconds() / _SECS_PER_DAY

        records.append(PlanAccuracyRecord(
            key=str(row.get("key", "")),
            title=str(row.get("title", ""))[:80],
            item_type=str(row.get("type", "")),
            squad=str(row.get("squad", "")),
            target_end=row["rm_target_end"],
            resolved=row["resolved"],
            slip_days=round(float(slip), 1),
            sprint_planned=str(row.get("sprint_first", "")),
            sprint_delivered=str(row.get("sprint_last_completed", "")),
        ))

    return records


def plan_accuracy_summary(records: list[PlanAccuracyRecord]) -> dict:
    """
    Aggregate plan accuracy statistics.

    Returns a dict with keys:
        n_items, n_on_time, n_late, n_early,
        pct_on_time (delivered within ±3 days of target),
        mean_slip_days, median_slip_days, p85_slip_days
    """
    if not records:
        return {}

    slips = [r.slip_days for r in records]
    arr   = np.array(slips)

    on_time_tolerance = 3.0   # days; items within ±3 days count as "on time"
    n_late    = int((arr > on_time_tolerance).sum())
    n_early   = int((arr < -on_time_tolerance).sum())
    n_on_time = int((np.abs(arr) <= on_time_tolerance).sum())

    return {
        "n_items":          len(records),
        "n_on_time":        n_on_time,
        "n_late":           n_late,
        "n_early":          n_early,
        "pct_on_time":      round(100 * n_on_time / len(records), 1),
        "mean_slip_days":   round(float(arr.mean()), 1),
        "median_slip_days": round(float(np.median(arr)), 1),
        "p85_slip_days":    round(float(np.percentile(arr, 85)), 1),
    }


# ── Sprint slippage ───────────────────────────────────────────────────────────

def _sprint_number(sprint_name: str) -> int | None:
    """
    Extract an integer sprint number from a sprint name.
    Handles common patterns:
      "PMD_26PI1_Sprint3"  → 3
      "Sprint 2"           → 2
      "Sprint2"            → 2
    Returns None if no number found.
    """
    match = re.search(r"sprint\s*(\d+)", sprint_name, flags=re.IGNORECASE)
    if match:
        return int(match.group(1))
    return None


def sprint_slippage_summary(df: pd.DataFrame) -> dict:
    """
    Analyse how many items slipped across one or more sprints.

    Requires:
        sprint_first             — first sprint the item appeared in
        sprint_last_completed    — sprint it was finally resolved in
        resolved                 — non-null means the item is Done

    Returns a dict with keys:
        n_items_with_sprint_data, n_no_slip, n_slipped_1, n_slipped_2plus,
        pct_no_slip, pct_slipped
    """
    required = {"sprint_first", "sprint_last_completed", "resolved"}
    if not required.issubset(df.columns):
        log.info("sprint_slippage_summary: sprint columns not present — returning empty.")
        return {}

    done = df[df["resolved"].notna()].copy()
    done = done[
        done["sprint_first"].notna() &
        (done["sprint_first"] != "") &
        done["sprint_last_completed"].notna() &
        (done["sprint_last_completed"] != "")
    ]

    if done.empty:
        return {}

    done["_n_planned"] = done["sprint_first"].apply(_sprint_number)
    done["_n_delivered"] = done["sprint_last_completed"].apply(_sprint_number)

    # Only count rows where we could extract both numbers
    valid = done[done["_n_planned"].notna() & done["_n_delivered"].notna()].copy()
    if valid.empty:
        return {}

    valid["_slip"] = (valid["_n_delivered"] - valid["_n_planned"]).astype(int)

    n_total     = len(valid)
    n_no_slip   = int((valid["_slip"] == 0).sum())
    n_slip_1    = int((valid["_slip"] == 1).sum())
    n_slip_2p   = int((valid["_slip"] >= 2).sum())
    n_early     = int((valid["_slip"] < 0).sum())  # delivered earlier than planned
    pct_no_slip = round(100 * n_no_slip / max(n_total, 1), 1)
    pct_slipped = round(100 * (n_slip_1 + n_slip_2p) / max(n_total, 1), 1)

    # ── Reliability check ────────────────────────────────────────────────────
    # Jira *replaces* the Sprint field when an item moves sprints (rather than
    # appending to a compound "Sprint1 + Sprint2" value).  When this happens,
    # sprint_first == sprint_last_completed for every item, so _slip is always 0
    # and the 100% no-slip result is an artefact of missing history, not reality.
    #
    # Heuristic: if ≥ 80 % of valid items have _slip == 0 *and* their raw
    # sprint_first exactly equals sprint_last_completed, the data is likely
    # unreliable rather than genuinely slip-free.
    same_sprint_mask = (
        valid["sprint_first"].astype(str).str.strip()
        == valid["sprint_last_completed"].astype(str).str.strip()
    )
    pct_same = same_sprint_mask.sum() / max(n_total, 1)
    data_reliable = not (pct_same >= 0.80 and n_no_slip / max(n_total, 1) >= 0.80)

    data_warning = (
        "Jira appears to have **replaced** the Sprint field when tickets moved sprints "
        "rather than keeping a history of all sprints. Because of this, every item shows "
        "the same 'planned' and 'delivered' sprint, making slippage appear to be 0% — "
        "which is almost certainly wrong.\n\n"
        "**Workaround:** to get reliable slippage data you need Jira's full issue changelog "
        "(available via the Jira API). The CSV export only contains the *current* sprint value."
        if not data_reliable else ""
    )

    log.debug(
        "sprint_slippage_summary: n=%d, pct_same_sprint=%.1f%%, data_reliable=%s",
        n_total, 100 * pct_same, data_reliable,
    )

    return {
        "n_items_with_sprint_data": n_total,
        "n_no_slip":                n_no_slip,
        "n_slipped_1":              n_slip_1,
        "n_slipped_2plus":          n_slip_2p,
        "n_delivered_early":        n_early,
        "pct_no_slip":              pct_no_slip,
        "pct_slipped":              pct_slipped,
        "data_reliable":            data_reliable,
        "data_warning":             data_warning,
    }

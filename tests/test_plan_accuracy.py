"""Tests for core/plan_accuracy.py — drift analysis functions."""
from __future__ import annotations

import pandas as pd
import pytest

from core.plan_accuracy import (
    date_drift_summary,
    drift_velocity,
    drift_adjusted_targets,
)


def _rm_df(rows: list[dict]) -> pd.DataFrame:
    """Build a minimal roadmaps DataFrame matching load_roadmaps() output."""
    return pd.DataFrame({
        "key":             [r["key"] for r in rows],
        "hierarchy":       [r.get("hierarchy", "Story") for r in rows],
        "rm_squad":        [r.get("squad", "Team A") for r in rows],
        "rm_target_end":   pd.to_datetime([r["target_end"] for r in rows]),
        "rm_target_start": pd.NaT,
        "rm_progress_pct": None,
        "rm_done_sp":      None,
        "rm_rem_sp":       None,
        "rm_done_ic":      None,
        "rm_total_ic":     None,
        "rm_rag":          None,
    })


# ── date_drift_summary ────────────────────────────────────────────────────────

def test_no_drift_when_dates_unchanged():
    base = _rm_df([{"key": "X-1", "target_end": "2026-06-30"}])
    curr = _rm_df([{"key": "X-1", "target_end": "2026-06-30"}])
    result = date_drift_summary(base, curr)
    assert result["n_compared"] == 1
    assert result["n_drifted"] == 0
    assert result["n_unchanged"] == 1
    assert result["max_drift_days"] == 0


def test_positive_drift_detected():
    base = _rm_df([{"key": "X-1", "target_end": "2026-06-01"}])
    curr = _rm_df([{"key": "X-1", "target_end": "2026-07-01"}])
    result = date_drift_summary(base, curr)
    assert result["n_drifted"] == 1
    assert result["max_drift_days"] == 30
    assert result["total_drift_days"] == 30
    assert result["records"].iloc[0]["drift_class"] == "moderate"


def test_pulled_in_detected():
    base = _rm_df([{"key": "X-1", "target_end": "2026-07-01"}])
    curr = _rm_df([{"key": "X-1", "target_end": "2026-06-01"}])
    result = date_drift_summary(base, curr)
    assert result["n_pulled_in"] == 1
    assert result["n_drifted"] == 0


def test_mixed_items():
    base = _rm_df([
        {"key": "X-1", "target_end": "2026-06-01"},
        {"key": "X-2", "target_end": "2026-06-01"},
        {"key": "X-3", "target_end": "2026-06-01"},
    ])
    curr = _rm_df([
        {"key": "X-1", "target_end": "2026-07-15"},  # +44 d (major)
        {"key": "X-2", "target_end": "2026-06-01"},  # unchanged
        {"key": "X-3", "target_end": "2026-05-25"},  # pulled in
    ])
    result = date_drift_summary(base, curr)
    assert result["n_compared"] == 3
    assert result["n_drifted"] == 1
    assert result["n_unchanged"] == 1
    assert result["n_pulled_in"] == 1
    assert result["max_drift_days"] == 44
    assert result["records"].iloc[0]["drift_class"] == "major"


def test_non_overlapping_keys_returns_empty():
    base = _rm_df([{"key": "X-1", "target_end": "2026-06-01"}])
    curr = _rm_df([{"key": "X-99", "target_end": "2026-06-01"}])
    result = date_drift_summary(base, curr)
    assert result == {}


def test_none_inputs_return_empty():
    assert date_drift_summary(None, None) == {}
    base = _rm_df([{"key": "X-1", "target_end": "2026-06-01"}])
    assert date_drift_summary(base, None) == {}


def test_drift_rate_calculated_with_baseline_date():
    base = _rm_df([{"key": "X-1", "target_end": "2026-06-01"}])
    curr = _rm_df([{"key": "X-1", "target_end": "2026-07-01"}])  # +30 days
    baseline_date = pd.Timestamp("2026-05-01")
    current_date  = pd.Timestamp("2026-05-29")   # 28 elapsed days
    result = date_drift_summary(base, curr, baseline_date=baseline_date, current_date=current_date)
    # drift_rate = 30 / 28 ≈ 1.0714
    assert result["drift_rate_per_day"] is not None
    assert result["drift_rate_per_day"] == pytest.approx(30 / 28, rel=0.01)


def test_by_hierarchy_aggregation():
    base = _rm_df([
        {"key": "E-1", "hierarchy": "Epic",  "target_end": "2026-06-01"},
        {"key": "S-1", "hierarchy": "Story", "target_end": "2026-06-01"},
        {"key": "S-2", "hierarchy": "Story", "target_end": "2026-06-01"},
    ])
    curr = _rm_df([
        {"key": "E-1", "hierarchy": "Epic",  "target_end": "2026-07-01"},  # +30
        {"key": "S-1", "hierarchy": "Story", "target_end": "2026-06-15"},  # +14
        {"key": "S-2", "hierarchy": "Story", "target_end": "2026-06-01"},  # unchanged
    ])
    result = date_drift_summary(base, curr)
    hier = result["by_hierarchy"].set_index("hierarchy")
    assert hier.loc["Epic", "drifted"] == 1
    assert hier.loc["Story", "drifted"] == 1
    assert hier.loc["Story", "items"] == 2


def test_by_squad_aggregation():
    base = _rm_df([
        {"key": "X-1", "squad": "Alpha", "target_end": "2026-06-01"},
        {"key": "X-2", "squad": "Beta",  "target_end": "2026-06-01"},
    ])
    curr = _rm_df([
        {"key": "X-1", "squad": "Alpha", "target_end": "2026-07-01"},  # +30
        {"key": "X-2", "squad": "Beta",  "target_end": "2026-06-01"},  # unchanged
    ])
    result = date_drift_summary(base, curr)
    assert not result["by_squad"].empty
    squads = result["by_squad"].set_index("squad")
    assert squads.loc["Alpha", "drifted"] == 1
    assert squads.loc["Beta",  "drifted"] == 0


# ── drift_velocity ────────────────────────────────────────────────────────────

def test_drift_velocity_returns_one_row_per_snapshot():
    snap1 = (pd.Timestamp("2026-01-01"), _rm_df([{"key": "X-1", "target_end": "2026-06-01"}]))
    snap2 = (pd.Timestamp("2026-03-01"), _rm_df([{"key": "X-1", "target_end": "2026-06-01"}]))
    curr  = _rm_df([{"key": "X-1", "target_end": "2026-07-01"}])
    result = drift_velocity([snap1, snap2], curr)
    assert len(result) == 2
    assert list(result["snapshot_date"]) == [pd.Timestamp("2026-01-01"), pd.Timestamp("2026-03-01")]


def test_drift_velocity_sorted_by_date():
    snap1 = (pd.Timestamp("2026-03-01"), _rm_df([{"key": "X-1", "target_end": "2026-06-01"}]))
    snap2 = (pd.Timestamp("2026-01-01"), _rm_df([{"key": "X-1", "target_end": "2026-06-01"}]))
    curr  = _rm_df([{"key": "X-1", "target_end": "2026-07-01"}])
    result = drift_velocity([snap1, snap2], curr)
    assert result.iloc[0]["snapshot_date"] < result.iloc[1]["snapshot_date"]


def test_drift_velocity_empty_when_no_overlap():
    snap = (pd.Timestamp("2026-01-01"), _rm_df([{"key": "X-1", "target_end": "2026-06-01"}]))
    curr = _rm_df([{"key": "X-99", "target_end": "2026-07-01"}])
    result = drift_velocity([snap], curr)
    assert result.empty


# ── drift_adjusted_targets ────────────────────────────────────────────────────

def test_adjusted_targets_basic():
    today = pd.Timestamp("2026-05-29")
    curr = _rm_df([{"key": "X-1", "target_end": "2026-07-29"}])  # 61 days out
    # drift rate 0.1 d/d → 61 * 0.1 = ~6 days extra
    result = drift_adjusted_targets(curr, drift_rate_per_day=0.1, today=today)
    assert len(result) == 1
    assert result.iloc[0]["expected_additional_drift"] == 6


def test_adjusted_targets_skips_past_dates():
    today = pd.Timestamp("2026-05-29")
    curr = _rm_df([
        {"key": "X-1", "target_end": "2026-07-01"},   # future — included
        {"key": "X-2", "target_end": "2026-04-01"},   # past   — excluded
    ])
    result = drift_adjusted_targets(curr, drift_rate_per_day=0.1, today=today)
    assert len(result) == 1
    assert result.iloc[0]["key"] == "X-1"


def test_adjusted_targets_zero_rate_returns_empty():
    curr = _rm_df([{"key": "X-1", "target_end": "2026-07-01"}])
    assert drift_adjusted_targets(curr, drift_rate_per_day=0.0).empty
    assert drift_adjusted_targets(curr, drift_rate_per_day=None).empty

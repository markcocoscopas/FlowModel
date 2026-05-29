"""Tests for core/plan_accuracy.py — date_drift_summary."""
from __future__ import annotations

import pandas as pd
import pytest

from core.plan_accuracy import date_drift_summary


def _rm_df(rows: list[dict]) -> pd.DataFrame:
    """Build a minimal roadmaps DataFrame matching load_roadmaps() output."""
    return pd.DataFrame({
        "key":            [r["key"] for r in rows],
        "hierarchy":      [r.get("hierarchy", "Story") for r in rows],
        "rm_target_end":  pd.to_datetime([r["target_end"] for r in rows]),
        "rm_target_start": pd.NaT,
        "rm_progress_pct": None,
        "rm_done_sp": None,
        "rm_rem_sp": None,
        "rm_done_ic": None,
        "rm_total_ic": None,
        "rm_rag": None,
    })


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

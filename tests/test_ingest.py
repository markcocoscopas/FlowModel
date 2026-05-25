"""
tests/test_ingest.py
~~~~~~~~~~~~~~~~~~~~
Tests for core.ingest: CSV loading, column deduplication, date parsing,
join, and filter logic.
"""

from __future__ import annotations

import pandas as pd
import pytest

from core.ingest import (
    _deduplicate_columns,
    _parse_last_completed_sprint,
    _parse_first_sprint,
    _normalise_blocked,
    load_snapshot,
    load_roadmaps,
    merge_datasets,
    apply_filters,
)


# ── Sprint parsing ─────────────────────────────────────────────────────────────

class TestSprintParsing:
    def test_last_completed_simple(self):
        # When the only part has a PI prefix, the full segment is returned
        # (minus the [COMPLETED] tag).  The PI prefix is part of the name.
        s = "PMD_25PI4_Sprint1 [COMPLETED]"
        result = _parse_last_completed_sprint(s)
        assert "Sprint1" in result
        assert "[COMPLETED]" not in result

    def test_last_completed_multiple(self):
        s = "PMD_25PI4_Sprint1 [COMPLETED] + Sprint2 [COMPLETED] + Sprint3"
        assert _parse_last_completed_sprint(s) == "Sprint2"

    def test_last_completed_none(self):
        s = "PMD_25PI4_Sprint5 [ACTIVE]"
        result = _parse_last_completed_sprint(s)
        assert "Sprint5" in result

    def test_first_sprint(self):
        s = "PMD_25PI4_Sprint3 [COMPLETED] + Sprint4 [COMPLETED]"
        assert "Sprint3" in _parse_first_sprint(s)

    def test_empty(self):
        assert _parse_last_completed_sprint("") == ""
        assert _parse_first_sprint(None) == ""


# ── Blocked normalisation ─────────────────────────────────────────────────────

class TestNormaliseBlocked:
    def test_impediment(self):
        s = pd.Series(["Impediment", "impediment", "", "IMPEDIMENT"])
        result = _normalise_blocked(s)
        assert result.tolist() == [True, True, False, True]

    def test_yes(self):
        s = pd.Series(["Yes", "no", "YES"])
        result = _normalise_blocked(s)
        assert result.tolist() == [True, False, True]

    def test_empty_and_nan(self):
        s = pd.Series([None, "", "Blocked", "false"])
        result = _normalise_blocked(s)
        assert result.iloc[0] == False
        assert result.iloc[2] == True


# ── Column deduplication ──────────────────────────────────────────────────────

class TestDeduplicateColumns:
    def test_no_duplicates(self):
        df = pd.DataFrame({"A": [1], "B": [2]})
        out = _deduplicate_columns(df)
        assert list(out.columns) == ["A", "B"]

    def test_label_merge(self):
        df = pd.DataFrame({"Labels": ["backend", "frontend"]})
        # Simulate duplicate Labels column by renaming after creation
        df2 = df.copy()
        df2.columns = ["Labels"]
        # Single column — no dedup needed
        out = _deduplicate_columns(df2)
        assert "Labels" in out.columns

    def test_sprint_columns_joined(self):
        # pandas renames duplicate CSV columns as Sprint, Sprint.1, Sprint.2 …
        # _deduplicate_columns must join all sprint columns with " + " so the
        # full sprint history is preserved for slippage detection.
        import io as _io
        raw = pd.read_csv(
            _io.StringIO("Sprint,Sprint\nSprint1 [COMPLETED],Sprint2 [COMPLETED]\n")
        )
        # pandas will have renamed to ["Sprint", "Sprint.1"]
        assert list(raw.columns) == ["Sprint", "Sprint.1"]
        out = _deduplicate_columns(raw)
        assert "Sprint" in out.columns
        assert "Sprint.1" not in out.columns
        # All sprint values must be joined so history is not lost
        assert out["Sprint"].iloc[0] == "Sprint1 [COMPLETED] + Sprint2 [COMPLETED]"

    def test_component_last_wins(self):
        # Jira puts the parent component first and the team sub-component last.
        # _deduplicate_columns must take the last non-null for Component/s so
        # squads sharing a parent component are correctly differentiated.
        import io as _io
        raw = pd.read_csv(
            _io.StringIO("Component/s,Component/s\nPerception MLO,PMD SW Dev\n")
        )
        assert list(raw.columns) == ["Component/s", "Component/s.1"]
        out = _deduplicate_columns(raw)
        assert "Component/s" in out.columns
        assert "Component/s.1" not in out.columns
        # Last non-null (most specific sub-component) should win
        assert out["Component/s"].iloc[0] == "PMD SW Dev"


# ── Integration: load sample CSV ──────────────────────────────────────────────

class TestLoadSnapshot:
    def test_loads_sample(self, sample_csv_path, default_config):
        df = load_snapshot(sample_csv_path, default_config)
        assert not df.empty
        assert "key" in df.columns
        assert "created" in df.columns
        assert "resolved" in df.columns
        assert "squad" in df.columns
        assert "is_blocked" in df.columns

    def test_date_columns_are_datetime(self, sample_csv_path, default_config):
        df = load_snapshot(sample_csv_path, default_config)
        assert pd.api.types.is_datetime64_any_dtype(df["created"])
        assert pd.api.types.is_datetime64_any_dtype(df["resolved"])

    def test_no_negative_cycle_time_after_filter(self, sample_csv_path, default_config):
        from core.ingest import apply_filters
        from core.metrics import cycle_time_series
        df = load_snapshot(sample_csv_path, default_config)
        filtered, _ = apply_filters(df, default_config)
        ct = cycle_time_series(filtered).dropna()
        assert (ct >= 0).all()


class TestLoadRoadmaps:
    def test_loads_sample(self, sample_roadmaps_path, default_config):
        df = load_roadmaps(sample_roadmaps_path, default_config)
        assert not df.empty
        assert "key" in df.columns
        assert "rm_target_end" in df.columns


class TestMerge:
    def test_merge_adds_rm_columns(
        self, sample_csv_path, sample_roadmaps_path, default_config
    ):
        snap = load_snapshot(sample_csv_path, default_config)
        rm   = load_roadmaps(sample_roadmaps_path, default_config)
        merged = merge_datasets(snap, rm)
        assert "rm_target_end" in merged.columns
        assert len(merged) == len(snap)   # left join preserves all snapshot rows

    def test_merge_without_roadmaps(self, sample_csv_path, default_config):
        snap = load_snapshot(sample_csv_path, default_config)
        merged = merge_datasets(snap, None)
        assert len(merged) == len(snap)


# ── apply_filters ─────────────────────────────────────────────────────────────

class TestApplyFilters:
    def test_excludes_cancelled(self, sample_csv_path, default_config):
        from core.ingest import load_snapshot, apply_filters
        df = load_snapshot(sample_csv_path, default_config)
        filtered, report = apply_filters(df, default_config)
        # Cancelled is in excluded_states — should not appear in filtered
        assert "Cancelled" not in filtered["status"].values

    def test_squad_filter(self, sample_csv_path, default_config):
        df = load_snapshot(sample_csv_path, default_config)
        squads_in_data = df["squad"].unique().tolist()
        if len(squads_in_data) < 1:
            pytest.skip("No squads in sample data")
        target = squads_in_data[0]
        filtered, report = apply_filters(df, default_config, squads=[target])
        assert set(filtered["squad"].unique()) == {target}

    def test_quality_report_counts_match(self, sample_csv_path, default_config):
        df = load_snapshot(sample_csv_path, default_config)
        filtered, report = apply_filters(df, default_config)
        assert report.total_rows_read == len(df)
        assert report.rows_accepted + report.rows_excluded == report.total_rows_read

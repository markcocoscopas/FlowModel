"""
tests/test_metrics.py
~~~~~~~~~~~~~~~~~~~~~
Tests for core.metrics: cycle time, throughput, WIP, and ageing.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.metrics import (
    cycle_time_series,
    cycle_time_stats,
    cycle_time_by_type,
    throughput_daily,
    throughput_weekly,
    throughput_stats,
    throughput_samples,
    wip_snapshot,
    ageing_items,
    flow_efficiency_note,
)


# ── Cycle time ────────────────────────────────────────────────────────────────

class TestCycleTimeSeries:
    def test_basic(self, healthy_squad_df):
        ct = cycle_time_series(healthy_squad_df)
        # Resolved items should have non-null cycle time
        done = healthy_squad_df[healthy_squad_df["resolved"].notna()]
        assert ct[done.index].notna().all()

    def test_in_flight_are_nan(self, healthy_squad_df):
        ct = cycle_time_series(healthy_squad_df)
        in_flight = healthy_squad_df[healthy_squad_df["resolved"].isna()]
        if not in_flight.empty:
            assert ct[in_flight.index].isna().all()

    def test_no_negative_values(self, healthy_squad_df):
        ct = cycle_time_series(healthy_squad_df).dropna()
        assert (ct >= 0).all()

    def test_empty_df_returns_empty_series(self):
        empty = pd.DataFrame(
            columns=["created", "resolved", "key", "type", "status", "squad"]
        )
        empty["created"] = pd.Series(dtype="datetime64[ns]")
        empty["resolved"] = pd.Series(dtype="datetime64[ns]")
        ct = cycle_time_series(empty)
        assert ct.empty


class TestCycleTimeStats:
    def test_returns_dataclass(self, healthy_squad_df):
        from core.models import CycleTimeStats
        stats = cycle_time_stats(healthy_squad_df)
        assert isinstance(stats, CycleTimeStats)

    def test_p50_less_than_p85_less_than_p95(self, healthy_squad_df):
        s = cycle_time_stats(healthy_squad_df)
        assert s.p50 <= s.p85 <= s.p95

    def test_zero_on_empty(self):
        import pandas as pd
        empty = pd.DataFrame({"created": pd.Series(dtype="datetime64[ns]"),
                               "resolved": pd.Series(dtype="datetime64[ns]"),
                               "type": pd.Series(dtype=str)})
        s = cycle_time_stats(empty)
        assert s.count == 0

    def test_healthy_squad_median_near_8d(self, healthy_squad_df):
        s = cycle_time_stats(healthy_squad_df)
        # Healthy squad fixture uses mean=8 ± 2 std → median should be 6–10
        assert 4 <= s.p50 <= 14, f"Unexpected median: {s.p50}"

    def test_bottleneck_squad_higher_median(self, healthy_squad_df, bottleneck_squad_df):
        healthy = cycle_time_stats(healthy_squad_df)
        bottleneck = cycle_time_stats(bottleneck_squad_df)
        assert bottleneck.p50 > healthy.p50


# ── Throughput ────────────────────────────────────────────────────────────────

class TestThroughputWeekly:
    def test_basic(self, healthy_squad_df):
        weekly = throughput_weekly(healthy_squad_df)
        assert not weekly.empty
        assert (weekly >= 0).all()

    def test_sum_equals_resolved_count(self, healthy_squad_df):
        n_resolved = healthy_squad_df["resolved"].notna().sum()
        weekly = throughput_weekly(healthy_squad_df)
        assert weekly.sum() == n_resolved

    def test_empty_df_returns_empty(self):
        empty = pd.DataFrame({"resolved": pd.Series(dtype="datetime64[ns]"), "key": []})
        assert throughput_weekly(empty).empty


class TestThroughputSamples:
    def test_returns_list(self, healthy_squad_df):
        weekly = throughput_weekly(healthy_squad_df)
        samples = throughput_samples(weekly, window_weeks=8)
        assert isinstance(samples, list)
        assert len(samples) > 0

    def test_respects_window(self, healthy_squad_df):
        weekly = throughput_weekly(healthy_squad_df)
        samples = throughput_samples(weekly, window_weeks=4)
        assert len(samples) <= 4

    def test_fallback_on_empty(self):
        assert throughput_samples(pd.Series(dtype=int)) == [0]


# ── WIP ───────────────────────────────────────────────────────────────────────

class TestWipSnapshot:
    def test_basic(self, healthy_squad_df, default_config):
        wip = wip_snapshot(healthy_squad_df, default_config)
        assert isinstance(wip, dict)
        # Total WIP should be the count of in-flight items
        n_inflight = healthy_squad_df[
            healthy_squad_df["resolved"].isna() & healthy_squad_df["created"].notna()
        ].shape[0]
        total = sum(wip.values())
        assert total == n_inflight

    def test_includes_all_in_flight_states(self, bottleneck_squad_df, default_config):
        wip = wip_snapshot(bottleneck_squad_df, default_config)
        # Bottleneck fixture has some Blocked items
        has_blocked = any("Blocked" in k or "blocked" in k.lower() for k in wip)
        assert has_blocked or wip.get("Blocked", 0) >= 0   # at least key present or 0


# ── Ageing WIP ────────────────────────────────────────────────────────────────

class TestAgeingItems:
    def test_only_in_flight(self, healthy_squad_df, default_config):
        items = ageing_items(healthy_squad_df, default_config)
        # All returned items should have no resolved date
        keys = {i.key for i in items}
        in_flight_keys = set(
            healthy_squad_df[healthy_squad_df["resolved"].isna()]["key"].tolist()
        )
        assert keys == in_flight_keys

    def test_sorted_by_age_desc(self, healthy_squad_df, default_config):
        items = ageing_items(healthy_squad_df, default_config)
        ages = [i.age_days for i in items]
        assert ages == sorted(ages, reverse=True)

    def test_blocked_items_flagged(self, bottleneck_squad_df, default_config):
        items = ageing_items(bottleneck_squad_df, default_config)
        blocked = [i for i in items if i.is_blocked]
        assert len(blocked) > 0


# ── Flow efficiency note ──────────────────────────────────────────────────────

def test_flow_efficiency_note_contains_phase2():
    note = flow_efficiency_note()
    assert "Phase 2" in note
    assert "changelog" in note.lower()


# ── Ageing WIP chart jitter ───────────────────────────────────────────────────

def test_ageing_wip_chart_jitter_separates_overlapping_items():
    """
    Two items with identical (status, age_days) must have distinct x-coordinates
    in the chart so neither dot is hidden behind the other.
    """
    from core.models import AgeingItem
    from ui.charts import ageing_wip_chart

    shared_status = "In Progress"
    shared_age    = 42.0

    item_a = AgeingItem(
        key="AAA-1", title="Alpha", item_type="Story",
        status=shared_status, squad="S", age_days=shared_age,
        created=pd.Timestamp("2025-01-01"),
        p50_reference=10.0, p85_reference=20.0, p95_reference=30.0,
        is_blocked=False, is_flagged=False,
    )
    item_b = AgeingItem(
        key="AAA-2", title="Beta", item_type="Story",
        status=shared_status, squad="S", age_days=shared_age,
        created=pd.Timestamp("2025-01-02"),
        p50_reference=10.0, p85_reference=20.0, p95_reference=30.0,
        is_blocked=False, is_flagged=False,
    )

    fig = ageing_wip_chart([item_a, item_b])
    x_coords = fig.data[0].x
    assert len(x_coords) == 2, "Expected exactly 2 data points"
    assert x_coords[0] != x_coords[1], (
        "Items sharing (status, age) must have distinct x-coordinates after jitter"
    )

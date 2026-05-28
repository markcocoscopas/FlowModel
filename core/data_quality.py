"""
core/data_quality.py
~~~~~~~~~~~~~~~~~~~~
Formats the DataQualityReport for display.

The DataQualityReport dataclass is produced by ingest.apply_filters().
This module provides:
  - format_report(report) → list of plain-English bullet points
  - quality_score(report) → float 0–100 (heuristic "data readiness" score)
"""

from __future__ import annotations

from core.models import DataQualityReport


def format_report(report: DataQualityReport) -> list[str]:
    """
    Convert a DataQualityReport into a list of human-readable bullet strings,
    intended for display in the Data Quality tab.
    """
    bullets: list[str] = []

    total = report.total_rows_read
    acc   = report.rows_accepted
    excl  = report.rows_excluded

    bullets.append(
        f"**{total:,}** total rows read from CSV; "
        f"**{acc:,}** accepted, **{excl:,}** excluded."
    )

    if excl > 0:
        bullets.append("**Exclusion breakdown:**")
        for reason, count in sorted(
            report.exclusion_reasons.items(), key=lambda x: -x[1]
        ):
            pct = round(100 * count / max(total, 1), 1)
            bullets.append(f"  - {reason}: {count:,} ({pct}%)")

    bullets.append(
        f"**{report.has_both_dates:,}** items are completed (have a Resolved date) — "
        f"that is **{report.pct_contributing_cycle_time}%** of all accepted items. "
        f"Cycle time, throughput, and Monte Carlo forecasts are calculated from these."
    )

    if report.has_both_dates < acc:
        n_missing = acc - report.has_both_dates
        bullets.append(
            f"  ⚠ **{n_missing:,}** accepted items are still in-flight (no Resolved date yet) — "
            "these contribute to WIP counts and the Ageing WIP chart, "
            "but not to cycle-time or throughput calculations."
        )

    if report.has_blocked_flag > 0:
        bullets.append(
            f"**{report.has_blocked_flag:,}** items have a Blocked flag set — "
            "surfaced in the Constraints tab."
        )

    if report.has_target_end > 0:
        bullets.append(
            f"**{report.has_target_end:,}** items have an Advanced Roadmaps target end date — "
            "plan accuracy metrics are available."
        )
    else:
        bullets.append(
            "No Advanced Roadmaps CSV loaded — plan accuracy metrics are unavailable. "
            "Load the roadmaps export to enable this feature."
        )

    bullets.append(
        "**Note:** Cycle times are calculated in *calendar* days (Resolved − Created). "
        "This is a lower bound on true elapsed time. "
        "Per-state residency requires Jira API integration (Phase 2)."
    )

    return bullets


def quality_score(report: DataQualityReport) -> float:
    """
    A heuristic 0–100 score for data readiness.

    Scoring components:
      - 60 pts: % of items contributing to cycle-time (has both dates)
      - 20 pts: < 5% exclusion rate
      - 10 pts: any blocked flag data present
      - 10 pts: any plan accuracy data present
    """
    if report.total_rows_read == 0:
        return 0.0

    score = 0.0

    # Cycle-time coverage (0–60)
    ct_pct = report.pct_contributing_cycle_time
    score += min(60.0, ct_pct * 0.6)

    # Low exclusion rate (0–20)
    excl_pct = 100 * report.rows_excluded / max(report.total_rows_read, 1)
    if excl_pct < 5:
        score += 20.0
    elif excl_pct < 20:
        score += 10.0

    # Blocked flag presence (0–10)
    if report.has_blocked_flag > 0:
        score += 10.0

    # Plan accuracy data (0–10)
    if report.has_target_end > 0:
        score += 10.0

    return round(score, 1)

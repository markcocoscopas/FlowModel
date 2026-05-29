"""
core/ingest.py
~~~~~~~~~~~~~~
Load, clean, and join work-item data from Jira CSV exports.

Two inputs are supported:
  1. Snapshot CSV  — "Created vs Resolved" export with 200+ columns.
  2. Roadmaps CSV  — "Advanced Roadmaps" export with 26 columns.

Both are optional, but at least the snapshot CSV is required for any metric.
The roadmaps CSV is joined by Issue key and unlocks plan-accuracy features.

Key quirks of the Jira export format handled here:
  - Duplicate column names (Labels ×2, Sprint ×5) — deduplicated / merged.
  - Compound sprint field: "PMD_26PI1_Sprint1 [COMPLETED] + Sprint2 ..."
  - Date format: "08/May/26 9:21 AM" → parsed with configurable strptime.
  - Component/s used as squad key (Team field is numeric ID, unusable).
  - Blocked field may contain "Impediment" as the truthy value.

Public API
~~~~~~~~~~
  load_snapshot(path, config)                → pd.DataFrame
  load_roadmaps(path, config)                → pd.DataFrame
  merge_datasets(snapshot_df, roadmaps_df)   → pd.DataFrame
  apply_filters(df, config, squads, types,
                date_from, date_to)          → pd.DataFrame, DataQualityReport
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Sequence

import pandas as pd

from config.schema import AppConfig
from core.models import DataQualityReport

log = logging.getLogger(__name__)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _safe_parse_dates(series: pd.Series, fmt: str) -> pd.Series:
    """
    Parse a string series to datetime, trying the configured format first,
    then falling back to pandas inference.  Returns NaT for unparseable values.
    """
    parsed = pd.to_datetime(series, format=fmt, errors="coerce")
    # Count how many failed
    n_failed = parsed.isna().sum() - series.isna().sum()
    if n_failed > 0:
        log.debug("Date parse: %d values did not match format '%s', trying inference.", n_failed, fmt)
        fallback = pd.to_datetime(series, errors="coerce", dayfirst=True)
        parsed = parsed.fillna(fallback)
    return parsed


def _deduplicate_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Jira exports duplicate column names (e.g. Labels, Sprint).
    When pandas reads a CSV with duplicates it auto-renames them as
    ``Column``, ``Column.1``, ``Column.2``, etc.  This function detects
    both true duplicates and the pandas ``.N`` suffix pattern and merges
    each group according to column type:

      - Labels columns: concatenate all non-null values, comma-separated.
      - Sprint columns: take the last non-null value (most recent sprint).
      - All other duplicates: take the first non-null occurrence.
    """
    import re

    # Build a mapping: base_name → [all column names that belong to it]
    # Handles both true pandas duplicates AND the `.1`, `.2` suffix pattern.
    groups: dict[str, list[str]] = {}
    for col in df.columns:
        # Strip trailing ".N" suffix produced by pandas duplicate handling
        base = re.sub(r"\.\d+$", "", col)
        groups.setdefault(base, []).append(col)

    # Only process groups that actually have more than one column
    needs_merge = {base: cols for base, cols in groups.items() if len(cols) > 1}
    if not needs_merge:
        return df

    result = df.copy()

    for base_name, dup_cols in needs_merge.items():
        if "label" in base_name.lower():
            merged = result[dup_cols].apply(
                lambda row: ", ".join(
                    v for v in row.dropna().astype(str) if v.strip()
                ),
                axis=1,
            )
        elif "sprint" in base_name.lower():
            # Join ALL non-null sprint columns with " + " so that sprint history
            # is preserved.  Jira emits one column per sprint the item appeared in
            # (Sprint, Sprint.1, Sprint.2 …).  Taking only the last value would
            # discard the earlier sprints and break slippage detection.
            merged = result[dup_cols].apply(
                lambda row: " + ".join(
                    str(v).strip()
                    for v in row.dropna().tolist()
                    if str(v).strip()
                ) or None,
                axis=1,
            )
        elif "component" in base_name.lower():
            # Last non-null wins for Component/s.
            # Jira exports the parent/product component first (e.g. "Perception MLO")
            # and the team-specific sub-component last (e.g. "PMD SW Dev").
            # Taking the last non-null gives the most specific value and correctly
            # differentiates squads that share a common parent component.
            merged = result[dup_cols].apply(
                lambda row: next(
                    (v for v in reversed(row.dropna().tolist()) if str(v).strip()),
                    None,
                ),
                axis=1,
            )
        else:
            # First non-null
            merged = result[dup_cols].bfill(axis=1).iloc[:, 0]

        result[base_name] = merged
        result.drop(
            columns=[c for c in dup_cols if c != base_name],
            inplace=True,
            errors="ignore",
        )

    return result


def _parse_last_completed_sprint(sprint_str: str | None) -> str:
    """
    Extract the last completed sprint name from a compound sprint string.

    Example input:
        "PMD_26PI1_Sprint1 [COMPLETED] + Sprint2 [COMPLETED] + Sprint3"
    Returns:
        "Sprint2"  (last one with [COMPLETED])
    If no COMPLETED sprint found, returns the full string stripped, or "".
    """
    if not sprint_str or not isinstance(sprint_str, str):
        return ""
    parts = [p.strip() for p in sprint_str.split("+")]
    completed = [p for p in parts if "[COMPLETED]" in p.upper()]
    if completed:
        last = completed[-1]
        return re.sub(r"\s*\[COMPLETED\]\s*", "", last, flags=re.IGNORECASE).strip()
    # No COMPLETED tag — return last part (active sprint)
    return parts[-1].replace("[ACTIVE]", "").replace("[FUTURE]", "").strip() if parts else ""


def _parse_first_sprint(sprint_str: str | None) -> str:
    """Extract the first sprint name from a compound sprint string."""
    if not sprint_str or not isinstance(sprint_str, str):
        return ""
    parts = [p.strip() for p in sprint_str.split("+")]
    return (
        parts[0]
        .replace("[COMPLETED]", "")
        .replace("[ACTIVE]", "")
        .replace("[FUTURE]", "")
        .strip()
    )


def _normalise_squad_series(series: pd.Series) -> pd.Series:
    """
    Jira sometimes exports the Components field as a comma-separated list
    when an item is tagged with multiple components (e.g. "PMV SW Dev, PMV_SW").
    This function normalises the series so every cell contains a single squad
    name by:

      1. Splitting each cell on commas to get individual component values.
      2. Finding the most common individual value across the whole series —
         this is the canonical squad/team name (e.g. "PMV SW Dev").
      3. For each cell, returning the canonical value if it is present in
         the cell's components; otherwise returning the first component.

    This handles all three real-world patterns seen in Jira exports:
        "PMV SW Dev"               → "PMV SW Dev"
        "PMV SW Dev, PMV_SW"       → "PMV SW Dev"
        "PMV_SW, TMA, PMV SW Dev"  → "PMV SW Dev"
    """
    from collections import Counter

    # Collect all individual component values to find the canonical one
    all_values: list[str] = []
    for cell in series.dropna():
        all_values.extend(v.strip() for v in str(cell).split(",") if v.strip())

    if not all_values:
        return series

    canonical = Counter(all_values).most_common(1)[0][0]

    def _pick(cell: str | float) -> str | None:
        if pd.isna(cell) or not str(cell).strip():
            return None
        parts = [v.strip() for v in str(cell).split(",") if v.strip()]
        if canonical in parts:
            return canonical
        return parts[0] if parts else None

    return series.apply(_pick)


def _normalise_blocked(series: pd.Series) -> pd.Series:
    """
    Blocked field may contain 'Impediment', 'Yes', 'True', or be empty.
    Return bool Series.
    """
    truthy = {"impediment", "yes", "true", "1", "blocked"}
    return series.fillna("").astype(str).str.strip().str.lower().isin(truthy)


# ── Public API ────────────────────────────────────────────────────────────────

def load_snapshot(path: str | Path, config: AppConfig) -> pd.DataFrame:
    """
    Load the Jira 'Created vs Resolved' snapshot CSV.

    Returns a DataFrame with normalised column names:
        key, title, type, status, squad, created, resolved,
        labels, story_points, blocked, flagged, age_jira,
        sprint_raw, sprint_first, sprint_last_completed,
        epic_link
    """
    path = Path(path)
    log.info("Loading snapshot CSV: %s", path)

    raw = pd.read_csv(path, dtype=str, low_memory=False)
    log.info("  Raw shape: %s rows × %s columns", *raw.shape)

    raw = _deduplicate_columns(raw)
    log.info("  Shape after deduplication: %s rows × %s columns", *raw.shape)

    col = config.columns  # shorthand

    def _get(col_name: str, default: str = "") -> pd.Series:
        if col_name in raw.columns:
            return raw[col_name]
        log.warning("  Column '%s' not found in CSV — filling with empty string.", col_name)
        return pd.Series([""] * len(raw), index=raw.index)

    sprint_raw = _get(col.get("sprint", "Sprint"))

    df = pd.DataFrame({
        "key":          _get(col["id"]),
        "title":        _get(col["title"]),
        "type":         _get(col["type"]),
        "status":       _get(col["status"]),
        "squad":        _get(col["squad"]),
        "labels":       _get(col.get("labels", "Labels")),
        "story_points": _get(col.get("story_points", "Custom field (Story Points)")),
        "blocked_raw":  _get(col.get("blocked", "Custom field (Blocked)")),
        "flagged_raw":  _get(col.get("flagged", "Custom field (Flagged)")),
        "age_jira":     _get(col.get("age", "Custom field (Age)")),
        "sprint_raw":   sprint_raw,
        "epic_link":    _get(col.get("epic_link", "Custom field (Epic Link)")),
    })

    # Parse dates
    df["created"]  = _safe_parse_dates(_get(col["created"]),  config.date_format)
    df["resolved"] = _safe_parse_dates(_get(col["resolved"]), config.date_format)

    # Derived sprint columns
    df["sprint_first"]            = df["sprint_raw"].apply(_parse_first_sprint)
    df["sprint_last_completed"]   = df["sprint_raw"].apply(_parse_last_completed_sprint)

    # Boolean flags
    df["is_blocked"] = _normalise_blocked(df["blocked_raw"])
    df["is_flagged"] = (
        df["flagged_raw"].fillna("").astype(str).str.strip().str.lower()
        .isin({"impediment", "yes", "true", "1", "flagged"})
    )

    # Numeric story points (may be empty)
    df["story_points"] = pd.to_numeric(df["story_points"], errors="coerce")

    # Strip leading/trailing whitespace from string columns
    for col_name in ("key", "title", "type", "status", "squad", "labels"):
        df[col_name] = df[col_name].astype(str).str.strip()

    log.info("  Loaded %d rows from snapshot.", len(df))
    return df


def load_roadmaps(path: str | Path, config: AppConfig) -> pd.DataFrame:
    """
    Load the Jira Advanced Roadmaps CSV.

    Returns a DataFrame with normalised column names keyed by
    config.roadmaps_columns, plus:
        key, hierarchy, target_start, target_end, progress_pct,
        progress_done_sp, progress_rem_sp, done_ic, total_ic, rag
    """
    path = Path(path)
    log.info("Loading roadmaps CSV: %s", path)

    raw = pd.read_csv(path, dtype=str, low_memory=False)
    log.info("  Raw shape: %s rows × %s columns", *raw.shape)

    rcol = config.roadmaps_columns
    date_fmt = config.date_format

    def _get(col_name: str, *fallbacks: str) -> pd.Series:
        """Return the first column that exists in raw, or an empty Series."""
        for name in (col_name, *fallbacks):
            if name in raw.columns:
                return raw[name]
        log.warning("  Roadmaps column '%s' not found.", col_name)
        return pd.Series([""] * len(raw), index=raw.index)

    df = pd.DataFrame({
        "key":              _get(rcol.get("id", "Issue key")),
        "hierarchy":        _get(rcol.get("hierarchy", "Hierarchy")),
        "rm_squad":         _get(rcol.get("squad", "Components")),
        "rm_target_start":  pd.to_datetime(
                                _get(rcol.get("target_start", "Target start date")),
                                errors="coerce", dayfirst=True, format="mixed"),
        "rm_target_end":    pd.to_datetime(
                                _get(rcol.get("target_end", "Target end date")),
                                errors="coerce", dayfirst=True, format="mixed"),
        "rm_progress_pct":  pd.to_numeric(
                                _get(rcol.get("progress_pct", "Progress (%)")),
                                errors="coerce"),
        # Accept either story-points or hours column names — Advanced Roadmaps
        # exports vary depending on whether SP or time-tracking is configured.
        "rm_done_sp":       pd.to_numeric(
                                _get(rcol.get("progress_done_sp", "Progress completed (sp)"),
                                     "Progress completed (h)"),
                                errors="coerce"),
        "rm_rem_sp":        pd.to_numeric(
                                _get(rcol.get("progress_rem_sp", "Progress remaining (sp)"),
                                     "Progress remaining (h)"),
                                errors="coerce"),
        "rm_done_ic":       pd.to_numeric(
                                _get(rcol.get("done_ic", "Done IC")),
                                errors="coerce"),
        "rm_total_ic":      pd.to_numeric(
                                _get(rcol.get("total_ic", "Total IC")),
                                errors="coerce"),
        "rm_rag":           _get(rcol.get("rag", "RAG")),
    })

    df["key"]      = df["key"].astype(str).str.strip()
    df["rm_squad"] = _normalise_squad_series(df["rm_squad"])
    log.info("  Loaded %d rows from roadmaps.", len(df))
    return df


# ── Candidate target-date column names in a regular Jira snapshot export ──────
# Jira allows many custom field names for "target end date" depending on how
# the project is configured.  We try them in priority order.
_SNAPSHOT_TARGET_END_CANDIDATES = [
    "Custom field (Target end)",
    "Custom field (Target End Date)",
    "Custom field (Target Release Date)",
    "Custom field (End Date)",
    "Due Date",
]


def load_for_drift(path: str | Path, config: AppConfig) -> pd.DataFrame:
    """
    Load any Jira CSV export — either a regular snapshot or an Advanced
    Roadmaps export — and return a normalised DataFrame suitable for drift
    comparison with ``date_drift_summary``.

    Output columns: key, rm_target_end, hierarchy, rm_squad
    (same schema as ``load_roadmaps`` so existing drift logic is reused).

    Auto-detection logic
    --------------------
    If the file contains a ``Target end date`` column (the canonical roadmaps
    column) OR a ``Hierarchy`` column, it is loaded via ``load_roadmaps``.
    Otherwise it is treated as a snapshot CSV and the first matching column
    from ``_SNAPSHOT_TARGET_END_CANDIDATES`` is used as the target date.

    Raises ``ValueError`` if no usable target-date column is found.
    """
    path = Path(path)
    raw  = pd.read_csv(path, dtype=str, low_memory=False, nrows=5)  # peek at columns
    cols = set(raw.columns)

    # ── Roadmaps format ────────────────────────────────────────────────────────
    if "Target end date" in cols or "Hierarchy" in cols:
        log.info("load_for_drift: detected roadmaps format — %s", path.name)
        return load_roadmaps(path, config)

    # ── Snapshot format ───────────────────────────────────────────────────────
    target_col: str | None = None
    for candidate in _SNAPSHOT_TARGET_END_CANDIDATES:
        if candidate in cols:
            target_col = candidate
            break

    if target_col is None:
        # Try a broader re-read with all rows in case the peek missed something
        raw_full = pd.read_csv(path, dtype=str, low_memory=False)
        for candidate in _SNAPSHOT_TARGET_END_CANDIDATES:
            if candidate in raw_full.columns:
                target_col = candidate
                raw = raw_full
                break

    if target_col is None:
        raise ValueError(
            f"No target end date column found in '{path.name}'. "
            f"Expected one of: {_SNAPSHOT_TARGET_END_CANDIDATES} "
            f"(for a snapshot CSV) or 'Target end date' (for a Roadmaps CSV)."
        )

    log.info("load_for_drift: snapshot format, using '%s' as target date — %s",
             target_col, path.name)

    raw_full = pd.read_csv(path, dtype=str, low_memory=False)
    raw_dd   = _deduplicate_columns(raw_full)

    def _gcol(col_name: str, *fallbacks: str) -> pd.Series:
        for name in (col_name, *fallbacks):
            if name in raw_dd.columns:
                return raw_dd[name]
        return pd.Series([""] * len(raw_dd), index=raw_dd.index)

    # Squad: Component/s (last non-null after dedup, already handled by _deduplicate_columns)
    squad_col = config.columns.get("squad", "Component/s")

    df = pd.DataFrame({
        "key":          _gcol(config.columns.get("id", "Issue key")).astype(str).str.strip(),
        "hierarchy":    _gcol(config.columns.get("type", "Issue Type")),  # type as hierarchy proxy
        "rm_squad":     _gcol(squad_col),
        "rm_target_end": pd.to_datetime(
                             _gcol(target_col),
                             errors="coerce", dayfirst=True, format="mixed"),
    })

    n_with_date = df["rm_target_end"].notna().sum()
    log.info("  load_for_drift: %d rows, %d with target date.", len(df), n_with_date)
    df["rm_squad"] = _normalise_squad_series(df["rm_squad"])
    return df[["key", "hierarchy", "rm_squad", "rm_target_end"]]


def merge_datasets(
    snapshot_df: pd.DataFrame,
    roadmaps_df: pd.DataFrame | None,
) -> pd.DataFrame:
    """
    Left-join roadmaps data onto the snapshot on 'key'.
    Roadmaps columns are prefixed with 'rm_'.
    If roadmaps_df is None, the snapshot is returned unchanged.
    """
    if roadmaps_df is None or roadmaps_df.empty:
        return snapshot_df

    merged = snapshot_df.merge(
        roadmaps_df.drop_duplicates(subset=["key"]),
        on="key",
        how="left",
        suffixes=("", "_rm"),
    )
    log.info(
        "  Merged: %d snapshot rows, %d roadmaps rows → %d merged rows.",
        len(snapshot_df), len(roadmaps_df), len(merged),
    )
    return merged


def apply_filters(
    df: pd.DataFrame,
    config: AppConfig,
    squads: Sequence[str] | None = None,
    item_types: Sequence[str] | None = None,
    date_from: "pd.Timestamp | None" = None,
    date_to:   "pd.Timestamp | None" = None,
) -> tuple[pd.DataFrame, DataQualityReport]:
    """
    Apply work-item-type exclusion, squad filter, date range filter, and
    removed excluded workflow states.

    Returns
    -------
    (filtered_df, DataQualityReport)

    The report explains what was dropped and why so the UI can surface it.
    Items are *not* silently dropped — the report counts every exclusion reason.
    """
    total = len(df)
    exclusion_reasons: dict[str, int] = {}

    mask = pd.Series(True, index=df.index)

    # ── 1. Exclude by workflow state category ─────────────────────────────────
    excluded_states = config.excluded_states
    if excluded_states:
        state_mask = df["status"].isin(excluded_states)
        n = state_mask.sum()
        if n:
            exclusion_reasons[f"Excluded workflow state ({', '.join(excluded_states)})"] = int(n)
        mask &= ~state_mask

    # ── 2. Filter by work-item type ───────────────────────────────────────────
    # When the user has explicitly chosen types via the sidebar, their selection
    # is the only type filter — config include/exclude lists are ignored so
    # they can freely include Epics, Initiatives, etc. if they want.
    # Config-based lists only act as a fallback when no UI selection is present.
    if item_types is not None and len(item_types) > 0:
        type_ui_mask = df["type"].isin(item_types)
        n = (mask & ~type_ui_mask).sum()
        if n:
            excluded_types = sorted(set(df.loc[mask & ~type_ui_mask, "type"].tolist()))
            exclusion_reasons[f"Not selected type ({', '.join(excluded_types)})"] = int(n)
        mask &= type_ui_mask
    else:
        # No UI selection — apply config-based exclude list then include list
        if config.work_item_types_exclude:
            type_excl_mask = df["type"].isin(config.work_item_types_exclude)
            n = (mask & type_excl_mask).sum()
            if n:
                exclusion_reasons[f"Excluded item type ({', '.join(config.work_item_types_exclude)})"] = int(n)
            mask &= ~type_excl_mask

        if config.work_item_types_include:
            type_incl_mask = df["type"].isin(config.work_item_types_include)
            n = (mask & ~type_incl_mask).sum()
            if n:
                exclusion_reasons["Not in include list"] = int(n)
            mask &= type_incl_mask

    # ── 3. Squad filter ───────────────────────────────────────────────────────
    if squads and len(squads) > 0:
        squad_mask = df["squad"].isin(squads)
        n = (mask & ~squad_mask).sum()
        if n:
            exclusion_reasons["Not in selected squad(s)"] = int(n)
        mask &= squad_mask

    # ── 4. Date range filter (on created date) ────────────────────────────────
    if date_from is not None:
        date_mask = df["created"] >= pd.Timestamp(date_from)
        n = (mask & ~date_mask).sum()
        if n:
            exclusion_reasons["Created before date range"] = int(n)
        mask &= date_mask

    if date_to is not None:
        date_mask = df["created"] <= pd.Timestamp(date_to)
        n = (mask & ~date_mask).sum()
        if n:
            exclusion_reasons["Created after date range"] = int(n)
        mask &= date_mask

    filtered = df[mask].copy()

    # ── Build quality report ─────────────────────────────────────────────────
    has_created  = filtered["created"].notna().sum()
    has_resolved = filtered["resolved"].notna().sum()
    has_both     = (filtered["created"].notna() & filtered["resolved"].notna()).sum()

    # Warn on implausible cycle times (negative or > 365 days)
    if has_both:
        ct = (filtered["resolved"] - filtered["created"]).dt.total_seconds() / 86400
        n_negative = (ct < 0).sum()
        n_long     = (ct > 365).sum()
        if n_negative:
            exclusion_reasons["Negative cycle time (resolved before created)"] = int(n_negative)
        if n_long:
            log.warning("  %d items have cycle time > 365 days — not excluded but flagged.", n_long)

    has_blocked = 0
    if "is_blocked" in filtered.columns:
        has_blocked = int(filtered["is_blocked"].sum())

    has_target_end = 0
    if "rm_target_end" in filtered.columns:
        has_target_end = int(filtered["rm_target_end"].notna().sum())

    report = DataQualityReport(
        total_rows_read=total,
        rows_accepted=int(mask.sum()),
        rows_excluded=int((~mask).sum()),
        exclusion_reasons=exclusion_reasons,
        has_resolved=int(has_resolved),
        has_created=int(has_created),
        has_both_dates=int(has_both),
        has_blocked_flag=has_blocked,
        has_target_end=has_target_end,
    )

    log.info(
        "  Filter result: %d accepted, %d excluded from %d total.",
        report.rows_accepted, report.rows_excluded, report.total_rows_read,
    )
    return filtered, report

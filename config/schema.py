"""
config/schema.py
~~~~~~~~~~~~~~~~
Validates the YAML config dict and provides typed access to every section.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


# ── Defaults ──────────────────────────────────────────────────────────────────
_DEFAULT_CONFIG_PATH = Path(__file__).parent / "default_config.yaml"

_REQUIRED_COLUMN_KEYS = {"id", "title", "type", "status", "created", "resolved"}


# ── Data classes ──────────────────────────────────────────────────────────────
@dataclass
class WorkflowState:
    name: str
    category: str          # "queue" | "active" | "done" | "excluded"
    start: bool = False    # cycle-time start marker
    end: bool = False      # cycle-time end marker

    def __post_init__(self) -> None:
        valid = {"queue", "active", "done", "excluded"}
        if self.category not in valid:
            raise ValueError(
                f"Workflow state '{self.name}': category must be one of {valid}, "
                f"got '{self.category}'."
            )


@dataclass
class MonteCarloConfig:
    default_window_weeks: int = 12
    n_simulations: int = 10_000
    confidence_levels: list[int] = field(default_factory=lambda: [50, 70, 85, 95])


@dataclass
class AppConfig:
    # raw dict for downstream use
    columns: dict[str, str]
    roadmaps_columns: dict[str, str]
    date_format: str
    work_item_types_include: list[str]
    work_item_types_exclude: list[str]
    workflow_states: list[WorkflowState]
    wip_limits: dict[str, int]
    squad_capacity_pct: int
    monte_carlo: MonteCarloConfig
    palette: list[str]

    # convenience
    @property
    def start_states(self) -> list[str]:
        return [s.name for s in self.workflow_states if s.start]

    @property
    def end_states(self) -> list[str]:
        return [s.name for s in self.workflow_states if s.end]

    @property
    def done_states(self) -> list[str]:
        return [s.name for s in self.workflow_states if s.category == "done"]

    @property
    def excluded_states(self) -> list[str]:
        return [s.name for s in self.workflow_states if s.category == "excluded"]

    @property
    def active_states(self) -> list[str]:
        return [s.name for s in self.workflow_states if s.category in ("active", "queue")]

    @property
    def state_order(self) -> list[str]:
        """States in workflow sequence (excludes 'excluded' category)."""
        return [s.name for s in self.workflow_states if s.category != "excluded"]


# ── Loader / validator ────────────────────────────────────────────────────────

def load_config(path: str | Path | None = None) -> AppConfig:
    """
    Load and validate a YAML config file.  If *path* is None the bundled
    ``default_config.yaml`` is used.  Raises ``ValueError`` with a descriptive
    message on any validation failure.
    """
    resolved = Path(path) if path else _DEFAULT_CONFIG_PATH
    if not resolved.exists():
        raise FileNotFoundError(f"Config file not found: {resolved}")

    with resolved.open(encoding="utf-8") as fh:
        raw: dict[str, Any] = yaml.safe_load(fh)

    return _parse(raw)


def load_config_from_dict(raw: dict[str, Any]) -> AppConfig:
    """Parse a partial config dict, merging with defaults for any missing keys.

    This allows users to upload a minimal YAML (e.g. just wip_limits) without
    having to repeat all the column mappings from the default config.
    """
    import copy
    with _DEFAULT_CONFIG_PATH.open(encoding="utf-8") as fh:
        defaults: dict[str, Any] = yaml.safe_load(fh)

    def _deep_merge(base: dict, override: dict) -> dict:
        result = copy.deepcopy(base)
        for k, v in override.items():
            if isinstance(v, dict) and isinstance(result.get(k), dict):
                result[k] = _deep_merge(result[k], v)
            else:
                result[k] = v
        return result

    merged = _deep_merge(defaults, raw)
    return _parse(merged)


def _parse(raw: dict[str, Any]) -> AppConfig:
    # ── columns ──────────────────────────────────────────────────────────────
    cols = raw.get("columns", {})
    missing = _REQUIRED_COLUMN_KEYS - set(cols.keys())
    if missing:
        raise ValueError(f"Config missing required column keys: {missing}")

    # ── roadmaps columns (optional) ──────────────────────────────────────────
    roadmaps_cols = raw.get("roadmaps_columns", {})

    # ── date format ──────────────────────────────────────────────────────────
    date_fmt = raw.get("date_format", "%d/%b/%y %I:%M %p")

    # ── work item types ──────────────────────────────────────────────────────
    wit = raw.get("work_item_types", {})
    include_types = [str(t) for t in wit.get("include", [])]
    exclude_types = [str(t) for t in wit.get("exclude", [])]

    # ── workflow ──────────────────────────────────────────────────────────────
    raw_states = raw.get("workflow", {}).get("states", [])
    states = [WorkflowState(**s) for s in raw_states]
    if not any(s.end for s in states):
        raise ValueError("Workflow config must define at least one state with end: true.")

    # ── WIP limits ────────────────────────────────────────────────────────────
    wip = {str(k): int(v) for k, v in raw.get("wip_limits", {}).items()}

    # ── capacity ──────────────────────────────────────────────────────────────
    capacity = int(raw.get("squad_capacity_pct", 80))
    if not (1 <= capacity <= 100):
        raise ValueError(f"squad_capacity_pct must be 1–100, got {capacity}.")

    # ── Monte Carlo ───────────────────────────────────────────────────────────
    mc_raw = raw.get("monte_carlo", {})
    mc = MonteCarloConfig(
        default_window_weeks=int(mc_raw.get("default_window_weeks", 12)),
        n_simulations=int(str(mc_raw.get("n_simulations", 10_000)).replace("_", "")),
        confidence_levels=[int(c) for c in mc_raw.get("confidence_levels", [50, 70, 85, 95])],
    )

    # ── palette ───────────────────────────────────────────────────────────────
    palette = [str(c) for c in raw.get("palette", [])]
    if not palette:
        # Okabe–Ito fallback
        palette = ["#E69F00", "#56B4E9", "#009E73", "#F0E442",
                   "#0072B2", "#D55E00", "#CC79A7", "#000000"]

    return AppConfig(
        columns=cols,
        roadmaps_columns=roadmaps_cols,
        date_format=date_fmt,
        work_item_types_include=include_types,
        work_item_types_exclude=exclude_types,
        workflow_states=states,
        wip_limits=wip,
        squad_capacity_pct=capacity,
        monte_carlo=mc,
        palette=palette,
    )

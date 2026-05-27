# Squad Flow Metrics

A local-web dashboard for flow-based analytics across one or more Agile squads.
Built on [Actionable Agile / Vacanti](https://actionableagile.com/) principles —
throughput and cycle time, not story-point velocity.

![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue)
![Streamlit](https://img.shields.io/badge/UI-Streamlit-red)
![Tests](https://img.shields.io/badge/tests-81%20passing-brightgreen)
![Coverage](https://img.shields.io/badge/coverage-87%25-green)

---

## What it does

| Tab | What you get |
|-----|-------------|
| **Overview** | Headline KPIs + auto-generated plain-English commentary |
| **Cycle Time** | Scatterplot with configurable p50/70/85/95 percentile lines |
| **Throughput** | Weekly run chart + histogram of throughput distribution |
| **Ageing WIP** | In-flight items vs historical cycle-time percentile reference lines |
| **Forecasts** | Monte Carlo *How Many?* and *When?* — probabilistic, not velocity-based |
| **Constraints** | Bottleneck signals from age-by-state and blocked-item analysis, with plain-English Theory of Constraints guidance |
| **Plan Accuracy** | Target end date vs actual, sprint slippage *(requires Roadmaps CSV)* |
| **Compare Squads** | Side-by-side small-multiples — diagnostic, not a league table |
| **Data Quality** | Exclusion log, scored data readiness (0–100) with per-component breakdown and plain-English verdict |
| **Export** | Download filtered data as CSV, full HTML report, or individual chart PNGs |

> **No story points. No velocity. No estimates.**
> Forecasts sample from your team's actual historical throughput distribution
> using Monte Carlo simulation.

---

## Download (Windows — no Python required)

> **Just want to run it on Windows?**
> Go to the [**Releases page**](https://github.com/markcocoscopas/squad-flow-metrics/releases/latest),
> download the **Setup.exe** installer, and run it. No Python, no admin rights, no setup.
> Launch from the Start Menu shortcut afterwards.
> Close the app (black command window) before installing an upgrade.

---

## Quick start (developers)

### macOS / Linux

```bash
git clone https://github.com/markcocoscopas/squad-flow-metrics.git
cd squad-flow-metrics
./run.sh
```

### Windows

> **Before you start:** Make sure Python 3.9+ is installed from
> [python.org](https://www.python.org/downloads/). During installation,
> tick **"Add Python to PATH"** — without this, the launcher cannot find Python.

```
git clone https://github.com/markcocoscopas/squad-flow-metrics.git
cd squad-flow-metrics
run.bat
```

Or double-click `run.bat` in File Explorer.

The launcher creates a virtual environment, installs all dependencies, and
opens the app at **http://localhost:8501**. On first run this takes about
30–60 seconds; subsequent launches are instant.

> **Windows — first launch after installing:** Windows Defender scans the
> bundled Python files the very first time they run. This can take **up to
> 10–15 minutes** before the browser page loads. This is a one-time delay —
> every subsequent launch is fast. Do not close the black command window
> while you are waiting.

> **PDF export on Windows:** the HTML report exports fine on all platforms.
> PDF export additionally needs [WeasyPrint system libraries (GTK3)](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html),
> which are complex to install on Windows. HTML is the recommended format
> for sharing with colleagues.

---

## Manual setup (if you prefer)

```bash
# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

```bat
:: Windows (Command Prompt)
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

**Requirements:** Python 3.9 or later. No other system dependencies needed
for all core features and HTML export.

---

## Loading your data

### Option 1 — Sample data (no Jira required)

Click **"Load sample data"** in the sidebar. This loads a synthetic dataset
of three squads over 26 weeks with deliberately different flow signatures
(healthy, Code-Review bottleneck, high-blocker), so every feature can be
explored immediately.

### Option 2 — Your Jira export

1. In Jira, go to **Issues → Search for issues → Export → Export to CSV (all fields)**.

2. Use a JQL filter that includes **both in-flight and completed** items — do not
   filter by `status = Done` or add a `Resolved >=` clause, or your WIP and Ageing
   WIP tabs will be empty. A good starting point:

   ```
   project = "YOUR_PROJECT"
   AND component = "Your Squad Name"
   AND issuetype in (Story, Bug, Task, Spike, "Sub-task")
   AND created >= startOfMonth(-6)
   ORDER BY created DESC
   ```

   For **multiple squads**, either use a broader component filter or export one CSV
   per squad and upload them all together — the app merges them automatically.

   ```
   project = "YOUR_PROJECT"
   AND component in ("Squad A", "Squad B", "Squad C")
   AND issuetype in (Story, Bug, Task, Spike, "Sub-task")
   AND created >= startOfMonth(-6)
   ORDER BY created DESC
   ```

3. *(Optional)* Export the **Advanced Roadmaps** plan view to unlock Plan Accuracy
   and Sprint Slippage tabs. One file per squad is fine — upload them all together.

4. Upload your files via the sidebar uploaders.

**The one thing to check:** the app uses the **Component/s** field as the squad
identifier. Make sure your issues have Component/s populated. If your squad name
lives in a different field (e.g. a custom Team field or a label), update
`config/default_config.yaml` — change `squad: "Component/s"` to match your field name.

> **Data stays local.** The app runs entirely offline. Nothing is sent anywhere.

---

## Custom configuration

The default config (`config/default_config.yaml`) is pre-set for the standard
Jira export format. If your Jira instance uses different field names, workflow
states, or WIP limits, create a custom YAML and upload it via the **⚙️ Configuration**
uploader in the sidebar. You only need to include the sections you want to override —
everything else falls back to the defaults.

### Common customisations

#### 1 — Squad lives in a different field

```yaml
columns:
  id:       "Issue key"
  title:    "Summary"
  type:     "Issue Type"
  status:   "Status"
  created:  "Created"
  resolved: "Resolved"
  squad:    "Custom field (Team)"   # ← change to whatever field holds your squad name
```

#### 2 — Different workflow states (including backlog exclusion)

States with `category: "excluded"` are filtered out of WIP, Ageing WIP, and
Constraints entirely. Use this for backlog/waiting-area states that aren't truly
in-flight. `category: "queue"` keeps them visible in WIP counts.

```yaml
workflow:
  states:
    - {name: "Backlog",      category: "excluded", start: false, end: false}  # waiting area
    - {name: "Funnel",       category: "excluded", start: false, end: false}  # waiting area
    - {name: "To Do",        category: "excluded", start: false, end: false}  # pre-work queue — not a flow constraint
    - {name: "In Progress",  category: "active",   start: true,  end: false}  # cycle time starts here
    - {name: "In Review",    category: "active",   start: false, end: false}
    - {name: "Blocked",      category: "queue",    start: false, end: false}
    - {name: "Done",         category: "done",     start: false, end: true}   # cycle time ends here
    - {name: "Cancelled",    category: "excluded", start: false, end: false}
```

#### 3 — WIP limits

```yaml
wip_limits:
  "In Progress": 4
  "In Review":   3
  "Blocked":     1
```

#### 4 — Full example (copy, edit, and upload via the sidebar)

```yaml
# my-squad-config.yaml
# Upload via: sidebar ▸ ⚙️ Configuration ▸ Custom config YAML

columns:
  id:           "Issue key"
  title:        "Summary"
  type:         "Issue Type"
  status:       "Status"
  created:      "Created"
  resolved:     "Resolved"
  squad:        "Component/s"          # or "Custom field (Team)" etc.
  story_points: "Custom field (Story Points)"
  blocked:      "Custom field (Blocked)"
  flagged:      "Custom field (Flagged)"
  sprint:       "Sprint"

date_format: "%d/%b/%y %I:%M %p"      # e.g. 08/May/26 9:21 AM — adjust if your dates look different

work_item_types:
  include: [Story, Bug, Task, Spike, Sub-task]
  exclude: [Epic, Initiative, Theme]

workflow:
  states:
    - {name: "Backlog",      category: "excluded", start: false, end: false}
    - {name: "To Do",        category: "excluded", start: false, end: false}  # pre-work queue
    - {name: "In Progress",  category: "active",   start: true,  end: false}
    - {name: "In Review",    category: "active",   start: false, end: false}
    - {name: "Blocked",      category: "queue",    start: false, end: false}
    - {name: "Done",         category: "done",     start: false, end: true}
    - {name: "Cancelled",    category: "excluded", start: false, end: false}

wip_limits:
  "In Progress": 4
  "In Review":   3
  "Blocked":     1

squad_capacity_pct: 80

monte_carlo:
  default_window_weeks: 12
  n_simulations: 10_000
  confidence_levels: [50, 70, 85, 95]
```

---

## Architecture

```
squad_flow_metrics/
├── app.py                    # Streamlit entry point (wiring only, no logic)
├── config/
│   ├── default_config.yaml   # Column mapping, workflow states, WIP limits
│   └── schema.py             # Config validation
├── core/                     # Pure-function analytics (no UI imports)
│   ├── ingest.py             # CSV loading, deduplication, date parsing, join
│   ├── metrics.py            # Cycle time, throughput, WIP, ageing WIP
│   ├── monte_carlo.py        # Vectorised MC engine (How Many / When)
│   ├── constraints.py        # Bottleneck analysis
│   ├── plan_accuracy.py      # Plan accuracy, sprint slippage
│   ├── data_quality.py       # Exclusion log formatting, quality score
│   └── models.py             # Typed result dataclasses
├── ui/                       # Streamlit tabs (thin — composition only)
│   ├── sidebar.py
│   ├── charts.py             # Shared Plotly chart builders
│   ├── export.py             # Export tab: CSV, HTML report, per-chart PNG
│   └── ...one file per tab
├── reports/
│   ├── renderer.py           # HTML/PDF report pipeline
│   └── templates/            # Jinja2 templates
├── data/sample/              # Synthetic sample dataset (3 squads, 26 weeks)
└── tests/                    # pytest — 81 tests, 87% coverage on core/
```

The `core/` layer is pure Python with no Streamlit dependency. The same engine
can be wrapped in a CLI or a scheduled job without changing any analytics code.

---

## Exporting results

The **📥 Export** tab gives you three ways to share your analysis:

### Full HTML report
Select a squad (or "All squads") and click **Generate & download HTML report**.
The file is completely self-contained — all charts are interactive Plotly divs
embedded inside a single `.html` file. It can be:
- Opened in any browser with no internet connection
- Emailed to colleagues who don't have the app installed
- Saved as PDF via browser **Print → Save as PDF** (no extra software needed)

The report includes every metric: KPIs, cycle time, throughput, ageing WIP,
Monte Carlo forecasts, constraint analysis, plan accuracy, and data quality.

### Filtered data CSV
Click **Download filtered data as CSV** to export whatever is currently showing
on screen — including the calculated `cycle_time_days` column — ready for
Excel, Google Sheets, or further analysis.

### Per-chart PNG
Every chart has a **📷 camera icon** in the top-right hover toolbar (visible
when you move your mouse over a chart). Clicking it downloads that chart as a
PNG image — handy for PowerPoint slides, Teams messages, or Confluence pages.

> **PDF export note:** WeasyPrint (a library that converts HTML to PDF directly)
> requires complex system libraries on Windows (GTK3). The recommended approach
> is to use the HTML report and let your browser handle PDF conversion:
> open the `.html` file → Ctrl+P → **Save as PDF**.

---

## Running the tests

```bash
source .venv/bin/activate
pytest tests/ -v
pytest tests/ --cov=core --cov-report=term-missing   # with coverage
```

---

## What's not in v1 (Phase 2 roadmap)

| Feature | Why deferred |
|---------|-------------|
| **Cumulative Flow Diagram** | Requires per-item status-change history — not in the Jira CSV export. Available via `GET /rest/api/2/issue/{key}/changelog`. |
| **Flow Efficiency** | Same — needs time-in-active-state per item. |
| **State residency distributions** | Same. |
| **Jira API direct connection** | CSV ingest only in v1. API integration removes the manual export step. |
| **Dependency graph** | Cross-squad link data exists in the CSV; rendering a useful directed graph needs more work. |

---

## Guiding principles

- **Flow over velocity.** Story points are not used anywhere.
- **Probabilistic over deterministic.** Forecasts are distributions with
  percentiles, never single-point estimates.
- **Constraint-aware.** Every view is designed to help identify *where* the
  bottleneck sits, not just *whether* there is one.
- **Lower-bound honesty.** Cycle times are calendar days (Resolved − Created).
  This is a lower bound on true elapsed time, and this is surfaced explicitly
  in every chart that uses it.
- **Squad autonomy preserved.** The Compare Squads tab is diagnostic, not a
  performance ranking.

---

## Changelog

### v1.3.0
- **Ageing WIP chart — overlapping markers fixed** — items with identical ages in the same status column are now separated by a small deterministic horizontal jitter (fixed seed, so the chart is identical across reloads and screenshots). Markers are semi-transparent (55% opacity) with a contrasting dark stroke so any residual stacking is immediately visible. Hover shows issue key, status, type, age, and blocked/flagged flags. The counter row below the chart (in-flight, blocked, older-than-p85, older-than-p95) now reconciles exactly with the visible dots.

### v1.2.9
- **Blocked count fix (Overview)** — items in the **Blocked workflow state** were not being counted as blocked in the Overview and Ageing WIP tabs unless the custom Blocked field was also set. The `is_blocked` flag now reflects both sources (custom field OR workflow state = Blocked), consistent with the Constraints tab.

### v1.2.8
- **One-click in-app upgrade** — when a newer version is available, the sidebar shows an **⬆️ Upgrade now** button. Clicking it downloads only the source files (~1 MB) directly from GitHub, applies them in place, and prompts you to restart. The bundled Python runtime and dependencies are never re-downloaded, so upgrades are fast regardless of connection speed.

### v1.2.7
- **Sprint slippage fix (root cause)** — Jira exports each sprint an item was in as a separate column (`Sprint`, `Sprint.1`, `Sprint.2` …). The CSV loader was discarding all but the last one, so `sprint_first` always equalled `sprint_last_completed` and slippage appeared to be 0%. All sprint columns are now joined together so the full history is preserved and slippage is calculated correctly.

### v1.2.6
- **Sprint slippage reliability detection** — when Jira replaces the Sprint field rather than keeping compound sprint history, the slippage analysis now detects this (≥ 80% of items with identical planned/delivered sprint) and shows a plain-English warning explaining why the data is unreliable, instead of silently displaying a misleading "100% no-slip" result. The warning includes a note that reliable slippage data requires the Jira API changelog.

### v1.2.1
- **Plan Accuracy tab** — now has **Overall** and **By Squad** sub-tabs. The By Squad view shows a summary table and small-multiples scatter chart per squad side by side, including sprint slippage per squad
- **Multi-file upload** — both snapshot and roadmaps uploaders now accept multiple CSVs (one per squad). Files are merged and de-duplicated automatically
- **Filters** — squad and work-item type filters now default to everything in the loaded data. Explicit type selection bypasses config include/exclude lists entirely
- **Windows installer** — setup `.exe` replaces the zip as the recommended download. Installs to user profile (no admin needed), creates Start Menu shortcut, never triggers Defender after initial install
- **Date filter fix** — uploading a new CSV now resets the date range so stale session values can't hide rows

### v1.0.2
- **Export tab** — download filtered data as CSV, full self-contained HTML report (interactive charts, no internet required), or individual chart PNGs via Plotly's built-in camera icon
- **Constraints tab** — added plain-English Theory of Constraints explainer, box plot reading guide, and contextual captions on every section so the tab is useful without prior knowledge
- **Data Quality score** — now shows a plain-English verdict (Excellent / Good / Fair / Poor), one-line advice, and an expandable breakdown of all four scoring components so you know exactly what to fix
- **Blocked count fix** — the Ageing WIP "Blocked" metric now correctly counts items in the *Blocked workflow state* as well as items with the custom Blocked field set
- **Bug fix** — resolved Python 3.11 syntax error in the Export tab (backslash in f-string)

### v1.0.1
- Export tab added (CSV, HTML report, per-chart PNG)
- README updated with export documentation

### v1.0.0
- Initial release: Overview, Cycle Time, Throughput, Ageing WIP, Forecasts, Constraints, Plan Accuracy, Compare Squads, Data Quality

---

## Publishing a new Windows release

When you want to share a new version with colleagues:

```bash
git tag v1.0.2          # bump the number each time
git push origin v1.0.2
```

That's it. GitHub Actions will automatically:
1. Spin up a Windows build server
2. Bundle the app with a self-contained Python (no install needed)
3. Build a **Setup.exe installer** and a portable zip
4. Attach both to the Releases page with download instructions

The build takes about **5–8 minutes**. You can watch it under the
**Actions** tab on GitHub. When it turns green, the zip is ready to share.

Colleagues just need the link:
`https://github.com/markcocoscopas/squad-flow-metrics/releases/latest`

You can also trigger a test build at any time **without** creating a release
by going to **Actions → Build Windows Package → Run workflow**.

---

## Licence

MIT — see `LICENCE` file.

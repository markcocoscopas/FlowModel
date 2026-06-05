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
| **Plan Accuracy** | Target end date vs actual, sprint slippage, **Date Drift Analysis** *(requires Roadmaps or snapshot CSV)* |
| **Compare Squads** | Side-by-side small-multiples — diagnostic, not a league table |
| **Data Quality** | Exclusion log, scored data readiness (0–100) with per-component breakdown and plain-English verdict |
| **Export** | Download filtered data as CSV, full HTML report, or individual chart PNGs |

> **No story points. No velocity. No estimates.**
> Forecasts sample from your team's actual historical throughput distribution
> using Monte Carlo simulation.

---

## Download (Windows — no Python required)

> **Just want to run it on Windows?**
> Go to the [**Releases page**](https://github.com/markcocoscopas/FlowModel/releases/latest),
> download the **Setup.exe** installer, and run it. No Python, no admin rights, no setup.
> Launch from the Start Menu shortcut afterwards.
> Close the app (black command window) before installing an upgrade.

---

## Quick start (developers)

### macOS / Linux

```bash
git clone https://github.com/markcocoscopas/FlowModel.git
cd squad-flow-metrics
./run.sh
```

### Windows

> **Before you start:** Make sure Python 3.9+ is installed from
> [python.org](https://www.python.org/downloads/). During installation,
> tick **"Add Python to PATH"** — without this, the launcher cannot find Python.

```
git clone https://github.com/markcocoscopas/FlowModel.git
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

## Date Drift Analysis — how to use it

> **What is date drift?**
> When a story or epic reaches its target end date without being completed, teams often
> quietly extend the date rather than record a miss. Each individual extension seems
> small and reasonable in isolation — but when you aggregate across a whole programme
> over a PI, the cumulative "soft slip" can hide significant schedule risk that is
> invisible in standard status reports.

The **Plan Accuracy → Date Drift** tab compares Jira exports taken at different
times and shows exactly how much each item's target date has moved.

### What files do you need?

Any Jira export from the same project will work — the app auto-detects the format:

- **Advanced Roadmaps CSV** (exported from the Advanced Roadmaps plan view) — uses the
  `Target end date` column
- **Regular "Created vs Resolved" snapshot CSV** — uses `Custom field (Target end)`,
  `Custom field (Target End Date)`, `Custom field (End Date)`, or `Due Date`,
  whichever is populated in your project

You do **not** need an Advanced Roadmaps CSV.

**How to load data:**
- Upload the **current** (newest) export via the **sidebar** as usual
- Upload the **baseline** (older) export(s) inside the **Date Drift tab** itself

---

### Multi-squad support

If you have two or more scrum squads each with their own baseline, upload **all the
baseline CSVs at once** — the tab now accepts multiple files. The app:

1. Reads the `Components` (squad) field from each baseline file automatically
2. Matches each baseline to the corresponding squad's current data
3. Shows a **combined programme-level summary** (total items, total slip, worst item)
   followed by a **separate section per squad** with its own metrics, drift chart,
   and plain-English product owner summary

One shared **baseline export date** input covers all squads — on PI planning day,
all squads baseline at the same time.

**Example — two squads, PI planning day:**

```
Sidebar upload (current):    Advanced Roadmaps_PMV_SW_Dev_20260620.csv   ← merged roadmaps for all squads
                             Advanced Roadmaps_Perception_20260620.csv

Date Drift tab (baselines):  Advanced Roadmaps_PMV_SW_Dev_17062026.csv   ← PI planning day
                             Advanced Roadmaps_Perception_17062026.csv   ← PI planning day
```

The app pairs each baseline with its matching squad in the current data and shows drift side by side.

---

### Recommended workflow for PI-based programmes

#### On PI Planning day (your baseline)

Export the Roadmaps or snapshot CSV **at the end of PI Planning day**, once all target
dates have been committed by the teams — not mid-planning while dates are still in flux.
Save one file per squad with the date in the filename
(e.g. `Advanced Roadmaps_PMV_SW_Dev_17062026.csv`). These are your **baselines**.

> The app tries to parse the export date from the filename automatically. If the date
> is in `DDMMYYYY` format at the end of the filename (as Jira typically exports it),
> it will be pre-filled in the date input.

#### Every sprint thereafter

Export the same CSV(s) at the **end of each sprint** and save with the date in the
filename. Upload the latest exports as your current files (sidebar) and any older ones
as the baselines.

| Exports available | What you get |
|-------------------|-------------|
| 2 snapshots per squad (baseline + now) | Snapshot comparison — total drift, worst items, per-squad breakdown |
| 3+ snapshots | All of the above + **Drift Velocity** chart showing whether drift is accelerating or slowing |
| 5+ snapshots (full PI) | Reliable drift rate → **Adjusted Forecast** showing where items will *actually* land |

---

### The three views explained

#### 📸 Snapshot comparison
Compares each baseline against the current export. For each squad shows:
- How many items have drifted and by how much
- A colour-coded horizontal bar chart: 🔴 major (>30 d) · 🟠 moderate (8–30 d) · 🟡 minor (1–7 d) · 🔵 pulled in
- A plain-English paragraph ready to share with a product owner
- Combined hierarchy table (Capability / Epic / Story) across all squads

When multiple squads are loaded a **programme-level header** shows the combined
total before the per-squad detail sections.

> **Short measurement window warning:** if your two exports are fewer than 14 days apart,
> the *drift rate* figure (days of drift per calendar day) will look alarming — dividing
> any meaningful drift by 3 or 5 days produces a large number. In that case, focus on
> the **absolute numbers** (total slip, number of items, worst item) rather than the rate.
> The app flags this automatically with a warning banner.

#### 📈 Drift velocity
Upload 2 or more historic exports. The app plots how total drift has accumulated over
time as a dual-axis line chart:
- 🔴 Total drift days (left axis) — the cumulative cost
- 🟠 Items drifted (right axis) — how many items have moved at all

A **rising slope** means dates are being pushed out faster than work is completing.
A **flattening** means the programme is stabilising.
A **downward turn** means items are being de-scoped or genuinely pulled in.

This chart is most powerful in a PI retrospective — it shows the story of the entire
PI in one picture.

#### 🔮 Adjusted forecast
Once a reliable drift rate is established (needs at least 2–4 weeks of history),
this view projects how much *additional* drift each in-flight item is likely to
accumulate before reaching its target.

```
adjusted_target = current_target + (remaining_days × drift_rate)
```

The rate is auto-filled from the snapshot comparison but can be overridden manually.
Items in the top-right of the bubble chart (far from target date AND high expected drift)
are your highest-risk deliveries.

---

### What to tell your product owner

When presenting drift data, lead with the **absolute numbers**, not the rate:

> *"Since PI Planning, N items have had their target end dates quietly pushed out,
> adding up to X days of hidden slip. The worst single item moved Y days further out.
> The drift rate over the PI is Z days per week — at this rate, an item with 60 days
> remaining is likely to slip by a further [Z × 8.5] days before it lands."*

Then show the **drift bar chart** by item and the **by-squad table** to anchor the
conversation in specifics rather than abstractions.

Useful follow-up questions to bring to the team:
- Why did these items move — was the original date aspirational or committed?
- Is this the same set of items slipping sprint after sprint, or different ones each time?
- If it's the same items, what is the root cause (dependency, unclear requirements, lack of capacity)?

---

### What *good* looks like

| Signal | Interpretation |
|--------|---------------|
| 0 drift across all items | Dates were either very conservative, or de-scoping is happening silently |
| Small number of items with minor drift | Normal — some estimation variance is expected |
| Same items appearing in every sprint's drift | Systemic planning problem — those items need explicit risk management |
| Drift rate falling sprint-on-sprint | The team is stabilising and getting better at right-sizing targets |
| Drift rate rising sprint-on-sprint | Scope or complexity is increasing faster than capacity — escalate |

---

## Custom configuration

The default config (`config/default_config.yaml`) is pre-set for the standard
Jira export format. If your Jira instance uses different field names, workflow
states, or WIP limits, create a custom YAML and upload it via the **⚙️ Configuration**
uploader in the sidebar.

> **You only need to include the sections you want to override** — the app deep-merges
> your file on top of the defaults, so a one-line YAML with just `wip_limits` is
> perfectly valid. You do not need to repeat column names or workflow states if those
> haven't changed.

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

### v1.5.11
- **Partial custom config YAML** — uploading a minimal YAML (e.g. just `wip_limits`) no longer errors with "missing required column keys". The app now deep-merges the uploaded file on top of the defaults, so you only need to include the sections you want to change.

### v1.5.10
- **Done epics show delivery outcome, not "overdue"** — Epic/Capability Progress table now shows `✅ On time`, `🔴 Xd late`, or `🔵 Xd early` for completed items instead of comparing today's date against a past target end date.

### v1.5.9
- **Target end date read directly from snapshot CSV** — if your team sets target end dates on tickets as part of the Definition of Ready, the app now picks them up automatically from the snapshot export (`Custom field (Target end)`, `Custom field (Target End Date)`, `Custom field (Target Release Date)`, `Due Date` etc). Historical Accuracy now populates without needing an Advanced Roadmaps CSV for teams whose target dates live on the ticket itself.

### v1.5.8
- **Historical Accuracy diagnostics** — new "🔍 Why are so few items showing?" expander in the Plan Accuracy tab shows three counts: resolved items, items with a roadmap target date, and items with both. Includes plain-English guidance on the most common cause (Roadmaps exports hiding completed items).

### v1.5.7
- **Plan Accuracy minimum threshold** — Historical Accuracy stats are now hidden when fewer than 5 completed items have a target end date (showing a plain "not enough data yet" message instead of misleading percentages from 1–2 items). A raw detail expander still shows the underlying data.

### v1.5.6
- **In-flight ticket drill-down on Overview** — the "Current WIP by state" section now has a "📋 View in-flight tickets" expander listing every unresolved item with key, title, type, squad, status, and age in days, sorted oldest first.

### v1.5.5
- **Fix duplicate Plotly chart ID crash** — `StreamlitDuplicateElementId` error on the Plan Accuracy tab when multiple squads were loaded. All `plotly_chart` calls now have unique `key=` arguments.

### v1.5.4
- **Squad capacity (%) slider** — new slider in the sidebar under **🎲 Forecast Settings** scales throughput samples before Monte Carlo simulations. 80% means the team delivers at 80% of raw throughput (accounts for ceremonies, unplanned work, and overhead). Applies to all three forecast modes (How Many, When, Risk-Adjusted When). Info bar shows raw mean → adjusted mean.

### v1.5.3
- **GitHub repository renamed** to `FlowModel`. All internal update-check URLs updated accordingly. The in-app upgrade banner now correctly points to the new repo.

### v1.5.2
- **Squad view radio in sync with sidebar dropdown** — the squad selector at the top of the main view now uses the same threshold-filtered squad list as the sidebar multiselect, preventing product-area component names (e.g. `TMA`, `AIOP`) from appearing as squad options in one place but not the other.

### v1.5.1
- **Date Drift — multi-squad baseline comparison** — the Snapshot Comparison baseline uploader now accepts multiple files (one per squad). The app auto-detects each baseline's squad name from its `Components` column, matches it to the corresponding squad in the current data, shows a combined programme-level header, and renders a separate section per squad with its own metrics, drift chart, and plain-English summary.

### v1.5.0
- **Fix "undefined" chart title** — the Historical Accuracy scatter chart title rendered as the string "undefined" due to `title=None` in Plotly. Fixed by setting `title_text=""`.

### v1.4.9
- **Multi-value Components normalisation** — Jira sometimes stores multiple components as a comma-separated string (e.g. `"PMV SW Dev, PMV_SW"`). The app now splits these and returns the most common single value, eliminating spurious combined-name rows in the Drift by Squad table.

### v1.4.8
- **README — comprehensive Date Drift user guide** added covering: what drift is, which file types work, recommended PI planning workflow, cadence table, explanation of all three sub-tabs, short-window rate warning, product owner talking points, and "what good looks like" reference table.

### v1.4.7
- **Date Drift — plain-English product owner summary** — the Snapshot Comparison tab now opens a "How to explain this to your product owner" box automatically, with a plain-English paragraph, average drift in sprints, and three suggested team questions. When the measurement window is < 14 days a warning explains that the rate figure is a mathematical artefact and directs attention to the absolute numbers instead.

### v1.4.6
- **Squad dropdown pollution fix** — component values that appear on fewer than 5% of team-level items are now filtered out of the squad dropdown. This removes label-like values (e.g. `PMV_SW`) and product-area components (e.g. `Towing & Hitching Assistance`) that Jira stores in secondary `Component/s` columns alongside the real team name.

### v1.4.5
- **Date Drift works with regular snapshot CSVs** — the drift comparison no longer requires an Advanced Roadmaps export. Any two regular Jira "Created vs Resolved" snapshot exports can be compared using `Custom field (Target end)`, `Custom field (Target End Date)`, `Custom field (End Date)`, or `Due Date` — the app auto-detects the format.

### v1.4.4
- **Same-squad multi-file merge fix** — uploading two time-period exports of the same squad (e.g. a May 25 and a May 28 snapshot) no longer incorrectly renames squads to `snapshot_0` / `snapshot_1`. Files sharing the same squad name are merged and de-duplicated by Issue key, keeping the first upload's version of any duplicate.

### v1.4.3
- **Date Drift Analysis — velocity, squad breakdown, and adjusted forecast** — three sub-tabs added to Plan Accuracy:
  - *Drift velocity*: upload multiple historic exports to see a line chart of how total drift has accumulated over time
  - *Squad breakdown*: box-plot showing drift distribution per team
  - *Adjusted forecast*: projects expected additional drift onto each in-flight item using `adjusted_target = current_target + (remaining_days × drift_rate)`

### v1.4.2
- **Date Drift Analysis** — new section in the Plan Accuracy tab. Upload a baseline Roadmaps CSV (your original plan) alongside the current export; the app compares every item's target end date and shows a colour-coded horizontal bar chart of drift per item (🔴 major >30 d · 🟠 moderate · 🟡 minor · 🔵 pulled in), a by-hierarchy summary table, and a detail expander.

### v1.4.1
- **`nan` in Epic/Capability progress table** — fixed string conversion of NaN fields
- **Draft / pre-work states removed from Constraints chart** — states like Draft, Backlog, Icebox no longer appear in the age-by-state box plot unless they have ≥ 3 items
- **Data Quality score** — "Cycle-time coverage" renamed to "Completed items" with plain-English explanation; all four score rows now give actionable advice
- **Squad mapping debug** — new expander in Data Quality shows item count by squad × type to help diagnose component/label bleed-through

### v1.4.0
- **Epic/Capability Progress table** — Plan Accuracy tab now includes a drill-down table for Epics and Capabilities showing target date, delivery risk (🔴/🟠/🟢), progress %, done/total issue count, and RAG status from the Roadmaps CSV
- **Squad filter pollution fix** — squad list now built from team-level items only (Story/Bug/Task/Spike/Sub-task), preventing Epic/Capability product-area component names from appearing as squad options

### v1.3.8 – v1.3.9
- **Plan Accuracy — Delivery Risk view** — new section shows all in-flight items against their target end dates, classified as overdue / at risk (≤14 days) / on track, with a horizontal bar chart
- **Plan Accuracy scatter chart redesign** — replaced overlapping dashed lines with a shaded ±3-day tolerance band drawn behind the data; three named legend traces (on time / late / early); x-jitter to separate items with the same target date

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
`https://github.com/markcocoscopas/FlowModel/releases/latest`

You can also trigger a test build at any time **without** creating a release
by going to **Actions → Build Windows Package → Run workflow**.

---

## Licence

MIT — see `LICENCE` file.

# SurveyPlatform

Curated runtime bundle for the unified survey platform.

This directory holds the unified CLI, the dashboards and launchers, the
pipeline source for every specialist tool, and the local `repository` and
`workspace` data folders. Survey source folders stay in the user-selected
archive tree. Built EXEs under each pipeline's `dist\` and the data folders are
git-ignored.

## Documentation

| Document | Covers |
|---|---|
| `README.md` (this file) | Entry points, workspaces, launchers, tests |
| `AGENT_HANDOFF.md` | Pipeline behavior contracts, regression jobs, continuation notes |
| `docs\CLI.md` | `survey_tool_cli.py` command reference |
| `docs\REPOSITORY_STRUCTURE.md` | Archive vs repository vs workspace boundaries and folder layout |
| `docs\SURVEY_LAUNCHER.md` | Daily Survey Launcher and Project Startup contract |
| `docs\design\SURVEY_PLATFORM_SPEC.md` | Original platform design (March 2026) and what was built |
| `pipelines\README.md` | Pipeline folders, launchers, build dependencies |
| `acceptance\README.md` | Synthetic end-to-end acceptance contract |
| `local_browser_app\README.md` | Browser workbench scope |

Each pipeline folder has its own README where one exists.

## Source Roots

The package-local `survey_tool_config.json` intentionally no longer pins one
live survey tree or one archive path.

Set the source/archive location at runtime instead:

- GUI: `Repository root`, `Source root`, `Discovery`
- CLI: `repo scan --root ... --source-root ... --discovery-mode ...`

`Repo Scan` reads from the selected source tree and writes metadata into this
package's local `repository/` folder. `repo materialize` is the separate copy
step when you want curated local working files. That split is intentional so
read-only archive discovery stays separate from local metadata and copies.

To refresh both repository metadata and the Question Browser from PowerShell,
pass the resolved repository path to both `--root` and `--db` so an older
machine-specific database setting cannot redirect the rebuild:

```powershell
$repo = (Resolve-Path .\repository).Path
py -3 .\survey_tool_cli.py repo scan --root $repo --source-root "C:\path\to\NPA Archive - Documents" --discovery-mode archive
py -3 .\survey_tool_cli.py repo questions-rebuild --root $repo --db (Join-Path $repo "questions.sqlite")
```

For direct stage commands, either pass an explicit `--root` or use the
survey-aware platform flows (`survey show`, `survey detect`, `survey run`)
that derive paths from repository metadata.

## Main Entry Point

From this directory:

```powershell
py -3 .\survey_tool_cli.py survey list
py -3 .\survey_tool_cli.py survey show NPA3789
py -3 .\survey_tool_cli.py survey run NPA3789 wincross
```

Or use:

```powershell
.\run_survey_platform.bat survey list
```

For a read-only drift check across configs, frozen app builds, workspace status,
and temp folders:

```powershell
.\run_suite_health_check.bat --workspace NPA3804
```

## Regression Tests

Run every pipeline's unit tests, and optionally the acceptance smoke test, with
one command:

```powershell
.\run_tests.bat
.\run_tests.bat --acceptance
```

Pass suite names such as `merge trend` to run a subset, and `-v` for full output.

## Acceptance Smoke Test

Run the synthetic end-to-end workflow after cross-pipeline changes or an EXE
rebuild:

```powershell
.\run_acceptance_smoke.bat
```

It stages an ignored `NPA9999 Acceptance` project and checks Project Startup,
launcher context, WinCross generation, merging, trend tables, quotas, Auto
Results, and open-end recoding. Reports and inspectable outputs are retained in
`acceptance_runs`. Add `--gui-smoke` to briefly start and close all packaged
specialist applications after the data checks. See
`acceptance\README.md` for the exact contract.

## GUI Entry Point

For the local browser version of the essential production tools, run:

```powershell
.\run_survey_browser.bat
```

It opens a localhost dashboard for Table Gen, Sheet Merge, Open-End Coder,
Question Browser, Auto Results, and the read-only Quota Checker review while
continuing to use the existing pipeline cores. See `local_browser_app/README.md`
for the deliberately simplified version and its test command.

For daily work in an existing client survey folder, use the lightweight Survey
Launcher:

```powershell
.\run_survey_ops_lite.bat
```

Select the survey ID and project root, then open a specialist workflow. The
`Project Startup` workflow creates the standard `Job`, `Data`, `Data\Partial`,
and `Job\Table Gen` paths without replacing existing folders, then copies the
newest `Qst` DOCX ending in `Final` into Table Gen. WinCross uses that output
folder and receives the selected survey context. See `docs\SURVEY_LAUNCHER.md`
for the folder and manifest contract.

For repository cataloging, question search, and the full workspace dashboard,
use:

```powershell
.\run_survey_platform_gui.bat
```

Or:

```powershell
py -3 .\survey_platform_gui.py
```

The GUI now includes a dedicated `Workflows` page with guided tabs for:

- WinCross
- Table Merge
- OE Codebook extract/render
- Empty Results generation

The repository scan controls now include:

- `Repository root`
- `Source root`
- `Discovery`

so the archive/input tree can be changed by the user without moving the local metadata repo.

## Local Workspace

Generated working files now default to:

```text
SurveyPlatform\workspace\NPA####\
```

Use this for pre-fielding WinCross outputs, tracked daily data deliveries,
guided merge outputs, OE drafts, and empty-results drafts. The OneDrive archive
source tree should be treated as an input location; `Repo Scan` remains an
explicit snapshot/update step.

Each survey workspace can also hold `workflow_status.json`, which records the
manually selected phase plus checklist/review status for that survey. Daily data
tracking keeps only the current local copy plus `data_delivery_manifest.json`;
new deliveries with different headers are blocked instead of overwriting the
current copy. The working current-data filename is stable, such as
`NPA3801_current_data.csv`, so downstream daily merge setup can keep pointing at
the same workspace path while the file contents refresh. The same status file
also tracks the current data day when a delivery is accepted.

Use `Add File to Workspace` to manually curate important files into typed
workspace folders. The app records those choices in `workspace_manifest.json`
and prefers curated workspace files over auto-detected archive files when it
preloads WinCross, TOMAS, merge, OE, and results defaults.
When the selected role is current data or current timeseries, `Add File to
Workspace` uses the same daily-delivery guardrails as `Track Delivery`: headers
must be readable and match the current tracked file before anything is replaced.
When the selected role is daily codelist, the file is copied into a day-specific
folder based on the current `Day` value in the `In-field Daily` tab.

The workspace now separates inputs and outputs so folder location carries more
meaning than strict filenames:

```text
workspace\NPA####\
  inputs\
    questionnaire\final\
    questionnaire\phone\
    questionnaire\sms\
    data\current\
    data\timeseries_current\
    data\codelists\day_#\
    merge\maps\
    tables\reviewed\
    results\templates\
    codebooks\
    other\
  outputs\
    wincross\raw\
    wincross\json\
    wincross\tables\
    tomas\
    merge\
      merge_runs\
    oe\codebooks\
    oe\wincross_blocks\
    results\
```

The folder for each `Add File to Workspace` role is defined in
`WORKSPACE_FILE_ROLES` in `pipelines\catalogger\repository_dashboard_gui.py`.

Use `Main survey selected` on the `Survey Workspaces` page to preload likely
inputs and outputs for those workflow tabs. The `Question Browser` stays
unfiltered by default. In the `Question Browser`, query matching defaults to
`All words`, so the same words can appear anywhere in the question text,
answer text, or derived tags. Use `Exact phrase` for the older contiguous text
match, or `Any word` for broader exploration.

For merge and OE, the workflow tabs also include buttons to open the advanced
specialist editors with the current survey and file paths preloaded, so
row-by-row review still lives inside the platform workflow instead of being
lost.

The `Start` tab is the intended home base. Detailed pipeline controls are hidden
behind `Show Advanced Details` by default; primary actions such as WinCross,
optional TOMAS, daily data tracking, and empty-results generation remain one
click away after a survey is confirmed.

The `Survey Workspaces` page also now includes `Materialize Selected`, which
opens a folder picker and copies the selected survey's curated files into a
local output root without writing back into the archive discovery tree.

For in-field trend practice, keep the current survey delivery as the merge
primary and use older jobs as secondary/trend sources. For example, after
tracking NPA3801 Day 1 data, the guided merge primary should be the current
NPA3801 data file and an older Stelson timeseries file such as NPA3787 can be
chosen as the secondary file. Guided merge writes outputs and merge run JSONs
under `workspace\NPA####\outputs\merge\`. When the current data day is known,
default merge output names include it, for example `NPA3801_day2_ts.csv`, so
practice runs are easier to compare. Guided merge orders rows with the older
secondary/trend file first and the current primary delivery appended after it,
while keeping the primary/current file's columns as the schema authority.
After the first successful guided merge for a primary/secondary survey pair,
Survey Platform saves the resolved column map under
`workspace\NPA####\inputs\merge\maps\` and reuses it on later daily guided
merges when the primary and secondary headers still match. That saved setup also
locks the primary working-data path, primary survey JSON, secondary file, and
secondary survey JSON from the reviewed Day 1 setup. The In-field Daily page
keeps only the quick daily merge action inline; use the Advanced Merge Editor
for the first reviewed map/setup run, then close it so the dashboard can capture
the map for later one-click saved-map merges.
Pipeline runs do not automatically rescan the repository; use `Repo Scan`
explicitly when you want the local index refreshed from source folders.

To generate a Word-layout PDF from curated workspace DOCX files, use:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\export_workspace_docx_pdf.ps1 -Survey NPA3797 -DryRun
powershell -NoProfile -ExecutionPolicy Bypass -File .\export_workspace_docx_pdf.ps1 -Survey NPA3797 -Overwrite
```

By default this scans `workspace\NPA####\inputs\questionnaire\final\`, writes
`*.wordlayout.pdf` next to each DOCX, and logs results to
`workspace\workspace_docx_to_pdf_results.csv`. Add `-Role phone,sms` to include
those curated questionnaire folders. This exporter uses local Microsoft Word
automation, refuses to write into the OneDrive archive tree, and asks you to
close existing Word windows before running unless `-AllowExistingWord` is used.

## Specialist Launchers

Day-to-day work can still happen directly inside the specialist app folders.
The repo-local launchers follow an `EXE-first` pattern: if a bundled EXE
exists under `dist\`, the launcher opens it; otherwise it falls back to the
source script for troubleshooting.

The full list of specialist apps, their launchers, and their build
dependencies is in `pipelines\README.md`. Desktop shortcuts open each app's
`dist\` EXE directly, so rebuild the EXE after a source change.

## Notes

- `repository/` is local, git-ignored metadata. It reflects the source/archive path and state from the last `repo scan`.
- If the live survey folders change, run `repo scan` again to refresh the repository index.
- TOMAS still requires its normal OpenAI credentials at runtime.
- Treat this package as the authoritative repository app and control plane. The specialist apps remain supported day-to-day tools, and older repo dashboards outside this package are legacy references.

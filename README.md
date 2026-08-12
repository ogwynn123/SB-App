# SurveyPlatform

Curated runtime bundle for the unified survey platform.

This directory mirrors the layout expected by `survey_tool_cli.py` and includes:

- the unified CLI and platform docs
- the current `repository` metadata and run history
- the active pipeline source for WinCross, catalog, merge, OE, TOMAS, and auto/empty results
- the packaged launcher/build-side files needed to work from `SurveyPlatform\pipelines` directly

The authoritative repository/control-plane structure is documented in:

- `REPOSITORY_STRUCTURE.md`

This bundle intentionally excludes or only partially includes:

- live survey source folders under `pipelines/wincross_table_generator/NPA_Surveys`
- some specialist app `build/` and `dist/` artifacts may be present, but do not assume every EXE is bundled
- copied app snapshots under `repos/`
- test and temp output folders

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

## GUI Entry Point

For daily work in an existing client survey folder, use the lightweight Survey
Launcher:

```powershell
.\run_survey_ops_lite.bat
```

Select the survey ID and project root, then open a specialist workflow. The
`Project Startup` workflow creates the standard `Job`, `Data`, `Data\Partial`,
and `Job\Table Gen` paths without replacing existing folders, then copies the
newest `Qst` DOCX ending in `Final` into Table Gen. WinCross uses that output
folder and receives the selected survey context. See `LITE_PLATFORM.md` for the
folder and manifest contract.

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
  outputs\
    wincross\raw\
    wincross\json\
    wincross\tables\
    tomas\
    merge\
    oe\
    results\
```

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

- WinCross: `pipelines\wincross_table_generator\open_survey_pipeline_gui.bat`
- Table Merge: `pipelines\table_merger\open_sheet_merge_gui.bat`
- Open-End Coder: `pipelines\open_end_coder\Launch_OE_Codebook_GUI.bat`
  - Primary output: a row-specific `*.OE-coded.csv`
  - Session state: project-local `*.oe_session.sqlite`
  - Legacy codebook editor: `pipelines\open_end_coder\Launch_OE_Codebook_Legacy_GUI.bat`
- Auto Results: `pipelines\auto_results\open_autoResults_gui.bat`
- TOMAS: `pipelines\thomas_in_a_box\open_tomas_pipeline_gui.bat`

## Notes

- `repository/` is a copy of the current platform metadata state as of packaging time.
- `repository/` may still reference whatever source/archive path was last scanned. That is repository data, not a fixed package default.
- If the live survey folders change, run `repo scan` again from this package to refresh the copied repository index.
- TOMAS still requires its normal OpenAI credentials at runtime.
- Treat this package as the authoritative repository app and control plane. The specialist apps remain supported day-to-day tools, and older repo dashboards outside this package are legacy references.

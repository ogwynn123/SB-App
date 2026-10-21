# Survey Launcher

The Survey Launcher is the single starting point for daily work. It selects an
existing survey folder and opens every workflow from one list. Processing logic
remains inside each specialist application or pipeline module.

| Workflow | Runs as | Working folder |
|---|---|---|
| Project Startup | launcher action | project root |
| WinCross Table Generator | Table Gen app | `Job\Table Gen` |
| Table Merger | Sheet Merge app (writes the Combined Demographics carry-over after a timeseries merge) | `Data` |
| Sample Append | launcher dialog over `pipelines\table_merger\sample_append.py` | `Data` |
| Open-End Coder | OE app | `Data\Partial\Open Ends` or `Data` |
| Sample Quota Checker | Quota app | `Data` |
| Trend Table Updater | Trend app | `Job\Table Gen` |
| Auto Results | Auto Results app | `Data\Partial\Results` or `Data` |
| Preliminary QC | launcher action over `pipelines\qc_checker\prelim_qc.py`; report in `Job\QC\<timestamp>` | `Job` |
| TOMAS | TOMAS app | `Qst\Spanish Ver` |
| Repository & Question Browser | full dashboard (`survey_platform_gui.py`) | project root |
| Browser Workbench | `run_survey_browser.bat` | project root |

Sample Append defaults to the newest `Data\NPA####ts*.csv` and remembers the
project's column mapping (`DATA_COLUMN=SAMPLE_COLUMN`) in the project manifest.
When any packaged EXE is older than its source, the Activity log says so and
points to `rebuild_apps.bat`.

## Launch

Run:

```bat
SurveyPlatform\run_survey_ops_lite.bat
```

An initial project can also be supplied from the command line:

```powershell
py -3 .\survey_ops_lite.py --survey-id NPA3827 --project-root "C:\path\to\NPA3827 Benchmark"
```

## Project Model

The selected archive survey folder is the operational project root. The
launcher does not copy files into `workspace` or `lite_workspace`.

Run `Project Startup` once after selecting a new project. It creates only the
missing folders in this layout:

```text
<project root>\
  Data\
    Partial\
  Job\
    Table Gen\
```

Existing folders and their contents are preserved. Project Startup recursively
searches `Qst` for DOCX filenames whose stem ends in `Final`, optionally followed by
a date (`Final 10.19.26`, `FINAL 9.30.26`, `Final 10-19-2026`), skips Spanish
versions, selects the most
recently modified match, and copies it into `Job\Table Gen`. It updates an older
copy, leaves an identical copy alone, and does not overwrite a newer differing
Table Gen copy.

The launcher searches `<project root>\Qst` for questionnaire DOCX/PDF pairs
and preloads WinCross to write RAW, JSON, TABLES, BANNERS, and COVER outputs to
`Job\Table Gen`. Standalone WinCross launches retain the legacy behavior of
writing outputs beside the questionnaire. WinCross and the Data-based tools no
longer create the shared project folders themselves; they prompt for Project
Startup when a required folder is missing.

Other tools reuse existing archive conventions when present:

- Auto Results prefers `Data\Partial\Results` or `Data\Partial Data\Results`.
- Open-End Coder prefers existing `Open Ends` or `OEs` folders. It creates a
  project-local `*.oe_session.sqlite` database there, preserves assignments by
  `Survnum` (or another confirmed unique key), and exports a new
  `*.OE-coded.csv` without modifying the imported datafile.
- Table Merger and Quota Checker use `Data` as their working location.
- Trend Table Updater uses `Job\Table Gen`.
- TOMAS uses `Qst\Spanish Ver`.

Every launched tool receives the survey ID, project root, and selected work
folder through a small environment contract. File dialogs begin in that work
folder, but the launcher does not guess input files. Explicit selections and
tool-specific saved pairings remain authoritative. When Table Merger is opened
from the launcher, globally saved input paths from another project are cleared
so they cannot be merged accidentally.

## State

A portable project manifest is written only after a tool is launched:

```text
<project root>\Job\.surveyplatform\project.json
```

It stores relative tool folders and launch timestamps. Recent-project history
and window state stay in the machine-local ignored file
`survey_launcher_settings.json`.

## Boundary

The launcher owns survey identity, project-root validation, project startup,
recent projects, and process launching. Merge mapping, table
generation, quota editing, result alignment, open-end coding, and translation
remain in separate GUIs.

## Acceptance Check

`run_acceptance_smoke.bat` exercises the launcher and major data contracts with
the repo-owned synthetic `NPA9999 Acceptance` fixture. The default run never
opens GUIs or touches archive projects. Use `--gui-smoke` after rebuilding EXEs
to add a packaged-startup check. Timestamped outputs and both text and JSON
reports are written under the ignored `acceptance_runs` folder.

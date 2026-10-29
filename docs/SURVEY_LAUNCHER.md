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
| TOMAS (hidden unless turned on, see below) | TOMAS app | `Qst\Spanish Ver` |
| Repository & Question Browser | full dashboard (`survey_platform_gui.py`) | project root |
| Browser Workbench | `run_survey_browser.bat` | project root |

## Project status panel

Above the workflow list, the launcher shows where the selected project stands.
Every line is read from the project's files, so nothing is ticked by hand and
it cannot drift out of date. Lines are Done, To do, Check (an input changed
after the step ran), or `-` (not used in this project), and "Next:" names the
first Check, else the first To do. Double-click a To do or Check line to open
its tool, or any other line to open its file.

| Step | Read from | Check when |
|---|---|---|
| Final questionnaire | Qst Final vs. `Job\Table Gen` copy (Project Startup's content comparison) | Qst holds a newer, different Final |
| Table Gen | `Job\Table Gen\*TABLES.autogen.txt` | the questionnaire changed after the tables were generated |
| WinCross job | `Job\NPA####.job` | |
| Data | `Data\NPA####*.csv` | |
| Merge (trend) | `Data\Merge\merge_runs`, `Data\NPA####ts*.csv`, carry-over review file | current data delivered after the last merge |
| Open ends | `*.oe_session.sqlite` under `Data` (read-only): latest-wave coded / total | |
| Daily partials | `Data\Partial\*Day N*.docx` | |
| Preliminary QC | newest `Job\QC\*\prelim_qc_issues.csv` | data or job changed after the QC, or critical issues |
| Final deliverables | `Results`, `Tab`, `Cover` DOCX in the project folder | |

Sample Append defaults to the newest `Data\NPA####ts*.csv` and remembers the
project's column mapping (`DATA_COLUMN=SAMPLE_COLUMN`) in the project manifest.
When any packaged EXE is older than its source, the Activity log says so and
points to `rebuild_apps.bat`.

TOMAS is off by default: it is hidden from the launcher and dashboard (buttons,
panel, survey-table column, and checklist steps) and skipped by the health
check and packaged-app launch check. To turn it on, add this to the
machine-local `survey_tool_config.json`:

```json
{"features": {"tomas": true}}
```

or set `SURVEYPLATFORM_TOMAS=1` for one session. The TOMAS code and its tests
are unchanged, and `rebuild_apps.bat` rebuilds it only when named.

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
      Banners\
      OEs\
      Results\
  Job\
    Table Gen\
```

Existing folders and their contents are preserved. A job that already keeps its
open ends in `Data\Partial\Open Ends` keeps using it; no empty `OEs` folder is
added beside it. Project Startup recursively
searches `Qst` for DOCX filenames whose stem ends in `Final`, optionally followed by
a date (`Final 10.19.26`, `FINAL 9.30.26`, `Final 10-19-2026`), skips Spanish
versions, selects the most
recently modified match, and copies it into `Job\Table Gen`. It updates an older
copy, leaves an identical copy alone, and does not overwrite a newer differing
Table Gen copy.

When run from the launcher, Project Startup also saves that questionnaire as
PDF with Word's own PDF export (the same as Word's Save as PDF, which made most
existing questionnaire PDFs; Acrobat is not needed). The PDF goes beside the
Final DOCX in `Qst` with the same name, because the launcher's WinCross pairs a
DOCX with the same-named PDF in `Qst`. It is also copied beside the Table Gen
DOCX when that copy is the same questionnaire. An existing PDF is never
replaced; one older than its DOCX is reported in the log so it can be re-saved.

Using that Final questionnaire's name with `Final` and any date after it
removed (`NPA3887 Stelson PA-10 Track Week 2 Final 10.19.26` becomes
`NPA3887 Stelson PA-10 Track Week 2`), Project Startup also adds five Word
documents to the project root: blank `<name> Tab.docx` and `<name> Trend
Tables.docx`; `<name> Cover.docx`, copied from the client's previous job (see
below); `<name> Trend Marginals.docx`, made from
`templates\Trend Marginals Template.docx` with its `XX-NN` title set to the
questionnaire's area; and `<name> Results.docx`, which starts as a copy of the
Final questionnaire. The area is the last field of the questionnaire's title
line, the one starting with the survey ID: a district such as `PA-10`, or a
state or city such as `Illinois` or `Providence, RI`. If there is no such line,
`XX-NN` is left in; if the template is missing, Trend Marginals starts blank. A
document that already exists is never overwritten, and none are created when
no Final questionnaire is found.

The Cover is copied from the most recent earlier job for the same client: the
hand-made `<name> Cover.docx` in that job's project root (drafts such as
`Cover DRAFT` and Table Gen's `COVER.autogen.docx` are not used). Startup looks
at the sibling job folders first (`Stelson\2026\NPA3880 Track Week 3` for
NPA3887), then widens one level at a time up to the client folder above the
year folders, so the first job of a year uses last year's cover and
`Bean\2026\General` finds `Bean\2026\Primary`. At each level the highest NPA
number below the current job with a cover wins. With no earlier cover, Cover
starts blank. The launcher log names the cover that was copied.

When the launcher runs Project Startup and has just created the Results copy,
it opens that copy in a separate hidden Word, runs the `Normal.dotm` macro
`EmptyResults_Safe_v2_Silent`, saves and closes it. The macro must not show
dialogs (Word is hidden, so a message box would hang startup), which is why
startup does not call `EmptyResults_Safe_v2` itself: that one ends with a
`MsgBox`. Add the silent variant to the same module as `EmptyResults_Safe_v2`:

```vb
Public Sub EmptyResults_Safe_v2_Silent()
    Dim prevScreen As Boolean
    prevScreen = Application.ScreenUpdating
    Application.ScreenUpdating = False
    On Error GoTo Fail

    ReplaceParagraphCodeTokens ActiveDocument
    ReplaceNumericOnlyTableCells ActiveDocument

    Application.ScreenUpdating = prevScreen
    Exit Sub

Fail:
    Application.ScreenUpdating = prevScreen
    Err.Raise Err.Number, "EmptyResults_Safe_v2_Silent", Err.Description
End Sub
```

`ReplaceParagraphCodeTokens` should skip the project header line (the one that
starts with the survey ID, such as `NPA3887<tab>October 20-22, 2026<tab>PA-10`),
or its date and district are emptied too. Add
`If IsProjectHeaderLine(Left$(bodyText, tabPos - 1)) Then GoTo NextParagraph`
after the first-tab check, with a small `IsProjectHeaderLine` function that
tests the text before the tab against `^\s*NPA\d+`.

If the macro is missing or Word fails, the Results copy is left as the
questionnaire and the launcher log says why. Startup never quits a Word you
already have open, and an existing Results document is not touched.
`run_project_startup(..., use_word=False)`, the default for scripts and tests,
skips Word entirely (no PDF and no Results emptying).

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

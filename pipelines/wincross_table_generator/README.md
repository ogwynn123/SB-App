# WinCross Table Generator

Turns a questionnaire DOCX/PDF pair into WinCross inputs:
DOCX/PDF -> RAW -> JSON -> TABLES, BANNERS, and COVER.

The table, banner, ranking, and summary rules are documented in
`AGENT_HANDOFF.md` under "WinCross/Table Gen behavioral contract".

## Launch

- GUI: `open_survey_pipeline_gui.bat` (opens `dist\survey_pipeline_gui.exe`
  when present, otherwise `survey_pipeline_gui.py`)
- CLI: `py -3 survey_tool_cli.py pipeline ...` from the package root; see
  `docs\CLI.md`
- From the Survey Launcher, outputs go to the project's `Job\Table Gen`.
  Standalone launches write outputs beside the questionnaire.

## GUI features

- Recursive discovery of exact-stem DOCX/PDF pairs under a chosen root
- Job table with per-survey status, validation state, and question count
- `Run Selected`, `Run All`, `Stop`, and `Overwrite Existing Outputs`
- Validation panel for missing sources, missing or stale outputs, and
  up-to-date counts
- Live log stream from each pipeline step
- Quick-open buttons for the folder and the RAW, JSON, TABLES, BANNERS, and
  COVER outputs
- Run report export as CSV or JSON
- Saved settings (last root, window geometry, overwrite mode) in the
  git-ignored `survey_pipeline_gui_settings.json`

## Files

| File | Role |
|---|---|
| `survey_pipeline_gui.py` | Desktop GUI |
| `survey_pipeline.py` | Orchestration: runs each step, pair discovery |
| `unified_pipeline.py` / `.bat` | Wrapper that forwards to `survey_tool_cli.py pipeline` |
| `survey_unformatter.py` | Questionnaire text cleanup before parsing |
| `surveyConvertJSON.py` | Questionnaire parsing to RAW/JSON |
| `question_attributes.py` | Question classification |
| `wincrossTableCompile.py` | TABLES compilation, summaries, and title cleanup |
| `wincrossBannerCompile.py` | BANNERS output |
| `wincrossCoverCompile.py` | COVER output |
| `survey_catalog.py` | Compatibility shim for `pipelines\catalogger\survey_catalog.py` |
| `pyi_rth_tk_paths.py` | PyInstaller runtime hook for Tk paths |

## Build

```powershell
py -3 -m pip install -r requirements.txt
.\build_gui_exe.bat     # dist\survey_pipeline_gui.exe
.\build_exe.bat         # dist\survey_pipeline.exe (CLI pipeline)
```

## Tests

From the package root: `.\run_tests.bat wincross`.

## Comparing against finished jobs

`golden_compare.py` runs the current pipeline on copies of archive jobs and
compares the generated TABLES with each job's final, hand-edited `.job` file.
The copies live in the git-ignored `corpus\wincross\NPA####\` folders (Final
DOCX/PDF, `final.job`, `historical\` autogen output, `source.json`), and
reports go to `corpus\reports\<timestamp>\` (`summary.md`, `tables.csv`, and one
Markdown file per job). Client data in the corpus must never be committed.

```powershell
py -3 golden_compare.py                  # all corpus jobs, reusing generated output
py -3 golden_compare.py --regenerate     # rerun Table Gen first
py -3 golden_compare.py --job NPA3873
```

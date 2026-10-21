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

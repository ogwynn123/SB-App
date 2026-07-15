# Survey Pipeline GUI MVP

## Goal
Provide a desktop app that lets users discover surveys, run the pipeline in batch, monitor progress, and open outputs without using the command line.

## Implemented
- Recursive survey discovery under a chosen root (supports `NPA_Surveys/NPA####` layout).
- Job table with per-survey status, validation state, and parsed question count.
- Run controls: `Run Selected`, `Run All`, `Stop`.
- Overwrite mode toggle: `Overwrite Existing Outputs`.
- Validation panel for:
  - missing source files
  - missing outputs
  - stale outputs (older than DOCX/PDF)
  - up-to-date counts
- Live log stream from pipeline steps.
- Quick-open actions for folder, RAW, JSON, and TABLES outputs.
- Run report export in CSV and JSON.
- Settings persistence:
  - last root path
  - window geometry
  - overwrite mode

## Primary file
- `survey_pipeline_gui.py`

## Backend support
- `survey_pipeline.py`
  - optional message callback support in `run_step`, `run_script`, and `run_one`
  - streaming subprocess output when callback is provided
  - recursive pair discovery helper: `find_docx_pdf_pairs_recursive`

## Build script
- `build_gui_exe.bat` for windowed EXE generation.

## Next increments
1. Add per-step progress indicators per job row (RAW/JSON/TABLES stage markers).
2. Add rerun filters (`only stale`, `only missing outputs`, `failed only`).
3. Add single-click `Open Latest Report` and in-app report table view.

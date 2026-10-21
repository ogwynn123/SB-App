# Pipeline Layout

This directory contains the production pipelines:

| Folder | Application | Launcher | Docs |
|---|---|---|---|
| `wincross_table_generator` | Table Gen / WinCross | `open_survey_pipeline_gui.bat` | `README.md` |
| `table_merger` | Sheet Merge | `open_sheet_merge_gui.bat` | `README_QUICKSTART.md` |
| `open_end_coder` | Open-End Coder | `Launch_OE_Codebook_GUI.bat` | `README.md` |
| `auto_results` | Auto Results, Empty Results | `open_autoResults_gui.bat`, `open_empty_results_generator.bat` | `EMPTY_RESULTS_GENERATOR.md` |
| `sample_quota_checker` | Quota Checker | `dist\sample_quota_checker.exe` or `py -3 sample_quota_checker_gui.py` | `quota_examples_verification.md` |
| `trend_table_updater` | Trend Table Updater | `open_trend_table_updater.bat` | `README.md` |
| `thomas_in_a_box` | TOMAS Spanish translation | `open_tomas_pipeline_gui.bat` | |
| `catalogger` | Repository dashboard and catalog | `..\run_survey_platform_gui.bat` | `..\docs\REPOSITORY_STRUCTURE.md` |
| `questionnaire_channel_builder` | Phone/SMS questionnaire drafts | CLI | `README.md` |
| `survey_writer` | Survey Writer drafting helper | `open_survey_writer_gui.bat` | `README.md` |

The former aggregated OE codebook editor remains available through
`open_end_coder\Launch_OE_Codebook_Legacy_GUI.bat`.

Package-level entry points (`survey_tool_cli.py`, `survey_platform_gui.py`,
`survey_ops_lite.py`, `run_tests.bat`) are described in the root `README.md`.
The CLI wrappers `wincross_table_generator\unified_pipeline.py` and
`table_merger\unified_merge.py` forward to `survey_tool_cli.py`.

## Launcher behavior

- Specialist launchers are EXE-first: if `dist\*.exe` exists, the launcher
  opens it.
- Without an EXE, the launcher falls back to the source script so
  troubleshooting still works.
- A source change does not reach an EXE launcher or desktop shortcut until the
  EXE is rebuilt with that app's `build_*.bat`. `suite_health_check.py` warns
  when an EXE is older than its source.

## Dependency setup

- WinCross GUI EXE:
  - `py -3 -m pip install -r pipelines/wincross_table_generator/requirements.txt`
- Sheet Merge GUI EXE:
  - `py -3 -m pip install pandas openpyxl rapidfuzz pyinstaller`
- OE GUI EXE:
  - `py -3 -m pip install pyinstaller openpyxl`
  - The production app is `oe_record_coder_gui.py`.
- Auto Results GUI EXE:
  - `py -3 -m pip install pyinstaller python-docx`
- Quota Checker GUI EXE:
  - `py -3 -m pip install pyinstaller pandas openpyxl`
- Trend Table Updater GUI EXE:
  - `py -3 -m pip install pyinstaller`
- TOMAS pipeline dependencies:
  - `py -3 -m pip install -r pipelines/thomas_in_a_box/requirements.txt`

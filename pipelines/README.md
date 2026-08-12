# Pipeline Layout

This directory now contains the production project pipelines:

- `wincross_table_generator`
- `open_end_coder`
- `table_merger`
- `thomas_in_a_box`
- `auto_results`
- `sample_quota_checker`
- `trend_table_updater`
- `catalogger`

`survey_writer` is also included as a source-launched drafting/helper app.

Key entrypoints:

- Unified CLI (repo root): `survey_tool_cli.py`
- Unified dashboard launcher (repo root): `survey_platform_gui.py`
- WinCross wrapper: `pipelines/wincross_table_generator/unified_pipeline.py`
- Table merger wrapper: `pipelines/table_merger/unified_merge.py`
- Specialist app launchers:
  - `pipelines/wincross_table_generator/open_survey_pipeline_gui.bat`
  - `pipelines/table_merger/open_sheet_merge_gui.bat`
  - `pipelines/open_end_coder/Launch_OE_Codebook_GUI.bat`
  - `pipelines/auto_results/open_autoResults_gui.bat`
  - `pipelines/trend_table_updater/trend_table_updater_gui.py`
  - `pipelines/thomas_in_a_box/open_tomas_pipeline_gui.bat`

Launcher behavior:

- Specialist launchers are `EXE-first`.
- If `dist\*.exe` exists, the launcher opens it.
- If no EXE is present, the launcher falls back to the source script so troubleshooting still works.

## Dependency setup

- WinCross GUI EXE:
  - `py -3 -m pip install -r pipelines/wincross_table_generator/requirements.txt`
- Table Merge GUI EXE:
  - `py -3 -m pip install pandas openpyxl rapidfuzz pyinstaller`
- OE GUI EXE:
  - `py -3 -m pip install pyinstaller openpyxl`
  - The production app is `oe_record_coder_gui.py`; the former aggregated
    codebook editor remains available through `Launch_OE_Codebook_Legacy_GUI.bat`.
- Auto Results GUI EXE:
  - `py -3 -m pip install pyinstaller python-docx`
- Trend Table Updater GUI EXE:
  - `py -3 -m pip install pyinstaller`
- TOMAS pipeline dependencies:
  - `py -3 -m pip install -r pipelines/thomas_in_a_box/requirements.txt`

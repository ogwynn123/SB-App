# Unified Survey CLI

`survey_tool_cli.py` provides one CLI-first entrypoint for:

- WinCross pipeline (`DOCX/PDF -> RAW -> JSON -> TABLES`)
- Sheet merging (`primary + secondary -> merged output/report/archive`)

Existing scripts remain intact under `pipelines/*`.

GUI note:

- `sheetMerging_gui.py` and `survey_pipeline_gui.py` now display a live `Backend: ...` status.
- `sheetMerging_gui.py` includes a `Run History` table with a `Backend` column per preflight/merge run.
- `sheetMerging_gui.py` now includes `Survey JSON Semantic Matching` controls:
  - `Primary survey JSON`
  - `Secondary survey JSON`
  - `Question similarity threshold`
  - `Question similarity policy (warn|drop|abort)`
- In `sheetMerging_gui.py`, semantic JSON checks run through the unified backend. If it falls back to local mode, the GUI logs that semantic checks are unavailable there.
- `survey_pipeline_gui.py` includes a `Backend` field in each job list row and in exported run reports.

## Shared Config

Default config path:

- `survey_tool_config.json` (repo root)

Override with:

```powershell
python survey_tool_cli.py --config .\my_config.json <subcommand> ...
```

## Pipeline Subcommand

Single run:

```powershell
python survey_tool_cli.py pipeline --docx .\pipelines\wincross_table_generator\NPA_Surveys\NPA3789\NPA3789.docx --pdf .\pipelines\wincross_table_generator\NPA_Surveys\NPA3789\NPA3789.pdf
```

Batch run (recursive pair discovery):

```powershell
python survey_tool_cli.py pipeline --root .\pipelines\wincross_table_generator\NPA_Surveys --recursive --overwrite
```

Save pipeline defaults:

```powershell
python survey_tool_cli.py pipeline --root .\pipelines\wincross_table_generator\NPA_Surveys --recursive --overwrite --save-defaults
```

Wrapper entrypoint (from `pipelines/wincross_table_generator`):

```powershell
python .\pipelines\wincross_table_generator\unified_pipeline.py --root .\pipelines\wincross_table_generator\NPA_Surveys --recursive
```

Windows launcher:

```powershell
.\pipelines\wincross_table_generator\unified_pipeline.bat --root .\pipelines\wincross_table_generator\NPA_Surveys --recursive
```

## Merge Subcommand

Dry run:

```powershell
python survey_tool_cli.py merge --primary .\pipelines\table_merger\sample_data_test\quickcsv_primary.csv --secondary .\pipelines\table_merger\sample_data_test\quickcsv_secondary.csv --primary-join respondent_id --secondary-join respondent_id --dry-run
```

Preflight:

```powershell
python survey_tool_cli.py merge --primary .\pipelines\table_merger\sample_data_test\quickcsv_primary.csv --secondary .\pipelines\table_merger\sample_data_test\quickcsv_secondary.csv --primary-join respondent_id --secondary-join respondent_id --preflight
```

Question-similarity-aware merge:

```powershell
python survey_tool_cli.py merge --primary .\pipelines\table_merger\surveyInput\NPA3777tsSB_20260219_094037.csv --secondary .\pipelines\table_merger\surveyInput\NPA3777tsSB_20260219_093835.csv --primary-join survnum --secondary-join survnum --primary-survey-json .\pipelines\wincross_table_generator\NPA_Surveys\NPA3789\NPA3789JSON.json --secondary-survey-json .\pipelines\wincross_table_generator\NPA_Surveys\NPA3789\NPA3789JSON.json --question-similarity-policy warn --question-similarity-threshold 60
```

Policies:

- `warn`: keep mappings, print low-similarity warnings.
- `drop`: remove low-similarity mapped question columns before merge.
- `abort`: fail merge if low-similarity mapped question columns exist.

Automatic timeseries layering:

- Triggered when `secondary` looks like `NPAXXXXts...` (for example `NPA3777tsSB.csv`), has a `timeseries` column, and `primary` is a non-`ts` `NPAXXXX` file.
- Primary rows are stamped to the next timeseries code (`max(secondary.timeseries)+1`, default `1` if secondary is blank/non-numeric).
- Duplicate join-key conflicts are treated as append in this mode (wave stacking behavior).
- Output name is normalized to `NPAXXXXts.csv` using the primary survey code.
- Unmapped secondary columns are carried forward:
  - prefixed as `XXXX_column` (where `XXXX` is primary survey code), or
  - left unchanged if already prefixed like `1234_column`.

Wrapper entrypoint (from `pipelines/table_merger`):

```powershell
python .\pipelines\table_merger\unified_merge.py --primary .\pipelines\table_merger\sample_data_test\quickcsv_primary.csv --secondary .\pipelines\table_merger\sample_data_test\quickcsv_secondary.csv --primary-join respondent_id --secondary-join respondent_id --dry-run
```

Windows launcher:

```powershell
.\pipelines\table_merger\unified_merge.bat --primary .\pipelines\table_merger\sample_data_test\quickcsv_primary.csv --secondary .\pipelines\table_merger\sample_data_test\quickcsv_secondary.csv --primary-join respondent_id --secondary-join respondent_id --dry-run
```

## Sheet Merge GUI EXE

Build:

```powershell
cd .\pipelines\table_merger
.\build_gui_exe.bat
```

Run:

```powershell
.\pipelines\table_merger\dist\sheet_merge_gui.exe
```

## Repository Layer

Initialize lightweight survey repository metadata:

```powershell
python survey_tool_cli.py repo init --root .\repository
```

Scan WinCross survey folders into per-survey metadata + index:

```powershell
python survey_tool_cli.py repo scan --root .\repository --source-root .\pipelines\wincross_table_generator\NPA_Surveys
```

View repository summary:

```powershell
python survey_tool_cli.py repo status --root .\repository
```

View one survey:

```powershell
python survey_tool_cli.py repo status --root .\repository --survey NPA3789
```

Repository dashboard GUI (status + survey categorization):

```powershell
py -3 .\pipelines\catalogger\repository_dashboard_gui.py
```

Dashboard behavior:

- Shows survey stage/last-run status from `repository/index.json`.
- Lets you edit `region` and `client` per survey.
- Includes a `Question Browser` tab with:
  - `Search` results (`query` + `state/region/client/survey` filters)
  - `Frequency` concept grouping (how often a question pattern appears)
  - `Rebuild Index` trigger for `repository/questions.sqlite`
  - `Preview Selected Row` popout with full question/item/options context
  - `Export CSV` for current result grid
- Saves to both:
  - `repository/surveys/NPA####/survey.meta.json` (`categorization` block)
  - `repository/index.json` (`region` and `client` on survey rows)
- `repo scan` now preserves existing `categorization` values.

Question-level index and search:

```powershell
python survey_tool_cli.py repo questions-rebuild --root .\repository
```

Search questions:

```powershell
python survey_tool_cli.py repo questions-search --root .\repository --query "vote for" --state IL --client "Normington Petts" --limit 30
```

Frequency view (how often concept appears across surveys):

```powershell
python survey_tool_cli.py repo questions-frequency --root .\repository --query "vote for" --state WI --limit 20
```

Region/state rule:

- The question index derives `state_code` from the first two characters of `region` (for example `IL`, `WI`, `CA`), and supports both `--region` and `--state` filters.

Cross-survey links (manual):

```powershell
python survey_tool_cli.py repo link add --root .\repository --left-survey NPA3789 --left-qid 15 --right-survey NPA3777 --right-qid 14 --status approved --note "Same issue open-end"
```

Cross-survey links (semantic suggestion preview):

```powershell
python survey_tool_cli.py repo link suggest --root .\repository --left-survey NPA3789 --right-survey NPA3777 --threshold 80 --limit 25
```

Cross-survey links (apply suggestions to `repository/links.json`):

```powershell
python survey_tool_cli.py repo link suggest --root .\repository --left-survey NPA3789 --right-survey NPA3777 --threshold 80 --auto-approve-threshold 92 --apply
```

List links:

```powershell
python survey_tool_cli.py repo link list --root .\repository --survey NPA3789 --status approved --limit 50
```

Change link status:

```powershell
python survey_tool_cli.py repo link set-status --root .\repository --id 12 --status rejected
```

Merge integration note:

- When `merge` runs with survey JSON semantic checks enabled (`--primary-survey-json` + `--secondary-survey-json`), low-similarity mapped question pairs that are explicitly `approved` in `repository/links.json` are automatically exempted from `drop/abort` handling.
- The merge output/preflight now prints `repo-link exemptions` details when this applies.
- When `merge` runs with `--repo-link-write-mappings`, the Sheet Merge GUI now surfaces repo-link write outcomes in the merge-complete dialog and run history (inserted/approved/suggested/upgraded/skipped counts plus warnings/links file path).

# Repository Structure

Status: Authoritative working model
Last reviewed: 2026-10-21

## Authoritative Location

The authoritative repository and control plane is the `SurveyPlatform`
directory (`C:\Users\normi\venv\SurveyPlatform`). Older repo or dashboard
copies elsewhere under `C:\Users\normi\venv` are historical reference only.

Within it, use these as the single source of truth:

- `survey_tool_cli.py`
  The platform/backend CLI. See `docs\CLI.md`.
- `survey_platform_gui.py`
  The unified platform launcher. It opens
  `pipelines\catalogger\repository_dashboard_gui.py`.
- `repository\`
  The local metadata, question index, and materialization repo.
- `workspace\`
  Local per-survey working inputs and outputs.
- `survey_tool_config.json`
  Machine-local defaults. It intentionally does not pin one source/archive path.
- `pipelines\*`
  The pipeline source tree and specialist applications.

## Package Layout

```text
SurveyPlatform/
  survey_tool_cli.py            platform CLI
  survey_platform_gui.py        full dashboard launcher
  survey_ops_lite.py            daily Survey Launcher (docs\SURVEY_LAUNCHER.md)
  survey_launcher_core.py
  suite_health_check.py         read-only drift check
  acceptance_smoke.py           synthetic end-to-end check (acceptance\README.md)
  run_tests.py                  runs every regression suite
  run_*.bat                     Windows launchers for the above
  export_*, jsonify_*           Word/PDF, JSON, and Question Browser export helpers
  docs/
  acceptance/                   acceptance fixtures
  local_browser_app/            localhost browser workbench
  pipelines/
    catalogger/                 repository dashboard and catalog
    wincross_table_generator/   questionnaire -> RAW/JSON/TABLES/BANNERS/COVER
    table_merger/               Sheet Merge
    open_end_coder/             record-level Open-End Coder
    auto_results/               Auto Results and empty-results generator
    sample_quota_checker/       Quota Checker and workbook scraper
    trend_table_updater/        Trend Table Updater
    thomas_in_a_box/            TOMAS Spanish translation
    questionnaire_channel_builder/
    survey_writer/
  repository/                   git-ignored local metadata (below)
  workspace/                    git-ignored per-survey working area (below)
```

Each specialist app builds its EXE into its own `pipelines\<app>\dist\`.
Desktop shortcuts and the EXE-first `.bat` launchers point there.

## Repository Contents

Under `SurveyPlatform\repository`:

- `index.json`
  Repository-wide survey index used by the GUI and `survey list`.
- `surveys\NPA####\survey.meta.json`
  One metadata record per discovered survey, with optional `runs\<stage>\*.json`
  run manifests.
- `questions.sqlite`
  Question Browser and `repo questions-*` index.
- `catalog.sqlite`
  Global catalog used by the `catalog` CLI commands.
- `links.json`
  Cross-survey question links, when any have been recorded.
- `materialized_surveys_csv_priority\NPA####\`
  Local curated copies made by `repo materialize`.

As of 2026-10-21 there were 844 survey metadata folders and 797 materialized
survey folders. Run `repo status` for current counts.

## Metadata Model

`survey.meta.json` (schema version 2) holds:

- survey identity: `survey_code`, `survey_id`
- source references: `source_root`, `source_dirs`, `primary_source_dir`
- the discovered file inventory: `files`
- `categorization` (`region`, `client`)
- the legacy file-presence summary: `status`, `pipelines_completed`, `last_run`
- the stage-aware map: `stages`
- a recent run summary: `recent_runs`

Stage ids are `wincross`, `catalog`, `merge`, `oe`, `tomas`, and `results`.
The original design for this model is in `docs\design\SURVEY_PLATFORM_SPEC.md`.

## Workspace Layout

`SurveyPlatform\workspace\NPA####\` holds `workflow_status.json`,
`workspace_manifest.json`, `data_delivery_manifest.json`, and:

```text
inputs/
  questionnaire/final/  questionnaire/phone/  questionnaire/sms/
  data/current/  data/timeseries_current/  data/codelists/day_#/
  merge/maps/
  tables/reviewed/
  results/templates/
  codebooks/
  other/
outputs/
  wincross/raw/  wincross/json/  wincross/tables/
  tomas/
  merge/  merge/merge_runs/
  oe/codebooks/  oe/wincross_blocks/
  results/
```

Role-to-folder mapping lives in `WORKSPACE_FILE_ROLES` in
`pipelines\catalogger\repository_dashboard_gui.py`. The README describes how
daily deliveries, curated files, and saved merge maps use these folders.

## Operational Model

The repository layer is three separate things:

1. Discovery/index: `repository\index.json`
2. Survey metadata: `repository\surveys\NPA####\survey.meta.json`
3. Local materialization: `repository\materialized_surveys_csv_priority\NPA####\`

Working outputs go to `workspace\NPA####\`.

## Input vs Local Repo

The source/archive tree is a read-only, user-selected input, usually
`C:\Users\normi\OneDrive - Normington Petts\NPA Archive - Documents`. Typical
archive layouts are `Client\NPA####` and `Client\<bucket>\NPA####`. It is not
the local repo.

Choose it at scan time:

- GUI: `Repository root`, `Source root`, and `Discovery`
- CLI: `repo scan --root ... --source-root ... --discovery-mode ...`

The distinction is critical:

- `repo scan` reads the selected source tree and writes metadata into
  `SurveyPlatform\repository`.
- `repo materialize` copies curated discovered files into a local folder.
- Guided workflow outputs are written to `SurveyPlatform\workspace\NPA####`.
- No operation treats the source tree as the metadata repo root.
- Pipeline runs do not implicitly rescan the repository.

## Current Workflow

1. Launch the platform from `SurveyPlatform`.
2. Set the desired `Source root` and `Discovery` mode.
3. Run `Repo Scan`.
4. Review surveys in `Survey Workspaces`.
5. Select `Main survey selected`.
6. Use guided workflows or the advanced specialist editors.
7. Materialize curated local copies only when needed.

The CLI equivalents are in `docs\CLI.md`. Daily work inside an archive project
folder can instead use the Survey Launcher (`docs\SURVEY_LAUNCHER.md`).

## Open Items

1. Strengthen stage truth.
   Several stages are still inferred from file presence. Each stage should rely
   more on manifests and less on heuristics over time.
2. Complete `survey run`.
   Only `wincross` and `merge` are first-class platform stage runs.
3. Keep GUI labeling clear.
   `Repository root` is the local metadata repo; `Source root` is the read-only
   archive/input tree.
4. Keep materialization narrow.
   The strict file selectors are intentional and should evolve through explicit
   rules rather than broad copying.

## Final Rule

If older repo/dashboard behavior conflicts with the packaged platform, prefer
`survey_tool_cli.py`, `pipelines\catalogger\repository_dashboard_gui.py`, and
`repository\` in this package.

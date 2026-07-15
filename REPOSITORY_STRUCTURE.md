# Repository Structure

Status: Authoritative working model
Date: 2026-03-25

## Authoritative Location

The authoritative repository/control-plane is the packaged `SurveyPlatform`
directory you are working from.

Within that package, the authoritative metadata repo is:

`SurveyPlatform\repository`

This is the structure to treat as current and active.

## What Is Authoritative

Use these paths as the single source of truth:

- `SurveyPlatform\survey_tool_cli.py`
  The authoritative platform/backend CLI.
- `SurveyPlatform\survey_platform_gui.py`
  The authoritative unified platform launcher.
- `SurveyPlatform\pipelines\catalogger\repository_dashboard_gui.py`
  The packaged repository/platform dashboard opened by `survey_platform_gui.py`.
- `SurveyPlatform\repository`
  The authoritative local metadata/index/materialization repo.
- `SurveyPlatform\survey_tool_config.json`
  The package-local defaults file. It intentionally no longer pins one live source/archive path.
- `SurveyPlatform\pipelines\*`
  The active packaged pipeline source tree and specialist app surface.

## What Is Legacy Or Secondary

These should not be treated as the main repository app anymore:

- older repo/dashboard copies outside this packaged `SurveyPlatform` folder
  Useful as historical reference, but not the main platform surface.
- `survey_tool_cli.py` at the workspace root
  Still useful as source history and for non-packaged development, but the packaged platform copy should be considered the operational control plane.
- `repos\*`
  Snapshot copies only, not platform source of truth.

## Concrete Structure

Current package layout:

```text
SurveyPlatform/
  survey_tool_cli.py
  survey_platform_gui.py
  survey_tool_config.json
  README.md
  SURVEY_PLATFORM_SPEC.md
  REPOSITORY_STRUCTURE.md
  pipelines/
    catalogger/
      repository_dashboard_gui.py
      survey_catalog.py
    wincross_table_generator/
      survey_pipeline.py
      survey_pipeline_gui.py
      surveyConvertJSON.py
      wincrossTableCompile.py
    table_merger/
      sheet_merge_core.py
      sheetMerging_gui.py
      sheetMerging_cli.py
    open_end_coder/
      oe_codebook_gui.py
      oe_codebook_tool.py
    thomas_in_a_box/
      tomas_pipeline.py
      tomas_pipeline_gui.py
    auto_results/
      autoResults_gui.py
      empty_results_generator.py
  repository/
    index.json
    surveys/
      NPA####/
        survey.meta.json
        runs/
          <stage>/
            *.json
    materialized_surveys_csv_priority/
      NPA####/
        docx/
        csv/
        materialization.manifest.json
  workspace/
    NPA####/
      workflow_status.json
      workspace_manifest.json
      data_delivery_manifest.json
      inputs/
        questionnaire/
          final/
          phone/
          sms/
        data/
          current/
          timeseries_current/
          codelists/
            day_#/
        tables/
          reviewed/
        codebooks/
        results/
          templates/
      outputs/
        wincross/
          raw/
          json/
          tables/
        tomas/
        merge/
        oe/
          codebooks/
          wincross_blocks/
        results/
```

## Repository Contents

Current contents under `SurveyPlatform\repository`:

- `index.json`
  Repository-wide survey index used by the GUI and `survey list`.
- `surveys\`
  One folder per discovered survey workspace.
- `materialized_surveys_csv_priority\`
  Local curated copies collected from the archive using the current strict materialization rules.

Current observed counts:

- `463` survey metadata folders under `repository\surveys`
- `463` materialized survey folders under `repository\materialized_surveys_csv_priority`

## Metadata Model

Each survey metadata folder should be treated as the local record for one survey:

- `repository\surveys\NPA####\survey.meta.json`

This file is the main per-survey record and should hold:

- survey identity
- source/archive directory references
- discovered file inventory
- categorization
- legacy status summary
- stage-aware status map
- recent run history summary

Platform stage ids currently modeled:

- `wincross`
- `catalog`
- `merge`
- `oe`
- `tomas`
- `results`

## Operational Model

The repository layer should be understood as three separate things:

1. Discovery/index
2. Survey metadata
3. Local materialization

Those map to concrete locations:

- Discovery/index:
  `SurveyPlatform\repository\index.json`
- Survey metadata:
  `SurveyPlatform\repository\surveys\NPA####\survey.meta.json`
- Local materialization:
  `SurveyPlatform\repository\materialized_surveys_csv_priority\NPA####\...`
- Local working outputs:
  `SurveyPlatform\workspace\NPA####\...`

## Input vs Local Repo

The input/source tree is read-only and is not the same thing as the local repo:

- Source/archive tree:
  User-selected at scan time. Typical archive layouts are `Client\NPA####` and `Client\<bucket>\NPA####`.
- Local platform repo:
  `SurveyPlatform\repository`

The source root is a user-selected scan input, not something that has to stay fixed inside the package:

- GUI:
  `Repository root`, `Source root`, and `Discovery`
- CLI:
  `repo scan --root ... --source-root ... --discovery-mode ...`

That distinction is critical:

- `repo scan` reads the selected source tree and writes local metadata into `SurveyPlatform\repository`
- `repo materialize` reads discovered source-backed files and copies curated outputs into a local folder
- Guided workflow outputs are written to `SurveyPlatform\workspace\NPA####`
- neither operation should treat the source tree as the metadata repo root

## Current Workflow

The concrete intended workflow is:

1. Launch the platform from `SurveyPlatform`.
2. Set the desired `Source root` and `Discovery` mode.
3. Run `Repo Scan`.
4. Review surveys in `Survey Workspaces`.
5. Select `Main survey selected`.
6. Use guided workflows or advanced specialist editors.
7. Materialize curated local copies only when needed.

CLI equivalents:

```powershell
cd <workspace>\SurveyPlatform
.\run_survey_platform.bat repo scan --root .\repository
.\run_survey_platform.bat survey list --root .\repository
.\run_survey_platform.bat survey show --root .\repository NPA3789
.\run_survey_platform.bat repo materialize --root .\repository --out .\repository\materialized_surveys_csv_priority --survey NPA3789
```

## Shortcomings To Resolve

This is the concrete hardening list for the repo layer:

1. Remove ambiguity about the active app.
   Decision: `SurveyPlatform` is authoritative as the repo control plane. Specialist apps under `SurveyPlatform\pipelines\*` remain active day-to-day tools.

2. Strengthen stage truth.
   Today several stages are inferred from file presence. Over time, each stage should rely more on stage manifests and less on heuristics.

3. Complete `survey run`.
   Today only `wincross` and `merge` are implemented as first-class platform stage runs.

4. Clarify GUI labeling.
   The GUI should keep distinguishing:
   - `Repository root` = local metadata repo
   - `Source root` = read-only archive/input tree

5. Keep materialization intentionally narrow.
   The strict file selectors are a feature, not a bug, but they should continue to evolve from explicit rules rather than broad copying.

## Final Rule

If there is ever a conflict between older repo/dashboard behavior and the packaged platform behavior, prefer:

- `SurveyPlatform\survey_tool_cli.py`
- `SurveyPlatform\pipelines\catalogger\repository_dashboard_gui.py`
- `SurveyPlatform\repository`

That is the one solid structure to keep building on.

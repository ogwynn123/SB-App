# Survey Platform Spec

Status: Draft
Date: 2026-03-19
Scope: Align the existing survey pipelines into one platform without rewriting the stage engines or moving survey files.

## Goals

- Make `NPA####` the canonical survey workspace object across the platform.
- Keep the existing pipeline engines separate, but expose them through one metadata model, one command surface, and one dashboard.
- Add stage-aware run history and artifact tracking without breaking the current repository/index flow.
- Preserve current survey folders, current generated artifacts, and current repo/search/link behavior during rollout.

## Non-Goals

- Do not merge all pipeline logic into one file or one monolith.
- Do not move survey artifacts out of `pipelines/wincross_table_generator/NPA_Surveys`.
- Do not break current `repo scan`, `repo status`, question indexing, or `links.json` semantics.
- Do not replace specialist GUIs before the dashboard/control plane exists.

## Current Constraints

The current repository already has the right raw shape for a platform:

- The survey workspace root is effectively `pipelines/wincross_table_generator/NPA_Surveys/NPA####`.
- In the current data set, all 37 survey folders share the same core WinCross bundle:
  - `DOCX`
  - `PDF`
  - `RAW.txt`
  - `JSON.json`
  - `TABLES.autogen.txt`
- Optional downstream artifacts are sparse:
  - 13/37 also have legacy `TABLES.txt`
  - 4/37 have timeseries CSV outputs
  - 2/37 have base CSV outputs
  - 1/37 has a codebook/codelist artifact

This means the platform should optimize for one common path plus optional branches:

1. WinCross ingest
2. Catalog/index
3. Optional merge
4. Optional OE
5. Optional TOMAS
6. Optional results generation

## Sources Of Truth

The platform should treat these areas differently:

- `pipelines/*`
  Purpose: stage engine source code and stage-specific tools
- `pipelines/wincross_table_generator/NPA_Surveys/NPA####`
  Purpose: canonical survey workspace and user-facing artifacts
- `repository/*`
  Purpose: platform metadata, search/index, cross-survey links, run history
- `repos/*`
  Purpose: legacy or duplicated snapshots; not a platform source of truth

## Platform Model

### Survey Workspace

One survey workspace is one `NPA####` folder plus its linked metadata in `repository/surveys/NPA####`.

Required workspace identity:

- `survey_code`
- `survey_id`
- `primary_source_dir`
- `source_dirs[]`
- `files` grouped by artifact kind
- `categorization` (`region`, `client`)

### Stage Registry

The platform should model each pipeline as a stage, even if the underlying implementation stays in separate modules.

Recommended stage ids:

- `wincross`
- `catalog`
- `merge`
- `oe`
- `tomas`
- `results`

Recommended dependency order:

- `wincross`: no platform dependency
- `catalog`: depends on `wincross`
- `merge`: usually depends on `wincross`, optionally consults `catalog`/`links`
- `oe`: depends on survey CSV/XLSX presence, optionally on `merge`
- `tomas`: independent branch, uses phone/sms docx/pdf pairs
- `results`: depends on report `docx` plus schema labels from `tables/json`

### Stage Status Model

Not every stage applies to every survey. The platform needs to distinguish unsupported from ready.

Recommended status enum:

- `not_applicable`
- `missing_inputs`
- `ready`
- `running`
- `succeeded`
- `failed`
- `stale`

Interpretation:

- `not_applicable`: this workspace does not support that stage
- `missing_inputs`: the stage could apply, but required inputs are absent
- `ready`: required inputs exist and outputs are missing or outdated
- `running`: an active run is in progress
- `succeeded`: the latest run completed and outputs exist
- `failed`: the latest run failed
- `stale`: outputs exist but upstream inputs changed afterward

## Stage Catalog

| Stage | Engine | Canonical Inputs | Canonical Outputs | Ready When |
| --- | --- | --- | --- | --- |
| `wincross` | `survey_pipeline.py` | `docx`, `pdf` or `raw_input` | `RAW.txt`, `JSON.json`, `TABLES.autogen.txt`, optional translated raw/json | docx/pdf pair exists or raw input exists |
| `catalog` | `survey_tool_cli.py repo scan/questions-*`, `survey_catalog.py` | survey workspace artifacts plus `repository` root | `survey.meta.json`, `index.json` row, `questions.sqlite` rows, optional `links.json` references | survey exists and at least JSON/TABLES artifacts exist |
| `merge` | `sheet_merge_core.py` | primary/secondary CSV/XLSX, join columns, optional survey JSONs, optional repo links | merged CSV/XLSX, report CSV, archive copy, `timeseries_master.json`, `merge_runs/*.json`, optional repo links | merge candidates exist and merge config is resolvable |
| `oe` | `oe_codebook_tool.py` | survey CSV/XLSX, `question-col`, companion code columns | codebook CSV/XLSX, rendered draft WinCross block TXT | survey data with OE columns exists |
| `tomas` | `tomas_pipeline.py` | phone docx/pdf + sms docx/pdf, API key/model settings | `RAW.en`, `RAW.es`, `JSON.es`, optional `JSON.en`, compare reports, optional rebuilt Spanish docx, manifest JSON | bilingual phone/sms pair exists and dependencies/config are present |
| `results` | `empty_results_generator.py` now; later broader auto-results | report `docx`, schema labels from `tables/json` | `EMPTY.docx` or later populated results outputs | report docx exists and schema labels can be loaded |

## Metadata Design

### `survey.meta.json` v2

Keep the current v1 fields stable:

- `files`
- `status`
- `pipelines_completed`
- `categorization`
- `last_run`

Add new stage-aware metadata alongside them:

```json
{
  "schema_version": 2,
  "survey_code": "3789",
  "survey_id": "NPA3789",
  "source_root": "pipelines\\wincross_table_generator\\NPA_Surveys",
  "source_dirs": [
    "pipelines\\wincross_table_generator\\NPA_Surveys\\NPA3789"
  ],
  "primary_source_dir": "pipelines\\wincross_table_generator\\NPA_Surveys\\NPA3789",
  "files": {
    "docx": ["..."],
    "pdf": ["..."],
    "raw_txt": ["..."],
    "survey_json": ["..."],
    "tables_txt": ["..."],
    "csv": ["..."]
  },
  "status": {
    "stage": "tables_ready",
    "has_docx": true,
    "has_pdf": true,
    "has_raw_txt": true,
    "has_json": true,
    "has_tables_txt": true,
    "has_csv": true
  },
  "pipelines_completed": [
    "wincross_table_generator"
  ],
  "categorization": {
    "region": "IL-08",
    "client": "Bean"
  },
  "last_run": "2026-03-10T13:56:23Z",
  "updated_at": "2026-03-19T00:00:00Z",
  "stages": {
    "wincross": {
      "status": "succeeded",
      "supported": true,
      "depends_on": [],
      "last_run_id": "wincross_20260319T000000Z",
      "last_run_at": "2026-03-19T00:00:00Z",
      "inputs": {
        "docx": ["..."],
        "pdf": ["..."]
      },
      "outputs": {
        "raw_txt": ["..."],
        "survey_json": ["..."],
        "tables_txt": ["..."]
      },
      "warnings": []
    },
    "catalog": {
      "status": "succeeded",
      "supported": true,
      "depends_on": ["wincross"],
      "last_run_id": "catalog_20260319T000100Z",
      "last_run_at": "2026-03-19T00:01:00Z",
      "inputs": {
        "survey_json": ["..."],
        "tables_txt": ["..."]
      },
      "outputs": {
        "survey_meta": ["repository\\surveys\\NPA3789\\survey.meta.json"],
        "index_row": ["repository\\index.json"],
        "question_index": ["repository\\questions.sqlite"]
      },
      "warnings": []
    },
    "merge": {
      "status": "succeeded",
      "supported": true,
      "depends_on": ["wincross"],
      "last_run_id": "merge_20260309T143945119573Z",
      "last_run_at": "2026-03-09T14:39:45Z",
      "inputs": {
        "csv": ["..."]
      },
      "outputs": {
        "merged_csv": ["...\\NPA3789ts.csv"],
        "merge_catalog": ["...\\timeseries_master.json"],
        "merge_run": ["...\\merge_runs\\merge_20260309T143945119573Z.json"]
      },
      "warnings": []
    },
    "oe": {
      "status": "not_applicable",
      "supported": false,
      "depends_on": ["merge"],
      "warnings": []
    },
    "tomas": {
      "status": "not_applicable",
      "supported": false,
      "depends_on": [],
      "warnings": []
    },
    "results": {
      "status": "ready",
      "supported": true,
      "depends_on": ["wincross"],
      "warnings": []
    }
  },
  "recent_runs": [
    {
      "run_id": "catalog_20260319T000100Z",
      "stage": "catalog",
      "status": "succeeded",
      "finished_at": "2026-03-19T00:01:00Z"
    },
    {
      "run_id": "merge_20260309T143945119573Z",
      "stage": "merge",
      "status": "succeeded",
      "finished_at": "2026-03-09T14:39:45Z"
    }
  ]
}
```

Design notes:

- `status` stays as the legacy scalar file-presence summary.
- `stages` becomes the platform truth for stage-by-stage status.
- `recent_runs` is a dashboard convenience cache, not the source of truth.
- `supported=false` is how the platform represents optional branches cleanly.

### `index.json` v2

Keep the current top-level summary and flat survey rows, but add per-stage summary fields for the dashboard.

Recommended additional row fields:

- `wincross_status`
- `catalog_status`
- `merge_status`
- `oe_status`
- `tomas_status`
- `results_status`
- `available_actions[]`

Example row shape:

```json
{
  "survey_code": "3789",
  "survey_id": "NPA3789",
  "stage": "tables_ready",
  "last_run": "2026-03-10T13:56:23Z",
  "primary_source_dir": "pipelines\\wincross_table_generator\\NPA_Surveys\\NPA3789",
  "pipelines_completed": ["wincross_table_generator"],
  "has_json": true,
  "has_tables_txt": true,
  "region": "IL-08",
  "client": "Bean",
  "wincross_status": "succeeded",
  "catalog_status": "succeeded",
  "merge_status": "succeeded",
  "oe_status": "not_applicable",
  "tomas_status": "not_applicable",
  "results_status": "ready",
  "available_actions": ["show", "run:results", "run:merge"]
}
```

### Run Manifest Layout

Do not replace existing stage-owned artifacts such as `merge_runs/*.json`. Add a common run history layout under `repository`.

Recommended layout:

- `repository/surveys/NPA3789/runs/wincross/<run_id>.json`
- `repository/surveys/NPA3789/runs/catalog/<run_id>.json`
- `repository/surveys/NPA3789/runs/merge/<run_id>.json`
- `repository/surveys/NPA3789/runs/oe/<run_id>.json`
- `repository/surveys/NPA3789/runs/tomas/<run_id>.json`
- `repository/surveys/NPA3789/runs/results/<run_id>.json`

Recommended manifest shape:

```json
{
  "schema_version": 1,
  "run_id": "merge_20260319T001500Z",
  "survey_code": "3789",
  "survey_id": "NPA3789",
  "stage": "merge",
  "status": "succeeded",
  "started_at": "2026-03-19T00:15:00Z",
  "finished_at": "2026-03-19T00:15:08Z",
  "engine": {
    "module": "pipelines/table_merger/sheet_merge_core.py",
    "entrypoint": "survey_tool_cli.py merge"
  },
  "inputs": {
    "primary": "...",
    "secondary": "...",
    "primary_join": "survnum",
    "secondary_join": "survnum"
  },
  "outputs": {
    "output_path": "...",
    "report_path": "...",
    "archive_path": "...",
    "catalog_run_path": "..."
  },
  "warnings": [],
  "metrics": {
    "mapping_count": 261
  }
}
```

## CLI Surface

Keep the current commands:

- `pipeline`
- `merge`
- `catalog`
- `repo`

Add a platform-facing survey command layer on top of them:

- `survey list`
- `survey show <survey-id>`
- `survey detect <survey-id>`
- `survey run <survey-id> <stage>`
- `survey history <survey-id>`
- `survey open <survey-id> --artifact <kind>`

Recommended examples:

```powershell
python survey_tool_cli.py survey list --region IL --merge-status succeeded
python survey_tool_cli.py survey show NPA3789
python survey_tool_cli.py survey detect NPA3789
python survey_tool_cli.py survey run NPA3789 wincross -- --overwrite
python survey_tool_cli.py survey run NPA3789 merge -- --secondary .\pipelines\wincross_table_generator\NPA_Surveys\NPA3777\NPA3777ts.csv
python survey_tool_cli.py survey history NPA3789 --stage merge
```

Design rules:

- `survey run` is a platform wrapper that resolves the workspace and writes run manifests.
- Stage-specific arguments should be forwarded after `--` instead of forcing a premature universal abstraction.
- Existing `pipeline`, `merge`, `repo`, and `catalog` commands remain valid and become implementation-level entrypoints.

## UI Surface

Do not merge all specialist GUIs immediately. Build one dashboard shell first, and let it launch stage-specific tools where needed.

Recommended dashboard evolution from `repository_dashboard_gui.py`:

### Portfolio View

- one row per survey
- categorization columns
- stage chips/columns for:
  - `wincross`
  - `catalog`
  - `merge`
  - `oe`
  - `tomas`
  - `results`
- filters by:
  - region
  - client
  - stage status
  - survey code

### Survey Detail View

- workspace summary
- artifact list by kind
- stage cards:
  - status
  - last run
  - warnings
  - run button
  - open output button

### Run History View

- per-survey run table
- filter by stage
- open manifest
- open main output

### Question Browser

- keep the existing question browser/search tab
- add stage filters only after the stage metadata is live

### GUI Strategy

Phase 1 platform actions may still delegate to existing tools:

- merge GUI
- WinCross GUI
- repository dashboard panels
- OE GUI if needed

That is acceptable. The platform value is the shared survey registry and run/status model, not immediate GUI rewrites.

## Recommended Code Organization

Do not move the current engines. Add a thin platform layer next to `survey_tool_cli.py`.

Recommended new modules:

- `survey_platform_registry.py`
  - stage registry and dependency definitions
- `survey_platform_detect.py`
  - survey workspace detection and stage readiness logic
- `survey_platform_runs.py`
  - run id generation, manifest writing, recent-run summaries
- `survey_platform_artifacts.py`
  - artifact normalization and kind mapping

Primary integration points:

- extend `survey_tool_cli.py` with `survey` subcommands
- extend repo metadata builders to emit `stages` and `recent_runs`
- extend `repository_dashboard_gui.py` to display stage-aware rows

## Rollout Plan

### Phase 1: Schema Additive Only

- Add `schema_version: 2` support for `survey.meta.json`
- Preserve v1 fields and behavior
- Add `stages` and `recent_runs`
- Add `*_status` projections to `index.json`

### Phase 2: Detection Before Execution

- Implement stage detection from existing artifacts
- Populate stage status during `repo scan`
- Do not change how stage engines run yet

### Phase 3: Platform Wrapper Commands

- Add `survey list`
- Add `survey show`
- Add `survey detect`
- Add `survey run`
- Add `survey history`

### Phase 4: Dashboard Upgrade

- add stage columns/chips to the existing dashboard
- add survey detail pane with artifact/run summary
- keep question browser intact

### Phase 5: Specialist Tool Integration

- launch or embed stage-specific GUI actions from the dashboard
- optionally add more platform-native forms for the most common stage actions

## Compatibility Rules

- `status.stage` remains until all current CLI/tests/UI consumers migrate
- `pipelines_completed` remains, but becomes a legacy compatibility field
- `links.json` keeps its current schema and meaning
- `questions.sqlite` rebuild/search must continue to read current `files`, `status`, and `categorization`
- `_sync_repo_from_pipeline` should keep the repository-wide view complete, even if stage updates become incremental later

## Immediate First Build

The first useful implementation slice is:

1. extend `survey.meta.json` and `index.json` with stage-aware metadata
2. add stage detection for `wincross`, `catalog`, `merge`, `oe`, `tomas`, and `results`
3. add `survey list` and `survey show`
4. upgrade the repository dashboard to display stage columns

That gets the platform from "collection of tools" to "single system with one workspace model" without destabilizing the existing pipelines.

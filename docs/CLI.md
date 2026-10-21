# Survey Tool CLI

`survey_tool_cli.py` is the single command-line entry point for the platform.
Run it from the `SurveyPlatform` root:

```powershell
py -3 .\survey_tool_cli.py <command> ...
.\run_survey_platform.bat <command> ...
```

Command groups:

| Command | Purpose |
|---|---|
| `survey` | Platform-facing workspace commands: `list`, `show`, `detect`, `history`, `run` |
| `repo` | Local repository metadata: `init`, `scan`, `status`, `materialize`, `questions-*`, `link` |
| `pipeline` | WinCross pipeline: DOCX/PDF -> RAW -> JSON -> TABLES, BANNERS, COVER |
| `merge` | Sheet merge: primary + secondary -> merged output, report, archive |
| `catalog` | Global question catalog: `rebuild`, `search`, `suggest-links`, `links`, `approve-link`, `reject-link` |

Every command accepts `--help`. The paths below are placeholders; survey
source folders live in the user-selected archive tree, not inside this package.

## Shared config

Defaults come from the machine-local, git-ignored `survey_tool_config.json` at
the package root. Most commands accept:

- `--save-defaults` to store the current options as defaults
- `--ignore-config` to ignore saved defaults for one run
- `--config <path>` (before the command) to use another config file

## Survey workspaces

```powershell
py -3 .\survey_tool_cli.py survey list --region IL --merge-status succeeded
py -3 .\survey_tool_cli.py survey show NPA3789
py -3 .\survey_tool_cli.py survey detect NPA3789
py -3 .\survey_tool_cli.py survey history NPA3789 --stage merge
py -3 .\survey_tool_cli.py survey run NPA3789 wincross -- --overwrite
py -3 .\survey_tool_cli.py survey run NPA3789 merge -- --secondary "C:\path\to\NPA3777ts.csv"
```

- `survey list` filters by `--survey`, `--region`, `--client`, `--stage`, and
  per-stage status (`--wincross-status`, `--catalog-status`, `--merge-status`,
  `--oe-status`, `--tomas-status`, `--results-status`).
- `survey run` resolves the workspace from repository metadata and records a
  run manifest. Only `wincross` and `merge` are first-class stages; the other
  stages still run through their specialist applications.
- Stage-specific arguments are forwarded after `--`.

Stage statuses are `not_applicable`, `missing_inputs`, `ready`, `running`,
`succeeded`, `failed`, and `stale`. See `docs\design\SURVEY_PLATFORM_SPEC.md` for
the metadata model behind them.

## Repository

Scan an archive tree into local metadata, then rebuild the question index.
Pass the resolved repository path to both `--root` and `--db` so an older
machine-specific setting cannot redirect the rebuild:

```powershell
$repo = (Resolve-Path .\repository).Path
py -3 .\survey_tool_cli.py repo scan --root $repo --source-root "C:\path\to\NPA Archive - Documents" --discovery-mode archive
py -3 .\survey_tool_cli.py repo questions-rebuild --root $repo --db (Join-Path $repo "questions.sqlite")
```

Other repository commands:

```powershell
py -3 .\survey_tool_cli.py repo init --root .\repository
py -3 .\survey_tool_cli.py repo status --root .\repository
py -3 .\survey_tool_cli.py repo status --root .\repository --survey NPA3789
py -3 .\survey_tool_cli.py repo scan --root .\repository --survey NPA3789 --dry-run
py -3 .\survey_tool_cli.py repo materialize --root .\repository --out .\repository\materialized_surveys_csv_priority --survey NPA3789
```

- `repo scan` reads the source tree and writes metadata into the local
  repository. It preserves existing `region`/`client` categorization.
- `--discovery-mode archive` handles `Client\NPA####` and
  `Client\<bucket>\NPA####` layouts; `standard` expects `NPA####` folders.
- `repo materialize` is the separate copy step for curated local files.
  Use `--kind` to limit artifact kinds and `--dry-run` to preview.

### Question search

```powershell
py -3 .\survey_tool_cli.py repo questions-search --root .\repository --query "vote for" --state IL --limit 30
py -3 .\survey_tool_cli.py repo questions-frequency --root .\repository --query "vote for" --state WI --limit 20
```

- `--match-mode` is `all_words` (default), `exact`, or `any_word`.
- Filters: `--region`, `--state`, `--client`, `--family`, `--survey`.
- `state` is the first two characters of the survey's `region` (for example
  `IL-08` -> `IL`).

### Cross-survey links

Links are stored in `repository\links.json`.

```powershell
py -3 .\survey_tool_cli.py repo link add --root .\repository --left-survey NPA3789 --left-qid 15 --right-survey NPA3777 --right-qid 14 --status approved --note "Same issue open-end"
py -3 .\survey_tool_cli.py repo link suggest --root .\repository --left-survey NPA3789 --right-survey NPA3777 --threshold 80 --limit 25
py -3 .\survey_tool_cli.py repo link suggest --root .\repository --left-survey NPA3789 --right-survey NPA3777 --threshold 80 --auto-approve-threshold 92 --apply
py -3 .\survey_tool_cli.py repo link list --root .\repository --survey NPA3789 --status approved --limit 50
py -3 .\survey_tool_cli.py repo link set-status --root .\repository --id 12 --status rejected
```

## WinCross pipeline

```powershell
py -3 .\survey_tool_cli.py pipeline --docx "C:\path\to\NPA3789.docx" --pdf "C:\path\to\NPA3789.pdf"
py -3 .\survey_tool_cli.py pipeline --root "C:\path\to\surveys" --recursive --overwrite
```

- Output paths can be set with `--raw-out`, `--json-out`, `--tables-out`,
  `--banners-out`, and `--cover-out`; `--skip-tables`, `--skip-banners`, and
  `--skip-cover` turn stages off.
- `--raw-input` starts from an existing RAW file instead of DOCX/PDF.
- `--translate-spanish` with the `--tomas-*` options runs the TOMAS translation
  step and requires OpenAI credentials.
- `--repo-sync` updates repository metadata after the run.

Wrapper used by the WinCross GUI EXE:
`pipelines\wincross_table_generator\unified_pipeline.py` (or `.bat`), which
forwards to `survey_tool_cli.py pipeline`.

## Sheet merge

```powershell
py -3 .\survey_tool_cli.py merge --primary current.csv --secondary prior_ts.csv --primary-join survnum --secondary-join survnum --preflight
py -3 .\survey_tool_cli.py merge --primary current.csv --secondary prior_ts.csv --primary-join survnum --secondary-join survnum --dry-run
py -3 .\survey_tool_cli.py merge --primary current.csv --secondary prior_ts.csv --primary-join survnum --secondary-join survnum --row-order secondary_first
```

Useful options:

- `--inspect`, `--preflight`, `--dry-run`, `--show-config`
- `--map PRIMARY=SECONDARY`, `--map-file`, `--block-primary`,
  `--mapping-mode {auto,manual_only}`
- `--row-order {primary_first,secondary_first}`; guided daily merges use
  `secondary_first`
- `--conflict-policy {skip,append,abort}` and the duplicate policies
- `--report-dir`, `--archive-dir`, `--output`, `--output-mode`

Question-similarity checks against survey JSONs:

```powershell
py -3 .\survey_tool_cli.py merge --primary current.csv --secondary prior_ts.csv --primary-join survnum --secondary-join survnum --primary-survey-json NPA3801JSON.json --secondary-survey-json NPA3787JSON.json --question-similarity-policy warn --question-similarity-threshold 60
```

- `warn` keeps mappings and prints low-similarity warnings.
- `drop` removes low-similarity mapped question columns before the merge.
- `abort` fails when low-similarity mapped question columns exist.
- Pairs that are `approved` in `repository\links.json` are exempt from `drop`
  and `abort`. `--repo-link-write-mappings` writes merge mappings back as links.

Automatic timeseries layering applies when the secondary looks like
`NPA####ts...`, has a `timeseries` column, and the primary is a non-`ts`
`NPA####` file:

- Primary rows get the next timeseries code (`max(secondary.timeseries) + 1`,
  or `1` when the secondary is blank or non-numeric).
- Duplicate join keys are appended as a new wave.
- Output is named `NPA####ts.csv` from the primary survey code.
- Unmapped secondary columns are carried forward with a `####_` prefix unless
  they already have one.

The reviewed-mapping rules that the GUI and guided merges rely on are in
`AGENT_HANDOFF.md` under "Sheet Merge contract".

Wrapper used by the Sheet Merge GUI EXE:
`pipelines\table_merger\unified_merge.py` (or `.bat`), which forwards to
`survey_tool_cli.py merge`.

## Global catalog

```powershell
py -3 .\survey_tool_cli.py catalog rebuild
py -3 .\survey_tool_cli.py catalog search --query "right direction" --limit 20 --source json
```

The Question Browser and `repo questions-search` use the separate
`repository\questions.sqlite` index, which is the one to keep current for
day-to-day question lookup.

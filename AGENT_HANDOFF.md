# SurveyPlatform agent handoff

Status date: 2026-10-21 (America/New_York)  
Authoritative project: `C:\Users\normi\venv\SurveyPlatform`  
Git branch: `main` (see `git log` for the current head)

This document is the continuation context for another coding agent. It combines
the stable project documentation with the workflow decisions established during
the current working session. Read this before changing any pipeline behavior.

## Fast start for the next agent

1. Work from `C:\Users\normi\venv\SurveyPlatform`.
2. Run `git status --short` before editing. If the tree has uncommitted user
   work, do not reset, revert, clean, or overwrite it.
3. Treat this packaged `SurveyPlatform` directory as the authoritative control
   plane. Older copies elsewhere under `C:\Users\normi\venv` are reference only.
4. Read the component README named in the relevant section below, inspect the
   current implementation and tests, and add a regression test for behavioral
   changes.
5. Prefer source launchers while debugging. Specialist launchers are EXE-first,
   so an old `dist` build can hide a correct source change. After changing a
   bundled module, run `.\rebuild_apps.bat` (it backs up, rebuilds stale EXEs,
   and launch-checks them; TOMAS only when named).
6. After cross-pipeline work, run `.\run_tests.bat --acceptance` from the
   project root. The acceptance stage uses synthetic data and does not touch
   archive projects.

Suggested continuation prompt:

> Use `C:\Users\normi\venv\SurveyPlatform\AGENT_HANDOFF.md` as the authoritative
> handoff for this survey workflow. Inspect the working tree before making
> changes, preserve any uncommitted modifications, and follow the component
> contracts and regression-test commands in the handoff. The packaged
> `SurveyPlatform` directory is the authoritative implementation.

## Repository state

As of 2026-10-21 all handoff work is committed on `main` (no remote), split by
area: WinCross rules, trend updater, sheet merge, Auto Results, quota scraper
and browser review, the local browser workbench, and this document. Old root
scratch files were moved into the ignored `.tmp_archive/` folder; keep
`.tmp_tests/` in place because the merge tests use it as their temp directory.

Later on 2026-10-21 the project was tidied: about 850 MB of stale
`build_rebuild*`/`dist_rebuild`/`working_snapshots` output was deleted, unused
legacy scripts (old Auto Results scripts, `surveyJSONer.py`, `sheetMerging.R`,
the legacy WinCross GUI, one-off catalog audits) were removed from git, and the
Quota Checker and Trend Table Updater EXEs were rebuilt from current source.
The previous EXEs are in `.tmp_archive\exe_backup_20261021\`. The desktop
shortcuts target each pipeline's normal `dist\` EXE.

Still run `git status --short` before editing and preserve any user work.

## System model

SurveyPlatform has three layers:

1. The source/archive survey tree is user-selected input, usually below
   `C:\Users\normi\OneDrive - Normington Petts\NPA Archive - Documents`. Treat
   it as read-only unless the user explicitly requests an output there.
2. `SurveyPlatform\repository` is the local metadata and question-search index.
3. `SurveyPlatform\workspace\NPA####` is the local working area for curated
   inputs, generated outputs, maps, manifests, and review files.

Repository discovery and local materialization are separate operations. A repo
scan reads the selected archive tree and updates local metadata; it must not
turn the archive folder into the metadata root. Pipeline runs do not implicitly
rescan the repository.

The main entry points are:

| Need | Entry point |
|---|---|
| Unified CLI | `survey_tool_cli.py` or `run_survey_platform.bat` |
| Full dashboard | `run_survey_platform_gui.bat` |
| Daily survey launcher | `run_survey_ops_lite.bat` |
| Local browser workbench | `run_survey_browser.bat` |
| WinCross/Table Gen | `pipelines\wincross_table_generator\open_survey_pipeline_gui.bat` |
| Sheet Merge | `pipelines\table_merger\open_sheet_merge_gui.bat` |
| Open-End Coder | `pipelines\open_end_coder\Launch_OE_Codebook_GUI.bat` |
| Auto Results | `pipelines\auto_results\open_autoResults_gui.bat` |
| Trend Tables | `pipelines\trend_table_updater\open_trend_table_updater.bat` |
| TOMAS | `pipelines\thomas_in_a_box\open_tomas_pipeline_gui.bat` |

Specialist launchers use a bundled EXE when present and fall back to source.
When testing source changes, run the Python entry point directly or rebuild the
EXE before judging the launcher.

## Daily launcher contract

`Project Startup` operates on the selected archive survey folder. It creates
only missing `Data`, `Data\Partial`, `Job`, and `Job\Table Gen` folders. It then
recursively finds the newest DOCX under `Qst` whose stem ends in `Final`, optionally
followed by a date (`FINAL 9.30.26`, `Final 10-19-2026`), skipping Spanish versions, and
copies it safely to `Job\Table Gen`: identical files are left alone, older
copies are updated, and a newer differing destination is not overwritten.

The launcher passes survey ID, project root, and working folder to each tool.
It should not guess input files. Its portable manifest is written only after a
tool is launched at `Job\.surveyplatform\project.json`.

The launcher is the single starting point: it also runs Sample Append and
Preliminary QC itself, and opens the repository dashboard and browser
workbench. Sample Append defaults to the newest `Data\NPA####ts*.csv` and
stores the column mapping in the manifest; Preliminary QC writes to
`Job\QC\<timestamp>`. The Activity log lists stale packaged EXEs.

## Local browser workbench

The browser app is a lightweight front end over existing pipeline cores, not a
replacement implementation. It binds only to `127.0.0.1`, normally at
`http://127.0.0.1:8765/`, and uses a temporary request token. Start it with:

```powershell
.\run_survey_browser.bat
```

Keep its terminal open while using it. Current tools are:

- Table Gen
- Sheet Merge
- Open-End Coder
- Question Browser
- Auto Results
- Sample Quota Checker

The first five were the requested essential scope; the quota checker was added
after its extraction rules were reviewed. Simplification is acceptable, but
the browser must keep using the production cores and normal Windows file paths.
The quota review remains read-only.

Primary files: `local_browser_app/server.py`, `services.py`, `static/app.js`,
`static/index.html`, and `static/styles.css`. See `local_browser_app/README.md`.

## WinCross/Table Gen behavioral contract

Primary implementation:

- questionnaire parsing: `pipelines\wincross_table_generator\surveyConvertJSON.py`
- question classification: `question_attributes.py`
- table compilation: `wincrossTableCompile.py`
- orchestration: `survey_pipeline.py`
- regressions: `test_wincrossTableCompile.py`, `test_question_attributes.py`,
  and `test_surveyConvertJSON.py`

The end-to-end pipeline is DOCX/PDF -> RAW -> JSON -> WinCross tables, banners,
and cover output. The GUI discovers exact-stem DOCX/PDF pairs.

### Banner and ranking rules

Current constants are:

```text
Normal:           OV,OI,O%,BR,RV,S2,P0,SA,SP
Unranked summary: OV,OI2,O%,BR,RV,S2,P0,SA,SP
Ranked summary:   OV,OD,OI2,O%,R%,BR,RV,S2,P0,SA,SP
```

Rank battery comparison summaries, including intensity/total/difference
summaries for more/less likely, favorable/unfavorable, convincing,
describes-well, focus importance, 0-10 favorability, and candidate
describes-better batteries.

Do not rank:

- Right Direction summary tables
- Candidate Communication summaries, including the two-question digital/mail
  version and the four-question supporting/attacking version

These exceptions deliberately use the unranked `OI2` banner.

### Past presidential vote

A presidential vote-recall table must contain:

- `TOTAL ANSWERING^TN^1`
- the two named candidates, Other, and the actual did-not-vote response
- Refused when it exists
- a divider
- `AMONG <YEAR> VOTERS`
- the two candidates and Other using the among-voter denominator

The did-not-vote selector is discovered from the actual answer label. Never
hard-code it as `(4)`. The same applies to optional Refused. The header is
`Qx. <YEAR> Vote for President` when a year is found.

### Vote certainty

Vote certainty is generated only when an immediately preceding vote question
can be paired with a 3- or 4-response certainty question. Accepted certainty
responses are:

- `Absolutely certain` or `Very certain`
- `Somewhat certain`
- a recognized not-certain variant, displayed as `Not really certain`
- optional Don't know

For a vote with lean rows, each candidate block uses candidate plus lean codes.
For a valid direct vote without leans, each nonterminal candidate gets a block.
Other, Don't know, and Refused are excluded from candidate blocks. The table
ends with the vote question's real undecided code. Header: `Qx. Vote Certainty`.

### Might-consider-voting follow-ups

A candidate-consideration question is recognized by classification or wording
like “chance you might consider voting,” with `Might consider` and `No chance`
answers. It searches backward for a routed vote question and uses `[IF Qx=...]`
codes plus the candidate name to identify the omitted candidate/lean pair.

Append after the normal response rows:

```text
VOTING <CANDIDATE>^<candidate+lean selector>^NS
VOTING FOR/WOULD CONSIDER^<candidate+lean> OR <follow-up might-consider>^NS
not <CANDIDATE>^<complement of candidate+lean>^HR,NS
```

Do not assume the follow-up is adjacent to the vote; the routed instruction is
authoritative. Keep the lowercase `not` label because it matches the requested
WinCross convention.

### Candidate Communication summary

Four consecutive yes/no/don't-know questions form the summary only when they
represent exactly two candidates and contain one `supporting` and one
`attacking` question for each. Candidate labels are derived from their names,
including surname particles such as `De La`.

The unranked summary includes, for each candidate:

- Supporting
- Attacking
- Both
- Either
- Neither

It then includes a `BOTH CANDIDATES` block with Supporting, Attacking, Both,
Any, None, and the hidden source line. The candidate-specific questions still
receive their normal tables. An incomplete or duplicated four-question set
must not create the summary.

### Describes-better summaries

A consistent forced-choice battery comparing two candidates creates three
ranked summaries:

- `Describes <candidate 1>`
- `Describes <candidate 2>`
- `Describes <candidate 1> minus <candidate 2>`

It accepts the expected candidate/candidate/Both/Neither/Don't know structure,
including bracketed terminal labels. Reject inconsistent candidate ordering or
codes across items.

### More/less likely and other battery summaries

The battery engine produces ranked first-intensity, total, and difference
summaries when item response profiles agree. For a less-likely scale that also
contains `Not true` and a more-likely reversal, also create the first-intensity
minus Not True/More Likely table.

Split-battery requirements:

- Conditions on every split item must include its marker-derived split
  variable, such as `num_ab(1)` or `num_ab(2)`.
- Keep the hidden split-variable rows used by WinCross positions.
- Include the same split conditions and combo rows in direct summary tables,
  total-minus-opposite tables, and first-intensity-minus-terminal/reversal
  tables.
- Repeated split cycles stay separate. A sequence A/B/A/B should yield two
  combo rows rather than one four-item combo.
- When paired items have the same subject after removing their split suffix,
  name the combo with the question letters and subject, for example
  `c/d. Farm - Combo` and `e/f. Iran - Combo`. Otherwise use `a/b. Combo`.
- Combo difference lines must calculate from the hidden positive/minuend and
  negative/subtrahend combo rows, just like ordinary item differences.

### No-difference parentheses

For placeholder battery labels, display `(No difference)` only when the survey
source has explicit brackets, including flattened cases where `[` and `]` were
split across source fields. If there are no source brackets, display
`No difference` without parentheses.

### Phone-readable title cleanup

Formatting applies to question titles only, never answer labels. Supported
examples include:

- `50 thousand` -> `50,000`
- `50 thousand dollars` -> `$50,000`
- `3 percent` -> `3%`
- `two billion dollars` -> `$2B`
- `sixty-two million dollars` -> `$62M`
- `three-point-three million dollars` -> `$3.3M`

Leave vague quantities unchanged, including `thousands of dollars`, `millions
of dollars`, and `hundreds of millions of dollars`.

Remove clear pronunciation guides from titles, for example
`Saudi Arabia [SOW-dee uh-RAY-bee-uh]` or an acronym guide such as
`DOGE [DOHJ]`. Preserve real bracketed item tags such as `[FARM]`. This cleanup
is also title-only.

## Trend Table Updater contract

Primary implementation: `pipelines\trend_table_updater\trend_table_updater_core.py`  
Tests: `test_trend_table_updater_core.py`

Normal use:

1. Load a glossary TXT, often the current Desktop `TTs.txt`.
2. Confirm inferred prior series.
3. Enter the new series and field-date label.
4. Save to a new file; do not overwrite the source unless explicitly asked.
5. Run tests and inspect the report for updated/skipped/error tables.

Key rules:

- Update only tables whose latest applicable wave is the prior series.
- Leave older histories exact; skip titles such as `Trend Table - [2022]`.
- Split at any table record, not only `TQ` or `TTREND`, so generic/non-trend
  records cannot be absorbed into the previous trend table.
- Accept normal, indented, mixed-case, legacy, and specialized IDs such as
  `TTREND`, `TTrend`, `TQ`, `TTT`, `TALLOCTREND`, and `TAVAILTREND`.
- Accept field-date labels such as `AUG 2026`, `SEP 15-17`, and `OCT 1`.
- Preserve internal divider offsets when recalculating vertical positions and
  NET CHANGE formulas.
- Extend compact aggregate selectors, for example
  `TIMESERIES (2-4,8-10)` -> `TIMESERIES (2-4,8-11)`.
- Update primary and filtered subsequences, filtered-only latest waves, and
  tables composed entirely of filtered waves.
- Correctly add a final wave/divider even when the source ends without a
  newline.
- Match NET subsets by response label, including slash-separated historical
  labels; reject ambiguous/unmatched NET labels instead of guessing.

Desktop output naming has generally been
`TTs - <field label> TS<series>.txt`. The most recent completed example was:

```text
C:\Users\normi\OneDrive - Normington Petts\Desktop\TTs - Oct 19-21 TS11.txt
```

with source `Desktop\TTs.txt`, label `OCT 19-21`, and `TIMESERIES(11)`.

## Trend marginal comparison method

When comparing old and new marginal DOCX files, do not assume they contain Word
tables. Recent files used fixed-width paragraphs. Compare shared historical
content by normalized section title plus row label, not physical row position.

Rules:

- Exclude the newly added current wave from the historical comparison.
- Compare every shared historical value and header token.
- Ranked summary tables can reorder rows, especially Q20-style summaries, so
  match by label before comparing values.
- Tables present only in the new file are “unverified/new,” not mismatches.
- Report old-only tables separately; they may be removed open ends.

The last completed comparison found 45 shared sections, 470 matched rows,
7,050 historical data cells, and 2,295 historical header tokens all exact.
The visible Q20 difference was row order from ranking, not changed values.

## Sheet Merge contract

Primary implementation: `pipelines\table_merger\sheet_merge_core.py`  
GUI: `sheetMerging_gui.py`  
Tests: `test_sheet_merge_core.py`

The primary/current file is the schema authority. Default row order is
`secondary_first`, which puts older trend rows above current rows while keeping
the primary column order.

The reviewed mapping is authoritative:

- A blank mapping means “do not fill this primary column.”
- The corresponding unmapped secondary field must still be preserved as a
  secondary-prefixed output column; it must not disappear.
- Preserve the user's reviewed/manual mapping exactly when possible.
- Manual mappings are one-to-one. A secondary column cannot be assigned to two
  primary columns.
- Shifted manual chains must first release stale auto-mapping ownership, or
  earlier reviewed pairs are incorrectly deleted.
- Base-question mappings propagate appropriate companions such as `a`, `b`,
  and `oth1`, except when the companion was explicitly mapped, cleared, or
  blocked.
- Split-assignment variables are excluded from ordinary fuzzy mapping and are
  preserved/prefixed when unmapped.
- Timeseries output must preserve secondary-only open-end companions and sort
  prefixed question columns according to the established survey-code order.
- A true prefixed-name collision should stop with a diagnostic rather than
  silently overwrite data.

After a timeseries merge, `carryover_tables.py` copies the previous wave's
Combined Demographics table(s) from `<previous project>\Job\NPA####.job` into
`<merged output stem>_carryover_combined_demos.txt` with a
`_carryover_report.md` issue register. Combined demos follow the last job in the
same region and cannot be predicted from a standalone questionnaire, so the
tables are copied verbatim. A variable is renamed only when the merge mapped it
manually/fuzzy/join to a differently named primary column; columns kept only for
older waves (`*_extra`, e.g. `3787_q10a`) are never substituted and are flagged.
Every variable/code is checked against the merged data by wave. No .job file is
edited; analysts may still choose another column (TX-15/TX-35 switched `race` to
`old_tsmr_race`). Validated on 9 consecutive-wave pairs: 7 identical to the final.

Guided daily merge saves the resolved map below
`workspace\NPA####\inputs\merge\maps` and reuses it only while the reviewed
primary/secondary headers still match. First-day setup belongs in the Advanced
Merge Editor; later deliveries can use the saved-map action.

## Auto Results contract

Primary implementation: `pipelines\auto_results\autoResults_gui.py`  
Empty-template implementation: `empty_results_generator.py`  
Tests: `test_autoResults_alignment.py`

Auto Results supports DOCX or XLSX as the value source, DOCX templates, the
fix/no-loss processing path, and alignment reports. It can run with XLSX as
primary even without a DOCX marginal.

The two common failures must have distinct messages:

- A selected DOCX/XLSX is 0 bytes: show `Empty Input File`, name the exact file,
  and suggest choosing/exporting a populated copy or waiting for OneDrive.
- A selected or output document is open/locked: show
  `Word Document Open or Locked`, list the selected paths, and suggest closing
  Word and the File Explorer preview pane.

Also distinguish missing files and invalid/non-Office ZIP files. Do not bury
the common cases in a generic traceback.

The empty-results generator replaces response values with `!!`/`!!%` using
TABLES/JSON schema labels so structural numbers in question text are not
blindly replaced.

## Sample Quota Checker contract

Primary files:

- `pipelines\sample_quota_checker\quota_workbook_scraper.py`
- `quota_browser_review.py`
- `sample_quota_checker_core.py`
- `test_quota_workbook_scraper.py`
- `test_sample_quota_checker.py`
- `local_browser_app\test_local_browser_app.py`

The scraper was developed against the user's collection at:

```text
C:\Users\normi\OneDrive - Normington Petts\Desktop\Quota Examples
```

Required behavior:

- Read workbooks without modifying or “correcting” them.
- Preserve workbook and sheet order in the review.
- Extract exact quota grids, min/max quota blocks, multiple base/oversample
  sections, percentages, source cells, and notes/instructions.
- A known NPA3857 workbook inconsistency is a source typo. Preserve it.
- Leave instructions such as `PLEASE CAP SMS COMPLETES...` as notes; they are
  legitimate edge-case instructions, not quota rows to normalize.
- Present the browser review in a sheet-like order with quota target/limit,
  current sample count, difference/status, match values, and source cell.
- Keep the browser version read-only while scraping/mapping rules are being
  verified.
- Auto-map known variants including `regioncode`, `gendergrp`/`hgender`,
  `num_ab`/`hsplitab`, `num_cd`/`hsplitcd`, race fields, and
  `stype`/`hsampletype`/`SampleType`.
- Detect and expose additional quota category columns rather than restricting
  mapping to the original hard-coded variable types.
- Keep distinct oversample sections mapped to distinct sample-type codes.

`quota_examples_verification.md` is the human review of the example extraction;
`quota_examples_extracted.json` is its machine-readable companion.

## Open-End Coder contract

The production coder is record-level. The imported survey file is read-only,
and assignments are keyed by `Survnum` or another confirmed unique key. Each
project stores state in one `*.oe_session.sqlite` and exports a new
`*.OE-coded.csv`; never alter the imported data in place.

For cumulative imports:

- New = record/question did not exist in the previous import.
- Source changed = verbatim or supplied source codes changed.
- Existing = unchanged.
- Existing user overrides are preserved and flagged for review when the source
  changes; they are not silently replaced.

Codebook metadata imports preserve and report differing nonblank metadata by
default. Only the explicit “Overwrite existing metadata” action replaces it.
WinCross exports are generated from effective row assignments and current
metadata, with supercategory NETs, direction summaries, Other at the bottom,
and ungrouped None/Don't know retained when present.

See `pipelines\open_end_coder\README.md`.

## Question Browser and repository

Question Browser reads `repository\questions.sqlite`. Search defaults to
`All words`; `Exact phrase` keeps contiguous matching and `Any word` broadens
it. To refresh both repository metadata and the question index:

```powershell
$repo = (Resolve-Path .\repository).Path
py -3 .\survey_tool_cli.py repo scan --root $repo --source-root "C:\path\to\NPA Archive - Documents" --discovery-mode archive
py -3 .\survey_tool_cli.py repo questions-rebuild --root $repo --db (Join-Path $repo "questions.sqlite")
```

The archive/source root and local repository root must remain visibly distinct.

## Questionnaire channel and survey-writer helpers

The channel builder creates reviewable Phone/SMS DOCX drafts and JSON reports.
It reuses source formatting sidecars, highlights changed text, and applies
rules from `channel_rules.default.json`. The current Table Gen pronunciation
cleanup is separate and affects generated table titles only.

Survey Writer is a separate draft helper under
`pipelines\survey_writer`; it saves drafts below `drafts\survey_writer` and is
not part of the main daily production flow.

## Sample append (replaces per-project R scripts)

`pipelines\table_merger\sample_append.py` (launcher: Sample Append) fills
data columns from a sample file by ID for the latest wave, copying values as
text. It never overwrites the input, writes `<data>_append.csv`, moves an
existing output to `Data\Backups\`, and stops if a respondent's ID is
duplicated in the sample with different values. It reproduces the NPA3857 CSM
append (`NPA3857 IA-01 CSM Append.R`: 600 wave-11 respondents, 589 changed
values) without the R script's side effects (renamed `voterbaseid`, a
`csm_score.x` column) and keeps the sample's full precision (R rounded to 9
decimals). The NPA3857 sample has 4 IDs with conflicting CSM scores; none are
respondents.

## Preliminary QC contract

`pipelines\qc_checker\prelim_qc.py` implements the structural part of
`docs\QC_GUIDE.md`: questionnaire JSON vs WinCross job (or TABLES) vs data,
with no source treated as authoritative and a severity-ranked issue register.
Glossary `DECLARE`/`ASSIGN`/`COMPUTE` variables count as defined and their
inputs are checked; screener TERMINATE options keep position codes; combined
question tables (generic ballot with leans) are not coverage gaps. Data
discovery picks the newest `NPA####*.csv` without spaces in the name. On 11
finished jobs it reports 0-8 items each; real findings included NPA3800 Q22
(duplicate questionnaire code 3) and NPA3863 Q9 (Undecided 11 vs table 7). It
also exposed a Table Gen parser bug: NPA3800 Q33 "I did not vote in 2024 ... 4"
parsed with code 2024. Numerical validation is out of scope and listed as a
limitation in every report.

## Useful regression/reference jobs

These archive jobs supplied real-world examples for the current rules. Use
copies or read-only inspection unless the user asks to regenerate an output.

| Job/path | Behavior exercised |
|---|---|
| `Bohannan\2026\NPA3857 Third Party\Job\Table Gen` | more/less-likely summaries, split combos, bracketed No difference |
| `Lee\2026\NPA3863 Week 7 Track\Job\Table Gen` | vote certainty and candidate describes summaries |
| `House Majority PAC\AZ-06\NPA3867 Track Week 6\Job\Table Gen` | might-consider follow-ups, phone-readable titles, split-minus tables |
| `House Majority PAC\NM-02\NPA3873 Track Week 5\Job\Table Gen` | four-question Candidate Communication summary |
| `Desktop\Quota Examples` | exact/min/max/oversample quota scraping and notes |
| `Desktop\TTs.txt` | recurring trend-table source |

Past Auto Results investigations showed that an apparently broken Results
folder was sometimes simply empty, while the other common cause was an open or
locked target document. Preserve the distinct diagnostics described above.

## Verification status at handoff

All of these passed on 2026-10-21:

| Area | Result |
|---|---:|
| WinCross compiler/classification/parser/banner/cover/GUI | 107 tests passed |
| Trend Table Updater | 19 tests passed |
| Sheet Merge core and GUI | 56 tests passed |
| Auto Results | 13 tests passed |
| Quota Checker/scraper | 10 tests passed |
| Open-End Coder | 36 tests passed |
| TOMAS | 9 tests passed |
| Catalog/repository dashboard | 12 tests passed |
| Channel builder, Survey Writer | 8 tests passed |
| Local browser app | 8 tests passed |
| Survey Launcher and acceptance harness | 15 tests passed |
| Total (`run_tests.bat`) | 293 tests passed |
| Synthetic end-to-end acceptance with `--gui-smoke` | all 11 stages passed |

The acceptance report for that run is:

```text
acceptance_runs\20261021_111554_9b0251\acceptance_report.txt
```

Run every suite from the SurveyPlatform root with:

```powershell
.\run_tests.bat                 # all 12 unit-test suites
.\run_tests.bat --acceptance    # plus the synthetic end-to-end smoke test
.\run_tests.bat merge trend -v  # selected suites with full output
```

`run_tests.py` lists each suite's folder and test files and sets `TEMP`/`TMP`
to the repo-local `.tmp_tests`. That avoids false `PermissionError` failures
from Windows sandbox restrictions on newly created temp directories. Add new
test files to its `SUITES` table.

## Current design limits and next likely work

- The browser app is intentionally simplified. Continue building on shared
  cores rather than forking pipeline logic into JavaScript.
- Quota scraping has broad example coverage but still needs user verification
  on new workbook layouts and newly discovered variable encodings.
- `survey run` is first-class for only some stages; the specialist tools remain
  the production path for the rest.
- Some stage truth still comes from file-presence heuristics; manifests should
  gradually replace those heuristics.
- If a source fix must reach a desktop shortcut, confirm what the `.lnk` targets
  and whether it opens a stale EXE before rebuilding anything.
- Keep client/archive outputs separate from repository source changes and never
  overwrite an input solely to make a test convenient.

## Canonical supporting documents

- `README.md` - package overview, documentation index, workspaces, launchers, tests
- `docs\CLI.md` - `survey_tool_cli.py` command reference
- `docs\SURVEY_LAUNCHER.md` - daily launcher and project-folder contract
- `docs\REPOSITORY_STRUCTURE.md` - authoritative/local/archive boundaries
- `docs\design\SURVEY_PLATFORM_SPEC.md` - original platform design and build status
- `pipelines\README.md` - component layout and dependencies
- `pipelines\wincross_table_generator\README.md` - WinCross GUI and pipeline files
- `local_browser_app\README.md` - browser scope and launch instructions
- `pipelines\table_merger\README_QUICKSTART.md` - merge workflow
- `pipelines\trend_table_updater\README.md` - trend updater use
- `pipelines\open_end_coder\README.md` - row-level coding contract
- `pipelines\auto_results\EMPTY_RESULTS_GENERATOR.md` - empty template behavior
- `pipelines\sample_quota_checker\quota_examples_verification.md` - example scrape review
- `acceptance\README.md` - synthetic end-to-end contract

If this handoff conflicts with a current regression test or implementation,
inspect the history and ask the user before deleting either behavior. Tests are
the executable contract; this document explains the intent behind them.

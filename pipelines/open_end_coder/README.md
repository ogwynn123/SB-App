# Record-Level Open-End Coder

The production Open-End Coder assigns final codes to specific respondent rows
using `Survnum` or another user-confirmed unique key. The imported survey file
is read-only. The primary output is a new `*.OE-coded.csv` with only the
applicable `cN_1..3` values changed.

## Project State

Each project uses one `*.oe_session.sqlite` database. It stores:

- imported datafile history and fingerprints
- detected `qN`/`qNoe` questions and `cN_1..3` code slots
- record-specific ordered code assignments
- category labels, supercategories, direction, source, and active status
- flags, notes, review status, and an audit log

Daily appended data can be imported into the same session. Existing overrides
are preserved by record key. Each import is matched by the selected unique key
and question, normally `Survnum` plus `qN`.

In trended (`ts`) files `Survnum` restarts every wave, so when the file has a
`Timeseries` column the record key is the pair `Timeseries + Survnum` (shown as
`2|1002` for survnum 1002 in wave 2). The pair must be unique; the same survnum
in different waves is expected. A session saved with a plain `Survnum` key is
converted on its next import using each response's stored wave, so earlier
overrides stay with the same respondent.

Prior waves are read-only. Only the latest `Timeseries` can be coded, reset, or
changed by bulk actions; the response list shows the latest wave. For a
correction, click **Unlock Prior Waves...** and give a reason: the list then
shows every wave until **Lock Prior Waves** is clicked or the session is
reopened. Unlocking and relocking are recorded in the audit log. The browser
workbench lists the latest wave by default and shows prior waves read-only.

The first imported file is the session baseline, so all of its responses are
marked **New**. On later cumulative imports:

- **New** means that record/question pair did not exist in the prior import.
- **Source changed** means its verbatim or supplied `cN_1..3` codes changed.
- **Existing** means the source response is unchanged.

**New or changed** is the default Code Responses queue. **All active** remains
available for reviewing the complete current file. A user override is never
silently replaced by a new source value; the response is flagged when its
source changes so the coder can review it.

## Views

1. **Code Responses** is the primary workspace. Codes are assigned in slot
   order to one respondent record at a time. Applying to identical text is an
   explicit bulk action that writes a separate assignment for every record.
   **Clean Up Others** removes a selected final code from latest-wave records
   only when another final code remains, leaving code-only records unchanged.
2. **Codebook** manages category labels and supercategory grouping as secondary
   metadata. Renaming a category does not alter respondent assignments. A daily
   codelist fills blank labels, supercategories, and directions. Differing
   nonblank metadata is preserved and reported by default. **Overwrite existing
   metadata** explicitly replaces those differences, with every replacement
   shown in the report and audit log. Existing WinCross open-end tables use the
   same preserve-and-report policy when imported into the selected question.
3. **Review & Export** shows completion and exports the coded CSV. Codebook,
   audit, and formatted WinCross open-end table files are secondary outputs.

The WinCross export is generated from effective record assignments and current
codebook metadata. It includes user codes, edited category labels,
supercategory `NET` groups, and positive/negative summary lines. Used codes
without labels are clearly marked in the output and reported after export.
Codes sharing the same label, supercategory, and direction are rendered on one
multi-code category line such as `Reproductive rights^(103,104)^NS,SK`.
The `OTHER` supercategory is retained at the bottom with `RL`, followed by
ungrouped `None` and `Don't know` categories with `RL` when present.

## Launch

Use `Launch_OE_Codebook_GUI.bat` or select **Open-End Coder** in the Survey
Launcher. The launcher passes the survey ID, project root, and preferred Open
Ends working folder to the app.

The former aggregated codebook editor remains available through
`Launch_OE_Codebook_Legacy_GUI.bat`.

## Drafting a first code list (experimental)

For a question not fielded before, `oe_codelist_embed.draft_keywords_by_meaning`
drafts a preliminary code list from the verbatims for an analyst to review.
Everything runs on this PC; no responses are sent anywhere.

1. Non-answers go to the house codes (have not heard enough, nothing, don't know).
2. Words and phrases used by several responses become candidate codes.
3. A small local sentence-embedding model (`BAAI/bge-small-en-v1.5`, about
   65 MB, run through `fastembed`) then drops candidates whose responses do not
   agree in meaning, merges codes that say the same thing in different words,
   files leftover responses under the closest code, and names each code with its
   most typical short clause.

The model downloads once into `SurveyPlatform/.models` (git-ignored). Embeddings
are cached in `corpus/oe/embeddings` (git-ignored client data). The same model
runs in a browser through transformers.js.

Supporting modules:

- `oe_codelist_draft.py`: text handling, non-answer rules, word-based drafters.
- `oe_codelist_kb.py`: drafters that learn from past analyst coding.
- `oe_embeddings.py`: local embedding and cache.
- `oe_eval_corpus.py`: builds `corpus/oe/*.json` from analyst-coded archive jobs (read-only).
- `oe_codelist_eval.py`: scores drafters against the analysts' final coding.

```bash
py -3 oe_codelist_eval.py keyword_themes keywords_by_meaning --sample 150
```

On 39 coded questions with a first-day sample of 150 responses, the draft
matches about 56% of the analysts' major themes closely. About 89% of analyst
themes appear as the main content of some draft code, 72% of draft codes are
mostly one analyst code, and it drafts about as many codes as a preliminary list.

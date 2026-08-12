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

# Sheet Merge GUI Quickstart

This app merges rows from a **secondary** survey sheet into a **primary** survey sheet using a join key and column mapping.
The primary file remains the schema authority: output columns follow the
primary/current file first. In Advanced settings, **Row order** controls whether
primary rows or secondary rows appear first.

## 1. Launch

From the repo-local pipeline folder:

```powershell
cd .\pipelines\table_merger
.\open_sheet_merge_gui.bat
```

Launcher behavior:

- if `dist\sheet_merge_gui.exe` exists, it opens that EXE
- otherwise it falls back to `sheetMerging_gui.py`

## 2. Basic Workflow

1. Set **Primary** file (CSV/XLSX).
2. Set **Secondary** file (CSV/XLSX).
3. Click **Refresh Sheets/Columns**.
4. Select:
   - **Primary sheet** / **Secondary sheet** (for XLSX)
   - **Primary join** / **Secondary join** (usually `survnum` or `respondent_id`)
5. Click **Auto Fill**.
6. Optional: adjust mapping rows manually.
7. Click **Run Merge**.

When a base question such as `q14` is mapped to `q7`, matching `q14a` and
`q14b` columns automatically follow to `q7a` and `q7b`. A companion row that
you map manually or clear remains under your control.

The mapping table is authoritative when you run Preflight or Merge. Any row
left blank stays unmapped; its secondary column is preserved separately using
the secondary survey prefix instead of filling the blank primary column.

## 3. JSON/Semantic Matching (Optional but Recommended)

For question-aware mapping and JSON previews, set:

- **Primary survey JSON**
- **Secondary survey JSON**

Then:

- Use **Auto Fill** for semantic mapping
- Use **Preview Selected JSON** or **Preview All JSON**

For battery questions, semantic matching is item-focused. A shared lead-in and
response scale can support a match, but cannot make different battery
statements map to one another.

If JSON files are not set, Auto Fill still works in non-semantic mode.

## 4. Output Behavior

- **new_file** mode: writes a new merged file.
- **overwrite** mode: writes back to the primary file.
- **Row order**: defaults to `secondary_first`, so older secondary rows appear
  above the current primary delivery. Select `primary_first` when needed.

You can change these in Basic/Advanced settings before running.

### Combined Demographics carry-over

After a timeseries merge (a new wave stacked onto `NPA####ts`), the app looks
for the previous wave's WinCross job (`<previous project>\Job\NPA####.job`) and
writes two review files next to the merged output:

- `<output>_carryover_combined_demos.txt`: the previous job's Combined
  Demographics table(s), copied verbatim except for variables the merge mapped
  to a new column name.
- `<output>_carryover_report.md`: every variable and code checked against the
  merged data by wave, with Major/Minor issues marked for human review (for
  example a variable blank for a whole wave, or not asked in the new wave).

Nothing is pasted into a job automatically; review the report, then copy the
table into the new job.

### Sample append (replaces per-project R append scripts)

`sample_append.py` fills data columns from a sample file by ID, for the latest
wave only unless told otherwise, and writes `<data stem>_append.csv`:

```powershell
py -3 sample_append.py "..\Data\NPA3857ts.csv" "..\Sample\NPA3857 Sample wCSM.csv" --column Bohannan_CSM_2026=csm_score
```

- ID columns that differ only by underscores/case are matched automatically
  (`voterbaseid` = `voterbase_id`); otherwise pass `--data-key`/`--sample-key`.
- The input file is never changed and every other value is copied as text.
- An existing output is moved to `Data\Backups\<name>.<timestamp>.csv` first.
- A sample ID repeated with different values stops the run if a respondent has it.
- `<output>_report.md` lists matched/unmatched IDs and values changed.

Checked against the NPA3857 CSM append: the same 600 wave-11 respondents and
589 changed values as the R script, without its side effects (renamed ID
column, `csm_score.x`) and with the sample's full precision.

## 5. Troubleshooting

### Auto Fill crash or app closes unexpectedly

Check:

- `pipelines\table_merger\dist\sheet_merge_gui_errors.log`
- `%TEMP%\sheet_merge_gui_faulthandler.log`

### If GUI does not open

Rebuild EXE:

```powershell
cd .\pipelines\table_merger
.\build_gui_exe.bat
```

### Run from source (fallback)

```powershell
cd .\pipelines\table_merger
.\run_sheetMerging_gui.ps1
```

## 6. Recommended Daily Use

Use the repo-local launcher every time:

```powershell
.\pipelines\table_merger\open_sheet_merge_gui.bat
```

It uses the local `dist\sheet_merge_gui.exe` when present and falls back to source otherwise.

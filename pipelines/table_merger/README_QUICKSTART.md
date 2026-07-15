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

## 3. JSON/Semantic Matching (Optional but Recommended)

For question-aware mapping and JSON previews, set:

- **Primary survey JSON**
- **Secondary survey JSON**

Then:

- Use **Auto Fill** for semantic mapping
- Use **Preview Selected JSON** or **Preview All JSON**

If JSON files are not set, Auto Fill still works in non-semantic mode.

## 4. Output Behavior

- **new_file** mode: writes a new merged file.
- **overwrite** mode: writes back to the primary file.
- **Row order**: use `secondary_first` for trend/daily workflows where older
  secondary rows should appear above the current primary delivery.

You can change these in Basic/Advanced settings before running.

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

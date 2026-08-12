# Trend Table Updater

Standalone WinCross glossary tool for adding a new wave to existing `TTREND`
tables and recalculating their `NET CHANGE` formulas.

## Use

1. Open `open_trend_table_updater.bat`.
2. Paste glossary text or load a TXT file.
3. Review the inferred prior and new timeseries values.
4. Enter the new wave label.
5. Select **Update Tables**.
6. Review the result and select **Save As**.

Only tables whose latest wave matches **Prior timeseries** are updated. Older
trend tables remain unchanged. Bracketed-year archive titles such as `[2022]`
are skipped by default.

## Tests

```powershell
py -3 -m unittest test_trend_table_updater_core
```

## Build

```powershell
.\build_gui_exe.bat
```

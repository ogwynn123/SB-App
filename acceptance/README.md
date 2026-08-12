# Acceptance Fixture

`NPA9999 Acceptance` is synthetic and contains no client data. The acceptance
runner copies it to an ignored run folder before doing any work; files under
`acceptance/fixtures` are never modified by a run.

The fixture exercises these contracts:

- Project Startup creates the standard folder tree and safely copies the Final DOCX.
- A second Project Startup run is idempotent.
- launcher work folders, source folders, environment variables, and entrypoints agree.
- WinCross produces a basic table from survey JSON.
- Table Merger preserves an explicitly unmapped primary question and prefixes the
  corresponding secondary data.
- Trend Tables add a wave and recalculate NET row positions.
- Quota Checker separates base sample and oversample records.
- Auto Results fills a DOCX and writes a clean alignment report.
- Open-End Coder applies codes to specific latest-wave records and exports both
  coded CSV and WinCross text.

From the repository root, run:

```powershell
py -3 .\acceptance_smoke.py
```

To also start each packaged GUI briefly and close the processes created by the
runner:

```powershell
py -3 .\acceptance_smoke.py --gui-smoke
```

Every run is retained under the ignored `acceptance_runs` directory. Review
`acceptance_report.txt` for the checklist and `acceptance_report.json` for
machine-readable details. A nonzero exit code means at least one check failed.

# Survey Workbench (local browser app)

This is a localhost front end for six SurveyPlatform workflows:

- Table Gen
- Sheet Merge
- Open-End Coder
- Question Browser
- Auto Results
- Sample Quota Checker

It reuses the current pipeline modules; it does not replace or modify the desktop
applications. The web server binds only to `127.0.0.1` and gives each launch a
temporary request token.

## Start

Double-click `run_survey_browser.bat` in the SurveyPlatform folder, or run:

```powershell
py -3 -m local_browser_app.server
```

The dashboard opens at `http://127.0.0.1:8765/`. Keep the small terminal window
open while using it; close it or press Ctrl+C to stop the app.

Paths are entered as normal Windows paths. This avoids uploading or copying
production data into browser storage. Long-running generation/export operations
show their progress in the lower-right run console.

## Current simplified scope

- Table Gen discovers exact-stem DOCX/PDF pairs and runs selected jobs.
- Sheet Merge previews auto/manual mappings before it writes anything. The
  reviewed `primary=secondary` text is passed back to the existing merge core,
  and secondary-only fields remain included.
- OE Coder covers persistent session import, filtering, response assignment,
  code-label editing, restore-original, and the four core exports.
- Question Browser searches the current `repository/questions.sqlite` index.
- Auto Results supports DOCX or XLSX value sources, the fix/no-loss processing
  path, and alignment reports. Existing empty-file and locked-document messages
  are retained.
- Quota Checker scrapes exact cells, min/max blocks, and oversamples in workbook
  order; maps fixed and newly detected sample variables; and displays quota,
  current count, and difference in a sheet-like review. It is read-only while
  the extraction and mapping rules are being verified.

## Tests

```powershell
py -3 -m unittest local_browser_app.test_local_browser_app -v
```


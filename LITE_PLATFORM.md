# Survey Ops Lite

Survey Ops Lite is a small daily-work shell for active survey jobs. It keeps a
simple project folder under `lite_workspace\NPA####` and delegates heavy work to
the existing WinCross table generator, table merger, and open-end coder.

## Launch

Run:

```bat
SurveyPlatform\run_survey_ops_lite.bat
```

## What It Owns

- One `project.json` per survey.
- Phone and SMS DOCX/PDF paths for WinCross generation.
- Current delivery data, timeseries data, and day-specific codelists.
- Header checking for current data so a new delivery with different columns is
  blocked instead of replacing the tracked file silently.
- Output folders for generated WinCross RAW, JSON, and TABLES files.
- Buttons to open the existing merge GUI, OE coder, and WinCross GUI.

## Current Boundary

This first version is deliberately barebones. It organizes daily job state and
runs the common WinCross path, but detailed merge mapping and OE codebook work
still happen in the specialist apps.

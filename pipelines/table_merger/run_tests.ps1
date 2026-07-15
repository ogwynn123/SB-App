param(
    [switch]$Fast,
    [switch]$KeepArtifacts,
    [string]$PythonExe = "python"
)

$ErrorActionPreference = "Stop"

$script:StepCount = 0
$script:PassCount = 0
$script:Failures = New-Object System.Collections.Generic.List[string]

function Assert-LastExitCode {
    param([string]$Context)
    if ($LASTEXITCODE -ne 0) {
        throw "$Context failed with exit code $LASTEXITCODE"
    }
}

function Invoke-Python {
    param(
        [string[]]$PyArgs,
        [string]$Context
    )
    & $PythonExe @PyArgs
    Assert-LastExitCode $Context
}

function Invoke-Step {
    param(
        [string]$Name,
        [scriptblock]$Action
    )
    $script:StepCount++
    Write-Host ""
    Write-Host "==> $Name"
    try {
        & $Action
        Write-Host "[PASS] $Name" -ForegroundColor Green
        $script:PassCount++
    } catch {
        $msg = "$Name :: $($_.Exception.Message)"
        Write-Host "[FAIL] $msg" -ForegroundColor Red
        $script:Failures.Add($msg) | Out-Null
    }
}

$repoRoot = (Get-Location).Path
$runRoot = Join-Path $repoRoot ".test_runs"
$runDir = Join-Path $runRoot (Get-Date -Format "yyyyMMdd_HHmmss")
New-Item -ItemType Directory -Path $runDir -Force | Out-Null
$originalTemp = $env:TEMP
$originalTmp = $env:TMP
$env:TEMP = $runDir
$env:TMP = $runDir

$csvPrefix = "runner_csv"
$xlsxPrefix = "runner_xlsx"
$mapFile = Join-Path $runDir "map.txt"
$csvPrimary = Join-Path $runDir "${csvPrefix}_primary.csv"
$csvSecondary = Join-Path $runDir "${csvPrefix}_secondary.csv"
$csvDryRunOut = Join-Path $runDir "csv_dryrun_output.csv"
$csvMergedOut = Join-Path $runDir "csv_merged_output.csv"
$xlsxPrimary = Join-Path $runDir "${xlsxPrefix}_primary.xlsx"
$xlsxSecondary = Join-Path $runDir "${xlsxPrefix}_secondary.xlsx"
$xlsxPreserveOut = Join-Path $runDir "xlsx_merged_preserve.xlsx"
$xlsxReplaceOut = Join-Path $runDir "xlsx_merged_replace.xlsx"

@(
    "first_name=fname",
    "last_name=lname"
) | Set-Content -Encoding UTF8 $mapFile

Write-Host "Running tests in: $runDir"

Invoke-Step "AST parse" {
    $code = @'
import ast
from pathlib import Path

for name in [
    'sheet_merge_core.py',
    'sheetMerging_cli.py',
    'sheetMerging_gui.py',
    'test_sheet_merge_core.py',
    'test_sheetMerging_gui.py',
]:
    ast.parse(Path(name).read_text(encoding='utf-8'))
print('AST_OK')
'@
    Invoke-Python -PyArgs @("-c", $code) -Context "AST parse"
}

Invoke-Step "Import smoke" {
    Invoke-Python -PyArgs @(
        "-c",
        "import sheet_merge_core, sheetMerging_cli, sheetMerging_gui; print('IMPORT_OK')"
    ) -Context "Import smoke"
}

Invoke-Step "Unit tests" {
    Invoke-Python -PyArgs @(
        "-m", "unittest", "-v",
        "test_sheet_merge_core.py",
        "test_sheetMerging_gui.py"
    ) -Context "Unit tests"
}

Invoke-Step "CLI help" {
    Invoke-Python -PyArgs @("sheetMerging_cli.py", "--help") -Context "CLI help"
}

Invoke-Step "Generate CSV sample" {
    Invoke-Python -PyArgs @(
        "sheetMerging_cli.py",
        "--generate-sample", $runDir,
        "--sample-format", "csv",
        "--sample-prefix", $csvPrefix,
        "--sample-primary-rows", "8",
        "--sample-secondary-rows", "6"
    ) -Context "Generate CSV sample"
    if (-not (Test-Path $csvPrimary)) {
        throw "Expected sample primary CSV not found: $csvPrimary"
    }
    if (-not (Test-Path $csvSecondary)) {
        throw "Expected sample secondary CSV not found: $csvSecondary"
    }
}

Invoke-Step "CSV preflight" {
    Invoke-Python -PyArgs @(
        "sheetMerging_cli.py",
        "--preflight",
        "--primary", $csvPrimary,
        "--secondary", $csvSecondary,
        "--primary-join", "respondent_id",
        "--secondary-join", "respondent_id",
        "--mapping-mode", "manual_only",
        "--map-file", $mapFile
    ) -Context "CSV preflight"
}

Invoke-Step "CSV dry-run has no output" {
    Invoke-Python -PyArgs @(
        "sheetMerging_cli.py",
        "--dry-run",
        "--primary", $csvPrimary,
        "--secondary", $csvSecondary,
        "--primary-join", "respondent_id",
        "--secondary-join", "respondent_id",
        "--mapping-mode", "auto",
        "--threshold", "80",
        "--top-n", "4",
        "--conflict-policy", "skip",
        "--output-mode", "new_file",
        "--output", $csvDryRunOut
    ) -Context "CSV dry-run"
    if (Test-Path $csvDryRunOut) {
        throw "Dry run produced output unexpectedly: $csvDryRunOut"
    }
}

Invoke-Step "CSV merge with map-file" {
    Invoke-Python -PyArgs @(
        "sheetMerging_cli.py",
        "--primary", $csvPrimary,
        "--secondary", $csvSecondary,
        "--primary-join", "respondent_id",
        "--secondary-join", "respondent_id",
        "--mapping-mode", "manual_only",
        "--map-file", $mapFile,
        "--conflict-policy", "skip",
        "--output-mode", "new_file",
        "--output", $csvMergedOut,
        "--no-report-enabled",
        "--no-archive-secondary"
    ) -Context "CSV merge"
    if (-not (Test-Path $csvMergedOut)) {
        throw "Expected CSV merge output not found: $csvMergedOut"
    }
}

if (-not $Fast) {
    Invoke-Step "Generate XLSX sample" {
        Invoke-Python -PyArgs @(
            "sheetMerging_cli.py",
            "--generate-sample", $runDir,
            "--sample-format", "xlsx",
            "--sample-prefix", $xlsxPrefix,
            "--sample-primary-rows", "8",
            "--sample-secondary-rows", "6"
        ) -Context "Generate XLSX sample"
        if (-not (Test-Path $xlsxPrimary)) {
            throw "Expected sample primary XLSX not found: $xlsxPrimary"
        }
        if (-not (Test-Path $xlsxSecondary)) {
            throw "Expected sample secondary XLSX not found: $xlsxSecondary"
        }
    }

    Invoke-Step "XLSX merge preserve_sheets" {
        Invoke-Python -PyArgs @(
            "sheetMerging_cli.py",
            "--primary", $xlsxPrimary,
            "--secondary", $xlsxSecondary,
            "--primary-sheet", "PrimaryData",
            "--secondary-sheet", "SecondaryData",
            "--primary-join", "respondent_id",
            "--secondary-join", "respondent_id",
            "--mapping-mode", "auto",
            "--threshold", "75",
            "--top-n", "4",
            "--conflict-policy", "skip",
            "--output-mode", "new_file",
            "--output", $xlsxPreserveOut,
            "--xlsx-write-mode", "preserve_sheets",
            "--no-report-enabled",
            "--no-archive-secondary"
        ) -Context "XLSX merge preserve_sheets"
        if (-not (Test-Path $xlsxPreserveOut)) {
            throw "Expected preserve_sheets output not found: $xlsxPreserveOut"
        }
    }

    Invoke-Step "XLSX merge replace_workbook" {
        Invoke-Python -PyArgs @(
            "sheetMerging_cli.py",
            "--primary", $xlsxPrimary,
            "--secondary", $xlsxSecondary,
            "--primary-sheet", "PrimaryData",
            "--secondary-sheet", "SecondaryData",
            "--primary-join", "respondent_id",
            "--secondary-join", "respondent_id",
            "--mapping-mode", "auto",
            "--threshold", "75",
            "--top-n", "4",
            "--conflict-policy", "skip",
            "--output-mode", "new_file",
            "--output", $xlsxReplaceOut,
            "--xlsx-write-mode", "replace_workbook",
            "--no-report-enabled",
            "--no-archive-secondary"
        ) -Context "XLSX merge replace_workbook"
        if (-not (Test-Path $xlsxReplaceOut)) {
            throw "Expected replace_workbook output not found: $xlsxReplaceOut"
        }
    }

    Invoke-Step "Validate XLSX sheet modes" {
        $code = @'
import pandas as pd
import sys

preserve = sys.argv[1]
replace = sys.argv[2]
with pd.ExcelFile(preserve) as xf:
    preserve_sheets = xf.sheet_names
with pd.ExcelFile(replace) as xf:
    replace_sheets = xf.sheet_names

assert 'PrimaryData' in preserve_sheets, preserve_sheets
assert 'merged' in preserve_sheets, preserve_sheets
assert replace_sheets == ['merged'], replace_sheets
print('XLSX_MODE_OK')
'@
        Invoke-Python -PyArgs @("-c", $code, $xlsxPreserveOut, $xlsxReplaceOut) -Context "Validate XLSX sheets"
    }
}

Write-Host ""
Write-Host "Summary: $script:PassCount/$script:StepCount steps passed."

if ($script:Failures.Count -gt 0) {
    Write-Host "Failures:" -ForegroundColor Red
    foreach ($failure in $script:Failures) {
        Write-Host " - $failure" -ForegroundColor Red
    }
    Write-Host "Artifacts retained at: $runDir"
    $env:TEMP = $originalTemp
    $env:TMP = $originalTmp
    exit 1
}

if (-not $KeepArtifacts) {
    Remove-Item -Recurse -Force $runDir
    $remaining = Get-ChildItem $runRoot -ErrorAction SilentlyContinue
    if (-not $remaining) {
        Remove-Item -Force $runRoot -ErrorAction SilentlyContinue
    }
    Write-Host "Artifacts removed."
} else {
    Write-Host "Artifacts retained at: $runDir"
}

$env:TEMP = $originalTemp
$env:TMP = $originalTmp

exit 0

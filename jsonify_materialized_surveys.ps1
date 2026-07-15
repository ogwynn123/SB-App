param(
    [string]$Root = ".\repository\materialized_surveys_csv_priority",
    [string[]]$Survey = @(),
    [switch]$Overwrite,
    [switch]$IncludeTables,
    [string]$LogPath = ""
)

$ErrorActionPreference = "Stop"

function Normalize-SurveyCode {
    param([string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) {
        return $null
    }
    $m = [regex]::Match($Value, '(?i)npa(?<code>\d{4,})')
    if ($m.Success) {
        return ("NPA{0}" -f ([int]$m.Groups["code"].Value))
    }
    if ($Value -match '^\d{4,}$') {
        return ("NPA{0}" -f ([int]$Value))
    }
    return $null
}

function Resolve-PythonExe {
    $candidates = @(
        (Join-Path $env:LocalAppData 'Python\pythoncore-3.14-64\python.exe'),
        (Join-Path $env:LocalAppData 'Programs\Python\Python314\python.exe')
    )
    foreach ($candidate in $candidates) {
        if (-not [string]::IsNullOrWhiteSpace($candidate) -and (Test-Path -LiteralPath $candidate)) {
            return $candidate
        }
    }
    $pyCmd = Get-Command py -ErrorAction SilentlyContinue
    if ($null -ne $pyCmd) {
        return "py -3"
    }
    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($null -ne $pythonCmd) {
        return "python"
    }
    throw "No Python interpreter found. Install Python 3.14 or adjust the launcher."
}

function Write-ResultsLog {
    param(
        [System.Collections.Generic.List[object]]$Rows,
        [string]$TargetPath
    )
    if ([string]::IsNullOrWhiteSpace($TargetPath)) {
        return
    }
    $targetDir = Split-Path -Parent $TargetPath
    if (-not [string]::IsNullOrWhiteSpace($targetDir)) {
        New-Item -ItemType Directory -Force -Path $targetDir | Out-Null
    }
    $Rows |
        Select-Object Survey, Status, DocxPath, PdfPath, RawPath, JsonPath, TablesPath, Detail |
        Export-Csv -LiteralPath $TargetPath -NoTypeInformation -Encoding UTF8
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$cliPath = Join-Path $scriptDir "survey_tool_cli.py"
if (-not (Test-Path -LiteralPath $cliPath)) {
    throw "survey_tool_cli.py not found next to this script: $cliPath"
}

$pythonExe = Resolve-PythonExe
$rootPath = Resolve-Path -LiteralPath $Root
$resolvedLogPath = ""
if ([string]::IsNullOrWhiteSpace($LogPath)) {
    $resolvedLogPath = Join-Path $rootPath "jsonify_materialized_results.csv"
}
else {
    $resolvedLogPath = [System.IO.Path]::GetFullPath($LogPath)
}

$wanted = @{}
foreach ($item in ($Survey | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })) {
    $normalized = Normalize-SurveyCode $item
    if ($null -ne $normalized) {
        $wanted[$normalized] = $true
    }
}

$surveyDirs = Get-ChildItem -LiteralPath $rootPath -Directory | Where-Object { $_.Name -match '^NPA\d+$' }
if ($wanted.Count -gt 0) {
    $surveyDirs = $surveyDirs | Where-Object { $wanted.ContainsKey($_.Name) }
}
$surveyDirs = $surveyDirs | Sort-Object Name

$results = New-Object System.Collections.Generic.List[object]

foreach ($surveyDir in $surveyDirs) {
    $surveyId = $surveyDir.Name
    $docxDir = Join-Path $surveyDir.FullName "docx"
    $pdfPath = Join-Path $surveyDir.FullName ($surveyId + ".pdf")
    $pdfInputPath = $pdfPath
    $rawPath = Join-Path $surveyDir.FullName ($surveyId + "RAW.txt")
    $jsonPath = Join-Path $surveyDir.FullName ($surveyId + "JSON.json")
    $tablesPath = Join-Path $surveyDir.FullName ($surveyId + "TABLES.autogen.txt")
    $docxPath = $null

    if (Test-Path -LiteralPath $docxDir) {
        $docxCandidate = Get-ChildItem -LiteralPath $docxDir -File -Filter *.docx | Sort-Object Name | Select-Object -First 1
        if ($null -ne $docxCandidate) {
            $docxPath = $docxCandidate.FullName
        }
    }

    if (-not (Test-Path -LiteralPath $pdfInputPath)) {
        $pdfDir = Join-Path $surveyDir.FullName "pdf"
        if (Test-Path -LiteralPath $pdfDir) {
            $pdfCandidate = Get-ChildItem -LiteralPath $pdfDir -File -Filter *.pdf | Sort-Object Name | Select-Object -First 1
            if ($null -ne $pdfCandidate) {
                $pdfInputPath = $pdfCandidate.FullName
            }
        }
    }

    if ($null -eq $docxPath) {
        $results.Add([pscustomobject]@{
            Survey = $surveyId
            Status = "missing_docx"
            DocxPath = ""
            PdfPath = $pdfInputPath
            RawPath = $rawPath
            JsonPath = $jsonPath
            TablesPath = $tablesPath
            Detail = ""
        })
        continue
    }

    if (-not (Test-Path -LiteralPath $pdfInputPath)) {
        $results.Add([pscustomobject]@{
            Survey = $surveyId
            Status = "missing_pdf"
            DocxPath = $docxPath
            PdfPath = $pdfPath
            RawPath = $rawPath
            JsonPath = $jsonPath
            TablesPath = $tablesPath
            Detail = ""
        })
        continue
    }

    if (-not $Overwrite.IsPresent) {
        if ($IncludeTables.IsPresent) {
            if ((Test-Path -LiteralPath $jsonPath) -and (Test-Path -LiteralPath $tablesPath)) {
                $results.Add([pscustomobject]@{
                    Survey = $surveyId
                    Status = "existing"
                    DocxPath = $docxPath
                    PdfPath = $pdfInputPath
                    RawPath = $rawPath
                    JsonPath = $jsonPath
                    TablesPath = $tablesPath
                    Detail = "json and tables already exist"
                })
                continue
            }
        }
        elseif (Test-Path -LiteralPath $jsonPath) {
            $results.Add([pscustomobject]@{
                Survey = $surveyId
                Status = "existing"
                DocxPath = $docxPath
                PdfPath = $pdfInputPath
                RawPath = $rawPath
                JsonPath = $jsonPath
                TablesPath = $tablesPath
                Detail = "json already exists"
            })
            continue
        }
    }

    $cmdParts = @(
        "--docx", $docxPath,
        "--pdf", $pdfInputPath,
        "--raw-out", $rawPath,
        "--json-out", $jsonPath,
        "--tables-out", $tablesPath
    )
    if ($Overwrite.IsPresent) {
        $cmdParts += "--overwrite"
    }
    if (-not $IncludeTables.IsPresent) {
        $cmdParts += "--skip-tables"
    }

    $argString = ($cmdParts | ForEach-Object {
        if ($_ -match '\s') {
            '"' + ($_ -replace '"', '\"') + '"'
        }
        else {
            $_
        }
    }) -join ' '

    try {
        if ($pythonExe -eq "py -3") {
            $output = & py -3 $cliPath pipeline @cmdParts 2>&1
            $exitCode = $LASTEXITCODE
        }
        elseif ($pythonExe -eq "python") {
            $output = & python $cliPath pipeline @cmdParts 2>&1
            $exitCode = $LASTEXITCODE
        }
        else {
            $output = & $pythonExe $cliPath pipeline @cmdParts 2>&1
            $exitCode = $LASTEXITCODE
        }

        if ($exitCode -ne 0) {
            throw ("pipeline exit code {0}: {1}" -f $exitCode, (($output | Out-String).Trim()))
        }

        $results.Add([pscustomobject]@{
            Survey = $surveyId
            Status = "created"
            DocxPath = $docxPath
            PdfPath = $pdfInputPath
            RawPath = $rawPath
            JsonPath = $jsonPath
            TablesPath = $tablesPath
            Detail = $argString
        })
    }
    catch {
        $results.Add([pscustomobject]@{
            Survey = $surveyId
            Status = "error"
            DocxPath = $docxPath
            PdfPath = $pdfInputPath
            RawPath = $rawPath
            JsonPath = $jsonPath
            TablesPath = $tablesPath
            Detail = $_.Exception.Message
        })
    }
}

$created = ($results | Where-Object { $_.Status -eq "created" }).Count
$existing = ($results | Where-Object { $_.Status -eq "existing" }).Count
$missingDocx = ($results | Where-Object { $_.Status -eq "missing_docx" }).Count
$missingPdf = ($results | Where-Object { $_.Status -eq "missing_pdf" }).Count
$errors = ($results | Where-Object { $_.Status -eq "error" }).Count

Write-ResultsLog -Rows $results -TargetPath $resolvedLogPath

Write-Host ("Root: {0}" -f $rootPath)
Write-Host ("Surveys scanned: {0}" -f $results.Count)
Write-Host ("Created: {0}" -f $created)
Write-Host ("Existing: {0}" -f $existing)
Write-Host ("Missing docx: {0}" -f $missingDocx)
Write-Host ("Missing pdf: {0}" -f $missingPdf)
Write-Host ("Errors: {0}" -f $errors)
Write-Host ("Mode: {0}" -f ($(if ($IncludeTables.IsPresent) { "json+tables" } else { "json_only" })))
Write-Host ("Log: {0}" -f $resolvedLogPath)

foreach ($row in $results) {
    if ($row.Status -ne "error") {
        continue
    }
    Write-Host ("  {0}: {1}" -f $row.Survey, $row.Detail)
}

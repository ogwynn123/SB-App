param(
    [string]$WorkspaceRoot = "",
    [string[]]$Survey = @(),
    [ValidateSet("final", "phone", "sms")]
    [string[]]$Role = @("final"),
    [switch]$Overwrite,
    [switch]$Visible,
    [switch]$DryRun,
    [switch]$AllowExistingWord,
    [string]$LogPath = ""
)

$ErrorActionPreference = "Stop"
$wdFormatPDF = 17

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

function Get-WantedSurveySet {
    param([string[]]$Values)
    $wanted = @{}
    foreach ($raw in ($Values | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })) {
        foreach ($part in ($raw -split '[,;]')) {
            $normalized = Normalize-SurveyCode $part.Trim()
            if ($null -ne $normalized) {
                $wanted[$normalized] = $true
            }
        }
    }
    return $wanted
}

function Add-Result {
    param(
        [System.Collections.Generic.List[object]]$Rows,
        [string]$Survey,
        [string]$Role,
        [string]$Status,
        [string]$DocxPath,
        [string]$PdfPath,
        [string]$Detail
    )
    $Rows.Add([pscustomobject]@{
        Survey = $Survey
        Role = $Role
        Status = $Status
        DocxPath = $DocxPath
        PdfPath = $PdfPath
        Detail = $Detail
    })
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
        Select-Object Survey, Role, Status, DocxPath, PdfPath, Detail |
        Export-Csv -LiteralPath $TargetPath -NoTypeInformation -Encoding UTF8
}

function Get-DocxFiles {
    param([string]$FolderPath)
    if (-not (Test-Path -LiteralPath $FolderPath)) {
        return @()
    }
    return @(
        Get-ChildItem -LiteralPath $FolderPath -File -Filter *.docx |
            Where-Object { -not $_.Name.StartsWith('~$') } |
            Sort-Object Name
    )
}

function Export-WordDocumentToPdf {
    param(
        $WordApp,
        [string]$DocxPath,
        [string]$PdfPath
    )

    $document = $null
    $pdfDir = Split-Path -Parent $PdfPath
    $baseName = [System.IO.Path]::GetFileNameWithoutExtension($PdfPath)
    $tmpPath = Join-Path $pdfDir ("{0}.tmp.{1}.pdf" -f $baseName, [guid]::NewGuid().ToString("N"))

    try {
        New-Item -ItemType Directory -Force -Path $pdfDir | Out-Null
        try {
            $document = $WordApp.Documents.OpenNoRepairDialog($DocxPath, $false, $true, $false)
        }
        catch {
            $document = $WordApp.Documents.Open($DocxPath, $false, $true, $false)
        }
        try {
            $document.ExportAsFixedFormat($tmpPath, $wdFormatPDF)
        }
        catch {
            $document.SaveAs([ref]$tmpPath, [ref]$wdFormatPDF)
        }
        if (-not (Test-Path -LiteralPath $tmpPath)) {
            throw "Word did not create the PDF output."
        }
        if (Test-Path -LiteralPath $PdfPath) {
            Remove-Item -LiteralPath $PdfPath -Force
        }
        Move-Item -LiteralPath $tmpPath -Destination $PdfPath -Force
    }
    finally {
        if ($null -ne $document) {
            try {
                $document.Close([ref]$false)
            }
            catch {}
        }
        if (Test-Path -LiteralPath $tmpPath) {
            try {
                Remove-Item -LiteralPath $tmpPath -Force
            }
            catch {}
        }
    }
}

if ([string]::IsNullOrWhiteSpace($WorkspaceRoot)) {
    $WorkspaceRoot = Join-Path $PSScriptRoot "workspace"
}

$rootPath = (Resolve-Path -LiteralPath $WorkspaceRoot).Path
if ($rootPath -like "*\OneDrive - Normington Petts\NPA Archive - Documents*") {
    throw "This exporter is for the local SurveyPlatform workspace only. Refusing to write PDFs into the archive."
}

$resolvedLogPath = ""
if ([string]::IsNullOrWhiteSpace($LogPath)) {
    $resolvedLogPath = Join-Path $rootPath "workspace_docx_to_pdf_results.csv"
}
else {
    $resolvedLogPath = [System.IO.Path]::GetFullPath($LogPath)
}

$roleDirs = @{
    final = "inputs\questionnaire\final"
    phone = "inputs\questionnaire\phone"
    sms = "inputs\questionnaire\sms"
}

$wanted = Get-WantedSurveySet $Survey
$surveyDirs = Get-ChildItem -LiteralPath $rootPath -Directory | Where-Object { $_.Name -match '^NPA\d+$' }
if ($wanted.Count -gt 0) {
    $surveyDirs = $surveyDirs | Where-Object { $wanted.ContainsKey($_.Name) }
}
$surveyDirs = @($surveyDirs | Sort-Object Name)

$results = New-Object System.Collections.Generic.List[object]
$jobs = New-Object System.Collections.Generic.List[object]
$found = @{}

foreach ($surveyDir in $surveyDirs) {
    $found[$surveyDir.Name] = $true
    foreach ($roleName in @($Role | Select-Object -Unique)) {
        $roleFolder = Join-Path $surveyDir.FullName $roleDirs[$roleName]
        $docxFiles = Get-DocxFiles $roleFolder
        if ($docxFiles.Count -eq 0) {
            Add-Result -Rows $results -Survey $surveyDir.Name -Role $roleName -Status "missing_docx" -DocxPath "" -PdfPath "" -Detail $roleFolder
            continue
        }

        foreach ($docxFile in $docxFiles) {
            $pdfPath = [System.IO.Path]::ChangeExtension($docxFile.FullName, ".wordlayout.pdf")
            $exists = Test-Path -LiteralPath $pdfPath
            if ($exists -and -not $Overwrite.IsPresent) {
                Add-Result -Rows $results -Survey $surveyDir.Name -Role $roleName -Status "existing" -DocxPath $docxFile.FullName -PdfPath $pdfPath -Detail "Use -Overwrite to replace."
                continue
            }
            if ($DryRun.IsPresent) {
                $detail = "would_create"
                if ($exists) {
                    $detail = "would_overwrite"
                }
                Add-Result -Rows $results -Survey $surveyDir.Name -Role $roleName -Status "dry_run" -DocxPath $docxFile.FullName -PdfPath $pdfPath -Detail $detail
                continue
            }
            $jobs.Add([pscustomobject]@{
                Survey = $surveyDir.Name
                Role = $roleName
                DocxPath = $docxFile.FullName
                PdfPath = $pdfPath
            })
        }
    }
}

if ($wanted.Count -gt 0) {
    foreach ($surveyName in @($wanted.Keys | Sort-Object)) {
        if (-not $found.ContainsKey($surveyName)) {
            Add-Result -Rows $results -Survey $surveyName -Role "" -Status "missing_survey" -DocxPath "" -PdfPath "" -Detail $rootPath
        }
    }
}

$word = $null
if ($jobs.Count -gt 0) {
    $existingWord = @(Get-Process WINWORD -ErrorAction SilentlyContinue)
    if ($existingWord.Count -gt 0 -and -not $AllowExistingWord.IsPresent) {
        foreach ($job in $jobs) {
            Add-Result -Rows $results -Survey $job.Survey -Role $job.Role -Status "error" -DocxPath $job.DocxPath -PdfPath $job.PdfPath -Detail "Word is already running. Close Word and rerun, or use -AllowExistingWord."
        }
        $jobs.Clear()
    }
}

if ($jobs.Count -gt 0) {
    try {
        $word = New-Object -ComObject Word.Application
        $word.Visible = $Visible.IsPresent
        $word.DisplayAlerts = 0
        try {
            $word.AutomationSecurity = 3
        }
        catch {}
    }
    catch {
        foreach ($job in $jobs) {
            Add-Result -Rows $results -Survey $job.Survey -Role $job.Role -Status "error" -DocxPath $job.DocxPath -PdfPath $job.PdfPath -Detail $_.Exception.Message
        }
        $jobs.Clear()
    }
}

try {
    foreach ($job in $jobs) {
        try {
            Export-WordDocumentToPdf -WordApp $word -DocxPath $job.DocxPath -PdfPath $job.PdfPath
            Add-Result -Rows $results -Survey $job.Survey -Role $job.Role -Status "created" -DocxPath $job.DocxPath -PdfPath $job.PdfPath -Detail ""
        }
        catch {
            Add-Result -Rows $results -Survey $job.Survey -Role $job.Role -Status "error" -DocxPath $job.DocxPath -PdfPath $job.PdfPath -Detail $_.Exception.Message
        }
    }
}
finally {
    if ($null -ne $word) {
        try {
            $word.Quit()
        }
        catch {}
    }
}

$created = @($results | Where-Object { $_.Status -eq "created" }).Count
$existing = @($results | Where-Object { $_.Status -eq "existing" }).Count
$missingDocx = @($results | Where-Object { $_.Status -eq "missing_docx" }).Count
$missingSurvey = @($results | Where-Object { $_.Status -eq "missing_survey" }).Count
$dryRunCount = @($results | Where-Object { $_.Status -eq "dry_run" }).Count
$errors = @($results | Where-Object { $_.Status -eq "error" }).Count

Write-ResultsLog -Rows $results -TargetPath $resolvedLogPath

Write-Host ("Workspace root: {0}" -f $rootPath)
Write-Host ("Roles: {0}" -f (($Role | Select-Object -Unique) -join ", "))
Write-Host ("Rows logged: {0}" -f $results.Count)
Write-Host ("Created: {0}" -f $created)
Write-Host ("Existing: {0}" -f $existing)
Write-Host ("Dry run: {0}" -f $dryRunCount)
Write-Host ("Missing docx: {0}" -f $missingDocx)
Write-Host ("Missing survey: {0}" -f $missingSurvey)
Write-Host ("Errors: {0}" -f $errors)
Write-Host ("Log: {0}" -f $resolvedLogPath)

foreach ($row in $results) {
    if ($row.Status -notin @("error", "missing_survey")) {
        continue
    }
    Write-Host ("  {0} {1}: {2}" -f $row.Survey, $row.Role, $row.Detail)
}

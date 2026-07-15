param(
    [string]$Root = ".\repository\materialized_surveys_csv_priority",
    [string[]]$Survey = @(),
    [switch]$Overwrite,
    [switch]$Visible,
    [string]$LogPath = ""
)

$ErrorActionPreference = "Stop"
$wdFormatPDF = 17

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
        Select-Object Survey, Status, PdfPath, Detail |
        Export-Csv -LiteralPath $TargetPath -NoTypeInformation -Encoding UTF8
}

function Export-WordDocumentToPdf {
    param(
        $WordApp,
        [string]$DocxPath,
        [string]$PdfPath
    )

    $document = $null
    try {
        $document = $WordApp.Documents.Open($DocxPath, $false, $true)
        try {
            $document.ExportAsFixedFormat($PdfPath, $wdFormatPDF)
        }
        catch {
            $document.SaveAs([ref]$PdfPath, [ref]$wdFormatPDF)
        }
    }
    finally {
        if ($null -ne $document) {
            try {
                $document.Close([ref]$false)
            }
            catch {}
        }
    }
}

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

$rootPath = Resolve-Path -LiteralPath $Root
$resolvedLogPath = ""
if ([string]::IsNullOrWhiteSpace($LogPath)) {
    $resolvedLogPath = Join-Path $rootPath "docx_to_pdf_results.csv"
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

$word = $null
$opened = $null
$results = New-Object System.Collections.Generic.List[object]

try {
    $word = New-Object -ComObject Word.Application
    $word.Visible = $Visible.IsPresent
    $word.DisplayAlerts = 0

    foreach ($surveyDir in $surveyDirs) {
        $docxDir = Join-Path $surveyDir.FullName "docx"
        $pdfPath = Join-Path $surveyDir.FullName ($surveyDir.Name + ".pdf")
        $docxPath = $null
        $status = "missing_docx"
        $detail = ""

        if (Test-Path -LiteralPath $docxDir) {
            $docxCandidate = Get-ChildItem -LiteralPath $docxDir -File -Filter *.docx | Sort-Object Name | Select-Object -First 1
            if ($null -ne $docxCandidate) {
                $docxPath = $docxCandidate.FullName
            }
        }

        if ($null -eq $docxPath) {
            $results.Add([pscustomobject]@{
                Survey = $surveyDir.Name
                Status = $status
                PdfPath = $pdfPath
                Detail = $detail
            })
            continue
        }

        if ((Test-Path -LiteralPath $pdfPath) -and -not $Overwrite.IsPresent) {
            $results.Add([pscustomobject]@{
                Survey = $surveyDir.Name
                Status = "existing"
                PdfPath = $pdfPath
                Detail = $docxPath
            })
            continue
        }

        try {
            if (Test-Path -LiteralPath $pdfPath) {
                Remove-Item -LiteralPath $pdfPath -Force
            }
            Export-WordDocumentToPdf -WordApp $word -DocxPath $docxPath -PdfPath $pdfPath

            $results.Add([pscustomobject]@{
                Survey = $surveyDir.Name
                Status = "created"
                PdfPath = $pdfPath
                Detail = $docxPath
            })
        }
        catch {
            if ($null -ne $opened) {
                try {
                    $opened.Close([ref]$false)
                }
                catch {}
                $opened = $null
            }
            $results.Add([pscustomobject]@{
                Survey = $surveyDir.Name
                Status = "error"
                PdfPath = $pdfPath
                Detail = $_.Exception.Message
            })
        }
    }
}
finally {
    if ($null -ne $opened) {
        try {
            $opened.Close([ref]$false)
        }
        catch {}
    }
    if ($null -ne $word) {
        try {
            $word.Quit()
        }
        catch {}
    }
}

$created = ($results | Where-Object { $_.Status -eq "created" }).Count
$existing = ($results | Where-Object { $_.Status -eq "existing" }).Count
$missing = ($results | Where-Object { $_.Status -eq "missing_docx" }).Count
$errors = ($results | Where-Object { $_.Status -eq "error" }).Count

Write-ResultsLog -Rows $results -TargetPath $resolvedLogPath

Write-Host ("Root: {0}" -f $rootPath)
Write-Host ("Surveys scanned: {0}" -f $results.Count)
Write-Host ("Created: {0}" -f $created)
Write-Host ("Existing: {0}" -f $existing)
Write-Host ("Missing docx: {0}" -f $missing)
Write-Host ("Errors: {0}" -f $errors)
Write-Host ("Log: {0}" -f $resolvedLogPath)

foreach ($row in $results) {
    if ($row.Status -ne "error") {
        continue
    }
    Write-Host ("  {0}: {1}" -f $row.Survey, $row.Detail)
}

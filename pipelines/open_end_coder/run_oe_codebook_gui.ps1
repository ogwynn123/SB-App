param(
    [string]$ScriptPath = "oe_codebook_gui.py",
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ScriptArgs
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not [System.IO.Path]::IsPathRooted($ScriptPath)) {
    $ScriptPath = Join-Path $scriptRoot $ScriptPath
}

$exitCode = 0
Push-Location $scriptRoot
try {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3 $ScriptPath @ScriptArgs
        $exitCode = $LASTEXITCODE
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        & python $ScriptPath @ScriptArgs
        $exitCode = $LASTEXITCODE
    } else {
        throw "Python interpreter not found (py or python)."
    }
} finally {
    Pop-Location
}

exit $exitCode

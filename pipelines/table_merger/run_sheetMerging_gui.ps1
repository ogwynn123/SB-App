param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$GuiArgs
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$exitCode = 0

Push-Location $scriptRoot
try {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3 ".\sheetMerging_gui.py" @GuiArgs
        $exitCode = $LASTEXITCODE
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        & python ".\sheetMerging_gui.py" @GuiArgs
        $exitCode = $LASTEXITCODE
    } else {
        throw "Python interpreter not found (py or python)."
    }
} finally {
    Pop-Location
}

exit $exitCode

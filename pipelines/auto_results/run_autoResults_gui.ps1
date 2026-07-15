param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ScriptArgs
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$exitCode = 0

Push-Location $scriptRoot
try {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3 ".\autoResults_gui.py" @ScriptArgs
        $exitCode = $LASTEXITCODE
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        & python ".\autoResults_gui.py" @ScriptArgs
        $exitCode = $LASTEXITCODE
    } else {
        throw "Python interpreter not found (py or python)."
    }
} finally {
    Pop-Location
}

exit $exitCode

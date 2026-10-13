param(
    [string] $BaseUrl = 'http://localhost:8000/illness-preview/'
)

$ErrorActionPreference = 'Stop'
$taskUrl = [Uri] $BaseUrl
if (-not $taskUrl.IsAbsoluteUri -or $taskUrl.Scheme -notin @('http', 'https') -or $taskUrl.Host -notin @('localhost', '127.0.0.1', '[::1]') -or $taskUrl.UserInfo) {
    throw 'Use an HTTP(S) loopback URL for an isolated local Autofever test server.'
}
$taskNpx = if (Get-Command npx.cmd -ErrorAction SilentlyContinue) { 'npx.cmd' } else { 'npx' }
$taskSession = "autofever-qa-$PID"
$taskTests = @('mobile-refinement-qa.js', 'mobile-help-backup-qa.js', 'mobile-refinement-regression-qa.js', 'mobile-dock-qa.js', 'mobile-multitab-qa.js', 'accessibility.js', 'contact-import.js', 'local-vault-deletion.js', 'helper-language.js', 'app-language.js')

function Invoke-TaskBrowser {
    param([string[]] $Arguments)
    $taskOutput = & $taskNpx --yes --package '@playwright/cli@0.1.22' playwright-cli "-s=$taskSession" @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) { throw ($taskOutput -join "`n") }
    if ($taskOutput | Select-String -Pattern '^(### Error|Error:)') { throw ($taskOutput -join "`n") }
    if ($Arguments[0] -eq 'run-code') {
        $taskResults = @($taskOutput | Select-String -Pattern '^"PASS:')
        if ($taskResults.Count -ne 1) { throw "No single explicit successful test result was returned. Refusing to report success.`n$($taskOutput -join "`n")" }
    }
    $taskOutput | Select-String -Pattern '^"PASS:|^### Error|^Error:'
}

Push-Location $PSScriptRoot
try {
    & (Join-Path (Join-Path $PSScriptRoot 'tests') 'runner-contract.ps1')
    Invoke-TaskBrowser -Arguments @('open', $BaseUrl)
    foreach ($taskTest in $taskTests) {
        $taskPath = Join-Path (Join-Path $PSScriptRoot 'tests') $taskTest
        Invoke-TaskBrowser -Arguments @('run-code', "--filename=$taskPath")
    }
    Write-Output "All $($taskTests.Count) browser suites passed. No messages were sent."
} finally {
    & $taskNpx --yes --package '@playwright/cli@0.1.22' playwright-cli "-s=$taskSession" close 2>&1 | Out-Null
    Pop-Location
}

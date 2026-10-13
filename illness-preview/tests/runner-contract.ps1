$ErrorActionPreference = 'Stop'
$taskRunnerPath = Join-Path (Split-Path $PSScriptRoot -Parent) 'verify.ps1'
$taskTokens = $null
$taskParseErrors = $null
$taskAst = [System.Management.Automation.Language.Parser]::ParseFile($taskRunnerPath, [ref]$taskTokens, [ref]$taskParseErrors)
if ($taskParseErrors.Count) { throw 'Test runner contains a syntax error.' }
$taskFunction = $taskAst.Find({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Invoke-TaskBrowser' }, $true)
if (-not $taskFunction) { throw 'Runner command boundary is missing.' }
. ([scriptblock]::Create($taskFunction.Extent.Text))

# Exercise the real result-handling function without opening browsers or running npm.
function Invoke-FixtureCli {
    $global:LASTEXITCODE = $script:fixtureExit
    return $script:fixtureOutput
}
$taskNpx = 'Invoke-FixtureCli'
$taskSession = 'contract-test'
$taskCases = @(
    @{ Name = 'missing result'; Output = @('Browser not open'); Exit = 0; Accept = $false },
    @{ Name = 'tool error despite zero exit'; Output = @('### Error', 'Error: browser closed'); Exit = 0; Accept = $false },
    @{ Name = 'ambiguous duplicate result'; Output = @('"PASS: first result"', '"PASS: second result"'); Exit = 0; Accept = $false },
    @{ Name = 'failed process'; Output = @('"PASS: stale output"'); Exit = 1; Accept = $false },
    @{ Name = 'one explicit passing result'; Output = @('### Result', '"PASS: verified behavior"', '### Ran Playwright code'); Exit = 0; Accept = $true }
)
foreach ($taskCase in $taskCases) {
    $script:fixtureOutput = $taskCase.Output
    $script:fixtureExit = $taskCase.Exit
    $taskAccepted = $true
    try { Invoke-TaskBrowser -Arguments @('run-code', '--filename=fixture.js') | Out-Null }
    catch { $taskAccepted = $false }
    if ($taskAccepted -ne $taskCase.Accept) { throw "Runner contract failed: $($taskCase.Name) was accepted=$taskAccepted" }
}
Write-Output 'PASS: runner rejects missing, duplicate and error results; accepts one explicit successful result.'

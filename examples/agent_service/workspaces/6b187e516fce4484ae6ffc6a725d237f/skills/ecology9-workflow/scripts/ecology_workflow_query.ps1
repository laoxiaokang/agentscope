[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$Workcode,

    [ValidateSet('todo', 'started', 'handled', 'processed', 'creatable', 'summary')]
    [string]$Mode = 'summary',

    [switch]$IncludeItems,

    [ValidateRange(1, 200)]
    [int]$PageSize = 100,

    [ValidateRange(1, 5000)]
    [int]$MaxItems = 1000
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$pythonCommand = Get-Command -Name 'python' -CommandType Application -ErrorAction SilentlyContinue |
    Select-Object -First 1
$pythonPrefix = @('-B')
if ($null -eq $pythonCommand) {
    $pythonCommand = Get-Command -Name 'py' -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    $pythonPrefix = @('-3', '-B')
}
if ($null -eq $pythonCommand) {
    [Console]::Error.WriteLine((
        [pscustomobject][ordered]@{
            error = 'python_unavailable'
            message = 'Python 3 is required for Ecology workflow queries.'
            elapsedMs = 0
        } | ConvertTo-Json -Compress
    ))
    exit 1
}

$pythonScript = Join-Path $PSScriptRoot 'ecology_workflow_query.py'
$pythonArgs = [System.Collections.Generic.List[string]]::new()
foreach ($value in $pythonPrefix) { $pythonArgs.Add($value) }
$pythonArgs.Add($pythonScript)
$pythonArgs.Add('--workcode')
$pythonArgs.Add($Workcode)
$pythonArgs.Add('--mode')
$pythonArgs.Add($Mode)
$pythonArgs.Add('--page-size')
$pythonArgs.Add([string]$PageSize)
$pythonArgs.Add('--max-items')
$pythonArgs.Add([string]$MaxItems)
if ($IncludeItems.IsPresent) { $pythonArgs.Add('--include-items') }

$previousPythonUtf8 = $env:PYTHONUTF8
try {
    $env:PYTHONUTF8 = '1'
    & $pythonCommand.Source @pythonArgs
    $exitCode = $LASTEXITCODE
}
catch {
    [Console]::Error.WriteLine((
        [pscustomobject][ordered]@{
            error = 'query_failed'
            message = 'Unable to start the Python workflow query.'
            elapsedMs = 0
        } | ConvertTo-Json -Compress
    ))
    $exitCode = 1
}
finally {
    $env:PYTHONUTF8 = $previousPythonUtf8
}

exit $exitCode

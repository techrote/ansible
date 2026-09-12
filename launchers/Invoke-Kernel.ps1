[CmdletBinding()]
param(
    [ValidateSet('run-slot', 'panel', 'status', 'qualify', 'contract')]
    [string]$Mode = 'status',
    [ValidateRange(1, 4)]
    [int]$Slot = 1
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
try {
    # Interpreter discovery is a trusted operator bootstrap, never task-controlled.
    $launcher = Get-Command 'py.exe' -CommandType Application -ErrorAction Stop
    $python = & $launcher.Source -3 -I -S -c 'import sys; print(sys.executable)'
    if ($LASTEXITCODE -ne 0 -or -not $python -or -not [IO.Path]::IsPathRooted($python)) {
        throw 'Install Python 3.12+ with the Windows Python launcher.'
    }
    $pythonArgs = @($Mode)
    if ($Mode -eq 'run-slot') { $pythonArgs += [string]$Slot }
    & $python -I -S -B (Join-Path $root 'run_kernel.py') @pythonArgs
    exit $LASTEXITCODE
} catch {
    Write-Error $_
    exit 3
}

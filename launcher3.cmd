@echo off
setlocal
pushd "%~dp0"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0launchers\Invoke-Kernel.ps1" -Mode run-slot -Slot 3
set "rc=%ERRORLEVEL%"
popd
exit /b %rc%

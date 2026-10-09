# MemoIsle WinUI desktop build script (Windows PowerShell)
# Output: winui\MemoIsle-winui.zip -- unzip and double-click MemoIsle.Desktop.exe
# Usage:
#   .\build-windows.ps1                    # self-contained (~200MB folder, no runtime needed)
#   .\build-windows.ps1 -FrameworkDependent # slim build (~20MB, needs .NET 8 Desktop Runtime + WinAppSDK Runtime)

param(
    [switch]$FrameworkDependent
)

$ErrorActionPreference = "Stop"
$projectDir = Join-Path $PSScriptRoot "MemoIsle.Desktop"
$publishDir = Join-Path $projectDir "publish"
$archivePath = Join-Path $PSScriptRoot "MemoIsle-winui.zip"

$extraArgs = @()
if ($FrameworkDependent) {
    $extraArgs += "-p:FrameworkDependent=true"
    Write-Host "Mode: framework-dependent (slim)"
}
else {
    Write-Host "Mode: self-contained (no runtime required)"
}

Write-Host "[1/3] Building Release ..."
Push-Location $projectDir
dotnet build -c Release -p:Platform=x64 @extraArgs

Write-Host "[2/3] Publishing ..."
dotnet publish -c Release -p:Platform=x64 -o publish @extraArgs
Pop-Location

Write-Host "[3/3] Creating zip archive ..."
if (Test-Path $archivePath) {
    Remove-Item $archivePath -Force
}
Compress-Archive -Path (Join-Path $publishDir "*") -DestinationPath $archivePath

Write-Host ""
Write-Host "Done: $archivePath"
Write-Host "Unzip it and run MemoIsle.Desktop.exe."
Write-Host "Backend URL can be overridden with MEMOISLE_API_BASE_URL (default http://127.0.0.1:8000/api/v1)."

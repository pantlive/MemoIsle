# MemoIsle 扩展一键下载/更新脚本。
# 用法：运行同目录下的 install.cmd，或 PowerShell 执行本文件。
#   默认从本机后端下载；部署到其他地址时传入 API 地址：
#     install.ps1 -ApiBase "https://api.example.com/api/v1"
param(
    [string]$ApiBase = "http://127.0.0.1:8000/api/v1"
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$url = "$ApiBase/browser-extension/download"
$zipPath = Join-Path $env:TEMP "memoisle-extension.zip"
$stageDir = Join-Path $env:TEMP "memoisle-extension-stage"

# 脚本自身不随扩展包覆盖，避免运行中被替换。
$keepScripts = @("install.cmd", "install.ps1")

Write-Host "正在从 $url 下载最新扩展……"
Invoke-WebRequest -Uri $url -OutFile $zipPath

if (Test-Path $stageDir) {
    Remove-Item -Recurse -Force $stageDir
}
Expand-Archive -Path $zipPath -DestinationPath $stageDir -Force
$sourceDir = Join-Path $stageDir "memoisle-extension"
if (-not (Test-Path (Join-Path $sourceDir "manifest.json"))) {
    Remove-Item -Force $zipPath
    Remove-Item -Recurse -Force $stageDir
    throw "下载内容不是有效的 MemoIsle 扩展包"
}

# 记录解压后的文件清单，用于清理旧版本遗留文件。
$incomingFiles = @{}
Get-ChildItem -Path $sourceDir -Recurse -File | ForEach-Object {
    $incomingFiles[$_.FullName.Substring($sourceDir.Length + 1)] = $true
}

# 逐文件覆盖到本目录（跳过脚本自身）。
Get-ChildItem -Path $sourceDir -Recurse -File | ForEach-Object {
    $relative = $_.FullName.Substring($sourceDir.Length + 1)
    if ($keepScripts -contains $relative) {
        return
    }
    $target = Join-Path $scriptDir $relative
    $targetParent = Split-Path -Parent $target
    if (-not (Test-Path $targetParent)) {
        New-Item -ItemType Directory -Path $targetParent -Force | Out-Null
    }
    Copy-Item -Path $_.FullName -Destination $target -Force
}

# 删除本目录里旧版本遗留、但新版本已不包含的文件。
$staleFiles = Get-ChildItem -Path $scriptDir -Recurse -File | Where-Object {
    $relative = $_.FullName.Substring($scriptDir.Length + 1)
    return (-not $incomingFiles.ContainsKey($relative)) -and
        ($keepScripts -notcontains $relative) -and
        (-not $_.FullName.StartsWith((Join-Path $scriptDir "tests")))
}
$staleFiles | Remove-Item -Force

Remove-Item -Force $zipPath
Remove-Item -Recurse -Force $stageDir
$manifestJson = Get-Content -Raw (Join-Path $scriptDir "manifest.json") | ConvertFrom-Json
Write-Host "已完成：$scriptDir 已更新为 v$($manifestJson.version)"
Write-Host ""

# 打开扩展管理页，请在页面里点击“重新加载”让更新生效。
$opened = $false
foreach ($browser in @("chrome", "msedge", "firefox")) {
    try {
        Start-Process $browser -ArgumentList "chrome://extensions"
        $opened = $true
        break
    }
    catch {
        # 尝试下一个浏览器。
    }
}
if (-not $opened) {
    Write-Host "请手动打开浏览器并访问 chrome://extensions。"
}

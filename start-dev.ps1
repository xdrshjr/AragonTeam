<#
.SYNOPSIS
    一键启动 AragonTeam 前后端开发服务（全部在当前窗口内）。

.DESCRIPTION
    在**当前** PowerShell 窗口中同时启动：
      - 后端 Flask (http://localhost:5000)  —— 使用 backend\.venv 隔离环境
      - 前端 Next.js (http://localhost:3000)
    两个服务的日志混合输出到本窗口，Ctrl+C 一次性停止两者（含子进程树）。
    首次运行会自动创建后端虚拟环境、安装依赖、准备 .env.local。
    之后再次运行只启动服务，不重复安装（除非加 -Install）。

.PARAMETER Install
    强制重新安装依赖（后端 pip install、前端 npm install），即使已存在。

.EXAMPLE
    .\start-dev.ps1
    首次自动装依赖并启动；之后直接启动。

.EXAMPLE
    .\start-dev.ps1 -Install
    强制刷新前后端依赖后启动。

.NOTES
    Windows / PowerShell 5.1 兼容。

    可选：启用「真实 Agent 执行」（真实 LLM 产出工作产物）；不设即离线模式，开箱即用。
    在运行本脚本前于当前窗口设置以下变量，即可让 dev/qa-agent 推进时调用真实大模型
    （见 README「真实 Agent 执行引擎」）：
        $env:AGENT_LLM_PROVIDER = 'anthropic'      # 或 'openai'
        $env:AGENT_LLM_API_KEY  = '<your-key>'     # 也可用 ANTHROPIC_API_KEY / OPENAI_API_KEY
    其余 AGENT_LLM_MODEL / _BASE_URL / _MAX_TOKENS / _TIMEOUT / _MAX_RETRIES / _WALL_BUDGET 均有默认值。
#>
[CmdletBinding()]
param(
    [switch]$Install
)

$ErrorActionPreference = 'Stop'

$root        = $PSScriptRoot
$backendDir  = Join-Path $root 'backend'
$frontendDir = Join-Path $root 'frontend'

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-Fail($msg) { Write-Host "!!  $msg" -ForegroundColor Red }

# 杀掉整棵进程树：npm.cmd / python 都会派生子进程，只杀父进程会留下孤儿占端口。
function Stop-ProcessTree($proc) {
    if ($null -eq $proc -or $proc.HasExited) { return }
    & taskkill.exe /PID $proc.Id /T /F 2>$null | Out-Null
}

# ---- 预检：目录与工具链 ---------------------------------------------------
if (-not (Test-Path $backendDir))  { Write-Fail "找不到 backend 目录：$backendDir";  exit 1 }
if (-not (Test-Path $frontendDir)) { Write-Fail "找不到 frontend 目录：$frontendDir"; exit 1 }

$missing = @()
foreach ($tool in 'python', 'node', 'npm') {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { $missing += $tool }
}
if ($missing.Count -gt 0) {
    Write-Fail ("缺少必要工具：{0}。请先安装后重试。" -f ($missing -join ', '))
    exit 1
}

# Start-Process 需要可执行文件本体；npm 在 Windows 上是 npm.cmd。
$npmExe = (Get-Command 'npm.cmd' -CommandType Application -ErrorAction SilentlyContinue).Source
if (-not $npmExe) { $npmExe = (Get-Command 'npm' -CommandType Application).Source }

# ---- 后端依赖准备（当前窗口内串行执行）-----------------------------------
$pythonExe = Join-Path $backendDir '.venv\Scripts\python.exe'
if ($Install -or -not (Test-Path $pythonExe)) {
    if (-not (Test-Path $pythonExe)) {
        Write-Step '创建后端虚拟环境 .venv ...'
        & python -m venv (Join-Path $backendDir '.venv')
        if ($LASTEXITCODE -ne 0) { Write-Fail '创建虚拟环境失败'; exit 1 }
    }
    Write-Step '安装后端依赖 ...'
    & $pythonExe -m pip install --upgrade pip
    & $pythonExe -m pip install -r (Join-Path $backendDir 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { Write-Fail '后端依赖安装失败'; exit 1 }
}

# ---- 前端依赖准备 ---------------------------------------------------------
Push-Location $frontendDir
try {
    if ($Install -or -not (Test-Path '.\node_modules')) {
        Write-Step '安装前端依赖 (npm install) ...'
        & $npmExe install
        if ($LASTEXITCODE -ne 0) { Write-Fail '前端依赖安装失败'; exit 1 }
    }
    if (-not (Test-Path '.\.env.local')) {
        Write-Step '生成 .env.local ...'
        Copy-Item '.env.local.example' '.env.local'
    }
}
finally {
    Pop-Location
}

# ---- 在当前窗口内同时拉起两个服务 -----------------------------------------
$backendProc  = $null
$frontendProc = $null
try {
    Write-Step '启动 Flask (http://localhost:5000) ...'
    $backendProc = Start-Process -FilePath $pythonExe -ArgumentList 'app.py' `
        -WorkingDirectory $backendDir -NoNewWindow -PassThru

    Write-Step '启动 Next.js (http://localhost:3000) ...'
    $frontendProc = Start-Process -FilePath $npmExe -ArgumentList 'run', 'dev' `
        -WorkingDirectory $frontendDir -NoNewWindow -PassThru

    Write-Host ''
    Write-Host '前后端已在当前窗口启动（日志混合输出）：' -ForegroundColor Green
    Write-Host '  后端  ->  http://localhost:5000  (健康检查 /api/health)'
    Write-Host '  前端  ->  http://localhost:3000'
    Write-Host '  按 Ctrl+C 停止全部服务。'
    Write-Host ''

    while (-not ($backendProc.HasExited -or $frontendProc.HasExited)) {
        Start-Sleep -Milliseconds 500
    }

    if ($backendProc.HasExited)  { Write-Fail "后端进程已退出（exit $($backendProc.ExitCode)），正在停止前端 ..." }
    if ($frontendProc.HasExited) { Write-Fail "前端进程已退出（exit $($frontendProc.ExitCode)），正在停止后端 ..." }
}
finally {
    Stop-ProcessTree $backendProc
    Stop-ProcessTree $frontendProc
    Write-Host '==> 前后端服务已停止。' -ForegroundColor Cyan
}

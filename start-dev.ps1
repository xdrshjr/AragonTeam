<#
.SYNOPSIS
    一键同时启动 AragonTeam 前后端开发服务。

.DESCRIPTION
    在两个独立的 PowerShell 窗口中分别启动：
      - 后端 Flask (http://localhost:5000)  —— 使用 backend\.venv 隔离环境
      - 前端 Next.js (http://localhost:3000)
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
    Windows / PowerShell 5.1 兼容；每个服务独占一个窗口，Ctrl+C 各自停止。
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

# 让子窗口知道是否强制重装（通过环境变量传递，子进程自动继承）
$env:ARAGON_FORCE_INSTALL = if ($Install) { '1' } else { '0' }

# ---- 后端启动命令（子窗口内执行，仅用单引号避免父进程展开）---------------
$backendCmd = @'
$host.UI.RawUI.WindowTitle = 'AragonTeam Backend :5000'
$ErrorActionPreference = 'Stop'

# —— 可选：启用「真实 Agent 执行」（真实 LLM 产出工作产物）；不设即离线模式，开箱即用 ——
# 取消下面两行注释并填入凭据即可让 dev/qa-agent 推进时调用真实大模型（见 README「真实 Agent 执行引擎」）：
#   $env:AGENT_LLM_PROVIDER = 'anthropic'          # 或 'openai'
#   $env:AGENT_LLM_API_KEY  = '<your-key>'         # 也可用 ANTHROPIC_API_KEY / OPENAI_API_KEY
# 其余 AGENT_LLM_MODEL / _BASE_URL / _MAX_TOKENS / _TIMEOUT / _MAX_RETRIES / _WALL_BUDGET 均有默认值。

$py = '.\.venv\Scripts\python.exe'
if ($env:ARAGON_FORCE_INSTALL -eq '1' -or -not (Test-Path $py)) {
    if (-not (Test-Path $py)) {
        Write-Host '==> 创建后端虚拟环境 .venv ...' -ForegroundColor Cyan
        python -m venv .venv
    }
    Write-Host '==> 安装后端依赖 ...' -ForegroundColor Cyan
    & $py -m pip install --upgrade pip
    & $py -m pip install -r requirements.txt
}
Write-Host '==> 启动 Flask (http://localhost:5000) ...' -ForegroundColor Green
& $py app.py
'@

# ---- 前端启动命令 ---------------------------------------------------------
$frontendCmd = @'
$host.UI.RawUI.WindowTitle = 'AragonTeam Frontend :3000'
$ErrorActionPreference = 'Stop'
if ($env:ARAGON_FORCE_INSTALL -eq '1' -or -not (Test-Path '.\node_modules')) {
    Write-Host '==> 安装前端依赖 (npm install) ...' -ForegroundColor Cyan
    npm install
}
if (-not (Test-Path '.\.env.local')) {
    Write-Host '==> 生成 .env.local ...' -ForegroundColor Cyan
    Copy-Item '.env.local.example' '.env.local'
}
Write-Host '==> 启动 Next.js (http://localhost:3000) ...' -ForegroundColor Green
npm run dev
'@

# ---- 分别拉起两个窗口 -----------------------------------------------------
Write-Step '启动后端窗口 ...'
Start-Process -FilePath 'powershell.exe' `
    -ArgumentList @('-NoExit', '-Command', $backendCmd) `
    -WorkingDirectory $backendDir

Write-Step '启动前端窗口 ...'
Start-Process -FilePath 'powershell.exe' `
    -ArgumentList @('-NoExit', '-Command', $frontendCmd) `
    -WorkingDirectory $frontendDir

Write-Host ''
Write-Host '前后端已在独立窗口启动：' -ForegroundColor Green
Write-Host '  后端  ->  http://localhost:5000  (健康检查 /api/health)'
Write-Host '  前端  ->  http://localhost:3000'
Write-Host ''
Write-Host '首次启动需等待依赖安装完成；关闭对应窗口或在其中 Ctrl+C 即可停止该服务。'

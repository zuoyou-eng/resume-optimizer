# 简历优化助手 · 一键启动（Windows / PowerShell 5.1+）
#
# 由「启动项目.bat」调用，也可以直接右键"使用 PowerShell 运行"。
# 首次运行会自动创建虚拟环境并安装依赖，需要联网，约 1-3 分钟。
#
# 停止服务：关掉弹出的「后端」「前端」两个窗口即可。

# 刻意用 Continue 而不是 Stop：PowerShell 5.1 会把"原生命令写 stderr"升级为
# NativeCommandError 终止错误（pip / npm 失败时必然写 stderr），
# 导致脚本静默退出、用户看不到任何提示。这里改为自行检查 $LASTEXITCODE。
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
if (-not $Root) { $Root = (Get-Location).Path }

function Write-Step([string]$msg) { Write-Host "  $msg" -ForegroundColor Cyan }
function Write-Ok([string]$msg)   { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Warn([string]$msg) { Write-Host "  [!]  $msg" -ForegroundColor Yellow }

function Stop-WithMessage([string]$msg) {
    Write-Host ""
    Write-Host "  [失败] $msg" -ForegroundColor Red
    Write-Host ""
    Read-Host "  按回车键退出"
    exit 1
}

function Test-PortFree([int]$port) {
    $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    return ($null -eq $conn)
}

# 装依赖：先按用户当前环境装；若失败，清空代理再试一次。
# 为什么需要这一步：国内用户常常配了 HTTP_PROXY/HTTPS_PROXY 指向本地代理
# （如 Clash 的 7897），但代理没开或已退出——此时 pip / npm 会立刻连接失败，
# 而错误信息只显示一堆超时，用户很难自己定位。这是实测抓到的高频失败原因。
function Install-Dependencies {
    param(
        [string]$What,
        [scriptblock]$Install
    )
    & $Install
    if ($LASTEXITCODE -eq 0) { return $true }

    Write-Warn "$What 首次安装失败，可能是代理配置失效，正在清空代理后重试..."
    $env:HTTP_PROXY = $null;  $env:HTTPS_PROXY = $null
    $env:http_proxy = $null;  $env:https_proxy = $null
    $env:ALL_PROXY = $null;   $env:all_proxy = $null
    & $Install
    return ($LASTEXITCODE -eq 0)
}

function Wait-ForUrl([string]$url, [int]$maxSeconds, [string]$what) {
    for ($i = 0; $i -lt $maxSeconds; $i++) {
        try {
            $null = Invoke-WebRequest -Uri $url -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop
            return $true
        } catch {
            Start-Sleep -Seconds 1
        }
    }
    Stop-WithMessage "$what 启动超时，请查看对应窗口里的报错信息。"
    return $false
}

Write-Host ""
Write-Host "  ============================================"
Write-Host "       简历优化助手 · 一键启动"
Write-Host "  ============================================"
Write-Host ""

# ---------- 1. 检查 Python ----------
$pyCmd = $null
if (Get-Command py -ErrorAction SilentlyContinue) { $pyCmd = "py" }
elseif (Get-Command python -ErrorAction SilentlyContinue) { $pyCmd = "python" }
if (-not $pyCmd) {
    Stop-WithMessage "未检测到 Python。请先安装 Python 3.11 或更高版本：https://www.python.org/downloads/ （安装时勾选 Add Python to PATH）"
}
Write-Step "[1/6] 已检测到 Python"

# ---------- 2. 后端依赖 ----------
$venvPy = Join-Path $Root "backend\.venv\Scripts\python.exe"
if (Test-Path $venvPy) {
    Write-Step "[2/6] 后端环境已就绪"
} else {
    Write-Step "[2/6] 首次运行：创建虚拟环境并安装后端依赖（需联网，约 1-2 分钟）"
    & $pyCmd -3 -m venv (Join-Path $Root "backend\.venv")
    if (-not (Test-Path $venvPy)) { Stop-WithMessage "虚拟环境创建失败，请检查 Python 安装是否完整。" }

    $reqFile = Join-Path $Root "backend\requirements.txt"
    $ok = Install-Dependencies -What "后端依赖" -Install { & $venvPy -m pip install -r $reqFile }
    if (-not $ok) {
        Stop-WithMessage "后端依赖安装失败。常见原因：1) 网络不通或 PyPI 被屏蔽，可换国内镜像源重试（pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple）；2) 公司内网必须走代理时，请确认代理服务已正常启动。"
    }
    Write-Ok "后端依赖安装完成"
}

# ---------- 3. 选择可用后端端口 ----------
$backendPort = 8000
while (-not (Test-PortFree $backendPort)) {
    $backendPort++
    if ($backendPort -gt 8100) { Stop-WithMessage "8000-8100 端口全部被占用，请先释放一个端口再运行。" }
}
Write-Step "[3/6] 后端端口：$backendPort"

# ---------- 4. 启动后端 ----------
Write-Step "[4/6] 正在启动后端服务..."
$backendDir = Join-Path $Root "backend"
Start-Process powershell -WorkingDirectory $backendDir -ArgumentList @(
    "-NoExit", "-Command",
    "cd '$backendDir'; .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port $backendPort"
)
Wait-ForUrl "http://127.0.0.1:$backendPort/api/v1/health" 40 "后端" | Out-Null
Write-Ok "后端已就绪（接口文档 http://127.0.0.1:$backendPort/docs）"

# ---------- 5. 前端依赖 ----------
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Write-Warn "未检测到 Node.js，跳过前端启动。"
    Write-Host ""
    Write-Host "  后端 API 已在运行，可直接使用接口文档：http://127.0.0.1:$backendPort/docs"
    Write-Host "  如需网页界面，请安装 Node.js 18+ 后重新运行本脚本：https://nodejs.org/"
    Write-Host ""
    Read-Host "  按回车键退出"
    exit 0
}

$nodeModules = Join-Path $Root "frontend\node_modules"
if (Test-Path $nodeModules) {
    Write-Step "[5/6] 前端依赖已就绪"
} else {
    Write-Step "[5/6] 首次运行：安装前端依赖（需联网，约 1-2 分钟）"
    $frontendDir = Join-Path $Root "frontend"
    $ok = Install-Dependencies -What "前端依赖" -Install {
        Push-Location $frontendDir
        try { & npm install } finally { Pop-Location }
    }
    if (-not $ok) { Stop-WithMessage "前端依赖安装失败，请检查网络后重试；若配了代理，请确认代理服务已启动。" }
    Write-Ok "前端依赖安装完成"
}

# ---------- 6. 启动前端并打开浏览器 ----------
$frontendPort = 5173
while (-not (Test-PortFree $frontendPort)) {
    $frontendPort++
    if ($frontendPort -gt 5200) { Stop-WithMessage "5173-5200 端口全部被占用，请先释放一个端口再运行。" }
}

Write-Step "[6/6] 正在启动前端服务（端口 $frontendPort）..."
$frontendDir = Join-Path $Root "frontend"
Start-Process powershell -WorkingDirectory $frontendDir -ArgumentList @(
    "-NoExit", "-Command",
    "`$env:API_TARGET='http://127.0.0.1:$backendPort'; cd '$frontendDir'; npm run dev"
)
# 就绪检测用 localhost 而不是 127.0.0.1：Vite 默认只绑 IPv6（[::1]），
# 用 127.0.0.1 探测会永远超时——后端 uvicorn 绑 127.0.0.1 所以没这个问题。
Wait-ForUrl "http://localhost:$frontendPort/" 60 "前端" | Out-Null

Write-Host ""
Write-Host "  ============================================"
Write-Host "       启动完成，浏览器即将自动打开"
Write-Host "  ============================================"
Write-Host ""
Write-Host "     网页界面   http://localhost:$frontendPort/"
Write-Host "     接口文档   http://127.0.0.1:$backendPort/docs"
Write-Host ""
Write-Host "     提示：关闭本窗口不会停止服务，"
Write-Host "           直接关掉「后端」「前端」两个窗口即可。"
Write-Host ""

Start-Process "http://localhost:$frontendPort/"
Read-Host "  按回车键退出"

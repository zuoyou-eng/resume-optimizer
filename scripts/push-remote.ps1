# 一键推送到远程仓库
# 用法：
#   .\scripts\push-remote.ps1 -RepoUrl https://github.com/<你的用户名>/resume-optimizer.git
#   .\scripts\push-remote.ps1 -RepoUrl <url> -DryRun      # 只做安全检查，不推送
#
# 脚本会依次做四件事：
#   1. 推送前三项安全复核（任一不通过则中止，不会推送）
#   2. 关联远程仓库 origin（已存在则先移除旧的）
#   3. git push -u origin main
#   4. 推送后核对远程分支与本地一致
#
# 关于凭据：push 时 Windows 会弹出凭据窗口，请在那里输入
#   GitHub：用户名 + Personal Access Token（不是登录密码）
#   Gitee ：用户名 + 登录密码（或私人令牌）
# 凭据由 Windows 凭据管理器保存，不经过任何脚本文件。

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$RepoUrl,

    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot

function Write-Step([string]$msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }
function Write-Ok([string]$msg)   { Write-Host "  [OK]   $msg" -ForegroundColor Green }
function Write-Bad([string]$msg)  { Write-Host "  [FAIL] $msg" -ForegroundColor Red }
function Write-Info([string]$msg) { Write-Host "  [..]   $msg" -ForegroundColor Gray }

Set-Location $repoRoot
Write-Host "仓库根目录: $repoRoot" -ForegroundColor White
Write-Host "目标远程  : $RepoUrl" -ForegroundColor White

# ---------- 1. 安全复核 ----------
Write-Step "推送前安全复核"

# 1.1 工作区必须干净
$dirty = git status --porcelain
if ($dirty) {
    Write-Bad "工作区有未提交改动，先提交或暂存后再推送："
    Write-Host ($dirty -join "`n")
    exit 1
}
Write-Ok "工作区干净（无未提交改动）"

# 1.2 文件数合理性检查
# 不做精确匹配（正常开发会增减文件），只防两种异常：
#   - 过多：.gitignore 失效导致 node_modules/ 或 backend/data/ 涌入
#   - 过少：仓库被误删或 .gitignore 误伤源码
$fileCount = (git ls-files | Measure-Object).Count
if ($fileCount -gt 200 -or $fileCount -lt 90) {
    Write-Bad "受控文件数为 $fileCount，不在合理区间 90-200。"
    Write-Host "  过多通常是 .gitignore 失效；过少通常是源码被误忽略。请先排查。"
    exit 1
}
Write-Ok "受控文件数 $fileCount（在合理区间 90-200）"

# 1.3 真实简历数据库绝不能被跟踪（代码管理规范 4.8 红线 1）
$dbTracked = (git ls-files | Select-String -Pattern "data/resume\.db" | Measure-Object).Count
if ($dbTracked -gt 0) {
    Write-Bad "检测到 backend/data/resume.db 被版本跟踪！其中含 45MB 真实简历原文。"
    Write-Host "  立即中止。请检查 .gitignore 中 'backend/data/' 是否仍然存在。"
    exit 1
}
Write-Ok "真实简历库未被跟踪（红线 1 通过）"

# 1.4 大文件检查（>1MB 的应只有 package-lock.json 与 6 张截图）
# 注意：不能用 git ls-files -z，其 NUL 分隔在 PowerShell 中不会被拆分成多个字符串
$big = git ls-files | ForEach-Object {
    $p = $_.Trim()
    if (-not $p) { return }
    try {
        if (Test-Path -LiteralPath $p -PathType Leaf -ErrorAction Stop) {
            $len = (Get-Item -LiteralPath $p -ErrorAction Stop).Length
            if ($len -gt 1MB) { [pscustomobject]@{ Size = $len; Path = $p } }
        }
    } catch {
        # 路径含通配符等特殊字符时跳过，不影响主流程
    }
}
if ($big) {
    Write-Info "大于 1MB 的受控文件："
    $big | ForEach-Object { Write-Host ("         {0:N0} bytes  {1}" -f $_.Size, $_.Path) }
} else {
    Write-Ok "无大于 1MB 的受控文件"
}

# 1.5 确认将推送的提交
Write-Info "即将推送的提交："
git log --oneline origin/main..main 2>$null | ForEach-Object { Write-Host "         $_" }
if ($LASTEXITCODE -ne 0) {
    git log --oneline -3 | ForEach-Object { Write-Host "         $_" }
}

if ($DryRun) {
    Write-Host "`n-DryRun 指定，跳过实际推送。" -ForegroundColor Yellow
    Write-Host "安全复核全部通过。确认无误后去掉 -DryRun 再执行。" -ForegroundColor Yellow
    exit 0
}

# ---------- 2. 关联远程仓库 ----------
Write-Step "关联远程仓库"
$existing = git remote get-url origin 2>$null
if ($LASTEXITCODE -eq 0 -and $existing) {
    Write-Info "已存在 origin：$existing（将替换为新地址）"
    git remote remove origin
    if ($LASTEXITCODE -ne 0) { Write-Bad "移除旧 origin 失败"; exit 1 }
}
git remote add origin $RepoUrl
if ($LASTEXITCODE -ne 0) { Write-Bad "git remote add 失败"; exit 1 }
Write-Ok "origin -> $RepoUrl"

# ---------- 3. 推送 ----------
Write-Step "推送到远程"
Write-Host "  若弹出 Windows 凭据窗口：GitHub 请填 用户名 + Personal Access Token（非登录密码）。" -ForegroundColor Yellow
git push -u origin main
if ($LASTEXITCODE -ne 0) {
    Write-Bad "git push 失败。常见原因："
    Write-Host "    - 凭据错误或 Token 无 repo 权限"
    Write-Host "    - 远程仓库已初始化（创建时勾了 README/.gitignore）导致 non-fast-forward"
    Write-Host "    - 网络无法访问 github.com（可换 Gitee 或为 git 配置代理）"
    exit 1
}
Write-Ok "推送完成"

# ---------- 4. 推送后核对 ----------
Write-Step "推送后核对"
$localSha  = (git rev-parse main).Trim()
$remoteSha = (git rev-parse origin/main).Trim()
if ($localSha -eq $remoteSha) {
    Write-Ok "本地 main 与 origin/main 一致：$($localSha.Substring(0,10))"
} else {
    Write-Bad "本地 ($localSha) 与远程 ($remoteSha) 不一致"
    exit 1
}

$remoteCount = (git ls-files | Measure-Object).Count
Write-Ok "受控文件数：$remoteCount"

Write-Host "`n推送成功。" -ForegroundColor Green
Write-Host "仓库地址：$RepoUrl" -ForegroundColor White
Write-Host "`n下一步：到仓库页面的 Actions 标签确认 CI 流水线已触发并跑绿。" -ForegroundColor Cyan
Write-Host "（若显示 'Workflows aren't being run'，进 Settings -> Actions -> General 改为 Allow all actions）" -ForegroundColor Gray

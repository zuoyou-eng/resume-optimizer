@echo off
chcp 65001 >nul
setlocal

if "%~1"=="" (
    echo.
    echo 用法: push-remote.bat ^<仓库地址^> [-DryRun]
    echo.
    echo 示例:
    echo   push-remote.bat https://github.com/你的用户名/resume-optimizer.git
    echo   push-remote.bat https://gitee.com/你的用户名/resume-optimizer.git -DryRun
    echo.
    echo 说明: 先做推送前安全复核，通过后才执行 git push。
    echo       push 时 Windows 会弹凭据窗口，GitHub 需填 Personal Access Token（非登录密码）。
    echo.
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0push-remote.ps1" %*
exit /b %ERRORLEVEL%

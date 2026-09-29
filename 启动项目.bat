@echo off
REM ============================================================
REM  Resume Optimizer - one-click launcher (Windows)
REM
REM  This file is intentionally ASCII-only: a UTF-8 .bat is parsed
REM  with the local code page on Chinese Windows, and some Chinese
REM  byte sequences end in ASCII bytes such as ')' or '\', which
REM  silently breaks if(...) blocks. All logic and messages live in
REM  scripts\start.ps1, which handles UTF-8 correctly.
REM ============================================================
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start.ps1"
if errorlevel 1 pause

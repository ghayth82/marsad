@echo off
chcp 65001 >nul
REM اختصار سطح المكتب يشير إلى هذا الملف
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start.ps1" %*
pause

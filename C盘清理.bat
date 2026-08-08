@echo off
title C盘清理工具

:: ============================================
:: C盘清理工具 v2.4
:: 作者: KuMoo | 公众号: 弱者思维体系
:: 仓库: https://github.com/kumoonet/c-drive-cleaner
:: ============================================
echo.
echo   C盘清理工具 v2.4  ·  公众号: 弱者思维体系  ·  KuMoo
echo.

:: 1. PATH中的python
where python >nul 2>&1
if %errorlevel% equ 0 (
    python "%~dp0c_drive_cleaner.py"
    exit /b
)

:: 2. 用户目录下的Python
set "PY=%LOCALAPPDATA%\Programs\Python"
for /d %%d in ("%PY%\Python3*") do (
    if exist "%%d\python.exe" (
        "%%d\python.exe" "%~dp0c_drive_cleaner.py"
        exit /b
    )
)

:: 3. uv（自动下载托管Python执行）
where uv >nul 2>&1
if %errorlevel% equ 0 (
    uv run "%~dp0c_drive_cleaner.py"
    exit /b
)

:: 4. 都没有
echo.
echo   [错误] 未找到Python或uv。
echo.
echo   方案A: 安装Python https://www.python.org/downloads/
echo   方案B: 安装uv    https://docs.astral.sh/uv/
echo          然后重新双击本文件（uv会自动下载Python）
echo.
pause

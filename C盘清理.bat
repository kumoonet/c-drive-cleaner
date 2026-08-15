@echo off
title C盘清理工具 v3.0

:: ============================================
:: C盘清理工具 v3.0
:: 作者: KuMoo | 公众号: 弱者思维体系
:: 仓库: https://github.com/kumoonet/c-drive-cleaner
:: 兼容: Windows 7 SP1+ / 8 / 8.1 / 10 / 11，32位与64位
:: 特性: 无Python环境自动部署便携版(embeddable)到 runtime\，绿色零安装
:: ============================================

:: 低配自动降并发（CPU不足5核 → 4线程，工具读取 CDRIVE_CLEANER_THREADS）
set "CDRIVE_CLEANER_THREADS=8"
if defined NUMBER_OF_PROCESSORS if %NUMBER_OF_PROCESSORS% LSS 5 set "CDRIVE_CLEANER_THREADS=4"

set "SCRIPT=%~dp0c_drive_cleaner.py"

:: 1. PATH中的python
where python >nul 2>&1
if %errorlevel% equ 0 (
    python "%SCRIPT%"
    exit /b
)

:: 2. 用户目录下的Python
set "PY=%LOCALAPPDATA%\Programs\Python"
for /d %%d in ("%PY%\Python3*") do (
    if exist "%%d\python.exe" (
        "%%d\python.exe" "%SCRIPT%"
        exit /b
    )
)

:: 3. uv自动下载并运行Python执行：
where uv >nul 2>&1
if %errorlevel% equ 0 (
    uv run "%SCRIPT%"
    exit /b
)

:: 4. 便携运行时（工具目录 runtime\python，目录拷走即用）
set "RUNTIME=%~dp0runtime\python"
if exist "%RUNTIME%\python.exe" (
    "%RUNTIME%\python.exe" "%SCRIPT%"
    exit /b
)

:: 5. 都没有 → 自动下载便携 Python（官方 embeddable 包）
echo.
echo   [信息] 未检测到 Python/uv，开始自动部署便携 Python...

:: 架构：AMD64 → amd64；其余(x86/ARM模拟) → win32
set "ARCH=win32"
if /i "%PROCESSOR_ARCHITECTURE%"=="AMD64" set "ARCH=amd64"

:: 版本：Win7(6.1)及以下 → 3.9.13（最后支持Win7的Python）；其余 → 3.12.10
set "VER=3.12.10"
ver | findstr /i "6\.1\." >nul 2>&1 && set "VER=3.9.13"
echo   [信息] 目标: Python %VER% (%ARCH%)

set "ZIP=%~dp0runtime\python-embed.zip"
if not exist "%~dp0runtime" mkdir "%~dp0runtime" >nul 2>&1

:: 镜像顺序：华为云 → npmmirror → python.org 官方（大陆直连首选华为云）
set "URL1=https://mirrors.huaweicloud.com/python/%VER%/python-%VER%-embed-%ARCH%.zip"
set "URL2=https://registry.npmmirror.com/-/binary/python/%VER%/python-%VER%-embed-%ARCH%.zip"
set "URL3=https://www.python.org/ftp/python/%VER%/python-%VER%-embed-%ARCH%.zip"

:: ---- 下载降级链：curl → PowerShell WebClient(TLS1.2) → http明文兜底 ----
where curl >nul 2>&1
if %errorlevel% equ 0 (
    curl -L --fail --silent --show-error --progress-bar -o "%ZIP%" "%URL1%"
    if not errorlevel 1 goto :down_ok
    curl -L --fail --silent --show-error --progress-bar -o "%ZIP%" "%URL2%"
    if not errorlevel 1 goto :down_ok
    curl -L --fail --silent --show-error --progress-bar -o "%ZIP%" "%URL3%"
    if not errorlevel 1 goto :down_ok
) else (
    echo   [信息] 系统无 curl，改用 PowerShell 下载...
)

:: PowerShell WebClient：.NET4.5+ 强制 TLS1.2；.NET3.5 无该枚举则抛错走下一级
powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12;(New-Object Net.WebClient).DownloadFile('%URL1%','%ZIP%')"
if not errorlevel 1 goto :down_ok
powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12;(New-Object Net.WebClient).DownloadFile('%URL2%','%ZIP%')"
if not errorlevel 1 goto :down_ok
powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12;(New-Object Net.WebClient).DownloadFile('%URL3%','%ZIP%')"
if not errorlevel 1 goto :down_ok

:: http明文兜底（仅华为云，Win7 无 TLS1.2 补丁时）
powershell -NoProfile -Command "(New-Object Net.WebClient).DownloadFile('http://mirrors.huaweicloud.com/python/%VER%/python-%VER%-embed-%ARCH%.zip','%ZIP%')"
if not errorlevel 1 goto :down_ok

echo   [错误] 所有下载方式均失败，请检查网络后重试。
goto :no_python

:down_ok
:: 校验下载完整性（zip 应大于5MB）
for %%A in ("%ZIP%") do if %%~zA LSS 5000000 (
    echo   [错误] 下载文件异常（过小），可能被网络拦截。
    goto :no_python
)

:: ---- 解压降级链：tar.exe → VBS Shell.Application（Win7 无 tar，WSH 内置）----
where tar >nul 2>&1
if %errorlevel% equ 0 (
    tar -xf "%ZIP%" -C "%~dp0runtime"
    if not errorlevel 1 goto :unzip_ok
)

set "VBS=%~dp0runtime\unzip.vbs"
> "%VBS%" echo Set fso = CreateObject("Scripting.FileSystemObject")
>> "%VBS%" echo Set sh = CreateObject("Shell.Application")
>> "%VBS%" echo src = WScript.Arguments(0)
>> "%VBS%" echo dst = WScript.Arguments(1)
>> "%VBS%" echo If Not fso.FolderExists(dst) Then fso.CreateFolder(dst)
>> "%VBS%" echo sh.NameSpace(dst).CopyHere sh.NameSpace(src).Items, 16
>> "%VBS%" echo pexe = fso.BuildPath(dst, "python.exe")
>> "%VBS%" echo For i = 1 To 120
>> "%VBS%" echo     If fso.FileExists(pexe) Then WScript.Quit 0
>> "%VBS%" echo     WScript.Sleep 500
>> "%VBS%" echo Next
>> "%VBS%" echo WScript.Quit 1
cscript //nologo "%VBS%" "%ZIP%" "%~dp0runtime"
del "%VBS%" >nul 2>&1
if not errorlevel 1 goto :unzip_ok
echo   [错误] 解压失败。
goto :no_python

:unzip_ok
del "%ZIP%" >nul 2>&1
if exist "%RUNTIME%\python.exe" (
    echo   [完成] 便携 Python 已部署到 runtime\（下次直接使用，无需再下载）。
    "%RUNTIME%\python.exe" "%SCRIPT%"
    exit /b
)
echo   [错误] 部署校验失败。
goto :no_python

:no_python
echo.
echo   [错误] 未找到 Python 或 uv，自动部署失败。
echo.
echo   方案A: 安装Python https://www.python.org/downloads/
echo   方案B: 安装uv    https://docs.astral.sh/uv/
echo   或修复网络后重新运行本文件。
echo.
pause

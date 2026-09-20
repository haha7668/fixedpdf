@echo off
setlocal EnableExtensions EnableDelayedExpansion

rem ============================================================================
rem  FixedPDF - Windows 启动脚本
rem
rem  双击即可运行。启动前检查运行环境（Python、虚拟环境、依赖组件），
rem  缺失的部分会给出下载或自动安装选项。
rem
rem  用法：
rem     start.bat            检查环境并启动服务
rem     start.bat --check    只检查环境，不启动（便于排查问题）
rem
rem  说明：本文件用 GBK 编码保存，与 Windows 中文环境的命令行一致；
rem        改成 UTF-8 会让中文注释被 cmd 当成命令执行。
rem ============================================================================

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

set "VENV_DIR=%SCRIPT_DIR%.venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"
set "REQUIREMENTS=%SCRIPT_DIR%requirements.txt"
set "APP_URL=http://127.0.0.1:8123"
set "PY_DOWNLOAD_URL=https://www.python.org/downloads/windows/"
set "PY_MIN_MAJOR=3"
set "PY_MIN_MINOR=10"
set "CHECK_ONLY=0"
if /i "%~1"=="--check" set "CHECK_ONLY=1"

title FixedPDF - 启动中

echo.
echo ============================================================
echo   FixedPDF - AI 智能文档阅读器
echo ============================================================

rem ---------------------------------------------------------------------------
rem 1) 定位 Python 解释器
rem    结果经临时文件中转：cmd 的 for /f 无法直接执行「引号包裹的路径 + 参数」，
rem    而路径可能含空格，因此不采用 for /f 解析。
rem ---------------------------------------------------------------------------
echo.
echo [1/4] Python 运行时

set "PY_EXE="
set "PY_SOURCE="
set "PROBE=%TEMP%\reader3_probe_%RANDOM%.txt"

if exist "%VENV_PY%" (
    set "PY_EXE="
    "%VENV_PY%" -c "import sys;print(sys.executable)" > "%PROBE%" 2>nul
    set /p PY_EXE=<"%PROBE%"
    if defined PY_EXE set "PY_SOURCE=项目虚拟环境"
)

if not defined PY_EXE (
    rem 系统 Python：py 启动器更可靠，能按需挑选版本。
    rem 每次读取前清空：set /p 读空文件不会清掉旧值。
    set "PY_EXE="
    py -3 -c "import sys;print(sys.executable)" > "%PROBE%" 2>nul
    set /p PY_EXE=<"%PROBE%"
    if defined PY_EXE set "PY_SOURCE=系统安装 (py)"
)
if not defined PY_EXE (
    set "PY_EXE="
    python -c "import sys;print(sys.executable)" > "%PROBE%" 2>nul
    set /p PY_EXE=<"%PROBE%"
    if defined PY_EXE set "PY_SOURCE=系统安装 (python)"
)

if not defined PY_EXE (
    del "%PROBE%" >nul 2>&1
    goto :no_python
)

rem 版本校验：需要 3.10+（同样先清空，避免读到旧值）
set "PY_VER="
"%PY_EXE%" -c "import sys;print('%%d.%%d.%%d' %% sys.version_info[:3])" > "%PROBE%" 2>nul
set /p PY_VER=<"%PROBE%"
del "%PROBE%" >nul 2>&1

if not defined PY_VER goto :no_python
for /f "tokens=1,2 delims=." %%a in ("!PY_VER!") do (
    set "PY_MAJOR=%%a"
    set "PY_MINOR=%%b"
)
if !PY_MAJOR! LSS %PY_MIN_MAJOR% goto :old_python
if !PY_MAJOR! EQU %PY_MIN_MAJOR% if !PY_MINOR! LSS %PY_MIN_MINOR% goto :old_python

echo       [OK] Python !PY_VER!  ^(!PY_SOURCE!^)
echo            !PY_EXE!

rem ---------------------------------------------------------------------------
rem 2) 检查虚拟环境
rem ---------------------------------------------------------------------------
echo.
echo [2/4] 虚拟环境

if exist "%VENV_PY%" (
    echo       [OK] 已就绪
) else (
    echo       [缺失] 尚未创建
    call :offer_create_venv
    if not exist "%VENV_PY%" (
        echo.
        echo 未创建虚拟环境，已取消启动。
        goto :end_fail
    )
)

rem ---------------------------------------------------------------------------
rem 3) 检查依赖组件
rem ---------------------------------------------------------------------------
echo.
echo [3/4] 依赖组件

call :check_deps
if defined DEPS_MISSING (
    echo       [缺失]!DEPS_MISSING!
    call :offer_install_deps
    if defined DEPS_MISSING (
        echo.
        echo 依赖不完整，已取消启动。
        goto :end_fail
    )
    echo       [OK] 依赖已补齐
) else (
    echo       [OK] 依赖完整
)

if "%CHECK_ONLY%"=="1" (
    echo.
    echo 环境检查通过。去掉 --check 参数即可启动服务。
    goto :end_ok
)

rem ---------------------------------------------------------------------------
rem 4) 启动服务
rem ---------------------------------------------------------------------------
echo.
echo [4/4] 启动服务

call :service_running
if not errorlevel 1 (
    echo       服务已在运行，直接打开浏览器
    start "" "%APP_URL%"
    goto :end_ok
)

rem Windows 控制台默认 GBK，不设 UTF-8 会在打印中文或 emoji 时崩溃
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

rem 稍等片刻再打开浏览器，让 uvicorn 完成启动
start "" /b cmd /c "timeout /t 3 /nobreak >nul & start "" "%APP_URL%""

echo       服务地址：%APP_URL%
echo.
echo ------------------------------------------------------------
echo   关闭此窗口即可停止服务（或按 Ctrl+C）
echo ------------------------------------------------------------
echo.

"%VENV_PY%" "%SCRIPT_DIR%server.py"
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" goto :server_failed
goto :end_ok


rem ============================================================================
rem  子过程
rem ============================================================================

:check_deps
rem 按 import 名逐个校验，比读 requirements.txt 更贴近真实可用性；
rem 批处理不便遍历映射，平铺以便定位到具体缺失项。
set "DEPS_MISSING="
call :dep fastapi       fastapi
call :dep uvicorn       uvicorn
call :dep pymupdf       pymupdf
call :dep bs4           beautifulsoup4
call :dep jinja2        jinja2
call :dep edge_tts      edge-tts
call :dep httpx         httpx
call :dep dotenv        python-dotenv
call :dep multipart     python-multipart
call :dep PIL           pillow
call :dep google.genai  google-genai
call :dep dashscope     dashscope
exit /b 0

:dep
"%VENV_PY%" -c "import %~1" >nul 2>&1
if errorlevel 1 set "DEPS_MISSING=!DEPS_MISSING! %~2"
exit /b 0

:service_running
rem 只当 /api/health 应答出本项目的 app 标识才认为服务已就绪；
rem 端口被别的程序占用时该端点会 404，从而避免误判成「服务已在运行」。
"%VENV_PY%" -c "import urllib.request,sys;r=urllib.request.urlopen('http://127.0.0.1:8123/api/health',timeout=1);sys.exit(0 if b'fixedpdf' in r.read().lower() else 1)" >nul 2>&1
exit /b %ERRORLEVEL%

:offer_create_venv
echo.
echo ------------------------------------------------------------
echo   需要创建虚拟环境 ^(.venv^)
echo ------------------------------------------------------------
echo   依赖会装在项目目录内，不影响系统 Python。
echo.
echo     [1] 现在创建并安装依赖 ^(需联网，约 1-3 分钟^)
echo     [0] 退出
echo.
set "CH="
set /p "CH=  请选择 [1/0]: "
if not "!CH!"=="1" exit /b 1

echo.
echo   正在创建虚拟环境 ...
"%PY_EXE%" -m venv "%VENV_DIR%"
if not exist "%VENV_PY%" (
    echo   [失败] 创建虚拟环境失败，请确认 Python 安装完整。
    exit /b 1
)
echo   已创建。正在安装依赖 ...
"%VENV_PY%" -m pip install --upgrade pip --quiet --disable-pip-version-check
"%VENV_PY%" -m pip install -r "%REQUIREMENTS%" --disable-pip-version-check
if errorlevel 1 (
    echo   [失败] 依赖安装失败，请检查网络或代理设置。
    exit /b 1
)
echo   依赖安装完成。
exit /b 0

:offer_install_deps
echo.
echo ------------------------------------------------------------
echo   安装缺失的依赖
echo ------------------------------------------------------------
echo     [1] 现在安装 ^(pip install -r requirements.txt^)
echo     [0] 退出
echo.
set "CH="
set /p "CH=  请选择 [1/0]: "
if "!CH!"=="1" (
    echo.
    echo   正在安装 ...
    "%VENV_PY%" -m pip install -r "%REQUIREMENTS%" --disable-pip-version-check
    if errorlevel 1 (
        echo   [失败] 安装失败，请检查网络或代理设置。
        exit /b 1
    )
    call :check_deps
    exit /b 0
)
exit /b 1

:no_python
echo.
echo       [缺失] 未检测到 Python
echo.
echo ------------------------------------------------------------
echo   本程序需要 Python %PY_MIN_MAJOR%.%PY_MIN_MINOR% 或更高版本
echo ------------------------------------------------------------
echo     [1] 打开 Python 官方下载页
echo         安装时请勾选 "Add python.exe to PATH"
echo     [2] 用 winget 自动安装 Python 3.12
echo     [0] 退出
echo.
set "CH="
set /p "CH=  请选择 [1/2/0]: "
if "!CH!"=="1" (
    start "" "%PY_DOWNLOAD_URL%"
    echo.
    echo   已打开下载页。安装完成后请重新运行本脚本。
    goto :end_fail
)
if "!CH!"=="2" (
    where winget >nul 2>&1
    if errorlevel 1 (
        echo.
        echo   未找到 winget，请改用选项 1 手动安装。
        goto :end_fail
    )
    echo.
    echo   正在通过 winget 安装 Python 3.12 ...
    winget install --id Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements
    echo.
    echo   安装已结束。请关闭本窗口后重新运行（PATH 需要重新加载）。
    goto :end_fail
)
goto :end_fail

:old_python
echo.
echo       [版本过低] 当前 !PY_VER!，需要 %PY_MIN_MAJOR%.%PY_MIN_MINOR%+
echo.
echo     [1] 打开 Python 官方下载页
echo     [0] 退出
echo.
set "CH="
set /p "CH=  请选择 [1/0]: "
if "!CH!"=="1" (
    start "" "%PY_DOWNLOAD_URL%"
    echo.
    echo   安装完成后请重新运行本脚本。
)
goto :end_fail

:server_failed
echo.
echo ============================================================
echo   服务异常退出 ^(代码 %EXIT_CODE%^)
echo ============================================================
echo.
echo   常见原因：
echo     - 端口 8123 被其他程序占用
echo     - 依赖安装不完整
echo     - 配置文件 ai_config.json 损坏
echo.
echo   可运行  start.bat --check  检查环境。
echo.
pause
goto :end_fail

:end_ok
endlocal
exit /b 0

:end_fail
echo.
pause
endlocal
exit /b 1

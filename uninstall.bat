@echo off
setlocal EnableExtensions EnableDelayedExpansion

rem ============================================================================
rem  FixedPDF - Windows 卸载脚本
rem
rem  删除本程序安装/运行产生的所有组件，恢复安装前的环境。
rem  双击运行，按提示选择卸载范围。
rem
rem  用法：
rem    uninstall.bat           交互式卸载
rem    uninstall.bat --check   只预览将删除的内容，不实际删除
rem
rem  说明：本文件用 GBK 编码保存，与 Windows 中文环境的命令行一致。
rem ============================================================================

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

set "DRY=0"
if /i "%~1"=="--check" set "DRY=1"

title FixedPDF - 卸载

echo.
echo ============================================================
echo   FixedPDF - 卸载程序
if "%DRY%"=="1" echo   （预览模式：只列出，不删除）
echo ============================================================
echo.

rem ---------------------------------------------------------------------------
rem 1) 检测服务是否在运行
rem ---------------------------------------------------------------------------
echo [检查] 服务状态 ...
netstat -ano 2>nul | findstr ":8123" | findstr "LISTENING" >nul 2>&1
if not errorlevel 1 (
    echo        [警告] 检测到服务正在运行（端口 8123）。
    echo.
    echo        请先关闭服务窗口（或在该窗口按 Ctrl+C 停止服务），
    echo        再重新运行本脚本；否则虚拟环境可能因文件占用而删除失败。
    echo.
    if "%DRY%"=="0" (
        echo   是否仍然继续？
        echo     [1] 继续（不推荐）
        echo     [0] 退出
        echo.
        set /p "CH=  请选择 [1/0]: "
        if not "!CH!"=="1" goto :end_cancel
    )
)

echo.
echo ------------------------------------------------------------
echo   卸载范围：
echo.
echo   [程序组件]（两种模式都会删除）
echo     - 虚拟环境与依赖      .venv
echo     - uv 包缓存            .uv-cache
echo     - 字节码缓存           __pycache__ 与 *.pyc
echo     - 检查/测试缓存        .pytest_cache .ruff_cache .mypy_cache
echo     - 覆盖率产物           .coverage htmlcov
echo     - 下载的词典           dict\*.db
echo     - 日志文件             *.log
echo     - 调试与打包产物       tmp output build dist
echo.
echo   [用户数据]（仅「完全卸载」删除）
echo     - 导入的书籍与翻译缓存  books
echo     - AI 配置与密钥         ai_config.json .env
echo     - 语音缓存              .tts_cache
echo ------------------------------------------------------------

if "%DRY%"=="1" (
    echo.
    echo   [预览] 以下为将删除的内容（未执行任何删除）：
    echo.
    call :show_components
    call :show_userdata
    echo.
    echo   预览结束。去掉 --check 参数运行即可真正卸载。
    goto :end_ok
)

echo.
echo   请选择卸载范围：
echo     [1] 完全卸载 —— 程序组件 + 用户数据（恢复安装前状态）
echo     [2] 标准卸载 —— 仅程序组件（保留书籍与 AI 配置）
echo     [0] 取消
echo.
set "MODE="
set /p "MODE=  请选择 [1/2/0]: "
if "!MODE!"=="0" goto :end_cancel
if not "!MODE!"=="1" if not "!MODE!"=="2" goto :end_cancel

if "!MODE!"=="1" (
    echo.
    echo   [确认] 完全卸载将删除 books 下的书籍、翻译缓存与 AI 配置，
    echo          这些数据删除后无法恢复。
    echo.
    set /p "CONFIRM=  输入 yes 确认删除全部数据："
    if /i not "!CONFIRM!"=="yes" goto :end_cancel
)

echo.
echo ------------------------------------------------------------
echo   正在卸载 ...
echo ------------------------------------------------------------
echo.
echo   [1/2] 删除程序组件 ...
call :show_components
call :remove_components
echo        [完成]
echo.
if "!MODE!"=="1" (
    echo   [2/2] 删除用户数据 ...
    call :show_userdata
    call :remove_userdata
    echo        [完成]
) else (
    echo   [2/2] 保留用户数据（书籍与 AI 配置）
)
echo.

echo ============================================================
echo   卸载完成。
echo ============================================================
echo.
echo   说明：
echo     - 项目源文件（含 start.bat 与本脚本）仍保留在：
echo       %SCRIPT_DIR%
echo       如需彻底移除，请手动删除该文件夹。
echo     - 若此前通过 winget 安装了 Python 3.12，可单独卸载：
echo       winget uninstall Python.Python.3.12
echo.
goto :end_ok

rem ---------------------------------------------------------------------------
rem  子过程：仅预览
rem ---------------------------------------------------------------------------
:show_components
echo     - 目录 .venv
echo     - 目录 .uv-cache
echo     - 目录 __pycache__ 及全部 *.pyc
echo     - 目录 .pytest_cache .ruff_cache .mypy_cache
echo     - 文件 .coverage
echo     - 目录 htmlcov
echo     - 文件 dict\*.db
echo     - 文件 *.log
echo     - 目录 tmp output build dist
exit /b 0

:show_userdata
echo     - 目录 books
echo     - 文件 ai_config.json
echo     - 文件 .env
echo     - 目录 .tts_cache
exit /b 0

rem ---------------------------------------------------------------------------
rem  子过程：实际删除
rem ---------------------------------------------------------------------------
:remove_components
call :rmdir .venv
call :rmdir .uv-cache
call :rmdir __pycache__
call :rmdir .pytest_cache
call :rmdir .ruff_cache
call :rmdir .mypy_cache
call :rmdir htmlcov
call :rmdir tmp
call :rmdir output
call :rmdir build
call :rmdir dist
call :delfile .coverage
del /f /s /q "*.pyc" 2>nul
del /f /q "*.log" 2>nul
if exist "dict\*.db" (
    del /f /q "dict\*.db" 2>nul
    del /f /q "dict\*.db-shm" 2>nul
    del /f /q "dict\*.db-wal" 2>nul
)
exit /b 0

:remove_userdata
call :rmdir books
call :rmdir .tts_cache
call :delfile ai_config.json
call :delfile .env
exit /b 0

:rmdir
rem %1 = 目录名
if exist "%~1" (
    rd /s /q "%~1" 2>nul
    if exist "%~1" (
        echo        [失败] %~1 可能被占用，删除不完整
    ) else (
        echo        [OK]   已删除目录 %~1
    )
) else (
    echo        [跳过] 目录 %~1 不存在
)
exit /b 0

:delfile
rem %1 = 文件名
if exist "%~1" (
    del /f /q "%~1" 2>nul
    if exist "%~1" (
        echo        [失败] %~1 可能被占用，删除不完整
    ) else (
        echo        [OK]   已删除文件 %~1
    )
) else (
    echo        [跳过] 文件 %~1 不存在
)
exit /b 0

rem ---------------------------------------------------------------------------
rem  结束
rem ---------------------------------------------------------------------------
:end_ok
echo.
pause
endlocal
exit /b 0

:end_cancel
echo.
echo   已取消卸载。
echo.
pause
endlocal
exit /b 1

@echo off
REM =============================================================
REM  Atour 亚朵比价 · 统一启动脚本 (Windows)
REM  同时启动前端（Astro 起始页 4321）与后端（Streamlit 结果页 8501）
REM  用法：双击 start.bat
REM =============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

set "FRONTEND=%~dp0frontend"
set "BACKEND=%~dp0backend"
set "ASTRO_PORT=4321"
set "STREAMLIT_PORT=8501"

echo ==================================================
echo   Atour 亚朵比价 - 一键启动
echo   前端(起始页):  http://localhost:%ASTRO_PORT%
echo   后端(结果页):  http://localhost:%STREAMLIT_PORT%
echo ==================================================

REM ---- 1) 前端 Astro ----
if not exist "%FRONTEND%\node_modules" (
  echo [frontend] 安装依赖...
  pushd "%FRONTEND%"
  call npm install
  popd
)

echo [frontend] 构建 Astro...
pushd "%FRONTEND%"
call npm run build
popd

echo [frontend] 启动预览 (端口 %ASTRO_PORT%)...
start "Atour-Frontend" cmd /c "cd /d "%FRONTEND%" && npm run preview -- --port %ASTRO_PORT% --host"

REM ---- 2) 后端 Streamlit ----
if not exist "%BACKEND%\.venv" (
  echo [backend] 创建 Python 虚拟环境并安装依赖...
  pushd "%BACKEND%"
  python -m venv .venv
  call .venv\Scripts\activate.bat
  pip install -r requirements.txt
  popd
)

echo [backend] 启动 Streamlit (端口 %STREAMLIT_PORT%)...
start "Atour-Backend" cmd /c "cd /d "%BACKEND%" && .venv\Scripts\streamlit.exe run app.py --server.port %STREAMLIT_PORT% --server.headless true"

echo.
echo 两个服务已启动：
echo   起始页: http://localhost:%ASTRO_PORT%
echo   结果页: http://localhost:%STREAMLIT_PORT%
echo 关闭对应窗口即可停止各服务。
endlocal

@echo off
REM =============================================================
REM  Atour Hotel Price Comparison - Unified launcher (Windows)
REM  Starts frontend (Astro landing page :4321) and backend (Streamlit results :8501)
REM  Usage: double-click start.bat
REM =============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

set "FRONTEND=%~dp0frontend"
set "BACKEND=%~dp0backend"
set "ASTRO_PORT=4321"
set "STREAMLIT_PORT=8501"

echo ==================================================
echo   Atour - One-click launcher
echo   Frontend (landing): http://localhost:%ASTRO_PORT%
echo   Backend (results):  http://localhost:%STREAMLIT_PORT%
echo ==================================================

REM ---- 1) Frontend Astro ----
if not exist "%FRONTEND%\node_modules" (
  echo [frontend] Installing dependencies...
  pushd "%FRONTEND%"
  call npm install
  popd
)

echo [frontend] Building Astro - result page: http://localhost:%STREAMLIT_PORT%
pushd "%FRONTEND%"
set "RESULT_APP_URL=http://localhost:%STREAMLIT_PORT%"
call npm run build
popd

echo [frontend] Starting preview (port %ASTRO_PORT%)...
start "Atour-Frontend" /D "%FRONTEND%" cmd /c "npm run preview -- --port %ASTRO_PORT% --host"

REM ---- 2) Backend Streamlit ----
if not exist "%BACKEND%\.venv" (
  echo [backend] Creating virtualenv and installing dependencies...
  pushd "%BACKEND%"
  python -m venv .venv
  call .venv\Scripts\activate.bat
  pip install -r requirements.txt
  popd
)

echo [backend] Starting Streamlit (port %STREAMLIT_PORT%)...
start "Atour-Backend" /D "%BACKEND%" cmd /c ".venv\Scripts\python.exe -m streamlit run app.py --server.port %STREAMLIT_PORT% --server.headless true"

echo.
echo Both services started:
echo   Landing page: http://localhost:%ASTRO_PORT%
echo   Results page:  http://localhost:%STREAMLIT_PORT%
echo Close the corresponding window to stop each service.
endlocal

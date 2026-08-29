@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "APP=%~dp0main.py"
set "VENV_PYW=%~dp0.venv\Scripts\pythonw.exe"
set "VENV_PY=%~dp0.venv\Scripts\python.exe"

if exist "%VENV_PYW%" (
  start "" "%VENV_PYW%" "%APP%"
  exit /b 0
)

if exist "%VENV_PY%" (
  start "" "%VENV_PY%" "%APP%"
  exit /b 0
)

where pythonw >nul 2>&1
if %ERRORLEVEL%==0 (
  start "" pythonw "%APP%"
  exit /b 0
)

where python >nul 2>&1
if %ERRORLEVEL%==0 (
  python "%APP%"
  exit /b %ERRORLEVEL%
)

echo Python was not found.
echo Create the virtualenv first:
echo   python -m venv .venv
echo   .venv\Scripts\python.exe -m pip install -r requirements.txt
pause
exit /b 1

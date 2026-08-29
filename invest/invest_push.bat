@echo off
setlocal enabledelayedexpansion

rem ============================================================
rem  V+ — sync to nox1020/invest + push vinor repo
rem  Remote: https://github.com/nox1020/vinor
rem  Target : %~dp0nox1020\invest\
rem  Usage:
rem    invest_push.bat
rem    invest_push.bat your commit message
rem ============================================================

set "SRC_DIR=%~dp0"
set "VINOR_ROOT=%~dp0nox1020"
set "DEST_DIR=%VINOR_ROOT%\invest"
set "REMOTE=https://github.com/nox1020/vinor.git"
set "CUSTOM_MSG=%*"

if not exist "%VINOR_ROOT%\.git" (
  echo [V+] clone vinor not found — cloning...
  git clone "%REMOTE%" "%VINOR_ROOT%"
  if errorlevel 1 (
    echo [V+] clone failed.
    pause
    exit /b 1
  )
)

if not exist "%DEST_DIR%" mkdir "%DEST_DIR%"

echo.
echo ============================================================
echo   V+ — Sync ^& Push
echo   Source : %SRC_DIR%
echo   Target : %DEST_DIR%
echo   Remote : nox1020/vinor
echo ============================================================
echo.

echo [V+] syncing files to nox1020\invest ...
robocopy "%SRC_DIR%" "%DEST_DIR%" /E /MIR /XD nox1020 .git .venv __pycache__ .pytest_cache /XF *.db *.sqlite* *.log .env .env.* *.lnk *.xlsx *.pdf Thumbs.db /NFL /NDL /NJH /NJS /nc /ns /np
set "RC=!ERRORLEVEL!"
if !RC! GEQ 8 (
  echo [V+] sync failed (robocopy exit !RC!).
  pause
  exit /b 1
)

cd /d "%VINOR_ROOT%" || (
  echo [V+] cannot cd to vinor repo.
  pause
  exit /b 1
)

if exist ".git\rebase-merge" (
  echo [V+] abort unfinished rebase...
  git rebase --abort
)

set "BRANCH=main"
for /f "delims=" %%b in ('git rev-parse --abbrev-ref HEAD 2^>nul') do set "BRANCH=%%b"
echo [V+] branch: %BRANCH%

git remote get-url origin >nul 2>&1
if errorlevel 1 (
  git remote add origin "%REMOTE%"
) else (
  git remote set-url origin "%REMOTE%"
)

echo [V+] pull --rebase --autostash...
git pull --rebase --autostash origin %BRANCH%
if errorlevel 1 (
  echo [V+] pull failed.
  pause
  exit /b 1
)

git add invest/
git diff --cached --quiet && (
  echo [V+] no changes in invest/ to push.
  pause
  exit /b 0
)

if defined CUSTOM_MSG (
  set "msg=!CUSTOM_MSG!"
) else (
  set "msg=Update V+ invest !date! !time!"
)

echo [V+] changes in invest/:
echo --------------------------
git status --short invest/
echo --------------------------

git commit -m "!msg!"
if errorlevel 1 (
  echo [V+] commit failed.
  pause
  exit /b 1
)

echo [V+] push...
git push origin %BRANCH%
if errorlevel 1 (
  echo [V+] push failed. Check GitHub auth.
  pause
  exit /b 1
)

echo.
echo ============================================================
echo   V+ — push OK  ^(nox1020/invest^)
echo   Branch: %BRANCH%
echo   Commit: !msg!
echo ============================================================
echo.
pause
exit /b 0

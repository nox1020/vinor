@echo off
setlocal enabledelayedexpansion

rem ============================================================
rem  Vinor — ادغام push مخزن Flask/PWA + مخزن Android APK
rem  استفاده:
rem    vinor_push.bat                  هر دو مخزن
rem    vinor_push.bat --vinor-only     فقط vinor
rem    vinor_push.bat --apk-only       فقط apk
rem    vinor_push.bat پیام کامیت        پیام سفارشی برای vinor
rem ============================================================

set "MODE=both"
set "VINOR_MSG="

if /i "%~1"=="--apk-only" (
  set "MODE=apk"
  shift
)
if /i "%~1"=="--vinor-only" (
  set "MODE=vinor"
  shift
)
if not "%~1"=="" set "VINOR_MSG=%*"

set "VINOR_DIR=%~dp0"
set "APK_DIR=%~dp0..\apk"

set "VINOR_STATUS=SKIPPED"
set "VINOR_BRANCH=-"
set "VINOR_VERSION=-"
set "VINOR_MSG_OUT=-"
set "VINOR_EXIT=0"

set "APK_STATUS=SKIPPED"
set "APK_BRANCH=-"
set "APK_VERSION=-"
set "APK_MSG_OUT=-"
set "APK_EXIT=0"

echo.
echo ============================================================
echo   Vinor — Auto Commit ^& Push  (mode: %MODE%)
echo ============================================================
echo.

if /i "%MODE%"=="both" (
  call :push_vinor
  echo.
  call :push_apk
) else if /i "%MODE%"=="vinor" (
  call :push_vinor
) else if /i "%MODE%"=="apk" (
  call :push_apk
)

call :print_report_vinor
echo.
call :print_report_apk
echo.

if %VINOR_EXIT% neq 0 (
  pause
  exit /b %VINOR_EXIT%
)
if %APK_EXIT% neq 0 (
  pause
  exit /b %APK_EXIT%
)
pause
exit /b 0

rem ======================== VINOR (Flask/PWA) ========================
:push_vinor
set "VINOR_STATUS=FAILED"
cd /d "%VINOR_DIR%" || (
  echo [VINOR] مسیر پیدا نشد: %VINOR_DIR%
  set "VINOR_EXIT=1"
  exit /b 1
)

git rev-parse --is-inside-work-tree >nul 2>&1 || (
  echo [VINOR] این مسیر یک مخزن Git نیست.
  set "VINOR_EXIT=1"
  exit /b 1
)

if exist ".git/rebase-merge" (
  echo [VINOR] Rebase نیمه‌تمام — abort...
  git rebase --abort
)

set "BRANCH=main"
for /f "delims=" %%b in ('git rev-parse --abbrev-ref HEAD 2^>nul') do set "BRANCH=%%b"
set "VINOR_BRANCH=%BRANCH%"
echo [VINOR] شاخه: %BRANCH%

set "EXCLUDE=app/data instance uploads logs app/static/uploads app/data/uploads *.db *.sqlite* *.log .env .env.* *.pem *.key *.crt"
git restore --staged %EXCLUDE% >nul 2>&1

echo [VINOR] pull --rebase --autostash...
git pull --rebase --autostash https://github.com/asman-trader/garmabsard-flask.git %BRANCH%
if errorlevel 1 (
  echo [VINOR] pull ناموفق بود.
  set "VINOR_EXIT=1"
  exit /b 1
)

git add -A
git reset %EXCLUDE% >nul 2>&1

git diff --cached --quiet && (
  echo [VINOR] هیچ تغییری برای پوش نیست.
  set "VINOR_STATUS=NO_CHANGES"
  set "VINOR_EXIT=0"
  if exist version.txt set /p VINOR_VERSION=<version.txt
  exit /b 0
)

set "version=0"
if exist version.txt set /p version=<version.txt
for /f "delims=0123456789" %%x in ("!version!") do set "version=0"
set /a version+=1
>version.txt echo !version!
set "VINOR_VERSION=!version!"
git add version.txt

if defined VINOR_MSG (
  set "msg=!VINOR_MSG!"
) else (
  set "msg=Auto commit v!version!"
)
set "VINOR_MSG_OUT=!msg!"

echo [VINOR] تغییرات:
echo --------------------------
git status --short
echo --------------------------

git commit -m "!msg!"
if errorlevel 1 (
  echo [VINOR] commit ناموفق بود.
  set "VINOR_EXIT=1"
  exit /b 1
)

git push https://github.com/asman-trader/garmabsard-flask.git %BRANCH% --force
if errorlevel 1 (
  echo [VINOR] push ناموفق بود.
  set "VINOR_EXIT=1"
  exit /b 1
)

set "VINOR_STATUS=OK"
set "VINOR_EXIT=0"
exit /b 0

rem ======================== APK (Android) ========================
:push_apk
set "APK_STATUS=FAILED"
cd /d "%APK_DIR%" || (
  echo [APK] مسیر پیدا نشد: %APK_DIR%
  set "APK_EXIT=1"
  exit /b 1
)

git rev-parse --is-inside-work-tree >nul 2>&1 || (
  echo [APK] این مسیر یک مخزن Git نیست.
  set "APK_EXIT=1"
  exit /b 1
)

set "BRANCH=main"
for /f "delims=" %%b in ('git rev-parse --abbrev-ref HEAD 2^>nul') do set "BRANCH=%%b"
set "APK_BRANCH=%BRANCH%"
echo [APK] شاخه: %BRANCH%

if not exist version.txt (
  >version.txt echo 1.0.0
)

set /p VERSION=<version.txt
set "APK_VERSION=!VERSION!"

rem ابتدا تغییرات واقعی را بررسی کن — بدون bump نسخه
git add -A

git diff --cached --quiet && git diff --quiet && (
  echo [APK] هیچ تغییری برای پوش نیست.
  set "APK_STATUS=NO_CHANGES"
  set "APK_EXIT=0"
  exit /b 0
)

rem فقط وقتی تغییر هست، نسخه را بالا ببر
for /f "tokens=1-3 delims=." %%a in ("!VERSION!") do (
  set "MAJOR=%%a"
  set "MINOR=%%b"
  set "PATCH=%%c"
)
set /a PATCH+=1
set "NEW_VERSION=!MAJOR!.!MINOR!.!PATCH!"
set "APK_VERSION=!NEW_VERSION!"
>version.txt echo !NEW_VERSION!
set "APK_MSG_OUT=Vinor Android WebView v!NEW_VERSION!"

echo [APK] نسخه جدید: !NEW_VERSION!
echo [APK] تغییرات:
echo --------------------------
git status --short
echo --------------------------

git add version.txt

git commit -m "!APK_MSG_OUT!"
if errorlevel 1 (
  echo [APK] commit ناموفق بود.
  set "APK_EXIT=1"
  exit /b 1
)

git push origin %BRANCH%
if errorlevel 1 (
  echo [APK] push ناموفق بود.
  set "APK_EXIT=1"
  exit /b 1
)

set "APK_STATUS=OK"
set "APK_EXIT=0"
exit /b 0

rem ======================== گزارش‌ها ========================
:print_report_vinor
echo ============================================================
echo   گزارش VINOR — Flask / PWA  (garmabsard-flask)
echo ============================================================
if /i "%VINOR_STATUS%"=="OK" (
  echo   وضعیت  : موفق
) else if /i "%VINOR_STATUS%"=="NO_CHANGES" (
  echo   وضعیت  : بدون تغییر — push انجام نشد
) else if /i "%VINOR_STATUS%"=="SKIPPED" (
  echo   وضعیت  : رد شد ^(در این اجرا اجرا نشد^)
) else (
  echo   وضعیت  : ناموفق
)
echo   شاخه   : %VINOR_BRANCH%
echo   نسخه   : %VINOR_VERSION%
if not "%VINOR_MSG_OUT%"=="-" echo   کامیت  : %VINOR_MSG_OUT%
echo ============================================================
exit /b 0

:print_report_apk
echo ============================================================
echo   گزارش APK — Android WebView  (vinor-webview-android)
echo ============================================================
if /i "%APK_STATUS%"=="OK" (
  echo   وضعیت  : موفق
) else if /i "%APK_STATUS%"=="NO_CHANGES" (
  echo   وضعیت  : بدون تغییر — push انجام نشد
) else if /i "%APK_STATUS%"=="SKIPPED" (
  echo   وضعیت  : رد شد ^(در این اجرا اجرا نشد^)
) else (
  echo   وضعیت  : ناموفق
)
echo   شاخه   : %APK_BRANCH%
echo   نسخه   : %APK_VERSION%
if not "%APK_MSG_OUT%"=="-" echo   کامیت  : %APK_MSG_OUT%
echo ============================================================
exit /b 0

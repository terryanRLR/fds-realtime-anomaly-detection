@echo off
if /I not "%~1"=="RUN" (
    start "" cmd /k "%~f0" RUN
    exit /b
)

setlocal EnableDelayedExpansion
title FDS Team Server Launcher v6

set "LOGFILE=%~dp0start_fds_team_log.txt"
echo ============================================== > "%LOGFILE%"
echo  FDS Team Server Launcher v6 (watcher) - %date% %time% >> "%LOGFILE%"
echo ============================================== >> "%LOGFILE%"

:: --------------------------------------------------
:: [EDIT HERE ONLY] change paths/values for your setup
:: --------------------------------------------------

set "LLAMA_DIR=C:\Users\terry\llama-cpp-turboquant\build\bin\Release"
set "MODEL_PATH=C:\Users\terry\llama-cpp-turboquant\models\gemma-4-26B-A4B-it-qat-UD-Q4_K_XL.gguf"

set NP=3
set CTX=56384
set TEMPERATURE=0.55

:: Resolve the real Desktop folder at runtime (handles localized names)
for /f "usebackq delims=" %%A in (`powershell -NoProfile -Command "[Environment]::GetFolderPath('Desktop')"`) do set "DESKTOP_PATH=%%A"
if not defined DESKTOP_PATH set "DESKTOP_PATH=%USERPROFILE%\Desktop"
set "DASHBOARD_DIR=%DESKTOP_PATH%\QAQC_streamlit"

set "CONDA_ENV=qaqc_st"

set LLAMA_PORT=8080
set STREAMLIT_PORT=8501

:: How long to wait for services (seconds = tries x 2)
set LLAMA_WAIT_TRIES=90
set ST_WAIT_TRIES=30

:: Watcher: set to 0 to skip starting it from this launcher
::  (set 0 if you registered FDSWatcher as a Windows service with NSSM)
set WATCHER_ENABLE=1
set "WATCHER_ARGS=--inbox inbox --interval 5 --startup-ping"

:: --------------------------------------------------
:: No need to edit below this line
:: --------------------------------------------------

echo.
echo  ================================================
echo    FDS Dashboard Team Server  (v6)
echo  ================================================
echo.

:: ---------- [0/6] Clean up stale processes ----------
echo  [0/6] Checking for stale ngrok sessions...
echo [0/6] stale-process check >> "%LOGFILE%"

tasklist /fi "imagename eq ngrok.exe" 2>nul | find /i "ngrok.exe" >nul
if not errorlevel 1 (
    echo   [FIX] Old ngrok session found - killing it.
    echo   [FIX] ngrok free tier allows only ONE session at a time.
    echo   [FIX] A leftover session makes the new tunnel fail silently
    echo   [FIX] and the old URL may point to the WRONG port - this is
    echo   [FIX] the most likely cause of the llama.cpp chat UI showing
    echo   [FIX] instead of the dashboard.
    echo [FIX] killed stale ngrok >> "%LOGFILE%"
    taskkill /f /im ngrok.exe >nul 2>&1
    timeout /t 2 /nobreak >nul
) else (
    echo   No stale ngrok found. OK.
)
echo.

:: ---------- [1/6] Pre-flight checks ----------
echo  [1/6] Verifying paths and programs...
echo [1/6] pre-check start >> "%LOGFILE%"
echo   Desktop path resolved as: %DESKTOP_PATH%
echo   Desktop path resolved as: %DESKTOP_PATH% >> "%LOGFILE%"

set "HAS_ERROR=0"

if not exist "%LLAMA_DIR%\" (
    echo   [ERROR] LLAMA_DIR folder not found: %LLAMA_DIR%
    echo   [ERROR] LLAMA_DIR not found >> "%LOGFILE%"
    set "HAS_ERROR=1"
)
if not exist "%LLAMA_DIR%\llama-server.exe" (
    echo   [ERROR] llama-server.exe not found in: %LLAMA_DIR%
    echo   [ERROR] llama-server.exe not found >> "%LOGFILE%"
    set "HAS_ERROR=1"
)
if not exist "%MODEL_PATH%" (
    echo   [ERROR] Model file not found: %MODEL_PATH%
    echo   [ERROR] model not found >> "%LOGFILE%"
    set "HAS_ERROR=1"
)
if not exist "%DASHBOARD_DIR%\dashboard.py" (
    echo   [ERROR] dashboard.py not found in: %DASHBOARD_DIR%
    echo   [ERROR] dashboard.py not found >> "%LOGFILE%"
    set "HAS_ERROR=1"
)
if "%WATCHER_ENABLE%"=="1" (
    if not exist "%DASHBOARD_DIR%\watcher.py" (
        echo   [WARN] watcher.py not found - watcher step will be skipped.
        echo   [WARN] watcher.py not found >> "%LOGFILE%"
        set "WATCHER_ENABLE=0"
    )
)
where ngrok >nul 2>>"%LOGFILE%"
if errorlevel 1 (
    echo   [ERROR] ngrok not found on PATH.
    echo   [ERROR] ngrok not on PATH >> "%LOGFILE%"
    set "HAS_ERROR=1"
)

:: Locate conda activate.bat directly (more reliable than 'conda activate'
:: inside a fresh cmd window that never ran 'conda init')
set "CONDA_ACT="
for %%P in ("%USERPROFILE%\anaconda3" "%USERPROFILE%\miniconda3" "C:\ProgramData\anaconda3" "C:\ProgramData\miniconda3") do (
    if exist "%%~P\Scripts\activate.bat" set "CONDA_ACT=%%~P\Scripts\activate.bat"
)
if defined CONDA_ACT (
    echo   Conda activate found: !CONDA_ACT!
    echo   conda activate: !CONDA_ACT! >> "%LOGFILE%"
) else (
    echo   [WARN] activate.bat not found in common locations.
    echo   [WARN] Will fall back to 'conda activate' - if the Streamlit
    echo   [WARN] window closes instantly, this is the reason.
    echo   [WARN] conda activate.bat not located >> "%LOGFILE%"
)

if "%HAS_ERROR%"=="1" (
    echo.
    echo  ------------------------------------------------
    echo   Please fix the errors above and run this again.
    echo   Log file: %LOGFILE%
    echo  ------------------------------------------------
    echo pre-check failed >> "%LOGFILE%"
    echo.
    echo  Press any key to close this window...
    pause >nul
    exit /b 1
)
echo   All paths/programs OK.
echo pre-check passed >> "%LOGFILE%"
echo.

:: ---------- [2/6] Write helper launch scripts ----------
:: Helper files avoid the nested-quote problem of  cmd /k "cd /d "path with spaces" && ..."
:: which can silently kill the Streamlit window when the Desktop path contains spaces.

set "HELP_LLAMA=%~dp0_run_llama.cmd"
set "HELP_ST=%~dp0_run_streamlit.cmd"
set "HELP_W=%~dp0_run_watcher.cmd"

> "%HELP_LLAMA%" echo @echo off
>>"%HELP_LLAMA%" echo title llama.cpp server
>>"%HELP_LLAMA%" echo cd /d "%LLAMA_DIR%"
>>"%HELP_LLAMA%" echo .\llama-server.exe --model "%MODEL_PATH%" -fa on --cont-batching --no-kv-unified -ctk turbo3 -ctv turbo3 -to 1800 -fit on --swa-full --ctx-checkpoints 1 -np %NP% --host 127.0.0.1 --port %LLAMA_PORT% -c %CTX% --temperature %TEMPERATURE% --repeat-penalty 1.12 --top-p 0.9 --top-k 40 --jinja
>>"%HELP_LLAMA%" echo echo.
>>"%HELP_LLAMA%" echo echo [llama.cpp ended - check messages above for errors]
>>"%HELP_LLAMA%" echo pause

> "%HELP_ST%" echo @echo off
>>"%HELP_ST%" echo title Streamlit dashboard
if defined CONDA_ACT (
    >>"%HELP_ST%" echo call "%CONDA_ACT%" %CONDA_ENV%
) else (
    >>"%HELP_ST%" echo call conda activate %CONDA_ENV%
)
>>"%HELP_ST%" echo cd /d "%DASHBOARD_DIR%"
>>"%HELP_ST%" echo streamlit run dashboard.py --server.address 0.0.0.0 --server.port %STREAMLIT_PORT% --browser.gatherUsageStats false
>>"%HELP_ST%" echo echo.
>>"%HELP_ST%" echo echo [Streamlit ended - check messages above for errors]
>>"%HELP_ST%" echo pause

> "%HELP_W%" echo @echo off
>>"%HELP_W%" echo title FDS watcher
if defined CONDA_ACT (
    >>"%HELP_W%" echo call "%CONDA_ACT%" %CONDA_ENV%
) else (
    >>"%HELP_W%" echo call conda activate %CONDA_ENV%
)
>>"%HELP_W%" echo cd /d "%DASHBOARD_DIR%"
>>"%HELP_W%" echo set PYTHONUTF8=1
>>"%HELP_W%" echo set PYTHONIOENCODING=utf-8
>>"%HELP_W%" echo set HF_HUB_OFFLINE=1
>>"%HELP_W%" echo python watcher.py %WATCHER_ARGS%
>>"%HELP_W%" echo echo.
>>"%HELP_W%" echo echo [watcher ended - exit code %%errorlevel%%]
>>"%HELP_W%" echo echo   2 = model load failed / 3 = already running / 4 = conda env error
>>"%HELP_W%" echo pause

echo  [2/6] Helper scripts written.
echo [2/6] helpers written >> "%LOGFILE%"
echo.

:: ---------- [3/6] Start llama.cpp and wait for /health ----------
echo  [3/6] Starting llama.cpp server...
echo        Model: %MODEL_PATH%
echo        Slots: %NP% / Context: %CTX% / Temp: %TEMPERATURE%
echo [3/6] starting llama.cpp >> "%LOGFILE%"

start "llama.cpp server" cmd /k "%HELP_LLAMA%"

echo        Waiting for llama.cpp health check (max %LLAMA_WAIT_TRIES%x2 sec)...
set /a _tries=0
:wait_llama
set /a _tries+=1
powershell -NoProfile -Command "try{Invoke-WebRequest -UseBasicParsing http://127.0.0.1:%LLAMA_PORT%/health -TimeoutSec 2 | Out-Null; exit 0}catch{exit 1}" >nul 2>&1
if not errorlevel 1 goto llama_ok
if %_tries% geq %LLAMA_WAIT_TRIES% goto llama_timeout
timeout /t 2 /nobreak >nul
goto wait_llama

:llama_timeout
echo        [WARN] llama.cpp did not answer /health in time.
echo        [WARN] Continuing anyway - check the llama.cpp window.
echo [WARN] llama health timeout >> "%LOGFILE%"
goto llama_done

:llama_ok
echo        llama.cpp is UP. (took about %_tries%x2 sec)
echo llama up after %_tries% tries >> "%LOGFILE%"

:llama_done
echo.

:: ---------- [4/6] Start the FDS watcher ----------
:: Placed AFTER the llama.cpp health check on purpose: the watcher calls the
:: LLM for every alert, so starting it earlier would make the first few
:: detections fall back to the plain template.
echo  [4/6] Starting FDS watcher...
echo [4/6] starting watcher >> "%LOGFILE%"

if not "%WATCHER_ENABLE%"=="1" (
    echo        Skipped (WATCHER_ENABLE=0 or watcher.py missing^).
    echo [4/6] watcher skipped >> "%LOGFILE%"
    goto watcher_done
)

:: If the NSSM service is already running, do NOT start a second one.
:: Two watchers on the same inbox would send every alert twice.
:: (watcher.py also guards this with a lock file and exits with code 3.^)
sc query FDSWatcher 2>nul | find /i "RUNNING" >nul
if not errorlevel 1 (
    echo        FDSWatcher service is already RUNNING - skipping.
    echo        Set WATCHER_ENABLE=0 at the top of this file to silence this.
    echo [4/6] watcher service already running >> "%LOGFILE%"
    goto watcher_done
)

echo        Inbox: %DASHBOARD_DIR%\inbox
echo        Args : %WATCHER_ARGS%
start "FDS watcher" cmd /k "%HELP_W%"

::  How we verify it started, without depending on log text (encoding-safe):
::  watcher.py holds an OS-level lock on .watcher.lock while running, and its
::  atexit handler removes the file on ANY clean exit - including exit 2/3/4.
::  So: file still there after init = alive.  file gone = it died on startup.
echo        Waiting for the watcher to initialize (15 sec^)...
timeout /t 15 /nobreak >nul
if exist "%DASHBOARD_DIR%\.watcher.lock" goto watcher_ok
goto watcher_timeout

:watcher_timeout
echo        [WARN] The watcher exited during startup.
echo        [WARN] Check the "FDS watcher" window. Common causes:
echo        [WARN]   exit 2 = model load failed  (wrong python interpreter^)
echo        [WARN]   exit 3 = another watcher is already running
echo [WARN] watcher start not confirmed >> "%LOGFILE%"
goto watcher_done

:watcher_ok
echo        Watcher is UP.
echo [4/6] watcher up >> "%LOGFILE%"

:watcher_done
echo.

:: ---------- [5/6] Start Streamlit and wait for the port ----------
echo  [5/6] Starting Streamlit dashboard...
echo        Path: %DASHBOARD_DIR%
echo        Port: %STREAMLIT_PORT%
echo [5/6] starting Streamlit >> "%LOGFILE%"

start "Streamlit dashboard" cmd /k "%HELP_ST%"

echo        Waiting for Streamlit to answer (max %ST_WAIT_TRIES%x2 sec)...
set /a _tries=0
:wait_st
set /a _tries+=1
powershell -NoProfile -Command "try{Invoke-WebRequest -UseBasicParsing http://127.0.0.1:%STREAMLIT_PORT% -TimeoutSec 2 | Out-Null; exit 0}catch{exit 1}" >nul 2>&1
if not errorlevel 1 goto st_ok
if %_tries% geq %ST_WAIT_TRIES% goto st_timeout
timeout /t 2 /nobreak >nul
goto wait_st

:st_timeout
echo        [ERROR] Streamlit is NOT answering on port %STREAMLIT_PORT%.
echo        [ERROR] Look at the "Streamlit dashboard" window - if it closed
echo        [ERROR] or shows a conda error, the env activation failed.
echo        [ERROR] ngrok will NOT be started to avoid sharing a dead URL.
echo [ERROR] streamlit not up - ngrok skipped >> "%LOGFILE%"
echo.
echo  Press any key to close this window...
pause >nul
exit /b 1

:st_ok
echo        Streamlit is UP.
echo streamlit up after %_tries% tries >> "%LOGFILE%"
echo.

:: ---------- [6/6] Start ngrok and VERIFY the tunnel target ----------
echo  [6/6] Starting ngrok tunnel to dashboard port %STREAMLIT_PORT%...
echo [6/6] starting ngrok >> "%LOGFILE%"

start "ngrok tunnel" cmd /k "ngrok http 127.0.0.1:%STREAMLIT_PORT%"

echo        Waiting for ngrok local API (max 20 sec)...
set /a _tries=0
:wait_ng
set /a _tries+=1
powershell -NoProfile -Command "try{Invoke-RestMethod http://127.0.0.1:4040/api/tunnels -TimeoutSec 2 | Out-Null; exit 0}catch{exit 1}" >nul 2>&1
if not errorlevel 1 goto ng_ok
if %_tries% geq 10 goto ng_timeout
timeout /t 2 /nobreak >nul
goto wait_ng

:ng_timeout
echo        [WARN] ngrok local API not answering. Check the ngrok window.
echo        [WARN] If it shows ERR_NGROK_108, another session is still
echo        [WARN] alive somewhere (another PC or a hidden process).
echo [WARN] ngrok api timeout >> "%LOGFILE%"
goto summary

:ng_ok
echo.
echo   ---- ACTIVE TUNNELS (public URL - local target) ----
powershell -NoProfile -Command "$t=(Invoke-RestMethod http://127.0.0.1:4040/api/tunnels).tunnels; if(-not $t -or $t.Count -eq 0){Write-Host '   [WARN] no active tunnels'} else { foreach($x in $t){Write-Host ('   ' + $x.public_url + '   ->   ' + $x.config.addr)} }"
echo   ----------------------------------------------------
echo.
echo   CHECK: the target above MUST end with :%STREAMLIT_PORT%
echo   If it ends with :%LLAMA_PORT% you are tunneling the LLM,
echo   not the dashboard - close all ngrok windows and rerun.
echo ngrok tunnels printed >> "%LOGFILE%"

:summary
echo.
echo  ================================================
echo   All services launched.
echo  ================================================
echo.
echo   Local access:    http://localhost:%STREAMLIT_PORT%
echo   LLM server:      http://localhost:%LLAMA_PORT%  (internal only)
if "%WATCHER_ENABLE%"=="1" (
    echo   Watcher:         watching %DASHBOARD_DIR%\inbox  (drop a CSV to test^)
    echo                    status: dashboard session 5 panel, or watcher.log
)
echo   Team share URL:  the https://....ngrok-free.app URL above
echo.
echo   NOTE for teammates: on first visit ngrok shows a warning
echo   page - click "Visit Site" once, then the dashboard loads.
echo   If they see a "Hello there" chat UI instead, they are on
echo   the WRONG (llama.cpp) tunnel - reshare the URL above.
echo.
echo   Log file: %LOGFILE%
echo  ================================================
echo main script done >> "%LOGFILE%"
echo.
echo  Press any key to close this window...
pause >nul

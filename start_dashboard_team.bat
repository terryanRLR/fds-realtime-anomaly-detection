@echo off
if /I not "%~1"=="RUN" (
    start "" cmd /k "%~f0" RUN
    exit /b
)

setlocal EnableDelayedExpansion
title FDS Team Server - dashboard.py only

set "LOGFILE=%~dp0start_dashboard_team_log.txt"
echo ============================================== > "%LOGFILE%"
echo  start_dashboard_team.bat - %date% %time% >> "%LOGFILE%"
echo ============================================== >> "%LOGFILE%"

:: --------------------------------------------------
:: [EDIT HERE] 이 런처만의 동작 스위치. 공용 경로/포트는 fds_config.bat 에서.
:: --------------------------------------------------
set WATCHER_ENABLE=1
set NGROK_ENABLE=1

call "%~dp0fds_config.bat"

echo.
echo  ================================================
echo    FDS Team Server - dashboard.py only
echo  ================================================
echo.

:: ---------- [0/6] Clean up stale ngrok ----------
echo  [0/6] Checking for stale ngrok sessions...
echo [0/6] stale-process check >> "%LOGFILE%"

tasklist /fi "imagename eq ngrok.exe" 2>nul | find /i "ngrok.exe" >nul
if not errorlevel 1 (
    echo   [FIX] Old ngrok session found - killing it.
    echo   [FIX] ngrok free tier allows only ONE tunnel session at a time.
    echo   [FIX] A leftover session makes the new tunnel fail silently or
    echo   [FIX] point at the wrong port.
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

set "HAS_ERROR=0"

if not exist "%LLAMA_DIR%\" (
    echo   [ERROR] LLAMA_DIR folder not found: %LLAMA_DIR%
    set "HAS_ERROR=1"
)
if not exist "%LLAMA_DIR%\llama-server.exe" (
    echo   [ERROR] llama-server.exe not found in: %LLAMA_DIR%
    set "HAS_ERROR=1"
)
if not exist "%MODEL_PATH%" (
    echo   [ERROR] Model file not found: %MODEL_PATH%
    set "HAS_ERROR=1"
)
if not exist "%DASHBOARD_DIR%\dashboard.py" (
    echo   [ERROR] dashboard.py not found in: %DASHBOARD_DIR%
    set "HAS_ERROR=1"
)
if "%WATCHER_ENABLE%"=="1" (
    if not exist "%DASHBOARD_DIR%\watcher.py" (
        echo   [WARN] watcher.py not found - watcher step will be skipped.
        set "WATCHER_ENABLE=0"
    )
)
if "%NGROK_ENABLE%"=="1" (
    where ngrok >nul 2>>"%LOGFILE%"
    if errorlevel 1 (
        echo   [ERROR] ngrok not found on PATH.
        set "HAS_ERROR=1"
    )
)

if "%HAS_ERROR%"=="1" (
    echo.
    echo  Please fix the errors above and run this again. Log: %LOGFILE%
    echo pre-check failed >> "%LOGFILE%"
    echo.
    echo  Press any key to close this window...
    pause >nul
    exit /b 1
)
echo   All paths/programs OK.
echo.

:: ---------- [2/6] Write helper launch scripts ----------
set "HELP_LLAMA=%~dp0_run_llama.cmd"
set "HELP_ST=%~dp0_run_dashboard_streamlit.cmd"
set "HELP_W=%~dp0_run_watcher.cmd"

> "%HELP_LLAMA%" echo @echo off
>>"%HELP_LLAMA%" echo title llama.cpp server
>>"%HELP_LLAMA%" echo cd /d "%LLAMA_DIR%"
>>"%HELP_LLAMA%" echo .\llama-server.exe --model "%MODEL_PATH%" -fa on --cont-batching --no-kv-unified -ctk turbo3 -ctv turbo3 -to 1800 -fit on --swa-full --ctx-checkpoints 1 -np %NP% --host 127.0.0.1 --port %LLAMA_PORT% -c %CTX% --temperature %TEMPERATURE% --repeat-penalty 1.12 --top-p 0.9 --top-k 40 --jinja
>>"%HELP_LLAMA%" echo echo.
>>"%HELP_LLAMA%" echo echo [llama.cpp ended - check messages above for errors]
>>"%HELP_LLAMA%" echo pause

> "%HELP_ST%" echo @echo off
>>"%HELP_ST%" echo title dashboard.py (Streamlit)
if defined CONDA_ACT (
    >>"%HELP_ST%" echo call "%CONDA_ACT%" %CONDA_ENV%
) else (
    >>"%HELP_ST%" echo call conda activate %CONDA_ENV%
)
>>"%HELP_ST%" echo cd /d "%DASHBOARD_DIR%"
>>"%HELP_ST%" echo streamlit run dashboard.py --server.address %BIND_ADDR% --server.port %DASHBOARD_PORT% --browser.gatherUsageStats false
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
echo.

:: ---------- [3/6] Start llama.cpp and wait for /health ----------
echo  [3/6] Starting llama.cpp server...
echo        Model: %MODEL_PATH%
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
echo        [WARN] llama.cpp did not answer /health in time. Continuing anyway.
goto llama_done

:llama_ok
echo        llama.cpp is UP. (took about %_tries%x2 sec)

:llama_done
echo.

:: ---------- [4/6] Start the FDS watcher ----------
echo  [4/6] Starting FDS watcher...

if not "%WATCHER_ENABLE%"=="1" (
    echo        Skipped (WATCHER_ENABLE=0 or watcher.py missing^).
    goto watcher_done
)

sc query FDSWatcher 2>nul | find /i "RUNNING" >nul
if not errorlevel 1 (
    echo        FDSWatcher service is already RUNNING - skipping.
    goto watcher_done
)

:: 락 파일이 있어도 실제로 watcher.py 프로세스가 살아있는지 직접 확인한다.
:: 이전 세션이 강제 종료돼서 락만 남아있는 stale lock 이면 자동으로 지우고
:: 새로 띄운다 - 그냥 락 존재만 보고 건너뛰면 워처가 영원히 안 뜨는 조용한
:: 실패가 생기기 때문.
:: 참고: 이 주석 블록은 반드시 아래 if exist 괄호 블록 밖에 있어야 한다 -
:: 괄호 블록 안에 들어간 콜론콜론 주석은 cmd.exe 파서를 깨뜨린다.
if exist "%DASHBOARD_DIR%\.watcher.lock" (
    powershell -NoProfile -Command "$p = Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -match 'watcher.py' }; if ($p) { exit 0 } else { exit 1 }" >nul 2>&1
    if not errorlevel 1 (
        echo        A watcher lock file exists and a watcher.py process is running - skipping.
        goto watcher_done
    ) else (
        echo        [FIX] Stale .watcher.lock found ^(no running watcher.py process^)
        echo        [FIX] - removing it and starting a fresh watcher.
        echo [FIX] removed stale watcher lock >> "%LOGFILE%"
        del /f /q "%DASHBOARD_DIR%\.watcher.lock" 2>nul
    )
)

echo        Inbox: %DASHBOARD_DIR%\inbox
start "FDS watcher" cmd /k "%HELP_W%"

echo        Waiting for the watcher to initialize (15 sec^)...
timeout /t 15 /nobreak >nul
if exist "%DASHBOARD_DIR%\.watcher.lock" (
    echo        Watcher is UP.
) else (
    echo        [WARN] The watcher exited during startup - check its window.
    echo        [WARN]   exit 2 = model load failed / exit 3 = already running
)

:watcher_done
echo.

:: ---------- [5/6] Start Streamlit (dashboard.py) and wait ----------
echo  [5/6] Starting dashboard.py on port %DASHBOARD_PORT%...

netstat -ano | findstr :%DASHBOARD_PORT% | findstr LISTENING >nul
if not errorlevel 1 (
    echo   [ERROR] Port %DASHBOARD_PORT% is already in use - is dashboard.py
    echo   [ERROR] already running from another launcher? Details:
    netstat -ano | findstr :%DASHBOARD_PORT% | findstr LISTENING
    echo   [ERROR] Close that process, or change DASHBOARD_PORT in fds_config.bat.
    echo [ERROR] dashboard port busy >> "%LOGFILE%"
    echo.
    echo  Press any key to close this window...
    pause >nul
    exit /b 1
)

start "dashboard.py" cmd /k "%HELP_ST%"

echo        Waiting for Streamlit to answer (max %ST_WAIT_TRIES%x2 sec)...
set /a _tries=0
:wait_st
set /a _tries+=1
powershell -NoProfile -Command "try{Invoke-WebRequest -UseBasicParsing http://127.0.0.1:%DASHBOARD_PORT% -TimeoutSec 2 | Out-Null; exit 0}catch{exit 1}" >nul 2>&1
if not errorlevel 1 goto st_ok
if %_tries% geq %ST_WAIT_TRIES% goto st_timeout
timeout /t 2 /nobreak >nul
goto wait_st

:st_timeout
echo        [ERROR] dashboard.py is NOT answering on port %DASHBOARD_PORT%.
echo        [ERROR] Check the "dashboard.py" window - a conda error is the
echo        [ERROR] usual cause. ngrok will NOT be started.
echo [ERROR] streamlit not up - ngrok skipped >> "%LOGFILE%"
echo.
echo  Press any key to close this window...
pause >nul
exit /b 1

:st_ok
echo        dashboard.py is UP.
echo.

:: ---------- [6/6] Start ngrok and verify the tunnel target ----------
if not "%NGROK_ENABLE%"=="1" (
    echo  [6/6] NGROK_ENABLE=0 - skipping ngrok tunnel.
    goto summary
)

echo  [6/6] Starting ngrok tunnel to dashboard.py (port %DASHBOARD_PORT%)...
start "ngrok tunnel" cmd /k "ngrok http 127.0.0.1:%DASHBOARD_PORT%"

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
goto summary

:ng_ok
echo.
echo   ---- ACTIVE TUNNELS (public URL - local target) ----
powershell -NoProfile -Command "$t=(Invoke-RestMethod http://127.0.0.1:4040/api/tunnels).tunnels; if(-not $t -or $t.Count -eq 0){Write-Host '   [WARN] no active tunnels'} else { foreach($x in $t){Write-Host ('   ' + $x.public_url + '   ->   ' + $x.config.addr)} }"
echo   ----------------------------------------------------
echo   CHECK: the target above MUST end with :%DASHBOARD_PORT%

:summary
echo.
echo  ================================================
echo   dashboard.py team server is up.
echo  ================================================
echo   Local access:  http://localhost:%DASHBOARD_PORT%
echo   LLM server:    http://localhost:%LLAMA_PORT%  (internal only)
if "%WATCHER_ENABLE%"=="1" echo   Watcher:       watching %DASHBOARD_DIR%\inbox
echo   Log file: %LOGFILE%
echo  ================================================
echo.
echo  Press any key to close this window...
pause >nul

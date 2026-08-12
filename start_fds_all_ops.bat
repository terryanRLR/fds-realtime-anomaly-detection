@echo off
if /I not "%~1"=="RUN" (
    start "" cmd /k "%~f0" RUN
    exit /b
)

setlocal EnableDelayedExpansion
title FDS Ops Server - ngrok publishes ops_dashboard.py (:8502)

set "LOGFILE=%~dp0start_fds_all_ops_log.txt"
echo ============================================== > "%LOGFILE%"
echo  start_fds_all_ops.bat - %date% %time% >> "%LOGFILE%"
echo ============================================== >> "%LOGFILE%"

:: --------------------------------------------------
:: [EDIT HERE] 이 런처만의 동작 스위치. 공용 경로/포트는 fds_config.bat 에서.
:: ngrok 무료 플랜은 동시 터널이 1개뿐이라, dashboard/ops 둘 중 하나만
:: 외부 공개(ngrok)하고 나머지는 사내망 IP로 접속합니다.
:: TUNNEL_TARGET 값: dashboard  또는  ops
:: --------------------------------------------------
set WATCHER_ENABLE=1
set NGROK_ENABLE=1

:: ★ 이 런처의 존재 이유: ngrok 을 ops_dashboard.py(:8502)로 연결한다.
::   start_fds_all.bat 은 dashboard.py(:8501)를 공개한다 - 그 차이가 전부다.
::   (예전에는 두 파일이 바이트 단위로 같아서, ops 런처를 써도 실제로는
::    분석용 dashboard.py 가 외부에 공개됐다.)
set TUNNEL_TARGET=ops

call "%~dp0fds_config.bat"

echo.
echo  ================================================
echo    FDS Ops Server - ngrok publishes OPS console
echo  ================================================
echo.

:: ---------- [0/8] Clean up stale ngrok ----------
echo  [0/8] Checking for stale ngrok sessions...
tasklist /fi "imagename eq ngrok.exe" 2>nul | find /i "ngrok.exe" >nul
if not errorlevel 1 (
    echo   [FIX] Old ngrok session found - killing it.
    echo   [FIX] ngrok free tier allows only ONE tunnel session at a time,
    echo   [FIX] which is why this launcher only tunnels ONE dashboard
    echo   [FIX] (TUNNEL_TARGET=%TUNNEL_TARGET%^) - the other is LAN-only.
    taskkill /f /im ngrok.exe >nul 2>&1
    timeout /t 2 /nobreak >nul
) else (
    echo   No stale ngrok found. OK.
)
echo.

:: ---------- [1/8] Pre-flight checks ----------
echo  [1/8] Verifying paths and programs...
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
if not exist "%DASHBOARD_DIR%\ops_dashboard.py" (
    echo   [ERROR] ops_dashboard.py not found in: %DASHBOARD_DIR%
    set "HAS_ERROR=1"
)
if "%WATCHER_ENABLE%"=="1" (
    if not exist "%DASHBOARD_DIR%\watcher.py" (
        echo   [WARN] watcher.py not found - watcher step will be skipped.
        set "WATCHER_ENABLE=0"
    )
)
if /I not "%TUNNEL_TARGET%"=="dashboard" if /I not "%TUNNEL_TARGET%"=="ops" (
    echo   [ERROR] TUNNEL_TARGET must be "dashboard" or "ops", got: %TUNNEL_TARGET%
    set "HAS_ERROR=1"
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
    echo.
    echo  Press any key to close this window...
    pause >nul
    exit /b 1
)
echo   All paths/programs OK.
echo.

:: ---------- [2/8] Write helper launch scripts ----------
set "HELP_LLAMA=%~dp0_run_llama.cmd"
set "HELP_ST_DASH=%~dp0_run_dashboard_streamlit.cmd"
set "HELP_ST_OPS=%~dp0_run_ops_streamlit.cmd"
set "HELP_W=%~dp0_run_watcher.cmd"

> "%HELP_LLAMA%" echo @echo off
>>"%HELP_LLAMA%" echo title llama.cpp server
>>"%HELP_LLAMA%" echo cd /d "%LLAMA_DIR%"
>>"%HELP_LLAMA%" echo .\llama-server.exe --model "%MODEL_PATH%" -fa on --cont-batching --no-kv-unified -ctk turbo3 -ctv turbo3 -to 1800 -fit on --swa-full --ctx-checkpoints 1 -np %NP% --host 127.0.0.1 --port %LLAMA_PORT% -c %CTX% --temperature %TEMPERATURE% --repeat-penalty 1.12 --top-p 0.9 --top-k 40 --jinja
>>"%HELP_LLAMA%" echo echo.
>>"%HELP_LLAMA%" echo echo [llama.cpp ended - check messages above for errors]
>>"%HELP_LLAMA%" echo pause

> "%HELP_ST_DASH%" echo @echo off
>>"%HELP_ST_DASH%" echo title dashboard.py (Streamlit)
if defined CONDA_ACT (
    >>"%HELP_ST_DASH%" echo call "%CONDA_ACT%" %CONDA_ENV%
) else (
    >>"%HELP_ST_DASH%" echo call conda activate %CONDA_ENV%
)
>>"%HELP_ST_DASH%" echo cd /d "%DASHBOARD_DIR%"
>>"%HELP_ST_DASH%" echo streamlit run dashboard.py --server.address %BIND_ADDR% --server.port %DASHBOARD_PORT% --browser.gatherUsageStats false
>>"%HELP_ST_DASH%" echo echo.
>>"%HELP_ST_DASH%" echo echo [Streamlit ended - check messages above for errors]
>>"%HELP_ST_DASH%" echo pause

> "%HELP_ST_OPS%" echo @echo off
>>"%HELP_ST_OPS%" echo title ops_dashboard.py (Streamlit)
if defined CONDA_ACT (
    >>"%HELP_ST_OPS%" echo call "%CONDA_ACT%" %CONDA_ENV%
) else (
    >>"%HELP_ST_OPS%" echo call conda activate %CONDA_ENV%
)
>>"%HELP_ST_OPS%" echo cd /d "%DASHBOARD_DIR%"
>>"%HELP_ST_OPS%" echo streamlit run ops_dashboard.py --server.address %BIND_ADDR% --server.port %OPS_PORT% --browser.gatherUsageStats false
>>"%HELP_ST_OPS%" echo echo.
>>"%HELP_ST_OPS%" echo echo [Streamlit ended - check messages above for errors]
>>"%HELP_ST_OPS%" echo pause

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

echo  [2/8] Helper scripts written.
echo.

:: ---------- [3/8] Start llama.cpp and wait for /health ----------
echo  [3/8] Starting llama.cpp server...
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
echo        llama.cpp is UP.
:llama_done
echo.

:: ---------- [4/8] Start the FDS watcher (once, shared by both dashboards) ----------
echo  [4/8] Starting FDS watcher...
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
:: 이전 세션이 강제 종료돼서 락만 남은 stale lock 이면 자동 삭제하고
:: 새로 띄운다.
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
        del /f /q "%DASHBOARD_DIR%\.watcher.lock" 2>nul
    )
)
start "FDS watcher" cmd /k "%HELP_W%"
echo        Waiting for the watcher to initialize (15 sec^)...
timeout /t 15 /nobreak >nul
if exist "%DASHBOARD_DIR%\.watcher.lock" (
    echo        Watcher is UP.
) else (
    echo        [WARN] The watcher exited during startup - check its window.
)
:watcher_done
echo.

:: ---------- [5/8] Start dashboard.py and wait ----------
echo  [5/8] Starting dashboard.py on port %DASHBOARD_PORT%...
netstat -ano | findstr :%DASHBOARD_PORT% | findstr LISTENING >nul
if not errorlevel 1 (
    echo   [ERROR] Port %DASHBOARD_PORT% already in use:
    netstat -ano | findstr :%DASHBOARD_PORT% | findstr LISTENING
    echo.
    echo  Press any key to close this window...
    pause >nul
    exit /b 1
)
start "dashboard.py" cmd /k "%HELP_ST_DASH%"
set /a _tries=0
:wait_dash
set /a _tries+=1
powershell -NoProfile -Command "try{Invoke-WebRequest -UseBasicParsing http://127.0.0.1:%DASHBOARD_PORT% -TimeoutSec 2 | Out-Null; exit 0}catch{exit 1}" >nul 2>&1
if not errorlevel 1 goto dash_ok
if %_tries% geq %ST_WAIT_TRIES% goto dash_timeout
timeout /t 2 /nobreak >nul
goto wait_dash
:dash_timeout
echo        [ERROR] dashboard.py is NOT answering. Check its window.
echo [ERROR] dashboard.py not up >> "%LOGFILE%"
goto dash_done
:dash_ok
echo        dashboard.py is UP.
:dash_done
echo.

:: ---------- [6/8] Start ops_dashboard.py and wait ----------
echo  [6/8] Starting ops_dashboard.py on port %OPS_PORT%...
netstat -ano | findstr :%OPS_PORT% | findstr LISTENING >nul
if not errorlevel 1 (
    echo   [ERROR] Port %OPS_PORT% already in use:
    netstat -ano | findstr :%OPS_PORT% | findstr LISTENING
    echo.
    echo  Press any key to close this window...
    pause >nul
    exit /b 1
)
start "ops_dashboard.py" cmd /k "%HELP_ST_OPS%"
set /a _tries=0
:wait_ops
set /a _tries+=1
powershell -NoProfile -Command "try{Invoke-WebRequest -UseBasicParsing http://127.0.0.1:%OPS_PORT% -TimeoutSec 2 | Out-Null; exit 0}catch{exit 1}" >nul 2>&1
if not errorlevel 1 goto ops_ok
if %_tries% geq %ST_WAIT_TRIES% goto ops_timeout
timeout /t 2 /nobreak >nul
goto wait_ops
:ops_timeout
echo        [ERROR] ops_dashboard.py is NOT answering. Check its window.
echo [ERROR] ops_dashboard.py not up >> "%LOGFILE%"
goto ops_done
:ops_ok
echo        ops_dashboard.py is UP.
:ops_done
echo.

:: ---------- [7/8] LAN IP (for the dashboard that will NOT be tunneled) ----------
for /f "usebackq delims=" %%A in (`powershell -NoProfile -Command "(Get-NetIPAddress -AddressFamily IPv4 | Where-Object {$_.InterfaceAlias -notmatch 'Loopback' -and $_.IPAddress -notmatch '^169\.254\.'} | Select-Object -First 1 -ExpandProperty IPAddress)"`) do set "LAN_IP=%%A"
if not defined LAN_IP set "LAN_IP=(확인 실패 - ipconfig 로 직접 확인)"

:: ---------- [8/8] Start ngrok for the chosen target only ----------
if not "%NGROK_ENABLE%"=="1" (
    echo  [8/8] NGROK_ENABLE=0 - skipping ngrok tunnel.
    goto summary
)

if /I "%TUNNEL_TARGET%"=="ops" (
    set "TUNNEL_PORT=%OPS_PORT%"
) else (
    set "TUNNEL_PORT=%DASHBOARD_PORT%"
)

echo  [8/8] Starting ngrok tunnel to %TUNNEL_TARGET% (port !TUNNEL_PORT!^)...
echo        (ngrok free tier = 1 tunnel only, so the other dashboard stays LAN-only)
start "ngrok tunnel" cmd /k "ngrok http 127.0.0.1:!TUNNEL_PORT!"

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
echo   CHECK: the target above MUST end with :!TUNNEL_PORT!

:summary
echo.
echo  ================================================
echo   All services launched.
echo  ================================================
echo   ops_dashboard.py  : http://localhost:%OPS_PORT%   ^<== PUBLISHED via ngrok
echo   dashboard.py      : http://localhost:%DASHBOARD_PORT%   ^(LAN only^)
echo   LLM server        : http://localhost:%LLAMA_PORT%  (internal only)
if "%WATCHER_ENABLE%"=="1" echo   Watcher           : watching %DASHBOARD_DIR%\inbox
echo.
if "%NGROK_ENABLE%"=="1" (
    echo   ngrok public URL  : tunnels %TUNNEL_TARGET% only ^(see above^)
    if /I "%TUNNEL_TARGET%"=="dashboard" (
        echo   ops_dashboard.py for teammates on this LAN: http://%LAN_IP%:%OPS_PORT%
    ) else (
        echo   dashboard.py for teammates on this LAN:     http://%LAN_IP%:%DASHBOARD_PORT%
    )
    echo   ^(This launcher publishes the OPS console. To publish the analysis
    echo    dashboard instead, run start_fds_all.bat - or change TUNNEL_TARGET
    echo    at the top of this script.^)
)
echo.
echo   Log file: %LOGFILE%
echo  ================================================
echo.
echo  Press any key to close this window...
pause >nul

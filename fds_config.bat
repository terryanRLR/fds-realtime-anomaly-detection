@echo off
:: ============================================================
::  FDS Team Server - 공유 설정 파일
::  이 파일은 직접 실행하는 게 아니라, 아래 3개 런처가 각자 시작할 때
::  call "%%~dp0fds_config.bat" 로 불러 씁니다.
::  경로/모델/포트를 바꿀 일이 있으면 이 파일 하나만 고치면 3개 스크립트에
::  전부 반영됩니다.
:: ============================================================

:: ---------- llama.cpp ----------
set "LLAMA_DIR=C:\Users\terry\llama-cpp-turboquant\build\bin\Release"
set "MODEL_PATH=C:\Users\terry\llama-cpp-turboquant\models\gemma-4-26B-A4B-it-qat-UD-Q4_K_XL.gguf"
set NP=3
set CTX=56384
set TEMPERATURE=0.55
set LLAMA_PORT=8080
set LLAMA_WAIT_TRIES=90

:: ---------- 대시보드 위치 / conda ----------
for /f "usebackq delims=" %%A in (`powershell -NoProfile -Command "[Environment]::GetFolderPath('Desktop')"`) do set "DESKTOP_PATH=%%A"
if not defined DESKTOP_PATH set "DESKTOP_PATH=%USERPROFILE%\Desktop"
set "DASHBOARD_DIR=%DESKTOP_PATH%\QAQC_streamlit"
set "CONDA_ENV=qaqc_st"

:: ---------- 대시보드 두 개 포트 ----------
set DASHBOARD_PORT=8501
set OPS_PORT=8502
set ST_WAIT_TRIES=30

:: ---------- 워처 ----------
set "WATCHER_ARGS=--inbox inbox --interval 5 --startup-ping"

:: ---------- conda activate.bat 위치 자동 탐색 ----------
set "CONDA_ACT="
for %%P in ("%USERPROFILE%\anaconda3" "%USERPROFILE%\miniconda3" "C:\ProgramData\anaconda3" "C:\ProgramData\miniconda3") do (
    if exist "%%~P\Scripts\activate.bat" set "CONDA_ACT=%%~P\Scripts\activate.bat"
)
if defined CONDA_ACT (
    echo   Conda activate found: !CONDA_ACT!
) else (
    echo   [WARN] activate.bat not found in common locations.
    echo   [WARN] Will fall back to 'conda activate' - if a streamlit/watcher
    echo   [WARN] window closes instantly, this is the likely reason.
)

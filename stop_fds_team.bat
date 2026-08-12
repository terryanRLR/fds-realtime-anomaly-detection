@echo off
chcp 65001 >nul
title FDS Server Shutdown

echo.
echo  FDS 서비스 전체 종료 중...
echo.

:: Streamlit (python 프로세스 중 streamlit이 포함된 것)
taskkill /f /im "ngrok.exe" 2>nul && echo  [OK] ngrok 종료 || echo  [--] ngrok 미실행

:: llama-server
taskkill /f /im "llama-server.exe" 2>nul && echo  [OK] llama-server 종료 || echo  [--] llama-server 미실행

echo.
echo  (Streamlit은 해당 터미널에서 Ctrl+C로 종료해주세요)
echo.
pause

@echo off
REM dashboard.py 전용 실행 스크립트 - 항상 8501 포트 고정
REM ops_dashboard.py 는 run_ops_dashboard.bat (8502) 로 따로 실행하세요.
set PORT=8501

netstat -ano | findstr :%PORT% | findstr LISTENING >nul
if %ERRORLEVEL%==0 (
    echo [경고] 포트 %PORT% 이 이미 사용 중입니다. 아래에서 확인하세요:
    netstat -ano | findstr :%PORT% | findstr LISTENING
    echo   -^> 위 프로세스를 종료하거나, ops_dashboard.py 를 이 포트로 켠 게 아닌지 확인하세요.
    pause
    exit /b 1
)

echo dashboard.py -^> http://localhost:%PORT%
streamlit run dashboard.py --server.port %PORT%

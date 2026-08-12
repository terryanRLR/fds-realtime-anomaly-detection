@echo off
REM ops_dashboard.py 전용 실행 스크립트 - 항상 8502 포트 고정
REM dashboard.py 는 run_dashboard.bat (8501) 로 따로 실행하세요.
set PORT=8502

netstat -ano | findstr :%PORT% | findstr LISTENING >nul
if %ERRORLEVEL%==0 (
    echo [경고] 포트 %PORT% 이 이미 사용 중입니다. 아래에서 확인하세요:
    netstat -ano | findstr :%PORT% | findstr LISTENING
    echo   -^> 위 프로세스를 종료하거나, dashboard.py 를 이 포트로 켠 게 아닌지 확인하세요.
    pause
    exit /b 1
)

echo ops_dashboard.py -^> http://localhost:%PORT%
streamlit run ops_dashboard.py --server.port %PORT%

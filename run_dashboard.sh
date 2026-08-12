#!/usr/bin/env bash
# dashboard.py 전용 실행 스크립트 — 항상 8501 포트 고정
# ops_dashboard.py 는 run_ops_dashboard.sh (8502) 로 따로 실행하세요.
set -e
PORT=8501

if lsof -i :"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "⚠️  포트 $PORT 이미 사용 중입니다. 다른 대시보드가 이 포트를 물고 있을 수 있어요:"
  lsof -i :"$PORT" -sTCP:LISTEN
  echo ""
  echo "   → 위 프로세스를 종료하거나, ops_dashboard.py 를 이 포트로 켠 게 아닌지 확인하세요."
  exit 1
fi

echo "🚀 dashboard.py → http://localhost:$PORT"
streamlit run dashboard.py --server.port "$PORT"

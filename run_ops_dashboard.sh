#!/usr/bin/env bash
# ops_dashboard.py 전용 실행 스크립트 — 항상 8502 포트 고정
# dashboard.py 는 run_dashboard.sh (8501) 로 따로 실행하세요.
set -e
PORT=8502

if lsof -i :"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "⚠️  포트 $PORT 이미 사용 중입니다. 다른 대시보드가 이 포트를 물고 있을 수 있어요:"
  lsof -i :"$PORT" -sTCP:LISTEN
  echo ""
  echo "   → 위 프로세스를 종료하거나, dashboard.py 를 이 포트로 켠 게 아닌지 확인하세요."
  exit 1
fi

echo "🚀 ops_dashboard.py → http://localhost:$PORT"
# 127.0.0.1 고정 — 관제 화면은 판정·발송 권한을 그대로 노출한다.
# LAN 공유가 필요하면 BIND_ADDR=0.0.0.0 을 주고 실행할 것.
BIND_ADDR="${BIND_ADDR:-127.0.0.1}"
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8
streamlit run ops_dashboard.py --server.address "$BIND_ADDR" --server.port "$PORT"

"""selftest_all — 자체 테스트 전부 실행  ✨ v24 신규

    python -m pipeline.selftest_all           # 전부
    python -m pipeline.selftest_all --fast    # 느린 것(UI·원본대조) 제외
    python -m pipeline.selftest_all agent ui  # 이름으로 골라서

왜 러너가 필요한가
  테스트가 열 개가 넘어가면 "무엇이 있는지" 자체를 모르게 된다. 손대기 전과 후에
  이 한 줄만 돌리면 되도록 모아 둔다.

⚠️ 모든 테스트는 **운영 DB(fds_results.db)를 건드리지 않는다.**
  임시 DB나 사본만 쓴다 — 예전에 selftest_alert 가 운영 원장에 테스트 행 18건을
  남긴 사고가 있었다(v24 에서 수정). 새 테스트를 추가할 때도 이 규칙을 지킬 것.
"""
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 🔧 FIX(인코딩): 한국어 Windows 기본 콘솔은 cp949 라서, 아래 출력에 쓰는 em dash(—)와
#   박스 문자(━ ═)가 UnicodeEncodeError 를 던지며 러너가 **첫 줄에서 즉사**했다.
#   README·인수인계 문서가 안내하는 `python -m pipeline.selftest_all --fast` 가
#   그대로는 돌지 않았다는 뜻이다. 매번 PYTHONUTF8=1 을 붙이게 하는 대신 여기서 고정한다.
#   ※ 자식 테스트들은 원래부터 안전했다 — main() 의 env 가 PYTHONIOENCODING 을
#     물려주고 subprocess 도 encoding="utf-8" 로 읽는다. 죽던 것은 **러너 자신의
#     print** 였다.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):      # 파이프로 리다이렉트된 경우 등
        pass

# (이름, 모듈, 느림?, 설명)
SUITE = [
    ("agent",       "pipeline.selftest_agent",        False, "챗봇 액션 화이트리스트·파싱"),
    ("shift",       "pipeline.selftest_shift",        False, "SLA 경과·교대 인수인계"),
    ("dispatch",    "pipeline.selftest_dispatch",     False, "발송 감사 로그·2단계 삭제"),
    ("detect_io",   "pipeline.selftest_detect_io",    False, "원장 이원화·거래ID·계좌이력"),
    ("status",      "pipeline.selftest_status_push",  False, "상태 외부 내보내기·잠금 하트비트"),
    ("alert",       "pipeline.selftest_alert",        False, "경보 폴링·등급·렌더"),
    ("ops",         "pipeline.selftest_ops",          False, "조회 계층·시간대"),
    ("analysis",    "pipeline.selftest_analysis",     False, "분석 캐시"),
    ("recheck",     "pipeline.selftest_recheck",      False, "재검증·마스킹"),
    ("migrate",     "pipeline.selftest_migrate",      False, "시간대 마이그레이션"),
    ("preprocessor", "pipeline.selftest_preprocessor", True,  "배치 불변식·시도 매핑"),
    ("ui",          "pipeline.selftest_ui",           True,  "화면 회귀 (AppTest)"),
]


def main() -> int:
    args = [a for a in sys.argv[1:]]
    fast = "--fast" in args
    picked = [a for a in args if not a.startswith("-")]

    todo = [s for s in SUITE
            if (not picked or s[0] in picked) and not (fast and s[2])]
    if not todo:
        print(f"실행할 테스트가 없습니다. 이름: {[s[0] for s in SUITE]}")
        return 1

    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    results, t_all = [], time.perf_counter()
    for name, mod, slow, desc in todo:
        print(f"\n{'━' * 62}\n▶ {name}  — {desc}{'  (느림)' if slow else ''}")
        t0 = time.perf_counter()
        p = subprocess.run([sys.executable, "-m", mod], cwd=str(ROOT), env=env,
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        dt = time.perf_counter() - t0
        ok = p.returncode == 0
        results.append((name, ok, dt))
        if ok:
            print(f"  ✅ 통과  ({dt:.1f}초)")
        else:
            print(f"  ❌ 실패  ({dt:.1f}초)")
            tail = [ln for ln in (p.stdout or "").split("\n") if ln.strip()][-25:]
            for ln in tail:
                print("     " + ln)
            if p.stderr and p.stderr.strip():
                print("     --- stderr ---")
                for ln in (p.stderr or "").split("\n")[-8:]:
                    if ln.strip():
                        print("     " + ln)

    n_ok = sum(1 for _, ok, _ in results if ok)
    print(f"\n{'═' * 62}")
    for name, ok, dt in results:
        print(f"  {'✅' if ok else '❌'} {name:<14}{dt:>7.1f}초")
    print(f"{'─' * 62}")
    print(f"  {n_ok}/{len(results)} 통과 · 총 {time.perf_counter() - t_all:.1f}초")
    return 0 if n_ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())

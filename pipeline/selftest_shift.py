"""selftest_shift — ops_shift(SLA · 교대 인수인계) 자체 검증  ✨ v24 신규

무엇을 지키려는가
  '방치된 시간'을 계산하는 층이다. 여기가 틀리면 화면의 🔴/🟡 가 거짓말을 하고,
  담당자는 급한 건을 급하지 않다고 믿는다. 그래서 경계값(정확히 SLA 인 순간)과
  **시간대 처리**를 집중적으로 본다 — 이 프로젝트에서 시각은 늘 사고의 진원지였다.

⚠️ 운영 DB 를 절대 건드리지 않는다. 모든 쓰기는 임시 DB 에서 한다.

실행:  python -m pipeline.selftest_shift
"""
import datetime as _dt
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import ops_shift as osh

fails: list[str] = []


def check(name: str, cond, detail: str = ""):
    print(("  ✅ " if cond else "  ❌ ") + name + (f" — {detail}" if detail else ""))
    if not cond:
        fails.append(name)


def utc_ago(minutes: float) -> str:
    return (_dt.datetime.now(_dt.timezone.utc)
            - _dt.timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")


print("=" * 62)
print("[1] age_minutes — UTC 문자열 → 경과 분")
check("30분 전", abs(osh.age_minutes(utc_ago(30)) - 30) < 1.5,
      str(osh.age_minutes(utc_ago(30))))
check("0분 전", abs(osh.age_minutes(utc_ago(0))) < 1.5)
check("None 안전", osh.age_minutes(None) is None)
check("쓰레기 문자열 안전", osh.age_minutes("어제쯤") is None)
check("빈 문자열 안전", osh.age_minutes("") is None)

print("\n[2] urgency — 경계값이 정확한가 (SLA=30)")
check("29분 → over 아님", osh.urgency(29, 30) != "over", osh.urgency(29, 30))
check("30분 → over", osh.urgency(30, 30) == "over", osh.urgency(30, 30))
check("31분 → over", osh.urgency(31, 30) == "over")
check("0분 → ok", osh.urgency(0, 30) == "ok")
check("None → ok 로 떨어진다(예외 없음)", osh.urgency(None, 30) in ("ok", "warn", "over"),
      str(osh.urgency(None, 30)))
_warn = [m for m in range(0, 31) if osh.urgency(m, 30) == "warn"]
check("warn 구간이 over 직전에 존재", bool(_warn), f"{min(_warn)}~{max(_warn)}분" if _warn else "없음")

print("\n[3] elapsed_label — 사람이 읽는 형태")
check("None → 대시", osh.elapsed_label(None) in ("—", "-", ""), osh.elapsed_label(None))
check("분 단위 표기", "분" in osh.elapsed_label(5), osh.elapsed_label(5))
check("시간 단위 표기", "시간" in osh.elapsed_label(200), osh.elapsed_label(200))

print("\n[4] annotate / sla_stats — 큐 전체 집계")
queue = [
    {"txn_id": "A", "ts_utc": utc_ago(120), "risk_score": 0.9},   # over
    {"txn_id": "B", "ts_utc": utc_ago(45), "risk_score": 0.5},    # over
    {"txn_id": "C", "ts_utc": utc_ago(1), "risk_score": 0.1},     # ok
    {"txn_id": "D", "ts_utc": None, "risk_score": 0.2},           # 시각 없음
]
osh.annotate(queue, 30)
check("모든 행에 urgency 주석", all("urgency" in r for r in queue))
check("모든 행에 elapsed 주석", all("elapsed" in r for r in queue))
check("시각 없는 행도 죽지 않는다", queue[3].get("urgency") is not None)

s = osh.sla_stats(queue, 30)
check("pending = 전체", s["pending"] == 4, str(s))
check("over 2건", s["over"] == 2, str(s))
check("최장 대기 ≈ 120분", abs((s["oldest_min"] or 0) - 120) < 2, str(s["oldest_min"]))

check("빈 큐 안전", osh.sla_stats([], 30)["pending"] == 0)
osh.annotate([], 30)

print("\n[5] sort_by_urgency — 급한 것이 위로")
order = [r["txn_id"] for r in osh.sort_by_urgency(list(queue))]
check("가장 오래 기다린 A 가 맨 앞", order[0] == "A", str(order))

print("\n[6] 교대 인수인계 — 임시 DB 에 저장·조회")
tmp = Path(tempfile.gettempdir()) / "selftest_shift.db"
for suf in ("", "-wal", "-shm"):
    if os.path.exists(str(tmp) + suf):
        os.remove(str(tmp) + suf)
DB = str(tmp)
sqlite3.connect(DB).close()

check("스키마 생성", osh.ensure_handover_schema(DB))
ok, msg = osh.save_handover(DB, "홍길동", "j형 급증 — 같은 수취계좌 3건", 8, "# 요약")
check("저장 성공", ok, msg)
rows = osh.recent_handovers(DB, limit=5)
check("조회 1건", len(rows) == 1, str(len(rows)))
check("작성자 보존", rows[0]["author"] == "홍길동", str(rows[0].get("author")))
check("메모 보존", "j형 급증" in rows[0]["note"], rows[0].get("note", "")[:30])
check("경과 표기(age) 포함", bool(rows[0].get("age")), str(rows[0].get("age")))

osh.save_handover(DB, "김철수", "두 번째", 8, "# 요약2")
rows = osh.recent_handovers(DB, limit=5)
check("최신이 맨 앞", rows[0]["author"] == "김철수", str([r["author"] for r in rows]))

print("\n[7] shift_summary — 판정 이력이 없어도 죽지 않는가")
summ = osh.shift_summary(DB, hours=8, sla_min=30)
check("counts/sla 키 존재", {"counts", "sla"} <= set(summ), str(list(summ)))
check("빈 DB 에서도 예외 없음", isinstance(summ.get("arrived", 0), int), str(summ.get("arrived")))

md = osh.handover_markdown(summ, author="홍길동", note="메모")
check("인수인계서 마크다운 생성", isinstance(md, str) and len(md) > 20, f"{len(md)}자")
check("작성자가 문서에 포함", "홍길동" in md)

print("\n[8] 존재하지 않는 DB 경로 — 조용히 빈 결과")
bad = str(Path(tempfile.gettempdir()) / "선택테스트_없는폴더" / "none.db")
check("recent_handovers 안전", osh.recent_handovers(bad) == [])
check("shift_summary 안전", isinstance(osh.shift_summary(bad, 8, 30), dict))

for suf in ("", "-wal", "-shm"):
    try:
        os.remove(DB + suf)
    except OSError:
        pass

print("\n" + "=" * 62)
if fails:
    print(f"❌ 실패 {len(fails)}건: {fails}")
    sys.exit(1)
print("✅ 전체 통과")

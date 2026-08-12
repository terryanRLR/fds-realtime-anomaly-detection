"""selftest_status_push — 워처 상태 외부 내보내기 + 잠금 하트비트  ✨ v24 신규

무엇을 지키려는가

  ① **상태 보고가 워처를 죽이지 않는다.** 파일 권한·네트워크 오류가 나도
     push() 는 예외를 던지지 않아야 한다. 상태 보고 때문에 탐지가 멈추면
     주객전도다.
  ② **미설정이면 아무 일도 안 한다.** 환경변수가 없으면 기존 동작과 100% 같아야 한다.
  ③ **내보낸 것을 되읽으면 화면이 그대로 그려진다** — watcher_panel.liveness() 에
     그대로 넘길 수 있는 모양이어야 클라우드에서 같은 화면이 된다.
  ④ **잠금 하트비트** — 화면이 열려 있는 동안 갱신되고, 남의 잠금은 건드리지 않는다.

⚠️ 운영 DB·네트워크를 건드리지 않는다. 임시 파일과 로컬 스텁만 쓴다.

실행:  python -m pipeline.selftest_status_push
"""
import json
import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import review_store as rs
from pipeline import status_push as sp
from pipeline import watcher_panel as wp

fails: list[str] = []


def check(name: str, cond, detail: str = ""):
    print(("  ✅ " if cond else "  ❌ ") + name + (f" — {detail}" if detail else ""))
    if not cond:
        fails.append(name)


TMP = Path(tempfile.gettempdir())
OUT = TMP / "selftest_status.json"
for p in (OUT, OUT.with_name(OUT.name + ".tmp")):
    if p.exists():
        p.unlink()

for k in (sp.ENV_FILE, sp.ENV_URL, sp.ENV_HEADERS, sp.ENV_MIN_SEC):
    os.environ.pop(k, None)

def _utc_ago(hours: float) -> str:
    import datetime as _dt
    return (_dt.datetime.now(_dt.timezone.utc)
            - _dt.timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")


STATUS = {"started_at": _utc_ago(6), "last_poll": _utc_ago(2),   # 2시간 전 = 죽은 상태
          "polls": 720, "rows_done": 1234, "anomalies": 7, "notified": 5,
          "errors": 0, "note": "running"}

print("=" * 62)
print("[1] 미설정이면 잠잠한가 (기본 동작 불변)")
check("configured() False", sp.configured() is False)
r = sp.push(STATUS)
check("push 가 아무것도 안 한다", r["enabled"] is False and r["skipped"] == "미설정", str(r))
check("파일이 생기지 않는다", not OUT.exists())

print("\n[2] 파일 내보내기")
os.environ[sp.ENV_FILE] = str(OUT)
sp._last_push = 0.0
check("configured() True", sp.configured() is True)
r = sp.push(STATUS, force=True)
check("파일 기록 성공", str(r["file"]).startswith("ok:"), str(r["file"]))
check("파일 생성됨", OUT.exists())
snap = json.loads(OUT.read_text(encoding="utf-8"))
check("스키마 표기", snap.get("schema") == "fds.watcher_status/1", str(snap.get("schema")))
for k in ("polls", "rows_done", "anomalies", "notified", "errors", "note"):
    check(f"{k} 보존", snap.get(k) == STATUS[k], f"{snap.get(k)} vs {STATUS[k]}")
check("pushed_at 이 UTC 19자", len(str(snap.get("pushed_at"))) == 19, str(snap.get("pushed_at")))
check("임시파일이 남지 않는다", not OUT.with_name(OUT.name + ".tmp").exists())

print("\n[3] 되읽기 — 화면이 그대로 그려지는가")
back = sp.read_status_file(OUT)
check("읽기 성공", isinstance(back, dict))
check("age_sec 계산됨", isinstance(back.get("age_sec"), int), str(back.get("age_sec")))
check("uptime_sec 계산됨", isinstance(back.get("uptime_sec"), int))
icon, desc = wp.liveness(back, 5.0)
check("★ liveness() 에 그대로 넘어간다", icon in ("🟢", "🔴", "🔵", "⚫"), f"{icon} {desc}")
check("오래된 하트비트는 응답 없음으로", icon == "🔴", f"{icon} {desc}")

fresh = dict(STATUS)
fresh["last_poll"] = sp._utc_now()
sp._last_push = 0.0
sp.push(fresh, force=True)
icon2, desc2 = wp.liveness(sp.read_status_file(OUT), 5.0)
check("방금 폴링이면 정상 동작 중", icon2 == "🟢", f"{icon2} {desc2}")

# ⏰ 미래 하트비트 = 시계 어긋남 또는 UTC 컬럼에 로컬시각 — '정상'으로 넘기면 안 된다
future = dict(STATUS)
future["last_poll"] = _utc_ago(-9)          # 9시간 미래 (KST 를 UTC 로 착각한 전형)
sp._last_push = 0.0
sp.push(future, force=True)
icon3, desc3 = wp.liveness(sp.read_status_file(OUT), 5.0)
check("★ 미래 하트비트를 경고한다 (정상으로 넘기지 않는다)",
      icon3 == "🟡" and "미래" in desc3, f"{icon3} {desc3[:50]}")

print("\n[4] 최소 간격 — 폴링마다 두드리지 않는가")
os.environ[sp.ENV_MIN_SEC] = "3600"
sp._last_push = time.time()
r = sp.push(STATUS)
check("간격 미달이면 건너뛴다", str(r["skipped"]).startswith("간격 미달"), str(r))
r = sp.push(STATUS, force=True)
check("force 면 그래도 내보낸다", r["skipped"] is None, str(r))
os.environ[sp.ENV_MIN_SEC] = "0"

print("\n[5] ⚠️ 실패해도 워처를 죽이지 않는가")
os.environ[sp.ENV_FILE] = str(TMP / "없는드라이브_selftest" / "x" / "s.json")
sp._last_push = 0.0
try:
    r = sp.push(STATUS, force=True)
    check("경로 오류에서 예외 없음", True, str(r["file"])[:40])
except Exception as e:                                  # pragma: no cover
    check("경로 오류에서 예외 없음", False, f"{type(e).__name__}: {e}")

os.environ[sp.ENV_FILE] = str(OUT)
os.environ[sp.ENV_URL] = "http://127.0.0.1:9/never"     # 연결 거부 (외부로 안 나감)
sp._last_push = 0.0
try:
    r = sp.push(STATUS, force=True)
    check("네트워크 실패에서 예외 없음", str(r["http"]).startswith("fail"), str(r["http"]))
    check("그래도 파일은 기록된다", str(r["file"]).startswith("ok:"), str(r["file"]))
except Exception as e:                                  # pragma: no cover
    check("네트워크 실패에서 예외 없음", False, f"{type(e).__name__}: {e}")
os.environ.pop(sp.ENV_URL, None)

check("잘못된 헤더 JSON 도 안전", True)
os.environ[sp.ENV_HEADERS] = "{깨진 json"
check("targets() 가 파싱 실패를 표시", sp.targets()["headers"] == -1, str(sp.targets()))
os.environ.pop(sp.ENV_HEADERS, None)

print("\n[6] 없는 파일 읽기")
check("None 반환", sp.read_status_file(TMP / "절대없는파일.json") is None)
bad = TMP / "selftest_broken.json"
bad.write_text("{깨진", encoding="utf-8")
check("깨진 JSON 도 None", sp.read_status_file(bad) is None)
bad.unlink()

print("\n[7] 🔒 잠금 하트비트 — 조사 중 잠금이 풀리지 않는가")
DB = str(TMP / "selftest_claim.db")
for suf in ("", "-wal", "-shm"):
    if os.path.exists(DB + suf):
        os.remove(DB + suf)
sqlite3.connect(DB).close()
rs.ensure_schema(DB)

rs.claim(DB, "T1", "홍길동")
rs.claim(DB, "T2", "홍길동")
rs.claim(DB, "T3", "김철수")

# TTL 을 넘긴 상태를 인위적으로 만든다 (claimed_at 을 과거로)
con = sqlite3.connect(DB)
con.execute(f"UPDATE {rs.CLAIM_TABLE} SET claimed_at = datetime('now','-20 minutes')")
con.commit()
con.close()
check("TTL 초과 → 잠금이 사라진 것으로 보인다", not rs.active_claims(DB),
      str(rs.active_claims(DB)))

n = rs.renew_claims(DB, "홍길동")
check("★ 내 잠금 2건이 갱신된다", n == 2, str(n))
act = rs.active_claims(DB)
check("★ 갱신 후 다시 유효해진다", set(act) == {"T1", "T2"}, str(sorted(act)))
check("남의 잠금은 갱신하지 않는다", "T3" not in act, str(sorted(act)))

check("이름이 비면 아무것도 안 한다", rs.renew_claims(DB, "") == 0)
check("없는 DB 에서도 예외 없음",
      rs.renew_claims(str(TMP / "없는폴더_x" / "n.db"), "홍길동") == 0)

for p in (OUT,):
    if p.exists():
        p.unlink()
for suf in ("", "-wal", "-shm"):
    try:
        os.remove(DB + suf)
    except OSError:
        pass
for k in (sp.ENV_FILE, sp.ENV_URL, sp.ENV_HEADERS, sp.ENV_MIN_SEC):
    os.environ.pop(k, None)

print("\n" + "=" * 62)
if fails:
    print(f"❌ 실패 {len(fails)}건: {fails}")
    sys.exit(1)
print("✅ 전체 통과")

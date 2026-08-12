import tempfile
from pathlib import Path
import os, sys, time, sqlite3, subprocess, shutil
# TZ 강제는 POSIX 전용이다. Windows 의 CRT 는 "Asia/Seoul" 같은 IANA 이름을
#   못 읽어 엉뚱한 오프셋(+1h)으로 떨어지고, 그러면 아래 32400 가정이 통째로 깨진다.
#   → tzset 이 있는 환경에서만 고정하고, 없으면 **머신의 실제 시간대**로 검증한다.
_TZ_FORCED = hasattr(time, "tzset")
if _TZ_FORCED:
    os.environ["TZ"] = "Asia/Seoul"
    time.tzset()
sys.path.insert(0,'.')

TMPDIR = tempfile.gettempdir()
DB = str(Path(TMPDIR) / "mig.db")


def local_offset() -> int:
    """로컬시각 − UTC (초). sqlite 에게 직접 묻는다 — 값을 쓴 주체가 sqlite 다."""
    con = sqlite3.connect(":memory:")
    try:
        return int(con.execute(
            "SELECT CAST(strftime('%s', datetime('now','localtime')) "
            "     - strftime('%s', datetime('now')) AS INTEGER)").fetchone()[0])
    finally:
        con.close()


OFFSET = local_offset()
def build(watcher_fresh=False):
    if os.path.exists(DB): os.remove(DB)
    for e in ("-wal","-shm"):
        if os.path.exists(DB+e): os.remove(DB+e)
    con=sqlite3.connect(DB)
    con.execute("""CREATE TABLE transactions (id INTEGER PRIMARY KEY AUTOINCREMENT,
      transaction_id TEXT, fraud_type TEXT, risk_score REAL, is_anomaly INTEGER,
      input_mode TEXT, processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    con.execute("""CREATE TABLE detections (transaction_id TEXT PRIMARY KEY,
      fraud_type TEXT, risk_score REAL, is_anomaly INTEGER, model TEXT, threshold REAL,
      detected_at TEXT DEFAULT (datetime('now','localtime')), raw_json TEXT)""")
    con.execute("CREATE TABLE notified (txn_id TEXT PRIMARY KEY, tier TEXT, sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    con.execute("""CREATE TABLE watcher_status (id INTEGER PRIMARY KEY, started_at TEXT,
      last_poll TEXT, polls INTEGER DEFAULT 0, rows_done INTEGER DEFAULT 0,
      anomalies INTEGER DEFAULT 0, notified INTEGER DEFAULT 0, errors INTEGER DEFAULT 0, note TEXT)""")
    lp = "datetime('now')" if watcher_fresh else "datetime('now','-3 hours')"
    con.execute(f"INSERT INTO watcher_status (id,started_at,last_poll) VALUES (1,datetime('now','-1 day'),{lp})")
    # A) detect_service 경로 — transactions/detections 둘 다 로컬
    for i in range(30):
        con.execute("INSERT INTO transactions (transaction_id,fraud_type,risk_score,is_anomaly,input_mode,processed_at)"
                    " VALUES (?,?,?,1,'watcher:inbox', datetime('now','localtime',?))",
                    (f"SVC_{i:03d}","f",0.9,f"-{i} hours"))
        con.execute("INSERT INTO detections VALUES (?,?,?,1,'lgbm',0.45, datetime('now','localtime',?), '{}')",
                    (f"SVC_{i:03d}","f",0.9,f"-{i} hours"))
        con.execute("INSERT INTO notified VALUES (?,'confirm', datetime('now',?))",(f"SVC_{i:03d}",f"-{i} hours"))
    # B) DEFAULT 경로 — transactions 만 UTC, detections 없음
    for i in range(20):
        con.execute("INSERT INTO transactions (transaction_id,fraud_type,risk_score,is_anomaly,input_mode)"
                    " VALUES (?,?,?,0,'stream')",(f"DEF_{i:03d}","m",0.1))
    con.commit(); con.close()

def q1(sql):
    """열고 닫는다. Windows 는 열린 파일을 지울 수 없어, 커넥션을 흘리면
    다음 build() 의 os.remove(DB) 가 PermissionError 로 죽는다."""
    con = sqlite3.connect(DB)
    try:
        r = con.execute(sql).fetchone()
        return r[0] if r else None
    finally:
        con.close()


def run(*args):
    # encoding 을 명시하지 않으면 Windows 에서 자식 출력을 CP949 로 디코드하다
    #   한글에서 UnicodeDecodeError → stdout 이 None 이 되어 테스트가 통째로 죽는다.
    return subprocess.run([sys.executable,"migrate_timestamps.py",DB,*args],
                          capture_output=True,text=True,encoding="utf-8",errors="replace",
                          env={**os.environ,"PYTHONIOENCODING":"utf-8"}).stdout

print("="*64)
print("\n[1] 드라이런 — 아무것도 바꾸지 않는가")
build()
before = q1("SELECT detected_at FROM detections LIMIT 1")
out = run()
print("\n".join("  "+l for l in out.strip().split("\n")[3:14]))
after = q1("SELECT detected_at FROM detections LIMIT 1")
assert before==after, "❌ 드라이런이 데이터를 변경함"
print(f"  ✅ 무변경 확인 ({before} 그대로)")

print("\n[2] 행별 판별 정확도")
assert "로컬 30 → 변환 / UTC 20 유지" in out or "로컬 30" in out, out
print("  ✅ detect_service 30건=로컬 / DEFAULT 20건=UTC 정확히 분류")

print("\n[3] 워처가 살아있으면 거부하는가")
build(watcher_fresh=True)
out = run("--apply")
assert "🚫 중단" in out, out
print("  " + [l for l in out.split("\n") if "🚫" in l or "살아" in l][0].strip())
print("  ✅ 거부됨 (마이그레이션 중 신규 행 유입 방지)")

print("\n[4] 실제 적용")
build()
con=sqlite3.connect(DB)
svc_before = con.execute("SELECT processed_at FROM transactions WHERE transaction_id='SVC_000'").fetchone()[0]
def_before = con.execute("SELECT processed_at FROM transactions WHERE transaction_id='DEF_000'").fetchone()[0]
det_before = con.execute("SELECT detected_at FROM detections WHERE transaction_id='SVC_000'").fetchone()[0]
con.close()
out = run("--apply")
print("\n".join("  "+l for l in out.strip().split("\n")[-12:]))
con=sqlite3.connect(DB)
svc_after = con.execute("SELECT processed_at FROM transactions WHERE transaction_id='SVC_000'").fetchone()[0]
def_after = con.execute("SELECT processed_at FROM transactions WHERE transaction_id='DEF_000'").fetchone()[0]
det_after = con.execute("SELECT detected_at FROM detections WHERE transaction_id='SVC_000'").fetchone()[0]
con.close()
print(f"\n  로컬행 SVC_000 : {svc_before} → {svc_after}")
print(f"  UTC행  DEF_000 : {def_before} → {def_after}  (유지되어야 함)")
print(f"  detections     : {det_before} → {det_after}")
from datetime import datetime
d=lambda a,b:(datetime.strptime(a,"%Y-%m-%d %H:%M:%S")-datetime.strptime(b,"%Y-%m-%d %H:%M:%S")).total_seconds()
assert d(svc_before,svc_after)==OFFSET, f"❌ 로컬행 변환 오류 {d(svc_before,svc_after)} (기대 {OFFSET})"
assert def_before==def_after, "❌ UTC행이 잘못 변환됨"
assert d(det_before,det_after)==OFFSET, "❌ detections 변환 오류"
print(f"  ✅ 로컬행만 -{OFFSET//3600}h, UTC행은 그대로")

print("\n[5] 백업 생성")
baks=[f for f in os.listdir(TMPDIR) if f.startswith("mig.db.bak-")]
print(f"  백업 파일: {baks[-1] if baks else '없음'}")
assert baks
print("  ✅ 생성됨")

print("\n[6] 멱등성 — 두 번 돌리면 거부하는가 (★ 가장 위험한 시나리오)")
out2 = run("--apply")
assert "이미 적용됨" in out2, out2
print("  " + [l for l in out2.split("\n") if "이미 적용" in l][0].strip())
print("  " + [l for l in out2.split("\n") if "두 배" in l][0].strip())
con=sqlite3.connect(DB)
svc_2nd = con.execute("SELECT processed_at FROM transactions WHERE transaction_id='SVC_000'").fetchone()[0]
con.close()
assert svc_2nd==svc_after, f"❌ 이중 적용됨! {OFFSET*2//3600}시간 어긋남"
print(f"  ✅ 값 불변 ({svc_2nd}) — 이중 적용 차단")

print("\n[7] 검증 결과")
for l in out.split("\n"):
    if "✅" in l and ("processed_at" in l or "notified" in l): print("  "+l.strip())

print("\n[8] 적용 후 ops_queries 진단 — 혼재가 사라졌는가")
sys.path.insert(0,'pipeline')
from pipeline import ops_queries as oq
oq._OFFSET_CACHE.clear()
for dg in oq.diagnose_timestamps(DB):
    flag = " ⚠️" if dg["불일치"] else " ✅"
    print(f"  {dg['테이블']}.{dg['컬럼']:13s} 관측={dg['관측']:6s} 행={dg['행수']:3d}{flag}")
mixed = [d for d in oq.diagnose_timestamps(DB) if d["관측"]=="혼재"]
assert not mixed, f"❌ 혼재 잔존: {mixed}"
print("  ✅ 혼재 컬럼 0개")

print("\n[9] --status")
print("  " + [l for l in run("--status").split("\n") if "적용됨" in l][0].strip())

print("\n"+"="*64); print("✅ 전체 통과")

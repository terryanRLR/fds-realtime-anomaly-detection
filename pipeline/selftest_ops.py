"""실제 스키마를 그대로 재현해 review_store / ops_queries 를 검증한다.
   핵심: transactions.processed_at 에 UTC 행과 로컬 행을 섞어 넣어
   시간대 정규화가 실제로 동작하는지 본다."""
import tempfile
from pathlib import Path
import os, sys, sqlite3, tempfile, random, time
os.environ["TZ"] = "Asia/Seoul"
try:
    time.tzset()
except AttributeError:
    pass
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pipeline import review_store as rs
from pipeline import ops_queries as oq

DB = str(Path(tempfile.gettempdir()) / "test_fds.db")
if os.path.exists(DB):
    os.remove(DB)

con = sqlite3.connect(DB)
con.execute("PRAGMA journal_mode=WAL")
# detect_service.py 와 동일한 DDL
con.execute("""CREATE TABLE transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, transaction_id TEXT, fraud_type TEXT,
    risk_score REAL, is_anomaly INTEGER DEFAULT 0, input_mode TEXT,
    true_label TEXT, processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
con.execute("""CREATE TABLE notified (
    txn_id TEXT PRIMARY KEY, tier TEXT, sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
con.execute("""CREATE TABLE detections (
    transaction_id TEXT PRIMARY KEY, fraud_type TEXT, risk_score REAL,
    is_anomaly INTEGER, model TEXT, threshold REAL,
    detected_at TEXT DEFAULT (datetime('now','localtime')), raw_json TEXT)""")
con.execute("""CREATE TABLE watcher_status (
    id INTEGER PRIMARY KEY, started_at TEXT, last_poll TEXT, polls INTEGER DEFAULT 0,
    rows_done INTEGER DEFAULT 0, anomalies INTEGER DEFAULT 0, notified INTEGER DEFAULT 0,
    errors INTEGER DEFAULT 0, note TEXT)""")
con.execute("INSERT INTO watcher_status (id, started_at, last_poll, polls, rows_done, "
            "anomalies, notified, errors, note) VALUES "
            "(1, datetime('now','-2 hours'), datetime('now'), 1440, 8800, 60, 45, 0, '')")

random.seed(7)
types = list("abcdefghijkl")
for i in range(60):
    tid = f"TXN_{i:04d}"
    score = round(random.random(), 4)
    anom = 1 if score >= 0.45 else 0
    ft = random.choice(types) if anom else "m"
    # 🔥 여기가 핵심: 절반은 detect_service 방식(로컬시각 문자열),
    #    절반은 컬럼 생략(DEFAULT CURRENT_TIMESTAMP = UTC) → 한 컬럼에 두 시간대
    if i % 2 == 0:
        con.execute(
            "INSERT INTO transactions (transaction_id, fraud_type, risk_score, "
            "is_anomaly, input_mode, processed_at) VALUES (?,?,?,?,?, "
            "datetime('now','localtime'))", (tid, ft, score, anom, "watcher:inbox"))
    else:
        con.execute(
            "INSERT INTO transactions (transaction_id, fraud_type, risk_score, "
            "is_anomaly, input_mode) VALUES (?,?,?,?,?)",
            (tid, ft, score, anom, "watcher:inbox"))
    con.execute("INSERT INTO detections VALUES (?,?,?,?,?,?,datetime('now','localtime'),?)",
                (tid, ft, score, anom, "👁 워처 · lgbm", 0.45,
                 '{"Amount": 120000, "Channel": "MOBILE"}'))
    if anom:
        con.execute("INSERT INTO notified VALUES (?,?,datetime('now'))",
                    (tid, "confirm" if score >= 0.8 else "review"))
con.commit()
con.close()

print("=" * 62)
print(f"로컬 오프셋: {oq.tz_offset_seconds(DB)}초 (KST면 32400)")

print("\n[1] 🩺 시간대 진단 — 혼재 컬럼을 잡아내는가?")
mixed_found = False
for d in oq.diagnose_timestamps(DB):
    flag = " ⚠️불일치" if d["불일치"] else ""
    print(f"  {d['테이블']}.{d['컬럼']:13s} 선언={d['선언']:6s} 관측={d['관측']:6s} "
          f"행={d['행수']:3d} 미래행={d['미래행']:3d}{flag}")
    if d["테이블"] == "transactions" and d["관측"] == "혼재":
        mixed_found = True
assert mixed_found, "❌ 혼재 컬럼을 탐지하지 못함"
print("  ✅ transactions.processed_at 혼재 탐지 성공")

print("\n[2] 알림 큐 — 시각이 전부 로컬 '현재'에 근접해야 함 (9시간 튀는 행 없어야)")
q = oq.alert_queue(DB, limit=8)
now_local = time.strftime("%Y-%m-%d %H:%M:%S")
print(f"  현재 로컬시각: {now_local}")
for r in q[:6]:
    print(f"  {r['txn_id']} score={r['risk_score']:.3f} type={r['fraud_type']} "
          f"시각={r['시각']} 판정={r['판정']}")
hours = {int(r["시각"][11:13]) for r in q if r["시각"]}
assert len(hours) <= 2, f"❌ 시각이 흩어짐(정규화 실패): {sorted(hours)}"
print(f"  ✅ 모든 행이 같은 시간대로 정규화됨 (시각대 {sorted(hours)})")

print("\n[3] 판정 기록 (append-only 확인)")
ok, msg = rs.record(DB, "TXN_0000", "fp", reason="legit_customer",
                    reviewer="김검토", memo="본인 확인 완료",
                    snapshot={"risk_score": 0.62, "tier": "review",
                              "fraud_type": "f", "th_review": 0.45,
                              "th_confirm": 0.80, "model": "lgbm"})
print(" ", msg)
ok2, msg2 = rs.record(DB, "TXN_0000", "tp", reviewer="박팀장",
                      memo="재검토 결과 실제 사기", 
                      snapshot={"risk_score": 0.62, "tier": "review",
                                "fraud_type": "f", "th_review": 0.45})
print(" ", msg2)
h = rs.history(DB, "TXN_0000")
assert len(h) == 2, f"❌ append-only 실패: {len(h)}행"
cur = rs.current(DB, ["TXN_0000"])["TXN_0000"]
assert cur["verdict"] == "tp" and cur["reviewer"] == "박팀장", "❌ 최신 판정이 아님"
print(f"  ✅ 이력 {len(h)}건 보존, 현재판정={cur['verdict']} by {cur['reviewer']}")

print("\n[4] 일괄 판정 + 집계")
batch = []
for i, r in enumerate(oq.alert_queue(DB, limit=40)):
    v = "fp" if i % 3 == 0 else "tp"
    batch.append({"txn_id": r["txn_id"], "verdict": v,
                  "reason": "legit_customer" if v == "fp" else None,
                  "risk_score": r["risk_score"], "fraud_type": r["fraud_type"],
                  "th_review": 0.45, "th_confirm": 0.80, "tier": "review",
                  "alert_ref": r["alert_ref"]})
n, errs = rs.record_many(DB, batch, reviewer="야간조")
print(f"  {n}건 기록, 실패 {len(errs)}건")
print(" ", rs.summary_line(DB))
c = rs.counts(DB)
assert c["total"] > 0 and c["fp_rate"] is not None
print(f"  ✅ 오탐률 {c['fp_rate']*100:.1f}%")

print("\n[5] 큐에서 판정 완료분 제외되는가")
before = len(oq.alert_queue(DB, limit=50, only_unreviewed=False))
after = len(oq.alert_queue(DB, limit=50, only_unreviewed=True))
print(f"  전체 {before}건 → 미판정 {after}건")
assert after < before, "❌ 판정 완료분이 큐에 남아있음"
print("  ✅ 제외 동작")

print("\n[6] 사유별 집계")
for r in rs.reason_counts(DB):
    print(f"  {r['사유']:30s} {r['건수']:3d}건 ({r['비중']}%)")

print("\n[7] 차원별 오탐")
for r in oq.fp_by_dimension(DB, "score_bucket")[:6]:
    print(f"  {r['구분']:12s} 정탐 {r['정탐']:3d} 오탐 {r['오탐']:3d} "
          f"오탐률 {r['오탐률']}%")

print("\n[8] 임계값 what-if — 선택 편향 경계가 표시되는가")
w = oq.threshold_whatif(DB, fp_cost=30_000, fn_cost=3_000_000)
print(f"  판정 표본 {w['n_judged']}건 · 신뢰구간 시작 {w['valid_from']}")
print(f"  {w['warning'][:90]}...")
print(f"  {'임계값':>6} {'알림':>5} {'정탐':>5} {'오탐':>5} {'놓침':>5} "
      f"{'정밀도':>7} {'기대비용':>12} 신뢰")
for r in w["rows"][::3]:
    print(f"  {r['임계값']:>6.2f} {r['알림건수']:>5} {r['정탐']:>5} {r['오탐']:>5} "
          f"{r['놓친사기']:>5} {str(r['정밀도']):>7} {r['기대비용']:>12,} "
          f"{'✓' if r['신뢰가능'] else '✗ 데이터없음'}")
assert any(not r["신뢰가능"] for r in w["rows"]), "❌ 편향 구간 표시 안 됨"
print("  ✅ 신뢰 불가 구간이 정확히 표시됨")

print("\n[9] 오탐률 추이")
for r in oq.fp_timeline(DB, "day"):
    print(f"  {r['구간']}  정탐 {r['정탐']:3d} 오탐 {r['오탐']:3d} "
          f"→ 오탐률 {r['오탐률']}%")

print("\n[10] 커버리지 (오탐률의 신뢰도)")
print(" ", oq.coverage(DB))

print("\n[11] 재학습 라벨 내보내기 — batch_analyzer TODO 종결")
ex = rs.export_training_labels(DB)
print(f"  {len(ex)}건 · 예시: {ex[0]}")
assert ex and "features" in ex[0]
print("  ✅ 피처 + 정답라벨 결합 성공")

print("\n[12] 읽기전용 연결이 워처 쓰기를 막지 않는가")
c_reader = oq._conn(DB)
c_reader.execute("SELECT COUNT(*) FROM transactions").fetchone()
c_writer = sqlite3.connect(DB, timeout=5)
c_writer.execute("UPDATE watcher_status SET polls=polls+1 WHERE id=1")
c_writer.commit(); c_writer.close(); c_reader.close()
print("  ✅ 읽기 중에도 쓰기 성공 (WAL + mode=ro)")

print("\n[13] undo")
print(" ", rs.undo_last(DB, "TXN_0000")[1])
assert len(rs.history(DB, "TXN_0000")) == 1

print("\n" + "=" * 62)
print("✅ 전체 통과")

print("\n[14] 커버리지 재검증 — 100%를 넘지 않는가")
cv = oq.coverage(DB)
print(" ", cv)
assert cv["커버리지"] is None or cv["커버리지"] <= 100.0, f"❌ 커버리지 {cv['커버리지']}%"
print("  ✅ 커버리지 정상 범위")

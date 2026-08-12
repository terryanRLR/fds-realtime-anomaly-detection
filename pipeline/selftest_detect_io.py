"""selftest_detect_io — detect_io(탐지 입력·저장) 자체 검증  ✨ v24 신규

무엇을 지키려는가 — v24 에서 닫은 세 가지가 다시 열리지 않게

  ① **원장 이원화** — 탐지는 detections(raw_json 보조) + transactions(알림 원장)
     양쪽에 남아야 한다. 예전엔 detections 에만 써서, 이 앱의 ▶탐지 실행 결과가
     트리아지 큐·탐지 로그·경보 폴링 **어디에도 나타나지 않았다.**
  ② **거래 식별자** — CSV 의 행 번호(`1`,`2`)를 그대로 PK 로 쓰면 다른 파일의
     같은 행 번호끼리 서로 덮어쓴다.
  ③ **계좌 이력 기본값** — 계좌 이력이 0 이면 학습 분포에 없는 '실재하지 않는
     계좌'가 되어, 무엇을 입력해도 정상으로 판정된다.

⚠️ 운영 DB 를 절대 건드리지 않는다. 임시 DB 에 스키마를 직접 만들어 쓴다.

실행:  python -m pipeline.selftest_detect_io
"""
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import detect_io as dio
from pipeline import ops_queries as oq

fails: list[str] = []


def check(name: str, cond, detail: str = ""):
    print(("  ✅ " if cond else "  ❌ ") + name + (f" — {detail}" if detail else ""))
    if not cond:
        fails.append(name)


DB = str(Path(tempfile.gettempdir()) / "selftest_detect_io.db")
for suf in ("", "-wal", "-shm"):
    if os.path.exists(DB + suf):
        os.remove(DB + suf)

# detect_service 와 같은 DDL (원장). detections 는 save_detection 이 만든다.
con = sqlite3.connect(DB)
con.execute("""CREATE TABLE transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, transaction_id TEXT, fraud_type TEXT,
    risk_score REAL, is_anomaly INTEGER DEFAULT 0, input_mode TEXT,
    true_label TEXT, processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
con.commit()
con.close()

ROW = {"ID": "SELFTEST_0001", "Transaction_Amount": -85_000_000, "Channel": "ATM",
       "Fraud_Type": "j", "_input_mode": "manual", "_true_label": "j"}

print("=" * 62)
print("[1] 거래 식별자 — 행 번호가 식별자로 둔갑하지 않는가")
for real in ("TXN-F14A75AE24", "TRAIN_000009", "train_sample_20260804_0"):
    check(f"진짜 ID 보존: {real[:22]}", dio.make_txn_id({"ID": real}, "ops:test_csv") == real)

a = dio.make_txn_id({"ID": 1}, "ops:test_csv")
b = dio.make_txn_id({"ID": 1}, "ops:train_csv")
check("숫자 ID 는 그대로 쓰지 않는다", a != "1", a)
check("행 번호는 뒤에 남아 추적 가능", a.endswith("_1"), a)
check("★ 출처가 다르면 다른 ID (파일 간 충돌 방지)", a != b, f"{a} vs {b}")
for junk in ("", "  ", "nan", "NaN", "None", None):
    g = dio.make_txn_id({"ID": junk}, "ops:manual")
    check(f"쓰레기 ID({junk!r}) → 생성", g.startswith("MANUAL_") and len(g) > 15, g)

print("\n[2] 계좌 이력 기본값 — '실재하지 않는 계좌' 방지")
H = dio.ACCOUNT_HISTORY_DEFAULTS
check("5개 항목", len(H) == 5, str(list(H)))
check("★ one_month_max_amount 가 0 이 아니다",
      H["Account_one_month_max_amount"] > 1_000_000,
      str(H["Account_one_month_max_amount"]))
check("initial_balance 도 현실값", H["Account_initial_balance"] > 1_000_000)
check("전부 숫자", all(isinstance(v, (int, float)) for v in H.values()))
check("화면 표기 정의가 짝을 이룬다", set(dio.ACCOUNT_HISTORY_FIELDS) == set(H),
      str(set(dio.ACCOUNT_HISTORY_FIELDS) ^ set(H)))
check("모든 항목에 (라벨, 도움말, step)",
      all(len(v) == 3 for v in dio.ACCOUNT_HISTORY_FIELDS.values()))

print("\n[3] 원장 이원화 — 두 테이블 모두에 남는가")
tid = dio.save_detection(DB, ROW, "j", 0.95, True, "m.pkl", 0.5, source="ops:manual")
check("txn_id 반환", tid == "SELFTEST_0001", str(tid))
con = sqlite3.connect(DB)
n_det = con.execute("select count(*) from detections where transaction_id=?", (tid,)).fetchone()[0]
n_tx = con.execute("select count(*) from transactions where transaction_id=?", (tid,)).fetchone()[0]
mode = con.execute("select input_mode from transactions where transaction_id=?", (tid,)).fetchone()[0]
truth = con.execute("select true_label from transactions where transaction_id=?", (tid,)).fetchone()[0]
con.close()
check("detections 에 1건", n_det == 1, str(n_det))
check("★ transactions(알림 원장)에도 1건", n_tx == 1, str(n_tx))
check("출처가 남는다", mode == "ops:manual", str(mode))
check("정답 라벨 보존", truth == "j", str(truth))

print("\n[4] 관제 화면에서 보이는가 (ops_queries 경유)")
q = oq.alert_queue(DB, limit=50, min_score=-1.0, only_unreviewed=False)
check("★ 알림 큐에 뜬다", any(r["txn_id"] == tid for r in q), f"{len(q)}건")
raw = oq.get_raw_row(DB, tid)
check("원본 피처 복원", bool(raw) and raw.get("Channel") == "ATM", str(raw)[:50])
feed = oq.live_feed(DB, limit=10, only_anomaly=True)
check("실시간 피드에 뜬다", any(r["txn_id"] == tid for r in feed))

print("\n[5] 재탐지 — 원장은 append, detections 는 upsert")
dio.save_detection(DB, ROW, "j", 0.97, True, "m.pkl", 0.5, source="ops:manual")
con = sqlite3.connect(DB)
n_det = con.execute("select count(*) from detections where transaction_id=?", (tid,)).fetchone()[0]
n_tx = con.execute("select count(*) from transactions where transaction_id=?", (tid,)).fetchone()[0]
score = con.execute("select risk_score from detections where transaction_id=?", (tid,)).fetchone()[0]
con.close()
check("transactions 는 2줄(append)", n_tx == 2, str(n_tx))
check("detections 는 1줄(최신값)", n_det == 1 and abs(score - 0.97) < 1e-9,
      f"{n_det}줄 · {score}")

print("\n[6] 중복 거래가 큐를 깨뜨리지 않는가")
#   원장이 append-only 라 같은 txn_id 가 여러 줄일 수 있다. 화면은 위젯 key 가
#   겹쳐 예외로 죽으므로, 조회 계층에서 최신 1줄만 남겨야 한다.
q = oq.alert_queue(DB, limit=50, min_score=-1.0, only_unreviewed=False)
ids = [r["txn_id"] for r in q]
check("★ 같은 거래는 한 줄만", len(ids) == len(set(ids)), str(ids))

print("\n[7] 시각 — 두 테이블이 같은 UTC 를 쓰는가")
con = sqlite3.connect(DB)
d_at = con.execute("select detected_at from detections where transaction_id=?", (tid,)).fetchone()[0]
t_at = con.execute("select processed_at from transactions where transaction_id=? order by id desc",
                   (tid,)).fetchone()[0]
now_utc = con.execute("select datetime('now')").fetchone()[0]
con.close()
check("detections 와 transactions 시각 동일", d_at == t_at, f"{d_at} vs {t_at}")
check("UTC 로 기록(현재와 2분 이내)", abs(
    (sqlite3.connect(":memory:").execute(
        "select strftime('%s',?) - strftime('%s',?)", (now_utc, d_at)).fetchone()[0] or 0)) < 120,
    f"{d_at} vs now {now_utc}")

print("\n[8] DB 가 없거나 깨져도 죽지 않는가")
bad = str(Path(tempfile.gettempdir()) / "없는폴더_selftest" / "x.db")
check("save_detection 이 None 반환(예외 없음)",
      dio.save_detection(bad, ROW, "j", 0.5, True, "m", 0.5) is None)

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

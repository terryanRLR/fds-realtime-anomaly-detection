"""detections 에만 남아 원장에서 누락된 탐지를 transactions 로 소급 적재한다.

왜 필요한가
  detect_io.save_detection(v24 이전)과 dashboard.py._save_detection_to_db 는
  detections 에만 썼다. 그런데 관제 화면이 '알림 원장'으로 읽는 것은 transactions
  다(pipeline/ops_queries.py:270 주석). 그래서 그 시절 ▶탐지 실행으로 만든 건들은
  트리아지 큐·탐지 로그 목록·경보 폴링 어디에도 나오지 않는다 —
  **저장은 됐는데 화면에서 도달할 수 없는 상태**로 남아 있다.

  v24 부터는 save_detection 이 두 테이블에 모두 쓰므로 새 탐지는 문제가 없다.
  이 스크립트는 **그 이전에 갇힌 과거분**만 꺼내온다.

무엇을 하지 않는가
  · detections 를 지우거나 고치지 않는다 (읽기만 한다)
  · 이미 원장에 있는 거래는 건드리지 않는다
  · transaction_id 가 비었거나 숫자 한 자리인 쓰레기 행은 기본으로 제외한다
    (구 대시보드가 CSV 의 ID 컬럼을 그대로 PK 로 써서 생긴 것들)

사용법
  python -m tools.backfill_ops_ledger                      # 미리보기(기본)
  python -m tools.backfill_ops_ledger --days 3             # 최근 3일만
  python -m tools.backfill_ops_ledger --days 3 --apply     # 실제 적재
  python -m tools.backfill_ops_ledger --db other.db --apply

되돌리기
  적재된 행은 input_mode 가 'ops:backfill' 이라 한 줄로 지울 수 있다.
    DELETE FROM transactions WHERE input_mode='ops:backfill';
"""
from __future__ import annotations

import argparse
import sqlite3
import sys

DEFAULT_DB = "fds_results.db"
MARK = "ops:backfill"


def _cols(con, table: str) -> set[str]:
    try:
        return {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
    except Exception:
        return set()


def find_orphans(con, days: int | None, keep_junk: bool) -> list[dict]:
    """원장에 없는 detections 행. detected_at 은 UTC 로 기록돼 있다."""
    q = ("SELECT d.transaction_id, d.fraud_type, d.risk_score, d.is_anomaly, "
         "       d.model, d.threshold, d.detected_at "
         "FROM detections d "
         "LEFT JOIN transactions t ON t.transaction_id = d.transaction_id "
         "WHERE t.transaction_id IS NULL")
    params: list = []
    if days:
        q += " AND d.detected_at > datetime('now', ?)"
        params.append(f"-{int(days)} days")
    q += " ORDER BY d.detected_at"
    rows = con.execute(q, params).fetchall()
    keys = ("transaction_id", "fraud_type", "risk_score", "is_anomaly",
            "model", "threshold", "detected_at")
    out = [dict(zip(keys, r)) for r in rows]
    if not keep_junk:
        out = [r for r in out
               if (r["transaction_id"] or "").strip()
               and not (r["transaction_id"] or "").strip().isdigit()]
    return out


def backfill(db: str = DEFAULT_DB, days: int | None = None,
             apply: bool = False, keep_junk: bool = False) -> int:
    con = sqlite3.connect(db)
    if "transactions" not in {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}:
        print("❌ transactions 테이블이 없습니다 — 워처를 한 번이라도 돌린 DB여야 합니다.")
        con.close()
        return 1

    orphans = find_orphans(con, days, keep_junk)
    if not orphans:
        print("✅ 원장에서 누락된 탐지가 없습니다.")
        con.close()
        return 0

    n_anom = sum(1 for r in orphans if r["is_anomaly"])
    print(f"원장 누락 {len(orphans)}건 (이상거래 {n_anom}건"
          f"{' · 최근 %d일' % days if days else ''})")
    for r in orphans[-15:]:
        print(f"  {r['detected_at']}  {r['transaction_id']:<32} "
              f"{r['fraud_type']}  {r['risk_score']:.4f}"
              f"{'  ⚠이상' if r['is_anomaly'] else ''}")
    if len(orphans) > 15:
        print(f"  … 외 {len(orphans) - 15}건")

    if not apply:
        print("\n미리보기입니다. 실제로 넣으려면 --apply 를 붙이세요.")
        print("⚠️ 적재된 건은 트리아지 큐에 '미판정'으로 나타납니다 — "
              "시연·테스트 탐지가 섞여 있다면 --days 로 범위를 좁히세요.")
        con.close()
        return 0

    cols = _cols(con, "transactions")
    n = 0
    for r in orphans:
        payload = {
            "transaction_id": r["transaction_id"],
            "fraud_type": r["fraud_type"],
            "risk_score": float(r["risk_score"] or 0),
            "is_anomaly": int(r["is_anomaly"] or 0),
            "input_mode": MARK,
            "true_label": "",
            "model": r["model"],
            "threshold": r["threshold"],
            # detected_at 은 UTC — 원장의 processed_at 도 UTC 이므로 그대로 옮긴다
            "processed_at": r["detected_at"],
            "detected_at": r["detected_at"],
        }
        use = {k: v for k, v in payload.items() if k in cols}
        if not use:
            continue
        con.execute(f"INSERT INTO transactions ({', '.join(use)}) "
                    f"VALUES ({', '.join('?' * len(use))})", tuple(use.values()))
        n += 1
    con.commit()
    con.close()
    print(f"\n✅ {n}건을 원장에 적재했습니다 (input_mode='{MARK}').")
    print(f"   되돌리려면: DELETE FROM transactions WHERE input_mode='{MARK}';")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", default=DEFAULT_DB)
    p.add_argument("--days", type=int, default=None, help="최근 N일만 대상")
    p.add_argument("--apply", action="store_true", help="실제로 적재 (없으면 미리보기)")
    p.add_argument("--keep-junk", action="store_true",
                   help="빈 문자열·숫자 한 자리 같은 쓰레기 ID도 포함")
    a = p.parse_args()
    sys.exit(backfill(a.db, a.days, a.apply, a.keep_junk))

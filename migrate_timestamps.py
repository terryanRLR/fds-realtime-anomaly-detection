"""
migrate_timestamps — 시간대 UTC 통일 마이그레이션 (M001)  ✨ v22

무엇을 고치는가
  fds_results.db 는 테이블마다 시간대가 다르고, transactions.processed_at 은
  **한 컬럼 안에** UTC 행과 로컬 행이 섞여 있다.

      watcher_status.started_at/last_poll   datetime('now')             UTC   ✅
      watch_cursor.updated_at               datetime('now')             UTC   ✅
      notified.sent_at                      datetime('now')             UTC   ✅
      detections.detected_at                datetime('now','localtime') LOCAL ❌
      transactions.processed_at (detect_svc) time.strftime()            LOCAL ❌
      transactions.processed_at (DEFAULT)   CURRENT_TIMESTAMP           UTC   ⚠️혼재

  ops_queries 가 조회 시 보정하고 있지만 그건 임시방편이다. 이 스크립트는
  **저장된 값 자체를 UTC 로 통일**하고, 코드 패치와 짝을 이룬다.

행별 시간대 판별 — 추측하지 않는다
  detections.detected_at 은 두 writer(detect_service:722, dashboard:931/948)가
  모두 localtime 을 쓰므로 **예외 없이 로컬**이다. 무조건 변환하면 된다.

  transactions.processed_at 은 애매하지만, detect_service._save_db() 가
  detections 와 transactions 에 **같은 호출 안에서** 쓴다는 사실을 이용한다.
      같은 txn_id 의 detected_at 과 값이 비슷하다  → 로컬 (detect_service 가 씀)
      offset 만큼 차이가 난다                       → UTC  (DEFAULT 가 씀)
      짝이 없다                                     → UTC 로 간주 (DEFAULT 경로)
  '미래인가' 같은 휴리스틱보다 훨씬 견고하다 — 오래된 행에도 통한다.

안전장치 (전부 기본 활성)
  1. **드라이런이 기본** — --apply 를 줘야 실제로 쓴다
  2. **자동 백업** — 쓰기 전 .bak-YYYYmmdd-HHMMSS 복사본 생성
  3. **멱등성** — schema_migrations 에 기록. 두 번 돌리면 거부한다
     (두 번 적용되면 18시간이 어긋나고 원인 추적이 매우 어렵다)
  4. **워처 생존 확인** — 워처가 돌고 있으면 거부. 마이그레이션 중 새 행이
     들어오면 그 행만 옛 규칙으로 쓰여 다시 혼재가 된다
  5. **검증** — 적용 후 재진단해 혼재가 사라졌는지 확인

사용법
    python migrate_timestamps.py fds_results.db            # 드라이런 (권장 첫 실행)
    python migrate_timestamps.py fds_results.db --apply    # 실제 적용
    python migrate_timestamps.py fds_results.db --status   # 적용 이력 확인

⚠️ 반드시 **워처를 멈춘 뒤** 실행하세요.
"""

from __future__ import annotations

import sys
import time
import shutil
import sqlite3
import argparse
from pathlib import Path

MIGRATION_ID = "M001_utc_unify"
MIGRATION_VERSION = "v22"

# 무조건 로컬로 기록되는 컬럼 (writer 가 전부 localtime)
UNCONDITIONAL_LOCAL = [("detections", "detected_at")]
# 행별 판별이 필요한 혼재 컬럼
MIXED = [("transactions", "processed_at")]
# 이미 UTC — 손대지 않는다
ALREADY_UTC = [("notified", "sent_at"), ("watcher_status", "started_at"),
               ("watcher_status", "last_poll"), ("watch_cursor", "updated_at"),
               ("analysis_cache", "captured_at"), ("alert_review", "reviewed_at")]

MATCH_TOLERANCE = 120        # 초. 같은 _save_db 호출이면 2분 이상 벌어지지 않는다
WATCHER_ALIVE_SEC = 120      # last_poll 이 이보다 최근이면 살아있다고 본다


def _conn(db):
    con = sqlite3.connect(str(db), timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    return con


def _tables(con):
    return {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}


def _cols(con, t):
    try:
        return {r[1] for r in con.execute(f"PRAGMA table_info({t})")}
    except Exception:
        return set()


def tz_offset(con) -> int:
    """로컬 − UTC (초). sqlite 에게 직접 묻는다 — 값을 쓴 주체가 sqlite 이기 때문."""
    r = con.execute("SELECT CAST(strftime('%s', datetime('now','localtime')) "
                    "         - strftime('%s', datetime('now')) AS INTEGER)").fetchone()
    return int(r[0]) if r and r[0] is not None else 0


# ══════════════════════════════════════════════════════════
# 안전장치
# ══════════════════════════════════════════════════════════

def ensure_migrations_table(con):
    con.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
        id          TEXT PRIMARY KEY,
        applied_at  TEXT NOT NULL,
        offset_sec  INTEGER,
        note        TEXT)""")


def already_applied(con) -> dict | None:
    ensure_migrations_table(con)
    r = con.execute("SELECT id, applied_at, offset_sec, note FROM schema_migrations "
                    "WHERE id=?", (MIGRATION_ID,)).fetchone()
    return dict(zip(("id", "applied_at", "offset_sec", "note"), r)) if r else None


def watcher_alive(con) -> tuple[bool, str]:
    """워처가 돌고 있으면 마이그레이션을 막는다.

    마이그레이션 도중 워처가 새 행을 넣으면 그 행만 옛 규칙(로컬)으로 기록되어
    통일이 깨진다. 게다가 어느 행이 신규인지 사후에 구분할 방법이 없다.
    """
    if "watcher_status" not in _tables(con):
        return False, "워처 상태 테이블 없음"
    r = con.execute(
        "SELECT last_poll, CAST(strftime('%s','now') - strftime('%s',last_poll) "
        "AS INTEGER) FROM watcher_status WHERE id=1").fetchone()
    if not r or r[0] is None:
        return False, "워처 실행 이력 없음"
    age = r[1] if r[1] is not None else 10 ** 9
    if age < WATCHER_ALIVE_SEC:
        return True, f"마지막 폴링 {age}초 전 — 워처가 살아 있습니다"
    return False, f"마지막 폴링 {age//60}분 전 — 정지 상태로 판단"


def backup(db: Path) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dst = db.with_suffix(db.suffix + f".bak-{stamp}")
    shutil.copy2(db, dst)
    # WAL 이 있으면 함께 복사해야 백업이 일관된다
    for ext in ("-wal", "-shm"):
        side = Path(str(db) + ext)
        if side.exists():
            shutil.copy2(side, Path(str(dst) + ext))
    return dst


# ══════════════════════════════════════════════════════════
# 분석
# ══════════════════════════════════════════════════════════

def classify_transactions(con, offset: int) -> dict:
    """transactions.processed_at 을 행별로 판별한다.

    같은 txn_id 의 detections.detected_at(확정 로컬)과 대조:
      차이 ≈ 0        → 로컬
      차이 ≈ offset   → UTC (processed_at 이 UTC 라 로컬보다 offset 만큼 이르다)
    """
    have = _tables(con)
    if "transactions" not in have or "processed_at" not in _cols(con, "transactions"):
        return {"local": [], "utc": [], "orphan": [], "total": 0}
    if "detections" not in have:
        # 대조군이 없다 — 전량을 detect_service 기록(로컬)로 보는 것은 위험하므로
        # 판별 불가로 보고하고 호출부가 결정하게 한다
        n = con.execute("SELECT COUNT(*) FROM transactions "
                        "WHERE processed_at IS NOT NULL").fetchone()[0]
        return {"local": [], "utc": [], "orphan": list(range(n)), "total": n,
                "no_reference": True}

    rows = con.execute("""
        SELECT t.id,
               CAST(strftime('%s', d.detected_at) - strftime('%s', t.processed_at)
                    AS INTEGER) AS diff
        FROM transactions t
        LEFT JOIN detections d ON d.transaction_id = t.transaction_id
        WHERE t.processed_at IS NOT NULL
    """).fetchall()

    local, utc, orphan = [], [], []
    for rid, diff in rows:
        if diff is None:
            orphan.append(rid)                      # detections 짝 없음 → DEFAULT(UTC)
        elif abs(diff) <= MATCH_TOLERANCE:
            local.append(rid)                       # detected_at 과 같은 시각 = 로컬
        elif abs(diff - offset) <= MATCH_TOLERANCE:
            utc.append(rid)                         # offset 차이 = 이미 UTC
        else:
            orphan.append(rid)                      # 설명 불가 → 건드리지 않는다
    return {"local": local, "utc": utc, "orphan": orphan, "total": len(rows)}


def analyze(db: Path) -> dict:
    con = _conn(db)
    off = tz_offset(con)
    have = _tables(con)
    report = {"offset": off, "tables": {}, "applied": already_applied(con)}

    for tbl, col in UNCONDITIONAL_LOCAL:
        if tbl in have and col in _cols(con, tbl):
            n = con.execute(f"SELECT COUNT(*) FROM {tbl} WHERE {col} IS NOT NULL").fetchone()[0]
            sample = con.execute(f"SELECT {col} FROM {tbl} WHERE {col} IS NOT NULL "
                                 f"ORDER BY rowid DESC LIMIT 1").fetchone()
            report["tables"][f"{tbl}.{col}"] = {
                "mode": "unconditional_local", "convert": n, "keep": 0,
                "sample": sample[0] if sample else None}

    for tbl, col in MIXED:
        if tbl in have and col in _cols(con, tbl):
            c = classify_transactions(con, off)
            report["tables"][f"{tbl}.{col}"] = {
                "mode": "mixed", "convert": len(c["local"]), "keep": len(c["utc"]),
                "orphan": len(c["orphan"]), "total": c["total"],
                "no_reference": c.get("no_reference", False),
                "_ids": c["local"]}

    for tbl, col in ALREADY_UTC:
        if tbl in have and col in _cols(con, tbl):
            n = con.execute(f"SELECT COUNT(*) FROM {tbl} WHERE {col} IS NOT NULL").fetchone()[0]
            report["tables"][f"{tbl}.{col}"] = {"mode": "already_utc", "convert": 0,
                                                "keep": n}
    con.close()
    return report


# ══════════════════════════════════════════════════════════
# 적용
# ══════════════════════════════════════════════════════════

def apply(db: Path, report: dict, assume_orphan_utc: bool = True) -> tuple[bool, str]:
    con = _conn(db)
    off = report["offset"]
    if off == 0:
        con.close()
        return False, "로컬 오프셋이 0입니다 — 변환할 것이 없습니다(이미 UTC 환경)"

    ensure_migrations_table(con)
    if already_applied(con):
        con.close()
        return False, "이미 적용된 마이그레이션입니다"

    changed = []
    try:
        con.execute("BEGIN IMMEDIATE")               # 다른 writer 를 잠근다
        for tbl, col in UNCONDITIONAL_LOCAL:
            key = f"{tbl}.{col}"
            if key not in report["tables"]:
                continue
            cur = con.execute(
                f"UPDATE {tbl} SET {col} = datetime({col}, '-{off} seconds') "
                f"WHERE {col} IS NOT NULL")
            changed.append(f"{key}: {cur.rowcount:,}행 변환")

        for tbl, col in MIXED:
            key = f"{tbl}.{col}"
            info = report["tables"].get(key)
            if not info:
                continue
            ids = info.get("_ids") or []
            n = 0
            for i in range(0, len(ids), 500):
                chunk = ids[i:i + 500]
                cur = con.execute(
                    f"UPDATE {tbl} SET {col} = datetime({col}, '-{off} seconds') "
                    f"WHERE id IN ({','.join('?' * len(chunk))})", chunk)
                n += cur.rowcount
            changed.append(f"{key}: {n:,}행 변환 · {info['keep']:,}행 유지(이미 UTC)"
                           + (f" · {info['orphan']:,}행 판별불가(유지)"
                              if info.get("orphan") else ""))

        con.execute(
            "INSERT INTO schema_migrations (id, applied_at, offset_sec, note) "
            "VALUES (?, datetime('now'), ?, ?)",
            (MIGRATION_ID, off, " / ".join(changed)))
        con.commit()
    except Exception as e:
        con.rollback()
        con.close()
        return False, f"적용 실패(롤백됨): {type(e).__name__}: {e}"
    con.close()
    return True, "\n".join("  · " + c for c in changed)


def verify(db: Path) -> list[str]:
    """적용 후 검증.

    🐛 FIX: 초기 구현은 classify_transactions() 를 재사용했는데, 그 분류기는
       **마이그레이션 이전에만** 유효하다. 변환이 끝나면 detections 와
       transactions 가 둘 다 UTC 라 diff≈0 이 되고, 분류기는 그것을 "로컬"로
       읽어 정상 상태를 오류로 보고했다(30건 남았다고 경고).

       변환 후의 정합성 기준은 다르다 — **세 테이블의 시각이 서로 일치하는가**.
       detections·transactions·notified 는 같은 _save_db 호출에서 쓰이므로
       통일이 끝났다면 상호 시차가 0 에 가까워야 한다.
    """
    con = _conn(db)
    have = _tables(con)
    out = []

    def _pair(t1, c1, k1, t2, c2, k2, label):
        if not {t1, t2} <= have:
            return
        r = con.execute(f"""
            SELECT COUNT(*), AVG(ABS(CAST(strftime('%s', a.{c1})
                                        - strftime('%s', b.{c2}) AS INTEGER)))
            FROM {t1} a JOIN {t2} b ON b.{k2} = a.{k1}
            WHERE a.{c1} IS NOT NULL AND b.{c2} IS NOT NULL""").fetchone()
        if not r or not r[0]:
            return
        avg = r[1] or 0
        ok = avg < 3600           # 1시간 미만이면 같은 시간대로 본다
        out.append(f"{'✅' if ok else '⚠️'} {label} 평균 시차 {avg:,.0f}초 "
                   f"({r[0]:,}건 대조)" + ("" if ok else " — 시간대가 여전히 어긋납니다"))

    _pair("detections", "detected_at", "transaction_id",
          "notified", "sent_at", "txn_id", "detections ↔ notified")
    _pair("transactions", "processed_at", "transaction_id",
          "notified", "sent_at", "txn_id", "transactions ↔ notified")
    _pair("detections", "detected_at", "transaction_id",
          "transactions", "processed_at", "transaction_id",
          "detections ↔ transactions")

    # 미래 시각 잔존 확인 — UTC 라면 어떤 행도 현재 UTC 를 넘지 않아야 한다
    for tbl, col in UNCONDITIONAL_LOCAL + MIXED:
        if tbl in have and col in _cols(con, tbl):
            n = con.execute(
                f"SELECT COUNT(*) FROM {tbl} WHERE CAST(strftime('%s',{col}) AS INTEGER) "
                f"> CAST(strftime('%s','now') AS INTEGER) + 60").fetchone()[0]
            if n:
                out.append(f"⚠️ {tbl}.{col} — 미래 시각 {n:,}행 (로컬 잔존 의심)")
            else:
                out.append(f"✅ {tbl}.{col} — 미래 시각 0행")
    con.close()
    return out


# ══════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════

def main(argv=None):
    ap = argparse.ArgumentParser(description="시간대 UTC 통일 마이그레이션")
    ap.add_argument("db", nargs="?", default="fds_results.db")
    ap.add_argument("--apply", action="store_true", help="실제로 적용 (기본은 드라이런)")
    ap.add_argument("--status", action="store_true", help="적용 이력만 확인")
    ap.add_argument("--force", action="store_true", help="워처 생존 확인을 건너뛴다")
    ap.add_argument("--no-backup", action="store_true")
    a = ap.parse_args(argv)

    db = Path(a.db)
    if not db.exists():
        print(f"❌ DB 파일이 없습니다: {db}")
        return 2

    print(f"migrate_timestamps {MIGRATION_VERSION} · {MIGRATION_ID}")
    print(f"DB: {db.resolve()}\n")

    rep = analyze(db)
    off = rep["offset"]
    print(f"로컬 오프셋: {off}초 ({off/3600:+.0f}시간)\n")

    if rep["applied"]:
        ap_ = rep["applied"]
        print(f"✅ 이미 적용됨 — {ap_['applied_at']} UTC (offset {ap_['offset_sec']}초)")
        print(f"   {ap_['note']}")
        if not a.status:
            print("\n두 번 적용하면 시각이 두 배로 어긋납니다. 중단합니다.")
        return 0
    if a.status:
        print("아직 적용되지 않았습니다.")
        return 0

    print("현황")
    for k, v in rep["tables"].items():
        if v["mode"] == "already_utc":
            print(f"  {k:34s} 이미 UTC · {v['keep']:,}행 (변경 없음)")
        elif v["mode"] == "unconditional_local":
            print(f"  {k:34s} 로컬 확정 · {v['convert']:,}행 → UTC 변환"
                  f"  (예: {v['sample']})")
        else:
            extra = f" · 판별불가 {v['orphan']:,}" if v.get("orphan") else ""
            print(f"  {k:34s} 혼재 · 로컬 {v['convert']:,} → 변환 / "
                  f"UTC {v['keep']:,} 유지{extra}")
            if v.get("no_reference"):
                print("      ⚠️ detections 테이블이 없어 대조 불가 — 전량 유지합니다")

    total = sum(v.get("convert", 0) for v in rep["tables"].values())
    if not total:
        print("\n변환할 행이 없습니다.")
        return 0

    if not a.apply:
        print(f"\n🔍 드라이런 — 실제로는 아무것도 바꾸지 않았습니다.")
        print(f"   {total:,}행이 변환 대상입니다.")
        print(f"   적용하려면:  python {Path(__file__).name} {a.db} --apply")
        return 0

    con = _conn(db)
    alive, why = watcher_alive(con)
    con.close()
    if alive and not a.force:
        print(f"\n🚫 중단 — {why}")
        print("   마이그레이션 중 워처가 새 행을 넣으면 그 행만 옛 규칙으로 기록되어")
        print("   통일이 다시 깨집니다. 워처를 멈춘 뒤 다시 실행하세요.")
        print("   (정말 강행하려면 --force)")
        return 3
    print(f"\n워처 상태: {why}")

    if not a.no_backup:
        b = backup(db)
        print(f"💾 백업 생성: {b.name}")

    ok, msg = apply(db, rep)
    print(f"\n{'✅ 적용 완료' if ok else '❌ 실패'}")
    print(msg)
    if ok:
        print("\n검증")
        for line in verify(db):
            print("  " + line)
        print("\n다음 단계: 코드 패치를 적용해야 앞으로 들어오는 행도 UTC 로 기록됩니다.")
        print("  detect_service.py · dashboard.py 의 datetime('now','localtime') → datetime('now')")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

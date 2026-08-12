"""
audit_store — 발송 감사 로그의 영속 저장소  ✨ v24 신규

왜 필요한가
  v24 에서 "기록이 빠지는 발송 경로"는 없앴지만, 기록은 여전히 세션 상태에만
  있었다. 새로고침 한 번이면 사라진다. "외부로 나간 것은 회수할 수 없다"가
  이 로그의 존재 이유인데, 휘발성 로그는 감사 자료로 쓸 수 없다.
  → 같은 DB(fds_results.db)에 테이블 하나를 둔다.

설계 원칙 (review_store 와 동일한 규칙)
  · 어떤 실패도 밖으로 던지지 않는다. DB 가 없거나 잠겨 있어도 **발송을 막지
    않는다** — 감사 기록 실패가 통보 자체를 막으면 주객이 전도된다.
    대신 (ok, msg) 로 알려 호출부가 화면에 표시할 수 있게 한다.
  · 시각은 UTC 로 저장한다. 표시 직전에만 로컬로 되돌린다(ops_queries 와 동일).
  · Streamlit 무관 — CLI·테스트에서 그대로 쓸 수 있다.

삭제에 대하여
  감사 로그를 지우는 행위 자체가 감사 대상이다. 그래서 purge() 는 지운 뒤
  **'몇 건을 누가 언제 지웠는지'를 같은 테이블에 한 줄 남긴다.** 전체 삭제를
  해도 그 흔적은 남는다 — 로그가 조용히 비어 있는 것과 "2026-08-09 에 홍길동이
  120건을 지웠다"가 남아 있는 것은 완전히 다른 이야기다.
"""
from __future__ import annotations

import datetime as _dt
import logging
import sqlite3
from pathlib import Path

log = logging.getLogger("audit_store")

AUDIT_STORE_VERSION = "v1"
DEFAULT_DB = "fds_results.db"
TABLE = "notify_audit"

_DDL = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    sent_at     TEXT    NOT NULL,          -- UTC 'YYYY-MM-DD HH:MM:SS'
    ok          INTEGER NOT NULL DEFAULT 0,
    channel     TEXT,                      -- slack | email | audit(내부 기록)
    txn_id      TEXT,
    fraud_type  TEXT,
    risk_score  REAL,
    recipient   TEXT,
    mask_level  TEXT,
    via         TEXT,                      -- auto | manual | purge
    error       TEXT,
    reviewer    TEXT
)"""

_INDEXES = (
    f"CREATE INDEX IF NOT EXISTS ix_{TABLE}_sent  ON {TABLE}(sent_at)",
    f"CREATE INDEX IF NOT EXISTS ix_{TABLE}_txn   ON {TABLE}(txn_id)",
)

_SCHEMA_DONE: set[str] = set()

_COLS = ("id", "sent_at", "ok", "channel", "txn_id", "fraud_type", "risk_score",
         "recipient", "mask_level", "via", "error", "reviewer")


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _conn(db_path: str | Path) -> sqlite3.Connection:
    con = sqlite3.connect(str(db_path), timeout=5)
    try:
        con.execute("PRAGMA busy_timeout=5000")
    except Exception:
        pass
    return con


def ensure_schema(db_path: str | Path = DEFAULT_DB) -> bool:
    key = str(db_path)
    if key in _SCHEMA_DONE:
        return True
    try:
        con = _conn(db_path)
        con.execute(_DDL)
        for ix in _INDEXES:
            con.execute(ix)
        con.commit()
        con.close()
        _SCHEMA_DONE.add(key)
        return True
    except Exception as e:
        log.warning(f"감사 로그 스키마 생성 실패: {e}")
        return False


def table_exists(db_path: str | Path = DEFAULT_DB) -> bool:
    """읽기 경로는 테이블을 만들지 않는다 — '아직 한 번도 발송이 없었다'와
    '연결이 안 됐다'를 구분할 수 있어야 하기 때문(analysis_store 와 같은 규칙)."""
    try:
        con = _conn(db_path)
        r = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                        (TABLE,)).fetchone()
        con.close()
        return bool(r)
    except Exception:
        return False


def append(db_path: str | Path, *, ok: bool, channel: str, fraud_type=None,
           risk_score=0, recipient: str = "", mask_level: str = "",
           via: str = "auto", txn_id: str = "", error: str = "",
           reviewer: str = "") -> tuple[bool, str]:
    """발송 시도 1건 기록. **실패해도 예외를 던지지 않는다** — 감사 기록 실패가
    통보를 막으면 안 된다."""
    if not ensure_schema(db_path):
        return False, "감사 로그 테이블을 만들 수 없습니다"
    try:
        con = _conn(db_path)
        con.execute(
            f"INSERT INTO {TABLE} (sent_at, ok, channel, txn_id, fraud_type, "
            f"risk_score, recipient, mask_level, via, error, reviewer) "
            f"VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (_utc_now(), int(bool(ok)), str(channel or ""), str(txn_id or ""),
             str(fraud_type or ""), float(risk_score or 0), str(recipient or ""),
             str(mask_level or ""), str(via or ""), str(error or "")[:500],
             str(reviewer or "")))
        con.commit()
        con.close()
        return True, "기록됨"
    except Exception as e:
        log.warning(f"감사 로그 기록 실패: {e}")
        return False, f"기록 실패: {e}"


def recent(db_path: str | Path = DEFAULT_DB, limit: int = 50,
           since_hours: int | None = None, channel: str | None = None,
           only_failed: bool = False) -> list[dict]:
    """최신순 기록. 시각은 UTC 그대로 — 표시 직전에 로컬로 바꾼다."""
    if not table_exists(db_path):
        return []
    q = f"SELECT {', '.join(_COLS)} FROM {TABLE} WHERE 1=1"
    params: list = []
    if since_hours:
        q += " AND sent_at > datetime('now', ?)"
        params.append(f"-{int(since_hours)} hours")
    if channel:
        q += " AND channel = ?"
        params.append(channel)
    if only_failed:
        q += " AND ok = 0"
    q += " ORDER BY id DESC LIMIT ?"
    params.append(int(limit))
    try:
        con = _conn(db_path)
        rows = con.execute(q, params).fetchall()
        con.close()
        return [dict(zip(_COLS, r)) for r in rows]
    except Exception as e:
        log.debug(f"감사 로그 조회 실패: {e}")
        return []


def stats(db_path: str | Path = DEFAULT_DB) -> dict:
    empty = {"rows": 0, "ok": 0, "fail": 0, "oldest": None, "newest": None}
    if not table_exists(db_path):
        return empty
    try:
        con = _conn(db_path)
        r = con.execute(
            f"SELECT COUNT(*), SUM(ok), MIN(sent_at), MAX(sent_at) FROM {TABLE}"
        ).fetchone()
        con.close()
        n, n_ok = int(r[0] or 0), int(r[1] or 0)
        return {"rows": n, "ok": n_ok, "fail": n - n_ok,
                "oldest": r[2], "newest": r[3]}
    except Exception as e:
        log.debug(f"감사 로그 통계 실패: {e}")
        return empty


def count_matching(db_path: str | Path = DEFAULT_DB,
                   before_days: int | None = None) -> int:
    """삭제 **전에** 몇 건이 지워질지 세어 화면에 보여주기 위한 함수.
    '몇 건이 사라지는지 모르는 채로 누르는 삭제'를 만들지 않기 위해 존재한다."""
    if not table_exists(db_path):
        return 0
    q = f"SELECT COUNT(*) FROM {TABLE} WHERE via <> 'purge'"
    params: list = []
    if before_days is not None:
        q += " AND sent_at < datetime('now', ?)"
        params.append(f"-{int(before_days)} days")
    try:
        con = _conn(db_path)
        n = int(con.execute(q, params).fetchone()[0] or 0)
        con.close()
        return n
    except Exception as e:
        log.debug(f"감사 로그 카운트 실패: {e}")
        return 0


def purge(db_path: str | Path = DEFAULT_DB, before_days: int | None = None,
          reviewer: str = "", keep_failed: bool = False) -> tuple[int, str]:
    """감사 로그 삭제. (지운 건수, 메시지) 반환.

    before_days=None 이면 **전체 삭제**.

    ⚠️ 삭제 자체를 기록한다
      지운 뒤 같은 테이블에 `via='purge'` 한 줄을 남긴다. 로그가 조용히 비어
      있는 것과 "언제 누가 몇 건을 지웠다"가 남는 것은 전혀 다른 이야기다.
      그 흔적 행은 다음 삭제 대상에서도 제외된다(count_matching 참조).
    """
    if not table_exists(db_path):
        return 0, "삭제할 기록이 없습니다"
    where = "via <> 'purge'"
    params: list = []
    if before_days is not None:
        where += " AND sent_at < datetime('now', ?)"
        params.append(f"-{int(before_days)} days")
    if keep_failed:
        where += " AND ok = 1"
    try:
        con = _conn(db_path)
        n = int(con.execute(f"SELECT COUNT(*) FROM {TABLE} WHERE {where}",
                            params).fetchone()[0] or 0)
        if not n:
            con.close()
            return 0, "조건에 맞는 기록이 없습니다"
        con.execute(f"DELETE FROM {TABLE} WHERE {where}", params)
        scope = "전체" if before_days is None else f"{int(before_days)}일 이전"
        if keep_failed:
            scope += " (실패 기록 보존)"
        con.execute(
            f"INSERT INTO {TABLE} (sent_at, ok, channel, via, error, reviewer) "
            f"VALUES (?,?,?,?,?,?)",
            (_utc_now(), 1, "audit", "purge",
             f"감사 로그 {n}건 삭제 — 범위: {scope}", str(reviewer or "")))
        con.commit()
        con.close()
        return n, f"🧹 {n}건을 삭제했습니다 (삭제 기록은 로그에 남습니다)"
    except Exception as e:
        log.warning(f"감사 로그 삭제 실패: {e}")
        return 0, f"삭제 실패: {e}"


def to_local(utc_str: str | None, db_path: str | Path = DEFAULT_DB) -> str:
    """UTC 문자열 → 로컬 표시용. ops_queries 의 규칙을 그대로 재사용한다."""
    if not utc_str:
        return ""
    try:
        try:
            from pipeline import ops_queries as _oq
        except ImportError:                            # pragma: no cover
            import ops_queries as _oq
        return _oq.to_local(utc_str, _oq.tz_offset_seconds(db_path))
    except Exception:
        return str(utc_str)


# ── CLI 확인용:  python -m pipeline.audit_store [db] ──
if __name__ == "__main__":                             # pragma: no cover
    import sys
    db = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DB
    s = stats(db)
    print(f"audit_store {AUDIT_STORE_VERSION} · DB={db}")
    print(f"  기록 {s['rows']}건 (성공 {s['ok']} · 실패 {s['fail']})")
    print(f"  {s['oldest']} ~ {s['newest']} UTC")
    for r in recent(db, limit=10):
        print(f"  {'✅' if r['ok'] else '❌'} {to_local(r['sent_at'], db)} · "
              f"{r['channel']} · {r['txn_id'] or '-'} · {r['via']}"
              f"{' · ' + r['error'] if r['error'] else ''}")

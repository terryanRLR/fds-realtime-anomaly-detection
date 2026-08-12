"""
review_store — 오탐/정탐 판정 저장소 (alert_review 테이블)  ✨ v19 신규

배경
  batch_analyzer.py:491 이 이렇게 적어두고 3개월째 방치돼 있었다.
    "장기: 해당 배치의 오탐/미탐 여부를 라벨링하여 모델 재학습 데이터로 축적하십시오."
  즉 **담당자가 '이 알림은 오탐이었다'고 남길 곳이 DB 어디에도 없다.**
  운영 오탐률을 아무도 모르고, 임계값은 검증셋(정적 라벨) 기준으로만 조정돼 왔다.
  이 모듈이 그 구멍을 메운다.

설계 원칙
  1. **추가 전용(append-only)** — 판정을 UPDATE 하지 않는다. 재판정하면 새 행이 쌓이고
     '현재 판정'은 txn_id 별 최신 행이다.
     ⚠️ 기존 `detections` 테이블은 transaction_id PK + UPSERT라 재탐지하면
        이전 판정이 **소리 없이 덮어써진다.** 감사 대상인 사람의 판정에 그 구조를
        쓰면 안 된다 — 의도적으로 다르게 만들었다.

  2. **판정 시점 스냅샷을 함께 저장** — risk_score / th_review / th_confirm / tier 를
     판정 당시 값으로 박아둔다. 워처 임계값은 watcher_config.json 으로 **핫 리로드**되므로
     (watcher_config.py 참조) th_review=0.45 에서 내린 '오탐' 판정과 0.60 에서 내린
     판정은 서로 비교 불가다. 스냅샷이 없으면 임계값 what-if 시뮬레이터가 전부 거짓말이 된다.

  3. **시각은 전부 UTC** — 이 프로젝트 DB는 UTC 와 localtime 이 테이블마다 섞여 있다
     (transactions.processed_at 은 심지어 writer 에 따라 한 컬럼에 둘 다 들어간다).
     여기서까지 늘리지 않는다. `reviewed_at` 은 sqlite `datetime('now')` = UTC 고정.
     화면 표시용 변환은 ops_queries.to_local() 이 담당한다.

  4. **워처를 막지 않는다** — WAL + busy_timeout, 트랜잭션은 한 문장씩 짧게.
     워처는 무인으로 5초마다 도는 프로세스라 여기서 락을 오래 쥐면 탐지가 밀린다.

  5. **쓰기는 여기에만** — watcher_panel.py 는 "이 모듈은 DB에 절대 쓰지 않는다"를
     문서화된 계약으로 삼고 있다. 그 계약을 깨지 않으려고 쓰기를 별도 파일로 뺐다.

핵심 API
    ensure_schema(db)                          # 최초 1회 (record 가 알아서도 부른다)
    record(db, txn_id, "fp", reason="legit_customer", reviewer="김검토")
    current(db, ["TXN_1","TXN_2"])             # → {txn_id: 최신 판정 dict}
    history(db, "TXN_1")                       # → 판정 이력 전체 (감사용)
    counts(db, since_hours=168)                # → {"fp": 12, "tp": 40, ...}
    export_training_labels(db)                 # → 재학습용 (피처 + 정답라벨)
"""

from __future__ import annotations

import os
import json
import sqlite3
import logging
from pathlib import Path

log = logging.getLogger(__name__)

REVIEW_STORE_VERSION = "v20"
DEFAULT_DB = "fds_results.db"

TABLE = "alert_review"
CLAIM_TABLE = "alert_claim"       # 누가 지금 이 알림을 붙잡고 있나 (동시 판정 방지)
DRAFT_TABLE = "review_draft"      # 판정 중이던 입력 (새로고침에도 살아남게)

# 잠금 유효시간(분). 브라우저를 그냥 닫으면 release 가 오지 않으므로,
# 이 시간이 지난 잠금은 자동으로 무효가 된다 — 안 그러면 알림이 영구히 잠긴다.
CLAIM_TTL_MIN = 15

# ── 판정 값 ────────────────────────────────────────────────
#   tp      정탐 — 실제 사기가 맞았다
#   fp      오탐 — 정상 거래인데 알림이 갔다  ← 이 대시보드의 주인공
#   fn      미탐 제보 — 알림이 안 갔는데 사기였다 (알림 큐가 아니라 사후 제보로 들어온다)
#   unclear 보류 — 판단 불가 / 추가 확인 필요
VERDICTS = ("tp", "fp", "fn", "unclear")

VERDICT_LABEL_KO = {
    "tp": "✅ 정탐", "fp": "🟡 오탐", "fn": "🔴 미탐", "unclear": "⏸ 보류",
}

# 오탐 사유 코드 — 자유 입력만 받으면 집계가 불가능해진다.
#   "왜 오탐이 나는가"를 유형별로 세야 임계값을 올릴지 피처를 고칠지 결정할 수 있다.
FP_REASONS = {
    "legit_customer": "정상 고객 확인됨 (본인 거래)",
    "known_pattern":  "기존 예외 패턴 (해외출장·급여일 등)",
    "test_data":      "테스트/내부 거래",
    "data_error":     "데이터 오류·중복 유입",
    "model_drift":    "모델 오작동 의심 (근거 불명)",
    "rule_overfit":   "룰 과민반응 (rule_checker)",
    "other":          "기타 (메모 참조)",
}

# 판정 당시 알림 등급 — detect_service._TIER_RANK 와 같은 어휘를 쓴다
TIERS = ("none", "review", "single", "confirm")

_SCHEMA_DONE: set[str] = set()      # 프로세스당 1회만 DDL (매 호출 DDL 은 낭비)


# ══════════════════════════════════════════════════════════
# 연결 / 스키마
# ══════════════════════════════════════════════════════════

def _conn(db_path: str | Path, readonly: bool = False) -> sqlite3.Connection:
    """워처와 공존하는 연결. WAL + 넉넉한 busy_timeout 이 핵심이다."""
    db_path = str(db_path)
    if readonly:
        # URI 읽기 전용 — 실수로도 워처의 쓰기를 막지 않는다.
        #   파일이 없으면 sqlite3.OperationalError 가 나므로 호출부가 잡아야 한다.
        con = sqlite3.connect(f"file:{Path(db_path).as_posix()}?mode=ro",
                              uri=True, timeout=5)
    else:
        con = sqlite3.connect(db_path, timeout=30)
    try:
        if not readonly:
            con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA busy_timeout=30000")
    except Exception:
        pass
    return con


_DDL = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    txn_id       TEXT    NOT NULL,
    alert_ref    INTEGER,          -- transactions.id (불변 원장). 못 찾으면 NULL
    verdict      TEXT    NOT NULL, -- tp | fp | fn | unclear
    reason       TEXT,             -- FP_REASONS 코드
    memo         TEXT,
    reviewer     TEXT,
    -- ↓ 판정 '당시' 스냅샷. 나중에 임계값이 바뀌어도 비교 기준이 남는다
    tier         TEXT,
    risk_score   REAL,
    fraud_type   TEXT,
    th_review    REAL,
    th_confirm   REAL,
    model        TEXT,
    source       TEXT,             -- ops_dashboard | api | import | cli
    reviewed_at  TEXT    NOT NULL  -- ⚠ UTC 고정 (datetime('now'))
)
"""

_INDEXES = (
    f"CREATE INDEX IF NOT EXISTS idx_{TABLE}_txn     ON {TABLE}(txn_id)",
    f"CREATE INDEX IF NOT EXISTS idx_{TABLE}_at      ON {TABLE}(reviewed_at)",
    f"CREATE INDEX IF NOT EXISTS idx_{TABLE}_verdict ON {TABLE}(verdict)",
)


# ── 🔒 v20: 동시 판정 방지 · 임시저장 ─────────────────────
#   두 담당자가 같은 알림을 동시에 열어 각자 판정하면, alert_review 에 서로
#   다른 결론이 두 줄 쌓인다(record 는 덮어쓰지 않는다). 어느 쪽이 맞는지
#   나중에 아무도 모른다 → 여는 순간 '내가 본다'를 선언하게 만든다.
_DDL_CLAIM = f"""
CREATE TABLE IF NOT EXISTS {CLAIM_TABLE} (
    txn_id     TEXT PRIMARY KEY,
    reviewer   TEXT NOT NULL,
    claimed_at TEXT NOT NULL      -- ⚠ UTC 고정 (datetime('now'))
)
"""

#   판정 중이던 입력은 지금까지 st.session_state 에만 있었다. 브라우저 새로고침
#   한 번이면 메모가 통째로 날아간다 — '켜 두는' 도구에서는 치명적이다.
_DDL_DRAFT = f"""
CREATE TABLE IF NOT EXISTS {DRAFT_TABLE} (
    txn_id     TEXT NOT NULL,
    reviewer   TEXT NOT NULL,
    verdict    TEXT,
    reason     TEXT,
    memo       TEXT,
    updated_at TEXT NOT NULL,     -- ⚠ UTC 고정
    PRIMARY KEY (txn_id, reviewer)
)
"""


def ensure_schema(db_path: str | Path = DEFAULT_DB) -> bool:
    """테이블·인덱스 보장. 이미 만들었으면 조용히 통과."""
    key = str(db_path)
    if key in _SCHEMA_DONE:
        return True
    try:
        con = _conn(db_path)
        con.execute(_DDL)
        con.execute(_DDL_CLAIM)
        con.execute(_DDL_DRAFT)
        for ix in _INDEXES:
            con.execute(ix)
        con.commit()
        con.close()
        _SCHEMA_DONE.add(key)
        return True
    except Exception as e:
        log.error(f"{TABLE} 스키마 생성 실패: {type(e).__name__}: {e}")
        return False


def connect(db_path: str | Path = DEFAULT_DB, readonly: bool = False):
    """같은 DB 를 쓰는 이웃 모듈(ops_shift 등)이 WAL·busy_timeout 설정을
    그대로 물려받도록 공개한다. 연결 로직을 복사하면 설정이 갈린다."""
    return _conn(db_path, readonly=readonly)


def table_exists(db_path: str | Path = DEFAULT_DB) -> bool:
    """읽기 경로에서 '아직 아무도 판정 안 함'과 'DB 없음'을 구분하기 위해."""
    try:
        con = _conn(db_path, readonly=True)
        r = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (TABLE,)
        ).fetchone()
        con.close()
        return r is not None
    except Exception:
        return False


# ══════════════════════════════════════════════════════════
# 쓰기
# ══════════════════════════════════════════════════════════

def default_reviewer() -> str:
    """검토자 이름 기본값. 대시보드가 여러 명에게 공유되므로 반드시 덮어쓰는 게 좋다."""
    return (os.getenv("FDS_REVIEWER")
            or os.getenv("USERNAME") or os.getenv("USER") or "unknown")


def record(db_path: str | Path,
           txn_id: str,
           verdict: str,
           *,
           reason: str | None = None,
           memo: str | None = None,
           reviewer: str | None = None,
           snapshot: dict | None = None,
           source: str = "ops_dashboard") -> tuple[bool, str]:
    """판정 1건 기록. (성공여부, 메시지)

    snapshot: 판정 당시 값들. ops_queries.alert_queue() 가 돌려주는 행을
      그대로 넘기면 된다 — 키는 tier / risk_score / fraud_type /
      th_review / th_confirm / model / alert_ref 를 본다.

    ⚠️ 같은 txn_id 로 다시 부르면 **덮어쓰지 않고 새 행이 쌓인다.**
       판정 번복은 그 자체가 감사 대상이라 지워선 안 된다.
    """
    txn_id = str(txn_id or "").strip()
    if not txn_id:
        return False, "거래 ID가 비었습니다"
    if verdict not in VERDICTS:
        return False, f"알 수 없는 판정값 '{verdict}' (가능: {', '.join(VERDICTS)})"
    if reason and reason not in FP_REASONS:
        # 막지는 않는다 — 사유 코드는 시간이 지나며 늘어나는 게 정상이다
        log.info(f"미등록 사유 코드 '{reason}' (그대로 저장)")

    if not ensure_schema(db_path):
        return False, "판정 테이블을 만들 수 없습니다 (DB 권한/경로 확인)"

    s = snapshot or {}
    rv = (reviewer or default_reviewer())[:100]
    try:
        con = _conn(db_path)
        con.execute(
            f"""INSERT INTO {TABLE}
                (txn_id, alert_ref, verdict, reason, memo, reviewer,
                 tier, risk_score, fraud_type, th_review, th_confirm, model,
                 source, reviewed_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?, datetime('now'))""",
            (txn_id,
             _int_or_none(s.get("alert_ref")),
             verdict,
             (reason or None),
             (memo or None)[:1000] if memo else None,
             rv,
             (s.get("tier") or None),
             _float_or_none(s.get("risk_score")),
             (s.get("fraud_type") or None),
             _float_or_none(s.get("th_review")),
             _float_or_none(s.get("th_confirm")),
             (s.get("model") or None),
             source),
        )
        # 판정이 끝났으면 잠금과 임시저장은 역할이 끝났다. 같은 트랜잭션에서
        # 정리해, '기록은 됐는데 잠금이 남아 남들이 못 보는' 상태를 만들지 않는다.
        con.execute(f"DELETE FROM {CLAIM_TABLE} WHERE txn_id=?", (txn_id,))
        con.execute(f"DELETE FROM {DRAFT_TABLE} WHERE txn_id=? AND reviewer=?",
                    (txn_id, rv))
        con.commit()
        con.close()
        return True, f"{VERDICT_LABEL_KO.get(verdict, verdict)} 기록됨 — {txn_id}"
    except Exception as e:
        log.error(f"판정 기록 실패({txn_id}): {type(e).__name__}: {e}")
        return False, f"기록 실패: {type(e).__name__}: {e}"


def record_many(db_path: str | Path, items: list[dict],
                reviewer: str | None = None,
                source: str = "ops_dashboard") -> tuple[int, list[str]]:
    """일괄 판정 (트리아지 화면에서 여러 건 체크 후 한 번에).
    반환: (성공 건수, 실패 메시지 목록)

    한 건씩 커밋하지 않고 하나의 트랜잭션으로 묶는다 — 워처가 도는 중에
    50번 커밋하면 그만큼 WAL 체크포인트가 끼어들어 폴링이 밀린다.
    """
    if not items:
        return 0, []
    if not ensure_schema(db_path):
        return 0, ["판정 테이블을 만들 수 없습니다"]

    rv = reviewer or default_reviewer()
    ok, errs = 0, []
    try:
        con = _conn(db_path)
        for it in items:
            txn_id = str(it.get("txn_id") or "").strip()
            verdict = it.get("verdict")
            if not txn_id or verdict not in VERDICTS:
                errs.append(f"건너뜀: {txn_id or '(ID없음)'} / {verdict}")
                continue
            try:
                con.execute(
                    f"""INSERT INTO {TABLE}
                        (txn_id, alert_ref, verdict, reason, memo, reviewer,
                         tier, risk_score, fraud_type, th_review, th_confirm, model,
                         source, reviewed_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?, datetime('now'))""",
                    (txn_id, _int_or_none(it.get("alert_ref")), verdict,
                     it.get("reason") or None,
                     (it.get("memo") or None),
                     (it.get("reviewer") or rv)[:100],
                     it.get("tier") or None, _float_or_none(it.get("risk_score")),
                     it.get("fraud_type") or None,
                     _float_or_none(it.get("th_review")),
                     _float_or_none(it.get("th_confirm")),
                     it.get("model") or None, source))
                ok += 1
            except Exception as e:
                errs.append(f"{txn_id}: {type(e).__name__}: {e}")
        con.commit()
        con.close()
    except Exception as e:
        errs.append(f"일괄 기록 실패: {type(e).__name__}: {e}")
    return ok, errs


def undo_last(db_path: str | Path, txn_id: str) -> tuple[bool, str]:
    """방금 찍은 판정 취소 — **이 모듈의 유일한 파괴적 연산.**

    오타로 잘못 누른 직후만 쓰라고 만든 것이다. 판정을 '바꾸고' 싶으면
    record() 로 새 판정을 남겨야 이력이 보존된다.
    """
    if not table_exists(db_path):
        return False, "판정 이력이 없습니다"
    try:
        con = _conn(db_path)
        cur = con.execute(
            f"SELECT id, verdict FROM {TABLE} WHERE txn_id=? ORDER BY id DESC LIMIT 1",
            (str(txn_id),))
        r = cur.fetchone()
        if not r:
            con.close()
            return False, f"{txn_id} 의 판정 이력이 없습니다"
        con.execute(f"DELETE FROM {TABLE} WHERE id=?", (r[0],))
        con.commit()
        con.close()
        return True, f"{txn_id} 의 마지막 판정({VERDICT_LABEL_KO.get(r[1], r[1])})을 취소했습니다"
    except Exception as e:
        return False, f"취소 실패: {type(e).__name__}: {e}"


# ══════════════════════════════════════════════════════════
# 읽기
# ══════════════════════════════════════════════════════════

_ROW_COLS = ("id", "txn_id", "alert_ref", "verdict", "reason", "memo", "reviewer",
             "tier", "risk_score", "fraud_type", "th_review", "th_confirm",
             "model", "source", "reviewed_at")


def current(db_path: str | Path = DEFAULT_DB,
            txn_ids: list[str] | None = None) -> dict[str, dict]:
    """txn_id 별 **최신** 판정. {txn_id: {...}}

    txn_ids 를 주면 그 건들만 (트리아지 화면에서 지금 보이는 30건만 조회하는 용도).
    None 이면 전체 — 건수가 많으면 느리니 화면에서는 되도록 목록을 넘길 것.
    """
    if not table_exists(db_path):
        return {}
    cols = ", ".join(_ROW_COLS)
    # id 가 AUTOINCREMENT 라 'txn_id 별 최대 id' = 최신 판정. reviewed_at 은 초 단위라
    # 같은 초에 두 번 찍으면 순서가 흔들린다 → 반드시 id 기준으로 뽑는다.
    sql = (f"SELECT {cols} FROM {TABLE} WHERE id IN "
           f"(SELECT MAX(id) FROM {TABLE} GROUP BY txn_id)")
    params: tuple = ()
    if txn_ids:
        ids = [str(x) for x in txn_ids if x]
        if not ids:
            return {}
        # sqlite 기본 변수 상한(999) 대비 — 큰 목록은 청크로 나눠 호출
        if len(ids) > 900:
            out: dict[str, dict] = {}
            for i in range(0, len(ids), 900):
                out.update(current(db_path, ids[i:i + 900]))
            return out
        sql += f" AND txn_id IN ({','.join('?' * len(ids))})"
        params = tuple(ids)
    try:
        con = _conn(db_path, readonly=True)
        rows = con.execute(sql, params).fetchall()
        con.close()
        return {r[1]: dict(zip(_ROW_COLS, r)) for r in rows}
    except Exception as e:
        log.debug(f"최신 판정 조회 실패: {e}")
        return {}


def history(db_path: str | Path, txn_id: str) -> list[dict]:
    """한 거래의 판정 이력 전체 (오래된 → 최신). 판정 번복 감사용."""
    if not table_exists(db_path):
        return []
    try:
        con = _conn(db_path, readonly=True)
        rows = con.execute(
            f"SELECT {', '.join(_ROW_COLS)} FROM {TABLE} WHERE txn_id=? ORDER BY id",
            (str(txn_id),)).fetchall()
        con.close()
        return [dict(zip(_ROW_COLS, r)) for r in rows]
    except Exception as e:
        log.debug(f"판정 이력 조회 실패: {e}")
        return []


def counts(db_path: str | Path = DEFAULT_DB,
           since_hours: int | None = None) -> dict[str, int]:
    """판정 집계. 최신 판정 기준(번복된 옛 판정은 세지 않는다).

    since_hours 는 **UTC 기준** — reviewed_at 이 UTC 라 SQL 안에서 비교해야
    로컬시각과 섞이지 않는다 (watcher_panel.py 가 겪은 것과 같은 함정).
    """
    base = {v: 0 for v in VERDICTS}
    # 🐛 FIX: 이 조기 반환이 total·fp_rate 를 빠뜨려, alert_review 테이블이 아직
    #   없는 **신규 DB 첫 실행**에서 summary_line() 이 KeyError 로 죽었다.
    #   반환 형태는 어떤 경로로 나가든 항상 같아야 한다 — 호출부가 키 존재를
    #   확인하도록 만드는 API 는 언젠가 반드시 터진다.
    base["total"] = 0
    base["fp_rate"] = None
    if not table_exists(db_path):
        return base
    sql = (f"SELECT verdict, COUNT(*) FROM {TABLE} WHERE id IN "
           f"(SELECT MAX(id) FROM {TABLE} GROUP BY txn_id)")
    params: tuple = ()
    if since_hours:
        sql += " AND reviewed_at > datetime('now', ?)"
        params = (f"-{int(since_hours)} hours",)
    sql += " GROUP BY verdict"
    try:
        con = _conn(db_path, readonly=True)
        for v, n in con.execute(sql, params).fetchall():
            base[v] = n
        con.close()
    except Exception as e:
        log.debug(f"판정 집계 실패: {e}")
    base["total"] = sum(base.get(v, 0) for v in VERDICTS)
    judged = base["tp"] + base["fp"]
    # 오탐률 = 오탐 / (정탐+오탐). 보류·미탐은 분모에서 뺀다 —
    #   보류를 정탐 취급하면 오탐률이 실제보다 낮게 보인다(가장 흔한 지표 왜곡).
    base["fp_rate"] = round(base["fp"] / judged, 4) if judged else None
    return base


def reason_counts(db_path: str | Path = DEFAULT_DB,
                  since_hours: int | None = None) -> list[dict]:
    """오탐 사유별 집계 — '임계값을 올릴지, 피처를 고칠지' 판단의 근거.

    legit_customer 가 많으면 → 임계값이 낮은 것
    model_drift 가 많으면    → 재학습이 필요한 것
    두 처방은 완전히 다르므로 사유 없는 오탐률은 행동으로 이어지지 않는다.
    """
    if not table_exists(db_path):
        return []
    sql = (f"SELECT COALESCE(reason,'(미기재)'), COUNT(*) FROM {TABLE} "
           f"WHERE verdict='fp' AND id IN "
           f"(SELECT MAX(id) FROM {TABLE} GROUP BY txn_id)")
    params: tuple = ()
    if since_hours:
        sql += " AND reviewed_at > datetime('now', ?)"
        params = (f"-{int(since_hours)} hours",)
    sql += " GROUP BY 1 ORDER BY 2 DESC"
    try:
        con = _conn(db_path, readonly=True)
        rows = con.execute(sql, params).fetchall()
        con.close()
        total = sum(n for _, n in rows) or 1
        return [{"사유코드": c, "사유": FP_REASONS.get(c, c), "건수": n,
                 "비중": round(n / total * 100, 1)} for c, n in rows]
    except Exception as e:
        log.debug(f"사유 집계 실패: {e}")
        return []


def reviewed_ids(db_path: str | Path = DEFAULT_DB) -> set[str]:
    """이미 판정이 끝난 거래 ID 집합 — 트리아지 대기열에서 제외하는 데 쓴다."""
    if not table_exists(db_path):
        return set()
    try:
        con = _conn(db_path, readonly=True)
        rows = con.execute(f"SELECT DISTINCT txn_id FROM {TABLE}").fetchall()
        con.close()
        return {r[0] for r in rows}
    except Exception:
        return set()


# ══════════════════════════════════════════════════════════
# 재학습용 내보내기 — batch_analyzer 의 TODO 를 실제로 닫는 부분
# ══════════════════════════════════════════════════════════

def export_training_labels(db_path: str | Path = DEFAULT_DB,
                           include_features: bool = True) -> list[dict]:
    """판정 결과 + 당시 피처를 재학습 데이터로 뽑는다.

    피처는 detections.raw_json 에서 온다.
    ⚠️ 워처가 넣은 raw_json 은 **마스킹본**이다 (detect_service._save_detections 주석 참조).
       계좌번호·이름 같은 원본 PII 는 이미 지워져 있으므로, 마스킹된 필드를
       그대로 학습에 쓰면 안 된다. 파생 피처(금액·시각·채널 등)만 쓸 것.

    반환 각 행: {txn_id, label, verdict, reason, risk_score, fraud_type,
                 reviewed_at(UTC), features: {...}}
    """
    verdicts = current(db_path)
    if not verdicts:
        return []
    out = []
    raw_map: dict[str, str] = {}
    if include_features:
        try:
            con = _conn(db_path, readonly=True)
            has = con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='detections'"
            ).fetchone()
            if has:
                for tid, rj in con.execute(
                        "SELECT transaction_id, raw_json FROM detections"):
                    if tid in verdicts:
                        raw_map[tid] = rj
            con.close()
        except Exception as e:
            log.warning(f"피처 조회 실패(라벨만 내보냅니다): {e}")

    for tid, v in verdicts.items():
        if v["verdict"] not in ("tp", "fp", "fn"):
            continue                      # 보류는 학습 라벨이 될 수 없다
        # 학습 라벨: 정탐/미탐 → 실제 사기(1), 오탐 → 정상(0)
        label = 0 if v["verdict"] == "fp" else 1
        rec = {"txn_id": tid, "label": label, "verdict": v["verdict"],
               "reason": v.get("reason"), "risk_score": v.get("risk_score"),
               "fraud_type": v.get("fraud_type"), "reviewed_at": v.get("reviewed_at"),
               "reviewer": v.get("reviewer")}
        if include_features and tid in raw_map:
            try:
                rec["features"] = json.loads(raw_map[tid] or "{}")
            except Exception:
                rec["features"] = {}
        out.append(rec)
    return out


# ══════════════════════════════════════════════════════════
# 잡동사니
# ══════════════════════════════════════════════════════════

def _float_or_none(v):
    try:
        return None if v is None or v == "" else float(v)
    except (TypeError, ValueError):
        return None


def _int_or_none(v):
    try:
        return None if v is None or v == "" else int(v)
    except (TypeError, ValueError):
        return None


# ══════════════════════════════════════════════════════════
# 🔒 잠금 (claim) — 동시 판정 방지
# ══════════════════════════════════════════════════════════

def claim(db_path: str | Path, txn_id: str, reviewer: str,
          ttl_min: int = CLAIM_TTL_MIN) -> tuple[bool, str, str | None]:
    """이 알림을 '내가 본다'고 선언. (성공여부, 메시지, 현재 보유자)

    · 비어 있거나 내 것이면 → 갱신하고 성공 (하트비트 역할도 겸한다)
    · 남이 TTL 안에 잡고 있으면 → 실패 + 보유자 이름
    · 남이 잡았지만 TTL 이 지났으면 → 뺏어온다 (브라우저를 닫고 간 경우)

    ⚠️ 이것은 **협조적 잠금**이다. record() 를 막지는 않는다 — DB 레벨 강제
    잠금은 워처까지 물릴 수 있어 위험하고, 관제 현장에서는 "누가 보고 있다"를
    보여주는 것만으로 충돌의 대부분이 사라진다.
    """
    txn_id, reviewer = str(txn_id or "").strip(), str(reviewer or "").strip()
    if not txn_id:
        return False, "거래 ID가 비었습니다", None
    if not ensure_schema(db_path):
        return False, "잠금 테이블을 만들 수 없습니다", None
    try:
        con = _conn(db_path)
        row = con.execute(
            f"""SELECT reviewer,
                       CAST((julianday('now') - julianday(claimed_at)) * 1440 AS INT)
                  FROM {CLAIM_TABLE} WHERE txn_id=?""", (txn_id,)).fetchone()
        if row and row[0] != reviewer and (row[1] is not None and row[1] < ttl_min):
            con.close()
            return False, f"🔒 {row[0]} 님이 검토 중입니다 ({row[1]}분 전 시작)", row[0]
        con.execute(
            f"""INSERT INTO {CLAIM_TABLE} (txn_id, reviewer, claimed_at)
                VALUES (?, ?, datetime('now'))
                ON CONFLICT(txn_id) DO UPDATE
                   SET reviewer=excluded.reviewer, claimed_at=excluded.claimed_at""",
            (txn_id, reviewer[:100]))
        con.commit()
        con.close()
        stolen = bool(row and row[0] != reviewer)
        return True, (f"이전 잠금({row[0]}) 만료 — 가져왔습니다" if stolen else "검토 시작"), reviewer
    except Exception as e:
        log.error(f"잠금 실패({txn_id}): {type(e).__name__}: {e}")
        return False, f"잠금 실패: {type(e).__name__}", None


def release(db_path: str | Path, txn_id: str, reviewer: str | None = None) -> bool:
    """잠금 해제. reviewer 를 주면 내 잠금일 때만 푼다 (남의 것을 실수로 풀지 않게)."""
    if not table_exists(db_path):
        return False
    try:
        con = _conn(db_path)
        if reviewer:
            con.execute(f"DELETE FROM {CLAIM_TABLE} WHERE txn_id=? AND reviewer=?",
                        (str(txn_id), str(reviewer)))
        else:
            con.execute(f"DELETE FROM {CLAIM_TABLE} WHERE txn_id=?", (str(txn_id),))
        con.commit()
        con.close()
        return True
    except Exception as e:
        log.debug(f"잠금 해제 실패({txn_id}): {e}")
        return False


def renew_claims(db_path: str | Path, reviewer: str) -> int:
    """내가 들고 있는 잠금 **전부**의 시각을 지금으로 민다. 갱신된 건수 반환.

    왜 필요한가 — '조사 중인데 잠금이 풀린다'
      claim() 은 위젯을 만질 때(on_change)만 불린다. 그런데 한 건을 진지하게
      들여다보면 15분(CLAIM_TTL_MIN)은 금방 지나간다. 그 사이 아무 위젯도
      건드리지 않았다면 잠금이 만료되고, 다른 담당자가 같은 알림을 집어
      **서로 다른 결론이 두 줄** 쌓인다. 잠금을 둔 이유가 사라지는 것이다.

    왜 '화면이 열려 있는 동안'이 옳은 기준인가
      TTL 이 존재하는 이유는 "브라우저를 그냥 닫으면 release 가 오지 않기
      때문"이다(claim 주석). 즉 구분해야 할 것은 **세션이 살아 있는가**지
      위젯을 만졌는가가 아니다. 화면이 열려 있으면 리런이 계속 도니 갱신되고,
      브라우저를 닫으면 갱신이 멈춰 TTL 이 제 역할을 한다.

    한 번의 UPDATE 로 끝낸다 — 행마다 질의하면 워처가 도는 중 WAL 경합이 생긴다.
    """
    reviewer = str(reviewer or "").strip()
    if not reviewer or not table_exists(db_path):
        return 0
    try:
        con = _conn(db_path)
        cur = con.execute(
            f"UPDATE {CLAIM_TABLE} SET claimed_at = datetime('now') WHERE reviewer = ?",
            (reviewer,))
        n = cur.rowcount or 0
        con.commit()
        con.close()
        return int(n)
    except Exception as e:
        log.debug(f"잠금 갱신 실패({reviewer}): {e}")
        return 0


def active_claims(db_path: str | Path = DEFAULT_DB,
                  ttl_min: int = CLAIM_TTL_MIN) -> dict:
    """유효한 잠금 전체 → {txn_id: {"reviewer", "age_min"}}.

    트리아지 큐를 그릴 때 한 번만 조회해 행마다 재사용한다 —
    20행에 20번 질의하면 워처가 도는 중 WAL 경합이 눈에 띈다.
    """
    try:
        con = _conn(db_path, readonly=True)
        rows = con.execute(
            f"""SELECT txn_id, reviewer,
                       CAST((julianday('now') - julianday(claimed_at)) * 1440 AS INT)
                  FROM {CLAIM_TABLE}""").fetchall()
        con.close()
    except Exception:
        return {}
    out = {}
    for txn_id, reviewer, age in rows:
        if age is None or age >= ttl_min:
            continue                      # 만료 — 없는 것으로 친다
        out[txn_id] = {"reviewer": reviewer, "age_min": int(age)}
    return out


def purge_expired_claims(db_path: str | Path = DEFAULT_DB,
                         ttl_min: int = CLAIM_TTL_MIN) -> int:
    """만료 잠금 정리. 없어도 active_claims 가 걸러내므로 동작엔 지장 없다 —
    테이블이 무한정 자라는 것만 막는다."""
    if not table_exists(db_path):
        return 0
    try:
        con = _conn(db_path)
        cur = con.execute(
            f"""DELETE FROM {CLAIM_TABLE}
                 WHERE (julianday('now') - julianday(claimed_at)) * 1440 >= ?""",
            (int(ttl_min),))
        n = cur.rowcount or 0
        con.commit()
        con.close()
        return n
    except Exception:
        return 0


# ══════════════════════════════════════════════════════════
# 💾 임시저장 (draft) — 새로고침에도 살아남는 판정 입력
# ══════════════════════════════════════════════════════════

def save_draft(db_path: str | Path, txn_id: str, reviewer: str, *,
               verdict: str | None = None, reason: str | None = None,
               memo: str | None = None) -> bool:
    """판정 중이던 입력을 저장 (txn_id + reviewer 단위 upsert).

    사람마다 따로 저장한다 — 같은 알림을 두 명이 보고 있을 때 서로의 메모를
    덮어쓰면 잠금을 둔 의미가 없다.
    """
    txn_id, reviewer = str(txn_id or "").strip(), str(reviewer or "").strip()
    if not txn_id or not reviewer:
        return False
    if not ensure_schema(db_path):
        return False
    try:
        con = _conn(db_path)
        con.execute(
            f"""INSERT INTO {DRAFT_TABLE}
                    (txn_id, reviewer, verdict, reason, memo, updated_at)
                VALUES (?,?,?,?,?, datetime('now'))
                ON CONFLICT(txn_id, reviewer) DO UPDATE
                   SET verdict=excluded.verdict, reason=excluded.reason,
                       memo=excluded.memo, updated_at=excluded.updated_at""",
            (txn_id, reviewer[:100], verdict, reason,
             (memo or None)[:1000] if memo else None))
        con.commit()
        con.close()
        return True
    except Exception as e:
        log.debug(f"임시저장 실패({txn_id}): {e}")
        return False


def load_drafts(db_path: str | Path, reviewer: str) -> dict:
    """내 임시저장 전체 → {txn_id: {"verdict","reason","memo","updated_at"}}.
    큐를 그리기 전에 한 번만 부른다."""
    if not reviewer or not table_exists(db_path):
        return {}
    try:
        con = _conn(db_path, readonly=True)
        rows = con.execute(
            f"""SELECT txn_id, verdict, reason, memo, updated_at
                  FROM {DRAFT_TABLE} WHERE reviewer=?""", (str(reviewer),)).fetchall()
        con.close()
    except Exception:
        return {}
    return {r[0]: {"verdict": r[1], "reason": r[2], "memo": r[3], "updated_at": r[4]}
            for r in rows}


def clear_draft(db_path: str | Path, txn_id: str, reviewer: str) -> bool:
    """판정이 확정되면 임시저장은 역할이 끝난다."""
    if not table_exists(db_path):
        return False
    try:
        con = _conn(db_path)
        con.execute(f"DELETE FROM {DRAFT_TABLE} WHERE txn_id=? AND reviewer=?",
                    (str(txn_id), str(reviewer)))
        con.commit()
        con.close()
        return True
    except Exception:
        return False


def summary_line(db_path: str | Path = DEFAULT_DB, since_hours: int = 168) -> str:
    """헤더/사이드바용 한 줄 요약 (MCP·CLI 에서도 재사용)."""
    c = counts(db_path, since_hours)
    if not c["total"]:
        return "📝 최근 판정 없음"
    fr = c["fp_rate"]
    return (f"📝 최근 {since_hours}h · 판정 {c['total']}건 · "
            f"정탐 {c['tp']} / 오탐 {c['fp']} / 미탐 {c['fn']} / 보류 {c['unclear']}"
            + (f" · 오탐률 {fr*100:.1f}%" if fr is not None else ""))


# ── CLI 확인용:  python -m pipeline.review_store ──
if __name__ == "__main__":
    import sys
    db = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DB
    print(f"review_store {REVIEW_STORE_VERSION} · DB={db}")
    print(" 테이블 존재:", table_exists(db))
    print(" ", summary_line(db))
    for r in reason_counts(db):
        print("  ", r)

"""
ops_queries — 관제/오탐 대시보드용 조회 레이어 (읽기 전용)  ✨ v19 신규

이 파일이 존재하는 이유 = **시각(timezone)**

  fds_results.db 는 테이블마다 시간대가 다르다. 전수 조사 결과:

    watcher_status.started_at / last_poll   datetime('now')             → UTC
    watch_cursor.updated_at                 datetime('now')             → UTC
    notified.sent_at                        datetime('now')             → UTC
    detections.detected_at                  datetime('now','localtime') → LOCAL
    transactions.processed_at (detect_service)  time.strftime()         → LOCAL
    transactions.processed_at (DEFAULT)     CURRENT_TIMESTAMP           → UTC   ⚠️

  마지막 두 줄을 보라. **같은 컬럼에 두 시간대가 섞여 들어간다.**
  detect_service._save_transactions 는 로컬시각 문자열을 넣지만(743행),
  컬럼을 생략하는 다른 writer 가 넣으면 DEFAULT 인 CURRENT_TIMESTAMP(UTC)가 박힌다.

  각 테이블을 따로 보는 지금은 안 터진다. 하지만 오탐 대시보드는 이것들을
  **하나의 타임라인에 합쳐야** 한다 — 그 순간 KST 기준 9시간짜리 유령 피크가 생긴다.
  그래서 모든 조회는 여기를 통과하며 UTC 로 정규화된다. 화면 표시 직전에만 로컬로 되돌린다.

  ⚠️ 근본 해결은 아니다. 진짜 고치려면 detect_service 가 전부 datetime('now') 로
     통일해야 한다. 이 모듈은 **기존 데이터를 버리지 않으면서** 읽는 임시방편이다.
     diagnose_timestamps() 가 현재 오염 상태를 보고해 준다.

설계 원칙
  · 읽기 전용. mode=ro URI 로 연다 — 무인 워처의 쓰기를 절대 막지 않는다.
  · 어떤 실패도 밖으로 던지지 않는다. 테이블이 없으면 빈 결과.
  · Streamlit 무관 — CLI·MCP·테스트에서 그대로 재사용 가능.

핵심 API
    diagnose_timestamps(db)                  # 시간대 오염 진단
    alert_queue(db, limit=50)                # 판정 대기 알림 큐 (트리아지 탭)
    fp_timeline(db, bucket="day")            # 오탐률 추이
    fp_by_dimension(db, "fraud_type")        # 유형/등급/점수구간별 오탐
    threshold_whatif(db, ...)                # 임계값 시뮬레이터
    live_feed(db, limit=30)                  # 실시간 탐지 피드
"""

from __future__ import annotations

import sqlite3
import logging
from pathlib import Path

log = logging.getLogger(__name__)

OPS_QUERIES_VERSION = "v22"
DEFAULT_DB = "fds_results.db"

try:
    from pipeline import review_store as rs
except ImportError:                                  # pragma: no cover
    import review_store as rs

try:
    from pipeline import demo_mode as _demo
except ImportError:                                  # pragma: no cover
    import demo_mode as _demo

# 컬럼별 선언 시간대. "auto" 는 한 컬럼에 섞여 있다고 알려진 경우.
TZ_DECLARED = {
    ("watcher_status", "started_at"): "utc",
    ("watcher_status", "last_poll"):  "utc",
    ("watch_cursor",   "updated_at"): "utc",
    ("notified",       "sent_at"):    "utc",
    # ⚠️ 'local' 이 아니다 — 두 writer(dashboard._save_detection_to_db,
    #   detect_io.save_detection) 모두 UTC 로 쓴다. 'local' 선언 때문에 조회 시
    #   9시간을 한 번 더 빼고 있었고, 🩺 진단이 74행 전부를 불일치로 표시했다.
    #   'utc' 로 못박지 않고 'auto' 로 두는 이유: 이 컬럼은 코드 사본이 둘이라
    #   한쪽이 다시 로컬로 돌아가도 휴리스틱이 스스로 보정한다.
    ("detections",     "detected_at"): "auto",
    ("transactions",   "processed_at"): "auto",     # ⚠️ 혼재
    ("transactions",   "detected_at"):  "local",    # 구 대시보드 스키마
    ("alert_review",   "reviewed_at"):  "utc",      # 신규 — 처음부터 UTC 고정
}


# ══════════════════════════════════════════════════════════
# 연결 · 시간대
# ══════════════════════════════════════════════════════════

def _conn(db_path: str | Path) -> sqlite3.Connection:
    """읽기 전용 연결. 파일이 없으면 OperationalError → 호출부가 잡는다."""
    con = sqlite3.connect(f"file:{Path(str(db_path)).as_posix()}?mode=ro",
                          uri=True, timeout=5)
    try:
        con.execute("PRAGMA busy_timeout=5000")
    except Exception:
        pass
    return con


_MIGRATED_CACHE: dict[str, bool] = {}


def migration_applied(db_path=DEFAULT_DB, mig_id: str = "M001_utc_unify") -> bool:
    """시간대 통일 마이그레이션(M001)이 적용됐는지.

    적용 후에는 detections/transactions 가 UTC 이므로 TZ_DECLARED 의 'local'·'auto'
    선언이 낡은 값이 된다. 그대로 두면 조회 시 UTC 를 한 번 더 빼서 9시간이 어긋난다.
    → 선언을 런타임에 갈아끼운다.
    """
    key = str(db_path)
    if key in _MIGRATED_CACHE:
        return _MIGRATED_CACHE[key]
    ok = False
    try:
        con = _conn(db_path)
        r = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        ).fetchone()
        if r:
            ok = con.execute("SELECT 1 FROM schema_migrations WHERE id=?",
                             (mig_id,)).fetchone() is not None
        con.close()
    except Exception:
        pass
    _MIGRATED_CACHE[key] = ok
    return ok


def declared_tz(db_path, table: str, col: str) -> str:
    """이 컬럼의 시간대 선언 — 마이그레이션 여부를 반영한다."""
    if migration_applied(db_path):
        return "utc"
    return TZ_DECLARED.get((table, col), "auto")


def _tables(con) -> set[str]:
    try:
        return {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    except Exception:
        return set()


def _cols(con, table: str) -> set[str]:
    try:
        return {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
    except Exception:
        return set()


_OFFSET_CACHE: dict[str, int] = {}


def tz_offset_seconds(db_path: str | Path = DEFAULT_DB) -> int:
    """로컬시각 − UTC (초). KST 면 32400.

    파이썬의 time.timezone 이 아니라 **sqlite 에게 직접 묻는다** — 값을 쓴 주체가
    sqlite 의 'localtime' 이기 때문이다. 서머타임·서버 TZ 설정 차이를 그대로 반영한다.
    """
    key = str(db_path)
    if key in _OFFSET_CACHE:
        return _OFFSET_CACHE[key]
    off = 0
    try:
        con = _conn(db_path)
        r = con.execute(
            "SELECT CAST(strftime('%s', datetime('now','localtime')) "
            "     - strftime('%s', datetime('now')) AS INTEGER)").fetchone()
        con.close()
        off = int(r[0]) if r and r[0] is not None else 0
    except Exception as e:
        log.debug(f"시간대 오프셋 조회 실패(0 가정): {e}")
    _OFFSET_CACHE[key] = off
    return off


def utc_expr(col: str, assume: str, offset: int) -> str:
    """`col` 을 UTC 로 정규화하는 SQL 식.

    assume:
      "utc"   그대로
      "local" offset 만큼 되돌린다
      "auto"  혼재 컬럼 — 값이 'UTC 현재시각보다 미래'면 로컬로 간주해 보정.

    ⚠️ "auto" 의 한계를 분명히 해두자. 이 휴리스틱은 **offset 이 양수일 때만**
       (한국·일본 등 UTC+) 신뢰할 수 있다. UTC− 지역에서는 로컬 문자열이 과거로
       보이는데, 그건 '오래된 UTC 행'과 구분이 안 된다. 그 경우 보정을 포기하고
       선언값(local)을 그대로 쓴다 — 조용히 틀린 값을 만드는 것보다
       일관되게 틀린 값이 낫고, diagnose_timestamps() 가 경고를 띄운다.
    """
    if assume == "utc" or offset == 0:
        return col
    if assume == "local":
        return f"datetime({col}, '-{offset} seconds')"
    # auto
    if offset > 0:
        # 60초 여유 — 방금 쓰인 UTC 행이 반올림으로 미래처럼 보이는 것을 방지
        _now = _epoch("'now'")
        return (f"CASE WHEN {_epoch(col)} > {_now} + 60 "
                f"THEN datetime({col}, '-{offset} seconds') ELSE {col} END")
    return f"datetime({col}, '-{offset} seconds')"


def _epoch(col: str) -> str:
    """🐛 SQLite 함정 — strftime('%s', …) 은 INTEGER 가 아니라 **TEXT** 를 돌려준다.

    그래서  strftime('%s', ts) > strftime('%s','now') + 60  은
    좌변 TEXT, 우변 INTEGER 비교가 되는데, SQLite 의 타입 우선순위상
    **INTEGER 는 항상 TEXT 보다 작다.** 즉 이 조건은 값과 무관하게 늘 참이다.
    (모든 행이 '미래'로 분류돼 UTC 컬럼까지 로컬로 오인식됐다.)

    watcher_panel.py 가 CAST(strftime(...) - strftime(...) AS INTEGER) 처럼
    **뺄셈**을 쓴 덕에 우연히 무사했던 것이지, 비교 연산은 반드시 캐스팅해야 한다.
    """
    return f"CAST(strftime('%s',{col}) AS INTEGER)"


_NOW = "'now'"      # f-string 안에서 따옴표 중첩을 피하기 위한 상수


def to_local(utc_str: str | None, offset: int) -> str:
    """UTC 문자열 → 로컬 표시용. 화면 렌더 직전에만 쓴다."""
    if not utc_str:
        return ""
    try:
        from datetime import datetime, timedelta
        dt = datetime.strptime(str(utc_str)[:19], "%Y-%m-%d %H:%M:%S")
        return (dt + timedelta(seconds=offset)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(utc_str)


def diagnose_timestamps(db_path: str | Path = DEFAULT_DB) -> list[dict]:
    """시간대 오염 진단 — 대시보드 🩺 패널에 그대로 띄울 결과.

    각 컬럼의 MAX(값)를 UTC 현재시각과 비교해 실제로 어느 시간대로
    기록되고 있는지 추정한다. 선언값과 다르면 flag 를 세운다.
    """
    off = tz_offset_seconds(db_path)
    out = []
    try:
        con = _conn(db_path)
        have = _tables(con)
        migrated = migration_applied(db_path)
        for (tbl, col), declared0 in TZ_DECLARED.items():
            if tbl not in have or col not in _cols(con, tbl):
                continue
            declared = "utc" if migrated else declared0
            try:
                r = con.execute(
                    f"SELECT MAX({col}), COUNT(*), "
                    f"  SUM(CASE WHEN {_epoch(col)} > {_epoch(_NOW)}+60 "
                    f"           THEN 1 ELSE 0 END) "
                    f"FROM {tbl} WHERE {col} IS NOT NULL").fetchone()
            except Exception:
                continue
            newest, n, n_future = (r or (None, 0, 0))
            if not n:
                continue
            n_future = n_future or 0
            if off > 0 and n_future and n_future < n:
                observed, mixed = "혼재", True
            elif off > 0 and n_future == n:
                observed, mixed = "local", False
            elif off > 0:
                observed, mixed = "utc", False
            else:
                observed, mixed = declared, False
            out.append({
                "테이블": tbl, "컬럼": col,
                "선언": declared + (" (M001)" if migrated and declared0 != "utc" else ""),
                "관측": observed,
                "행수": n, "미래행": n_future, "최신값": newest,
                "불일치": bool(mixed or (observed != declared and declared != "auto")),
            })
        con.close()
    except Exception as e:
        log.debug(f"시간대 진단 실패: {e}")
    return out


# ══════════════════════════════════════════════════════════
# 알림 원장 — 어떤 테이블을 '진실'로 삼는가
# ══════════════════════════════════════════════════════════
#
# detections 는 transaction_id 가 PK + UPSERT 라 **재탐지하면 이전 판정이 덮어써진다**
# (detect_service.py:722). 사람이 판정을 붙일 대상 원장으로는 부적격이다.
# transactions 는 id INTEGER PRIMARY KEY AUTOINCREMENT 로 append-only 이므로
# 알림 원장은 transactions 를 쓴다. detections 는 raw_json(피처)을 얻는 보조 테이블.

def _ledger(con) -> tuple[str, dict] | tuple[None, None]:
    """알림 원장 테이블과 컬럼 맵을 고른다. 스키마 세대차를 여기서 흡수한다."""
    have = _tables(con)
    if "transactions" in have:
        c = _cols(con, "transactions")
        ts = ("processed_at" if "processed_at" in c else
              "detected_at" if "detected_at" in c else None)
        if ts:
            return "transactions", {
                "id": "id" if "id" in c else "rowid",
                "txn": "transaction_id", "ts": ts,
                "score": "risk_score", "type": "fraud_type",
                "anom": "is_anomaly",
                "mode": "input_mode" if "input_mode" in c else None,
                "truth": "true_label" if "true_label" in c else None,
                "model": "model" if "model" in c else None,
                "thr": "threshold" if "threshold" in c else None,
            }
    if "detections" in have:
        # 폴백 — 워처를 안 돌리고 대시보드만 써온 DB
        return "detections", {
            "id": "rowid", "txn": "transaction_id", "ts": "detected_at",
            "score": "risk_score", "type": "fraud_type", "anom": "is_anomaly",
            "mode": None, "truth": None, "model": "model", "thr": "threshold",
        }
    return None, None


def _like_escape(s: str) -> str:
    """LIKE 패턴의 와일드카드를 리터럴로. 검색어에 `%`·`_` 가 섞여도
    '아무거나 매치'로 변질되지 않게 한다 (`_` 는 거래 ID 에 흔하다)."""
    return (str(s).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_"))


def alert_queue(db_path: str | Path = DEFAULT_DB, limit: int = 50,
                min_score: float = 0.0, only_unreviewed: bool = True,
                watcher_only: bool = False, since_hours: int | None = None,
                txn_like: str | None = None,
                only_anomaly: bool = False) -> list[dict]:
    """판정 대기 알림 큐 — 트리아지 탭의 본체.

    '알림'의 정의: is_anomaly=1 **또는** risk_score >= min_score.
      detect_service 는 점수가 낮아도 예측 유형이 사기면 review 로 올린다
      (watcher_panel.py 의 안내문 참조 — 이 모델 사기 재현율 0.53 대비 미탐 안전망).
      그래서 점수만으로 거르면 그 안전망에 걸린 건들이 큐에서 사라진다.

    ⚠️ `txn_like` / `only_anomaly` 는 **SQL 에서** 거른다 — 호출부가 결과를 받아
       파이썬에서 거르면 안 된다. 그러면 "limit 만큼 뽑고 → 거른다" 가 되어
       **요청한 건수보다 훨씬 적게** 남는다. 실제로 그렇게 깨져 있었다:
         · 탐지 로그 '건수 50 + 이상거래만'  → 화면에 4행
         · 실시간 피드 12건                  → 화면에 4건
         · 검색어는 최근 N건 안에서만 매치 (그 밖의 거래는 영원히 안 나옴)
       조건을 SQL 로 내리면 limit 이 '거른 뒤의 건수'를 뜻하게 되어 뜻대로 동작한다.
    """
    try:
        con = _conn(db_path)
    except Exception as e:
        log.debug(f"DB 열기 실패: {e}")
        return []
    off = tz_offset_seconds(db_path)
    try:
        tbl, m = _ledger(con)
        if not tbl:
            con.close()
            return []
        ts_utc = utc_expr(m["ts"], declared_tz(db_path, tbl, m["ts"]), off)
        sel = [f"{m['id']} AS alert_ref", f"{m['txn']} AS txn_id",
               f"{ts_utc} AS ts_utc", f"{m['score']} AS risk_score",
               f"{m['type']} AS fraud_type", f"{m['anom']} AS is_anomaly"]
        for k, alias in (("mode", "source"), ("truth", "true_label"),
                         ("model", "model"), ("thr", "threshold")):
            sel.append(f"{m[k]} AS {alias}" if m.get(k) else f"NULL AS {alias}")

        q = (f"SELECT {', '.join(sel)} FROM {tbl} "
             f"WHERE ({m['anom']}=1 OR {m['score']} >= ?)")
        params: list = [float(min_score)]
        if watcher_only and m.get("mode"):
            q += f" AND {m['mode']} LIKE 'watcher%'"
        if only_anomaly:
            q += f" AND {m['anom']}=1"
        if txn_like and str(txn_like).strip():
            # SQLite 의 LIKE 는 ASCII 대소문자를 구분하지 않는다 — 거래 ID 는 ASCII
            q += f" AND {m['txn']} LIKE ? ESCAPE '\\'"
            params.append(f"%{_like_escape(str(txn_like).strip())}%")
        if since_hours:
            q += f" AND {ts_utc} > datetime('now', ?)"
            params.append(f"-{int(since_hours)} hours")
        # 넉넉히 뽑아 판정 완료분을 파이썬에서 제외 — alert_review 는 같은 DB지만
        # 읽기 전용 연결 하나로 JOIN 하면 테이블 부재 시 통째로 실패한다.
        q += f" ORDER BY {m['id']} DESC LIMIT ?"
        # 판정 완료분(only_unreviewed)과 중복 거래를 파이썬에서 걸러내므로 넉넉히 뽑는다
        params.append(int(limit) * (4 if only_unreviewed else 2))
        rows = con.execute(q, params).fetchall()
        keys = ("alert_ref", "txn_id", "ts_utc", "risk_score", "fraud_type",
                "is_anomaly", "source", "true_label", "model", "threshold")
        con.close()
    except Exception as e:
        log.debug(f"알림 큐 조회 실패: {e}")
        try:
            con.close()
        except Exception:
            pass
        return []

    items = [dict(zip(keys, r)) for r in rows]

    # 🎬 시연 모드(환경변수 FDS_DEMO_MODE=1)에서만 동작한다.
    #   여기가 알림 행이 나오는 **유일한 깔때기**다(live_feed 도 이 함수를 부른다).
    #   그래서 시각 재기준을 이 한 자리에서 하면 트리아지·SLA·교대 요약·실시간
    #   피드가 전부 같은 기준을 본다. 아래 `시각` 파생보다 먼저 와야 한다.
    #   꺼져 있으면(기본) 아무 일도 하지 않는다.
    items = _demo.rebase(items, "ts_utc")

    done = rs.reviewed_ids(db_path) if only_unreviewed else set()
    verdicts = {} if only_unreviewed else rs.current(
        db_path, [i["txn_id"] for i in items])

    out = []
    seen_txn: set = set()
    for it in items:
        if only_unreviewed and it["txn_id"] in done:
            continue
        # ── 같은 거래는 한 줄만 ──────────────────────────────
        #   원장은 append-only 라 같은 transaction_id 가 여러 줄일 수 있다
        #   (워처가 같은 파일을 재처리, 같은 건을 다시 탐지 등 — 실제로 이 DB에도
        #   3줄짜리 거래가 있다). 그런데 판정은 txn_id 단위(alert_review)라
        #   두 줄을 따로 찍을 수 없고, 화면에서는 위젯 key(`cb_{tid}`)가 겹쳐
        #   **StreamlitDuplicateElementKey 로 트리아지 탭 전체가 예외로 죽는다.**
        #   (표시 건수 100 에서 재현됐다.)
        #   id DESC 정렬이므로 첫 번째가 최신 상태 — 그것만 남긴다.
        #   재탐지 이력은 '탐지 로그'의 astore.history 가 따로 보여준다.
        if it["txn_id"] in seen_txn:
            continue
        seen_txn.add(it["txn_id"])
        it["시각"] = to_local(it["ts_utc"], off)
        it["risk_score"] = round(float(it["risk_score"] or 0), 4)
        v = verdicts.get(it["txn_id"])
        it["판정"] = rs.VERDICT_LABEL_KO.get(v["verdict"], "-") if v else "-"
        out.append(it)
        if len(out) >= limit:
            break
    return out


def live_feed(db_path: str | Path = DEFAULT_DB, limit: int = 30,
              only_anomaly: bool = False) -> list[dict]:
    """실시간 탐지 피드 — 관제 탭 상단에 흐르는 목록. 시각은 로컬로 정규화됨.

    필터를 alert_queue 에 넘긴다(파이썬에서 거르지 않는다) — 예전에는 12건을 뽑아
    이상거래만 남겨 **화면에 4건**만 흐르곤 했다.
    """
    return alert_queue(db_path, limit=limit, min_score=-1.0,
                       only_unreviewed=False, only_anomaly=only_anomaly)


def get_raw_row(db_path: str | Path = DEFAULT_DB, txn_id: str = "") -> dict | None:
    """단건 거래의 원본(마스킹됨) 피처 딕셔너리 — detections.raw_json에서 복원.

    AI 분석(LLMAnalyzer.analyze)이나 화면 상세 표시에 거래 피처(금액·채널·
    잔액·플래그 등)가 필요할 때 쓴다. detect_service._save_detections가 적재한
    값은 이미 PII 마스킹이 끝난 상태이므로 추가 마스킹 없이 그대로 써도 안전하다.
    같은 transaction_id로 여러 번 탐지됐다면 detections는 PRIMARY KEY UPSERT라
    가장 최근 값만 남아 있다 — 그게 곧 우리가 원하는 최신 상태다.
    """
    if not txn_id:
        return None
    try:
        con = _conn(db_path)
    except Exception as e:
        log.debug(f"DB 열기 실패: {e}")
        return None
    try:
        if "detections" not in _tables(con):
            return None
        row = con.execute(
            "SELECT raw_json FROM detections WHERE transaction_id=?", (txn_id,)
        ).fetchone()
        if not row or not row[0]:
            return None
        import json
        return json.loads(row[0])
    except Exception as e:
        log.debug(f"raw_json 조회 실패({txn_id}): {e}")
        return None
    finally:
        con.close()


# ══════════════════════════════════════════════════════════
# 오탐 분석
# ══════════════════════════════════════════════════════════

_BUCKET_FMT = {"hour": "%Y-%m-%d %H:00", "day": "%Y-%m-%d", "week": "%Y-W%W"}


def fp_timeline(db_path: str | Path = DEFAULT_DB, bucket: str = "day",
                since_hours: int = 720) -> list[dict]:
    """오탐률 추이. 판정 시각(alert_review.reviewed_at, UTC)이 기준이다.

    ⚠️ '탐지 시각'이 아니라 '판정 시각' 기준인 이유: 담당자가 며칠 밀렸다가
       몰아서 판정하면 탐지 시각 기준 그래프는 과거가 계속 바뀐다. 운영 지표는
       '언제 판정했는가'로 고정해야 지난주 수치가 이번 주에 흔들리지 않는다.
    """
    fmt = _BUCKET_FMT.get(bucket, _BUCKET_FMT["day"])
    if not rs.table_exists(db_path):
        return []
    off = tz_offset_seconds(db_path)
    try:
        con = _conn(db_path)
        rows = con.execute(
            f"""SELECT strftime(?, datetime(reviewed_at, ? )) AS b,
                       SUM(CASE WHEN verdict='tp' THEN 1 ELSE 0 END),
                       SUM(CASE WHEN verdict='fp' THEN 1 ELSE 0 END),
                       SUM(CASE WHEN verdict='fn' THEN 1 ELSE 0 END),
                       SUM(CASE WHEN verdict='unclear' THEN 1 ELSE 0 END)
                FROM {rs.TABLE}
                WHERE id IN (SELECT MAX(id) FROM {rs.TABLE} GROUP BY txn_id)
                  AND reviewed_at > datetime('now', ?)
                GROUP BY b ORDER BY b""",
            (fmt, f"+{off} seconds", f"-{int(since_hours)} hours")).fetchall()
        con.close()
    except Exception as e:
        log.debug(f"오탐 추이 조회 실패: {e}")
        return []
    out = []
    for b, tp, fp, fn, un in rows:
        judged = (tp or 0) + (fp or 0)
        out.append({"구간": b, "정탐": tp or 0, "오탐": fp or 0,
                    "미탐": fn or 0, "보류": un or 0,
                    "오탐률": round((fp or 0) / judged * 100, 1) if judged else None})
    return out


def fp_by_dimension(db_path: str | Path = DEFAULT_DB,
                    dim: str = "fraud_type",
                    since_hours: int | None = None) -> list[dict]:
    """차원별 오탐 집계. dim: fraud_type | tier | model | reviewer | score_bucket

    판정 당시 스냅샷(alert_review 안의 값)만 쓴다 — 원장을 JOIN 하면
    재탐지로 덮어써진 현재값이 섞여 들어와 과거 판정과 어긋난다.
    """
    if not rs.table_exists(db_path):
        return []
    if dim == "score_bucket":
        expr = ("CASE WHEN risk_score IS NULL THEN '(점수없음)' "
                "     WHEN risk_score < 0.2 THEN '0.0–0.2' "
                "     WHEN risk_score < 0.4 THEN '0.2–0.4' "
                "     WHEN risk_score < 0.6 THEN '0.4–0.6' "
                "     WHEN risk_score < 0.8 THEN '0.6–0.8' "
                "     ELSE '0.8–1.0' END")
    elif dim in ("fraud_type", "tier", "model", "reviewer", "reason"):
        expr = f"COALESCE({dim}, '(미상)')"
    else:
        return []
    sql = (f"SELECT {expr} AS d, "
           f" SUM(CASE WHEN verdict='tp' THEN 1 ELSE 0 END), "
           f" SUM(CASE WHEN verdict='fp' THEN 1 ELSE 0 END), COUNT(*) "
           f"FROM {rs.TABLE} "
           f"WHERE id IN (SELECT MAX(id) FROM {rs.TABLE} GROUP BY txn_id)")
    params: list = []
    if since_hours:
        sql += " AND reviewed_at > datetime('now', ?)"
        params.append(f"-{int(since_hours)} hours")
    sql += " GROUP BY d ORDER BY 3 DESC"
    try:
        con = _conn(db_path)
        rows = con.execute(sql, params).fetchall()
        con.close()
    except Exception as e:
        log.debug(f"차원별 집계 실패: {e}")
        return []
    out = []
    for d, tp, fp, n in rows:
        judged = (tp or 0) + (fp or 0)
        out.append({"구분": d, "정탐": tp or 0, "오탐": fp or 0, "전체": n,
                    "오탐률": round((fp or 0) / judged * 100, 1) if judged else None})
    return out


def threshold_whatif(db_path: str | Path = DEFAULT_DB,
                     grid: list[float] | None = None,
                     fp_cost: float = 30_000, fn_cost: float = 3_000_000,
                     since_hours: int | None = None) -> dict:
    """임계값 시뮬레이터 — **실제 담당자 판정** 기반.

    세션2의 비용곡선은 검증셋(정적 라벨) 기준이라 운영 분포와 다르다.
    여기서는 실제로 알림이 나갔고 사람이 정탐/오탐을 찍은 건들로 계산한다.

    🚨 선택 편향 경고 (반드시 화면에 같이 띄울 것)
      우리는 **실제로 알림이 발생한 거래만** 관측한다. 과거 th_review 아래로
      깔려서 알림이 안 간 거래에는 판정이 없다. 따라서:
        · τ ≥ (과거 최저 th_review) 구간 → 신뢰 가능. 알림을 줄였을 때의 효과를 봄
        · τ < (과거 최저 th_review) 구간 → **데이터 없음.** 새 알림이 얼마나
          늘지, 그중 몇 %가 오탐일지 이 데이터로는 알 수 없다
      valid_from 아래 구간은 회색 처리하거나 아예 그리지 말 것.

    반환: {"rows": [...], "valid_from": float|None, "n_judged": int, "warning": str}
    """
    grid = grid or [round(x / 20, 2) for x in range(1, 20)]     # 0.05 ~ 0.95
    if not rs.table_exists(db_path):
        return {"rows": [], "valid_from": None, "n_judged": 0,
                "warning": "판정 이력이 없습니다 — 트리아지 탭에서 몇 건 판정하면 곡선이 그려집니다"}

    sql = (f"SELECT verdict, risk_score, th_review FROM {rs.TABLE} "
           f"WHERE id IN (SELECT MAX(id) FROM {rs.TABLE} GROUP BY txn_id) "
           f"  AND verdict IN ('tp','fp') AND risk_score IS NOT NULL")
    params: list = []
    if since_hours:
        sql += " AND reviewed_at > datetime('now', ?)"
        params.append(f"-{int(since_hours)} hours")
    try:
        con = _conn(db_path)
        rows = con.execute(sql, params).fetchall()
        con.close()
    except Exception as e:
        return {"rows": [], "valid_from": None, "n_judged": 0,
                "warning": f"조회 실패: {e}"}

    judged = [(v, float(s), (float(t) if t is not None else None)) for v, s, t in rows]
    if not judged:
        return {"rows": [], "valid_from": None, "n_judged": 0,
                "warning": "점수 스냅샷이 있는 판정이 없습니다 "
                           "(구버전 판정 행에는 risk_score 가 비어 있을 수 있습니다)"}

    ths = [t for _, _, t in judged if t is not None]
    valid_from = min(ths) if ths else None

    out = []
    for tau in grid:
        fired_tp = sum(1 for v, s, _ in judged if s >= tau and v == "tp")
        fired_fp = sum(1 for v, s, _ in judged if s >= tau and v == "fp")
        missed_tp = sum(1 for v, s, _ in judged if s < tau and v == "tp")
        fired = fired_tp + fired_fp
        out.append({
            "임계값": tau,
            "알림건수": fired,
            "정탐": fired_tp,
            "오탐": fired_fp,
            "놓친사기": missed_tp,
            "정밀도": round(fired_tp / fired * 100, 1) if fired else None,
            "오탐률": round(fired_fp / fired * 100, 1) if fired else None,
            "기대비용": round(fired_fp * fp_cost + missed_tp * fn_cost),
            "신뢰가능": (valid_from is None or tau >= valid_from),
        })

    warn = ""
    if valid_from is not None:
        warn = (f"⚠️ 이 곡선은 임계값 {valid_from:.2f} 이상에서만 신뢰할 수 있습니다. "
                f"그 아래로 내렸을 때 새로 발생할 알림은 판정 데이터가 없어 "
                f"추정 불가입니다(관측된 건 = 실제로 알림이 나간 건뿐).")
    return {"rows": out, "valid_from": valid_from,
            "n_judged": len(judged), "warning": warn}


def threshold_whatif_fn(db_path: str | Path = DEFAULT_DB,
                        grid: list[float] | None = None,
                        fp_cost: float = 30_000, fn_cost: float = 3_000_000,
                        since_hours: int | None = None) -> dict:
    """**등록된 미탐(FN)까지 넣어 계산하는 두 번째 곡선.**

    왜 별도 함수인가 — 이 프로젝트에는 이미 임계값 숫자가 두 개 있다.
      ① tools/threshold_report.py : 검증셋(정답 라벨)으로 계산. 현재 운영값
         th_review=0.005 가 여기서 나왔다. 모든 FN 을 알고 있다.
      ② threshold_whatif()        : 운영 판정(tp/fp)으로 계산. 알림이 나간 건만
         관측하므로 FN 을 구조적으로 볼 수 없다.
    여기에 세 번째를 **덮어쓰기로** 넣으면 "어제 본 추천치와 오늘 값이 다른데
    무엇이 바뀐 건지 모르는" 상태가 된다. 그래서 ②를 한 줄도 건드리지 않고
    옆에 나란히 두는 쪽을 택했다 — 화면도 두 곡선을 겹쳐 그린다.

    계산 (τ = 임계값)
      · 관측된 정탐/오탐 : 기존과 동일하게 s >= τ 면 발생
      · 등록된 미탐      : 점수 s 가 있으면
          s >= τ  → 그 임계값이었다면 **잡혔을** 건이다 (정탐 + 알림 1건 추가)
          s <  τ  → 여전히 놓친다 (미탐 유지)
      · 점수가 없는 미탐(원장에 없는 거래)은 곡선에 올릴 수 없다 —
        버리지 않고 n_fn_unscored 로 따로 돌려준다.

    이 곡선을 읽는 법 — 두 가지를 헷갈리면 안 된다
      ① **높이(level)는 항상 ②보다 높거나 같다.** 당연하다. ②가 아예 보지 못했던
         실제 미탐을 비용에 더하는 것이니까. "FN 을 넣었더니 비용이 올랐다"는
         버그가 아니라 정상이다 — 원래 있던 손실이 이제 보이는 것뿐이다.
      ② **쓸모 있는 것은 최소점의 위치**다. 낮은 임계값에서 회수되는 사기가
         계산에 들어오므로, 최소비용 지점이 ② 대비 **왼쪽으로(더 낮은 쪽으로)**
         움직인다. 임계값을 내릴 근거는 바로 이 이동이다.

    🚨 비대칭 경고 (호출부가 반드시 화면에 띄울 것)
      미탐 데이터는 임계값을 내렸을 때의 **이득만** 알려준다. 내려서 새로 올라올
      **오탐이 몇 건일지는 여전히 아무도 모른다**(관측된 적이 없다). 즉 이 곡선은
      valid_from 아래에서 '내리는 비용'을 과소평가한다 — 최소점이 왼쪽으로 간
      만큼을 그대로 믿으면 안 되고, 방향의 근거로만 쓸 것.

    반환: threshold_whatif() 의 키 + base / n_fn / n_fn_unscored / optimistic_below
    """
    base = threshold_whatif(db_path, grid=grid, fp_cost=fp_cost,
                            fn_cost=fn_cost, since_hours=since_hours)
    out = {**base, "base": base["rows"], "n_fn": 0, "n_fn_unscored": 0,
           "optimistic_below": base["valid_from"]}
    if not base["rows"]:
        return out

    sql = (f"SELECT risk_score FROM {rs.TABLE} "
           f"WHERE id IN (SELECT MAX(id) FROM {rs.TABLE} GROUP BY txn_id) "
           f"  AND verdict='fn'")
    params: list = []
    if since_hours:
        sql += " AND reviewed_at > datetime('now', ?)"
        params.append(f"-{int(since_hours)} hours")
    try:
        con = _conn(db_path)
        rows = con.execute(sql, params).fetchall()
        con.close()
    except Exception as e:
        out["warning"] = (out.get("warning") or "") + f" · 미탐 조회 실패: {e}"
        return out

    fn_scores = [float(r[0]) for r in rows if r[0] is not None]
    out["n_fn"] = len(rows)
    out["n_fn_unscored"] = len(rows) - len(fn_scores)
    if not fn_scores:
        return out

    new_rows = []
    for r in base["rows"]:
        tau = r["임계값"]
        caught = sum(1 for s in fn_scores if s >= tau)      # 이 τ 였다면 잡혔을 사기
        still = len(fn_scores) - caught                     # 여전히 놓치는 사기
        fired_tp = (r["정탐"] or 0) + caught
        fired_fp = r["오탐"] or 0                            # 미탐은 오탐을 늘리지 않는다
        fired = fired_tp + fired_fp
        missed = (r["놓친사기"] or 0) + still
        new_rows.append({
            **r,
            "알림건수": fired, "정탐": fired_tp, "놓친사기": missed,
            "정밀도": round(fired_tp / fired * 100, 1) if fired else None,
            "오탐률": round(fired_fp / fired * 100, 1) if fired else None,
            "기대비용": round(fired_fp * fp_cost + missed * fn_cost),
            "미탐반영": caught,
        })
    out["rows"] = new_rows
    return out


def coverage(db_path: str | Path = DEFAULT_DB, since_hours: int = 168,
             min_score: float = 0.0) -> dict:
    """판정 커버리지 — 알림 중 몇 %가 검토됐나. **오탐률의 신뢰도 척도**다.

    커버리지가 20% 인데 오탐률 5% 라고 하면 그 5%는 아무 의미가 없다
    (검토하기 쉬운 건만 골라 판정했을 가능성이 높다). 그래서 오탐률을 표시할 때는
    반드시 커버리지를 옆에 붙여야 한다.

    🐛 FIX: 초기 구현은 분자를 rs.counts()(=전체 판정 건수), 분모를 is_anomaly=1
       건수로 잡아 **커버리지가 100%를 넘었다.** 창(window) 밖 판정과 알림이 아닌
       거래의 판정까지 분자에 들어갔기 때문이다.
       → 분자·분모를 같은 알림 집합에서 뽑도록 고쳤다.
         '이번 창의 알림 중, 판정이 하나라도 달린 건'만 분자다.
    """
    off = tz_offset_seconds(db_path)
    alert_ids: set[str] = set()
    try:
        con = _conn(db_path)
        tbl, m = _ledger(con)
        if tbl:
            ts_utc = utc_expr(m["ts"], declared_tz(db_path, tbl, m["ts"]), off)
            rows = con.execute(
                f"SELECT DISTINCT {m['txn']} FROM {tbl} "
                f"WHERE ({m['anom']}=1 OR {m['score']} >= ?) "
                f"  AND {ts_utc} > datetime('now', ?) AND {m['txn']} IS NOT NULL",
                (float(min_score), f"-{int(since_hours)} hours")).fetchall()
            alert_ids = {r[0] for r in rows}
        con.close()
    except Exception as e:
        log.debug(f"커버리지 조회 실패: {e}")

    total = len(alert_ids)
    if not total:
        return {"알림": 0, "판정": 0, "커버리지": None, "오탐률": None,
                "신뢰도": "표본없음"}

    # 이 알림들에 달린 최신 판정만 본다 (판정 시각은 창 밖이어도 유효)
    verdicts = rs.current(db_path, list(alert_ids))
    reviewed = len(verdicts)
    tp = sum(1 for v in verdicts.values() if v["verdict"] == "tp")
    fp = sum(1 for v in verdicts.values() if v["verdict"] == "fp")
    judged = tp + fp
    cov = reviewed / total
    return {
        "알림": total, "판정": reviewed,
        "커버리지": round(cov * 100, 1),
        "오탐률": round(fp / judged * 100, 1) if judged else None,
        "신뢰도": ("높음" if cov >= 0.7 else "보통" if cov >= 0.3 else "낮음"),
        "_note": ("커버리지가 낮으면 오탐률은 참고용입니다 — "
                  "검토가 쉬운 건에 판정이 몰렸을 수 있습니다") if cov < 0.3 else "",
    }


# ── CLI 확인용:  python -m pipeline.ops_queries [db] ──
if __name__ == "__main__":
    import sys
    db = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DB
    print(f"ops_queries {OPS_QUERIES_VERSION} · DB={db} · "
          f"로컬오프셋 {tz_offset_seconds(db)}초")
    print("\n🩺 시간대 진단")
    for d in diagnose_timestamps(db):
        flag = "  ⚠️ 불일치" if d["불일치"] else ""
        print(f"  {d['테이블']}.{d['컬럼']:14s} 선언={d['선언']:6s} "
              f"관측={d['관측']:6s} 행={d['행수']}{flag}")
    print("\n📋 판정 대기 큐")
    for r in alert_queue(db, limit=5):
        print("  ", r)
    print("\n📊 커버리지:", coverage(db))

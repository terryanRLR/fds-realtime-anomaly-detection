"""
analysis_store — 탐지 시점 분석 결과 캐시 (analysis_cache 테이블)  ✨ v21 신규

메우려는 구멍
  detect_service.detect() 는 거래 1건마다 이만큼을 계산한다:

      det["proba"]   13클래스 확률 분포
      det["llm"]     {"analysis", "slack", "email", "ctx"}  ← LLM 리포트 전문
      det["tier"] / ["errors"] / ["elapsed"]
      masked         마스킹된 원거래 내역
      rag_ctx        RAG 근거 문서

  그런데 _save_db() 가 남기는 것은 6개 컬럼뿐이다 —
  fraud_type · risk_score · is_anomaly · model · threshold · raw_json.

  **LLM 이 쓴 판정 근거·이상 패턴·오탐 체크·권장 조치는 Slack 을 보내는 순간 사라진다.**
  LLM 을 돌리는 이유 자체가 그 분석인데 DB 에 한 글자도 남지 않는다.

  결과적으로 사흘 뒤 담당자는 "위험 0.72, 유형 f" 만 보고 정탐/오탐을 찍어야 한다.
  게다가 재검증 경로는 마스킹 훼손으로 막혀 있다(ops_recheck.mask_damage).
  → **탐지 시점에 캐시하는 것이 근거를 남기는 유일한 방법이다.**

설계 원칙
  1. 추가 전용 — review_store 와 같다. 재분석하면 새 행이 쌓이고 최신이 현재다.
     (detections 의 UPSERT 로 근거가 덮어써지는 사고를 반복하지 않는다)
  2. 시각은 UTC — captured_at 은 datetime('now') 고정.
  3. 페이로드는 zlib 압축 — LLM 리포트는 건당 1~4KB 다. 하루 100건이면 1년에 100MB 를
     넘는다. 압축하면 3분의 1 이하로 줄고, 무인 운영에서 디스크는 조용히 차오른다.
  4. 저장 직전 한 번 더 마스킹 — 심층 방어. 호출부가 원본을 넘겨도 평문이 쌓이지 않는다.
  5. 실패해도 탐지를 막지 않는다 — 캐시는 부가 기능이다. 저장이 실패했다고
     알림이 안 나가면 본말전도다. 모든 쓰기가 try/except 로 격리된다.

워처에 붙이는 법 (파일 수정 없이)
    from pipeline import analysis_store as astore
    astore.attach(svc)          # DetectService 인스턴스를 감싼다
  또는 프로세스 전역으로
    astore.install()            # DetectService 클래스 자체를 감싼다

핵심 API
    ensure_schema(db)
    attach(svc) / install()          # 캡처 훅
    save(db, det, row, svc=None)     # 수동 저장
    load(db, txn_id)                 # 최신 분석 1건
    history(db, txn_id)              # 재분석 이력
    log_rows(db, ...)                # 로그 브라우저용 목록
    stats(db) / prune(db, days)      # 용량 관리
"""

from __future__ import annotations

import json
import zlib
import sqlite3
import logging
from pathlib import Path

log = logging.getLogger(__name__)

ANALYSIS_STORE_VERSION = "v21"
SCHEMA_VER = "1"
TABLE = "analysis_cache"
DEFAULT_DB = "fds_results.db"

# 필드별 상한 — LLM 이 폭주해도 DB 를 망가뜨리지 않게. 잘리면 말미에 표시가 붙는다.
MAX_TEXT = 24_000          # analysis / email 본문
MAX_SLACK = 8_000
MAX_PAYLOAD = 512_000      # 압축 전 전체 JSON
COMPRESS_OVER = 1_024      # 이보다 크면 zlib

_SCHEMA_DONE: set[str] = set()

try:
    from pipeline.pii_masker import PIIMasker
except ImportError:                                    # pragma: no cover
    try:
        from pii_masker import PIIMasker
    except ImportError:
        PIIMasker = None


# ══════════════════════════════════════════════════════════
# 스키마
# ══════════════════════════════════════════════════════════

_DDL = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    txn_id       TEXT    NOT NULL,
    alert_ref    INTEGER,
    captured_at  TEXT    NOT NULL,   -- ⚠ UTC 고정
    -- 판정 결과
    fraud_type   TEXT,
    risk_score   REAL,
    tier         TEXT,
    is_anomaly   INTEGER,
    -- 당시 환경 (나중에 "왜 이 판정이었나"를 되짚는 데 필수)
    model        TEXT,
    clf_mode     TEXT,
    th_review    REAL,
    th_confirm   REAL,
    pii_level    TEXT,
    llm_provider TEXT,
    llm_model    TEXT,
    llm_used     INTEGER DEFAULT 0,
    -- 본문
    payload      BLOB,               -- JSON (필요 시 zlib)
    payload_enc  TEXT,               -- json | zlib
    size_raw     INTEGER,
    -- 메타
    source       TEXT,
    elapsed      REAL,
    n_errors     INTEGER DEFAULT 0,
    schema_ver   TEXT
)
"""

_INDEXES = (
    f"CREATE INDEX IF NOT EXISTS idx_{TABLE}_txn ON {TABLE}(txn_id)",
    f"CREATE INDEX IF NOT EXISTS idx_{TABLE}_at  ON {TABLE}(captured_at)",
    f"CREATE INDEX IF NOT EXISTS idx_{TABLE}_ref ON {TABLE}(alert_ref)",
)


def _conn(db_path, readonly: bool = False) -> sqlite3.Connection:
    db_path = str(db_path)
    if readonly:
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


def ensure_schema(db_path=DEFAULT_DB) -> bool:
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
        log.error(f"{TABLE} 스키마 생성 실패: {type(e).__name__}: {e}")
        return False


def table_exists(db_path=DEFAULT_DB) -> bool:
    try:
        con = _conn(db_path, readonly=True)
        r = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                        (TABLE,)).fetchone()
        con.close()
        return r is not None
    except Exception:
        return False


# ══════════════════════════════════════════════════════════
# 페이로드
# ══════════════════════════════════════════════════════════

def _clip(s, n: int) -> str:
    s = "" if s is None else str(s)
    return s if len(s) <= n else s[:n] + f"\n\n…(이하 {len(s)-n:,}자 생략)"


def _mask(row: dict, level: str = "standard") -> dict:
    """저장 직전 마스킹 — 심층 방어.

    detect_service 는 이미 마스킹본을 LLM 에 넘기지만, 대시보드 경로
    (dashboard._save_detection_to_db)는 원본을 그대로 넣는다.
    여기서 한 번 더 통과시켜야 어느 경로로 들어와도 평문이 쌓이지 않는다.
    """
    if not row:
        return {}
    if PIIMasker is None or level == "off":
        return {k: v for k, v in row.items() if not str(k).startswith("_")}
    try:
        return PIIMasker(level=level).mask_row(
            {k: v for k, v in row.items() if not str(k).startswith("_")})
    except Exception as e:
        log.warning(f"캐시 마스킹 실패(필드 제외): {e}")
        return {}


def _pack(obj: dict) -> tuple[bytes, str, int]:
    """JSON → (bytes, 인코딩, 원본크기). 큰 것만 압축한다."""
    raw = json.dumps(obj, ensure_ascii=False, default=str)
    if len(raw) > MAX_PAYLOAD:
        obj = dict(obj)
        obj["_truncated"] = f"페이로드 {len(raw):,}자 → 상한 {MAX_PAYLOAD:,}자 초과로 축약"
        for k in ("rag", "rule", "notify"):
            obj.pop(k, None)
        raw = json.dumps(obj, ensure_ascii=False, default=str)[:MAX_PAYLOAD]
    b = raw.encode("utf-8")
    if len(b) > COMPRESS_OVER:
        return zlib.compress(b, 6), "zlib", len(b)
    return b, "json", len(b)


def _unpack(blob, enc: str) -> dict:
    try:
        if blob is None:
            return {}
        b = bytes(blob)
        if enc == "zlib":
            b = zlib.decompress(b)
        return json.loads(b.decode("utf-8"))
    except Exception as e:
        log.warning(f"페이로드 해제 실패: {type(e).__name__}: {e}")
        return {"_error": f"페이로드를 읽을 수 없습니다: {e}"}


# ══════════════════════════════════════════════════════════
# 저장
# ══════════════════════════════════════════════════════════

def save(db_path, det: dict, row: dict | None = None, svc=None,
         alert_ref: int | None = None, extra: dict | None = None) -> tuple[bool, str]:
    """탐지 결과 1건을 캐시한다. det 는 DetectService.detect() 반환 dict.

    실패해도 예외를 던지지 않는다 — 캐시 때문에 알림이 막히면 본말전도다.
    """
    if not det:
        return False, "저장할 결과가 없습니다"
    if not ensure_schema(db_path):
        return False, "캐시 테이블을 만들 수 없습니다"

    cfg = getattr(svc, "cfg", None)
    pii_level = getattr(cfg, "pii_level", "standard") if cfg else "standard"
    llm = det.get("llm") or {}

    payload = {
        "row": _mask(row or {}, pii_level),
        "proba": {str(k): round(float(v), 6) for k, v in (det.get("proba") or {}).items()},
        "llm": {
            "analysis": _clip(llm.get("analysis"), MAX_TEXT),
            "slack": _clip(llm.get("slack"), MAX_SLACK),
            "email": _clip(llm.get("email"), MAX_TEXT),
            "ctx": llm.get("ctx") if isinstance(llm.get("ctx"), (list, dict)) else None,
        },
        "errors": list(det.get("errors") or [])[:20],
        "notify": {"tier": det.get("tier"), "slack": bool(det.get("sent_slack")),
                   "email": bool(det.get("sent_email")),
                   "deduped": bool(det.get("deduped"))},
        "fraud_name": det.get("fraud_name"),
    }
    if extra:
        payload.update({k: v for k, v in extra.items() if k not in payload})

    blob, enc, size = _pack(payload)
    try:
        con = _conn(db_path)
        con.execute(
            f"""INSERT INTO {TABLE}
                (txn_id, alert_ref, captured_at, fraud_type, risk_score, tier,
                 is_anomaly, model, clf_mode, th_review, th_confirm, pii_level,
                 llm_provider, llm_model, llm_used, payload, payload_enc, size_raw,
                 source, elapsed, n_errors, schema_ver)
                VALUES (?,?,datetime('now'),?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (str(det.get("txn_id") or "-"), alert_ref,
             det.get("fraud_type"), _f(det.get("risk_score")), det.get("tier"),
             int(bool(det.get("is_anomaly"))),
             getattr(svc, "clf_mode", None) or (det.get("model")),
             getattr(svc, "clf_mode", None),
             _f(getattr(cfg, "th_review", None)), _f(getattr(cfg, "th_confirm", None)),
             pii_level,
             getattr(cfg, "llm_provider", None), getattr(cfg, "llm_model", None),
             int(bool(det.get("llm_used"))),
             sqlite3.Binary(blob), enc, size,
             det.get("source"), _f(det.get("elapsed")),
             len(det.get("errors") or []), SCHEMA_VER))
        con.commit()
        con.close()
        return True, f"분석 캐시 저장 ({size:,}B → {len(blob):,}B, {enc})"
    except Exception as e:
        log.warning(f"분석 캐시 저장 실패({det.get('txn_id')}): {type(e).__name__}: {e}")
        return False, f"저장 실패: {type(e).__name__}: {e}"


def _f(v):
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


# ══════════════════════════════════════════════════════════
# 캡처 훅 — 기존 파일을 수정하지 않고 붙인다
# ══════════════════════════════════════════════════════════

def attach(svc, db_path: str | None = None):
    """DetectService **인스턴스**의 detect() 를 감싸 결과를 캐시한다.

    워처에 2줄만 추가하면 된다:
        from pipeline import analysis_store as astore
        astore.attach(svc)

    ⚠️ 캡처는 반드시 **워처 프로세스 안에서** 일어나야 한다.
       LLM 리포트는 그 순간 그 프로세스의 메모리에만 존재하고,
       DB 에는 애초에 기록되지 않으므로 대시보드가 나중에 주워올 수 없다.
    """
    if getattr(svc, "_astore_attached", False):
        return svc
    db = db_path or getattr(getattr(svc, "cfg", None), "db_path", DEFAULT_DB)
    orig = svc.detect

    def wrapped(row, source="watcher"):
        det = orig(row, source)
        try:
            # 이상거래가 아니면 LLM 도 안 돌았고 남길 근거도 없다 — 용량만 먹는다
            if det and det.get("is_anomaly"):
                save(db, det, row, svc)
        except Exception as e:                          # pragma: no cover
            log.debug(f"캐시 훅 실패(탐지는 정상): {e}")
        return det

    svc.detect = wrapped
    svc._astore_attached = True
    ensure_schema(db)
    log.info(f"📼 분석 캐시 훅 부착 — {db}")
    return svc


def install(db_path: str | None = None) -> bool:
    """DetectService **클래스** 자체를 감싼다 (이후 만들어지는 모든 인스턴스에 적용).

    워처 코드에 손을 못 대는 상황에서 진입점 스크립트로 감쌀 때 쓴다.
    """
    try:
        try:
            from pipeline.detect_service import DetectService
        except ImportError:
            from detect_service import DetectService
    except ImportError as e:
        log.error(f"DetectService 를 찾지 못했습니다: {e}")
        return False
    if getattr(DetectService, "_astore_installed", False):
        return True
    orig = DetectService.detect

    def wrapped(self, row, source="watcher"):
        det = orig(self, row, source)
        try:
            if det and det.get("is_anomaly"):
                save(db_path or getattr(self.cfg, "db_path", DEFAULT_DB), det, row, self)
        except Exception as e:                          # pragma: no cover
            log.debug(f"캐시 훅 실패(탐지는 정상): {e}")
        return det

    DetectService.detect = wrapped
    DetectService._astore_installed = True
    log.info("📼 분석 캐시 훅 설치 (클래스 레벨)")
    return True


# ══════════════════════════════════════════════════════════
# 조회
# ══════════════════════════════════════════════════════════

_META = ("id", "txn_id", "alert_ref", "captured_at", "fraud_type", "risk_score",
         "tier", "is_anomaly", "model", "clf_mode", "th_review", "th_confirm",
         "pii_level", "llm_provider", "llm_model", "llm_used", "size_raw",
         "source", "elapsed", "n_errors", "schema_ver")


def load(db_path, txn_id: str) -> dict | None:
    """해당 거래의 **최신** 분석 캐시 (메타 + 페이로드 전개)."""
    if not table_exists(db_path):
        return None
    try:
        con = _conn(db_path, readonly=True)
        r = con.execute(
            f"SELECT {', '.join(_META)}, payload, payload_enc FROM {TABLE} "
            f"WHERE txn_id=? ORDER BY id DESC LIMIT 1", (str(txn_id),)).fetchone()
        con.close()
        if not r:
            return None
        d = dict(zip(_META, r[:len(_META)]))
        d.update(_unpack(r[-2], r[-1]))
        return d
    except Exception as e:
        log.debug(f"분석 캐시 조회 실패({txn_id}): {e}")
        return None


def history(db_path, txn_id: str) -> list[dict]:
    """재분석 이력 (오래된 → 최신). 메타만 — 본문은 load() 로."""
    if not table_exists(db_path):
        return []
    try:
        con = _conn(db_path, readonly=True)
        rows = con.execute(
            f"SELECT {', '.join(_META)} FROM {TABLE} WHERE txn_id=? ORDER BY id",
            (str(txn_id),)).fetchall()
        con.close()
        return [dict(zip(_META, r)) for r in rows]
    except Exception:
        return []


def cached_ids(db_path, txn_ids: list[str] | None = None) -> set[str]:
    """캐시가 있는 거래 ID — 로그 목록에 📼 배지를 붙이는 용도."""
    if not table_exists(db_path):
        return set()
    try:
        con = _conn(db_path, readonly=True)
        if txn_ids:
            ids = [str(x) for x in txn_ids if x][:900]
            if not ids:
                return set()
            rows = con.execute(
                f"SELECT DISTINCT txn_id FROM {TABLE} "
                f"WHERE txn_id IN ({','.join('?'*len(ids))})", ids).fetchall()
        else:
            rows = con.execute(f"SELECT DISTINCT txn_id FROM {TABLE}").fetchall()
        con.close()
        return {r[0] for r in rows}
    except Exception:
        return set()


def stats(db_path=DEFAULT_DB) -> dict:
    """용량·보존 현황. 무인 운영에서 디스크는 조용히 차오른다."""
    if not table_exists(db_path):
        return {"rows": 0, "txns": 0, "stored_mb": 0.0, "raw_mb": 0.0,
                "ratio": None, "oldest": None, "newest": None}
    try:
        con = _conn(db_path, readonly=True)
        r = con.execute(
            f"SELECT COUNT(*), COUNT(DISTINCT txn_id), "
            f"       COALESCE(SUM(LENGTH(payload)),0), COALESCE(SUM(size_raw),0), "
            f"       MIN(captured_at), MAX(captured_at) FROM {TABLE}").fetchone()
        con.close()
        n, ntx, stored, raw, old, new = r
        return {"rows": n, "txns": ntx,
                "stored_mb": round(stored / 1e6, 2), "raw_mb": round(raw / 1e6, 2),
                "ratio": round(stored / raw, 3) if raw else None,
                "oldest": old, "newest": new}
    except Exception as e:
        log.debug(f"캐시 통계 실패: {e}")
        return {"rows": 0, "txns": 0, "stored_mb": 0.0, "raw_mb": 0.0,
                "ratio": None, "oldest": None, "newest": None}


def prune(db_path, keep_days: int = 180,
          keep_reviewed: bool = True) -> tuple[int, str]:
    """오래된 캐시 삭제. (삭제 건수, 메시지)

    keep_reviewed=True 면 **판정이 달린 거래는 남긴다** —
    그 근거는 감사 자료이자 재학습 라벨의 출처라 나이로 지우면 안 된다.
    """
    if not table_exists(db_path):
        return 0, "캐시 테이블이 없습니다"
    try:
        con = _conn(db_path)
        q = f"DELETE FROM {TABLE} WHERE captured_at < datetime('now', ?)"
        params = [f"-{int(keep_days)} days"]
        has_review = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='alert_review'"
        ).fetchone()
        if keep_reviewed and has_review:
            q += " AND txn_id NOT IN (SELECT DISTINCT txn_id FROM alert_review)"
        cur = con.execute(q, params)
        n = cur.rowcount
        con.commit()
        try:
            con.execute("VACUUM")       # 실제 파일 크기를 줄인다
        except Exception:
            pass
        con.close()
        return n, (f"{n:,}건 삭제 ({keep_days}일 이전"
                   + (", 판정된 건은 보존)" if keep_reviewed and has_review else ")"))
    except Exception as e:
        return 0, f"정리 실패: {type(e).__name__}: {e}"


# ── CLI:  python -m pipeline.analysis_store [db] [txn_id] ──
if __name__ == "__main__":
    import sys
    db = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DB
    print(f"analysis_store {ANALYSIS_STORE_VERSION} · DB={db}")
    s = stats(db)
    print(f"  캐시 {s['rows']:,}건 / 거래 {s['txns']:,}건 · "
          f"저장 {s['stored_mb']}MB (원본 {s['raw_mb']}MB, 압축률 {s['ratio']})")
    print(f"  기간 {s['oldest']} ~ {s['newest']} (UTC)")
    if len(sys.argv) > 2:
        d = load(db, sys.argv[2])
        print(json.dumps(d, ensure_ascii=False, indent=2, default=str)[:2000]
              if d else "  (캐시 없음)")

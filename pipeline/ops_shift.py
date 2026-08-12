"""
ops_shift — SLA 경과시간 · 교대 인수인계

관제 도구가 "혼자서도 돌아가려면" 답해야 하는 두 질문을 담당한다.

  ③ 지금 급한 게 뭔가?      — 알림이 뜬 지 몇 분 지났나, 약속한 시간을 넘긴 건 몇 건인가
  ④ 다음 사람에게 뭘 넘기나? — 내 근무 동안 무슨 일이 있었고, 뭘 남기고 가나

왜 '경과시간'이 필요한가
  지금까지 트리아지 큐는 **미판정 여부**만 봤다. 그래서 3분 전 알림과 6시간 전
  알림이 같은 모습으로 나란히 있었다. 관제에서 중요한 것은 "판정했나"가 아니라
  "얼마나 오래 방치됐나"다 — 오래된 알림일수록 이미 돈이 빠져나갔을 확률이 높다.

시간 규약 (여기서 틀리면 전부 틀린다)
  DB 의 reviewed_at · ts_utc 는 **UTC 문자열**이다. 파이썬에서 비교할 때
  naive datetime 으로 now() 를 쓰면 로컬시각과 섞여 9시간이 통째로 어긋난다.
  이 모듈은 UTC 로만 계산하고, 표시 직전에만 사람 말로 바꾼다.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

OPS_SHIFT_VERSION = "v2"

log = logging.getLogger("ops_shift")

try:
    from pipeline import review_store as rs
except ImportError:                                    # pragma: no cover
    import review_store as rs

HANDOVER_TABLE = "shift_handover"

# 기본 SLA — 알림이 뜬 뒤 이 시간 안에 판정한다는 약속(분)
DEFAULT_SLA_MIN = 30


# ══════════════════════════════════════════════════════════
# 시간 계산
# ══════════════════════════════════════════════════════════
def _parse_utc(ts) -> datetime | None:
    """'2026-08-08 10:25:14' / ISO 문자열 → tz-aware UTC datetime.
    DB 가 돌려주는 값은 tz 표기가 없는 UTC 라, 명시적으로 UTC 를 붙여준다."""
    if ts is None or ts == "":
        return None
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    s = str(ts).strip().replace("T", " ")
    if s.endswith("Z"):
        s = s[:-1]
    if "+" in s[10:]:
        s = s[:s.rindex("+")]
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
                "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    log.debug(f"시각 파싱 실패: {ts!r}")
    return None


def age_minutes(ts_utc) -> float | None:
    """UTC 시각 문자열 → 지금까지 몇 분 지났나. 파싱 실패 시 None."""
    dt = _parse_utc(ts_utc)
    if dt is None:
        return None
    delta = (datetime.now(timezone.utc) - dt).total_seconds() / 60.0
    return max(0.0, delta)          # 시계 오차로 음수가 나와도 '미래'는 표시하지 않는다


# 경과시간 단위 — (방금, 분, 시간, 일)
#   ⚠ 이 문자열은 헤더 배지 '최장 대기' · 트리아지 행 · 교대 요약에 모두 나온다.
#     화면에서 가장 자주 보이는 축에 속해, 여기가 한국어로 남으면 다른 언어에서
#     "Longest wait: 5일 15시간" 처럼 한 줄 안에서 언어가 섞인다.
_ELAPSED = {
    "ko": ("방금", "{n}분", "{n}시간", "{n}일"),
    "en": ("just now", "{n}m", "{n}h", "{n}d"),
    "ja": ("たった今", "{n}分", "{n}時間", "{n}日"),
    "zh": ("刚刚", "{n}分钟", "{n}小时", "{n}天"),
}


def elapsed_label(minutes: float | None, lang: str = "ko") -> str:
    """분 → 사람 말. '방금 · 7분 · 2시간 10분 · 1일 3시간'

    lang 을 생략하면 한국어 — 기존 호출부(인수인계서 본문 등)가 그대로 돈다.
    """
    if minutes is None:
        return "—"
    now_s, min_s, hr_s, day_s = _ELAPSED.get(lang, _ELAPSED["ko"])
    m = int(minutes)
    if m < 1:
        return now_s
    if m < 60:
        return min_s.format(n=m)
    h, mm = divmod(m, 60)
    if h < 24:
        return hr_s.format(n=h) + (" " + min_s.format(n=mm) if mm else "")
    d, hh = divmod(h, 24)
    return day_s.format(n=d) + (" " + hr_s.format(n=hh) if hh else "")


def urgency(minutes: float | None, sla_min: int = DEFAULT_SLA_MIN) -> str:
    """'ok' | 'warn' | 'over' — SLA 대비 상태. warn 은 80% 소진 지점."""
    if minutes is None:
        return "ok"
    if minutes >= sla_min:
        return "over"
    if minutes >= sla_min * 0.8:
        return "warn"
    return "ok"


# ══════════════════════════════════════════════════════════
# 큐 주석 · 통계
# ══════════════════════════════════════════════════════════
def annotate(queue: list[dict], sla_min: int = DEFAULT_SLA_MIN,
             lang: str = "ko") -> list[dict]:
    """알림 큐 각 행에 age_min · elapsed · urgency 를 붙인다 (원본을 수정).
    ts_utc 가 없으면 조용히 None 으로 둔다 — 큐가 통째로 비는 것보다 낫다."""
    for r in queue or []:
        a = age_minutes(r.get("ts_utc"))
        r["age_min"] = a
        r["elapsed"] = elapsed_label(a, lang)
        r["urgency"] = urgency(a, sla_min)
    return queue


def sla_stats(queue: list[dict], sla_min: int = DEFAULT_SLA_MIN) -> dict:
    """큐 전체의 SLA 현황. annotate() 를 먼저 부르지 않아도 동작한다."""
    ages = []
    for r in queue or []:
        a = r.get("age_min", "__missing__")
        if a == "__missing__":
            a = age_minutes(r.get("ts_utc"))
        if a is not None:
            ages.append(a)
    n_over = sum(1 for a in ages if a >= sla_min)
    n_warn = sum(1 for a in ages if sla_min * 0.8 <= a < sla_min)
    ages_sorted = sorted(ages)
    median = ages_sorted[len(ages_sorted) // 2] if ages_sorted else None
    return {
        "pending": len(queue or []),
        "measurable": len(ages),
        "over": n_over,
        "warn": n_warn,
        "oldest_min": max(ages) if ages else None,
        "median_min": median,
        "sla_min": int(sla_min),
    }


def sort_by_urgency(queue: list[dict]) -> list[dict]:
    """오래 기다린 것부터. '무엇을 먼저 볼까'의 기본값은 점수가 아니라 대기시간이다
    — 점수 높은 건은 이미 누가 봤을 확률이 높고, 방치된 건은 아무도 안 봤다."""
    return sorted(queue or [],
                  key=lambda r: (r.get("age_min") if r.get("age_min") is not None
                                 else age_minutes(r.get("ts_utc")) or 0),
                  reverse=True)


# ══════════════════════════════════════════════════════════
# 교대 인수인계
# ══════════════════════════════════════════════════════════
def shift_summary(db_path: str | Path, hours: int = 8,
                  sla_min: int = DEFAULT_SLA_MIN, queue_limit: int = 300,
                  lang: str = "ko") -> dict:
    """근무 구간 요약 — '무슨 일이 있었나 / 뭘 남기고 가나'.

    hours 는 UTC 기준으로 review_store 가 세고, 유입 알림은 ops_queries 가 센다.
    두 숫자의 출처가 다르므로 (유입 ≠ 판정) 화면에서도 나란히 보여준다.
    """
    out = {"hours": int(hours), "sla_min": int(sla_min),
           "arrived": 0, "pending": [], "counts": {}, "by_reviewer": [],
           "sla": {}, "error": None}
    try:
        from pipeline import ops_queries as oq
    except ImportError:                                # pragma: no cover
        try:
            import ops_queries as oq
        except ImportError:
            out["error"] = "ops_queries 미탑재"
            return out

    try:
        arrived = oq.alert_queue(db_path, limit=queue_limit, min_score=0.0,
                                 only_unreviewed=False, since_hours=int(hours))
        out["arrived"] = len(arrived)
    except Exception as e:
        log.debug(f"유입 알림 조회 실패: {e}")

    try:
        pending = oq.alert_queue(db_path, limit=queue_limit, min_score=0.0,
                                 only_unreviewed=True)
        annotate(pending, sla_min, lang)
        out["pending"] = sort_by_urgency(pending)
        out["sla"] = sla_stats(pending, sla_min)
    except Exception as e:
        log.debug(f"미처리 큐 조회 실패: {e}")
        out["sla"] = sla_stats([], sla_min)

    try:
        out["counts"] = rs.counts(db_path, since_hours=int(hours))
    except Exception as e:
        log.debug(f"판정 집계 실패: {e}")

    out["by_reviewer"] = reviewer_breakdown(db_path, hours)
    return out


def reviewer_breakdown(db_path: str | Path, hours: int = 8) -> list[dict]:
    """근무 구간의 판정자별 실적 — 누가 몇 건을 어떻게 찍었나.
    최신 판정 기준(번복된 옛 판정은 세지 않는다) — counts() 와 같은 규칙."""
    if not rs.table_exists(db_path):
        return []
    try:
        con = rs.connect(db_path, readonly=True)
        rows = con.execute(
            f"""SELECT reviewer,
                       SUM(verdict='tp'), SUM(verdict='fp'),
                       SUM(verdict='fn'), SUM(verdict='unclear'), COUNT(*)
                  FROM {rs.TABLE}
                 WHERE id IN (SELECT MAX(id) FROM {rs.TABLE} GROUP BY txn_id)
                   AND reviewed_at > datetime('now', ?)
                 GROUP BY reviewer ORDER BY COUNT(*) DESC""",
            (f"-{int(hours)} hours",)).fetchall()
        con.close()
    except Exception as e:
        log.debug(f"판정자별 집계 실패: {e}")
        return []
    return [{"reviewer": r[0] or "(이름 없음)", "tp": r[1] or 0, "fp": r[2] or 0,
             "fn": r[3] or 0, "unclear": r[4] or 0, "total": r[5] or 0}
            for r in rows]


def handover_markdown(summary: dict, author: str = "", note: str = "",
                      top_n: int = 10) -> str:
    """인수인계서 텍스트. 복사해서 메신저에 붙이거나 파일로 내려받는 용도.

    화면 캡처 대신 텍스트로 만드는 이유: 다음 근무자가 검색할 수 있어야 하고,
    나중에 '그날 뭐라고 넘겼더라'를 다시 찾을 수 있어야 한다.
    """
    c = summary.get("counts") or {}
    s = summary.get("sla") or {}
    L = [f"# 교대 인수인계 — 최근 {summary.get('hours', 8)}시간"]
    if author:
        L.append(f"작성자: {author}")
    L.append("")
    L.append("## 요약")
    L.append(f"- 유입 알림: **{summary.get('arrived', 0)}건**")
    L.append(f"- 판정 완료: **{c.get('total', 0)}건** "
             f"(정탐 {c.get('tp', 0)} / 오탐 {c.get('fp', 0)} / "
             f"미탐 {c.get('fn', 0)} / 보류 {c.get('unclear', 0)})")
    if c.get("fp_rate") is not None:
        L.append(f"- 오탐률: **{c['fp_rate'] * 100:.1f}%**")
    L.append(f"- 미처리 잔여: **{s.get('pending', 0)}건** "
             f"(SLA {s.get('sla_min', '-')}분 초과 {s.get('over', 0)}건)")
    if s.get("oldest_min") is not None:
        L.append(f"- 최장 대기: **{elapsed_label(s['oldest_min'])}**")

    by = summary.get("by_reviewer") or []
    if by:
        L += ["", "## 판정자별", "", "| 담당자 | 정탐 | 오탐 | 미탐 | 보류 | 합계 |",
              "|---|---:|---:|---:|---:|---:|"]
        for b in by:
            L.append(f"| {b['reviewer']} | {b['tp']} | {b['fp']} | {b['fn']} "
                     f"| {b['unclear']} | {b['total']} |")

    pend = summary.get("pending") or []
    if pend:
        L += ["", f"## 넘기는 미처리 (오래 기다린 순 · 상위 {top_n})", "",
              "| 대기 | 거래 ID | 유형 | 점수 | SLA |", "|---|---|---|---:|---|"]
        for r in pend[:top_n]:
            flag = {"over": "🔴 초과", "warn": "🟡 임박", "ok": "🟢"}.get(
                r.get("urgency", "ok"), "")
            L.append(f"| {r.get('elapsed', '—')} | {r.get('txn_id', '')} "
                     f"| {r.get('fraud_type', '')} | {float(r.get('risk_score') or 0):.3f} "
                     f"| {flag} |")
    else:
        L += ["", "## 넘기는 미처리", "", "없음 — 큐를 비우고 넘깁니다 ✅"]

    if note:
        L += ["", "## 인수인계 메모", "", note.strip()]
    return "\n".join(L)


# ══════════════════════════════════════════════════════════
# 인수인계 메모 저장 — 다음 근무자가 실제로 읽을 수 있게
# ══════════════════════════════════════════════════════════
_DDL_HANDOVER = f"""
CREATE TABLE IF NOT EXISTS {HANDOVER_TABLE} (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    author     TEXT NOT NULL,
    hours      INTEGER,
    note       TEXT,
    snapshot   TEXT,              -- 작성 시점 요약(마크다운). 나중에 숫자가 바뀌어도 그대로 남는다
    created_at TEXT NOT NULL      -- ⚠ UTC 고정
)
"""

_HO_DONE: set[str] = set()


def ensure_handover_schema(db_path: str | Path) -> bool:
    key = str(db_path)
    if key in _HO_DONE:
        return True
    try:
        con = rs.connect(db_path)
        con.execute(_DDL_HANDOVER)
        con.commit()
        con.close()
        _HO_DONE.add(key)
        return True
    except Exception as e:
        log.error(f"{HANDOVER_TABLE} 스키마 생성 실패: {e}")
        return False


def save_handover(db_path: str | Path, author: str, note: str,
                  hours: int = 8, snapshot: str = "") -> tuple[bool, str]:
    if not (note or "").strip():
        return False, "인수인계 메모가 비었습니다"
    if not ensure_handover_schema(db_path):
        return False, "인수인계 테이블을 만들 수 없습니다"
    try:
        con = rs.connect(db_path)
        con.execute(
            f"""INSERT INTO {HANDOVER_TABLE} (author, hours, note, snapshot, created_at)
                VALUES (?,?,?,?, datetime('now'))""",
            (str(author or "unknown")[:100], int(hours),
             note.strip()[:4000], (snapshot or "")[:20000]))
        con.commit()
        con.close()
        return True, "인수인계를 저장했습니다"
    except Exception as e:
        log.error(f"인수인계 저장 실패: {e}")
        return False, f"저장 실패: {type(e).__name__}"


def recent_handovers(db_path: str | Path, limit: int = 5,
                     lang: str = "ko") -> list[dict]:
    """최근 인수인계 — 근무를 시작할 때 '앞사람이 뭘 남겼나'를 먼저 본다."""
    try:
        con = rs.connect(db_path, readonly=True)
        rows = con.execute(
            f"""SELECT id, author, hours, note, created_at, snapshot
                  FROM {HANDOVER_TABLE} ORDER BY id DESC LIMIT ?""",
            (int(limit),)).fetchall()
        con.close()
    except Exception:
        return []                  # 테이블이 아직 없으면 '없음'과 같다
    return [{"id": r[0], "author": r[1], "hours": r[2], "note": r[3],
             "created_at": r[4], "snapshot": r[5],
             "age": elapsed_label(age_minutes(r[4]), lang)} for r in rows]

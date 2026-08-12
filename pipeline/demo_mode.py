"""demo_mode — 시연용 시각 축소(time compression). 기본은 꺼져 있다.

왜 필요한가
  관제 대시보드 상단에 `최장 대기 47일 6시간`, `SLA 30분 초과 113건` 이 뜬다.
  화면은 **정확하게** 동작하고 있다 — 운영 원장(fds_results.db)에 남은 미판정
  이력이 실제로 그만큼 오래된 것이다. 그런데 포트폴리오로 이 화면을 보여주면
  "운영이 방치됐다" 로 읽힌다. 로컬 테스트 DB 가 오래된 것뿐인데도.

무엇을 하는가
  DB 를 고치지 않는다. **조회 결과의 시각만** 최근 구간으로 비례 축소한다.

    실제 구간:  2026-06-26 08:09  ~  2026-08-10 02:23   (44.8일)
    시연 구간:  (지금 - 6시간)    ~  (지금)              (6시간)

  가장 오래된 건이 창의 시작, 가장 최근 건이 "방금" 에 놓이고, 그 사이 행들은
  **원래 위치의 비율 그대로** 배치된다. 즉

    · 건수      그대로 (113건 → 113건)
    · 순서      그대로
    · 상대 위치 그대로 (전체 구간의 30% 지점이었으면 창의 30% 지점)
    · 절대 간격 축소  ← 이것만 바뀐다

  왜 단순히 "최근 N시간만 보여주기" 가 아닌가: 이 DB 는 113건 중 **100건이
  6월 26일 하루에 몰려 있다**(대량 배치 시험의 흔적). 최근 6시간으로 자르면
  5건만 남아 관제 화면으로서 의미가 없다. 그래서 자르지 않고 축소한다.

  왜 단순히 "전체를 미래로 밀기" 가 아닌가: 최신 건이 2.5일 전이라 밀어도
  스팬 44.8일이 그대로 남는다 — 최장 대기가 44일로 찍혀 문제가 그대로다.

어떻게 켜는가
    set FDS_DEMO_MODE=1              (Windows)      · 끄면 기본 동작
    set FDS_DEMO_WINDOW_H=6                         · 창 길이(시간), 기본 6

  켜면 화면 맨 위에 **축소 사실과 원래 구간을 적은 배지**가 뜬다. 재기준된
  시각을 실제 운영 시각으로 오인하지 않도록 숨기지 않는다.

주의
  · 읽기 전용이다. DB 에 쓰지 않는다.
  · 매핑은 프로세스당 한 번 계산해 캐시한다 — rerun 마다 값이 튀지 않는다.
  · 판정·발송 같은 쓰기 동작은 그대로다. 시각 표시만 바뀐다.
  · 원본 값은 각 행의 `_ts_utc_real` 에 남긴다(진단·대조용).

적용 범위 (의도적으로 좁게 잡았다)
  ✅ `ops_queries.alert_queue()` 가 내보내는 알림 행 — 트리아지 큐, 헤더 배지
     (미판정·SLA 초과·최장 대기), 교대 요약, 실시간 피드가 모두 여기서 나온다.
     문제였던 `최장 대기 47일` 이 이 경로다.

  ❌ **발송 이력**(`audit_store.recent()` 의 `sent_at`) — 재기준하지 않는다.
     이 조회는 `since_hours` 를 **SQL 에서** 실제 시각으로 거른다. 표시값만
     밀어도 "최근 24시간" 필터가 이미 0행을 반환하므로 앞뒤가 맞지 않는다.
     제대로 하려면 필터 기준까지 함께 옮겨야 하는데, 그러면 시연 플래그가
     쿼리 의미를 바꾸는 셈이 되어 위험이 이득보다 크다.
     → 시연 중 '발송 이력' 탭은 실제 과거 시각을 보여준다. 의도된 동작이다.

  ❌ **워처 상태**(`watcher_status.last_poll`) — 재기준하지 않는다.
     이건 과거 기록이 아니라 **살아 있는 프로세스의 현재 상태**다. 워처가 꺼져
     있으면 데드맨 스위치가 "응답 없음" 으로 잡아야 맞다. 그걸 최근 시각으로
     덮으면 죽은 프로세스를 살아 있다고 보여주는 것이 된다 — 재기준이 아니라
     조작이다. 시연 때 워처 패널도 보여주려면 워처를 실제로 켜면 된다.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)

ENV_FLAG = "FDS_DEMO_MODE"
ENV_WINDOW = "FDS_DEMO_WINDOW_H"
DEFAULT_WINDOW_H = 6.0
_TRUE = {"1", "true", "yes", "on", "y"}

# 프로세스당 한 번 정하는 매핑. (실제 최소, 실제 최대, 창 끝, 창 길이초)
_map: tuple[datetime, datetime, datetime, float] | None = None


def enabled() -> bool:
    """시연 모드 여부. 환경변수만 본다 — 코드에서 켜지 않는다."""
    return os.getenv(ENV_FLAG, "").strip().lower() in _TRUE


def window_hours() -> float:
    try:
        v = float(os.getenv(ENV_WINDOW, "") or DEFAULT_WINDOW_H)
        return v if v > 0 else DEFAULT_WINDOW_H
    except ValueError:
        return DEFAULT_WINDOW_H


def _parse(ts) -> datetime | None:
    """'YYYY-MM-DD HH:MM:SS' 계열 → aware datetime(UTC)."""
    if ts in (None, ""):
        return None
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    s = str(ts).strip().replace("T", " ")
    if s.endswith("Z"):
        s = s[:-1]
    s = s.split("+")[0].split(".")[0].strip()
    for f in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, f).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _ensure_map(rows: list[dict], key: str) -> bool:
    """행들의 실제 구간을 보고 매핑을 확정한다. 이미 있으면 그대로 쓴다.

    데이터가 없거나 시각이 하나뿐이면 매핑하지 않는다(캐시도 남기지 않는다) —
    뒤에 더 넓은 조회가 오면 그때 정하도록 둔다.
    """
    global _map
    if _map is not None:
        return True
    stamps = [d for d in (_parse(r.get(key)) for r in (rows or [])) if d]
    if len(stamps) < 2:
        return False
    lo, hi = min(stamps), max(stamps)
    if hi <= lo:
        return False
    win = window_hours() * 3600.0
    _map = (lo, hi, datetime.now(timezone.utc), win)
    log.info("시연 모드: 실제 %.1f일 구간(%s ~ %s)을 최근 %.1f시간으로 축소",
             (hi - lo).total_seconds() / 86400,
             lo.strftime("%Y-%m-%d %H:%M"), hi.strftime("%Y-%m-%d %H:%M"),
             win / 3600)
    return True


def span_label() -> str | None:
    """'2026-06-26 08:09 ~ 2026-08-10 02:23 (44.8일)' — 배지 표기용."""
    if _map is None:
        return None
    lo, hi, _, _ = _map
    days = (hi - lo).total_seconds() / 86400
    return (f"{lo.strftime('%Y-%m-%d %H:%M')} ~ "
            f"{hi.strftime('%Y-%m-%d %H:%M')} ({days:.1f}일)")


def rebase(rows: list[dict], key: str = "ts_utc") -> list[dict]:
    """행들의 `key` 시각을 시연 창으로 비례 축소한다. 꺼져 있으면 그대로 반환.

    lo→(끝-창), hi→끝 으로 선형 사상한다. 원본은 `_ts_utc_real` 에 보존.
    """
    if not enabled() or not rows:
        return rows
    if not _ensure_map(rows, key):
        return rows
    lo, hi, end, win = _map
    total = (hi - lo).total_seconds()
    for r in rows:
        cur = _parse(r.get(key))
        if cur is None:
            continue
        frac = (cur - lo).total_seconds() / total
        frac = 0.0 if frac < 0 else (1.0 if frac > 1 else frac)   # 창 밖은 양끝에 붙임
        r["_ts_utc_real"] = r[key]
        r[key] = (end - timedelta(seconds=win * (1.0 - frac))
                  ).strftime("%Y-%m-%d %H:%M:%S")
    return rows


def badge_text(lang: str = "ko") -> str:
    """화면에 띄울 안내. 축소 사실과 원래 구간을 숨기지 않는다."""
    sp = span_label()
    w = window_hours()
    if lang.startswith("en"):
        tail = f" Real range: {sp}." if sp else ""
        return (f"🎬 Demo mode — alert timestamps are compressed into the last "
                f"{w:g} hours.{tail} Counts, order and relative spacing are the "
                f"real data; only absolute intervals are scaled.")
    tail = f" 실제 구간: {sp}." if sp else ""
    return (f"🎬 시연 모드 — 알림 시각을 최근 {w:g}시간 구간으로 비례 축소해 "
            f"표시합니다.{tail} 건수·순서·상대 위치는 실제 데이터 그대로이고, "
            f"절대 간격만 축소했습니다.")

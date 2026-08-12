"""
status_push — 워처 상태를 **DB 밖으로** 내보낸다  ✨ v24 신규

풀려는 문제 (README_WATCHER5 §9)
  Streamlit Cloud 는 오빠 PC 가 아니라 Streamlit 서버에서 대시보드를 돌린다.
  워처 상태는 로컬 `fds_results.db` 안에만 있으므로 **클라우드에서는 영원히
  '워처를 실행한 적 없음'** 으로 보인다. 워처가 상태를 밖으로 밀어주지 않으면
  이 문제는 대시보드 쪽에서 풀 수 없다.

무엇을 하는가
  워처가 폴링할 때마다(또는 N초마다) 상태 스냅샷을 **JSON 한 덩이**로 내보낸다.

    · 파일   — 공유 폴더·OneDrive·S3 마운트·네트워크 드라이브에 그대로 떨어뜨린다
    · HTTP   — 아무 엔드포인트로 POST (Supabase REST · 사내 API · webhook.site 등)

  둘 다 **선택**이다. 환경변수가 없으면 아무 일도 하지 않는다 —
  기본 동작(로컬 DB)은 지금까지와 100% 같다.

설정 (.env 또는 환경변수)
    FDS_STATUS_FILE      내보낼 JSON 경로       예) D:/share/fds_status.json
    FDS_STATUS_URL       POST 할 엔드포인트     예) https://xxx.supabase.co/rest/v1/fds_status
    FDS_STATUS_HEADERS   추가 헤더(JSON 문자열) 예) {"apikey":"...","Authorization":"Bearer ..."}
    FDS_STATUS_MIN_SEC   최소 간격(초, 기본 30) — 폴링이 5초여도 30초에 한 번만 내보낸다

설계 원칙
  · **워처를 절대 죽이지 않는다.** 네트워크 오류·권한 오류는 로그만 남기고 삼킨다.
    상태 보고가 탐지를 멈추면 주객전도다.
  · 파일은 임시파일 → 원자적 교체. 읽는 쪽이 반쪽 JSON 을 보지 않게.
  · 시각은 UTC. 이 프로젝트의 시각 규칙과 같다.

읽는 쪽
    read_status_file(path) 로 같은 JSON 을 되읽어 watcher_panel.liveness() 에
    그대로 넘길 수 있다(키 이름을 맞춰 두었다).

CLI 확인:  python -m pipeline.status_push            # 현재 설정·마지막 스냅샷
           python -m pipeline.status_push --test     # 지금 한 번 내보내 보기
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import time
from pathlib import Path

log = logging.getLogger("status_push")

STATUS_PUSH_VERSION = "v1"

ENV_FILE = "FDS_STATUS_FILE"
ENV_URL = "FDS_STATUS_URL"
ENV_HEADERS = "FDS_STATUS_HEADERS"
ENV_MIN_SEC = "FDS_STATUS_MIN_SEC"

DEFAULT_MIN_SEC = 30

_last_push = 0.0


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def configured() -> bool:
    """내보낼 곳이 하나라도 설정돼 있는가. 아니면 이 모듈은 완전히 잠잠하다."""
    return bool(os.getenv(ENV_FILE) or os.getenv(ENV_URL))


def targets() -> dict:
    """현재 설정 — 화면·CLI 에 그대로 보여줄 수 있게 (비밀 헤더 값은 가린다)."""
    hdr = os.getenv(ENV_HEADERS) or ""
    try:
        n_hdr = len(json.loads(hdr)) if hdr else 0
    except Exception:
        n_hdr = -1                                   # 파싱 실패
    return {
        "file": os.getenv(ENV_FILE) or None,
        "url": os.getenv(ENV_URL) or None,
        "headers": n_hdr,
        "min_sec": _min_sec(),
        "enabled": configured(),
    }


def _min_sec() -> int:
    try:
        return max(1, int(os.getenv(ENV_MIN_SEC, DEFAULT_MIN_SEC)))
    except (TypeError, ValueError):
        return DEFAULT_MIN_SEC


def build_snapshot(status: dict | None, extra: dict | None = None) -> dict:
    """watcher_panel.read_status() 결과 → 내보낼 JSON.

    키 이름을 read_status() 와 맞춰 둔다 — 읽는 쪽이 liveness() 에 그대로
    넘길 수 있어야 '클라우드에서도 같은 화면'이 된다.
    """
    s = dict(status or {})
    snap = {
        "schema": "fds.watcher_status/1",
        "pushed_at": _utc_now(),                      # UTC
        "host": os.getenv("COMPUTERNAME") or os.getenv("HOSTNAME") or "",
        "started_at": s.get("started_at"),
        "last_poll": s.get("last_poll"),
        "polls": s.get("polls"),
        "rows_done": s.get("rows_done"),
        "anomalies": s.get("anomalies"),
        "notified": s.get("notified"),
        "errors": s.get("errors"),
        "note": s.get("note"),
    }
    if extra:
        snap.update(extra)
    return snap


def push(status: dict | None, *, force: bool = False,
         extra: dict | None = None) -> dict:
    """상태를 내보낸다. 결과 요약 dict 반환 (실패해도 예외를 던지지 않는다).

    force=False 면 FDS_STATUS_MIN_SEC 간격을 지킨다 — 5초 폴링마다 네트워크를
    두드리면 워처가 느려지고 상대 서버도 싫어한다.
    """
    global _last_push
    out = {"enabled": configured(), "skipped": None, "file": None, "http": None}
    if not out["enabled"]:
        out["skipped"] = "미설정"
        return out

    now = time.time()
    if not force and (now - _last_push) < _min_sec():
        out["skipped"] = f"간격 미달({_min_sec()}초)"
        return out
    _last_push = now

    snap = build_snapshot(status, extra)
    body = json.dumps(snap, ensure_ascii=False, indent=2)

    fp = os.getenv(ENV_FILE)
    if fp:
        try:
            p = Path(fp)
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_name(p.name + ".tmp")
            tmp.write_text(body, encoding="utf-8")
            tmp.replace(p)                            # 원자적 교체 — 반쪽 읽기 방지
            out["file"] = f"ok:{p}"
        except Exception as e:                        # 워처를 죽이지 않는다
            out["file"] = f"fail:{type(e).__name__}: {e}"
            log.warning(f"상태 파일 내보내기 실패({fp}): {e}")

    url = os.getenv(ENV_URL)
    if url:
        try:
            import requests
            headers = {"Content-Type": "application/json"}
            raw = os.getenv(ENV_HEADERS)
            if raw:
                try:
                    headers.update(json.loads(raw))
                except Exception as e:
                    log.warning(f"{ENV_HEADERS} 파싱 실패(무시): {e}")
            r = requests.post(url, data=body.encode("utf-8"), headers=headers,
                              timeout=5)
            out["http"] = f"{r.status_code}"
            if r.status_code >= 400:
                log.warning(f"상태 POST 응답 {r.status_code}: {r.text[:120]}")
        except Exception as e:
            out["http"] = f"fail:{type(e).__name__}"
            log.warning(f"상태 POST 실패({url}): {e}")
    return out


def read_status_file(path: str | Path) -> dict | None:
    """내보낸 JSON 을 되읽어 read_status() 와 같은 모양으로 돌려준다.

    age_sec / uptime_sec 는 저장돼 있지 않으므로 **읽는 시점에 계산**한다 —
    그래야 watcher_panel.liveness() 가 그대로 동작한다.
    """
    try:
        p = Path(path)
        if not p.exists():
            return None
        snap = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        log.debug(f"상태 파일 읽기 실패({path}): {e}")
        return None

    def _age(ts) -> int | None:
        if not ts:
            return None
        try:
            t = _dt.datetime.strptime(str(ts)[:19], "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=_dt.timezone.utc)
            return int((_dt.datetime.now(_dt.timezone.utc) - t).total_seconds())
        except Exception:
            return None

    snap["age_sec"] = _age(snap.get("last_poll"))
    snap["uptime_sec"] = _age(snap.get("started_at"))
    return snap


# ── CLI ────────────────────────────────────────────────────
if __name__ == "__main__":                             # pragma: no cover
    import sys
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print(f"status_push {STATUS_PUSH_VERSION}")
    t = targets()
    print(f"  설정: 파일={t['file'] or '-'} · URL={t['url'] or '-'} "
          f"· 추가헤더 {t['headers']}개 · 최소간격 {t['min_sec']}초")
    if not t["enabled"]:
        print(f"  ⚠ 내보낼 곳이 없습니다. {ENV_FILE} 또는 {ENV_URL} 를 설정하세요.")
    if "--test" in sys.argv:
        try:
            from pipeline import watcher_panel as wp
            st = wp.read_status(os.getenv("FDS_DB_PATH", "fds_results.db"))
        except Exception as e:
            print(f"  워처 상태를 읽지 못했습니다: {e}")
            st = None
        print("  내보내는 중…", push(st, force=True))
    if t["file"]:
        cur = read_status_file(t["file"])
        print(f"  마지막 스냅샷: {cur if cur else '(없음)'}")

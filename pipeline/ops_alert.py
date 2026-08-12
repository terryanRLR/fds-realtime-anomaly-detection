"""
ops_alert — 이상거래 실시간 알람 (사운드 · 팝업 · 데스크톱 알림)  ✨ v20 신규

무엇을 하는가
  워처가 새 이상거래를 넣으면, 대시보드의 **어느 탭에 있든** 화면 위에 경보 카드가 뜨고
  삐용삐용 사이렌이 울리고 윈도우 알림이 나간다. 카드를 클릭하면 해당 거래의
  트리아지 화면으로 바로 이동한다.

🚨 이 모듈의 절반은 '덜 울리게 하는' 코드다 — 그 이유

  알람 시스템은 기능이 부족해서 죽지 않는다. **과해서** 죽는다.
  운영 오탐률이 30%대라면 세 번 중 한 번은 거짓 경보다. 새벽에 두 번 깨우고
  두 번 다 헛것이면 담당자는 사흘 안에 토글을 끄고 다시는 켜지 않는다.
  그럼 정작 진짜 사고 때 아무도 모른다.

  그래서 기본값을 보수적으로 잡았다:
    · 기본 등급 = confirm 만. review 까지 울리면 소음이 3배가 된다
      (구간 경계는 워처 설정 th_review/th_confirm 을 그대로 따른다)
    · 같은 거래는 dedup_min 안에 다시 울리지 않는다
    · 조용한 시간대(quiet hours) 설정
    · 폴링 1회당 최대 alert 개수 제한 — 대량 유입 시 100번 울리는 사고 방지
  그리고 UI 는 토글 옆에 **현재 설정의 예상 소음량과 오탐률**을 함께 보여준다.
  켜는 순간 대가를 알 수 있어야 계속 켜 둔다.

🔊 브라우저 오디오 정책 (중요)
  최신 브라우저는 사용자가 페이지와 상호작용하기 전에는 소리를 차단한다.
  AudioContext 가 'suspended' 상태로 생성되며, **에러 없이 조용히** 실패한다.
  (dashboard.py:918 의 기존 _play_alarm 이 이 문제를 안고 있다.)
  → arm_audio() 버튼을 한 번 눌러 ctx.resume() 을 태워야 실제로 울린다.

🖥 데스크톱 알림은 '보는 사람' PC 에 뜬다
  브라우저 Notification API 를 쓴다. 파이썬에서 win10toast/PowerShell 을 부르면
  **서버 PC** 에 뜨는데, ngrok 등으로 팀에 공유하면 아무도 보지 못한다.

♿ 접근성
  초당 3회를 넘는 점멸은 광과민성 발작을 유발할 수 있다(WCAG 2.3.1).
  펄스 주기를 1.4초로 두고 prefers-reduced-motion 을 존중한다.
"""

from __future__ import annotations

import json
import os
import time
import logging
from pathlib import Path

log = logging.getLogger(__name__)

ALERT_VERSION = "v25"

# 임계값 폴백 — 워처 설정(watcher_config.json)을 못 읽었을 때만 쓴다.
#   이 숫자가 코드 곳곳에 흩어져 있으면 설정을 바꿔도 화면이 따라오지 않는다.
DEFAULT_TH_REVIEW = 0.45
DEFAULT_TH_CONFIRM = 0.80

TIERS = ("confirm", "review", "all")

# {thr}/{thc} 는 **실제 적용 중인 임계값**으로 채운다 — tier_label() 을 쓸 것.
#   예전에는 여기에 0.80·0.45 가 문자열로 박혀 있었다. 이 프로젝트의 실제 설정은
#   th_review 0.005 / th_confirm 0.9 라서, 화면이 "확정만 (0.80↑)" 이라고
#   말하는 동안 시스템은 0.9 로 판정하고 있었다.
TIER_LABEL = {
    "confirm": ("확정만 ({thc}↑) — 권장", "Confirmed only (≥{thc}) — recommended",
                "確定のみ ({thc}↑) — 推奨", "仅确认 ({thc}↑) — 推荐"),
    "review":  ("검토 이상 ({thr}↑)", "Review and above (≥{thr})",
                "検討以上 ({thr}↑)", "复核及以上 ({thr}↑)"),
    "all":     ("모든 이상거래 — 소음 주의", "All anomalies — noisy",
                "全異常取引 — 騒音注意", "全部异常 — 噪音较大"),
}
_LANG_IDX = {"ko": 0, "en": 1, "ja": 2, "zh": 3}


def fmt_th(v) -> str:
    """임계값 표기 — 0.005 처럼 작은 값이 '0.01' 로 뭉개지지 않게.
    0.9 → '0.9' · 0.005 → '0.005' · 0.8 → '0.8'"""
    try:
        s = f"{float(v):.4f}".rstrip("0").rstrip(".")
        return s or "0"
    except (TypeError, ValueError):
        return "-"


def tier_label(key: str, lang: str = "ko",
               th_review=None, th_confirm=None) -> str:
    """등급 라벨. 숫자는 호출부가 넘긴 **실제 임계값**으로 채워진다.

    모르는 key 는 그대로 돌려준다 — 예전처럼 조용히 'confirm' 라벨로 폴백하면
    잘못된 key 를 넘겨도 그럴듯한 화면이 나와 원인을 못 찾는다.
    """
    if key not in TIER_LABEL:
        return str(key)
    tpl = TIER_LABEL[key][_LANG_IDX.get(lang, 0)]
    return tpl.format(
        thr=fmt_th(DEFAULT_TH_REVIEW if th_review is None else th_review),
        thc=fmt_th(DEFAULT_TH_CONFIRM if th_confirm is None else th_confirm))


DEFAULTS = {
    # 🔔 v22: 기본 ON. 관제 도구를 열어 둔 사람은 경보를 받으려고 연 것이다.
    #   대신 기본 등급은 confirm 로 보수적이라 소음이 크지 않다.
    "alarm_on": True,
    "alarm_tier": "confirm",
    "alarm_sound": True,
    "alarm_volume": 0.25,       # 0.3 은 야간 관제실에서 너무 크다
    "alarm_desktop": True,
    "alarm_popup": True,
    "alarm_dedup_min": 30,
    "alarm_quiet_from": 0,      # 조용한 시간 시작 (0=사용 안 함)
    "alarm_quiet_to": 0,
    "alarm_max_burst": 3,       # 폴링 1회당 최대 경보 수
    "alarm_beeps": 3,           # 삐- 반복 횟수 (1~10)
    # 플로팅 카드가 안 보이는 환경(엄격한 CSP 등)을 위한 폴백. 기본 OFF —
    # 둘 다 켜면 같은 경보가 두 번 보인다.
    "alarm_banner": False,
    "alarm_audio_armed": False,
    "_alarm_seen_id": None,     # transactions.id 워터마크
    "_alarm_recent": {},        # {txn_id: 마지막 경보 시각(epoch)}
}


# ══════════════════════════════════════════════════════════
# 📀 설정 공유 — 두 대시보드가 같은 경보 정책을 쓴다
#
#   경보 설정이 세션에만 있으면 앱마다 따로 논다. "야간엔 조용히" 를 관제
#   화면에서 켜 뒀는데 분석 화면은 그대로 울리는 식이다 — 둘 다 같은 사람의
#   같은 스피커로 나가므로 정책이 갈리면 곧바로 사고가 된다.
#   그래서 **사용자가 정한 값만** 파일 한 벌에 둔다.
#
#   런타임 상태(_alarm_seen_id · _alarm_recent · alarm_audio_armed)는 공유하지
#   않는다. 워터마크를 공유하면 한쪽이 본 경보를 다른 쪽이 영영 못 보고,
#   오디오 활성화는 **브라우저 탭마다** 따로 받아야 하는 권한이라 옮길 수 없다.
# ══════════════════════════════════════════════════════════
PREFS_ENV = "FDS_ALARM_PREFS"
_DEFAULT_PREFS = Path(__file__).resolve().parent.parent / "alarm_prefs.json"

SHARED_KEYS = ("alarm_on", "alarm_tier", "alarm_sound", "alarm_volume",
               "alarm_desktop", "alarm_popup", "alarm_beeps", "alarm_banner",
               "alarm_dedup_min", "alarm_quiet_from", "alarm_quiet_to",
               "alarm_max_burst")

_prefs_cache: dict = {"path": None, "mtime": -1.0, "data": {}}


def prefs_path() -> Path:
    return Path(os.environ.get(PREFS_ENV) or _DEFAULT_PREFS)


def load_prefs() -> dict:
    """파일에 저장된 경보 설정. 없거나 깨졌으면 빈 dict(= DEFAULTS 사용)."""
    p = prefs_path()
    try:
        mt = p.stat().st_mtime
    except OSError:
        _prefs_cache.update(path=str(p), mtime=-1.0, data={})
        return {}
    if _prefs_cache["path"] == str(p) and _prefs_cache["mtime"] == mt:
        return dict(_prefs_cache["data"])
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        data = {k: raw[k] for k in SHARED_KEYS if k in raw}
    except (OSError, ValueError) as e:
        log.warning(f"경보 설정을 읽을 수 없습니다 → 기본값 사용: {e}")
        data = {}
    _prefs_cache.update(path=str(p), mtime=mt, data=dict(data))
    return dict(data)


def save_prefs(ss) -> tuple[bool, str]:
    """현재 세션의 경보 설정을 파일에 쓴다. 원자적 교체 — 반쯤 쓰인 파일이 안 보인다."""
    p = prefs_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        data = {k: ss[k] for k in SHARED_KEYS if k in ss}
        data["_saved_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, p)
    except (OSError, TypeError) as e:
        log.warning(f"경보 설정 저장 실패: {e}")
        return False, str(e)
    _prefs_cache.update(path=None, mtime=-1.0, data={})
    return True, str(p)


def init_state(ss, shared: bool = True):
    """세션 기본값 채우기. shared=True 면 파일에 저장된 설정을 먼저 얹는다.

    순서가 중요하다 — 파일 값 → 그 다음 DEFAULTS 로 빈 칸 메우기. 반대로 하면
    setdefault 가 이미 채운 기본값 때문에 파일 값이 영영 반영되지 않는다.
    """
    if shared:
        for k, v in load_prefs().items():
            ss.setdefault(k, v)
    for k, v in DEFAULTS.items():
        ss.setdefault(k, v)


def on_pref_change(ss):
    """설정 위젯의 on_change 콜백 — 바꾼 즉시 상대 앱에도 반영되게 저장한다."""
    save_prefs(ss)


# ══════════════════════════════════════════════════════════
# 폴링 — 새 알림 감지
# ══════════════════════════════════════════════════════════

def _tier_of(score, th_review, th_confirm):
    s = float(score or 0)
    if s >= th_confirm:
        return "confirm"
    if s >= th_review:
        return "review"
    return "none"


def poll_new(oq, db, ss, th_review=DEFAULT_TH_REVIEW,
             th_confirm=DEFAULT_TH_CONFIRM) -> list[dict]:
    """마지막으로 본 이후 새로 들어온 알림만 반환한다.

    워터마크로 transactions.id 를 쓴다 — AUTOINCREMENT 라 단조 증가하고,
    detections 처럼 UPSERT 로 덮어써지지 않아 '새 것'의 정의가 흔들리지 않는다.
    시각 기준으로 하면 UTC/로컬 혼재 컬럼 때문에 경보를 놓치거나 과거를 다시 울린다.
    """
    if not ss.get("alarm_on"):
        return []
    if _in_quiet_hours(ss):
        return []

    rows = oq.alert_queue(db, limit=40, min_score=0.0, only_unreviewed=False)
    if not rows:
        return []

    ids = [r.get("alert_ref") for r in rows if isinstance(r.get("alert_ref"), int)]
    newest = max(ids) if ids else None
    seen = ss.get("_alarm_seen_id")

    # 최초 실행 — 과거 전체를 울리면 안 된다. 현재 지점을 기준선으로 잡고 침묵.
    if seen is None:
        ss["_alarm_seen_id"] = newest
        log.info(f"알람 워터마크 초기화: id={newest} (기존 알림은 울리지 않습니다)")
        return []
    if newest is None or newest <= seen:
        return []

    tier_min = ss.get("alarm_tier", "confirm")
    now = time.time()
    dedup_sec = int(ss.get("alarm_dedup_min", 30)) * 60
    recent = ss.get("_alarm_recent") or {}
    # 🔁 에코 차단 — 지금 화면에 떠 있는 경보는 다시 쏘지 않는다.
    #   ops 의 ▶탐지 실행은 결과를 그리는 자리에서 즉시 경보를 쏘는데(즉각적인
    #   피드백이 목적), 그 건이 이제 원장(transactions)에도 들어가므로 다음 폴링이
    #   같은 거래를 '새 알림'으로 한 번 더 집는다. 재알람 억제(분)를 0으로 둔
    #   사람의 설정을 뒤엎지 않으면서 이 중복만 막으려면, 시간이 아니라
    #   '아직 표시 중인가'로 판단하는 것이 정확하다.
    _showing = {a.get("txn_id") for a in active(ss)}

    out = []
    for r in rows:
        ref = r.get("alert_ref")
        if not isinstance(ref, int) or ref <= seen:
            continue
        if r.get("txn_id") in _showing:
            continue
        tier = _tier_of(r.get("risk_score"), th_review, th_confirm)
        if tier_min == "confirm" and tier != "confirm":
            continue
        if tier_min == "review" and tier == "none":
            continue
        if tier_min == "all" and not (r.get("is_anomaly") or tier != "none"):
            continue
        tid = r.get("txn_id")
        if tid in recent and (now - recent[tid]) < dedup_sec:
            continue
        recent[tid] = now
        r = dict(r)
        r["tier"] = tier
        out.append(r)

    ss["_alarm_seen_id"] = newest
    # 오래된 dedup 기록 정리 (세션이 길어지면 무한히 쌓인다)
    ss["_alarm_recent"] = {k: v for k, v in recent.items() if now - v < dedup_sec * 2}

    out.sort(key=lambda x: -float(x.get("risk_score") or 0))
    cap = int(ss.get("alarm_max_burst", 3))
    if len(out) > cap:
        log.info(f"경보 {len(out)}건 중 상위 {cap}건만 표시 (버스트 제한)")
        out = out[:cap]
    return out


def _in_quiet_hours(ss) -> bool:
    a, b = int(ss.get("alarm_quiet_from", 0)), int(ss.get("alarm_quiet_to", 0))
    if a == b:
        return False
    h = time.localtime().tm_hour
    return (a <= h < b) if a < b else (h >= a or h < b)


def noise_forecast(oq, rs, db, ss, hours=168,
                   th_review=None, th_confirm=None) -> dict:
    """이 설정이면 얼마나 울릴지 + 그중 몇 %가 헛것일지.

    토글 옆에 이걸 띄우는 게 이 모듈에서 가장 중요한 UI 결정이다.
    대가를 모르고 켠 알람은 반드시 꺼진다.

    ⚠️ 임계값은 **반드시 호출부가 넘겨야** 의미가 있다. 예전에는 여기서 0.45/0.80 을
       하드코딩했는데, 실제 폴링(poll_new)은 워처 설정(0.005/0.9)으로 돌고 있었다.
       즉 '예상 알람 N회/일' 이 실제와 다른 기준으로 계산된 숫자였다 —
       켜기 전에 대가를 보여준다는 이 패널의 존재 이유가 무너져 있었다.
    """
    try:
        rows = oq.alert_queue(db, limit=500, min_score=0.0, only_unreviewed=False,
                              since_hours=hours)
    except Exception:
        rows = []
    cfg_tier = ss.get("alarm_tier", "confirm")
    thr = DEFAULT_TH_REVIEW if th_review is None else float(th_review)
    thc = DEFAULT_TH_CONFIRM if th_confirm is None else float(th_confirm)
    n = 0
    for r in rows:
        tier = _tier_of(r.get("risk_score"), thr, thc)
        if cfg_tier == "confirm" and tier == "confirm":
            n += 1
        elif cfg_tier == "review" and tier != "none":
            n += 1
        elif cfg_tier == "all" and (r.get("is_anomaly") or tier != "none"):
            n += 1
    per_day = round(n / max(hours / 24, 1), 1)
    c = rs.counts(db, hours)
    fp = c.get("fp_rate")
    return {"per_day": per_day, "total": n, "fp_rate": fp,
            "wasted": round(per_day * fp, 1) if fp is not None else None}


# ══════════════════════════════════════════════════════════
# 렌더링 — 사운드 · 팝업 · 데스크톱 알림
# ══════════════════════════════════════════════════════════

_SEV = {"confirm": ("#ff4d6d", "확정", "CONFIRMED"),
        "review":  ("#f0a83c", "검토", "REVIEW"),
        "none":    ("#6aa7e8", "관찰", "WATCH")}


def _card_svg() -> str:
    """레이더 스윕 SVG.

    번쩍이는 빨간 사각형 대신 이걸 쓴 이유:
      · 초당 3회 이상 점멸은 광과민성 발작 위험(WCAG 2.3.1). 스윕은 회전이라 점멸이 없다
      · 관제실 화면에서 '탐지'의 시각 언어는 레이더다 — 학습이 필요 없다
    """
    return (
        '<svg viewBox="0 0 64 64" width="44" height="44" aria-hidden="true" '
        'style="color:inherit;flex:0 0 auto">'
        '<circle cx="32" cy="32" r="28" fill="none" stroke="currentColor" stroke-opacity=".22" stroke-width="1.5"/>'
        '<circle cx="32" cy="32" r="19" fill="none" stroke="currentColor" stroke-opacity=".18" stroke-width="1"/>'
        '<circle cx="32" cy="32" r="10" fill="none" stroke="currentColor" stroke-opacity=".14" stroke-width="1"/>'
        '<line x1="32" y1="4" x2="32" y2="60" stroke="currentColor" stroke-opacity=".10"/>'
        '<line x1="4" y1="32" x2="60" y2="32" stroke="currentColor" stroke-opacity=".10"/>'
        # 🐛 gradient 를 쓰지 않는다 — <defs> 의 id 는 문서 전역이라 카드가 여러 장이면
        #    두 번째 카드부터 첫 카드의 gradient 를 참조해 색이 뭉갠다.
        #    단색 + fill-opacity 로 같은 효과를 내면 id 자체가 필요 없다.
        '<g class="opsRadarSweep" style="transform-origin:32px 32px">'
        '<path d="M32 32 L32 4 A28 28 0 0 1 56 18 Z" fill="currentColor" fill-opacity=".32"/>'
        '<path d="M32 32 L32 4 A28 28 0 0 1 44 7.5 Z" fill="currentColor" fill-opacity=".26"/></g>'
        '<circle class="opsRadarBlip" cx="45" cy="21" r="3.4" fill="currentColor"/>'
        '</svg>')


def _html(st, html: str, height: int = 0):
    """HTML/JS 삽입 — Streamlit 버전 차이를 흡수한다.

    st.components.v1.html 은 2026-06-01 부로 지원 종료 예고가 붙었고
    st.iframe 이 후속이다. 신규 API 를 먼저 시도하고 없으면 구 API 로 떨어진다.
    (dashboard.py 도 같은 구 API 를 쓰고 있어 함께 손봐야 한다.)

    🐛 FIX: st.iframe 은 height=0 을 거부한다(StreamlitInvalidHeightError).
    이 함수의 모든 호출부(render/_ARM_HTML)가 관례적으로 height=0 을 쓰는
    "보이지 않는 JS 주입기" 패턴이라, 예전 코드는 매번 이 예외를 던졌다.
    게다가 여기서 TypeError 만 잡고 있어서 그 예외가 그대로 위로 새어나갔고,
    호출부인 render() 의 넓은 except Exception 이 그걸 조용히 삼켜서 —
    경보 팝업이 한 번도 뜨지 않았다(로그에만 "무시" 경고가 남았다).
    → height 를 1px 이상으로 보정하고, 예외 종류를 가리지 않고 구 API 로 폴백한다.
    """
    fn = getattr(st, "iframe", None)
    if fn is not None:
        try:
            _h = height if isinstance(height, int) and height > 0 else 1
            return fn(html, height=_h)
        except Exception:
            pass
    return st.components.v1.html(html, height=height)


# ══════════════════════════════════════════════════════════
# 🔔 v22 — 경보 UI를 **네이티브 Streamlit 위젯**으로 전환
#
#   왜 바꿨나: 주입 HTML 의 버튼이 끝내 동작하지 않았다.
#   iframe(components.html/st.iframe) 안에서 만든 핸들러는 Streamlit 이 리런하며
#   iframe 을 파괴할 때 함께 죽는다. 컨트롤러를 부모 문서로 옮겨 봐도,
#   브라우저·CSP·샌드박스 조합에 따라 주입 자체가 막히면 방법이 없다.
#   → **클릭이 필요한 것은 전부 st.button 으로** 만든다. Streamlit 이 이벤트를
#     직접 받으므로 realm·CSP 와 무관하게 100% 동작한다.
#   JS 는 클릭이 필요 없는 것(소리·데스크톱 알림)에만 남긴다.
#
#   부작용: 카드가 화면 우상단 고정이 아니라 페이지 상단(탭 위)에 놓인다.
#   대신 어느 탭에 있든 보이고, 버튼이 실제로 눌린다.
# ══════════════════════════════════════════════════════════
ACTIVE_KEY = "_ops_active_alerts"


def fire(ss, alerts: list[dict], ttl_confirm: int = 45, ttl_other: int = 22):
    """경보를 '표시 중' 목록에 넣는다. 실제 그리기는 render_banner 가 한다.

    만료는 JS 타이머가 아니라 **타임스탬프 비교**로 처리한다 — 리런마다 다시
    계산하므로 iframe 이 파괴돼도 영향이 없다(예전 버그의 근본 원인).
    """
    now = time.time()
    cur = list(ss.get(ACTIVE_KEY) or [])
    have = {a.get("txn_id") for a in cur}
    # 폴링이 아닌 경로(수동 탐지·테스트)로 들어온 경보도 재알람 억제 기록에 남긴다.
    #   예전엔 poll_new 만 이 맵을 채웠다. 수동 탐지가 원장에 적재되기 시작하면서
    #   같은 건이 폴링으로 한 번 더 잡히는데, 카드 TTL(22초)이 폴링 주기(최대 60초)
    #   보다 짧으면 _showing 검사만으로는 새는 창이 생긴다.
    recent = ss.get("_alarm_recent") or {}
    for a in alerts or []:
        tid = str(a.get("txn_id") or "-")
        recent[tid] = now
        if tid in have:                        # 같은 거래는 다시 쌓지 않는다
            continue
        tier = a.get("tier") if a.get("tier") in _SEV else "none"
        cur.append({**a, "txn_id": tid, "tier": tier,
                    "_expire": now + (ttl_confirm if tier == "confirm" else ttl_other)})
        have.add(tid)
    ss["_alarm_recent"] = recent
    ss[ACTIVE_KEY] = cur[-12:]                 # 화면을 덮지 않게 상한
    return ss[ACTIVE_KEY]


def active(ss) -> list[dict]:
    """만료되지 않은 경보만. 호출할 때마다 정리된다."""
    now = time.time()
    cur = [a for a in (ss.get(ACTIVE_KEY) or []) if float(a.get("_expire", 0)) > now]
    ss[ACTIVE_KEY] = cur
    return cur


def dismiss(ss, txn_id=None):
    """닫기. txn_id 가 없으면 전부."""
    if txn_id is None:
        ss[ACTIVE_KEY] = []
    else:
        ss[ACTIVE_KEY] = [a for a in (ss.get(ACTIVE_KEY) or [])
                          if a.get("txn_id") != txn_id]


def render_banner(st, ss, T: dict, fraud_label, lang="ko", on_open=None) -> bool:
    """표시 중인 경보를 네이티브 위젯으로 그린다. 그린 게 있으면 True.

    on_open(txn_id) : '확인하기'를 눌렀을 때 호출되는 콜백 (탭 이동 등)
    """
    items = active(ss)
    if not items:
        return False
    # (확인하기, 닫기, 전체 닫기, 위험도, 배너 헤더)
    #   ⚠ ja/zh 가 빠져 있으면 그 언어에서 이 배너만 한국어로 남는다 —
    #     ops_ui 의 4개 국어 원칙과 맞춘다.
    _L4 = {
        "ko": ("확인하기", "닫기", "전체 닫기", "위험도", "##### 🔔 새 경보 {n}건"),
        "en": ("Review", "Dismiss", "Clear all", "Risk", "##### 🔔 {n} new alerts"),
        "ja": ("確認する", "閉じる", "すべて閉じる", "リスク", "##### 🔔 新しいアラート {n}件"),
        "zh": ("查看", "关闭", "全部关闭", "风险", "##### 🔔 {n} 条新告警"),
    }
    L = _L4.get(lang, _L4["ko"])
    now = time.time()

    with st.container(border=True):
        hc1, hc2 = st.columns([5, 1], vertical_alignment="center")
        hc1.markdown(L[4].format(n=len(items)))
        if hc2.button(L[2], key="ops_alert_clear_all", width="stretch"):
            dismiss(ss)
            st.rerun()

        for a in items:
            tid = a["txn_id"]
            accent, ko_t, en_t = _SEV[a["tier"]]
            label = ko_t if lang == "ko" else en_t
            left = max(0, int(float(a.get("_expire", now)) - now))
            c1, c2, c3, c4 = st.columns([1.1, 3.2, 1, 1],
                                        vertical_alignment="center")
            c1.markdown(
                f'<div style="font:800 24px/1 ui-monospace,Consolas,monospace;'
                f'color:{accent};font-variant-numeric:tabular-nums">'
                f'{float(a.get("risk_score") or 0):.3f}</div>'
                f'<div style="font-size:9.5px;font-weight:800;letter-spacing:.09em;'
                f'padding:2px 7px;border-radius:999px;background:{accent};'
                f'color:#0d0d0d;display:inline-block;margin-top:4px">{label}</div>',
                unsafe_allow_html=True)
            c2.markdown(
                f'<div style="font-size:13px;font-weight:700;color:{T["text_primary"]}">'
                f'{fraud_label(a.get("fraud_type"), lang, short=True)}</div>'
                f'<div style="font-size:10.5px;color:{T["text_muted"]};'
                f'font-family:ui-monospace,Consolas,monospace">{tid}'
                f'{" · " + str(a.get("시각")) if a.get("시각") else ""}'
                f'{" · " + str(a.get("source")) if a.get("source") else ""}'
                f' · {left}s</div>', unsafe_allow_html=True)
            if c3.button(L[0], key=f"ops_alert_go_{tid}", type="primary",
                         width="stretch"):
                if on_open:
                    on_open(tid)
                dismiss(ss, tid)
                st.rerun()
            if c4.button(L[1], key=f"ops_alert_dm_{tid}", width="stretch"):
                dismiss(ss, tid)
                st.rerun()
    return True


def render(st, alerts: list[dict], ss, T: dict, fraud_label, lang="ko",
           app_url_param="goto"):
    """경보를 화면에 띄운다. 실패해도 대시보드를 죽이지 않는다.

    구현 메모 — 왜 components.html 인가
      st.markdown(unsafe_allow_html=True) 는 <script> 를 실행하지 않는다(사운드 불가).
      components.html 은 srcdoc iframe 이라 같은 오리진을 상속하므로
      window.parent.document 에 접근할 수 있다. 이 방식이어야
      **탭 컨테이너 밖**(document.body 바로 아래)에 붙어 어느 탭에서든 보인다.
      dashboard.py:1571 의 사이드바 수정 JS 가 쓰는 것과 같은, 이 코드베이스에서
      이미 검증된 기법이다.
    """
    if not alerts:
        return
    try:
        _render(st, alerts, ss, T, fraud_label, lang, app_url_param)
    except Exception as e:                                # pragma: no cover
        log.warning(f"경보 렌더 실패(무시): {type(e).__name__}: {e}")


def _render(st, alerts, ss, T, fraud_label, lang, param):
    payload = []
    for a in alerts:
        _tier = a.get("tier") if a.get("tier") in _SEV else "none"
        accent, ko_t, en_t = _SEV[_tier]
        payload.append({
            "id": str(a.get("txn_id") or "-"),
            "score": float(a.get("risk_score") or 0),
            "type": fraud_label(a.get("fraud_type"), lang, short=True),
            "tier": ko_t if lang == "ko" else en_t,
            # 자동 소멸 시간을 등급으로 정한다. 예전엔 표시 문자열("확정")을 비교해
            # 언어를 바꾸면 확정 경보도 22초 만에 사라졌다 — 코드로 비교한다.
            "sev": _tier,
            "accent": accent,
            "time": str(a.get("시각") or ""),
            "src": str(a.get("source") or ""),
        })

    cfg = {
        "sound": bool(ss.get("alarm_sound", True)),
        "popup": bool(ss.get("alarm_popup", True)),
        "vol": float(ss.get("alarm_volume", 0.25)),
        # 🔁 삐- 소리 반복 횟수. 관제실에서 3회는 짧고 10회는 고문이다 — 사용자가 정한다
        "beeps": max(1, min(10, int(ss.get("alarm_beeps", 3)))),
        "desktop": bool(ss.get("alarm_desktop", True)),
        "param": param,
        # 테마는 컨트롤러가 CSS 변수로 받는다 — 컨트롤러는 1회만 주입되므로
        # 색을 코드에 굽지 않고 매번 넘겨야 테마 전환이 반영된다.
        "theme": {"card": T["bg_card"], "surface": T["bg_surface"],
                  "text": T["text_primary"], "muted": T["text_muted"]},
        "labels": {
            "ko": {"open": "확인하기", "dismiss": "닫기", "clear": "전체 닫기", "hint": "클릭 → 탐지 로그에서 상세 보기",
                   "title": "이상거래 탐지",
                   "body": "이상치 발생 — 대시보드에서 확인하세요", "risk": "위험도"},
            "en": {"open": "Review", "dismiss": "Dismiss", "clear": "Clear all", "hint": "Click → open in detection log",
                   "title": "Anomaly detected",
                   "body": "Anomaly detected — check the dashboard", "risk": "Risk"},
            "ja": {"open": "確認", "dismiss": "閉じる", "clear": "すべて閉じる", "hint": "クリック → 検知ログで詳細",
                   "title": "異常取引を検知",
                   "body": "異常が発生しました — ダッシュボードで確認してください", "risk": "危険度"},
            "zh": {"open": "查看", "dismiss": "关闭", "clear": "全部关闭", "hint": "点击 → 在检测日志中查看",
                   "title": "检测到异常交易",
                   "body": "发生异常 — 请在仪表板中查看", "risk": "风险度"},
        }.get(lang, {}),
    }

    html = (_SOUND_JS
            .replace("__ALERTS__", json.dumps(payload, ensure_ascii=False))
            .replace("__CFG__", json.dumps(cfg, ensure_ascii=False))
            .replace("__STAMP__", str(int(time.time() * 1000))))
    _html(st, html, 0)


# ── 사운드 활성화 (브라우저 정책 우회에 필요한 사용자 제스처) ──
_ARM_HTML = """
<div style="font-family:system-ui;font-size:12px">
<button id="opsArm" style="width:100%;padding:8px 12px;border-radius:9px;cursor:pointer;
  border:1px solid __ACCENT__;background:__ACCENT__22;color:__ACCENT__;font-weight:700">
  🔔 __LABEL__</button>
<div id="opsArmMsg" style="color:__MUTED__;margin-top:6px;line-height:1.5"></div></div>
<script>
(function(){
  var btn=document.getElementById('opsArm'), msg=document.getElementById('opsArmMsg');
  var W=window.parent||window;
  btn.addEventListener('click', function(){
    var out=[];
    // ① 오디오: 브라우저는 사용자 제스처 안에서만 AudioContext 를 깨워준다.
    try{
      var AC=W.AudioContext||W.webkitAudioContext;
      W.__opsAudio = W.__opsAudio || new AC();
      if(W.__opsAudio.state==='suspended'){ W.__opsAudio.resume(); }
      // 무음 1틱을 실제로 재생해야 일부 브라우저가 '활성'으로 인정한다
      var o=W.__opsAudio.createOscillator(), g=W.__opsAudio.createGain();
      g.gain.value=0.0001; o.connect(g); g.connect(W.__opsAudio.destination);
      o.start(); o.stop(W.__opsAudio.currentTime+0.02);
      out.push('🔊 소리 준비됨 ('+W.__opsAudio.state+')');
    }catch(e){ out.push('⚠️ 오디오 실패: '+e.message); }
    // ② 데스크톱 알림 권한 — 이것도 제스처가 필요하다
    try{
      if(W.Notification){
        if(W.Notification.permission==='granted'){ out.push('🖥 알림 허용됨'); }
        else if(W.Notification.permission==='denied'){
          out.push('🚫 알림이 차단돼 있습니다 — 주소창 자물쇠 아이콘에서 허용으로 바꿔주세요');
        } else {
          W.Notification.requestPermission().then(function(p){
            msg.innerHTML += '<br>'+(p==='granted'?'🖥 알림 허용됨':'🚫 알림 거부됨');
          });
          out.push('🖥 알림 권한 요청 중…');
        }
      } else { out.push('⚠️ 이 브라우저는 데스크톱 알림을 지원하지 않습니다'); }
    }catch(e){ out.push('⚠️ 알림 실패: '+e.message); }
    msg.innerHTML = out.join('<br>');
  });
})();
</script>"""


def arm_button(st, T, label="소리·알림 활성화 (1회만)"):
    """오디오/알림 권한을 켜는 버튼. 반드시 사용자 클릭 안에서 실행돼야 한다."""
    _html(st, _ARM_HTML.replace("__ACCENT__", T["accent"])
                       .replace("__MUTED__", T["text_muted"])
                       .replace("__LABEL__", label), 116)


_DIAG_HTML = """
<div style="font-family:system-ui;font-size:12px">
<button id="opsDiag" style="width:100%;padding:7px 12px;border-radius:9px;cursor:pointer;
  border:1px solid __MUTED__;background:transparent;color:__MUTED__;font-weight:700">
  🩺 __LABEL__</button>
<div id="opsDiagMsg" style="color:__MUTED__;margin-top:6px;line-height:1.6"></div></div>
<script>
(function(){
  var btn=document.getElementById('opsDiag'), msg=document.getElementById('opsDiagMsg');
  var W=window.parent||window, D=W.document;
  btn.addEventListener('click', function(){
    var L=[];
    // ① 오디오 컨텍스트 — 'running' 이어야 소리가 난다
    var a = (W.__opsAudio && W.__opsAudio.state) || 'none';
    L.push((a==='running'?'✅':(a==='suspended'?'⚠️':'❌'))+' 오디오: '+a
           + (a==='suspended'?' — 활성화 버튼을 눌러주세요':'')
           + (a==='none'?' — 아직 만들어지지 않음(활성화 필요)':''));
    // ② 데스크톱 알림 권한
    var n = (W.Notification && W.Notification.permission) || 'unsupported';
    L.push((n==='granted'?'✅':(n==='denied'?'🚫':'⚠️'))+' 데스크톱 알림: '+n
           + (n==='denied'?' — 주소창 자물쇠 → 알림 허용으로 바꿔주세요':'')
           + (n==='default'?' — 아직 요청 전(활성화 필요)':''));
    // ③ 컨트롤러 주입 여부 — 이게 없으면 카드가 아예 안 뜬다
    L.push((W.__opsAlert?'✅':'❌')+' 경보 컨트롤러: '+(W.__opsAlert?'주입됨':'없음'));
    // ④ 현재 떠 있는 카드 수
    L.push('🗂 표시 중인 경보 카드: '+D.querySelectorAll('.ops-alert').length+'개');
    // ⑤ 탭 가시성 — 백그라운드 탭은 브라우저가 타이머를 늦춘다
    L.push('👁 탭 상태: '+(D.hidden?'백그라운드(알림 지연 가능)':'활성'));
    // ⑥ 실제 알림 1건 발사 테스트
    if(n==='granted'){
      try{
        var t=new W.Notification('🩺 FDS 알림 테스트',{body:'이 알림이 보이면 데스크톱 알림은 정상입니다.',tag:'ops-diag'});
        W.setTimeout(function(){try{t.close();}catch(e){}}, 6000);
        L.push('📨 테스트 알림을 보냈습니다 — 화면 구석을 확인하세요');
      }catch(e){ L.push('❌ 알림 발사 실패: '+e.message); }
    }
    msg.innerHTML = L.join('<br>');
  });
})();
</script>"""


def diagnostics_button(st, T, label="소리·알림 상태 진단"):
    """브라우저 안의 상태(오디오/알림 권한/컨트롤러)를 읽어 화면에 표시한다.

    파이썬은 이 값들을 알 수 없다 — 전부 사용자 브라우저 안에 있고, Streamlit 은
    컴포넌트에서 부모로 값을 되돌려받는 통로가 없다. 그래서 '읽어서 직접 그린다'.
    """
    _html(st, _DIAG_HTML.replace("__MUTED__", T["text_muted"])
                        .replace("__LABEL__", label), 150)


# ══════════════════════════════════════════════════════════
# JS 템플릿
#
# 🐛 FIX(v21) — "테스트 경보가 사라지지 않고 버튼도 안 눌리던" 버그의 진짜 원인
#
#   components.html / st.iframe 은 **iframe** 을 만든다. 예전 코드는 그 iframe 안에서
#   카드 DOM 을 만들어 **부모 문서**(window.parent.document)에 append 했다.
#   그런데 핸들러(onclick 클로저)와 setTimeout 은 **iframe 의 실행 컨텍스트** 소유다.
#
#   Streamlit 은 리런할 때마다 컴포넌트 iframe 을 파괴하고 새로 만든다. 그 순간
#     · 예약돼 있던 setTimeout 이 **취소된다**      → 카드가 영원히 안 사라짐
#     · onclick 이 참조하던 함수의 realm 이 죽는다  → 버튼을 눌러도 아무 일 없음
#   카드 DOM 은 부모에 있으니 화면에는 그대로 남는다. 정확히 신고된 증상이다.
#
#   → 해결: 로직 전체를 **부모 문서의 <script>** 로 한 번만 주입해 부모 realm 에서
#     돌게 한다. iframe 은 데이터만 넘기는 얇은 전달자가 된다. 부모 realm 은
#     페이지가 살아있는 한 유지되므로 타이머·핸들러가 리런에도 살아남는다.
#
#   f-string 을 쓰지 않는다 — JS·CSS 의 중괄호가 전부 이스케이프 대상이 되어
#   읽을 수 없는 코드가 된다. 치환 토큰 방식이 유지보수에 훨씬 안전하다.
# ══════════════════════════════════════════════════════════

# 부모 문서에 1회 주입되는 컨트롤러. window.__opsAlert 하나만 노출한다.
_SOUND_JS = r"""
<script>
(function(){
  var CFG = __CFG__, ALERTS = __ALERTS__, STAMP = "__STAMP__", SVG = __SVG__;
  var W = window.parent || window, D = W.document;
  if (W.__opsStamp === STAMP) return;           // 같은 rerun 중복 실행 방지
  W.__opsStamp = STAMP;

  // ══════════════════════════════════════════════════════
  // 🔊 자동 무장
  //   브라우저는 사용자 제스처 전에는 오디오를 막는다. 예전에는 담당자가
  //   '활성화' 버튼을 매번 눌러야 했다 — 안 누르면 조용히 무음이었다.
  //   → 페이지 어디든 첫 클릭/키입력에 컨텍스트를 깨운다. 이것도 정당한 제스처다.
  // ══════════════════════════════════════════════════════
  if (!W.__opsArmHook) {
    W.__opsArmHook = true;
    var arm = function(){
      try{
        var AC = W.AudioContext || W.webkitAudioContext;
        if(!AC) return;
        var c = W.__opsAudio || (W.__opsAudio = new AC());
        if (c.state === 'suspended') c.resume();
      }catch(e){}
    };
    D.addEventListener('pointerdown', arm, {capture:true});
    D.addEventListener('keydown', arm, {capture:true});
  }

  function siren(){
    if(!CFG.sound) return;
    try{
      var AC = W.AudioContext || W.webkitAudioContext;
      if(!AC) return;
      var ctx = W.__opsAudio || (W.__opsAudio = new AC());
      if(ctx.state === 'suspended'){ ctx.resume(); }
      var t0 = ctx.currentTime, vol = Math.max(0.0001, Math.min(1, CFG.vol||0.25));
      var n = Math.max(1, Math.min(10, CFG.beeps||3));
      for(var i=0;i<n;i++){
        [[880,0],[1180,0.16]].forEach(function(p){
          var t = t0 + i*0.34 + p[1];
          var o = ctx.createOscillator(), g = ctx.createGain();
          o.type = 'triangle'; o.frequency.setValueAtTime(p[0], t);
          g.gain.setValueAtTime(0.0001, t);                  // 클릭 노이즈 방지
          g.gain.exponentialRampToValueAtTime(vol, t+0.012);
          g.gain.exponentialRampToValueAtTime(0.0001, t+0.15);
          o.connect(g); g.connect(ctx.destination);
          o.start(t); o.stop(t+0.17);
        });
      }
    }catch(e){ console.warn('ops siren:', e); }
  }

  // ══════════════════════════════════════════════════════
  // 🖥 데스크톱 알림 — 클릭하면 탐지 로그로
  // ══════════════════════════════════════════════════════
  function desktop(a){
    if(!CFG.desktop) return;
    try{
      if(!W.Notification || W.Notification.permission !== 'granted') return;
      var L = CFG.labels || {};
      var n = new W.Notification(L.title || '이상거래 탐지', {
        body: (L.body || '') + '\n' + a.type + ' · ' + (L.risk||'위험도') + ' '
              + Number(a.score).toFixed(2) + ' · ' + a.id,
        tag: 'ops-' + a.id, requireInteraction: false
      });
      n.onclick = function(){
        try{
          W.focus();
          var u = new URL(W.location.href);
          u.searchParams.set(CFG.param || 'goto', a.id);
          u.searchParams.set('gototab', 'log');
          u.searchParams.set('_ts', Date.now());
          W.location.href = u.toString();
        }catch(e){}
        n.close();
      };
    }catch(e){ console.warn('ops notify:', e); }
  }

  // ══════════════════════════════════════════════════════
  // 🛰 플로팅 경보 카드 — 우상단 고정 · 레이더 스윕
  //
  // 🐛 이 블록이 예전에 "안 사라지고 버튼도 안 눌리던" 그 코드다.
  //    원인은 카드 자체가 아니라 **클로저와 JS 타이머**였다.
  //    iframe 은 리런마다 파괴되는데, 거기서 만든 onclick 클로저와
  //    setTimeout 은 iframe realm 소유라 함께 죽는다. 카드 DOM 은
  //    부모에 남아 있으니 화면에는 그대로 보였다.
  //
  //    → 이번엔 **클로저를 하나도 쓰지 않는다.**
  //      · 닫기(X)   : 인라인 onclick **속성**. 부모 문서가 컴파일하므로
  //                    iframe 이 죽어도 그대로 동작한다(클로저가 아니다).
  //      · 자동 소멸 : JS 타이머 대신 **CSS 애니메이션**. 렌더링 엔진이
  //                    돌리므로 어떤 realm 과도 무관하다.
  //      · 클릭 이동 : JS 없이 <a href>. 순수 브라우저 내비게이션.
  //    덕분에 레이더 애니메이션을 그대로 살리면서도 동작이 보장된다.
  // ══════════════════════════════════════════════════════
  function ensureStyle(){
    if (D.getElementById('ops-alert-style')) return;
    var s = D.createElement('style'); s.id = 'ops-alert-style';
    s.textContent = [
      '#ops-alert-wrap{position:fixed;top:14px;right:14px;z-index:2147483647;',
      '  display:flex;flex-direction:column;gap:10px;max-width:340px;',
      '  font-family:system-ui,-apple-system,"Segoe UI",sans-serif;pointer-events:none}',
      '.ops-alert{pointer-events:auto;background:var(--ops-card,#1a1e26);color:var(--ops-text,#eee);',
      '  border-radius:14px;padding:13px 15px;display:flex;gap:12px;align-items:flex-start;',
      '  border:1px solid rgba(255,255,255,.10);border-left:4px solid var(--sev);',
      '  box-shadow:0 12px 40px rgba(0,0,0,.5),0 0 0 1px var(--sev);',
      '  position:relative;overflow:hidden;text-decoration:none;',
      // ⏱ 자동 소멸을 CSS 로 — animation-delay 로 TTL 을 준다.
      //   forwards 라 마지막 프레임(투명·높이0)이 유지된다.
      '  animation:opsIn .42s cubic-bezier(.16,1,.3,1) both,',
      '            opsOut .55s ease var(--ttl,22s) forwards}',
      '.ops-alert::before{content:"";position:absolute;inset:0;border-radius:14px;',
      '  background:radial-gradient(120% 80% at 100% 0%,var(--sev),transparent 62%);',
      '  opacity:.13;pointer-events:none}',
      '.ops-alert .halo{position:absolute;inset:-2px;border-radius:14px;border:1px solid var(--sev);',
      '  opacity:0;animation:opsHalo 1.4s ease-out 3}',
      '@keyframes opsIn{from{opacity:0;transform:translateX(26px) scale(.96)}to{opacity:1;transform:none}}',
      '@keyframes opsOut{to{opacity:0;transform:translateX(26px);visibility:hidden;',
      '  height:0;min-height:0;margin:0;padding-top:0;padding-bottom:0;border-width:0}}',
      '@keyframes opsHalo{0%{opacity:.85;transform:scale(1)}100%{opacity:0;transform:scale(1.07)}}',
      '@keyframes opsSweep{to{transform:rotate(360deg)}}',
      '@keyframes opsBlip{0%,100%{opacity:.25}50%{opacity:1}}',
      '.opsRadarSweep{animation:opsSweep 2.4s linear infinite}',
      '.opsRadarBlip{animation:opsBlip 1.4s ease-in-out infinite}',
      '.ops-alert .sc{font:800 27px/1 ui-monospace,Consolas,monospace;color:var(--sev);',
      '  font-variant-numeric:tabular-nums;letter-spacing:-.02em}',
      '.ops-alert .tp{font-size:13px;font-weight:700;margin-top:3px;color:var(--ops-text,#eee)}',
      '.ops-alert .mt{font-size:10.5px;color:var(--ops-muted,#888);margin-top:3px;',
      '  font-family:ui-monospace,Consolas,monospace;word-break:break-all}',
      '.ops-alert .badge{display:inline-block;font-size:9.5px;font-weight:800;',
      '  letter-spacing:.09em;padding:2px 7px;border-radius:999px;',
      '  background:var(--sev);color:#0d0d0d}',
      '.ops-alert .hint{font-size:9.5px;color:var(--ops-muted,#888);margin-top:6px;opacity:.75}',
      // ✕ 닫기 — 카드 우상단. 링크 위에 겹치므로 z-index 로 띄운다
      '.ops-x{position:absolute;top:7px;right:9px;z-index:3;cursor:pointer;',
      '  width:20px;height:20px;line-height:18px;text-align:center;border-radius:6px;',
      '  font-size:13px;font-weight:700;color:var(--ops-muted,#888);',
      '  border:1px solid rgba(255,255,255,.14);background:rgba(0,0,0,.25);',
      '  user-select:none}',
      '.ops-x:hover{color:#fff;background:var(--sev);border-color:var(--sev)}',
      '@media (prefers-reduced-motion:reduce){',
      '  .ops-alert{animation:opsOut .55s ease var(--ttl,22s) forwards}',
      '  .ops-alert .halo,.opsRadarSweep,.opsRadarBlip{animation:none!important}}'
    ].join('');
    D.head.appendChild(s);
  }

  function cards(){
    if(!CFG.popup || !(ALERTS||[]).length) return;
    ensureStyle();
    var w = D.getElementById('ops-alert-wrap');
    if(!w){ w = D.createElement('div'); w.id='ops-alert-wrap'; D.body.appendChild(w); }
    var th = CFG.theme || {};
    w.style.setProperty('--ops-card', th.card || '#1a1e26');
    w.style.setProperty('--ops-text', th.text || '#eee');
    w.style.setProperty('--ops-muted', th.muted || '#888');

    var L = CFG.labels || {};
    ALERTS.forEach(function(a){
      // 같은 거래가 이미 떠 있으면 새로 만들지 않는다
      if (w.querySelector('[data-ops-id="' + String(a.id).replace(/"/g,'') + '"]')) return;

      // 🔗 카드 전체가 링크다. JS 를 전혀 쓰지 않는 순수 내비게이션이라
      //    iframe 이 죽든 말든 항상 동작한다. 목적지는 탐지 로그.
      var href = W.location.pathname + '?' + CFG.param + '=' +
                 encodeURIComponent(a.id) + '&gototab=log&_ts=' + Date.now();
      var el = D.createElement('a');
      el.className = 'ops-alert';
      el.setAttribute('data-ops-id', String(a.id));
      el.setAttribute('href', href);
      el.style.setProperty('--sev', a.accent);
      el.style.setProperty('--ttl', (a.sev === 'confirm' ? 45 : 22) + 's');
      el.innerHTML =
        '<div class="halo"></div>' +
        // ✕ — 인라인 속성 핸들러(클로저 아님) + 링크 이동 차단
        '<div class="ops-x" title="' + (L.dismiss||'닫기') + '"' +
        ' onclick="event.preventDefault();event.stopPropagation();' +
        'var c=this.parentNode;c.remove();' +
        'var p=document.getElementById(\'ops-alert-wrap\');' +
        'if(p&&!p.querySelector(\'.ops-alert\'))p.remove();return false;">✕</div>' +
        '<div style="color:' + a.accent + '">' + SVG + '</div>' +
        '<div style="flex:1;min-width:0">' +
          '<span class="badge">' + a.tier + '</span>' +
          '<div class="sc">' + Number(a.score).toFixed(3) + '</div>' +
          '<div class="tp">' + a.type + '</div>' +
          '<div class="mt">' + a.id + (a.time ? (' · ' + a.time) : '') + '</div>' +
          '<div class="hint">' + (L.hint || '클릭 → 탐지 로그에서 상세 보기') + '</div>' +
        '</div>';
      w.appendChild(el);
    });
  }

  (ALERTS||[]).forEach(desktop);
  cards();
  if ((ALERTS||[]).length) siren();
})();
</script>"""


# SVG 는 런타임에 JSON 문자열로 주입된다 (카드가 innerHTML 로 쓴다)
_SOUND_JS = _SOUND_JS.replace("__SVG__", json.dumps(_card_svg()))

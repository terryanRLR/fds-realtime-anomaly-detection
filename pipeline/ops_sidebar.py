"""
ops_sidebar — 관제 대시보드 사이드바 (dashboard.py 사이드바 이식 + 관제 전용 항목)

왜 사이드바인가
  ops_dashboard 는 원래 헤더의 ⋮ 팝오버 하나에 DB 경로·검토자·언어·테마·마스킹만
  들어 있었다. 판정 임계값도, 탐지 모델도, 데이터셋도 고를 수 없어서 "탐지 입력"
  탭이 사실상 반쪽이었다. dashboard.py 의 사이드바(1796~2008행)를 이식해
  **한 화면에서 조작 가능한 값 전부**를 왼쪽에 모은다.

설정의 단일 출처 원칙
  같은 값을 두 곳에서 고칠 수 있으면 반드시 어긋난다. 그래서
    · ⋮ 팝오버에 있던 db_path/reviewer/lang/theme/pii_level → 여기로 이주 (팝오버에선 제거)
    · AI 탭 '분석 설정' 익스팬더의 ai_* 키 → 여기로 이주 (탭에선 제거)
  위젯 key 는 **기존 이름을 그대로 유지**한다. 본문 코드가
  st.session_state['ai_slack_webhook'] 처럼 읽고 있어서, 키를 바꾸면 전부 깨진다.

여기 없는 것 (일부러 탭에 남긴 것)
  auto_refresh/_refresh_sec(실시간 감시) · window_h(오탐 분석) · fp_cost/fn_cost(튜닝).
  화면을 보면서 즉시 돌리는 값이라, 그 탭 안에 있는 편이 맞다.

배치 원칙 — '만지는 빈도'가 순서다 (v21)
  v20 까지는 dashboard.py 에서 이식한 순서(임계값→모델→데이터셋→AI→…)를 그대로 썼고,
  정작 **근무를 시작할 때마다** 고치는 검토자 이름이 8번째라 스크롤해야 닿았다.
  온보딩(ops_guide)의 퀵스타트 1번이 "검토자 이름을 바꾸세요"인데 말이다.
  그래서 다음 3층으로 다시 세웠다.
    ① 상태  — 판정자·워처 생존. 설정이 아니라 '지금 어떤가'라서 항상 보여야 한다
    ② 매일  — 관제 설정 · 임계값 · 모델 · 데이터셋
    ③ 1회   — ⚙ 고급 설정(LLM·알림 채널·음성·표시·버전) 한 덩어리로 접는다

  ⚠ 고급 설정은 반드시 **st.expander** 여야 한다. st.toggle 로 감싸 `if` 로 걸면
    접힌 동안 위젯이 인스턴스화되지 않고, Streamlit 이 그 key 를 세션에서 청소한다 —
    API 키·Slack Webhook 이 접을 때마다 사라진다. expander 는 접혀 있어도 내용을
    항상 만들기 때문에(접기는 CSS다) 값이 유지된다.
    그 대가로 expander 를 중첩할 수 없으므로, 안쪽 expander 는 소제목으로 폈다.

  ⚠ 관제 설정이 모델 섹션보다 **위**에 있어야 한다. '📁 경로'의 model_dir 입력이
    관제 설정 안에 있고 모델 목록이 그 값을 읽는다 — 아래에 있으면 폴더를 바꿔도
    한 번 더 새로고침해야 목록이 갱신됐다.
"""

from __future__ import annotations

import html
import logging
from pathlib import Path

import streamlit as st

OPS_SIDEBAR_VERSION = "v24"

log = logging.getLogger("ops_sidebar")

try:
    from pipeline import asset_registry as ar
except ImportError:                                    # pragma: no cover
    import asset_registry as ar

# 경보 설정 공유(alarm_prefs.json). 없으면 세션 전용으로 조용히 내려간다.
try:
    from pipeline import ops_alert as _oa
except ImportError:                                    # pragma: no cover
    _oa = None


def _save_alarm_prefs():
    if _oa:
        _oa.save_prefs(st.session_state)

try:
    from pipeline import ops_ui as ui
except ImportError:                                    # pragma: no cover
    import ops_ui as ui

try:
    from pipeline import review_store as rs
except ImportError:                                    # pragma: no cover
    import review_store as rs

# 워처 설정 — '경보 등급의 진실'을 사이드바에 그대로 비춰 주기 위해서만 읽는다(쓰지 않음)
try:
    from pipeline import watcher_config as wcfg
except ImportError:                                    # pragma: no cover
    try:
        import watcher_config as wcfg
    except ImportError:
        wcfg = None

PROVIDERS = ["local", "anthropic", "openai", "deepseek", "moonshot", "custom"]

TTS_VOICES = {"ko": "한국어", "en": "English", "ja": "日本語", "zh": "中文"}

# 사이드바가 소유하는 상태의 기본값. ops_dashboard._DEFAULTS 와 겹치지 않는 것만.
SIDEBAR_DEFAULTS = {
    "th_slider": 0.5,
    "dual_threshold": False,
    "th_review": 0.6,
    "th_confirm": 0.8,
    "selected_model": "",
    "ds_folder": "data/",
    "selected_dataset": "",
    "tts_lang": "ko",
    "ai_llm_provider": "local",
    # 탐지 직후 AI 분석까지 한 번에 — 기본 ON. 이상거래를 본 담당자가 원하는
    # 다음 동작은 거의 항상 '이유 알기'다. 급할 때만 끈다.
    "ai_auto_run": True,
    "ai_rag_k": 3,
    "ai_pii_skip_local": True,
    "ai_llama_url": "",
    "ai_anthropic_key": "",
    "ai_openai_key": "",
    "ai_deepseek_key": "",
    "ai_moonshot_key": "",
    "ai_custom_url": "",
    "ai_custom_model": "",
    "ai_custom_key": "",
    "ai_slack_webhook": "",
    "ai_notify_email": "",
    "ai_smtp_user": "",
    "ai_smtp_pass": "",
    # 리치 알림(Slack 시각화 헤더 · Email KPI + HTML 리포트 첨부). dashboard.py 의
    #   'rich_notify' 와 같은 기본값 ON — 두 화면의 발송물이 같아야 하기 때문이다.
    "ai_rich_notify": True,
    # 자동 발송은 되돌릴 수 없다 — 켜는 것은 명시적 행동이어야 하므로 기본 OFF
    "auto_slack": False,
    "auto_email": False,
    # SLA · 교대 · 동시 판정 잠금
    "sla_min": 30,
    "shift_hours": 8,
    "claim_on": True,
    # 챗봇은 기본 접힘 — 사이드바 세로 공간을 늘 먹으면 설정이 안 보인다
    "chat_open": False,
}


def init_state(session_state) -> None:
    """위젯을 그리기 전에 호출. 기본값을 세션에 심어두면 이후 위젯은
    value=/index= 없이 key 만으로 만들 수 있다 — Streamlit 이 '무엇이 진실인가'로
    경고를 내는 상황 자체가 생기지 않는다."""
    for k, v in SIDEBAR_DEFAULTS.items():
        session_state.setdefault(k, v)


def _section(title: str, T: dict):
    st.markdown(
        f'<div style="font-size:10.5px;font-weight:700;letter-spacing:0.08em;'
        f'text-transform:uppercase;color:{T["text_muted"]};margin:14px 0 6px">{title}</div>',
        unsafe_allow_html=True)


def _note(text: str, T: dict, color: str | None = None):
    st.markdown(
        f'<div style="color:{color or T["text_muted"]};font-size:10.5px;'
        f'line-height:1.55;margin:-4px 0 4px">{text}</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════
# 섹션들
# ══════════════════════════════════════════════════════════
def _threshold_section(T: dict, t) -> dict:
    """판정 임계값 + 이중 임계값(발송 등급).

    dashboard.py 는 검증셋 기준 비용곡선에서 임계값을 얻지만, 관제에서는
    담당자가 직접 만지는 값이다. '⚙ 임계값 튜닝' 탭이 실판정 기반 추천치를
    계산해 주면 여기 슬라이더로 옮겨 적용한다.

    ⚠️ 여기 값은 **이 콘솔이 내보내는 통보의 등급**(ops_dispatch.notify_tier)이다.
       워처가 쏘는 경보의 등급은 watcher_config.json 이 정한다 — 별개의 값이다.
       예전에는 둘 다 'th_review/th_confirm' 이라는 같은 이름으로 불리면서
       화면 어디에도 구분이 없어, 사이드바가 0.50 을 보여주는 동안 워처는
       0.005/0.9 로 돌고 있었다. 이제 ui.threshold_matrix 가 셋을 나란히 보여준다.
    """
    _section("🎯 " + t("sb.threshold_label"), T)

    # 워처가 실제로 쓰는 값 — 사이드바 슬라이더와 다를 수 있고, 다른 게 정상이다
    _wc = wcfg.load() if wcfg else {}
    _w_thr, _w_thc = _wc.get("th_review"), _wc.get("th_confirm")

    # 튜닝 탭이 추천치를 예약해 두면 여기서 소비한다.
    # Streamlit 은 위젯 생성 '후' 그 key 를 고치면 예외를 던지므로 반드시 생성 직전에.
    if "_pending_threshold" in st.session_state:
        st.session_state["th_slider"] = float(st.session_state.pop("_pending_threshold"))

    threshold = st.slider(t("sb.threshold_label"), 0.0, 1.0, step=0.01,
                          key="th_slider", label_visibility="collapsed",
                          help=t("sb.threshold_help"))

    st.toggle(t("sb.dual"), key="dual_threshold", help=t("sb.dual_help"))
    if st.session_state["dual_threshold"]:
        t1 = st.slider(t("sb.th_review"), 0.0, 1.0, step=0.01, key="th_review")
        t2 = st.slider(t("sb.th_confirm"), 0.0, 1.0, step=0.01, key="th_confirm")
        if t2 < t1:
            _note(t("sb.dual_inverted", v=f"{max(t1, t2):.2f}"), T, T["amber"])
        t2e = max(t1, t2)
        out = {"threshold": float(threshold), "dual": True,
               "th_review": float(t1), "th_confirm": float(t2e)}
    else:
        out = {"threshold": float(threshold), "dual": False,
               "th_review": float(threshold), "th_confirm": float(threshold)}

    # ── 임계값 3종 대조표 ──────────────────────────────────
    #   "지금 이 화면의 숫자"와 "워처가 실제로 쓰는 숫자"를 같은 자리에서 본다.
    #   캡션 한 줄로 워처 값만 보여주던 예전 방식은, 정작 어긋나기 쉬운
    #   ②탐지 판정 · ③발송 등급을 비교 대상에 넣지 못했다.
    st.markdown(ui.threshold_matrix(
        watcher=(_w_thr, _w_thc), detect=out["threshold"],
        dispatch=(out["th_review"], out["th_confirm"]), dual=out["dual"],
        compact=True), unsafe_allow_html=True)
    return out


def _model_section(T: dict, t, lang: str) -> dict:
    """전역 탐지 모델 — 탐지 입력·재검증·진단이 모두 이 선택을 따른다."""
    _section("🧠 " + t("sb.model_section"), T)
    model_dir = st.session_state.get("model_dir", "models/")
    avail = ar.get_available_models(model_dir, lang)
    names = list(avail.keys())

    # 최초 진입 시 1회만 자동 선택. 이후 사용자 변경은 그대로 유지한다.
    if not st.session_state.get("_model_default_applied"):
        st.session_state["selected_model"] = ar.preferred_model_name(avail)
        st.session_state["_model_default_applied"] = True

    cur = st.session_state.get("selected_model")
    idx = names.index(cur) if cur in names else 0
    sel = st.selectbox(t("sb.model_select_label"), names, index=idx,
                       key="model_sel_global", label_visibility="collapsed",
                       format_func=lambda x: ar.display_name(x, lang),
                       help=t("sb.model_select_help"))
    st.session_state["selected_model"] = sel

    info = avail.get(sel, {})
    path = info.get("path", "-")
    exists = Path(path).exists() if path != "-" else False
    badge = (f'<span style="color:{T["green"]}">● 로드 가능</span>' if exists
             else f'<span style="color:{T["red"]}">● 파일 없음</span>')
    st.markdown(
        f'<div style="color:{T["text_muted"]};font-size:10.5px;'
        f'font-family:var(--font-mono);margin-top:-4px;word-break:break-all">'
        f'{badge} · {path}</div>', unsafe_allow_html=True)
    if info.get("desc"):
        st.caption(info["desc"])
    return {"models": avail, "name": sel, "path": path, "exists": exists}


def _dataset_section(T: dict, t) -> dict:
    """평가/샘플 데이터셋 — '탐지 입력' 탭의 test.csv·train.csv 모드가 쓴다."""
    _section(t("sb.sec_dataset"), T)
    folder = st.text_input(t("sb.ds_folder"), key="ds_folder",
                           help=t("sb.ds_folder_help"))
    found = ar.discover_ds(folder)
    if not found:
        st.caption(t("sb.ds_none", path=folder))
        return {"found": {}, "name": None}

    names = list(found.keys())
    cur = st.session_state.get("selected_dataset") or ar.preferred_dataset(found)
    idx = names.index(cur) if cur in names else 0
    sel = st.selectbox(t("sb.dataset"), names, index=idx, key="ds_sel_global",
                       label_visibility="collapsed",
                       format_func=lambda x: ar.dataset_label(x, found))
    st.session_state["selected_dataset"] = sel
    st.caption(getattr(found[sel], "note", ""))
    return {"found": found, "name": sel}


def _ai_section(T: dict, t) -> None:
    """LLM 제공자 · API 키 · 알림 채널. AI 탭 익스팬더에서 이주해 온 것.

    ⚠ 여기서 expander 를 쓰면 안 된다 — 호출부가 이미 '⚙ 고급 설정' expander
      안이라 중첩이 되고, Streamlit 이 예외를 던진다. 소제목으로 구분한다."""
    _section("🤖 " + t("ai.settings"), T)
    provider = st.selectbox(t("ai.provider"), PROVIDERS, key="ai_llm_provider")
    st.number_input("RAG top_k", min_value=1, max_value=10, key="ai_rag_k",
                    help=t("sb.rag_k_help"))

    if provider == "anthropic":
        st.text_input("Anthropic API Key", key="ai_anthropic_key", type="password")
    elif provider == "openai":
        st.text_input("OpenAI API Key", key="ai_openai_key", type="password")
    elif provider == "deepseek":
        st.text_input("DeepSeek API Key", key="ai_deepseek_key", type="password")
    elif provider == "moonshot":
        st.text_input("Moonshot API Key", key="ai_moonshot_key", type="password")
    elif provider == "custom":
        st.text_input("Custom URL", key="ai_custom_url")
        st.text_input("Custom Model", key="ai_custom_model")
        st.text_input("Custom API Key", key="ai_custom_key", type="password")
    else:
        st.text_input(t("sb.llama_url"), key="ai_llama_url",
                      placeholder="http://localhost:8080")
        st.toggle(t("sb.pii_skip_local"), key="ai_pii_skip_local",
                  help=t("sb.pii_skip_local_help"))
    st.caption(t("sb.env_note"))

    _section(t("sb.sec_channel"), T)
    st.text_input("Slack Webhook URL", key="ai_slack_webhook", type="password")
    st.text_input(t("ai.email_to"), key="ai_notify_email",
                  placeholder="ops@company.com")
    st.text_input("SMTP User", key="ai_smtp_user")
    st.text_input("SMTP Password", key="ai_smtp_pass", type="password")

    # 리치 알림 — 끄면 '머리말 + LLM 텍스트' 평문으로 나간다(예전 동작).
    st.toggle(t("notif.rich_toggle"), key="ai_rich_notify", help=t("notif.rich_help"))

    # 자동 발송 — 탐지 즉시 사람에게 밀어낸다. 되돌릴 수 없으므로 기본 OFF.
    st.toggle(t("sb.auto_slack"), key="auto_slack", help=t("sb.auto_slack_help"))
    st.toggle(t("sb.auto_email"), key="auto_email", help=t("sb.auto_email_help"))
    if st.session_state.get("dual_threshold") and (
            st.session_state.get("auto_slack") or st.session_state.get("auto_email")):
        _note(t("sb.dual_active"), T)
    if st.session_state.get("auto_email") and not st.session_state.get("ai_notify_email"):
        _note(t("sb.no_recipient"), T, T["amber"])


def _voice_section(T: dict, t) -> None:
    """TTS 언어만. 경보의 **마스터 스위치는 '🛡 관제 설정'** 으로 올렸고(v22),
    세부 설정(사운드/데스크톱/조용한시간/등급)은 여전히 ops_alert 가 '실시간 감시'
    탭에서 소유한다 — 한 묶음이라 쪼개면 오히려 헷갈린다."""
    _section(t("sb.sec_voice"), T)
    st.selectbox(t("sb.tts_lang"), list(TTS_VOICES.keys()), key="tts_lang",
                 format_func=lambda x: TTS_VOICES[x])


def _ops_section(T: dict, t, lang: str) -> None:
    """관제 전용 — 검토자·SLA·경로·마스킹. ⋮ 팝오버에서 이주해 온 것."""
    _section(t("sb.sec_ops"), T)
    st.text_input(t("tri.reviewer"), key="reviewer",
                  help=t("sb.reviewer_help"))
    # 챗봇이 예약해 둔 SLA 를 여기서 소비한다 (ops_agent.set_sla).
    #   위젯 생성 **직전**이어야 한다 — 생성 후엔 Streamlit 이 key 수정을 막는다.
    if "_pending_sla" in st.session_state:
        st.session_state["sla_min"] = int(st.session_state.pop("_pending_sla"))
    s1, s2 = st.columns(2)
    with s1:
        st.number_input(t("sb.sla"), 5, 480, step=5, key="sla_min",
                        help=t("sb.sla_help"))
    with s2:
        st.number_input(t("sb.shift_h"), 1, 24, step=1, key="shift_hours",
                        help=t("sb.shift_h_help"))
    st.toggle(t("sb.claim"), key="claim_on",
              help=t("sb.claim_help", n=rs.CLAIM_TTL_MIN))
    st.selectbox(t("sb.pii_level"), ["off", "basic", "standard", "strict"],
                 key="pii_level", help=t("sb.pii_level_help"))

    # ── 🔔 경보 마스터 ────────────────────────────────────
    #   세부 설정(사운드·데스크톱·조용한시간·등급·중복억제·테스트)은 계속
    #   '🟢 실시간 감시' 탭이 소유한다 — 한 묶음이라 쪼개면 오히려 헷갈린다는
    #   판단은 그대로다(모듈 상단 주석). 여기 두는 것은 셋뿐이다:
    #     ① 켜짐/꺼짐  ② 지금 어떤 등급으로 울리나  ③ 세부 설정으로 가는 길
    #   근거: "알람 어떻게 꺼요?"의 답이 탭 안쪽 접힌 패널이면 아무도 못 찾고,
    #   결국 스피커를 꺼버린다 — 그러면 경보 기능 전체가 죽는다.
    if "alarm_on" in st.session_state:
        # 마스터 스위치도 파일에 남긴다 — dashboard.py 세션5 의 경보와 한 벌이라,
        #   여기서 끄면 그쪽도 조용해져야 "알람을 껐다"가 사실이 된다.
        st.toggle(t("sb.alarm_master"), key="alarm_on", help=t("sb.alarm_master_help"),
                  on_change=_save_alarm_prefs)
        _tier = st.session_state.get("alarm_tier", "confirm")
        _tier_txt = t(f"alarm.tier_{_tier}_short") if _tier in ("confirm", "review", "all") else _tier
        _note(t("sb.alarm_tier_now", tier=_tier_txt), T,
              T["green"] if st.session_state.get("alarm_on") else T["text_muted"])
        if st.button(t("sb.alarm_open"), key="sb_alarm_open", width="stretch",
                     help=t("sb.alarm_open_help")):
            st.session_state["_force_tab"] = "live"
            st.session_state["_open_alarm"] = True     # 패널을 펼친 채로 연다
            st.rerun()
    with st.expander(t("sb.paths"), expanded=False):
        st.text_input(t("common.db"), key="db_path")
        st.text_input(t("sb.log_path"), key="log_path")
        st.text_input(t("sb.model_dir"), key="model_dir")
        st.text_input(t("sb.inbox"), key="watch_inbox", help=t("sb.inbox_help"))


def _appearance_section(T: dict, t, lang: str) -> None:
    _section(t("sb.sec_appearance"), T)
    lg = st.radio(t("common.lang"), ui.LANG_OPTIONS, horizontal=True,
                  index=ui.LANG_OPTIONS.index(lang) if lang in ui.LANG_OPTIONS else 0,
                  format_func=lambda x: ui.LANG_DISPLAY.get(x, x), key="_lang_pick")
    if lg != lang:
        st.session_state["lang"] = lg
        st.rerun()
    cur_theme = st.session_state.get("theme", ui.DEFAULT_THEME)
    th = st.selectbox(t("common.theme"), ui.THEME_ORDER,
                      index=ui.THEME_ORDER.index(cur_theme)
                      if cur_theme in ui.THEME_ORDER else 0,
                      format_func=lambda k: ui.theme_display(k, lang), key="_theme_pick")
    if th != cur_theme:
        st.session_state["theme"] = th
        st.rerun()


def _watcher_badge() -> None:
    """워처 하트비트 배지. 모듈이 없거나 DB가 비어도 대시보드는 영향받지 않는다.

    ⚠ db_path/poll_interval 을 **넘겨야** 한다. 예전엔 인자 없이 불러 배지가
      watcher_panel.DEFAULT_DB 를 읽었다 — 사이드바에서 DB 경로를 바꾼 사람은
      다른 DB의 하트비트를 자기 것으로 착각하게 된다."""
    try:
        from pipeline.watcher_panel import render_watcher_badge
    except ImportError:
        return
    try:
        render_watcher_badge(st.session_state.get("db_path", "fds_results.db"),
                             float(st.session_state.get("poll_interval", 5.0)))
    except Exception as e:
        log.debug(f"워처 배지 생략: {e}")


def _identity_bar(T: dict, t) -> None:
    """지금 이 화면이 '누구로' 기록되는지 + 워처가 살아 있는지.

    둘 다 설정이 아니라 **상태**다. 검토자 이름은 판정·잠금·임시저장이 전부 묶이는
    값이라 틀린 채로 한 시간 일하면 되돌릴 수 없고, 워처 생존은 관제에서 가장 자주
    흘끗 보는 값이다. v20 까지 전자는 8번째 섹션, 후자는 맨 마지막에 있었다.
    """
    who = (st.session_state.get("reviewer") or "").strip()
    ok = bool(who)
    # ⚠ f-string 안에서 같은 종류의 따옴표를 중첩하면 Python 3.11 에서는 문법
    #   오류다(3.12+ 만 허용). 이 앱의 실행 환경은 3.11 이므로 밖에서 꺼내 둔다.
    _no_name = t("sb.no_name_hint")
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:6px;font-size:11px;'
        f'margin:-4px 0 2px">'
        f'<span style="color:{T["text_muted"]}">{t("sb.identity")}</span>'
        f'<b style="color:{T["text_primary"] if ok else T["amber"]}">'
        f'{html.escape(who) if ok else _no_name}</b></div>',
        unsafe_allow_html=True)
    _watcher_badge()


# ══════════════════════════════════════════════════════════
# 진입점
# ══════════════════════════════════════════════════════════
def render(t, T: dict, lang: str, versions: dict | None = None,
           chat_panel=None, editors=None) -> dict:
    """사이드바 전체를 그리고, 본문이 쓸 값을 dict 로 돌려준다.

    반환 키: threshold · dual · th_review · th_confirm · model · dataset · rag_k
    (나머지 설정은 전부 st.session_state 로 읽으면 된다)

    chat_panel: AI 어시스턴트를 그리는 콜러블. 사이드바는 어느 탭에 있든
      보이므로, 챗봇을 여기 두면 "질문하려고 탭을 옮기는" 단계가 사라진다.

    순서는 '만지는 빈도'다 — 모듈 상단 주석의 3층 구조를 그대로 따른다.
    """
    init_state(st.session_state)
    _brand_sub = t("sb.brand_sub")      # f-string 안 따옴표 중첩 회피 (3.11)
    with st.sidebar:
        # ── ① 상태 — 내가 누구로 기록되나 · 워처는 살아있나 ─
        st.markdown(
            f'<div style="padding:0 0 8px">'
            f'<div style="font-size:15px;font-weight:800;color:{T["accent"]};'
            f'letter-spacing:-0.01em">🛡 FDS Ops Console</div>'
            f'<div style="font-size:10px;color:{T["text_muted"]};margin-top:2px;'
            f'letter-spacing:0.04em">{_brand_sub}</div>'
            f'<div style="height:1px;background:linear-gradient(90deg,'
            f'rgba({T["accent_rgb"]},0.45),transparent);margin:9px 0 7px"></div></div>',
            unsafe_allow_html=True)
        _identity_bar(T, t)

        # ── 🤖 AI 어시스턴트 — 상태 바로 아래 ───────────────
        #   설정 아래로 내리면 스크롤해야 닿는다. 급할 때 묻는 물건이라
        #   '항상 같은 자리, 스크롤 없이'가 접근성의 전부다.
        if chat_panel is not None:
            st.toggle(t("sb.chat"), key="chat_open", help=t("sb.chat_help"))
            if st.session_state.get("chat_open"):
                with st.container(border=True):
                    chat_panel()
            st.divider()

        # ── ② 매일 만지는 것 ────────────────────────────────
        #   관제 설정이 맨 앞이다. 근무 시작마다 검토자 이름을 확인/변경하는 것이
        #   이 화면의 첫 동작이고(ops_guide 퀵스타트 1번), 이름이 틀린 채로 찍은
        #   판정은 되돌릴 수 없다. 모델 섹션보다 위여야 하는 이유는 모듈 주석 참조.
        _ops_section(T, t, lang)
        th = _threshold_section(T, t)
        model = _model_section(T, t, lang)
        dataset = _dataset_section(T, t)

        # ── ③ 대개 최초 1회만 정하는 것 ─────────────────────
        #   expander 여야 한다(toggle+if 금지) — 이유는 모듈 상단 주석.
        with st.expander(t("sb.advanced"), expanded=False):
            st.caption(t("sb.advanced_note"))
            _ai_section(T, t)
            _voice_section(T, t)
            _appearance_section(T, t, lang)
            if versions:
                _section(t("sb.modules"), T)
                st.code("\n".join(f"{k:<15}{v}" for k, v in versions.items()),
                        language="text")

        # ── 🖊 프롬프트 · 📚 RAG 편집기 ─────────────────────
        #   ⚠ '⚙ 고급 설정' expander **밖**이어야 한다. 두 렌더러가 각자
        #     st.expander 를 열기 때문에 안에 넣으면 중첩으로 죽는다.
        #     성격은 ③(대개 한 번만 정하는 것)이라 자리는 여기가 맞다.
        if editors is not None:
            st.caption(t("sb.editors_note"))
            editors()

        # ── 🎓 사용 안내 — 평생 한두 번이라 맨 아래 ─────────
        st.divider()
        if st.button(t("sb.guide_again"), key="sb_guide", width="stretch",
                     help=t("sb.guide_again_help")):
            st.session_state["_ops_guide_open"] = True
            st.rerun()

    return {**th, "model": model, "dataset": dataset,
            "rag_k": int(st.session_state.get("ai_rag_k", 3))}

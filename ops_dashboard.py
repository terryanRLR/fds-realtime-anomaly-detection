"""
ops_dashboard — 관제 · 오탐 전용 대시보드  ✨ v19 신규

메인 대시보드(dashboard.py)와의 관계
  · 메인은 **분석·검증** 도구다 — 데이터셋을 골라 모델 성능을 보고, 합성데이터를 만든다.
  · 이것은 **운영** 도구다 — 무인 워처가 24시간 돌면서 쏘는 알림을 사람이 받아
    정탐/오탐을 판정하고, 그 판정으로 임계값을 조정한다.
  두 도구는 같은 DB(fds_results.db)와 같은 판정 엔진(DetectService)을 공유하지만
  화면 수명이 다르다. 메인은 "열어서 본다", 이것은 "켜 둔다".

기존에 없던 것 (= 이 앱의 존재 이유)
  1. 오탐 피드백 루프 — batch_analyzer.py:491 이 남긴 TODO 를 실제로 닫는다.
  2. 실제 판정 기반 임계값 튜닝 — 세션2의 비용곡선은 검증셋(정적 라벨) 기준이라
     운영 분포와 다르다. 여기서는 담당자가 찍은 실제 정탐/오탐으로 계산한다.
  3. 자동 갱신 — 기존 워처 패널은 🔄 버튼이 전부였다. st.fragment 로 관제 패널만
     부분 리런한다(전체 리런하면 모델·데이터셋 캐시까지 흔들린다).

⚠️ 실행 위치
  워처가 도는 **그 PC에서** 열어야 한다. fds_results.db 는 로컬 파일이라
  Streamlit Cloud 등 다른 서버에서는 워처 상태가 보이지 않는다.

실행
  streamlit run ops_dashboard.py
"""

from __future__ import annotations

import os
import sys
import time
import logging
import unicodedata
from pathlib import Path

import streamlit as st
import pandas as pd

_PROJ = Path(__file__).resolve().parent
for _p in (str(_PROJ), str(_PROJ / "pipeline")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ── Streamlit Cloud 대응 ──────────────────────────────────
#   Cloud 에는 .env 가 없다(.gitignore 로 막았고, 올려서도 안 된다).
#   대신 st.secrets 를 os.environ 으로 흘려보내 아래 모든 os.getenv 가
#   로컬과 똑같이 동작하게 만든다. 로컬에서는 secrets.toml 이 없으므로
#   조용히 아무 일도 하지 않는다 — .env 가 이미 채워 놨기 때문이다.
try:
    from secrets_bridge import load_secrets_into_env
    _SECRETS_APPLIED = load_secrets_into_env()
except Exception:                                      # pragma: no cover
    _SECRETS_APPLIED = []

log = logging.getLogger("ops_dashboard")
if not log.handlers:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")

st.set_page_config(page_title="FDS Ops Console", page_icon="🛡",
                   layout="wide", initial_sidebar_state="expanded")

# ── Streamlit 최소 버전 ────────────────────────────────────
#   st.tabs(key=…, default=…) 는 1.58+ 에서만 받는다. 낮은 버전에서는 탭을
#   만드는 순간 TypeError 로 죽는데, 화면에는 스택 트레이스만 뜨고 원인을
#   알 수 없다. 여기서 미리 잡아 무엇을 하면 되는지 알려 준다.
_ST_MIN = (1, 58)
try:
    _ST_VER = tuple(int(x) for x in st.__version__.split(".")[:2])
except Exception:                                      # pragma: no cover
    _ST_VER = (0, 0)
if _ST_VER < _ST_MIN:
    # ⚠ 이 메시지만 i18n 대상이 아니다 — t() 는 ops_ui 를 import 하고 세션을
    #   읽은 뒤에야 만들어지는데(아래), 그 import 자체가 이 버전에서 실패할 수
    #   있다. 부팅 단계의 하드 스톱이라 한국어 고정으로 둔다.
    st.error(
        f"### Streamlit 버전이 낮습니다\n\n"
        f"현재 **{st.__version__}** · 필요 **{_ST_MIN[0]}.{_ST_MIN[1]} 이상**\n\n"
        f"이 콘솔은 `st.tabs(key=…, default=…)`(1.58+)로 탭 상태를 관리합니다 — "
        f"경보 카드를 눌렀을 때 해당 탭으로 이동하는 기능이 여기에 달려 있습니다.\n\n"
        "```\npip install -U \"streamlit>=1.58\"\n```")
    st.stop()

# ══════════════════════════════════════════════════════════
# 🔌 포트 배지 — dashboard.py 와 동일한 목적. 두 앱을 동시에 켰을 때
#   화면 우상단에 "앱 이름 · 포트"가 보이므로, 두 탭에서 같은 배지가
#   보이면 포트 충돌(둘 중 하나가 실제로는 안 떠 있음)이라는 뜻이다.
# ══════════════════════════════════════════════════════════
def _port_badge(app_name: str):
    try:
        _port = st.get_option("server.port")
    except Exception:
        _port = None
    _port_txt = str(_port) if _port else "?"
    st.markdown(
        f"""<div style="position:fixed;top:6px;right:12px;z-index:99999;
        background:rgba(0,0,0,0.55);color:#e8f0fe;font-family:monospace;
        font-size:11px;padding:3px 10px;border-radius:6px;letter-spacing:.02em;
        pointer-events:none;">🔌 {app_name} · :{_port_txt}</div>""",
        unsafe_allow_html=True,
    )

_port_badge("ops_dashboard.py")

# ── 내부 모듈 ────────────────────────────────────────────
try:
    from pipeline import ops_ui as ui
    from pipeline import review_store as rs
    from pipeline import ops_queries as oq
    from pipeline import demo_mode as _demo
    from pipeline import watcher_panel as wp
    from pipeline import watcher_config as wcfg
except ImportError:                                    # pragma: no cover
    import ops_ui as ui
    import review_store as rs
    import ops_queries as oq
    import demo_mode as _demo
    try:
        import watcher_panel as wp
    except ImportError:
        wp = None
    try:
        import watcher_config as wcfg
    except ImportError:
        wcfg = None

try:
    from pipeline import analysis_store as astore
except ImportError:
    try:
        import analysis_store as astore
    except ImportError:
        astore = None

try:
    from pipeline import ops_alert as oa
except ImportError:
    try:
        import ops_alert as oa
    except ImportError:
        oa = None

try:
    from pipeline import ops_recheck as rc
except ImportError:
    try:
        import ops_recheck as rc
    except ImportError:
        rc = None                                      # 모델 모듈이 없으면 재검증만 비활성

# ── 🆕 dashboard.py 와 공유하는 컴포넌트 ──────────────────
#   detect_ui   : 위험 게이지 · 확률 막대 · 사기유형 카드 · 규칙 체크리스트
#   asset_registry: 모델/데이터셋 탐색 (사이드바 셀렉터의 목록 공급원)
#   ops_sidebar : 사이드바 전체 (임계값·모델·데이터셋·AI·관제 설정)
#   셋 다 없으면 관제 기본 기능은 그대로 돌고, 해당 UI만 빠진다.
try:
    from pipeline import detect_ui as dui
except ImportError:                                    # pragma: no cover
    try:
        import detect_ui as dui
    except ImportError:
        dui = None

try:
    from pipeline import asset_registry as ar
except ImportError:                                    # pragma: no cover
    try:
        import asset_registry as ar
    except ImportError:
        ar = None

# detect_workbench : '탐지 입력' 6종 + 액션바 (dashboard.py 세션5 와 공용 예정)
#   ⚠ 없으면 AI 탭의 '🎯 탐지 입력'만 빠지고 나머지 관제 기능은 그대로 돈다.
try:
    from pipeline import detect_workbench as dwb
except ImportError:                                    # pragma: no cover
    try:
        import detect_workbench as dwb
    except ImportError:
        dwb = None

try:
    from pipeline import ops_sidebar as osb
except ImportError:                                    # pragma: no cover
    try:
        import ops_sidebar as osb
    except ImportError:
        osb = None

# ops_dispatch : 자동 발송 · 감사 로그 · 연결 테스트 · LLM 단계 재실행
#   (ops_alert 는 '들어오는' 경보, 이쪽은 '나가는' 통보 — 이름이 비슷하니 주의)
try:
    from pipeline import ops_dispatch as odp
except ImportError:                                    # pragma: no cover
    try:
        import ops_dispatch as odp
    except ImportError:
        odp = None

# status_push : 워처 상태를 DB 밖으로 (클라우드에서 이 화면을 띄웠을 때의 폴백)
try:
    from pipeline import status_push as _sp
except ImportError:                                    # pragma: no cover
    try:
        import status_push as _sp
    except ImportError:
        _sp = None

# audit_store : 발송 감사 로그 영속 저장 (ops_dispatch 가 실제로 쓴다)
try:
    from pipeline import audit_store as aust
except ImportError:                                    # pragma: no cover
    try:
        import audit_store as aust
    except ImportError:
        aust = None

# ops_shift : SLA 경과시간 · 교대 인수인계
try:
    from pipeline import ops_shift as osh
except ImportError:                                    # pragma: no cover
    try:
        import ops_shift as osh
    except ImportError:
        osh = None

# ops_guide : 첫 실행 온보딩 · 사용 안내
try:
    from pipeline import ops_guide as ogd
except ImportError:                                    # pragma: no cover
    try:
        import ops_guide as ogd
    except ImportError:
        ogd = None

# ops_agent : 관제 전용 챗봇 액션 (탭 이동·범위·임계값·일괄선택 …)
try:
    from pipeline import ops_agent as oag
except ImportError:                                    # pragma: no cover
    try:
        import ops_agent as oag
    except ImportError:
        oag = None

APP_VERSION = "v39"

# ══════════════════════════════════════════════════════════
# 상태 초기화
# ══════════════════════════════════════════════════════════
_DEFAULTS = {
    "lang": "ko",
    "theme": ui.DEFAULT_THEME,
    "db_path": os.getenv("FDS_DB_PATH", "fds_results.db"),
    "log_path": os.getenv("FDS_LOG_PATH", "watcher.log"),
    "model_dir": os.getenv("FDS_MODEL_DIR", "models/"),
    # 📤 inbox 전송이 쓰는 폴더. 예전에는 이 키를 **아무도 설정하지 않아서**
    #   `st.session_state.get('watch_inbox', 'inbox')` 가 항상 폴백을 탔다 —
    #   워처 감시 폴더를 바꿔도 전송은 늘 `inbox/` 로 갔다는 뜻이다.
    #   다른 경로 설정(db_path/log_path/model_dir)과 같은 규칙으로 배선한다.
    "watch_inbox": os.getenv("FDS_INBOX", "inbox"),
    "poll_interval": 5.0,
    "auto_refresh": True,
    "reviewer": rs.default_reviewer(),
    "pii_level": "standard",
    "window_h": 168,
    "_refresh_sec": 5,
    "fp_cost": 30_000,
    "fn_cost": 3_000_000,
}
for _k, _v in _DEFAULTS.items():
    st.session_state.setdefault(_k, _v)

if oa:
    # shared=True — alarm_prefs.json 을 먼저 얹고 빈 칸만 기본값으로 메운다.
    #   dashboard.py 세션5 와 같은 경보 정책을 쓰기 위한 단일 출처다.
    oa.init_state(st.session_state)


def _save_alarm_prefs():
    """경보 설정 위젯의 on_change — 바꾼 즉시 파일에 남겨 상대 앱도 따라오게 한다."""
    if oa:
        oa.save_prefs(st.session_state)

# ── 경보 카드 클릭 → 해당 거래로 이동 ──────────────────────
#   Streamlit 은 JS 이벤트를 직접 받지 못한다. 경보 카드가 쿼리 파라미터를
#   바꾸면 재실행이 걸리고, 여기서 그것을 읽어 트리아지로 보낸다.
_goto = st.query_params.get("goto")
_gototab = st.query_params.get("gototab")
if _goto:
    st.session_state["jump_txn"] = _goto
    # 데스크톱 알림은 '탐지 로그'로 보낸다(gototab=log) — 알림을 누른 사람이
    #   보고 싶은 건 "그 건이 무엇이었나"(당시 데이터·분석)다.
    #   경보 카드의 '확인하기'는 판정이 목적이라 트리아지로 간다.
    st.session_state["_force_tab"] = _gototab if _gototab in ("log", "triage") else "triage"
    st.query_params.clear()

t = ui.make_ops_t(st.session_state)
LANG = st.session_state["lang"]
T = ui.get_theme(st.session_state["theme"])
DB = st.session_state["db_path"]

st.markdown(ui.build_css(T), unsafe_allow_html=True)
if dui:
    # ops_ui CSS **뒤에** 주입해야 한다 — 같은 클래스가 겹치면 나중 정의가 이긴다
    st.markdown(dui.build_css(T), unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════
# 🤖 AI 어시스턴트 — 사이드바 패널 (AI 탭과 **같은 대화**를 공유)
#
#   ⚠ 이 함수는 사이드바가 그려지는 시점(바로 아래)에 호출되므로, LLM 빌더나
#     컨텍스트 수집기(_build_llm_analyzer / _ops_chat_context)보다 **위**에 있다.
#     그것들은 아직 정의되기 전이다 — 그래서 여기서는 질문을 **바로 처리하지 않고**
#     세션에 적재만 하고, 헬퍼가 모두 갖춰진 뒤(_drain_pending_chat)에서 처리한다.
#     이 순서를 어기면 "질문을 보낼 때만" NameError 가 나는 고약한 버그가 된다.
# ══════════════════════════════════════════════════════════
CHAT_KEY = "ops_chat_history"
CHAT_PENDING = "_ops_chat_pending"


def _sidebar_chat():
    """사이드바용 축소 챗 — 어느 탭에 있든 손이 닿는 곳에 둔다.
    폭이 좁으므로 최근 왕복만 보여주고, 전체 대화·음성 입력은 AI 탭에 맡긴다."""
    hist = st.session_state.get(CHAT_KEY, [])
    if hist:
        for m in hist[-4:]:
            _is_user = m.get("role") == "user"
            st.markdown(
                f'<div style="font-size:11px;line-height:1.5;margin:3px 0;padding:6px 9px;'
                f'border-radius:8px;background:{T["bg_card"]};'
                f'border-left:2px solid {T["accent"] if _is_user else T["green"]}">'
                f'<b>{"나" if _is_user else "AI"}</b> · {m.get("content", "")[:400]}</div>',
                unsafe_allow_html=True)
    else:
        st.caption("예) 지금 미처리 몇 건이야? / 오탐률 어때? / 워처 살아있어?")

    q = st.chat_input("무엇이든 물어보세요", key="ops_chat_sb")
    if q:
        st.session_state[CHAT_PENDING] = q      # 처리는 아래에서 (위 주석 참조)
        st.rerun()

    c1, c2 = st.columns(2)
    if c1.button("🗑 비우기", key="ops_chat_sb_clear", width="stretch"):
        st.session_state[CHAT_KEY] = []
        st.rerun()
    if c2.button("↗ 전체보기", key="ops_chat_sb_open", width="stretch",
                 help="AI 탭에서 전체 대화·음성 입력을 씁니다"):
        st.session_state["_force_tab"] = "ai"
        st.rerun()


# ── RAG 인덱스 캐시 ───────────────────────────────────────
#   ⚠ 이 자리에 있어야 한다. 아래 _sidebar_editors 가 `.clear` 를 넘기는데,
#     사이드바는 스크립트 앞쪽에서 그려지므로 그때 이 이름이 이미 있어야 한다.
#     (예전에 챗봇이 겪은 것과 같은 '정의 순서' 함정이다 — 주석 위쪽 참조)
@st.cache_resource(show_spinner="RAG 인덱스 준비 중…")
def _get_rag_cached(top_k):
    from pipeline.rag_searcher import RAGSearcher
    return RAGSearcher(top_k=top_k)


def _sidebar_editors():
    """🖊 프롬프트 · 📚 RAG 편집기 — 사이드바 ③(대개 한 번만 정하는 것) 구역.

    왜 옮겼나: 여기는 '설정'이지 '작업'이 아니다. 그런데 관제 콘솔의 첫 화면인
    AI 분석 탭 맨 위를 차지하고 있어서, 탭을 열면 할 일(탐지·분석)보다 편집기가
    먼저 보였다. 사이드바에서 임계값·모델·LLM을 고치는 것과 같은 층이다.

    ⚠ 두 렌더러는 **자기 안에서 st.expander 를 연다.** 그래서 '⚙ 고급 설정'
      expander 안에 넣을 수 없다(중첩 금지). 형제로 나란히 둔다.
    """
    if dwb is None:                                    # pragma: no cover
        st.caption("detect_workbench 모듈 미탑재 — 편집기를 쓸 수 없습니다")
        return
    dwb.render_prompt_editor(t=t, key_ns="ai", height=150)
    dwb.render_rag_editor(t=t, key_ns="ai", height=150,
                          on_change=_get_rag_cached.clear)


# ══════════════════════════════════════════════════════════
# 사이드바 — 임계값 · 모델 · 데이터셋 · AI · 관제 설정
#   ⚠ DB 존재 확인(st.stop)보다 **먼저** 그린다. DB가 없을 때 사이드바까지
#     사라지면 db_path 를 고칠 방법이 없어 앱이 벽돌이 된다.
# ══════════════════════════════════════════════════════════
if osb:
    CFG = osb.render(t, T, LANG, versions={
        "ops_dashboard": APP_VERSION,
        "ops_ui": f"{ui.OPS_UI_VERSION}  i18n_data={'O' if ui.HAS_I18N_DATA else 'X'}",
        "ops_sidebar": osb.OPS_SIDEBAR_VERSION,
        "detect_ui": dui.DETECT_UI_VERSION if dui else "-",
        "detect_workbench": dwb.DETECT_WORKBENCH_VERSION if dwb else "-",
        "asset_registry": ar.ASSET_REGISTRY_VERSION if ar else "-",
        "review_store": rs.REVIEW_STORE_VERSION,
        "ops_queries": oq.OPS_QUERIES_VERSION,
        "ops_recheck": rc.RECHECK_VERSION if rc else "-",
        "watcher_panel": wp.PANEL_VERSION if wp else "-",
        "streamlit": st.__version__,
    }, chat_panel=_sidebar_chat, editors=_sidebar_editors)
else:                                                  # pragma: no cover
    CFG = {"threshold": 0.5, "dual": False, "th_review": 0.5, "th_confirm": 0.5,
           "model": {"models": {}, "name": "", "path": "", "exists": False},
           "dataset": {"found": {}, "name": None}, "rag_k": 3}

# 사이드바가 소유하는 값을 본문이 짧은 이름으로 쓴다
THRESHOLD   = CFG["threshold"]
# ⚠️ CFG 의 th_review/th_confirm 은 **발송(dispatch) 등급** 정책이다 —
#   ops_dispatch.notify_tier 가 session_state 에서 직접 읽어 쓴다.
#   경보 등급은 워처 설정이 단일 출처이므로 _tier_th() 를 쓸 것. 이름이 같아
#   섞어 쓰기 쉬워서, 여기서 짧은 별칭을 만들지 않는다(예전에 그래서 어긋났다).
SEL_MODEL   = CFG["model"]["name"]
SEL_MODEL_P = CFG["model"]["path"]
SEL_DS      = CFG["dataset"]["name"]
DS_FOUND    = CFG["dataset"]["found"]


# ══════════════════════════════════════════════════════════
# 헤더 — 밀린 일을 모든 탭 위에 띄운다
#
#   첫 화면이 '🧠 AI 분석'이라, 미판정이 쌓여 있어도 트리아지 탭을 손으로 누르기
#   전에는 알 수 없었다. 관제 도구가 "일이 밀렸다"를 숨기면 안 된다.
#   그래서 헤더에 상시 배지를 단다 — 어느 탭에서 일하든 눈에 들어온다.
# ══════════════════════════════════════════════════════════
_HDR_CAP = 500          # 배지용 상한. 넘으면 '500+' 로 표기한다


@st.cache_data(ttl=15, show_spinner=False)
def _header_stats(db: str, sla_min: int, db_mtime: float) -> dict:
    """헤더 배지용 집계. 매 rerun 마다 원장을 훑으면 워처 폴링과 경합하므로
    15초 캐시 + `db_mtime`(DB 변경 시각)으로 무효화한다 — 새 탐지가 들어오면
    파일이 바뀌므로 캐시 키가 달라져 즉시 갱신된다.

    ⚠ 인자 이름 앞에 `_` 를 붙이면 안 된다. st.cache_data 는 밑줄로 시작하는
      인자를 **해시에서 제외**하므로, `_mtime` 이라고 쓰는 순간 DB 가 바뀌어도
      15초 동안 옛 숫자를 보여주게 된다(무효화가 통째로 죽는다)."""
    q = oq.alert_queue(db, limit=_HDR_CAP, min_score=0.0, only_unreviewed=True)
    if osh:
        osh.annotate(q, sla_min, LANG)
        s = osh.sla_stats(q, sla_min)
        return {"pending": len(q), "over": s["over"], "oldest": s["oldest_min"]}
    return {"pending": len(q), "over": 0, "oldest": None}


def _header_badges() -> list:
    """[(라벨, 값, kind)] — DB 가 없으면 빈 목록(헤더는 그래도 뜬다)."""
    try:
        if not Path(DB).exists():
            return []
        _sla = int(st.session_state.get("sla_min", 30))
        s = _header_stats(DB, _sla, Path(DB).stat().st_mtime)
    except Exception as e:                             # pragma: no cover
        # 배지 때문에 앱이 죽으면 안 된다 — 없는 채로 그린다
        log.debug(f"헤더 배지 생략: {e}")
        return []

    _n = f"{_HDR_CAP}+" if s["pending"] >= _HDR_CAP else f"{s['pending']}"
    _who = (st.session_state.get("reviewer") or "").strip()
    return [
        (t("hdr.pending"), _n, "bad" if s["pending"] else "ok"),
        (t("hdr.sla_over", n=_sla), f"{s['over']}", "bad" if s["over"] else "ok"),
        (t("hdr.oldest"), osh.elapsed_label(s["oldest"], LANG) if osh else "-",
         "warn" if s["oldest"] and s["oldest"] > _sla else ""),
        (t("hdr.reviewer"), _who or t("hdr.no_name"), "" if _who else "warn"),
    ]


st.markdown(ui.hero(t, badges=_header_badges()), unsafe_allow_html=True)

# ── 🎬 시연 모드 안내 ──────────────────────────────────────
#   FDS_DEMO_MODE=1 이면 알림 시각이 현재로 재기준된다(pipeline/demo_mode.py).
#   재기준된 시각을 실제 운영 시각으로 오인하면 안 되므로, **끄기 전까지 항상**
#   화면 맨 위에 보이게 둔다. 배지 렌더가 실패해도 앱은 계속 돌아야 한다.
try:
    if _demo.enabled():
        st.info(_demo.badge_text(LANG))
except Exception as e:                                 # pragma: no cover
    log.debug(f"시연 모드 배지 생략: {e}")

# ── 🎓 첫 실행 안내 ────────────────────────────────────────
#   DB 확인(st.stop)보다 **먼저** 띄운다. 처음 여는 사람은 DB 경로부터
#   틀리기 쉬운데, 그때 안내가 안 나오면 빈 에러 화면만 보게 된다.
if ogd:
    ogd.maybe_show(T, reviewer=st.session_state.get("reviewer", ""),
                   force=bool(st.session_state.pop("_ops_guide_open", False)),
                   lang=LANG)

# ── 🔔 경보 배너 (폴백) ────────────────────────────────────
#   기본 경보는 우상단 **플로팅 카드**(레이더 애니메이션)다. 이 배너는
#   엄격한 CSP 등으로 카드가 안 보이는 환경을 위한 대안이라 기본 OFF —
#   둘 다 켜면 같은 경보가 두 번 보인다.
if oa and st.session_state.get("alarm_banner"):
    def _alert_open(_tid):
        st.session_state["jump_txn"] = _tid
        st.session_state["_force_tab"] = "triage"
    oa.render_banner(st, st.session_state, T, ui.fraud_label, LANG,
                     on_open=_alert_open)

# DB 존재 확인 — 없으면 나머지를 그리지 않는다 (모든 탭이 빈 화면이 되므로)
if not Path(DB).exists():
    st.error(f"{t('live.nodb')}\n\n`{DB}`")
    st.caption(t("live.nodb_hint"))
    st.stop()


# ══════════════════════════════════════════════════════════
# 공통 헬퍼
# ══════════════════════════════════════════════════════════

def _kpi_row(items):
    cols = st.columns(len(items))
    for c, (label, value, delta) in zip(cols, items):
        c.metric(label, value, delta)


def _sync_widget(key: str, source):
    """위젯의 세션 값을 **원본이 바뀌었을 때만** 원본으로 되돌린다.
    반드시 그 위젯을 만들기 **전에** 호출할 것 (생성 후엔 Streamlit 이 막는다).

    왜 필요한가 — Streamlit 은 key 가 이미 세션에 있으면 `value=` 를 **무시한다.**
    그래서 `st.text_area(value=새본문, key="…")` 는 두 번째 렌더부터 새 본문을
    보여주지 않는다. 이 앱에서 실제로 이렇게 깨져 있었다:

      · 🔁 재생성 → 이메일 미리보기는 옛 본문 그대로인데 **전송은 새 본문**이 나갔다
        (= 보이는 것과 보내는 것이 달랐다 — 가장 위험한 형태)
      · 배치 재실행 → 이전 배치의 이메일이 그대로 남았다
      · 프롬프트 '기본값 복원' → 세션 값은 지워지는데 편집창은 그대로라
        복원이 안 된 것처럼 보였다
      · 임계값 튜닝 → 비용을 바꿔 최소비용 지점이 이동해도 슬라이더는 첫 값에 고정

    원본 해시를 함께 들고 있다가 원본이 바뀐 순간에만 덮어쓴다. 그래서
    **사용자가 손으로 고친 내용은 보존**되고(원본은 그대로니까), 재생성처럼
    원본이 바뀐 경우에만 새 값으로 따라간다.

    ※ 버튼 클릭 → `st.rerun()` 이 위젯 생성 **전에** 일어나는 경우
      (예: 트리아지 '모두 선택')는 Streamlit 이 위젯 상태를 정리해 주므로
      이 헬퍼가 필요 없다. 문제는 위젯이 이미 그려진 뒤에 원본이 바뀌는 경우다.
    """
    import hashlib
    tag = f"_src__{key}"
    digest = hashlib.md5(str(source).encode("utf-8", "replace")).hexdigest()
    if key not in st.session_state or st.session_state.get(tag) != digest:
        st.session_state[key] = source
        st.session_state[tag] = digest
    return st.session_state[key]


def _pill(text, kind="ok"):
    return f'<span class="pill {kind}">{text}</span>'


def _verdict_label(v) -> str:
    """판정 코드 → 화면 문구.

    ⚠ rs.VERDICT_LABEL_KO 를 화면에 직접 쓰지 말 것 — 이름 그대로 **한국어 고정**
      이라 언어를 바꿔도 그 칸만 한국어로 남는다. 트리아지 라디오가 쓰는 것과
      같은 키(tri.tp/fp/fn/unclear)로 뽑아 화면 전체가 한 벌만 쓰게 한다.
    """
    return t(f"tri.{v}") if v in rs.VERDICTS else (v or "-")


def _score_class(score, th_review=0.45, th_confirm=0.80):
    s = float(score or 0)
    return "hi" if s >= th_confirm else ("mid" if s >= th_review else "")


def _cfg():
    return wcfg.load() if wcfg else {}


# 워처 설정을 못 읽었을 때만 쓰는 폴백 (숫자는 ops_alert 에 한 벌만 둔다)
_FB_THR = oa.DEFAULT_TH_REVIEW if oa else 0.45
_FB_THC = oa.DEFAULT_TH_CONFIRM if oa else 0.80


def _tier_th() -> tuple[float, float]:
    """**경보 등급 임계값의 단일 출처** = 워처 설정(watcher_config.json).

    왜 사이드바가 아니라 워처 설정인가
      등급(확정/검토)은 '워처가 이 건을 어떻게 취급했는가'를 뜻한다. 워처는
      watcher_config 의 th_review/th_confirm 으로 통보 등급을 정하므로, 관제 화면이
      다른 숫자를 쓰면 "워처는 확정으로 쐈는데 화면엔 검토"가 생긴다.

    예전에 어긋나 있던 곳
      · noise_forecast  → 0.45/0.80 하드코딩
      · 등급 라벨 문구  → "확정만 (0.80↑)" 문자열 고정
      · 수동 탐지 tier  → 사이드바 값(기본 0.5/0.5)
      실제 설정은 0.005/0.9 라, 같은 화면에 세 가지 기준이 동시에 떠 있었다.

    사이드바의 이중 임계값은 **발송(dispatch) 등급** — 이 콘솔에서 내보내는 통보의
    정책이라 별개다(ops_dispatch.notify_tier). 이름이 같아 헷갈리므로 분리해 둔다.
    """
    c = _cfg()
    try:
        thr = float(c.get("th_review", _FB_THR))
    except (TypeError, ValueError):
        thr = _FB_THR
    try:
        thc = float(c.get("th_confirm", _FB_THC))
    except (TypeError, ValueError):
        thc = _FB_THC
    return thr, max(thr, thc)      # 2차 < 1차 로 잘못 저장된 설정 방어


def _tier_of(score) -> str:
    """위험도 → 경보 등급. 화면 전체가 이 함수 하나만 쓴다."""
    thr, thc = _tier_th()
    s = float(score or 0)
    return "confirm" if s >= thc else ("review" if s >= thr else "none")


# ══════════════════════════════════════════════════════════
# 🧠 AI 분석 · 알림 — dashboard.py 세션5(4034~5433행) 이식.
#   원본은 selected_model/dual_threshold(검증셋 기준) 상태에 강하게 종속돼 있어
#   그대로 복붙하면 동작하지 않는다. 여기서는 데이터 소스를 검증셋 → 라이브
#   알림(oq.alert_queue + detections.raw_json)으로 교체해 완전히 독립시켰다.
#   설정값도 dashboard.py의 llm_p5/ov_* 키를 공유하지 않고 ai_* 로 분리해
#   두 대시보드를 동시에 켜도 서로의 세션 상태를 건드리지 않는다.
# ══════════════════════════════════════════════════════════

def _build_llm_analyzer():
    from pipeline.llm_analyzer import LLMAnalyzer
    provider = st.session_state.get('ai_llm_provider', 'local')
    key_map = {
        'anthropic': st.session_state.get('ai_anthropic_key', ''),
        'openai':    st.session_state.get('ai_openai_key', ''),
        'deepseek':  st.session_state.get('ai_deepseek_key', ''),
        'moonshot':  st.session_state.get('ai_moonshot_key', ''),
        'custom':    st.session_state.get('ai_custom_key', ''),
    }
    api_key = key_map.get(provider, '') or None
    # 🛡 dashboard.py와 동일한 안전장치: 로컬 모델 실패 시 미마스킹 원문이
    #   클라우드로 폴백되는 경로를 '로컬+마스킹생략' 조합에서 차단한다.
    no_cloud_fb = (provider == 'local' and st.session_state.get('ai_pii_skip_local', True))
    # 슬롯 목록은 detect_workbench 가 단일 출처 — 편집기와 같은 표를 본다.
    #   예전엔 두 앱의 빌더가 각자 4키 dict 를 들고 있어, 슬롯이 늘면 한쪽을
    #   빠뜨리기 쉬웠다("편집기에서 저장했는데 그 프롬프트가 안 먹는다").
    _overrides = dwb.prompt_overrides() if dwb else {}
    return LLMAnalyzer(
        max_tokens=512,
        llama_cpp_url=st.session_state.get('ai_llama_url', '') or None,
        model=st.session_state.get('ai_model_name', '') or None,
        provider=provider,
        api_key=api_key,
        custom_url=st.session_state.get('ai_custom_url', '') or None,
        custom_model=st.session_state.get('ai_custom_model', '') or None,
        cloud_fallback=not no_cloud_fb,
        prompt_overrides=_overrides,
    )


def _build_notifier():
    from pipeline.notifier import Notifier
    return Notifier(
        smtp_user=st.session_state.get('ai_smtp_user', '') or None,
        smtp_pass=st.session_state.get('ai_smtp_pass', '') or None,
        slack_webhook_url=st.session_state.get('ai_slack_webhook', '') or None,
    )


def _ai_effective_email():
    return ((st.session_state.get('ai_notify_email') or '').strip()
            or os.getenv('FDS_NOTIFY_EMAIL', '').strip()
            or (st.session_state.get('ai_smtp_user') or '').strip()
            or os.getenv('SMTP_USER', '').strip())


# ── 📨 리치 알림 — dashboard.py 와 **같은 컴포저**를 쓴다 ────
#   예전엔 여기가 ops_dispatch.compose_*_default(머리말 + LLM 텍스트)뿐이라,
#   같은 탐지 건이라도 관제 화면에서 보내면 Slack 위험도 게이지도, 이메일 KPI 카드도,
#   HTML 리포트 첨부도 없는 '반쪽 통보'가 나갔다. 컴포저를 공유해 그 차이를 없앤다.
try:
    from pipeline import notify_compose as nc
except ImportError:                                    # pragma: no cover
    nc = None


def _rich_on() -> bool:
    return bool(st.session_state.get('ai_rich_notify', True)) and nc is not None


def _build_masker_forced():
    """첨부 리포트 전용 — '로컬이면 마스킹 생략' 설정을 무시하고 반드시 마스킹한다.
    첨부는 메일함에 그대로 남으므로 로컬 분석이었는지와 무관하게 원문이 새면 안 된다."""
    try:
        from pipeline.pii_masker import PIIMasker
        return PIIMasker(level=st.session_state.get('pii_level', 'standard'))
    except Exception:
        return _DummyMasker()


def _report_dl(det: dict, slot: str) -> None:
    """📄 보고서(.md) 저장 버튼. 서식은 dashboard.py 세션5 와 같은 함수를 쓴다.

    왜 필요한가 — Slack/Email 은 '지금 알린다'이고 이 파일은 '나중에 남긴다'다.
    관제 화면에는 후자가 아예 없어서, 분석 결과를 보관하려면 화면을 복사하거나
    자기 앞으로 메일을 보내야 했다. 발송(되돌릴 수 없음)과 저장(안전함)은
    다른 행동인데 저장이 없다는 이유로 발송을 누르게 되는 구조였다.
    """
    if not nc or not (det.get("llm") or {}).get("analysis"):
        return
    _ft = str(det.get("fraud_type", "x"))
    st.download_button(
        t("ai.report_md"),
        nc.report_md_single(det, t=t, lang=LANG,
                            fraud_name=ui.fraud_label(_ft, LANG)).encode("utf-8"),
        file_name=f"fds_report_{_ft}_{det.get('txn_id') or 'manual'}_"
                  f"{time.strftime('%Y%m%d_%H%M%S')}.md",
        mime="text/markdown", key=f"report_md_{slot}", width="stretch",
        help=t("ai.report_md_help"))


def _tier_head_of(det: dict, tier: str) -> str:
    """등급 머리말 — 리치 스위치와 **무관하게** 항상 붙는다. 리치는 시각화의
    문제지, '지금 뭘 해야 하나'를 알리는 문장은 평문 발송에도 있어야 한다."""
    return (odp.tier_head(st.session_state, tier, det.get('risk_score', 0))
            if odp else "")


def _rich_slack(det: dict, tier: str = "single", body=None) -> str:
    """Slack 본문 = 등급 머리말 + (리치면) 시각화 헤더 + 화면에 보이던 LLM 텍스트."""
    _txt = body if body is not None else ((det.get('llm') or {}).get('slack', '') or "")
    _head = _tier_head_of(det, tier)
    if nc is None:                                     # pragma: no cover
        return (_head + "\n\n" + _txt) if _head else _txt
    return nc.slack_single(det, _tier_th()[0], t=t, lang=LANG, body=_txt,
                           head=_head, rich=_rich_on())


def _rich_email(det: dict, tier: str = "single", body=None):
    """→ (평문, html|None, 첨부|None). body 에는 **화면에서 편집한 본문**이 들어온다
    — 미리보기와 실제 발송물이 어긋나지 않도록 여기서 그대로 감싼다."""
    _txt = body if body is not None else ((det.get('llm') or {}).get('email', '') or "")
    _head = _tier_head_of(det, tier)
    if nc is None:                                     # pragma: no cover
        return ((_head + "\n\n" + _txt) if _head else _txt), None, None
    return nc.email_single(det, _tier_th()[0], t=t, lang=LANG, body=_txt,
                           head=_head, rich=_rich_on(),
                           masker=_build_masker_forced)


def _send(channel: str, body: str, *, fraud_type=None, risk_score=0,
          txn_id: str = "", subject: str | None = None, tier: str | None = None,
          html: str | None = None, attachments: list | None = None):
    """수동 발송 + 결과 표시. **화면의 모든 발송 버튼이 이 함수 하나만 부른다.**

    감사 로그는 ops_dispatch.send_manual 안에서 남는다 — 여기서 audit 를 호출하지
    않는 것이 핵심이다. 예전에는 버튼마다 send → audit_append 를 손으로 짝지었고,
    6개 경로 중 4개(단건 분석 Slack/Email · 배치 Slack/Email)에서 audit 가 빠져
    있었다. 그런데 진단 탭은 "자동·수동을 가리지 않고 모든 시도를 기록합니다"
    라고 안내하고 있었다 — 감사 로그가 거짓말을 하고 있었던 셈이다.
    """
    if channel == "slack" and not st.session_state.get('ai_slack_webhook', ''):
        st.error(t("ai.no_webhook"))
        return False
    to = ""
    if channel == "email":
        to = _ai_effective_email()
        if not to:
            st.error(t("ai.no_smtp"))
            return False
        if subject is None:
            subject = (odp.tier_subject(tier or 'single', fraud_type, risk_score)
                       if odp else
                       f"[FDS] {str(fraud_type).upper()}형 이상거래 탐지")
    if odp:
        ok, err = odp.send_manual(
            st.session_state, channel=channel, body=body or "",
            notifier_factory=_build_notifier, fraud_type=fraud_type,
            risk_score=risk_score, to=to, subject=subject or "",
            mask_level=st.session_state.get('pii_level', '-'), txn_id=txn_id,
            db_path=DB, html=html, attachments=attachments)
    else:                                              # pragma: no cover
        nn = _build_notifier()
        ok = bool(nn.send_slack(body) if channel == "slack"
                  else nn.send_email(to, subject or "", body,
                                     html=html, attachments=attachments))
        err = getattr(nn, "last_error", "")
    (st.success if ok else st.error)(
        t("ai.sent_ok") if ok else t("ai.sent_fail", e=err))
    return ok


# ══════════════════════════════════════════════════════════
# ✋ 발송 전 확인 — 외부로 나간 것은 회수할 수 없다
#
#   감사 로그(_send → ops_dispatch.send_manual)는 **사후 추적**이지 예방이 아니다.
#   지금까지 6개 발송 버튼이 전부 클릭 한 번에 실제 전송이었고, 그중 이메일 본문은
#   바로 옆 편집창에서 방금 고칠 수 있는 값이라 오발송 여지가 컸다.
#   버튼은 '예약'만 하고, 수신처·마스킹·본문을 보여준 뒤 한 번 더 받는다.
#
#   slot = 화면상의 발송 버튼 하나. 확인 카드가 누른 버튼 **바로 아래** 뜨도록
#   호출부에서 버튼 직후에 _send_confirm(slot) 을 부른다.
#   (한 번에 하나만 예약된다 — 카드가 여기저기 동시에 뜨면 무엇을 보내는지 흐려진다)
# ══════════════════════════════════════════════════════════
_SEND_PENDING = "_send_pending"


def _send_ask(slot: str, channel: str, body: str, **kw) -> None:
    """실제 발송 대신 '예약'만 한다. 실제 전송은 _send_confirm 의 버튼에서.

    kw 로 det(단건) 또는 bres(배치) 를 함께 넘기면 확인 카드가 리치 본문
    (Slack 시각화 헤더 / Email KPI + HTML 리포트 첨부)까지 만들어 보여준다.
    """
    st.session_state[_SEND_PENDING] = {"slot": slot, "channel": channel,
                                       "body": body or "", **kw}
    st.rerun()


def _compose_pending(p: dict):
    """예약된 발송 1건 → (평문, html|None, 첨부|None).

    det/bres 가 없거나 리치가 꺼져 있으면 예약된 본문 그대로 — 즉 예전 동작이다.
    """
    ch, body = p["channel"], (p.get("body") or "")
    tier = p.get("tier") or "single"
    det, bres = p.get("det"), p.get("bres")
    if det is None and bres is None:
        return body, None, None
    try:
        if bres is not None:
            _r = _rich_on()
            return ((nc.slack_batch(bres, t=t, lang=LANG, body=body, rich=_r), None, None)
                    if ch == "slack" else
                    nc.email_batch(bres, t=t, lang=LANG, body=body, rich=_r))
        return ((_rich_slack(det, tier, body=body), None, None) if ch == "slack"
                else _rich_email(det, tier, body=body))
    except Exception as e:                             # pragma: no cover
        # 시각화가 깨졌다고 통보 자체가 막히면 안 된다
        log.warning(f"리치 본문 구성 실패 → 평문으로 발송: {e}")
        return body, None, None


def _send_confirm(slot: str) -> None:
    p = st.session_state.get(_SEND_PENDING)
    if not p or p.get("slot") != slot:
        return
    ch = p["channel"]
    # 🎨 리치 구성은 **여기서** 한다 — 확인 카드에 보이는 본문이 곧 나가는 본문이어야
    #   하기 때문이다. 예약 시점에 미리 만들어두면 그 사이 마스킹·등급 설정을 바꿔도
    #   낡은 본문이 나간다.
    body, html, atts = _compose_pending(p)
    to = (_ai_effective_email() if ch == "email"
          else ("설정된 Slack Webhook" if st.session_state.get("ai_slack_webhook") else ""))
    with st.container(border=True):
        st.markdown("###### " + t("send.confirm_title",
                                  ch="Slack" if ch == "slack" else "Email"))
        if not to:
            st.error(t("ai.no_webhook") if ch == "slack" else t("ai.no_smtp"))
        else:
            st.markdown(t("send.recipients", to=to, tid=p.get("txn_id") or "-",
                          mask=st.session_state.get("pii_level", "-")))
        if not body.strip():
            st.warning(t("send.empty_body"))
        st.caption(t("send.preview_note", n=len(body)))
        st.code(body[:400] + ("…" if len(body) > 400 else ""), language="text")
        if atts:
            # 첨부는 메일함에 그대로 남는다 — 무엇이 붙는지 보고 승인하게 한다
            st.caption(t("send.rich_note", n=len(atts),
                         names=", ".join(a[0] for a in atts)))
        st.caption(t("send.irreversible"))
        c1, c2 = st.columns([1.4, 1])
        if c1.button(t("send.go"), key=f"sendok_{slot}", type="primary",
                     width="stretch", disabled=not to):
            # 카드를 먼저 걷고 발송한다 — _send 가 성공/실패 메시지를 이 자리에
            #   찍으므로, rerun 하지 않아야 결과가 화면에 남는다.
            st.session_state.pop(_SEND_PENDING, None)
            _send(ch, body, fraud_type=p.get("fraud_type"),
                  risk_score=p.get("risk_score", 0), txn_id=p.get("txn_id", ""),
                  subject=p.get("subject"), tier=p.get("tier"),
                  html=html, attachments=atts)
        if c2.button(t("common.cancel"), key=f"sendno_{slot}", width="stretch"):
            st.session_state.pop(_SEND_PENDING, None)
            st.rerun()


def _build_rag(top_k=3):
    return _get_rag_cached(top_k)


class _DummyMasker:
    level = "off"
    def mask_row(self, row): return dict(row)


def _build_masker():
    """✨ 강화 포인트: 별도 설정을 새로 만들지 않고, 트리아지 탭이 이미 쓰는
    'pii_level' 세션 값을 그대로 재사용한다 — 관제 화면 전체가 마스킹 기준
    하나를 공유해 '트리아지에선 마스킹, AI 분석에선 원문' 같은 불일치를 막는다."""
    try:
        from pipeline.pii_masker import PIIMasker
    except ImportError:
        return _DummyMasker()
    level = st.session_state.get('pii_level', 'standard')
    provider = st.session_state.get('ai_llm_provider', 'local')
    if level != 'off' and provider == 'local' and st.session_state.get('ai_pii_skip_local', True):
        level = 'off'
    try:
        return PIIMasker(level=level)
    except Exception:
        return _DummyMasker()


def _redo_step(det: dict, step: str) -> bool:
    """LLM 3단계 중 한 단계만 재생성 — 이 앱의 설정(ai_* 키)으로 팩토리를 묶어
    ops_dispatch 에 넘긴다. dashboard.py 는 같은 함수를 ov_* 키로 부른다."""
    if not odp:
        return False
    return odp.redo_llm_step(
        det, step,
        analyzer_factory=_build_llm_analyzer,
        masker_factory=_build_masker,
        rag_factory=_build_rag,
        lang=LANG,
        rag_k=int(st.session_state.get('ai_rag_k', 3)))


def _ops_chat_context() -> str:
    """AI 어시스턴트에게 줄 '지금 이 순간의 관제 화면 상태' 텍스트 스냅샷.

    dashboard.py의 _chat_context()는 화면이 그릴 때 만든 스냅샷을 저장해뒀다가
    재사용한다(검증셋 기반이라 값이 잘 안 바뀌므로). ops는 반대로 초 단위로
    바뀌는 라이브 DB가 유일한 진실이라, 질문이 들어올 때마다 매번 새로 조회한다
    — 화면에 보이는 숫자와 챗봇 답변이 어긋나는 일이 없다."""
    lines = []
    try:
        status = wp.read_status(DB) if wp else None
        icon, desc = (wp.liveness(status, st.session_state.get("poll_interval", 5.0))
                     if wp else ("⚫", "워처 모듈 없음"))
        lines.append(f"[워처 상태] {icon} {desc}")
        if status:
            lines.append(f"  누적 처리 {status.get('rows_done', '-')}건 · "
                        f"이상거래 {status.get('anomalies', '-')}건 · "
                        f"알림 발송 {status.get('notified', '-')}건 · "
                        f"오류 {status.get('errors', '-')}건")
    except Exception:
        pass

    try:
        pend = oq.alert_queue(DB, limit=200, only_unreviewed=True)
        lines.append(f"[판정 대기 알림] {len(pend)}건")
        if pend:
            by_type = {}
            for r in pend:
                k = ui.fraud_label(r["fraud_type"], LANG, short=True)
                by_type[k] = by_type.get(k, 0) + 1
            top = sorted(by_type.items(), key=lambda x: -x[1])[:5]
            lines.append("  유형별: " + ", ".join(f"{k} {v}건" for k, v in top))
            avg_r = sum(float(r["risk_score"] or 0) for r in pend) / len(pend)
            lines.append(f"  평균 위험도 {avg_r:.3f}")
    except Exception:
        pass

    try:
        win = int(st.session_state.get("window_h", 168))
        fp_rows = oq.fp_timeline(DB, bucket="day", since_hours=win)
        if fp_rows:
            last = fp_rows[-1]
            lines.append(f"[오탐률] 최근 {win}시간 · 최신 구간({last.get('구간','-')}) "
                        f"오탐률 {last.get('오탐률', '-')}% "
                        f"(정탐 {last.get('정탐', '-')}건 · 오탐 {last.get('오탐', '-')}건)")
    except Exception:
        pass

    try:
        cfg = _cfg()
        lines.append(f"[임계값 설정] 1차(검토) {cfg.get('th_review', '-')} · "
                    f"2차(확정) {cfg.get('th_confirm', '-')}")
    except Exception:
        pass

    try:
        if astore:
            cs = astore.stats(DB)
            lines.append(f"[AI 분석 캐시] {cs.get('rows', 0)}건 저장됨 "
                        f"({cs.get('stored_mb', '-')}MB)")
    except Exception:
        pass

    try:
        summ = rs.summary_line(DB, since_hours=int(st.session_state.get("window_h", 168)))
        if summ:
            lines.append(f"[판정 이력 요약] {summ}")
    except Exception:
        pass

    return "\n".join(lines) if lines else "표시할 데이터가 없습니다."


# ══════════════════════════════════════════════════════════
# 🤖 AI 어시스턴트 — 전송 처리 (렌더는 위쪽 _sidebar_chat / AI 탭)
# ══════════════════════════════════════════════════════════
def _run_ops_chat(q: str):
    """질문 1건 처리 → 히스토리에 (질문, 답변) 추가 + 관제 액션 실행.

    ChatAgent 의 `enable_actions` 는 계속 False 로 둔다 — 그 플래그를 켜면
    chat_agent.ACTIONS(전역 · dashboard 전용)가 프롬프트에 붙어, ops 에 없는
    기능(세션 1~5 이동 등)을 안내하게 된다.
    대신 ops 전용 레지스트리(pipeline/ops_agent.py)를 시스템 지시문에 덧붙이고
    응답을 직접 파싱한다. 발송·판정·워처 제어는 화이트리스트에서 제외돼 있다.
    """
    if not q or not q.strip():
        return
    hist = st.session_state.get(CHAT_KEY, [])
    acts, notes = [], []
    try:
        from pipeline.chat_agent import ChatAgent, _SYSTEM as _CHAT_SYSTEM
        _sys = st.session_state.get("chat_system_override") or _CHAT_SYSTEM.get(LANG)
        if oag and _sys:
            _sys = _sys + oag.actions_prompt(LANG)
        agent = ChatAgent(_build_llm_analyzer(), lang=LANG,
                          system_override=_sys, enable_actions=False)
        with st.spinner(t("chat.thinking")):
            ans, _ = agent.answer(hist, q, _ops_chat_context())
        if oag:
            ans, acts = oag.parse(ans)
            if acts:
                # 액션이 큐를 참조할 수 있으므로(select_pending) 현재 큐를 넘긴다
                try:
                    _q_now = oq.alert_queue(DB, limit=100, only_unreviewed=True)
                    if osh:
                        osh.annotate(_q_now, int(st.session_state.get("sla_min", 30)), LANG)
                except Exception:
                    _q_now = []
                notes = oag.apply(acts, st.session_state, queue=_q_now)
            if not ans and notes:
                ans = "요청하신 동작을 실행했습니다."
    except Exception as e:
        ans = f"⚠ {type(e).__name__}: {e}"
    if notes:
        ans = (ans or "") + "\n\n" + "\n".join(f"· {n}" for n in notes)
    st.session_state[CHAT_KEY] = hist + [
        {"role": "user", "content": q},
        {"role": "assistant", "content": ans},
    ]


# 사이드바가 적재해 둔 질문을 여기서 처리한다 — 이 지점이면 LLM 빌더와
#   컨텍스트 수집기가 모두 정의돼 있다. 처리 후 rerun 해야 답변이 화면에 뜬다.
_pending_q = st.session_state.pop(CHAT_PENDING, None)
if _pending_q:
    _run_ops_chat(_pending_q)
    st.rerun()

# 🔧 자가진단의 '이 액션 실행' 도 **같은 자리**에서 처리한다.
#   버튼은 AI 탭 안(= 대부분의 위젯보다 뒤)에 있어서 거기서 apply() 를 부르면
#   "위젯 인스턴스화 후 key 수정" 예외가 난다. 여기는 탭 생성 전이라 안전하다.
#   결과 메모는 세션에 남겨 두고, 다음 런에 진단 패널이 꺼내 보여 준다.
_live_marker = st.session_state.pop("_ops_agent_live", None)
if _live_marker and oag:
    _, _live_acts = oag.parse(f"[[ACTION: {_live_marker}]]")
    st.session_state["_ops_agent_live_notes"] = (
        oag.apply(_live_acts, st.session_state) or ["(반영된 것이 없습니다)"])


# ══════════════════════════════════════════════════════════
# 탭 순서
#
#   1 AI 분석    ★ 첫 화면. 데이터를 넣어 탐지·분석하고 알림까지 보내는 작업대
#   2 트리아지   미판정 알림을 정탐/오탐으로 찍는다 (판정 루프의 본체)
#   3 실시간감시 켜 두는 상황판. 워처 생존 + 새 경보 유입
#   4 교대인계   근무 시작에 앞사람 메모를 읽고, 끝에 남길 것을 적는다
#   5 탐지 로그  "그 거래 어떻게 됐지?" 조회·조사
#   6 오탐 분석  판정이 쌓인 뒤의 회고 — 무엇이 헛 알람이었나
#   7 임계값튜닝 ⑥의 결론을 숫자로 반영 (⑥→⑦ 인과 순서라 붙여 둔다)
#   8 진단       연결 테스트 · 발송 감사 로그 · 타임존
#
# ⚠ 인덱스(TABS[0])가 아니라 **이름**으로 받는다. 예전엔 표시 순서와 `with` 블록
#   순서가 어긋나(1,2,3,4,5,0,6) 코드를 읽기 어려웠고, 탭을 하나 추가할 때마다
#   번호를 다시 세야 했다. 이름을 쓰면 순서를 바꿔도 본문은 손댈 필요가 없다.
# ══════════════════════════════════════════════════════════
# ── 탭 라벨 ────────────────────────────────────────────────
#   압축 모드(tabc.*)는 좁은 화면용이다. 기본 라벨 8개는 한국어 기준 탭바가
#   약 1,100px 인데 1366px 노트북에서 사이드바를 빼면 본문이 1,030px 라 넘친다
#   (마지막 탭이 잘린다). 압축하면 728px 로 들어온다.
#   ⚠ 기본값은 꺼짐 — 확정된 화면 문구를 마음대로 줄이지 않는다. 순서는 어느
#     모드에서도 동일하고, 첫 탭은 항상 🧠 AI 분석이다.
_TAB_KEYS = ("ai", "triage", "live", "shift", "log", "fp", "tune", "diag")

# ⌨ 단축키 V·A 가 예약해 둔 토글 값을 여기서 소비한다.
#   두 값 모두 위젯 key 라, 위젯이 만들어진 **뒤**(파일 끝 단축키 블록)에서
#   직접 쓰면 Streamlit 이 예외를 던진다. 그래서 예약값으로 받아 위젯 생성보다
#   앞인 이 자리에서 옮겨 담는다 — ops_agent 가 사이드바 위젯(_pending_sla 등)에
#   쓰는 것과 똑같은 패턴이다. ops_tab_compact 는 바로 아래에서 읽으므로,
#   소비 지점이 이 줄보다 뒤로 가면 한 박자 늦게 반영된다.
for _pk, _wk in (("_pending_compact", "ops_tab_compact"),
                 ("_pending_autorf", "auto_refresh")):
    if _pk in st.session_state:
        st.session_state[_wk] = bool(st.session_state.pop(_pk))

_compact = bool(st.session_state.setdefault(
    "ops_tab_compact", os.getenv("FDS_OPS_TAB_COMPACT", "") == "1"))
TAB_DEFS = {k: t(f"{'tabc' if _compact else 'tab'}.{k}") for k in _TAB_KEYS}

# ── 배치안 ────────────────────────────────────────────────
#   'ai_first' 가 **확정된 기본값**이다 — 바꾸지 말 것.
#   'ops_first' 는 "관제 흐름(트리아지→감시→인계)대로 놓으면 어떤가"를 눈으로
#   비교해 보기 위한 실험용 배치다. 선택은 **세션에만** 남으므로 브라우저를
#   새로 열면 기본값으로 돌아오고, 파일·설정 어디에도 저장되지 않는다.
#   전환 UI 는 '🩺 진단' 탭 맨 아래. 비교가 끝나면 이 dict 에서 'ops_first'
#   항목과 진단 탭의 해당 블록만 지우면 원래 코드로 돌아간다.
TAB_LAYOUTS = {
    "ai_first":  ["ai", "triage", "live", "shift", "log", "fp", "tune", "diag"],
    "ops_first": ["triage", "live", "shift", "log", "fp", "tune", "ai", "diag"],
}
# 배치안의 표시 문구는 i18n 키 `diag.layout_<배치안키>` 에 있다 —
#   여기 별도 dict 를 두면 언어가 늘 때 한쪽만 고쳐진다.
_layout = st.session_state.setdefault(
    "ops_tab_layout", os.getenv("FDS_OPS_TAB_LAYOUT", "ai_first"))
if _layout not in TAB_LAYOUTS:                         # 오타·구버전 값 방어
    _layout = st.session_state["ops_tab_layout"] = "ai_first"

TAB_ORDER = [(k, TAB_DEFS[k]) for k in TAB_LAYOUTS[_layout]]
TAB_LABEL = dict(TAB_ORDER)
TAB_KEY = "ops_tab"

# 경보 카드 클릭 → 해당 탭으로 실제 이동.
#   st.tabs 는 1.58부터 key/default 를 받는다. 위젯 생성 **전에** 세션 값을
#   바꿔야 반영되므로 반드시 이 자리에서 소비한다.
#   (이전 버전은 _force_tab 을 세팅만 하고 읽는 곳이 없어 동작하지 않았다 —
#    거래 ID만 넘어가고 담당자가 트리아지 탭을 손으로 눌러야 했다.)
_ft = st.session_state.pop("_force_tab", None)
if _ft and _ft in TAB_LABEL:
    st.session_state[TAB_KEY] = TAB_LABEL[_ft]

# ⚠ st.tabs(key=…) 는 **선택된 라벨 문자열**을 세션에 담는다. 언어나 압축 모드를
#   바꾸면 라벨 집합이 통째로 달라져 저장된 값이 어디에도 없는 문자열이 된다.
#   그대로 두면 선택이 조용히 첫 탭으로 튀거나 위젯이 예외를 던진다.
#   여기서 지워 주면 default= 가 다시 적용된다(= 첫 탭).
if st.session_state.get(TAB_KEY) not in TAB_LABEL.values():
    st.session_state.pop(TAB_KEY, None)

# 경보에서 넘어온 거래 ID — 여기서 한 번만 꺼내 모든 탭이 공유한다.
#   예전엔 트리아지 블록이 pop 해버려, 뒤에 오는 AI 탭의 '단건 분석' 기본 선택
#   코드가 항상 None 을 받았다(= 죽은 경로). 소비 지점을 탭 밖으로 올려 해결.
JUMP_TXN = st.session_state.pop("jump_txn", None)

# 🤖 챗봇 실행형 액션(run_ai_analysis / run_batch)의 예약 플래그.
#   ⚠ **여기서** 꺼낸다. 실행 지점(AI 탭의 단건 분석·일괄 분석 버튼)은 둘 다
#     조건 분기 깊숙한 곳이라, 거기서 pop 하면 조건이 안 맞은 런에서 플래그가
#     소비되지 않고 남는다 — 다음 자동 새로고침 때 사용자가 시키지도 않은
#     분석이 갑자기 도는 셈이다. 바로 위 JUMP_TXN 이 같은 이유로 탭 밖으로
#     올라와 있다. 플래그는 "이 런에서 한 번"만 유효하다.
PENDING_AI_RUN = bool(st.session_state.pop("_pending_ai_run", False))
PENDING_BATCH_RUN = bool(st.session_state.pop("_pending_batch_run", False))

TABS = st.tabs([lbl for _, lbl in TAB_ORDER], key=TAB_KEY,
               default=TAB_ORDER[0][1])
# ⚠ 위치가 아니라 **이름**으로 받는다. 배치안을 바꿔도 아래 `with TAB_*` 블록은
#   한 줄도 손대지 않는다 — 위치 언패킹이면 순서가 바뀌는 순간 전부 어긋난다.
_TAB = {k: c for (k, _lbl), c in zip(TAB_ORDER, TABS)}
TAB_AI, TAB_TRIAGE, TAB_LIVE = _TAB["ai"], _TAB["triage"], _TAB["live"]
TAB_SHIFT, TAB_LOG, TAB_FP = _TAB["shift"], _TAB["log"], _TAB["fp"]
TAB_TUNE, TAB_DIAG = _TAB["tune"], _TAB["diag"]


# ══════════════════════════════════════════════════════════
# 탭 1 — 🚨 알림 트리아지  ★ 이 앱의 존재 이유 (미판정 → 정탐/오탐)
# ══════════════════════════════════════════════════════════
with TAB_TRIAGE:
    f1, f2, f3, f4 = st.columns([1.2, 1, 1, 1])
    with f1:
        only_new = st.toggle(t("tri.only_new"), value=True, key="tri_only_new")
    with f2:
        min_sc = st.slider(t("tri.min_score"), 0.0, 1.0, 0.0, 0.05, key="tri_min")
    with f3:
        # 상한 50. 행마다 expander+체크박스+라디오+셀렉트+입력+버튼(≈6위젯)이라
        #   100건이면 600위젯이 되어 Streamlit 이 눈에 띄게 느려진다 —
        #   관제에서 화면이 굼뜬 것은 기능이 하나 없는 것보다 나쁘다.
        #   더 봐야 하면 '최소 점수'·정렬로 좁히는 편이 빠르다.
        _TRI_OPTS = [10, 20, 30, 50]
        if st.session_state.get("tri_n") not in _TRI_OPTS:
            st.session_state.pop("tri_n", None)        # 구버전 값(100) 정리
        n_show = st.select_slider(t("tri.show_n"), _TRI_OPTS, value=20, key="tri_n",
                                  help=t("tri.show_n_help"))
    with f4:
        # 기본값을 '대기 오래된 순'으로 둔다. 점수 높은 건은 이미 누가 봤을
        # 확률이 높고, 방치된 건은 아무도 안 봤다 — 후자가 더 위험하다.
        #
        # ⚠ 옵션은 **코드값**(age/score)이고 화면 문구는 format_func 가 만든다.
        #   예전엔 라디오가 돌려준 한글 라벨을 `== "대기순"` 으로 비교했다 —
        #   그 상태로 번역하면 한국어 외 언어에서 조건이 영원히 거짓이 되어
        #   정렬이 조용히 점수순으로 굳는다(화면은 '대기순'이라고 말하면서).
        #   세션에 남은 구버전 한글 값도 여기서 정리한다.
        _SORT_OPTS = ["age", "score"]
        if st.session_state.get("tri_sort") not in _SORT_OPTS:
            st.session_state.pop("tri_sort", None)
        tri_sort = st.radio(t("tri.sort"), _SORT_OPTS, horizontal=True, key="tri_sort",
                            format_func=lambda k: t(f"tri.sort_{k}"))
        tri_desc = st.toggle(t("tri.sort_desc"), key="tri_sort_desc",
                             help=t("tri.sort_desc_help"))

    SLA_MIN = int(st.session_state.get("sla_min", 30))
    REVIEWER = st.session_state.get("reviewer") or rs.default_reviewer()
    CLAIM_ON = bool(st.session_state.get("claim_on", True))

    jump = JUMP_TXN
    if jump:
        st.info(t("tri.jumped", tid=jump))

    queue = oq.alert_queue(DB, limit=int(n_show), min_score=float(min_sc),
                           only_unreviewed=bool(only_new))
    if jump:
        # 경보로 들어온 건이 필터에 걸려 안 보이면 큐에 강제로 끌어올린다 —
        # 클릭했는데 아무것도 없는 화면이 나오는 것이 최악의 경험이다
        if not any(r["txn_id"] == jump for r in queue):
            extra = oq.alert_queue(DB, limit=300, min_score=0.0, only_unreviewed=False)
            hit = [r for r in extra if r["txn_id"] == jump]
            queue = hit + queue
        else:
            queue.sort(key=lambda r: r["txn_id"] != jump)

    # ── ⏱ SLA 주석 + 현황 ──────────────────────────────────
    #   지금까지 큐는 '미판정 여부'만 봤다. 3분 전 알림과 6시간 전 알림이
    #   같은 모습으로 나란히 있었는데, 관제에서 중요한 건 방치된 시간이다.
    if osh:
        osh.annotate(queue, SLA_MIN, LANG)
        _sla = osh.sla_stats(queue, SLA_MIN)
        if not jump:
            # 대기순 = age_min, 점수순 = risk_score. 방향은 토글이 정한다.
            #   기본(내림차순)은 각각 '오래 기다린 순' · '위험한 순'이다.
            _key = ((lambda r: (r.get("age_min") if r.get("age_min") is not None
                                else osh.age_minutes(r.get("ts_utc")) or 0))
                    if tri_sort == "age"
                    else (lambda r: float(r.get("risk_score") or 0)))
            queue = sorted(queue, key=_key, reverse=bool(tri_desc))
        k1, k2, k3, k4 = st.columns(4)
        k1.metric(t("tri.kpi_pending"), t("common.cases", n=_sla["pending"]))
        k2.metric(t("tri.kpi_over", n=SLA_MIN), t("common.cases", n=_sla["over"]),
                  delta=None if not _sla["over"] else t("tri.need_check"),
                  delta_color="inverse" if _sla["over"] else "off")
        k3.metric(t("tri.kpi_warn"), t("common.cases", n=_sla["warn"]))
        k4.metric(t("tri.kpi_oldest"), osh.elapsed_label(_sla["oldest_min"], LANG))

    # ── 🔒 잠금 하트비트 ───────────────────────────────────
    #   claim() 은 위젯을 만질 때만 불린다. 한 건을 15분 넘게 들여다보면 잠금이
    #   만료돼 다른 담당자가 같은 알림을 집는다 — 잠금을 둔 의미가 사라진다.
    #   화면이 열려 있는 동안 주기적으로 갱신한다. 브라우저를 닫으면 갱신이
    #   멈춰 TTL 이 제 역할을 한다(그게 TTL 의 원래 목적이다).
    if CLAIM_ON:
        _hb_frag = getattr(st, "fragment", None)
        _hb_sec = max(60, int(rs.CLAIM_TTL_MIN * 60 / 3))   # TTL 의 1/3 주기
        if _hb_frag is not None:
            @_hb_frag(run_every=_hb_sec)
            def _claim_heartbeat():
                n = rs.renew_claims(DB, REVIEWER)
                if n:
                    st.caption(t("tri.heartbeat", n=n, ts=time.strftime("%H:%M:%S")))
            _claim_heartbeat()
        else:                                              # pragma: no cover
            rs.renew_claims(DB, REVIEWER)

    # 잠금·임시저장은 큐 전체분을 **한 번만** 조회한다.
    #   행마다 질의하면 20행 = 40회 왕복이고, 워처가 도는 중 WAL 경합이 눈에 띈다.
    _claims = rs.active_claims(DB) if CLAIM_ON else {}
    _drafts = rs.load_drafts(DB, REVIEWER)
    if _drafts:
        st.caption(t("tri.drafts", n=len(_drafts)))

    st.markdown("##### " + t("tri.title_n", title=t("tri.title"), n=len(queue)))

    if not queue:
        st.info(t("tri.empty"))
    else:
        thr, thc = _tier_th()

        # ══════════════════════════════════════════════════════
        # ☑️ 일괄 판정 — 같은 결론이 뻔한 건들을 한 번에
        #   실제 관제에서는 "테스트 계정 20건", "같은 배치 오류 15건"처럼
        #   한 눈에 같은 결론인 묶음이 흔하다. 하나씩 펼쳐 찍으면 20번 rerun 이다.
        #   record_many() 는 **하나의 트랜잭션**으로 묶어 커밋한다 —
        #   50번 커밋하면 그만큼 WAL 체크포인트가 끼어들어 워처 폴링이 밀린다.
        # ══════════════════════════════════════════════════════
        _SEL_KEY = "tri_bulk_sel"
        _sel: set = set(st.session_state.get(_SEL_KEY, set()))
        # 큐에서 사라진(이미 판정된) 건은 선택에서도 지운다
        _qids = {r["txn_id"] for r in queue}
        _sel &= _qids

        with st.container(border=True):
            bs1, bs2, bs3, bs4 = st.columns([1.1, 1.1, 1.3, 2.5],
                                            vertical_alignment="bottom")
            if bs1.button(t("tri.sel_all"), key="tri_sel_all", width="stretch"):
                st.session_state[_SEL_KEY] = set(_qids)
                st.rerun()
            if bs2.button(t("tri.sel_none"), key="tri_sel_none", width="stretch"):
                st.session_state[_SEL_KEY] = set()
                st.rerun()
            if bs3.button(t("tri.sel_over"), key="tri_sel_over", width="stretch",
                          help=t("tri.sel_over_help")):
                st.session_state[_SEL_KEY] = {
                    r["txn_id"] for r in queue if r.get("urgency") == "over"}
                st.rerun()
            bs4.caption(t("tri.sel_count", n=len(_sel), m=len(queue))
                        + (t("tri.sel_hint") if _sel else ""))

            if _sel:
                bv1, bv2, bv3 = st.columns([1.2, 1.6, 1.2],
                                           vertical_alignment="bottom")
                _bv = bv1.radio(t("tri.verdict"), rs.VERDICTS, key="tri_bulk_verdict",
                                format_func=lambda v: t(f"tri.{v}"))
                _br = None
                if _bv == "fp":
                    _br = bv2.selectbox(t("tri.reason"), list(rs.FP_REASONS),
                                        key="tri_bulk_reason",
                                        format_func=lambda c: ui.reason_label(c, LANG))
                else:
                    bv2.caption(t("tri.bulk_reason_hint"))
                _bm = st.text_input(t("tri.bulk_memo"), key="tri_bulk_memo",
                                    placeholder=t("tri.bulk_memo_ph"))

                # 남이 잠근 건은 일괄에서 제외한다 — 일괄이라고 잠금을 무시하면
                # 잠금을 둔 의미가 없다. 몇 건이 빠지는지 미리 알린다.
                _blocked = {tid for tid in _sel
                            if (_claims.get(tid) or {}).get("reviewer", REVIEWER) != REVIEWER}
                _target = sorted(_sel - _blocked)
                if _blocked:
                    st.warning(t("tri.bulk_blocked", n=len(_blocked),
                                 ids=", ".join(sorted(_blocked)[:3])))

                if st.button(t("tri.bulk_save", n=len(_target)),
                             key="tri_bulk_save", type="primary", width="stretch",
                             disabled=not _target):
                    _qmap = {r["txn_id"]: r for r in queue}
                    _items = []
                    for tid_ in _target:
                        _r = _qmap.get(tid_) or {}
                        _sc = float(_r.get("risk_score") or 0)
                        _items.append({
                            "txn_id": tid_, "verdict": _bv, "reason": _br,
                            "memo": _bm or None,
                            "alert_ref": _r.get("alert_ref"),
                            "risk_score": _sc, "fraud_type": _r.get("fraud_type"),
                            "model": _r.get("model"),
                            "tier": ("confirm" if _sc >= thc
                                     else "review" if _sc >= thr else "none"),
                            "th_review": thr, "th_confirm": thc,
                        })
                    n_ok, errs = rs.record_many(DB, _items, reviewer=REVIEWER)
                    # 판정이 끝났으면 잠금·임시저장·선택 상태를 함께 정리한다
                    for tid_ in _target:
                        rs.release(DB, tid_, REVIEWER)
                        rs.clear_draft(DB, tid_, REVIEWER)
                        for _k in (f"v_{tid_}", f"r_{tid_}", f"m_{tid_}"):
                            st.session_state.pop(_k, None)
                    st.session_state[_SEL_KEY] = set(_blocked)
                    if n_ok:
                        st.success(t("tri.bulk_done", n=n_ok))
                    for e in errs[:5]:
                        st.error(e)
                    st.rerun()

        for r in queue:
            tid = r["txn_id"]
            _held = _claims.get(tid)
            _mine = bool(_held and _held["reviewer"] == REVIEWER)
            _locked = bool(_held and not _mine)
            _urg = {"over": "🔴", "warn": "🟡", "ok": ""}.get(r.get("urgency", "ok"), "")
            _age = f' · ⏱ {r["elapsed"]}' if r.get("elapsed") else ""
            _lock_txt = (f' · 🔒 {_held["reviewer"]}' if _locked
                         else (' · ✏️ 내가 검토 중' if _mine else ''))
            _dft = '  💾' if tid in _drafts else ''
            head = (f'{_urg}{r["risk_score"]:.3f} · '
                    f'{ui.fraud_label(r["fraud_type"], LANG, short=True)} · '
                    f'{tid} · {r["시각"]}{_age}{_lock_txt}{_dft}')

            # 체크박스를 expander **밖**에 둔다 — 안에 두면 펼쳐야만 선택할 수 있어
            # "훑어보며 여러 건 고르기"라는 일괄 판정의 목적이 사라진다.
            _cb, _ex = st.columns([0.055, 0.945])
            with _cb:
                _checked = st.checkbox(
                    t("tri.cb_label"), value=(tid in _sel), key=f"cb_{tid}",
                    label_visibility="collapsed",
                    help=t("tri.cb_help", tid=tid))
                if _checked and tid not in _sel:
                    _sel.add(tid)
                    st.session_state[_SEL_KEY] = _sel
                elif not _checked and tid in _sel:
                    _sel.discard(tid)
                    st.session_state[_SEL_KEY] = _sel
            with _ex:
                _row_ctx = st.expander(head, expanded=(tid == jump))
            with _row_ctx:
                if _locked:
                    st.warning(t("tri.locked", who=_held["reviewer"],
                                 min=_held["age_min"]))
                    if st.button(t("tri.steal"), key=f"steal_{tid}"):
                        rs.release(DB, tid)
                        rs.claim(DB, tid, REVIEWER)
                        st.rerun()
                d1, d2 = st.columns([1.3, 1])
                with d1:
                    st.markdown(f"**{t('tri.detail')}**")
                    st.caption(t("tri.masked_note"))
                    feats = rc.load_stored_features(DB, tid) if rc else {}
                    if feats:
                        safe = (rc.safe_view(feats, st.session_state["pii_level"])
                                if rc else feats)
                        st.json({k: v for k, v in list(safe.items())[:25]}, expanded=False)
                    else:
                        st.caption(t("common.none"))

                    if rc and st.button(t("tri.recheck"), key=f"rk_{tid}"):
                        res = rc.recheck(DB, tid, model_dir=st.session_state["model_dir"])
                        if res["blocked"]:
                            st.warning(res["blocked"])
                        else:
                            cur = res["current"]
                            st.success(t("tri.recheck_now", ft=cur["fraud_type"],
                                         score=f"{cur['risk_score']:.4f}"))
                            if res.get("drift"):
                                st.caption(res["drift"]["해석"])

                with d2:
                    st.markdown(f"**{t('tri.verdict')}**")

                    # ── 💾 임시저장 복원 ────────────────────────
                    #   위젯 key 가 세션에 없을 때만 DB 값을 심는다. 이미 있으면
                    #   사용자가 방금 만진 값이므로 덮어쓰면 안 된다.
                    _d = _drafts.get(tid) or {}
                    if _d:
                        if f"v_{tid}" not in st.session_state and _d.get("verdict") in rs.VERDICTS:
                            st.session_state[f"v_{tid}"] = _d["verdict"]
                        if f"r_{tid}" not in st.session_state and _d.get("reason") in rs.FP_REASONS:
                            st.session_state[f"r_{tid}"] = _d["reason"]
                        if f"m_{tid}" not in st.session_state and _d.get("memo"):
                            st.session_state[f"m_{tid}"] = _d["memo"]

                    # 위젯을 만질 때마다 ① 잠금 갱신 ② 임시저장.
                    #   on_change 는 바뀐 위젯 하나에 대해서만 불리므로,
                    #   화면을 다시 그릴 때마다 20행을 쓰는 낭비가 없다.
                    def _touch(_tid=tid):
                        if CLAIM_ON:
                            rs.claim(DB, _tid, REVIEWER)
                        rs.save_draft(
                            DB, _tid, REVIEWER,
                            verdict=st.session_state.get(f"v_{_tid}"),
                            reason=st.session_state.get(f"r_{_tid}"),
                            memo=st.session_state.get(f"m_{_tid}"))

                    verdict = st.radio(
                        t("tri.verdict"), rs.VERDICTS, key=f"v_{tid}",
                        label_visibility="collapsed", on_change=_touch,
                        format_func=lambda v: t(f"tri.{v}"))
                    reason = None
                    if verdict == "fp":
                        reason = st.selectbox(
                            t("tri.reason"), list(rs.FP_REASONS), key=f"r_{tid}",
                            on_change=_touch,
                            format_func=lambda c: ui.reason_label(c, LANG))
                    memo = st.text_input(t("tri.memo"), key=f"m_{tid}", on_change=_touch)
                    if _d.get("updated_at"):
                        st.caption(t("tri.draft_saved", age=(
                            osh.elapsed_label(osh.age_minutes(_d["updated_at"]), LANG)
                            if osh else _d["updated_at"])))
                    if st.button(t("tri.save"), key=f"s_{tid}", type="primary",
                                 width="stretch"):
                        ok, msg = rs.record(
                            DB, tid, verdict, reason=reason, memo=memo,
                            reviewer=REVIEWER,
                            # 판정 당시 스냅샷 — 임계값이 나중에 바뀌어도 비교 기준이 남는다
                            snapshot={"alert_ref": r.get("alert_ref"),
                                      "risk_score": r.get("risk_score"),
                                      "fraud_type": r.get("fraud_type"),
                                      "model": r.get("model"),
                                      "tier": ("confirm" if r["risk_score"] >= thc
                                               else "review" if r["risk_score"] >= thr
                                               else "none"),
                                      "th_review": thr, "th_confirm": thc})
                        (st.success if ok else st.error)(msg)
                        if ok:
                            # record() 가 잠금·임시저장을 이미 지웠다. 위젯 상태도
                            # 함께 비워야 다음 알림에 이전 메모가 따라붙지 않는다.
                            for _k in (f"v_{tid}", f"r_{tid}", f"m_{tid}"):
                                st.session_state.pop(_k, None)
                            st.rerun()
                    if _mine and st.button(t("tri.unlock"), key=f"unlock_{tid}"):
                        rs.release(DB, tid, REVIEWER)
                        st.rerun()


# ══════════════════════════════════════════════════════════
# 탭 2 — 🟢 실시간 감시 (상시 켜 두는 상황판)
# ══════════════════════════════════════════════════════════
with TAB_LIVE:
    c_top1, c_top2 = st.columns([3, 1], vertical_alignment="center")
    with c_top2:
        auto = st.toggle(t("live.autorefresh"), key="auto_refresh")
        interval = st.select_slider(t("live.sec"), [3, 5, 10, 30, 60],
                                    key="_refresh_sec", label_visibility="collapsed")

    # st.fragment(run_every=…) 는 이 블록만 재실행한다 — 전체 rerun 이면
    # 모델·데이터셋 캐시와 트리아지 입력 위젯 상태까지 흔들린다.
    _frag = getattr(st, "fragment", None)

    def _render_live():
        status = wp.read_status(DB) if wp else None
        _from_push = False
        # ☁ 로컬 DB 에 워처 흔적이 없으면, 워처가 밖으로 내보낸 스냅샷을 읽는다.
        #   Streamlit Cloud 처럼 **다른 서버**에서 이 화면을 띄운 경우가 그렇다
        #   (README_WATCHER5 §9). 워처 쪽 설정은 FDS_STATUS_FILE.
        if status is None and _sp is not None:
            _f = os.getenv("FDS_STATUS_FILE")
            if _f:
                status = _sp.read_status_file(_f)
                _from_push = status is not None
        icon, desc = (wp.liveness(status, st.session_state["poll_interval"])
                      if wp else ("⚫", t("live.never")))
        if _from_push:
            st.caption(t("live.from_push", path=os.getenv("FDS_STATUS_FILE")))
        if status is None:
            st.info(t("live.never"))
        else:
            (st.success if icon == "🟢" else st.error if icon == "🔴"
             else st.info)(f"{icon} {desc}")
            _kpi_row([
                (t("live.kpi_polls"), f"{status['polls']:,}", None),
                (t("live.kpi_rows"), f"{status['rows_done']:,}", None),
                (t("live.kpi_anom"), f"{status['anomalies']:,}", None),
                (t("live.kpi_sent"), f"{status['notified']:,}", None),
                (t("live.kpi_err"), f"{status['errors']:,}",
                 None if not status["errors"] else t("live.need_check")),
            ])

        st.markdown(f"##### {t('live.feed')}")
        feed = oq.live_feed(DB, limit=12, only_anomaly=True)
        if not feed:
            st.caption(t("common.none"))
        else:
            thr, thc = _tier_th()
            for r in feed:
                cls = _score_class(r["risk_score"], thr, thc)
                st.markdown(
                    f'<div class="alert-card {cls}">'
                    f'<span class="mono" style="font-size:13px;font-weight:700">'
                    f'{r["risk_score"]:.3f}</span> &nbsp;'
                    f'<b>{ui.fraud_label(r["fraud_type"], LANG, short=True)}</b>'
                    f'<span class="note"> · {r["txn_id"]} · {r["시각"]}'
                    f'{" · " + str(r["source"]) if r.get("source") else ""}</span>'
                    f'</div>', unsafe_allow_html=True)
        # ── 🚨 신규 이상거래 경보 ──────────────────────────
        #   프래그먼트 안이라 자동 갱신 주기를 그대로 탄다. 별도 타이머가 없다.
        if oa and st.session_state.get("alarm_on"):
            _pthr, _pthc = _tier_th()
            new_alerts = oa.poll_new(oq, DB, st.session_state, _pthr, _pthc)
            if new_alerts:
                oa.fire(st.session_state, new_alerts)
                oa.render(st, new_alerts, st.session_state, T,
                          ui.fraud_label, LANG, app_url_param="goto")

        st.caption(f"🕐 {time.strftime('%H:%M:%S')}")

    if _frag is not None and auto:
        _render_live = _frag(run_every=interval)(_render_live)
        _render_live()
    else:
        _render_live()
        if st.button(f"🔄 {t('common.refresh')}", key="live_refresh"):
            st.rerun()
        if auto and _frag is None:
            st.caption(t("live.no_fragment"))

    # ══ 🚨 경보 설정 ══════════════════════════════════════
    if oa:
        _cur_tier = st.session_state.get("alarm_tier", "confirm")
        _on = st.session_state.get("alarm_on")
        _athr, _athc = _tier_th()
        # 사이드바의 '⚙ 경보 세부 설정'을 누르면 이 패널을 펼친 채로 연다 —
        #   접힌 패널로 보내 놓고 "여기 있습니다"라고 하면 한 번 더 찾아야 한다.
        _on_txt = t("alarm.on") if _on else t("alarm.off")
        with st.expander(t("alarm.panel_title", state=_on_txt,
                           tier=oa.tier_label(_cur_tier, LANG, _athr,
                                              _athc).split(" —")[0]),
                         expanded=bool(st.session_state.pop("_open_alarm", False))):
            # 등급 경계가 어디서 오는지 명시한다 — 이 숫자를 바꾸는 곳은
            #   '⚙ 임계값 튜닝' 탭이지 이 패널이 아니다.
            st.caption(t("alarm.tier_basis", thr=oa.fmt_th(_athr),
                         thc=oa.fmt_th(_athc)))
            # ── 켜기 전에 대가를 보여준다 ────────────────────
            #   알람은 기능이 부족해서가 아니라 과해서 꺼진다. 하루 몇 번 울리고
            #   그중 몇 번이 헛것인지 모르고 켜면 반드시 사흘 안에 꺼진다.
            #   ⚠️ 예보는 반드시 폴링과 **같은 임계값**으로 계산해야 의미가 있다.
            fc = oa.noise_forecast(oq, rs, DB, st.session_state,
                                   hours=int(st.session_state["window_h"]),
                                   th_review=_athr, th_confirm=_athc)
            n1, n2, n3 = st.columns(3)
            n1.metric(t("alarm.fc_expected"), t("alarm.per_day", n=fc["per_day"]))
            n2.metric(t("alarm.fc_fp"),
                      f"{fc['fp_rate']*100:.0f}%" if fc["fp_rate"] is not None else "-")
            n3.metric(t("alarm.fc_wasted"),
                      t("alarm.per_day", n=fc["wasted"]) if fc["wasted"] is not None else "-",
                      delta=t("alarm.raise_tier"), delta_color="off")
            if fc["wasted"] and fc["wasted"] >= 3:
                st.warning(t("alarm.noisy", n=fc["wasted"]))

            a1, a2 = st.columns([1, 1.6])
            with a1:
                # ⚠ '경보 켜기' 토글은 **사이드바(🛡 관제 설정)로 이주**했다.
                #   같은 key 로 위젯을 두 번 만들면 Streamlit 이 죽고, 무엇보다
                #   "알람 어떻게 꺼요"의 답이 이 탭 안쪽 접힌 패널이면 아무도
                #   못 찾는다(결국 스피커를 끈다). 마스터는 늘 보이는 곳에 둔다.
                st.markdown(t("alarm.state_line", state=_on_txt))
                st.caption(t("alarm.master_note"))
                # ✨ 경보 정책은 두 대시보드가 한 벌을 쓴다 — 여기서 바꾼 값이
                #   dashboard.py 세션5 의 경보에도 그대로 적용된다(파일 공유).
                #   같은 사람의 같은 스피커로 나가므로 정책이 갈리면 사고가 된다.
                _sv = _save_alarm_prefs
                st.toggle(t("alarm.sound"), key="alarm_sound", on_change=_sv)
                st.toggle(t("alarm.desktop"), key="alarm_desktop", on_change=_sv)
                st.toggle(t("alarm.popup"), key="alarm_popup", on_change=_sv,
                          help=t("alarm.popup_help"))
                st.toggle(t("alarm.banner"), key="alarm_banner", on_change=_sv,
                          help=t("alarm.banner_help"))
            with a2:
                st.selectbox(t("alarm.tier_pick"), oa.TIERS, key="alarm_tier",
                             on_change=_sv,
                             format_func=lambda k: oa.tier_label(
                                 k, LANG, _athr, _athc))
                st.slider(t("alarm.volume"), 0.0, 1.0, key="alarm_volume", step=0.05,
                          on_change=_sv)
                st.slider(t("alarm.beeps"), 1, 10, key="alarm_beeps", on_change=_sv,
                          help=t("alarm.beeps_help"))
                st.number_input(t("alarm.dedup"), 0, 1440, key="alarm_dedup_min",
                                on_change=_sv)
                q1, q2 = st.columns(2)
                q1.number_input(t("alarm.quiet_from"), 0, 23, key="alarm_quiet_from",
                                on_change=_sv)
                q2.number_input(t("alarm.quiet_to"), 0, 23, key="alarm_quiet_to",
                                on_change=_sv)
                st.caption(t("alarm.quiet_note"))
                st.caption(t("alarm.shared_note", path=str(oa.prefs_path().name)))

            st.markdown("---")
            st.markdown("###### " + t("alarm.arm_header"))
            st.caption(t("alarm.arm_note"))
            oa.arm_button(st, T)

            # 상태를 파이썬이 직접 읽을 수 없다(브라우저 안의 값이다).
            #   그래서 진단 버튼이 브라우저에서 읽어 화면에 직접 써 준다.
            oa.diagnostics_button(st, T)

            ta1, ta2, ta3 = st.columns(3)
            _armed = bool(st.session_state.get("alarm_audio_armed"))
            # 테스트 점수도 실제 등급 경계에서 뽑는다 — 0.93/0.55/0.30 을 고정해 두면
            #   th_confirm=0.9 같은 설정에서 '검토 경보 0.55' 가 실제로는 검토가
            #   아닌 값이 되어, 화면과 판정 규칙이 또 어긋난다.
            _sc_conf = min(0.999, (_athc + 1.0) / 2)
            _sc_rev = (_athr + _athc) / 2 if _athc > _athr else _athr
            _sc_none = _athr / 2
            for _tier, _sc, _col in (("confirm", _sc_conf, ta1),
                                     ("review", _sc_rev, ta2),
                                     ("none", _sc_none, ta3)):
                if _col.button(t(f"alarm.test_{_tier}"), key=f"alarm_test_{_tier}",
                               width="stretch"):
                    # 테스트는 등급 필터·조용한 시간을 우회한다 — "지금 이 설정으로
                    # 소리가 나는가"를 확인하는 것이 목적이므로, 필터에 걸려
                    # 아무 일도 안 일어나면 고장인지 설정인지 구분할 수 없다.
                    st.session_state["alarm_audio_armed"] = True
                    _test_a = [{"txn_id": f"TEST_{_tier.upper()}",
                                "risk_score": _sc, "fraud_type": "f",
                                "tier": _tier,
                                "시각": time.strftime("%Y-%m-%d %H:%M:%S"),
                                "source": "test"}]
                    oa.fire(st.session_state, _test_a)     # 배너용(폴백) 적재
                    oa.render(st, _test_a, st.session_state, T, ui.fraud_label, LANG)
                    if not _armed:
                        st.info(t("alarm.arm_first"))
            st.caption(t("alarm.test_note"))

    # 워처 제어·설정은 기존 패널을 그대로 재사용한다 (중복 구현 금지)
    if wp:
        with st.expander(t("live.watcher_panel"), expanded=False):
            wp.render_watcher_panel(DB, st.session_state["log_path"],
                                    st.session_state["poll_interval"],
                                    key_prefix="ops", expanded=False, lang=LANG)


# ══════════════════════════════════════════════════════════
# 탭 3 — 🔄 교대 인수인계 (근무 시작에 읽고, 끝에 적는다)
# ══════════════════════════════════════════════════════════
with TAB_SHIFT:
    if not osh:
        st.caption(t("shift.no_module"))
    else:
        _sh_hours = int(st.session_state.get("shift_hours", 8))
        _sla_min = int(st.session_state.get("sla_min", 30))
        _reviewer = st.session_state.get("reviewer") or rs.default_reviewer()

        # ── ① 앞사람이 남긴 것부터 ──────────────────────────
        #   근무를 시작할 때 가장 먼저 볼 것은 내 실적이 아니라 인계 사항이다.
        st.markdown("##### " + t("shift.prev_header"))
        _prev = osh.recent_handovers(DB, limit=5, lang=LANG)
        if not _prev:
            st.caption(t("shift.prev_empty"))
        else:
            _last = _prev[0]
            st.info(t("shift.prev_entry", who=_last["author"], age=_last["age"])
                    + f"\n\n{_last['note']}")
            if len(_prev) > 1:
                with st.expander(t("shift.prev_more", n=len(_prev) - 1)):
                    for h in _prev[1:]:
                        st.markdown(t("shift.prev_entry", who=h["author"], age=h["age"]))
                        st.caption(h["note"])
                        if h.get("snapshot"):
                            with st.expander(t("shift.prev_snapshot"), expanded=False):
                                st.markdown(h["snapshot"])
                        st.divider()

        st.divider()

        # ── ② 내 근무 동안 무슨 일이 있었나 ──────────────────
        sc1, sc2 = st.columns([3, 1], vertical_alignment="bottom")
        sc1.markdown("##### " + t("shift.summary_header", h=_sh_hours))
        if sc2.button(t("shift.recalc"), key="sh_refresh", width="stretch"):
            st.rerun()

        _sum = osh.shift_summary(DB, hours=_sh_hours, sla_min=_sla_min, lang=LANG)
        _c, _s = _sum["counts"], _sum["sla"]
        m1, m2, m3, m4 = st.columns(4)
        m1.metric(t("shift.arrived"), t("common.cases", n=_sum["arrived"]))
        m2.metric(t("shift.judged"), t("common.cases", n=_c.get("total", 0)))
        m3.metric(t("shift.left"), t("common.cases", n=_s.get("pending", 0)),
                  delta=(t("shift.sla_over_delta", n=_s.get("over", 0))
                         if _s.get("over") else None),
                  delta_color="inverse" if _s.get("over") else "off")
        m4.metric(t("tri.kpi_oldest"), osh.elapsed_label(_s.get("oldest_min"), LANG))

        v1, v2, v3, v4 = st.columns(4)
        v1.metric(t("tri.tp"), _c.get("tp", 0))
        v2.metric(t("tri.fp"), _c.get("fp", 0))
        v3.metric(t("tri.fn"), _c.get("fn", 0))
        v4.metric(t("tri.unclear"), _c.get("unclear", 0))
        if _c.get("fp_rate") is not None:
            st.caption(t("shift.fp_rate_note", rate=f"{_c['fp_rate'] * 100:.1f}"))

        _by = _sum.get("by_reviewer") or []
        if _by:
            st.markdown("###### " + t("shift.by_reviewer"))
            st.dataframe(pd.DataFrame(_by).rename(columns={
                "reviewer": t("shift.col_reviewer"), "tp": t("shift.col_tp"),
                "fp": t("shift.col_fp"), "fn": t("shift.col_fn"),
                "unclear": t("shift.col_unclear"), "total": t("shift.col_total")}),
                width="stretch", hide_index=True)

        _pend = _sum.get("pending") or []
        if _pend:
            st.markdown("###### " + t("shift.pending_header"))
            st.dataframe(pd.DataFrame([{
                t("shift.col_wait"): r.get("elapsed", "—"),
                "SLA": {"over": t("shift.urg_over"),
                        "warn": t("shift.urg_warn")}.get(r.get("urgency"), "🟢"),
                t("shift.col_txn"): r.get("txn_id", ""),
                t("shift.col_type"): ui.fraud_label(r.get("fraud_type"), LANG, short=True),
                t("shift.col_score"): round(float(r.get("risk_score") or 0), 4),
                t("shift.col_time"): r.get("시각", ""),
            } for r in _pend[:15]]), width="stretch", hide_index=True)
        else:
            st.success(t("shift.pending_none"))

        st.divider()

        # ── ③ 남길 것을 적는다 ─────────────────────────────
        st.markdown("##### " + t("shift.write_header"))
        _note = st.text_area(t("shift.note_label"), key="sh_note", height=120,
                             placeholder=t("shift.note_ph"))
        # ⚠ 인수인계서 **본문**은 번역 대상이 아니다 — 저장·다운로드되어 조직에
        #   남는 산출물이라, 화면 언어를 바꿨다고 문서 언어까지 따라가면
        #   "영어로 보다가 저장했더니 영문 인계서"가 된다.
        _md = osh.handover_markdown(_sum, author=_reviewer, note=_note)

        h1, h2, h3 = st.columns([1.2, 1.2, 2])
        if h1.button(t("shift.save"), key="sh_save", type="primary", width="stretch"):
            ok, msg = osh.save_handover(DB, _reviewer, _note, _sh_hours, _md)
            if ok:
                st.session_state.pop("sh_note", None)
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)
        h2.download_button(t("shift.download"), _md.encode("utf-8-sig"),
                           file_name=f"handover_{time.strftime('%Y%m%d_%H%M')}.md",
                           mime="text/markdown", key="sh_dl", width="stretch")
        h3.caption(t("shift.author_note", who=_reviewer))

        with st.expander(t("shift.preview"), expanded=False):
            st.markdown(_md)


# ══════════════════════════════════════════════════════════
# 탭 4 — 🗃 탐지 로그 (당시 데이터 + 당시 분석 결과)
# ══════════════════════════════════════════════════════════
with TAB_LOG:
    if astore is None:
        st.error(t("log.no_astore"))
    else:
        _cs = astore.stats(DB)
        lg1, lg2, lg3 = st.columns([2, 1, 1])
        with lg1:
            q = st.text_input(t("log.search"), key="log_q",
                              placeholder=t("log.search_ph"),
                              help=t("log.search_help"))
        with lg2:
            lg_n = st.select_slider(t("log.n"), [25, 50, 100, 200], value=50, key="log_n")
        with lg3:
            lg_anom = st.toggle(t("log.anomaly_only"), value=True, key="log_anom")

        if _cs["rows"] == 0:
            # 🐛 FIX: 예전에는 rows==0 이면 무조건 "훅이 안 붙었다"고 단정했다.
            #   실제로는 훅이 멀쩡히 붙어 있어도 **탐지된 이상거래가 아직 없으면**
            #   0건이다(attach 는 is_anomaly=True 인 건만 캐시한다). 멀쩡한 설정을
            #   두고 워처를 고치라고 안내하는 오진이었다.
            #
            #   구분 기준: attach() 는 부착 시점에 ensure_schema() 를 부른다.
            #   반대로 읽기 경로(stats/log_rows)는 테이블을 만들지 않는다.
            #   → 테이블이 있다 = 훅이 최소 한 번은 돌았다.
            if astore.table_exists(DB):
                st.info(t("log.cache_ok"))
            else:
                st.warning(f"{t('log.hook_missing')}\n\n" + t("log.hook_snippet"))
        else:
            st.caption(t("log.cache_stat", label=t("log.cache_size"),
                         rows=f"{_cs['rows']:,}", txns=f"{_cs['txns']:,}",
                         mb=_cs["stored_mb"], raw=_cs["raw_mb"], ratio=_cs["ratio"],
                         a=_cs["oldest"], b=_cs["newest"]))

        # ── 🔔 경보 카드·데스크톱 알림에서 넘어온 거래 ──────────
        #   카드는 `?goto=<txn>&gototab=log` 로 이 탭을 연다. 예전에는 탭만
        #   바뀌고 **그 거래가 선택되지 않아** 담당자가 표에서 손으로 찾아야 했다
        #   (JUMP_TXN 을 트리아지·AI 탭만 소비하고 여기는 읽지 않았다).
        #   사용설명서는 "카드 클릭 → 그 거래의 당시 데이터·분석"이라고 안내한다.
        #
        #   포커스를 세션에 담아 두는 이유: JUMP_TXN 은 첫 런에서 소비되므로,
        #   필터를 한 번만 건드려도 상세가 닫혀 버린다. 사용자가 표에서 다른 행을
        #   직접 고를 때까지 유지한다.
        if JUMP_TXN:
            st.session_state["log_focus"] = JUMP_TXN
        _focus = st.session_state.get("log_focus")
        if _focus:
            fc1, fc2 = st.columns([4, 1], vertical_alignment="center")
            fc1.info(t("log.focus_note", tid=_focus))
            if fc2.button(t("log.focus_clear"), key="log_focus_clear", width="stretch"):
                st.session_state.pop("log_focus", None)
                st.rerun()

        # 검색어·이상거래 필터는 **SQL 에서** 건다. 뽑아 놓고 파이썬에서 거르면
        #   '건수 50' 이 '50건을 뽑아 그중 남은 것'이 되어, 이상거래만 켰을 때
        #   화면에 4행만 뜨고 검색은 최근 50건 안에서만 매치했다.
        _qs = (q or "").strip()
        rows = oq.alert_queue(DB, limit=int(lg_n), min_score=-1.0,
                              only_unreviewed=False, txn_like=_qs or None,
                              only_anomaly=bool(lg_anom))
        if _qs:
            st.caption(t("log.search_result", q=_qs, n=len(rows), cap=int(lg_n)))

        # 검색 중에는 알림 포커스를 끌어올리지 않는다 — 검색 결과에 해당하지 않는
        #   거래가 맨 위에 끼면 '내가 찾은 것'과 섞여 혼란스럽다.
        #   포커스 자체는 지우지 않으므로 검색어를 비우면 다시 열린다.
        if _focus and _qs:
            _focus = None

        if _focus:
            # 필터(이상거래만·검색어)나 표시 건수에 걸려 안 보일 수 있다.
            #   눌렀는데 빈 화면이 나오는 것이 최악이므로 강제로 끌어올린다.
            _hit = [r for r in rows if r["txn_id"] == _focus]
            if not _hit:
                _wide = oq.alert_queue(DB, limit=500, min_score=-1.0,
                                       only_unreviewed=False)
                _hit = [r for r in _wide if r["txn_id"] == _focus]
                if not _hit:
                    st.warning(t("log.focus_missing", tid=_focus))
            rows = _hit + [r for r in rows if r["txn_id"] != _focus]

        cached = astore.cached_ids(DB, [r["txn_id"] for r in rows])
        verdicts = rs.current(DB, [r["txn_id"] for r in rows])

        if not rows:
            st.info(t("common.none"))
        else:
            st.caption(t("log.pick"))
            table = []
            for r in rows:
                v = verdicts.get(r["txn_id"])
                table.append({
                    "": "📼" if r["txn_id"] in cached else "",
                    t("log.col_txn"): r["txn_id"],
                    t("log.col_time"): r["시각"],
                    t("log.col_risk"): round(float(r["risk_score"] or 0), 4),
                    t("log.col_type"): ui.fraud_label(r["fraud_type"], LANG, short=True),
                    t("log.col_verdict"): _verdict_label(v["verdict"]) if v else "-",
                    t("log.col_source"): r.get("source") or "",
                })
            sel = st.dataframe(table, width="stretch", hide_index=True,
                               on_select="rerun", selection_mode="single-row",
                               key="log_table")
            idx = None
            try:
                picked = sel.selection.rows
                idx = picked[0] if picked else None
            except Exception:
                idx = None

            if idx is not None:
                # 사람이 표에서 직접 골랐다 → 알림 포커스는 역할을 다했다
                if _focus and rows[idx]["txn_id"] != _focus:
                    st.session_state.pop("log_focus", None)
            elif _focus:
                # 표 선택이 없으면 알림에서 넘어온 거래를 연다 (맨 위로 올려 뒀다)
                idx = next((i for i, r in enumerate(rows)
                            if r["txn_id"] == _focus), None)

            if idx is not None and idx < len(rows):
                r = rows[idx]
                tid = r["txn_id"]
                st.markdown("---")
                st.markdown(f"### `{tid}`")

                cache = astore.load(DB, tid)
                h1, h2, h3, h4 = st.columns(4)
                h1.metric(t("log.m_risk"), f"{float(r['risk_score'] or 0):.4f}")
                h2.metric(t("log.col_type"),
                          ui.fraud_label(r["fraud_type"], LANG, short=True))
                h3.metric(t("log.m_tier"), (cache or {}).get("tier") or "-")
                _v = verdicts.get(tid)
                h4.metric(t("log.col_verdict"),
                          _verdict_label(_v["verdict"]) if _v else t("log.unreviewed"))

                if not cache:
                    st.warning(f"**{t('log.nocache')}**\n\n{t('log.nocache_why')}")

                dtabs = st.tabs([t("log.tab_data"), t("log.tab_llm"),
                                 t("log.tab_proba"), t("log.tab_sent"),
                                 t("log.tab_env"), t("log.verdict_hist")])

                # 📄 당시 데이터
                with dtabs[0]:
                    data = (cache or {}).get("row") or {}
                    if not data and rc:
                        data = rc.safe_view(rc.load_stored_features(DB, tid),
                                            st.session_state["pii_level"])
                        if data:
                            st.caption(t("log.from_rawjson"))
                    if data:
                        st.dataframe([{t("log.col_field"): k, t("log.col_value"): str(v)}
                                      for k, v in data.items()],
                                     width="stretch", hide_index=True, height=340)
                    else:
                        st.caption(t("common.none"))

                # 🧠 LLM 분석
                with dtabs[1]:
                    llm = (cache or {}).get("llm") or {}
                    if llm.get("analysis"):
                        st.markdown(llm["analysis"])
                        if llm.get("ctx"):
                            with st.expander(t("log.rag_docs")):
                                st.json(llm["ctx"], expanded=False)
                    elif cache:
                        st.caption(t("log.no_llm"))
                        for e in (cache.get("errors") or []):
                            st.caption(f"• {e}")
                    else:
                        st.caption(t("log.nocache"))

                # 📊 확률 분포
                with dtabs[2]:
                    proba = (cache or {}).get("proba") or {}
                    if proba:
                        import plotly.graph_objects as go
                        items = sorted(proba.items(), key=lambda kv: -kv[1])[:8]
                        fig = go.Figure(go.Bar(
                            x=[v for _, v in items][::-1],
                            y=[ui.fraud_label(k, LANG, short=True) for k, _ in items][::-1],
                            orientation="h", marker_color=T["accent"]))
                        fig.update_layout(height=260, **ui.plotly_layout(T))
                        st.plotly_chart(fig, width="stretch")
                        st.caption(t("log.proba_note"))
                    else:
                        st.caption(t("log.nocache"))

                # 📨 발송 내역
                with dtabs[3]:
                    nt = (cache or {}).get("notify") or {}
                    llm = (cache or {}).get("llm") or {}
                    if nt:
                        st.markdown(t(
                            "log.sent_summary", tier=nt.get("tier"),
                            slack=t("log.sent_yes") if nt.get("slack") else "—",
                            email=t("log.sent_yes") if nt.get("email") else "—",
                            dedup=t("log.dedup_yes") if nt.get("deduped")
                            else t("log.dedup_no")))
                    if llm.get("slack"):
                        with st.expander(t("log.slack_body"), expanded=True):
                            st.code(llm["slack"], language="text")
                    if llm.get("email"):
                        with st.expander(t("log.email_body")):
                            st.markdown(llm["email"])
                    if not nt and not llm:
                        st.caption(t("log.nocache"))

                # ⚙ 당시 환경
                with dtabs[4]:
                    if cache:
                        _K, _V = t("log.col_item"), t("log.col_value")
                        st.dataframe([
                            {_K: t("log.env_captured"), _V: cache.get("captured_at")},
                            {_K: t("log.env_model"), _V: cache.get("model")},
                            {_K: t("log.env_th"),
                             _V: f"{cache.get('th_review')} / {cache.get('th_confirm')}"},
                            {_K: t("log.env_pii"), _V: cache.get("pii_level")},
                            {_K: "LLM", _V: f"{cache.get('llm_provider')} / "
                                            f"{cache.get('llm_model')}"},
                            {_K: t("log.env_llm_used"),
                             _V: t("log.yes") if cache.get("llm_used") else t("log.no")},
                            {_K: t("log.env_elapsed"),
                             _V: t("log.seconds", n=f"{cache.get('elapsed') or 0:.2f}")},
                            {_K: t("log.env_errors"), _V: cache.get("n_errors")},
                            {_K: t("log.env_source"), _V: cache.get("source")},
                        ], width="stretch", hide_index=True)
                        st.caption(t("log.th_hotreload"))
                        hist = astore.history(DB, tid)
                        if len(hist) > 1:
                            st.caption(t("log.reanalyzed", n=len(hist)))
                    else:
                        st.caption(t("log.nocache"))

                # 판정 이력
                with dtabs[5]:
                    vh = rs.history(DB, tid)
                    if vh:
                        st.dataframe([{
                            t("log.col_reviewed_at"): x["reviewed_at"],
                            t("log.col_verdict"): _verdict_label(x["verdict"]),
                            t("log.col_reason"): (ui.reason_label(x["reason"], LANG)
                                                  if x["reason"] else ""),
                            t("log.col_reviewer"): x["reviewer"],
                            t("log.col_memo"): x["memo"] or "",
                            t("log.col_score_then"): x["risk_score"],
                        } for x in vh], width="stretch", hide_index=True)
                    else:
                        st.caption(t("log.no_history"))
                    st.markdown("---")
                    qv1, qv2, qv3 = st.columns(3)
                    for _c, _vd in ((qv1, "tp"), (qv2, "fp"), (qv3, "unclear")):
                        if _c.button(t(f"tri.{_vd}"), key=f"logv_{tid}_{_vd}",
                                     width="stretch"):
                            ok, msg = rs.record(
                                DB, tid, _vd, reviewer=st.session_state["reviewer"],
                                snapshot={"alert_ref": r.get("alert_ref"),
                                          "risk_score": r.get("risk_score"),
                                          "fraud_type": r.get("fraud_type"),
                                          "tier": (cache or {}).get("tier"),
                                          "th_review": (cache or {}).get("th_review"),
                                          "th_confirm": (cache or {}).get("th_confirm")},
                                source="ops_log")
                            (st.success if ok else st.error)(msg)
                            if ok:
                                st.rerun()

        with st.expander(f"🧹 {t('log.prune')}"):
            st.caption(t("log.prune_note"))
            pk1, pk2 = st.columns([2, 1])
            keep_d = pk1.number_input(t("log.prune_days"), 7, 3650, 180, key="prune_days")
            keep_r = pk1.toggle(t("log.prune_keep"), value=True, key="prune_keep")
            if pk2.button(t("log.prune_go"), key="prune_go"):
                n, msg = astore.prune(DB, int(keep_d), bool(keep_r))
                st.success(msg)


# ══════════════════════════════════════════════════════════
# 탭 5 — 📉 오탐 분석 (무엇이 헛 알람이었나)
# ══════════════════════════════════════════════════════════
with TAB_FP:
    win = st.select_slider(t("common.window"), [24, 72, 168, 720, 2160],
                           key="window_h",
                           format_func=lambda h: (t("common.days", n=h // 24) if h >= 24
                                                  else t("common.hours", n=h)))
    cov = oq.coverage(DB, since_hours=int(win))
    # ⚠ cov 의 키('알림'/'판정'/…)는 ops_queries 가 돌려주는 **데이터 키**다.
    #   화면 라벨만 번역하고 키는 그대로 둔다.
    _kpi_row([
        (t("fp.kpi_alerts"), f"{cov['알림']:,}", None),
        (t("fp.kpi_judged"), f"{cov['판정']:,}", None),
        (t("fp.coverage"),
         f"{cov['커버리지']}%" if cov["커버리지"] is not None else "-",
         t(f"fp.conf_{cov['신뢰도']}")),
        (t("fp.rate"), f"{cov['오탐률']}%" if cov["오탐률"] is not None else "-", None),
    ])
    if cov.get("_note"):
        st.warning(t("fp.cov_warn"))

    tl = oq.fp_timeline(DB, "day", since_hours=int(win))
    if not tl:
        st.info(t("fp.no_data"))
    else:
        import pandas as pd
        import plotly.graph_objects as go
        df = pd.DataFrame(tl)
        fig = go.Figure()
        fig.add_bar(x=df["구간"], y=df["정탐"], name=t("tri.tp"),
                    marker_color=T["green"])
        fig.add_bar(x=df["구간"], y=df["오탐"], name=t("tri.fp"),
                    marker_color=T["amber"])
        fig.add_scatter(x=df["구간"], y=df["오탐률"], name=t("fp.rate"),
                        yaxis="y2", mode="lines+markers", line={"color": T["red"]})
        fig.update_layout(barmode="stack", yaxis2={"overlaying": "y", "side": "right",
                                                   "range": [0, 100], "showgrid": False},
                          **ui.plotly_layout(T))
        fig.update_layout(title=t("fp.timeline"))
        st.plotly_chart(fig, width="stretch")

        c1, c2 = st.columns(2)
        with c1:
            st.markdown(f"##### {t('fp.by_dim')}")
            dim = st.selectbox(t("fp.dim_label"), ["fraud_type", "score_bucket", "tier",
                                                   "model", "reviewer"], key="fp_dim")
            rows = oq.fp_by_dimension(DB, dim, since_hours=int(win))
            if dim == "fraud_type":
                for x in rows:
                    x["구분"] = ui.fraud_label(x["구분"], LANG, short=True)
            st.dataframe(rows, width="stretch", hide_index=True)
        with c2:
            st.markdown(f"##### {t('fp.reasons')}")
            rr = rs.reason_counts(DB, since_hours=int(win))
            for x in rr:
                x["사유"] = ui.reason_label(x["사유코드"], LANG)
            st.dataframe([{k: v for k, v in x.items() if k != "사유코드"} for x in rr],
                         width="stretch", hide_index=True)

    # ══════════════════════════════════════════════════════════
    # 🔴 미탐(FN) 등록 — 피드백 루프의 빠진 반쪽
    #
    #   트리아지 큐는 **알림이 나간 건**만 담는다. 그런데 진짜 미탐은 정의상
    #   알림이 안 나간 거래다 — 고객 민원·사고 접수로 뒤늦게 알게 된다.
    #   그래서 지금까지 verdict 'fn' 은 목록에 있어도 **입력할 창구가 없었고**,
    #   집계·교대 요약의 '미탐' 칸은 영원히 0이었다.
    #   여기서 거래 ID로 직접 등록한다.
    # ══════════════════════════════════════════════════════════
    _fn_cnt = rs.counts(DB, since_hours=int(win)).get("fn", 0)
    with st.expander(t("fn.title", d=int(win) // 24, n=_fn_cnt)):
        st.caption(t("fn.desc"))
        _fn_tid = st.text_input(t("fn.txn_label"), key="fn_tid",
                                placeholder=t("fn.txn_ph")).strip()

        _fn_hit = None
        if _fn_tid:
            try:
                _cands = oq.alert_queue(DB, limit=20, min_score=-1.0,
                                        only_unreviewed=False, txn_like=_fn_tid,
                                        only_anomaly=False)
                _fn_hit = next((r for r in _cands if r["txn_id"] == _fn_tid), None)
            except Exception as e:                     # pragma: no cover
                st.caption(t("fn.lookup_fail", e=e))

            if _fn_hit:
                _fs = float(_fn_hit.get("risk_score") or 0)
                _thr_now, _ = _tier_th()
                st.success(t("fn.found", score=f"{_fs:.4f}",
                             ftype=ui.fraud_label(_fn_hit.get("fraud_type"),
                                                  LANG, short=True),
                             ts=_fn_hit.get("시각", "")))
                if _fs < _thr_now:
                    st.info(t("fn.below_th", score=f"{_fs:.4f}", thr=f"{_thr_now:g}"))
            else:
                st.warning(t("fn.not_found"))

        _fn_memo = st.text_area(t("fn.memo_label"), key="fn_memo", height=80,
                                placeholder=t("fn.memo_ph"))
        st.caption(t("fn.memo_warn"))

        if st.button(t("fn.save"), key="fn_save", type="primary",
                     disabled=not _fn_tid):
            _snap = {}
            if _fn_hit:
                _thr_s, _thc_s = _tier_th()
                _snap = {"alert_ref": _fn_hit.get("alert_ref"),
                         "risk_score": _fn_hit.get("risk_score"),
                         "fraud_type": _fn_hit.get("fraud_type"),
                         "model": _fn_hit.get("model"),
                         "tier": "none",       # 알림이 안 나간 건이다
                         "th_review": _thr_s, "th_confirm": _thc_s}
            ok, msg = rs.record(DB, _fn_tid, "fn", memo=_fn_memo or None,
                                reviewer=st.session_state["reviewer"],
                                snapshot=_snap, source="ops_fn_manual")
            (st.success if ok else st.error)(msg)
            if ok:
                for _k in ("fn_tid", "fn_memo"):
                    st.session_state.pop(_k, None)
                st.rerun()

        st.caption(t("fn.scope_note"))

    with st.expander(t("fp.export")):
        st.caption(t("fp.export_note"))
        if st.button(t("fp.export_go")):
            import json
            data = rs.export_training_labels(DB)
            st.download_button(t("fp.export_dl", n=len(data)),
                               json.dumps(data, ensure_ascii=False, indent=2),
                               file_name=f"fp_labels_{time.strftime('%Y%m%d')}.json",
                               mime="application/json")


# ══════════════════════════════════════════════════════════
# 탭 6 — ⚙ 임계값 튜닝 (⑤의 결론을 숫자로)
# ══════════════════════════════════════════════════════════
with TAB_TUNE:
    st.markdown(f"##### {t('th.title')}")
    st.caption(t("th.desc"))

    # ── 임계값 3종 대조표 ──────────────────────────────────
    #   이 탭은 셋 중 ①(워처 경보 등급)만 바꾼다. 나머지 둘은 사이드바 소관인데,
    #   이름이 전부 th_review/th_confirm 이라 "여기서 적용했는데 왜 안 바뀌지"가
    #   반복됐다. 손대기 전에 지금 값 셋을 나란히 보여준다.
    _wc_now = _cfg()
    st.markdown(ui.threshold_matrix(
        watcher=(_wc_now.get("th_review"), _wc_now.get("th_confirm")),
        detect=CFG["threshold"],
        dispatch=(CFG["th_review"], CFG["th_confirm"]), dual=CFG["dual"]),
        unsafe_allow_html=True)

    cc1, cc2 = st.columns(2)
    fp_cost = cc1.number_input(t("th.fp_cost"), min_value=0, max_value=100_000_000,
                               step=10_000, key="fp_cost")
    fn_cost = cc2.number_input(t("th.fn_cost"), min_value=0, max_value=1_000_000_000,
                               step=100_000, key="fn_cost")

    w = oq.threshold_whatif(DB, fp_cost=float(fp_cost), fn_cost=float(fn_cost))
    if not w["rows"]:
        st.info(w["warning"] or t("fp.no_data"))
    else:
        import pandas as pd
        import plotly.graph_objects as go
        df = pd.DataFrame(w["rows"])
        ok_df = df[df["신뢰가능"]]
        st.caption(t("th.sample_n", n=w["n_judged"]))
        if w["warning"]:
            st.warning(t("th.bias"))

        # ── 🔴 미탐 반영 곡선 (선택) ─────────────────────────
        #   기존 곡선을 **덮어쓰지 않는다.** oq.threshold_whatif_fn 은 별도 함수이고
        #   여기서도 겹쳐 그리기만 한다 — 추천 슬라이더는 계속 기존 곡선을 따른다.
        #   숫자를 조용히 바꿔치기하면 "어제 본 추천치와 오늘이 다른데 왜인지 모르는"
        #   상태가 되고, 그건 임계값 도구가 절대 만들면 안 되는 상태다.
        _fn_on = st.toggle(t("th.fn_toggle"), key="th_use_fn",
                           help=t("th.fn_toggle_help"))
        _wf = None
        if _fn_on:
            _wf = oq.threshold_whatif_fn(DB, fp_cost=float(fp_cost),
                                         fn_cost=float(fn_cost))
            if not _wf["n_fn"]:
                st.caption(t("th.fn_none"))
                _wf = None

        fig = go.Figure()
        # 신뢰 불가 구간은 회색 점선 — 그리되 '이건 근거 없음'이 보이게
        fig.add_scatter(x=df["임계값"], y=df["기대비용"], mode="lines",
                        name=t("th.series_unknown"),
                        line={"color": T["text_muted"], "dash": "dot"})
        fig.add_scatter(x=ok_df["임계값"], y=ok_df["기대비용"], mode="lines+markers",
                        name=t("th.series_cost"), line={"color": T["accent"], "width": 3})
        if w["valid_from"] is not None:
            fig.add_vline(x=w["valid_from"], line_dash="dash",
                          line_color=T["red"], annotation_text=t("th.vline_border"))
        if len(ok_df):
            best = ok_df.loc[ok_df["기대비용"].idxmin()]
            fig.add_vline(x=float(best["임계값"]), line_color=T["green"],
                          annotation_text=t("th.vline_min", v=f"{best['임계값']:.2f}"))
        if _wf:
            _fdf = pd.DataFrame(_wf["rows"])
            _fok = _fdf[_fdf["신뢰가능"]]
            fig.add_scatter(x=_fdf["임계값"], y=_fdf["기대비용"], mode="lines",
                            name=t("th.fn_series"),
                            line={"color": T["red"], "width": 2, "dash": "dash"})
            if len(_fok):
                _fbest = _fok.loc[_fok["기대비용"].idxmin()]
                fig.add_vline(x=float(_fbest["임계값"]), line_dash="dot",
                              line_color=T["red"],
                              annotation_text=t("th.fn_vline",
                                                v=f"{_fbest['임계값']:.2f}"))
        fig.update_layout(title=t("th.chart_title"), **ui.plotly_layout(T))
        st.plotly_chart(fig, width="stretch")

        if _wf:
            _fok = pd.DataFrame(_wf["rows"])
            _fok = _fok[_fok["신뢰가능"]]
            if len(_fok) and len(ok_df):
                st.markdown(t(
                    "th.fn_summary", n=_wf["n_fn"] - _wf["n_fn_unscored"],
                    a=f"{float(ok_df.loc[ok_df['기대비용'].idxmin()]['임계값']):.2f}",
                    b=f"{float(_fok.loc[_fok['기대비용'].idxmin()]['임계값']):.2f}"))
            if _wf["n_fn_unscored"]:
                st.caption(t("th.fn_unscored", n=_wf["n_fn_unscored"]))
            st.info(t("th.fn_howto"))

        st.dataframe(_fdf if _wf else df, width="stretch", hide_index=True)

        if wcfg and len(ok_df):
            best_th = float(ok_df.loc[ok_df["기대비용"].idxmin()]["임계값"])
            st.markdown("---")

            # 지금 워처가 실제로 쓰는 값. 이 파일은 **핫 리로드**되므로 저장하는
            #   순간 무인 워처의 경보 기준이 바뀐다(재시작이 필요 없다).
            try:
                _cur_thr = float(_wc_now.get("th_review"))
            except (TypeError, ValueError):
                _cur_thr = None

            # ── 값 입력: 슬라이더(대략) + 숫자(정확) ──────────
            #   ⚠ 슬라이더 하나만 두면 안 된다. step=0.01 격자는 **0.005 를 아예
            #     표현하지 못하는데**, 지금 운영값이 정확히 0.005 다. 슬라이더만
            #     있으면 현재 값을 다시 적용하는 것조차 불가능하고, 0.01 로 올려
            #     저장하면 소리 없이 2배로 바뀐다.
            #   그래서 **숫자 입력이 원본**이고, 슬라이더는 '이 근처'를 잡는
            #   보조 도구다. 아래 new_th 는 반드시 숫자 쪽에서 읽는다.
            _sync_widget("apply_thr_num", best_th)     # 추천치가 바뀌면 따라간다
            if "apply_thr" not in st.session_state:
                st.session_state["apply_thr"] = round(
                    float(st.session_state["apply_thr_num"]), 2)

            def _thr_from_slider():
                # 슬라이더를 움직였다 = 정밀값도 그 눈금으로 간다
                st.session_state["apply_thr_num"] = float(st.session_state["apply_thr"])

            def _thr_from_num():
                _v = min(1.0, max(0.0, float(st.session_state["apply_thr_num"] or 0.0)))
                st.session_state["apply_thr_num"] = _v
                # 슬라이더는 가장 가까운 눈금까지만 따라온다(0.005 → 0.01 로 보임).
                #   적용값은 어디까지나 숫자 쪽이라 정밀도는 잃지 않는다.
                st.session_state["apply_thr"] = round(_v, 2)

            a1, a2, a3 = st.columns([2, 1, 1], vertical_alignment="bottom")
            a1.slider(t("th.apply_label"), 0.0, 1.0, step=0.01,
                      key="apply_thr", on_change=_thr_from_slider,
                      help=t("th.apply_help"))
            a2.number_input(t("th.exact"), 0.0, 1.0, step=0.001, format="%.4f",
                            key="apply_thr_num", on_change=_thr_from_num,
                            help=t("th.exact_help"))
            new_th = float(st.session_state["apply_thr_num"])

            _same = (_cur_thr is not None and abs(new_th - _cur_thr) < 1e-9)
            if a3.button(t("th.apply"), type="primary", width="stretch",
                         disabled=_same, help=t("th.apply_help_btn")):
                st.session_state["_th_apply_pending"] = float(new_th)
                st.rerun()
            if _same:
                a3.caption(t("th.same_as_now"))
            elif abs(new_th - round(new_th, 2)) > 1e-9:
                a3.caption(t("th.precise_note", v=f"{new_th:g}"))

            # ══════════════════════════════════════════════════
            # ✋ 적용 전 확인 — 되돌릴 수 없는 동작이다
            #
            #   watcher_config.json 저장 = 무인 워처의 경보 기준 즉시 변경이다.
            #   그런데 지금까지는 클릭 **한 번**이었고, 슬라이더는 비용을 만질
            #   때마다 최소비용 지점으로 저 혼자 움직인다(_sync_widget) —
            #   "숫자 구경하다 실수로 운영 정책을 바꾸는" 경로가 열려 있었다.
            #   무엇이 어떻게 바뀌고 알림량이 어떻게 될지 보여준 뒤 한 번 더 받는다.
            # ══════════════════════════════════════════════════
            _pend = st.session_state.get("_th_apply_pending")
            if _pend is not None:
                with st.container(border=True):
                    st.markdown("###### " + t("th.confirm_title"))

                    # 그리드(0.05 간격)에 스냅하면 현재값 0.005 같은 설정이
                    #   0.05 로 뭉개져 "안 바뀐다"는 오해를 준다. 두 지점을
                    #   **정확히** 다시 계산해 나란히 놓는다.
                    _pts = sorted({round(float(_pend), 4)}
                                  | ({round(_cur_thr, 4)} if _cur_thr is not None
                                     else set()))
                    _w2 = oq.threshold_whatif(DB, grid=_pts,
                                              fp_cost=float(fp_cost),
                                              fn_cost=float(fn_cost))
                    _at = {r["임계값"]: r for r in _w2["rows"]}
                    _rc = _at.get(round(_cur_thr, 4)) if _cur_thr is not None else None
                    _rn = _at.get(round(float(_pend), 4))

                    st.markdown(
                        t("th.confirm_change",
                          old=_cur_thr if _cur_thr is not None else "?", new=_pend),
                        unsafe_allow_html=True)

                    if _rc and _rn:
                        # 표시 컬럼만 번역한다 — _rc/_rn 의 키는 ops_queries 가
                        #   돌려주는 **데이터 키**라 손대면 조회가 깨진다.
                        def _cmp_row(_r, _kind):
                            return {t("th.col_kind"): _kind,
                                    t("th.col_threshold"): _r["임계값"],
                                    t("th.col_alerts"): _r["알림건수"],
                                    t("shift.col_tp"): _r["정탐"],
                                    t("shift.col_fp"): _r["오탐"],
                                    t("th.col_missed"): _r["놓친사기"],
                                    t("th.col_fp_rate"): _r["오탐률"],
                                    t("th.col_cost"): _r["기대비용"]}
                        st.dataframe([_cmp_row(_rc, t("th.row_now")),
                                      _cmp_row(_rn, t("th.row_after"))],
                                     width="stretch", hide_index=True)
                        _d_alert = (_rn["알림건수"] or 0) - (_rc["알림건수"] or 0)
                        _d_miss = (_rn["놓친사기"] or 0) - (_rc["놓친사기"] or 0)
                        st.caption(t("th.confirm_delta", n=_w2["n_judged"],
                                     da=_d_alert, dm=_d_miss))

                    # ① 근거 없는 구간으로 내리는 경우 — 가장 위험한 방향이다
                    if w["valid_from"] is not None and float(_pend) < w["valid_from"]:
                        st.error(t("th.below_valid", v=f"{w['valid_from']:.2f}"))

                    # ② 기존 결정 근거(_note)가 있으면 반드시 보여준다.
                    #    이 값은 팀이 비용분석으로 정해 둔 것일 수 있고, 그 맥락을
                    #    모른 채 덮어쓰면 되돌릴 근거까지 함께 사라진다.
                    _note = (_wc_now.get("_note") or "").strip()
                    if _note:
                        st.warning(t("th.prev_rationale", note=_note,
                                     who=_wc_now.get("_changed_by", "?"),
                                     when=_wc_now.get("_changed_at", "?")))

                    st.caption(t("th.hot_reload"))

                    y1, y2 = st.columns([1.4, 1])
                    if y1.button(t("th.confirm_go"), key="th_apply_confirm",
                                 type="primary", width="stretch"):
                        cur = wcfg.load()
                        cur["th_review"] = float(_pend)
                        ok, msg = wcfg.save(cur, meta={
                            "changed_by": st.session_state["reviewer"],
                            "changed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                            "reason": f"ops_dashboard 시뮬레이터 — 판정 {w['n_judged']}건 기반 "
                                      f"(이전 {_cur_thr} → {_pend})"})
                        st.session_state.pop("_th_apply_pending", None)
                        (st.success if ok else st.error)(
                            f"{msg}\n\n{t('th.applied')}" if ok else msg)
                        if ok:
                            st.rerun()
                    if y2.button(t("common.cancel"), key="th_apply_cancel", width="stretch"):
                        st.session_state.pop("_th_apply_pending", None)
                        st.rerun()


# ══════════════════════════════════════════════════════════
# 탭 7 — 🧠 AI 분석 · 알림 (dashboard.py 세션5 이식 + 라이브 데이터 재배선)
# ══════════════════════════════════════════════════════════
with TAB_AI:
    st.markdown(f"##### {t('ai.title')}")
    st.caption(t("ai.desc"))

    # ⚙ LLM 제공자 · API 키 · 알림 채널은 **사이드바**로 이주했다(ops_sidebar.py).
    #   같은 값을 두 곳에서 고칠 수 있으면 반드시 어긋나기 때문 — 위젯 key(ai_*)는
    #   그대로라 아래 본문 코드는 한 줄도 바꿀 필요가 없다.
    _prov_now = st.session_state.get("ai_llm_provider", "local")
    st.caption(t("ai.provider_now", prov=_prov_now, k=CFG["rag_k"]))

    # ── 작업 서브탭을 **먼저** 만든다 ───────────────────────
    #   st.tabs 는 호출한 자리에 컨테이너를 박고, 나중에 `with AI_SUB[i]:` 로 채워도
    #   내용은 그 자리에 들어간다. 그래서 생성만 위로 올리면 아래 편집기 코드는
    #   한 줄도 안 옮기고 화면 순서만 뒤집을 수 있다.
    #   왜 뒤집나: 이 탭을 여는 이유는 거의 항상 '탐지·분석'인데, 지금까지는
    #   프롬프트/RAG 편집기(설정에 가까운 도구)가 화면 맨 위를 차지해
    #   정작 할 일이 스크롤 아래에 있었다. 사이드바에서 고친 것과 같은 문제다.
    AI_SUB = st.tabs([t("ai.sub_detect"), t("ai.sub_single"),
                      t("ai.sub_batch"), t("ai.sub_chat")])

    # ── 🖊 프롬프트 · 📚 RAG 편집기는 **사이드바**로 이주했다 ─────
    #   여기는 '작업대'인데 설정 도구가 맨 위를 차지해, 탭을 여는 이유(탐지·분석)가
    #   스크롤 아래로 밀려 있었다. 임계값·모델·LLM과 같은 층(사이드바 ③)으로 옮겼다.
    #   위젯 key(prompt_ov_* / prompt_ta_*)는 그대로라 저장된 프롬프트는 유지된다.
    st.caption(t("ai.editors_moved"))

    # ── 서브탭 0: 탐지 입력 (세션5 5종 입력모드 이식) ─────
    #   dashboard.py 세션4/5가 쓰던 실제 ML 분류기(pipeline.detect_io)를 그대로 가져왔다.
    #   ops가 지금까지는 '이미 판정된' 알림만 다뤘는데, 이 탭은 반대로 '아직 판정되지
    #   않은' 임의의 거래(직접입력/CSV/합성/폴더)를 그 자리에서 즉시 탐지한다 —
    #   시연·what-if 조사·CSV로 받은 리스트 확인에 쓴다. 탐지 결과는 detections
    #   테이블에 그대로 적재되어 '탐지 로그' 탭에서도 보인다.
    with AI_SUB[0]:
        from pipeline import detect_io as dio

        # 모델·임계값은 **사이드바가 단일 출처**다. 예전에는 이 탭에 자체 셀렉터가
        #   있고 임계값은 워처 설정(th_review)을 읽어, 담당자가 사이드바에서 바꾼 값과
        #   여기 탐지 결과가 어긋났다. 이제 둘 다 사이드바를 따른다.
        avail_models = CFG["model"]["models"] or dio.get_available_models()
        sel_model = SEL_MODEL or dio.default_model_name(avail_models)
        _mpath = SEL_MODEL_P or avail_models.get(sel_model, {}).get("path", "models/lgbm_fds.pkl")
        _th = float(THRESHOLD)
        # ── 입력 6종 + 액션 바 → pipeline/detect_workbench.py (v26 이관) ──
        #   여기 있던 385줄은 dashboard.py 세션5에도 거의 같은 코드로 복사돼 있었다.
        #   부품(detect_ui/detect_io)은 이미 공유했는데 **조립 계층**만 두 벌이라,
        #   한쪽만 고쳐지는 사고가 실제로 났다(프롬프트 편집기 value= 버그).
        #   그래서 '거래 1건 고르기'까지를 공용 모듈로 뽑았다.
        #
        #   ⚠ 뽑은 것은 **입력까지**다. 아래 탐지 실행·경보·LLM 분석·발송은 여기 남는다 —
        #     두 앱의 그 뒤 처리가 완전히 달라(ops 는 ops: 소스태그 원장 적재 + ops_alert,
        #     dashboard 는 자체 발송 경로) 합치면 콜백만 열 개가 붙는다.
        #   ⚠ key_prefix="det" 는 기존 위젯 key 를 **그대로 유지**하기 위한 것이다.
        #     바꾸면 사용자가 입력해 둔 값과 챗봇 액션(_force_det_tab)이 전부 끊긴다.
        def _handoff_batch(rows):
            """추출분을 '📦 배치 분석' 서브탭으로 넘긴다."""
            st.session_state['ai_batch_rows'] = rows
            st.session_state['ai_batch_go'] = True
            st.rerun()

        # ── ⚙ 탐지와 동시에 AI 분석 — **누르기 전에** 정하는 스위치 ──
        #   예전엔 이 토글이 결과 블록(`if is_anomaly:`) 안에 있었다. 그래서
        #     · 탐지를 실행하기 전에는 보이지 않고
        #     · 정상 판정이면 아예 나타나지 않으며
        #     · 이미 LLM 이 도는 것을 본 **뒤에야** 끌 수 있었다
        #   — 로컬 모델이 수십 초 걸리는 상황에서 '급하니 분석은 건너뛰자'를
        #   선택할 방법이 사실상 없었다. 실행 버튼과 같은 화면에 올린다.
        st.toggle(t("ai.auto_run"), key="ai_auto_run", help=t("ai.auto_run_help"))
        if not st.session_state.get("ai_auto_run", True):
            st.caption(t("ai.auto_run_off_note"))

        if dwb is None:                                # pragma: no cover
            st.error(t("ai.no_workbench"))
            row_to_predict = None
        else:
            row_to_predict = dwb.render_input_modes(
                t=t, lang=LANG, key_prefix="det",
                model_name=sel_model, model_path=_mpath, threshold=_th,
                dataset_name=SEL_DS, dataset_found=DS_FOUND,
                inbox_dir=st.session_state.get('watch_inbox') or 'inbox',
                fraud_label=ui.fraud_label,
                on_batch=_handoff_batch,
                tab_key="ops_det_tab",
                force_tab_key="_force_det_tab",
                pending_scope_key="_pending_scope",
            )

        # ── 탐지 실행 → ML 분류 + (설정에 따라) AI 분석 자동 실행 ──
        if row_to_predict is not None:
            with st.spinner(t("det.detecting")):
                try:
                    _b0 = {k: v for k, v in row_to_predict.items()
                          if not str(k).startswith('_') and k != 'Fraud_Type'}
                    clf, _mode, _use_clean = dio.resolve_classifier(_mpath, _b0)
                    fraud_type, risk_score, _proba = clf.predict(_b0 if _use_clean else row_to_predict)
                    is_anomaly = (fraud_type != 'm') or (risk_score >= _th)
                    # source 는 원장(transactions.input_mode)에 그대로 남는다 —
                    #   워처 건('watcher:파일명')과 이 화면에서 돌린 건을 나중에
                    #   구분할 수 있어야 통계에서 시연분을 걸러낼 수 있다.
                    _tid = dio.save_detection(
                        DB, row_to_predict, fraud_type, risk_score,
                        is_anomaly, sel_model, _th,
                        source=f"ops:{row_to_predict.get('_input_mode', 'manual')}")
                    _mode_code = _mode[0]
                    _mode_txt = {
                        "bundle": t("det.clf_bundle", n=_mode[1], shape=_mode[2]),
                        "encoded": t("det.clf_encoded"),
                        "bridge": t("det.clf_bridge", ck=_mode[1]),
                        "mlclf": t("det.clf_mlclf"),
                    }.get(_mode_code, _mode_code)
                    st.session_state['_det_last'] = {
                        'row': dict(row_to_predict), 'fraud_type': fraud_type,
                        'risk_score': float(risk_score), 'is_anomaly': bool(is_anomaly),
                        'txn_id': _tid, 'mode': _mode_txt,
                        # ✨ 확률 분포 보존 — detect_ui 의 확률 막대·차트가 이걸 쓴다.
                        #   예전엔 버리고 있어서 "왜 이 유형인가"를 화면에서 볼 수 없었다.
                        'proba_dict': dict(_proba) if isinstance(_proba, dict) else {},
                        'model': sel_model, 'threshold': _th,
                    }
                    # 🕘 세션 내 탐지 이력 — 임계값 재조정 시 과거 판정이
                    #   어떻게 뒤집히는지 보려면 원본 점수가 남아 있어야 한다
                    if dui:
                        dui.history_append(
                            st.session_state, txn_id=_tid, is_anomaly=is_anomaly,
                            fraud_type=fraud_type, risk_score=risk_score, threshold=_th,
                            input_mode=row_to_predict.get('_input_mode', '-'),
                            model=sel_model)
                    # 새 탐지 → 직전 AI 분석 결과는 무효 (다른 거래의 분석이 남지 않게)
                    st.session_state.pop('_det_ai_result', None)
                    # 📼 분석 캐시에도 남긴다 — 이래야 '🗃 탐지 로그'에서 이 건을
                    #   열었을 때 당시 확률분포·환경이 함께 보인다. 예전에는 AI 분석을
                    #   돌린 경우에만 저장돼, 수동 탐지는 로그에 목록만 뜨고 내용이 비었다.
                    #   (LLM 리포트는 분석을 돌린 뒤 같은 txn_id 로 덮어써 합류한다)
                    if astore and _tid:
                        try:
                            astore.save(DB, {
                                "txn_id": _tid, "fraud_type": fraud_type,
                                "risk_score": float(risk_score),
                                "is_anomaly": bool(is_anomaly),
                                "proba": dict(_proba) if isinstance(_proba, dict) else {},
                                "model": sel_model, "source": "ops_manual",
                                # 경보 등급은 워처 설정을 따른다(사이드바 발송 등급과 별개)
                                "tier": _tier_of(risk_score),
                                "llm_used": False, "errors": [],
                            }, row_to_predict)
                        except Exception as _ase:
                            log.debug(f"수동 탐지 캐시 저장 실패(무시): {_ase}")
                    # 🔔 수동 탐지도 경보를 울린다.
                    #   예전에는 워처가 DB에 넣은 건만 폴링으로 잡혀 경보가 났다.
                    #   이 탭에서 직접 돌린 탐지는 아무 소리도 안 나서, 시연·조사 중
                    #   이상거래를 놓치기 쉬웠다. 같은 등급 규칙(alarm_tier)을 따른다.
                    if is_anomaly:
                        st.session_state['_det_alert_pending'] = {
                            "txn_id": _tid or "MANUAL",
                            "risk_score": float(risk_score),
                            "fraud_type": fraud_type,
                            "tier": _tier_of(risk_score),
                            "시각": time.strftime("%Y-%m-%d %H:%M:%S"),
                            "source": "manual",
                        }
                except Exception as e:
                    st.session_state['_det_last'] = {'error': str(e)}

        _dlast = st.session_state.get('_det_last')
        if _dlast:
            if _dlast.get('error'):
                st.error(t("det.classify_fail", e=_dlast['error']))
            else:
                st.markdown(f"###### {t('det.result_title')}")
                if dui:
                    # 판정 배너 → 게이지+상세표 → 규칙 체크리스트 → 유형 카드 → 확률
                    #   dashboard.py 세션5와 **같은 함수**를 호출한다 (pipeline/detect_ui.py)
                    dui.detection_result(_dlast, _dlast.get('threshold', _th), T,
                                         lang=LANG, t=t, chart_height=200)
                else:                                  # pragma: no cover
                    _badge = t("det.anomaly") if _dlast['is_anomaly'] else t("det.normal")
                    dr1, dr2 = st.columns(2)
                    dr1.metric(_badge, ui.fraud_label(_dlast['fraud_type'], LANG, short=True))
                    dr2.metric("risk_score", f"{_dlast['risk_score']:.4f}")
                st.caption(_dlast.get('mode', ''))
                if _dlast.get('txn_id'):
                    st.caption(t("det.saved", tid=_dlast['txn_id']))

                # ── 🔔 수동 탐지 경보 발사 ────────────────────
                #   결과를 그린 **뒤에** 쏜다. 경보 카드는 화면 우상단 고정이라
                #   결과 렌더보다 먼저 쏘면 같은 rerun 안에서 스탬프가 소비돼 묻힌다.
                _dap = st.session_state.pop('_det_alert_pending', None)
                if _dap and oa and st.session_state.get("alarm_on"):
                    _want = st.session_state.get("alarm_tier", "confirm")
                    _rank = {"confirm": 2, "review": 1, "none": 0}
                    _need = {"confirm": 2, "review": 1, "all": 0}.get(_want, 2)
                    if _rank.get(_dap["tier"], 0) >= _need:
                        oa.fire(st.session_state, [_dap])
                        oa.render(st, [_dap], st.session_state, T, ui.fraud_label, LANG)
                    else:
                        st.caption(t("ai.alarm_skipped", tier=_want))

                # ── 🧠 AI 분석 ───────────────────────────────
                if _dlast['is_anomaly']:
                    # 토글은 탐지 입력 위로 올렸다 — 결과를 본 뒤가 아니라 **실행 전에**
                    #   정해야 의미가 있는 스위치이기 때문이다. 여기서는 값만 읽는다.
                    #   (같은 key 로 위젯을 두 번 만들면 DuplicateWidgetID 로 죽는다)
                    _auto = bool(st.session_state.get("ai_auto_run", True))
                    _already = (st.session_state.get('_det_ai_result') or {}).get('txn_id') \
                        == (_dlast.get('txn_id') or 'MANUAL')
                    _go_ai = (st.button("🧠 " + t("ai.run"), key="det_run_ai",
                                        type="secondary")
                              if not _auto else (_auto and not _already))
                    if _go_ai:
                        with st.spinner(t("ai.running")):
                            try:
                                masker = _build_masker()
                                masked_row = masker.mask_row(_dlast['row'])
                                rag = _build_rag(int(st.session_state.get('ai_rag_k', 3)))
                                anlz = _build_llm_analyzer()
                                rag_ctx = rag.search(
                                    f"사기유형 {_dlast['fraud_type']} 이상거래 탐지 원인 분석",
                                    _dlast['fraud_type'])
                                raw_r = anlz.analyze(masked_row, _dlast['fraud_type'],
                                                     _dlast['risk_score'], rag_ctx, lang=LANG)
                                llm_result = raw_r if isinstance(raw_r, dict) else {
                                    "analysis": str(raw_r), "slack": str(raw_r)[:500],
                                    "email": str(raw_r)}
                                det_full = {
                                    "txn_id": _dlast.get('txn_id') or 'MANUAL',
                                    "fraud_type": _dlast['fraud_type'],
                                    "risk_score": _dlast['risk_score'],
                                    "is_anomaly": True, "tier": None,
                                    "source": "ops_dashboard_detect",
                                    "row": _dlast['row'],
                                    "llm": llm_result, "llm_used": True, "errors": [],
                                }
                                # 🚀 자동 발송 — 사이드바 토글이 켜져 있을 때만.
                                #   되돌릴 수 없는 동작이라 감사 로그를 함께 남긴다.
                                if odp:
                                    # 컴포저는 dashboard.py 세션5 와 같은 것을 쓴다 —
                                    #   자동 발송물도 수동 발송물과 같은 모양이어야 한다.
                                    odp.auto_send(
                                        det_full, st.session_state,
                                        notifier_factory=_build_notifier,
                                        email_resolver=_ai_effective_email,
                                        compose_slack=_rich_slack,
                                        compose_email=_rich_email,
                                        mask_level=st.session_state.get('pii_level', '-'),
                                        db_path=DB)
                                st.session_state['_det_ai_result'] = det_full
                                if astore and _dlast.get('txn_id'):
                                    astore.save(DB, det_full, _dlast['row'])
                            except Exception as e:
                                st.error(t("ai.sent_fail", e=e))

                    _dai = st.session_state.get('_det_ai_result')
                    if _dai and _dai['txn_id'] == (_dlast.get('txn_id') or 'MANUAL'):
                        _llm = _dai.get('llm') or {}
                        # 자동 발송 등급·결과 뱃지 (실패 사유까지 노출)
                        if odp:
                            _nb = odp.tier_badge_html(_dai, T)
                            if _nb:
                                st.markdown(_nb, unsafe_allow_html=True)
                        st.markdown(f"###### {t('ai.analysis_header')}")
                        st.markdown(_llm.get('analysis', ''))
                        # 🔊 분석문 음성 재생 — 화면을 못 볼 때 귀로 받는다
                        if dui and _llm.get('analysis'):
                            dui.tts_player(_llm['analysis'], "det_analysis",
                                           st.session_state.get('tts_lang', LANG), T)
                        # 🔁 이 단계만 다시 — 3단계 통 재생성은 최대 6분 45초가 걸린다
                        if odp and st.button(t("ai.redo_analysis"), key="det_redo_analysis"):
                            with st.spinner(t("ai.redoing")):
                                if _redo_step(_dai, "analysis"):
                                    st.rerun()

                        dsc1, dsc2 = st.columns(2)
                        with dsc1:
                            st.markdown(f"###### {t('ai.slack_header')}")
                            st.code(_llm.get('slack', ''), language="text")
                            _sb1, _sb2 = st.columns([1.4, 1])
                            if _sb1.button(t("ai.send_slack"), key="det_send_slack",
                                           width='stretch'):
                                _send_ask("det_slack", "slack", _llm.get('slack', ''),
                                          fraud_type=_dai['fraud_type'],
                                          risk_score=_dai['risk_score'],
                                          txn_id=_dai.get('txn_id', ''),
                                          tier=_dai.get('notify_tier', 'single'),
                                          det=_dai)
                            if odp and _sb2.button(t("ai.redo"), key="det_redo_slack",
                                                   width='stretch'):
                                with st.spinner(t("ai.regenerating")):
                                    if _redo_step(_dai, "slack"):
                                        st.rerun()
                            _send_confirm("det_slack")
                        with dsc2:
                            st.markdown(f"###### {t('ai.email_header')}")
                            # 편집 가능한 미리보기 — **여기 보이는 그대로** 나간다.
                            #   예전에는 재생성해도 이 칸이 안 바뀌는데 전송은 새 본문을
                            #   보내서, 화면과 실제 발송물이 달랐다.
                            _sync_widget("det_email_prev", _llm.get('email', ''))
                            st.text_area("det_email_preview", height=160,
                                        label_visibility="collapsed", key="det_email_prev")
                            st.caption(t("ai.editable_note"))
                            _eb1, _eb2 = st.columns([1.4, 1])
                            if _eb1.button(t("ai.send_email"), key="det_send_email",
                                           width='stretch'):
                                _send_ask("det_email", "email",
                                          st.session_state.get("det_email_prev", ""),
                                          fraud_type=_dai['fraud_type'],
                                          risk_score=_dai['risk_score'],
                                          txn_id=_dai.get('txn_id', ''),
                                          tier=_dai.get('notify_tier', 'single'),
                                          det=_dai)
                            if odp and _eb2.button(t("ai.redo"), key="det_redo_email",
                                                   width='stretch'):
                                with st.spinner(t("ai.regenerating")):
                                    if _redo_step(_dai, "email"):
                                        st.rerun()
                            _send_confirm("det_email")

                        # 📄 보고서 저장 — 보낸 것과 별개로 '남기는' 산출물
                        _report_dl(_dai, "det")

                # ── 🕘 탐지 이력 (이번 세션) — 임계값을 바꾸면 몇 건이 뒤집히는가 ──
                if dui and st.session_state.get('det_history'):
                    with st.expander(
                            t("det.history_n", n=len(st.session_state["det_history"])),
                            expanded=False):
                        if dui.history_table(st.session_state['det_history'], _th, T,
                                             lang=LANG, t=t, key_prefix="ops") == "clear":
                            st.session_state.pop('det_history', None)
                            st.rerun()

    # ── 서브탭 1: 단건 분석 ──────────────────────────────
    with AI_SUB[1]:
        alerts = oq.alert_queue(DB, limit=100, only_unreviewed=True)
        if not alerts:
            st.info(t("ai.no_alert"))
        else:
            opts = {f"{r['txn_id']} · {ui.fraud_label(r['fraud_type'], LANG, short=True)} · "
                   f"{float(r['risk_score']):.3f} · {r['시각']}": r for r in alerts}
            keys_list = list(opts.keys())
            # 트리아지/경보 카드에서 넘어온 알림이 있으면 기본 선택으로 맞춘다
            _default_idx = 0
            _jt = JUMP_TXN
            if _jt:
                for _i, r in enumerate(opts.values()):
                    if r['txn_id'] == _jt:
                        _default_idx = _i
                        break
            sel_label = st.selectbox(t("ai.pick"), keys_list, index=_default_idx,
                                     key="ai_pick_alert")
            alert = opts[sel_label]
            tid = alert["txn_id"]

            raw_row = oq.get_raw_row(DB, tid)
            if not raw_row:
                st.warning(t("ai.no_row"))
            else:
                if st.session_state.get('pii_level', 'standard') == 'off':
                    st.warning(t("ai.mask_off_warn"))

                _cache_key = f"_ai_result_{tid}"
                # 🤖 챗봇 액션 run_ai_analysis 도 같은 자리로 들어온다 (PENDING_AI_RUN).
                #   버튼은 위젯 **반환값**이라 세션 상태로 누를 수 없어서, 에이전트는
                #   예약 플래그만 남기고 실제 실행은 여기서 `버튼 or 플래그`로 받는다.
                if st.button(t("ai.run"), type="primary", key="ai_run_btn") or PENDING_AI_RUN:
                    with st.spinner(t("ai.running")):
                        try:
                            masker = _build_masker()
                            clean_row = {k: v for k, v in raw_row.items()
                                        if not str(k).startswith('_')}
                            masked_row = masker.mask_row(clean_row)
                            rag = _build_rag(int(st.session_state.get('ai_rag_k', 3)))
                            anlz = _build_llm_analyzer()
                            fraud_type = alert.get("fraud_type") or "?"
                            fraud_name = ui.fraud_label(fraud_type, LANG, short=False)
                            rag_ctx = rag.search(
                                f"사기유형 {fraud_type} {fraud_name} 이상거래 탐지 원인 분석",
                                fraud_type)
                            raw_r = anlz.analyze(masked_row, fraud_type,
                                                 float(alert.get("risk_score") or 0),
                                                 rag_ctx, lang=LANG)
                            if isinstance(raw_r, dict):
                                llm_result = raw_r
                            else:
                                llm_result = {"analysis": str(raw_r),
                                             "slack": str(raw_r)[:500], "email": str(raw_r)}
                            det = {
                                "txn_id": tid, "fraud_type": fraud_type,
                                "risk_score": float(alert.get("risk_score") or 0),
                                "is_anomaly": bool(alert.get("is_anomaly")),
                                "tier": None, "source": "ops_dashboard",
                                # row 는 이메일 첨부 리포트의 거래 표 재료다. 첨부는
                                #   notify_compose 가 **강제 마스킹**해서 넣는다.
                                "row": clean_row,
                                "llm": llm_result, "llm_used": True, "errors": [],
                            }
                            st.session_state[_cache_key] = det
                            # ✨ 강화 포인트: 결과를 analysis_cache에 저장 →
                            #   '탐지 로그' 탭이 이미 astore.load()로 읽는 저장소에
                            #   그대로 합류하므로, 별도 뷰어를 새로 만들 필요가 없다.
                            if astore:
                                ok, _msg = astore.save(DB, det, clean_row,
                                                       alert_ref=alert.get("alert_ref"))
                                if ok:
                                    st.toast(t("ai.cached"))
                        except Exception as e:
                            st.error(t("ai.sent_fail", e=e))

                det = st.session_state.get(_cache_key)
                if det:
                    llm = det.get("llm") or {}
                    st.markdown(f"###### {t('ai.analysis_header')}")
                    st.markdown(llm.get("analysis", ""))

                    sc1, sc2 = st.columns(2)
                    with sc1:
                        st.markdown(f"###### {t('ai.slack_header')}")
                        st.code(llm.get("slack", ""), language="text")
                        if st.button(t("ai.send_slack"), key=f"ai_send_slack_{tid}",
                                    width="stretch"):
                            _send_ask("ai_slack", "slack", llm.get("slack", ""),
                                      fraud_type=det['fraud_type'],
                                      risk_score=det['risk_score'], txn_id=tid,
                                      det=det)
                        _send_confirm("ai_slack")
                    with sc2:
                        st.markdown(f"###### {t('ai.email_header')}")
                        _ekey = f"ai_email_prev_{tid}"
                        _sync_widget(_ekey, llm.get("email", ""))
                        st.text_area("email_preview", height=180,
                                    label_visibility="collapsed", key=_ekey)
                        st.caption(t("ai.as_is_note"))
                        if st.button(t("ai.send_email"), key=f"ai_send_email_{tid}",
                                    width="stretch"):
                            _send_ask("ai_email", "email",
                                      st.session_state.get(_ekey, ""),
                                      fraud_type=det['fraud_type'],
                                      risk_score=det['risk_score'], txn_id=tid,
                                      subject=t("ai.subject_single",
                                                ft=str(det["fraud_type"]).upper(), tid=tid),
                                      det=det)
                        _send_confirm("ai_email")

                    _report_dl(det, f"ai_{tid}")

    # ── 서브탭 2: 배치 분석 ──────────────────────────────
    #   pipeline.batch_analyzer.run_batch()는 classifier.predict(row)로
    #   '재분류'하는 것을 전제로 설계됐다(검증셋 배치용). 운영에서는 이미
    #   워처가 판정을 끝낸 거래를 다시 분류하면 워처와 다른 결과가 나와
    #   신뢰가 깨진다 — 그래서 재분류 대신 '이미 나온 판정을 그대로
    #   돌려주는' 가짜 classifier를 꽂아 run_batch의 집계·LLM 리포트·
    #   Slack/Email 템플릿 로직만 그대로 재사용한다.
    with AI_SUB[2]:
        st.markdown(f"##### {t('batch.title')}")
        st.caption(t("batch.desc"))

        # ── 📦 입력 탭에서 넘어온 추출분 ─────────────────────
        #   '탐지 입력'의 액션 바 [📦 일괄 분석]이 rows 를 여기로 넘긴다.
        #   알림 큐(라이브)와 추출분(임의 데이터)은 성격이 다르므로 소스를 명시적으로 고른다.
        _handoff = st.session_state.get('ai_batch_rows') or []
        if st.session_state.pop('ai_batch_go', False) and _handoff:
            st.session_state['batch_src'] = "handoff"
        _src_opts = ["queue", "handoff"] if _handoff else ["queue"]
        b_src = st.radio(
            t("batch.src_label"), _src_opts, horizontal=True, key="batch_src",
            format_func=lambda x: (t("batch.src_queue") if x == "queue"
                                   else t("batch.src_handoff", n=len(_handoff))))
        if b_src == "handoff":
            st.caption(t("batch.handoff_note", n=len(_handoff)))

        bc1, bc2, bc3 = st.columns([1, 1, 1])
        b_hours = bc1.number_input(t("batch.window"), min_value=1, max_value=720,
                                   value=24, key="batch_window_h",
                                   disabled=(b_src == "handoff"))
        b_limit = bc2.number_input(t("batch.limit"), min_value=1, max_value=200,
                                   value=30, key="batch_limit",
                                   disabled=(b_src == "handoff"))
        b_run = bc3.button(t("batch.run"), type="primary", width="stretch",
                           key="batch_run_btn") or PENDING_BATCH_RUN
        # ↑ 챗봇 액션 run_batch 도 같은 자리로 들어온다 (플래그는 탭 밖에서 pop —
        #   TABS 생성부 주석 참조). 아래 두 갈래(handoff / queue)가 모두 b_run 을 본다.

        _bcache_key = "_ai_batch_result"
        if b_run and b_src == "handoff":
            # 추출분은 아직 판정 전이다 → 진짜 분류기로 돌린다
            with st.spinner(t("batch.running")):
                try:
                    from pipeline.batch_analyzer import run_batch
                    _b0 = {k: v for k, v in _handoff[0].items()
                           if not str(k).startswith('_') and k != 'Fraud_Type'}
                    _clf, _, _use_clean = dio.resolve_classifier(_mpath, _b0)
                    _rows = []
                    for _r in _handoff:
                        _c = {k: v for k, v in _r.items() if not str(k).startswith('_')}
                        _c.setdefault("transaction_id", _r.get("ID", "-"))
                        _rows.append(_c if _use_clean else dict(_r))
                    bres = run_batch(
                        _rows, _clf, threshold=float(THRESHOLD),
                        analyzer=_build_llm_analyzer(), masker=_build_masker(),
                        rag=_build_rag(int(st.session_state.get('ai_rag_k', 3))),
                        lang=LANG)
                    st.session_state[_bcache_key] = {
                        "bres": bres, "skipped": 0, "n_included": len(_rows)}
                except Exception as e:
                    st.error(t("batch.failed", e=e))
        elif b_run:
            b_alerts = oq.alert_queue(DB, limit=int(b_limit), only_unreviewed=True,
                                      since_hours=int(b_hours))
            if not b_alerts:
                st.info(t("batch.no_alerts"))
            else:
                with st.spinner(t("batch.running")):
                    try:
                        from pipeline.batch_analyzer import run_batch

                        class _PrejudgedClassifier:
                            """run_batch가 요구하는 predict(row) 인터페이스를 흉내낸다.
                            워처가 이미 내린 판정(_ft/_risk)을 그대로 돌려줄 뿐,
                            실제 재분류는 하지 않는다."""
                            @staticmethod
                            def predict(row):
                                return row.get("_ft", "?"), float(row.get("_risk", 0)), {}

                        rows, skipped = [], 0
                        for a in b_alerts:
                            raw = oq.get_raw_row(DB, a["txn_id"])
                            if not raw:
                                skipped += 1
                                continue
                            r = {k: v for k, v in raw.items() if not str(k).startswith('_')}
                            r["transaction_id"] = a["txn_id"]
                            r["_ft"] = a.get("fraud_type") or "?"
                            r["_risk"] = float(a.get("risk_score") or 0)
                            rows.append(r)

                        if not rows:
                            st.warning(t("ai.no_row"))
                        else:
                            masker = _build_masker()
                            rag = _build_rag(int(st.session_state.get('ai_rag_k', 3)))
                            anlz = _build_llm_analyzer()
                            bres = run_batch(
                                rows, _PrejudgedClassifier(),
                                threshold=_tier_th()[0],
                                analyzer=anlz, masker=masker, rag=rag,
                                lang=LANG,
                            )
                            st.session_state[_bcache_key] = {
                                "bres": bres, "skipped": skipped,
                                "n_included": len(rows),
                            }
                            if skipped:
                                st.caption(t("batch.skip_note", skip=skipped))
                    except Exception as e:
                        st.error(t("ai.sent_fail", e=e))

        bpack = st.session_state.get(_bcache_key)
        if bpack:
            bres = bpack["bres"]
            _kpi_row([
                (t("batch.kpi_total"), bpack["n_included"], None),
                (t("batch.kpi_anomaly"), bres.anomaly_count, None),
                (t("batch.kpi_avg"), f"{bres.avg_risk:.3f}", None),
                (t("batch.kpi_max"), f"{bres.max_risk:.3f}", None),
            ])
            st.caption(bres.summary_line)

            st.markdown(f"###### {t('batch.report_header')}")
            st.markdown(bres.analysis)

            if bres.top_risky:
                st.markdown(f"###### {t('batch.top_risky')}")
                st.dataframe(
                    [{"거래ID": r["txn_id"],
                      "유형": ui.fraud_label(r["fraud_type"], LANG, short=True),
                      "위험도": r["risk_score"], "금액": r["amount"],
                      "채널": r["channel"]} for r in bres.top_risky],
                    width="stretch", hide_index=True)

            bsc1, bsc2 = st.columns(2)
            with bsc1:
                st.markdown(f"###### {t('ai.slack_header')}")
                st.code(bres.slack, language="text")
                if st.button(t("ai.send_slack"), key="batch_send_slack",
                            width="stretch"):
                    _send_ask("batch_slack", "slack", bres.slack, fraud_type="batch",
                              risk_score=bres.max_risk,
                              txn_id=f"BATCH/{bpack['n_included']}건", bres=bres)
                _send_confirm("batch_slack")
            with bsc2:
                st.markdown(f"###### {t('ai.email_header')}")
                # 배치를 다시 돌리면 원본이 바뀌므로 미리보기도 새 리포트로 갱신된다
                _sync_widget("batch_email_prev", bres.email)
                st.text_area("batch_email_preview", height=180,
                            label_visibility="collapsed", key="batch_email_prev")
                st.caption(t("ai.as_is_note"))
                if st.button(t("ai.send_email"), key="batch_send_email",
                            width="stretch"):
                    _send_ask("batch_email", "email",
                              st.session_state.get("batch_email_prev", ""),
                              fraud_type="batch", risk_score=bres.max_risk,
                              txn_id=f"BATCH/{bpack['n_included']}건",
                              subject=t("ai.subject_batch", n=bpack["n_included"]),
                              bres=bres)
                _send_confirm("batch_email")

            # 📄 배치 보고서 저장 — KPI·유형분포 머리말 + 3단계 산출물
            if nc:
                st.download_button(
                    t("ai.report_md"),
                    nc.report_md_batch(bres, t=t, lang=LANG).encode("utf-8"),
                    file_name=f"fds_batch_report_{bpack['n_included']}rows_"
                              f"{time.strftime('%Y%m%d_%H%M%S')}.md",
                    mime="text/markdown", key="batch_report_md", width="stretch",
                    help=t("ai.report_md_help"))

    # ── 서브탭 3: AI 어시스턴트 (챗봇 + 음성입력) ────────
    #   dashboard.py의 챗봇(pipeline.chat_agent.ChatAgent)을 그대로 재사용하되
    #   enable_actions=False로 켠다. ChatAgent는 action 화이트리스트를 앱별로
    #   나눌 수 없는 전역 레지스트리(ACTIONS)라 dashboard 전용 액션(세션 이동·
    #   직접입력 폼 등)이 섞여 있다. 워처 시작/중지 같은 ops 전용 액션은
    #   되돌릴 수 없는 운영 조작이라 별도의 확인 카드(Human-in-the-loop) 설계가
    #   필요해 — 여기서는 안전하게 '읽기 전용 해설'만 제공하고, 실행형 액션은
    #   다음 증분으로 남긴다. 대신 컨텍스트는 검증셋이 아니라 100% 라이브 DB다.
    with AI_SUB[3]:
        _chat_key = "ops_chat_history"
        _hist = st.session_state.get(_chat_key, [])
        _hdr1, _hdr2 = st.columns([5, 1])
        with _hdr1:
            st.caption(t("chat.desc"))
        with _hdr2:
            if st.button(t("chat.clear"), key="ops_chat_clear", width="stretch"):
                st.session_state[_chat_key] = []
                st.rerun()
        if not _hist:
            st.caption(t("chat.empty"))
        for _cm in _hist:
            with st.chat_message("user" if _cm.get("role") == "user" else "assistant"):
                st.markdown(_cm.get("content", ""))

        with st.expander(t("chat.voice")):
            va, vb = st.columns(2)
            with va:
                audio = st.audio_input(t("chat.voice_record"), key="ops_chat_audio")
            with vb:
                up = st.file_uploader(t("chat.voice_upload"),
                                      type=["wav", "mp3", "m4a", "webm", "ogg"],
                                      key="ops_chat_audio_up")
            _blob = None
            _fname = "audio.wav"
            if audio is not None:
                _blob = audio.getvalue()
                _fname = "audio.wav"
            elif up is not None:
                _blob = up.getvalue()
                _fname = up.name
            if _blob and st.button(t("chat.stt_go"), key="ops_stt_go"):
                with st.spinner(t("chat.voice_transcribing")):
                    try:
                        from pipeline.speech_to_text import SpeechToText
                        stt = SpeechToText(
                            backend="auto",
                            allow_cloud=bool(st.session_state.get('ai_stt_allow_cloud', True)),
                            api_key=st.session_state.get('ai_openai_key', '') or None,
                            lang=LANG,
                        )
                        ok, text, why = stt.transcribe(_blob, _fname)
                    except Exception as e:
                        ok, text, why = False, "", str(e)
                if ok:
                    st.success(t("chat.voice_ok", text=text))
                    st.session_state[CHAT_PENDING] = text   # 처리는 다음 런에서
                    st.rerun()
                else:
                    st.error(t("chat.voice_fail", why=why))
            st.toggle(t("chat.stt_cloud"), key="ai_stt_allow_cloud", value=True)

        # ── 💬 퀵프롬프트 ─────────────────────────────────
        #   빈 입력창 앞에서 "무엇을 물어볼 수 있는지" 모르는 게 가장 큰 진입장벽이다.
        #   ⚠ 문구 한국어 고정 — 사이드바 챗(_sidebar_chat)과 같은 규칙.
        #   챗 입력창은 값을 미리 채우는 API가 없어서, 누르면 입력창을 거치지 않고
        #   바로 대기열에 적재한다(= 사용자가 타이핑해 보낸 것과 같은 경로).
        st.caption("💬 이런 걸 물어볼 수 있어요")
        _QUICK = [
            "지금 미처리 몇 건이야?",
            "SLA 넘긴 건만 골라줘",
            "최근 7일 오탐률 어때?",
            "워처 살아있어?",
        ]
        _qc = st.columns(2)
        for _qi, _qp in enumerate(_QUICK):
            with _qc[_qi % 2]:
                if st.button(_qp, key=f"ops_chat_quick_{_qi}", width="stretch"):
                    st.session_state[CHAT_PENDING] = _qp
                    st.rerun()

        # ── 🔧 에이전트 자가진단 ───────────────────────────
        #   "챗봇이 말만 하고 안 움직인다"의 원인은 대개 액션 파이프라인이 아니라
        #   LLM 연결이다(로컬 모델 미기동 → 응답 없음 → 액션 0건). 둘을 가를 수
        #   있어야 담당자가 혼자 판단한다. 파서는 LLM 없이도 검증되므로,
        #   여기서 초록불이 뜨는데 액션이 안 먹으면 → 원인은 모델 쪽이다.
        with st.expander("🔧 에이전트 자가진단 (액션이 안 먹을 때)"):
            if not oag:
                st.warning("ops_agent 모듈을 불러오지 못했습니다 — 액션 기능 전체가 꺼집니다.")
            else:
                _prov = st.session_state.get("ai_llm_provider", "-")
                st.code(f"ops_agent  {oag.OPS_AGENT_VERSION}\n"
                        f"actions    {len(oag.ACTIONS)}종 등록\n"
                        f"provider   {_prov}", language="text")
                # 전 액션의 example 을 파서에 왕복시켜, 등록과 인식이 어긋나지 않았는지 본다
                _bad = [n for n, m in oag.ACTIONS.items()
                        if [a["name"] for a in oag.parse(f"[[ACTION: {m['example']}]]")[1]] != [n]]
                if _bad:
                    st.error(f"파서 왕복 실패: {', '.join(_bad)}")
                else:
                    st.success(f"파서 정상 — {len(oag.ACTIONS)}종 모두 인식됩니다")
                # 화이트리스트 밖은 버리는가 (안전장치가 살아 있는지)
                _cl, _mal = oag.parse("[[ACTION: send_slack(all)]]")
                st.caption(("✅ 화이트리스트 밖 액션은 버립니다 (발송·판정·워처 제어는 사람 몫)"
                            if not _mal else "⚠ 위험 액션이 통과했습니다 — 즉시 확인 필요"))

                _live = st.selectbox("액션 직접 실행해 보기", list(oag.ACTIONS),
                                     key="ops_agent_live_sel",
                                     format_func=lambda k: f"{k} — {oag.ACTIONS[k]['example']}")
                # ⚠ 여기서 oag.apply() 를 **바로 부르면 안 된다**. 이 자리는 AI 탭
                #   안이라 트리아지 정렬·로그 검색어·기간 같은 위젯이 이미 만들어진
                #   뒤다 — 액션이 그 key 를 건드리는 순간 Streamlit 이 예외를 던진다.
                #   챗 입력과 똑같이 **적재만** 하고, 위젯보다 앞선 드레인 지점에서 처리한다.
                if st.button("이 액션 실행", key="ops_agent_live_go"):
                    st.session_state["_ops_agent_live"] = oag.ACTIONS[_live]["example"]
                    st.rerun()
                for _n in st.session_state.pop("_ops_agent_live_notes", []):
                    st.write("·", _n)

        q = st.chat_input(t("chat.input_ph"), key="ops_chat_in")
        if q:
            # 사이드바 챗과 **같은 경로**로 태운다: 여기서 바로 처리하면 액션이
            #   이미 만들어진 위젯(트리아지 정렬 등)의 key 를 건드려 Streamlit 이
            #   예외를 던진다. 적재만 하고 다음 런의 드레인 지점에서 처리한다.
            st.session_state[CHAT_PENDING] = q
            st.rerun()


# ══════════════════════════════════════════════════════════
# 탭 8 — 🩺 진단 (연결 테스트 · 발송 감사 · 타임존)
# ══════════════════════════════════════════════════════════
with TAB_DIAG:
    # ── 🔌 연결 테스트 — "왜 알림이 안 오지?"를 3초 안에 답한다 ──
    #   진단 탭이 제자리다. 알림이 안 올 때 담당자가 가장 먼저 여는 곳이고,
    #   ML/RAG/LLM/SMTP 중 어디가 끊겼는지 여기서 한 번에 갈린다.
    st.markdown("##### " + t("diag.conn_test"))
    if odp:
        odp.render_connection_tests(
            T, lang=LANG, model_path=SEL_MODEL_P,
            rag_factory=_build_rag,
            analyzer_factory=_build_llm_analyzer,
            notifier_factory=_build_notifier,
            key_prefix="diag")
        st.caption(t("diag.conn_target", model=SEL_MODEL,
                     prov=st.session_state.get("ai_llm_provider", "local")))
    else:
        st.caption(t("diag.no_dispatch"))

    # ── 📤 발송 감사 로그 — 외부로 나간 것은 회수할 수 없다 ──
    st.markdown("##### " + t("diag.audit"))
    if odp:
        st.caption(t("diag.audit_desc"))
        _ag1, _ag2 = st.columns([1, 3], vertical_alignment="bottom")
        _aud_n = _ag1.select_slider(t("diag.audit_n"), [12, 25, 50, 100, 200], value=12,
                                    key="audit_limit")
        _ag2.caption(t("diag.audit_persist"))
        odp.render_audit(st.session_state, T, limit=int(_aud_n), db_path=DB, lang=LANG)

        with st.expander(t("diag.audit_purge")):
            odp.render_audit_purge(st.session_state, T, DB, key_prefix="diag", lang=LANG)
    else:
        st.caption(t("diag.no_dispatch_short"))

    st.divider()
    st.markdown(f"##### {t('diag.tz')}")
    st.caption(t("diag.tz_offset", n=oq.tz_offset_seconds(DB)))
    diag = oq.diagnose_timestamps(DB)
    if diag:
        st.dataframe(diag, width="stretch", hide_index=True)
        if any(d["불일치"] for d in diag):
            st.warning(t("diag.tz_warn"))
    else:
        st.caption(t("common.none"))

    st.markdown(f"##### {t('diag.model')}")
    if rc:
        ok, _clf, why = rc.load_guarded(None, st.session_state["model_dir"])
        (st.success if ok else st.error)(why)
    else:
        st.caption(t("diag.no_recheck"))

    # ══════════════════════════════════════════════════════
    # 🧪 화면 배치 비교 (실험 · 세션 한정)
    #
    #   기본 배치('🧠 AI 분석 우선')는 확정된 요구사항이라 코드 기본값을 바꾸지
    #   않는다. 여기서는 "관제 흐름대로 놓으면 어떤가"를 잠깐 눈으로 확인하고
    #   원래대로 돌아올 수 있게만 열어 둔다 — 선택은 세션에만 남으므로
    #   새로고침하면 기본(확정)안으로 복귀하고, 설정 파일에는 아무것도 안 쓴다.
    # ══════════════════════════════════════════════════════
    st.divider()
    st.markdown("##### " + t("diag.layout_header"))
    _cur_layout = st.session_state.get("ops_tab_layout", "ai_first")
    _keys = list(TAB_LAYOUTS.keys())
    _pick = st.radio(t("diag.layout_label"), _keys, key="diag_layout_pick",
                     index=_keys.index(_cur_layout) if _cur_layout in _keys else 0,
                     format_func=lambda k: t(f"diag.layout_{k}"), horizontal=True,
                     help=t("diag.layout_help"))
    st.caption("  ·  ".join(TAB_DEFS[k] for k in TAB_LAYOUTS[_pick]))
    if _pick != _cur_layout:
        if st.button(t("diag.layout_go"), key="diag_layout_go", width="stretch"):
            st.session_state["ops_tab_layout"] = _pick
            st.session_state["_force_tab"] = TAB_LAYOUTS[_pick][0]
            st.rerun()
    elif _cur_layout != "ai_first":
        st.info(t("diag.layout_experimental"))
        if st.button(t("diag.layout_reset"), key="diag_layout_reset",
                     type="primary", width="stretch"):
            st.session_state["ops_tab_layout"] = "ai_first"
            # 위젯 key 는 **지운다** — 이미 인스턴스화된 위젯의 값을 대입하면
            #   Streamlit 이 예외를 던진다. 지우면 다음 런에서 index= 로 다시 잡힌다.
            st.session_state.pop("diag_layout_pick", None)
            st.session_state["_force_tab"] = "ai"
            st.rerun()
    else:
        st.caption(t("diag.layout_default"))

    # ── 🗜 압축 탭 라벨 ─────────────────────────────────────
    #   배치(순서)와 라벨 길이는 서로 다른 문제라 스위치를 분리해 둔다 —
    #   확정된 순서는 그대로 두고 폭만 줄이고 싶을 때가 대부분이다.
    if st.toggle(t("diag.compact"), key="ops_tab_compact",
                 help=t("diag.compact_help")):
        pass                    # 값은 위쪽 TAB_DEFS 가 다음 런에서 읽는다
    _px = sum(2 if unicodedata.east_asian_width(_c) in "WF" or ord(_c) > 0x1F000
              else 1 for _lbl in TAB_DEFS.values() for _c in _lbl)
    st.caption(t("diag.compact_now", px=(_px + 32) * 8,
                 mode=t("diag.compact_on") if _compact else t("diag.compact_off")))

    st.divider()
    st.markdown("##### " + t("diag.modules"))
    st.code("\n".join([
        f"ops_dashboard  {APP_VERSION}",
        f"ops_ui         {ui.OPS_UI_VERSION}   i18n_data={'O' if ui.HAS_I18N_DATA else 'X'}",
        f"ops_sidebar    {osb.OPS_SIDEBAR_VERSION if osb else '-'}",
        f"ops_dispatch   {odp.OPS_DISPATCH_VERSION if odp else '-'}",
        f"notify_compose {nc.NOTIFY_COMPOSE_VERSION if nc else '-'}   "
        f"rich={'ON' if st.session_state.get('ai_rich_notify', True) else 'OFF'}",
        f"audit_store    {aust.AUDIT_STORE_VERSION if aust else '-'}",
        f"detect_ui      {dui.DETECT_UI_VERSION if dui else '-'}",
        f"detect_wbench  {dwb.DETECT_WORKBENCH_VERSION if dwb else '-'}",
        f"asset_registry {ar.ASSET_REGISTRY_VERSION if ar else '-'}",
        f"review_store   {rs.REVIEW_STORE_VERSION}",
        f"ops_queries    {oq.OPS_QUERIES_VERSION}",
        f"ops_recheck    {rc.RECHECK_VERSION if rc else '-'}",
        f"watcher_panel  {wp.PANEL_VERSION if wp else '-'}",
        f"watcher_config {wcfg.CONFIG_VERSION if wcfg else '-'}",
        f"streamlit      {st.__version__}",
    ]), language="text")
    st.caption(rs.summary_line(DB))


# ══════════════════════════════════════════════════════════
# ⌨ 키보드 단축키  ✨ v38
#
# 왜 여기(파일 맨 끝)인가
#   히든 버튼을 누르면 st.rerun() 이 걸린다. 그런데 Streamlit 은 **그 런에서
#   그려지지 않은 위젯의 상태를 폐기**한다. 그래서 단축키 블록이 화면 앞쪽에
#   있으면, 키를 누르는 순간 뒤쪽 탭의 위젯(트리아지 필터·로그 검색어 등)이
#   통째로 초기화된다. dashboard.py 가 v12 에서 겪은 버그가 정확히 이것이고,
#   거기서는 위젯 key 를 상태값과 조합하는 우회로 막았다.
#   ops 는 애초에 **모든 위젯이 그려진 뒤**에 두는 쪽을 택한다 — 우회가 필요 없다.
#
# 두 갈래로 나눈 이유
#   · 순수 클라이언트 동작(탭 이동·사이드바·챗 포커스)은 JS 가 DOM 을 직접
#     누른다. 파이썬 왕복이 없으니 즉각 반응하고, 무엇보다 rerun 이 없어서
#     위쪽 위젯 상태를 건드릴 일이 아예 없다.
#   · 파이썬 상태가 필요한 것(테마·언어·압축·자동새로고침)만 히든 버튼을 탄다.
# ══════════════════════════════════════════════════════════


def _html(content, height=0, scrolling=False, **kw):
    """HTML/JS 삽입 호환 레이어 — dashboard.py 의 _html 과 **같은 규칙**.

    st.components.v1.html 은 2026-06-01 지원 종료 예고가 붙었고 st.iframe 이
    후속이다. 다만 드롭인 교체가 아니다:
      · height=0 거부 → StreamlitInvalidHeightError. 보이지 않는 JS 주입기는
        관례적으로 height=0 이라 그대로 넘기면 전부 터진다 → 1 로 보정
      · scrolling 인자 없음 → TypeError → 넘기지 않는다
    실패하면 예외 종류를 가리지 않고 구 API 로 떨어진다.
    ⚠ st.html() 은 대안이 아니다 — iframe 이 아닌 인라인이고 기본값이
      unsafe_allow_javascript=False 라 스크립트가 실행되지 않는다.
    """
    _h = height if isinstance(height, int) and height > 0 else 1
    _fn = getattr(st, "iframe", None)
    if _fn is not None:
        try:
            return _fn(content, height=_h)
        except Exception:
            pass
    import streamlit.components.v1 as _c
    return _c.html(content, height=height, scrolling=scrolling, **kw)

# ⚠ 문구는 한국어 고정이다. i18n_data.py 를 건드리지 않기로 했고(4개국어 미번역),
#   같은 이유로 사이드바 챗(_sidebar_chat)도 한국어로 적혀 있다. 같은 규칙을 따른다.
KEYMAP = [
    ("1 ~ 8",  "탭 이동 (AI분석·트리아지·실시간·인계·로그·오탐·튜닝·진단)"),
    ("← →",    "이전 / 다음 탭"),
    ("C",      "AI 어시스턴트 입력창으로 이동 + 커서"),
    ("H",      "사용 안내(온보딩) 다시 보기"),
    ("? /",    "이 단축키 모음 열기"),
    ("R",      "지금 새로고침"),
    ("A",      "자동 새로고침 켜기 / 끄기"),
    ("V",      "탭 라벨 압축 모드 (좁은 화면용)"),
    ("B",      "사이드바 펼치기 / 접기"),
    ("T",      "테마 순환"),
    ("L",      "언어 순환"),
    ("Ctrl+/", "단축키 힌트 토스트"),
]

# ── 히든 버튼 (화면 밖으로 밀어낸다 · JS 가 대신 누른다) ──
st.markdown("""<style>
.st-key-hk_theme,.st-key-hk_lang,.st-key-hk_guide,.st-key-hk_keymap,
.st-key-hk_compact,.st-key-hk_autorf,.st-key-hk_refresh,.st-key-hk_chat{
position:fixed!important;top:-10000px!important;left:-10000px!important;
width:1px!important;height:1px!important;overflow:hidden!important;opacity:0!important}
</style>""", unsafe_allow_html=True)

if st.button("⌨T", key="hk_theme"):
    _o = list(ui.THEME_ORDER)
    _c = st.session_state.get("theme", ui.DEFAULT_THEME)
    st.session_state["theme"] = _o[(_o.index(_c) + 1) % len(_o)] if _c in _o else _o[0]
    # ⚠ 위젯 key 를 **지운다**. 사이드바 셀렉트박스(_theme_pick)에 예전 값이 남아
    #   있으면, 다음 런에서 그쪽이 `th != cur_theme` 로 보고 테마를 되돌려 놓는다
    #   (ops_sidebar._appearance_section). 지우면 index= 로 새로 잡힌다.
    st.session_state.pop("_theme_pick", None)
    st.rerun()

if st.button("⌨L", key="hk_lang"):
    _o = list(ui.LANG_OPTIONS)
    _c = st.session_state.get("lang", _o[0])
    st.session_state["lang"] = _o[(_o.index(_c) + 1) % len(_o)] if _c in _o else _o[0]
    st.session_state.pop("_lang_pick", None)          # 위와 같은 되돌림 방지
    st.rerun()

if st.button("⌨H", key="hk_guide"):
    st.session_state["_ops_guide_open"] = True
    st.rerun()

if st.button("⌨?", key="hk_keymap"):
    st.session_state["_ops_keymap_open"] = True
    st.rerun()

# ⚠ 아래 둘은 **위젯 key** 다(진단 탭의 압축 토글 · 실시간 감시 탭의 자동 새로고침).
#   이 블록은 그 위젯들이 이미 만들어진 뒤에 실행되므로, 여기서 session_state 를
#   직접 쓰면 "위젯 인스턴스화 후 key 수정" 예외가 난다 — 그 예외는 화면에 빨간
#   박스로 뜨고 토글은 먹지 않는다. 예약값으로 넘기고 위젯 생성 **앞**에서 소비한다.
#   (챗봇 액션 set_compact_tabs/set_auto_refresh 는 처리 지점이 위젯보다 앞이라
#    직접 써도 안전하다 — 같은 규칙을 서로 다른 위치에서 지키는 것뿐이다)
if st.button("⌨V", key="hk_compact"):
    st.session_state["_pending_compact"] = not st.session_state.get("ops_tab_compact", False)
    st.rerun()

if st.button("⌨A", key="hk_autorf"):
    st.session_state["_pending_autorf"] = not st.session_state.get("auto_refresh", True)
    st.rerun()

if st.button("⌨R", key="hk_refresh"):
    st.rerun()                                        # 지금 다시 조회 (라이브 DB)

if st.button("⌨C", key="hk_chat"):
    # 사이드바가 접혀 있어 챗 입력창을 못 찾았을 때의 폴백 — AI 탭의 전체 챗으로.
    st.session_state["_force_tab"] = "ai"
    st.session_state["_ops_focus_chat"] = True
    st.rerun()


# ── ⌨ 단축키 모음 모달 (? 또는 / · 챗봇 액션 open_keymap) ──
def _render_keymap_body():
    st.caption("입력창·목록에 커서가 있을 때는 단축키가 동작하지 않습니다 (타이핑 보호).")
    _bd = f"rgba({T['accent_rgb']},0.35)"
    for _keys, _label in KEYMAP:
        _chips = "".join(
            '<kbd style="display:inline-block;min-width:22px;text-align:center;'
            'padding:2px 7px;margin-right:4px;border-radius:5px;background:%s;'
            'border:1px solid %s;border-bottom-width:2px;font-family:monospace;'
            'font-size:11.5px;font-weight:700;color:%s">%s</kbd>'
            % (T["bg_surface"], _bd, T["accent"], _k)
            for _k in _keys.split())
        st.markdown(
            '<div style="display:flex;align-items:center;gap:10px;padding:5px 0;'
            'border-bottom:1px solid %s"><div style="min-width:150px">%s</div>'
            '<div style="color:%s;font-size:12px">%s</div></div>'
            % (_bd, _chips, T["text_secondary"], _label),
            unsafe_allow_html=True)
    st.caption("AI 어시스턴트에게 “단축키 알려줘”라고 해도 이 창이 열립니다.")


_D = getattr(st, "dialog", None) or getattr(st, "experimental_dialog", None)
if st.session_state.pop("_ops_keymap_open", False):
    if _D is not None:
        try:
            @_D("⌨ 키보드 단축키", width="small")
            def _keymap_dialog():
                _render_keymap_body()
                if st.button("닫기", key="hk_close", width="stretch"):
                    st.rerun()
            _keymap_dialog()
        except Exception:                              # 다이얼로그 미지원 폴백
            with st.container(border=True):
                st.markdown("##### ⌨ 키보드 단축키")
                _render_keymap_body()
    else:
        with st.container(border=True):
            st.markdown("##### ⌨ 키보드 단축키")
            _render_keymap_body()


# ── 키 리스너 ──────────────────────────────────────────────
#   🔧 테마/언어를 바꾸면 아래 JS 문자열(색상 보간)이 달라져 iframe 이 재마운트되고,
#     구 iframe 이 등록한 리스너는 렐름과 함께 죽는다. "가드로 1회만 등록"하면
#     그 순간부터 전체 단축키가 먹통이 되므로, **항상 제거 후 재등록**한다.
#     (dashboard.py v8.4 가 T 한 번 누르면 키가 죽던 버그를 이렇게 고쳤다)
_kb_hint = "⌨ 1~8 탭 · ←→ 이동 · C 챗 · R 새로고침 · A 자동 · ? 전체 단축키"
# ⚠ f-string 식 안에서 바깥과 같은 따옴표를 쓰는 건 Python 3.12+ 에서만 된다.
#   배포 파이썬을 못 박아 두지 않았으므로 색상은 **미리 꺼내** 이름만 보간한다.
_kb_acc = T["accent"]
_kb_rgb = T["accent_rgb"]
_kb_js = f"""<!DOCTYPE html><html><head><style>body{{margin:0;padding:0;background:transparent}}</style></head>
<body><script>
(function(){{
var d=window.parent.document;
function hk(cls){{var b=d.querySelector('.st-key-'+cls+' button');if(b)b.click();}}
function toast(msg,ms){{
  var e=d.querySelector('#opsKbdToast');
  if(!e){{e=d.createElement('div');e.id='opsKbdToast';
    e.style.cssText='position:fixed;bottom:28px;right:28px;z-index:99999;'
    +'background:rgba(13,22,38,0.95);border:1px solid rgba({_kb_rgb},0.40);'
    +'border-radius:10px;padding:10px 18px;font-family:monospace;font-size:12px;'
    +'color:{_kb_acc};pointer-events:none;opacity:0;transition:opacity .4s;'
    +'box-shadow:0 0 20px rgba({_kb_rgb},0.15)';
    d.body.appendChild(e);}}
  e.innerHTML=msg;e.style.opacity='1';
  clearTimeout(e.__h);e.__h=setTimeout(function(){{e.style.opacity='0'}},ms||3200);
}}
// 메인 탭바만 고른다. AI 탭 안의 서브탭·로그 상세탭도 [role=tab] 이라, 문서 순서상
//   **가장 먼저 나오는** tablist(=1107행에서 만든 8개짜리)로 범위를 좁힌다.
function mainTabs(){{
  var tl=d.querySelector('[data-testid="stTabs"] [role="tablist"]');
  return tl?Array.prototype.slice.call(tl.querySelectorAll(':scope > button[role="tab"]')):[];
}}
function handler(e){{
  if(e.isComposing)return;                      // 한글 IME 조합 중에는 무시
  var ae=d.activeElement||{{}};
  var tag=(ae.tagName||'').toUpperCase();
  if(['INPUT','TEXTAREA','SELECT'].indexOf(tag)>=0)return;
  if(ae.isContentEditable)return;
  // 단일문자 키가 셀렉트/슬라이더/탭 포커스 중 새어나가면, 그쪽의 type-ahead 를
  //   가로채 엉뚱한 조작이 된다(임계값 슬라이더를 만지다 탭이 바뀌는 식).
  if(ae.closest&&ae.closest('[data-baseweb="select"],[data-baseweb="input"],'
    +'[data-baseweb="textarea"],[data-testid="stSelectbox"],[data-testid="stMultiSelect"],'
    +'[data-testid="stNumberInput"],[data-testid="stTextInput"],[data-testid="stTextArea"],'
    +'[data-testid="stSlider"],[role="combobox"],[role="listbox"],[role="slider"],'
    +'[role="tab"],[contenteditable="true"]'))return;
  var k=(e.key||'').toLowerCase();
  if((e.ctrlKey||e.metaKey)&&k==='/'){{e.preventDefault();toast('{_kb_hint}',9000);return;}}
  if(e.ctrlKey||e.metaKey||e.altKey)return;

  if('12345678'.indexOf(e.key)>=0&&e.key.length===1){{
    var ts=mainTabs(),i=parseInt(e.key)-1;
    if(ts.length>i){{e.preventDefault();ts[i].click();}}
    return;
  }}
  if(k==='arrowleft'||k==='arrowright'){{
    var ts2=mainTabs();if(!ts2.length)return;
    var cur=0;for(var j=0;j<ts2.length;j++){{if(ts2[j].getAttribute('aria-selected')==='true')cur=j;}}
    var nx=k==='arrowleft'?Math.max(0,cur-1):Math.min(ts2.length-1,cur+1);
    if(nx!==cur){{e.preventDefault();ts2[nx].click();}}
    return;
  }}
  if(k==='c'){{
    e.stopPropagation();                        // Streamlit 기본 C(캐시 지우기) 차단
    e.preventDefault();
    var ci=d.querySelector('[data-testid="stSidebar"] [data-testid="stChatInputTextArea"]')
         ||d.querySelector('[data-testid="stSidebar"] [data-testid="stChatInput"] textarea')
         ||d.querySelector('[data-testid="stChatInputTextArea"]');
    if(ci){{ci.scrollIntoView({{behavior:'smooth',block:'center'}});ci.focus();}}
    else{{hk('hk_chat');}}                       // 사이드바가 접혀 있으면 AI 탭으로
    return;
  }}
  if(k==='b'){{                                  // 순수 클라이언트 — 파이썬 왕복 없음
    e.preventDefault();
    var sc=d.querySelector('[data-testid="stSidebarCollapsedControl"] button')
         ||d.querySelector('[data-testid="stExpandSidebarButton"]')
         ||d.querySelector('[data-testid="stCollapseSidebarButton"]');
    if(sc)sc.click();
    return;
  }}
  if(e.key==='?'||k==='/'){{e.preventDefault();hk('hk_keymap');return;}}
  if(k==='h'){{e.preventDefault();hk('hk_guide');return;}}
  if(k==='t'){{e.preventDefault();hk('hk_theme');return;}}
  if(k==='l'){{e.preventDefault();hk('hk_lang');return;}}
  if(k==='v'){{e.preventDefault();hk('hk_compact');return;}}
  if(k==='r'){{e.preventDefault();hk('hk_refresh');return;}}
  if(k==='a'){{e.preventDefault();hk('hk_autorf');return;}}
}}
if(d.__opsKbd){{try{{d.removeEventListener('keydown',d.__opsKbd,true);}}catch(_e){{}}}}
d.__opsKbd=handler;
d.addEventListener('keydown',handler,true);
if(!d.__opsKbdToast){{d.__opsKbdToast=true;setTimeout(function(){{toast('{_kb_hint}',4200)}},700);}}
}})();
</script></body></html>"""
_html(_kb_js, height=0, scrolling=False)

# C 로 AI 탭에 막 넘어온 직후라면, 렌더가 끝난 지금 입력창에 커서를 둔다.
if st.session_state.pop("_ops_focus_chat", False):
    _html("""<script>
(function(){var d=window.parent.document;
setTimeout(function(){
  var ci=d.querySelector('[data-testid="stChatInputTextArea"]')
       ||d.querySelector('[data-testid="stChatInput"] textarea');
  if(ci){ci.scrollIntoView({behavior:'smooth',block:'center'});ci.focus();}
},300);})();
</script>""", height=0, scrolling=False)

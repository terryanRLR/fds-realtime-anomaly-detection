"""
detect_workbench — '탐지 작업대' 조립 계층 (dashboard.py 세션5 ↔ ops_dashboard AI 탭 공용)

왜 이 모듈이 생겼나
  같은 화면이 두 앱에 **각각 복사**돼 있었다(dashboard.py 세션5 / ops AI 탭).
  부품(`detect_ui.py` 렌더 · `detect_io.py` 모델/DB I/O)은 이미 공유했는데,
  그 부품을 **조립하는 계층**만 두 벌이었다. 그 결과 한쪽만 고쳐지는 사고가
  반복됐다 — Streamlit 의 `value=` 함정(key 가 있으면 value 무시)만으로 3번:

    ① ops 이메일 미리보기 (v24)        보이는 본문 ≠ 실제 발송 본문
    ② dashboard 프롬프트 편집기 (v26)  '기본값 복원'이 화면에 반영 안 됨
    ③ dashboard RAG 편집기 (v26)       [저장]이 남의 수정을 되돌림

  거기에 dashboard 직접입력은 자동채움 버튼이 **눌리는 순간 예외로 죽고**,
  row 에 계좌 이력이 빠져 고위험 프리셋조차 정상(m)으로 판정됐다(v26 A1).
  **셋 다 예외가 안 나거나 조용히 실패한다.** 눈으로는 못 찾는다.

무엇을 합치고 무엇을 남겼나
  합친 것 — 갈리면 **같은 값에 다른 결과**가 나오는 것들
    · 직접입력 계약   AUTOFILL_PRESET · build_manual_row · render_account_history
    · 편집기 계층     render_prompt_editor · render_rag_editor · prompt_overrides
    · 입력 6종 + 액션바  render_input_modes  (ops 만 사용)
  남긴 것 — **설계상 다른** 것 (합치면 제품이 망가진다)
    · 발송 경로: ops = 편집 가능한 평문 + 감사 로그
                 dashboard = 리치 HTML + 강제 마스킹 첨부 리포트
    · 화면 스타일: dashboard 는 `_seg_nav`·컴팩트 뷰·`t3_src` 등 자기 것을 갖는다

설계 원칙 (어기면 "ops 전용 모듈"이 되어 공용화가 깨진다)
    · 앱 전역 상태를 **읽지 않는다** — 필요한 값은 전부 인자로 받는다
    · 위젯 key 에 `key_prefix` 를 붙인다 — 두 앱이 같은 세션을 써도 안 겹친다
    · 헬퍼(_send/_redo_step/LLM 빌더·RAG 캐시)를 **콜백**으로 받는다

⚠ i18n
  두 앱의 키 접두어가 다르다(`s5.*` vs `ai.*`/`det.*`) — 접미어는 같다.
  그래서 `key_ns` 로 접두어를 받고, 키가 없으면 `_tf()` 가 접미어로 한 번 더
  찾아 한국어 폴백을 쓴다. 한쪽 i18n 에 종속되면 나머지 앱이 이 모듈을 못 쓴다.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from pathlib import Path

import pandas as pd
import streamlit as st

DETECT_WORKBENCH_VERSION = "v3"

log = logging.getLogger("detect_workbench")

try:
    from pipeline import detect_io as dio
except ImportError:                                    # pragma: no cover
    import detect_io as dio

# 입력 모드 — 순서가 곧 탭 순서다.
#   'dataset' 이 맨 앞·기본값인 이유: 호출부(사이드바)가 고른 데이터셋을 그대로
#   쓰는 경로라 손이 가장 자주 가고, parquet X/y 페어까지 다뤄 경로 입력보다 범용적이다.
MODES = ("dataset", "manual", "test", "train", "synthetic", "folder")

# t(key) 가 키를 그대로 돌려주면(= 그 앱 i18n 에 없는 키) 이 폴백을 쓴다.
#   두 앱의 키 접두어가 다르다(`ai.*`/`det.*` vs `s5.*`) — 공용 모듈이 한쪽
#   i18n 에 종속되면 나머지 앱이 이 모듈을 못 쓴다.
_FALLBACK = {
    "det.tab1": "✏️ 직접입력", "det.tab2": "📄 test.csv", "det.tab3": "📊 train.csv",
    "det.tab4": "🧪 합성생성", "det.tab5": "📁 폴더배치",
    "det.sample_n": "추출 건수", "det.seed": "시드(-1=무작위)",
    "det.extract": "추출", "det.run": "▶ 탐지 실행", "det.row_select": "행 선택",
    "det.gen_n": "생성 건수", "det.gen_type": "사기 유형", "det.gen_run": "생성",
    "det.folder_path": "폴더 경로", "det.folder_scan": "스캔",
    "det.autofill": "🎲 고위험 시나리오 자동입력",
    "det.section_txn": "거래", "det.section_env": "환경", "det.section_flags": "플래그",
    "det.amount": "거래금액", "det.distance": "거리(km)", "det.balance": "계좌잔액",
    "det.channel": "채널", "det.os": "운영체제",
    "det.no_testcsv": "파일을 읽을 수 없습니다: {path}",
    "det.no_csv": "CSV 가 없습니다: {path}",
    "det.files_found": "{n}개 파일 발견",
}


_FALLBACK.update({
    # 🖊 프롬프트 편집기 — 두 앱의 접미어는 같고 접두어만 다르다(`ai.` / `s5.`)
    "prompt_editor_title": "🖊 프롬프트 편집기",
    "prompt_editor_help": "LLM 에 보내는 지시문을 직접 고칩니다. 재시작이 필요 없습니다.",
    "prompt_tab_analysis": "원인 분석", "prompt_tab_slack": "Slack",
    "prompt_tab_email": "Email", "prompt_tab_batch": "배치",
    "prompt_vars_label": "쓸 수 있는 자리표시자",
    "prompt_save": "💾 저장", "prompt_reset": "↩ 기본값 복원",
    "prompt_active": "✅ 사용자 프롬프트가 적용 중입니다",
    "prompt_store_note": "📀 저장 위치 `{path}` · 적용 중 {n}개 — "
                         "**두 대시보드가 이 파일 한 벌을 함께 씁니다.**",
    "prompt_saved_both": "💾 저장했습니다 — 다른 대시보드에도 적용됩니다",
    "prompt_saved_session": "⚠ 파일 저장 실패({e}) — 이번 세션에만 적용됩니다",
    # 📚 RAG 편집기
    "rag_editor_title": "📚 RAG 지식베이스 편집",
    "rag_editor_help": "LLM 분석에 함께 넣는 참고 문서입니다. 저장하면 다시 색인합니다.",
    "rag_docs_path": "{path} · {n}개 문서",
    "rag_create_samples": "샘플 문서 만들기",
    "rag_saved": "저장했습니다", "rag_reindexed": "재색인을 예약했습니다",
    "rag_deleted": "{name} 을(를) 삭제했습니다",
    "rag_fail": "실패 — {e}", "rag_read_fail": "{name} 읽기 실패 — {e}",
    "rag_save": "💾 저장", "rag_reindex": "🔄 재색인", "rag_delete": "🗑 삭제",
    "rag_delete_confirm": "한 번 더 누르면 {name} 이(가) 영구 삭제됩니다",
    "rag_new_label": "새 문서 이름", "rag_new_btn": "➕ 만들기",
    "rag_new_empty": "이름을 입력하세요",
    "rag_new_bad": "이름에 경로 구분자나 앞점(.)을 쓸 수 없습니다",
    "rag_new_dup": "{name} 은(는) 이미 있습니다",
})


# ── i18n 8단계 신규 키 (한국어 폴백) ─────────────────────────
#   ops 는 ops_ui 의 det.* 키로 4개 국어를 받고, dashboard.py 는 그 키가 없으므로
#   여기 폴백(한국어)을 그대로 쓴다 — 즉 dashboard.py 화면은 변하지 않는다.
_FALLBACK.update({
    "det.acct_hist": "🏦 계좌 이력 — 판정에 크게 영향을 줍니다",
    "det.acct_hist_desc":
        "직접입력은 58개 피처 중 22개만 채웁니다. 나머지는 모델 번들의 기본값이 쓰이는데, "
        "**계좌 이력이 0(거래가 전혀 없던 계좌)** 으로 채워져 있어 무엇을 입력해도 정상으로 "
        "판정되곤 했습니다. 아래 기본값은 `train.csv` 의 **정상 계좌 중앙값** — 즉 '평범한 "
        "실제 계좌'입니다. 값을 0 으로 되돌리면 그 증상이 그대로 재현됩니다.",
    "det.acct_reset": "↩ 계좌 이력 기본값으로",
    "det.acct_reset_help": "train.csv 정상 계좌 중앙값으로 되돌립니다",
    "det.model_line": "🧠 `{model}` · 임계값 {th} — 사이드바에서 바꿉니다",
    "det.model_missing": "⚠ {path} 없음 — 모델 파일을 models/ 에 두세요",
    "det.tab_dataset": "📂 선택 데이터셋",
    "det.save_csv": "💾 CSV 저장",
    "det.send_inbox": "📤 inbox 전송",
    "det.send_inbox_help":
        "워처 감시 폴더({dir})에 CSV로 저장합니다. 워처가 실행 중이면 몇 초 안에 자동 "
        "탐지·알림까지 진행됩니다. 폴더는 사이드바 '📁 경로'에서 바꿉니다.",
    "det.send_ok": "📤 전송 완료 — `{path}`",
    "det.send_newdir": "이 폴더는 방금 새로 만들어졌습니다 — 워처가 감시하는 폴더가 맞는지 "
                       "확인하세요. 다르면 탐지가 일어나지 않습니다.",
    "det.send_fail": "저장 실패 — {e}",
    "det.batch": "📦 일괄 분석 ({n}건)",
    "det.batch_help": "추출한 전체를 '📦 배치 분석' 탭으로 넘깁니다",
    "det.batch_min": "일괄 분석은 2건 이상",
    "det.path_of": "{name} 경로",
    "det.read_fail": "읽기 실패: {name}",
    "det.first_row": "📄 {name} · 첫 행",
    "det.pick_dataset": "사이드바 '📂 데이터셋'에서 먼저 데이터셋을 고르세요",
    "det.scope": "추출 범위",
    "det.scope_help": "특정 사기 유형만 뽑아 모델 반응을 확인할 수 있습니다",
    "det.scope_nolabel": "범위 선택 불가 — 이 데이터셋에는 라벨(Fraud_Type)이 없습니다",
    "det.scope_empty": "'{scope}' 범위에 해당하는 행이 없습니다",
    "det.ds_load_fail": "데이터셋 로드 실패: {e}",
    "det.extracted": "{n}건 추출 · 범위 {scope}",
})

def _tf(t, key: str, **kw) -> str:
    """t(key) 를 부르되, 그 앱에 키가 없으면(키가 그대로 돌아오면) 폴백을 쓴다.

    폴백은 `det.tab1` 같은 전체 키와 `rag_save` 같은 접미어 둘 다로 찾는다 —
    프롬프트/RAG 편집기는 두 앱의 접두어만 다르고(`ai.` vs `s5.`) 접미어가 같다.
    """
    try:
        s = t(key, **kw) if kw else t(key)
    except Exception:                                  # pragma: no cover
        s = key
    if s == key:
        # 전체 키 → 없으면 접두어를 뗀 접미어로 한 번 더
        s = _FALLBACK.get(key) or _FALLBACK.get(key.split(".", 1)[-1], key)
        if kw:
            try:
                s = s.format(**kw)
            except Exception:
                pass
    return s


def _alerter(alert):
    """앱마다 오류 표시 방식이 다르다(st.error vs alert_box). 없으면 기본값."""
    if alert is not None:
        return alert

    def _default(msg, level="error"):
        (st.warning if level in ("warn", "warning") else st.error)(msg)
    return _default


# ══════════════════════════════════════════════════════════
# 직접입력 '계약' — 두 앱이 **반드시** 같아야 하는 부분
#
#   화면(라벨·컬럼·컴팩트 모드)은 앱마다 달라도 된다. 하지만 아래 세 가지가
#   갈리면 **같은 값을 넣어도 다른 판정이 나온다** — 그게 실제로 일어났다:
#     · dashboard.py 는 자동채움이 눌리는 순간 예외로 죽었다(위젯 생성 후 key 수정)
#     · dashboard.py 가 만드는 row 에는 계좌 이력이 아예 없어서, 사기 프리셋조차
#       '거래가 전혀 없던 계좌'로 채워져 정상으로 판정됐다
#   그래서 값 세트·row 조립·계좌 이력을 여기 한 벌만 둔다.
# ══════════════════════════════════════════════════════════

# 폼 최초 진입 기본값 (평범한 정상 거래)
MANUAL_DEFAULTS = {"amount": 500_000, "distance": 50, "balance": 10_000_000,
                   "channel": "ATM", "os": "Windows", "access_medium": "a"}

# 🎲 고위험 시나리오 — 심야 ATM 대액 출금 + 루팅/VPN/미사용단말/정지계좌
AUTOFILL_PRESET = {"amount": -85_000_000, "distance": 480, "balance": 120_000_000,
                   "channel": "ATM", "os": "Others", "access_medium": "a"}
AUTOFILL_FLAGS = ("Customer_rooting_jailbreak_indicator",
                  "Customer_VPN_Indicator",
                  "Customer_flag_terminal_malicious_behavior_1",
                  "Unused_terminal_status",
                  "Recipient_account_suspend_status")

# 직접입력이 다루지 않는 범주형 — 두 앱이 같은 값을 써야 결과가 비교 가능하다
MANUAL_STATIC = {"Customer_credit_rating": "B", "Customer_loan_type": "a",
                 "Error_Code": "a", "Type_General_Automatic": "general",
                 "Customer_Gender": "male"}


def autofill_payload(field_keys: dict, flag_key) -> dict:
    """자동채움이 세션에 넣을 {위젯key: 값}.

    ⚠ 이 dict 는 **위젯을 만들기 전에** 세션에 반영해야 한다. 버튼은 폼 아래에
      있으므로 버튼 안에서 바로 쓰면 "cannot be modified after the widget ...
      is instantiated" 예외가 난다 — 두 앱 모두 그래서 죽어 있었다.
      → 버튼은 `_pending` 플래그만 세우고 rerun, 다음 런의 위젯 생성 전에 소비.

    field_keys: {'amount': 'amount_in', ...}  앱마다 위젯 key 가 다르므로 매핑을 받는다
    flag_key:   플래그명 → 위젯 key 로 바꾸는 콜러블
    """
    out = {}
    for field, wkey in (field_keys or {}).items():
        if field in AUTOFILL_PRESET:
            out[wkey] = AUTOFILL_PRESET[field]
    for fl in AUTOFILL_FLAGS:
        if fl in dio.BINARY_FLAGS:
            out[flag_key(fl)] = True
    return out


def account_history_defaults() -> dict:
    """train.csv 정상 계좌 중앙값. 0 으로 두면 '거래가 전혀 없던 계좌'가 된다."""
    return {k: float(v) for k, v in dio.ACCOUNT_HISTORY_DEFAULTS.items()}


def read_account_history(key_prefix: str) -> dict:
    """세션에 있는 계좌 이력 위젯 값을 읽는다(없으면 기본값)."""
    return {k: float(st.session_state.get(f"{key_prefix}_hist_{k}", v))
            for k, v in account_history_defaults().items()}


def render_account_history(key_prefix: str, *, expanded: bool = False,
                           reset_pending_key: str | None = None, t=None) -> dict:
    """🏦 계좌 이력 편집 패널. 반환: 현재 값 dict.

    화면에 없으면 '보이지 않는 값이 판정을 좌우하는' 상태가 된다 — 실제로 이
    다섯 값 때문에 사기 프리셋이 정상으로 나왔다.
    """
    _rk = reset_pending_key or f"_{key_prefix}_hist_reset_pending"
    for _hk, _hv in account_history_defaults().items():
        st.session_state.setdefault(f"{key_prefix}_hist_{_hk}", _hv)

    with st.expander(_tf(t, "det.acct_hist"), expanded=expanded):
        st.caption(_tf(t, "det.acct_hist_desc"))
        _hc = st.columns(3)
        for _i, (_hk, (_lbl, _help, _step)) in enumerate(
                dio.ACCOUNT_HISTORY_FIELDS.items()):
            with _hc[_i % 3]:
                st.number_input(_lbl, min_value=0.0, step=float(_step),
                                key=f"{key_prefix}_hist_{_hk}", help=_help,
                                format="%.0f")
        if st.button(_tf(t, "det.acct_reset"), key=f"{key_prefix}_hist_reset",
                     help=_tf(t, "det.acct_reset_help")):
            st.session_state[_rk] = True
            st.rerun()
    return read_account_history(key_prefix)


def build_manual_row(*, amount, distance, balance, channel, os_, access_medium,
                     flags: dict | None = None, history: dict | None = None,
                     input_mode: str = "manual") -> dict:
    """직접입력 → 모델에 넣을 row.

    ⚠ `history` 를 생략해도 **기본값(정상 계좌 중앙값)이 들어간다.** 예전
      dashboard.py 처럼 계좌 이력을 아예 빼면 번들 기본값 0 이 쓰여
      '한 달간 거래가 전혀 없던 계좌'가 되고, 사기 프리셋도 정상으로 나온다.
    """
    hist = account_history_defaults()
    if history:
        hist.update({k: float(v) for k, v in history.items() if k in hist})
    return {"Transaction_Amount": amount, "Distance": distance,
            "Account_balance": balance, "Channel": channel,
            "Operating_System": os_, "Access_Medium": access_medium,
            **MANUAL_STATIC, **hist,
            **{k: int(v) for k, v in (flags or {}).items()},
            "_input_mode": input_mode}


# ══════════════════════════════════════════════════════════
# 위젯 상태 헬퍼 — 두 앱이 함께 쓴다
# ══════════════════════════════════════════════════════════
def sync_widget(key: str, source):
    """위젯의 세션 값을 **원본이 바뀌었을 때만** 원본으로 되돌린다.
    반드시 그 위젯을 만들기 **전에** 호출할 것 (생성 후엔 Streamlit 이 막는다).

    왜 필요한가 — Streamlit 은 key 가 이미 세션에 있으면 `value=` 를 **무시한다.**
    그래서 `st.text_area(value=새본문, key="…")` 는 두 번째 렌더부터 새 본문을
    보여주지 않는다. 두 앱에서 실제로 이렇게 깨져 있었다:

      · 🔁 재생성 → 이메일 미리보기는 옛 본문인데 **전송은 새 본문**이 나갔다
        (= 보이는 것과 보내는 것이 달랐다 — 가장 위험한 형태)
      · 프롬프트 '기본값 복원' → 세션 값은 지워지는데 편집창은 그대로였다
      · 임계값 튜닝 → 최소비용 지점이 움직여도 슬라이더는 첫 값에 고정

    원본 해시를 함께 들고 있다가 원본이 바뀐 순간에만 덮어쓴다. 그래서
    **사용자가 손으로 고친 내용은 보존**되고, 원본이 바뀐 경우에만 따라간다.

    ※ 버튼 클릭 → `st.rerun()` 이 위젯 생성 **전에** 일어나는 경우는 Streamlit 이
      알아서 정리하므로 이 헬퍼가 필요 없다. 문제는 위젯이 이미 그려진 **뒤에**
      원본이 바뀌는 경우다.
    """
    tag = f"_src__{key}"
    digest = hashlib.md5(str(source).encode("utf-8", "replace")).hexdigest()
    if key not in st.session_state or st.session_state.get(tag) != digest:
        st.session_state[key] = source
        st.session_state[tag] = digest
    return st.session_state[key]


# ══════════════════════════════════════════════════════════
# 🖊 프롬프트 · 📚 RAG 편집기 — 두 앱이 거의 같은 코드를 두 벌 갖고 있었다
#
#   왜 합치나 (줄 수 때문이 아니다)
#     Streamlit 의 `value=` 함정(key 가 있으면 value 무시)이 **같은 편집기 코드가
#     두 벌**이라는 이유로 세 번 반복됐다:
#       ① ops 이메일 미리보기(v24)   — 보이는 본문 ≠ 실제 발송 본문
#       ② dashboard 프롬프트 편집기(v26) — '기본값 복원'이 화면에 반영 안 됨
#       ③ dashboard RAG 편집기(v26)      — 저장 시 남의 수정을 되돌림
#     셋 다 **예외가 안 난다.** 눈으로는 못 찾고, 코드가 두 벌인 한 계속 재발한다.
#
#   i18n: 두 앱의 접미어는 같고 접두어만 다르다 → `key_ns` 로 받는다("ai" / "s5").
# ══════════════════════════════════════════════════════════
PROMPT_SLOTS = ("analysis", "slack", "email", "batch")

# ── 📀 프롬프트 저장소 — 세션이 아니라 **파일**이 진실이다 ──────────
#
#   왜 파일로 옮겼나
#     오버라이드가 `st.session_state` 에만 살았다. 두 앱은 별개 프로세스라
#     세션이 안 겹치고, 브라우저 탭을 닫으면 그것마저 사라진다. 그래서
#       · dashboard 세션5 에서 프롬프트를 고쳐도 ops 관제 화면은 옛 프롬프트로 분석
#       · 새로고침 한 번에 편집 내용 소실
#     이 둘이 조용히 일어났다 — 예외가 안 나니 "저장했는데 왜 안 먹지"로만 보인다.
#
#   왜 API 키(ov_*/ai_*)는 여전히 분리하나
#     프롬프트는 **분석 결과를 결정하는 내용물**이라 두 화면이 같아야 하고,
#     키·수신처는 **접속 자격**이라 화면마다 달라야 한다(운영/검증 분리).
#     둘을 같은 축으로 다루면 한쪽을 합치는 순간 다른 쪽까지 새어 나간다.
#
#   경로는 FDS_PROMPT_STORE 로 바꿀 수 있다 — 테스트가 실제 프롬프트를
#   덮어쓰지 않도록 하는 안전장치이자, 여러 배포본이 한 벌을 공유하는 통로다.
PROMPT_STORE_ENV = "FDS_PROMPT_STORE"
_DEFAULT_STORE = Path(__file__).resolve().parent.parent / "prompts" / "overrides.json"

# (경로, mtime, ns) → 내용. 분석할 때마다 부르는 경로라 mtime 이 그대로면 안 읽는다.
_store_cache: dict = {"path": None, "mtime": -1.0, "data": {}}


def prompt_store_path() -> Path:
    return Path(os.environ.get(PROMPT_STORE_ENV) or _DEFAULT_STORE)


def load_prompt_store() -> dict:
    """파일에 저장된 오버라이드. 없거나 깨졌으면 빈 dict (= 기본 프롬프트)."""
    p = prompt_store_path()
    try:
        mt = p.stat().st_mtime
    except OSError:
        _store_cache.update(path=str(p), mtime=-1.0, data={})
        return {}
    if _store_cache["path"] == str(p) and _store_cache["mtime"] == mt:
        return dict(_store_cache["data"])
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        data = {s: str(raw.get(s) or "") for s in PROMPT_SLOTS if raw.get(s)}
    except (OSError, ValueError) as e:
        # 깨진 파일이 앱을 막으면 안 된다 — 기본 프롬프트로 조용히 내려간다
        log.warning(f"프롬프트 저장소를 읽을 수 없습니다 → 기본 프롬프트 사용: {e}")
        data = {}
    _store_cache.update(path=str(p), mtime=mt, data=dict(data))
    return dict(data)


def save_prompt_override(slot: str, text: str) -> tuple[bool, str]:
    """슬롯 하나를 저장(빈 문자열이면 삭제). (성공, 메시지) 반환.

    ⚠ 다른 앱이 같은 파일을 동시에 고칠 수 있다. 그래서 쓰기 **직전에** 다시 읽어
      합치고(read-modify-write), 임시 파일 → os.replace 로 원자적으로 바꾼다.
      마지막 쓰기가 이기는 창이 남지만 슬롯 단위로는 서로를 덮지 않는다.
    """
    if slot not in PROMPT_SLOTS:
        return False, f"알 수 없는 슬롯: {slot}"
    p = prompt_store_path()
    text = (text or "").strip()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        cur = {}
        if p.exists():
            try:
                cur = {k: v for k, v in json.loads(p.read_text(encoding="utf-8")).items()
                       if k in PROMPT_SLOTS and v}
            except ValueError:
                cur = {}                       # 깨진 파일은 이번 저장으로 새로 쓴다
        if text:
            cur[slot] = text
        else:
            cur.pop(slot, None)
        cur["_saved_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, p)                     # 원자적 교체 — 반쯤 쓰인 파일이 안 보인다
    except OSError as e:
        log.warning(f"프롬프트 저장 실패: {e}")
        return False, str(e)
    _store_cache.update(path=None, mtime=-1.0, data={})   # 다음 읽기에서 새로 읽는다
    return True, str(p)


def prompt_overrides() -> dict:
    """편집기가 저장해 둔 사용자 프롬프트. LLMAnalyzer(prompt_overrides=…) 에 그대로 넣는다.

    두 앱의 `_build_llm_analyzer` 가 각자 같은 4키 dict 를 하드코딩하고 있었다.
    슬롯이 하나 늘면 두 곳을 다 고쳐야 하는데, 그러다 한쪽을 빠뜨리면
    "편집기에서 저장했는데 그 프롬프트가 안 먹는다"가 된다.

    **파일이 유일한 진실이다.** 세션 사본(prompt_ov_*)은 파일 저장이 실패했을 때만
    남는 비상 경로다 — 평소에 사본이 남아 있으면 상대 앱이 나중에 저장한 프롬프트를
    이 세션이 계속 무시하게 되어, 파일로 옮긴 의미가 사라진다.
    """
    store = load_prompt_store()
    return {s: (st.session_state.get(f"prompt_ov_{s}") or store.get(s, "") or "")
            for s in PROMPT_SLOTS}


def _prompt_defaults() -> dict:
    """기본 템플릿 — llm_analyzer / batch_analyzer 가 단일 진실이다."""
    out = {s: "" for s in PROMPT_SLOTS}
    helps = {s: "" for s in PROMPT_SLOTS}
    try:
        from pipeline.llm_analyzer import (DEFAULT_ANALYSIS_PROMPT_TEMPLATE,
                                           DEFAULT_SLACK_PROMPT_TEMPLATE,
                                           DEFAULT_EMAIL_PROMPT_TEMPLATE,
                                           PROMPT_VARS_HELP)
        out.update(analysis=DEFAULT_ANALYSIS_PROMPT_TEMPLATE,
                   slack=DEFAULT_SLACK_PROMPT_TEMPLATE,
                   email=DEFAULT_EMAIL_PROMPT_TEMPLATE)
        helps.update(analysis=PROMPT_VARS_HELP, slack=PROMPT_VARS_HELP,
                     email=PROMPT_VARS_HELP)
    except ImportError:                                # pragma: no cover
        pass
    try:
        from pipeline.batch_analyzer import (DEFAULT_BATCH_PROMPT_TEMPLATE,
                                             PROMPT_VARS_HELP_BATCH)
        out["batch"] = DEFAULT_BATCH_PROMPT_TEMPLATE
        helps["batch"] = PROMPT_VARS_HELP_BATCH
    except ImportError:                                # pragma: no cover
        pass
    return {"tpl": out, "help": helps}


def render_prompt_editor(*, t, key_ns: str = "ai", height: int = 220,
                         vars_label: bool = False, expanded: bool = False) -> None:
    """🖊 분석/Slack/Email/배치 프롬프트 편집기 (expander 포함).

    vars_label: 자리표시자 안내에 굵은 라벨을 붙일지(dashboard 세션5 스타일).
    """
    _d = _prompt_defaults()
    _store = load_prompt_store()
    with st.expander(_tf(t, f"{key_ns}.prompt_editor_title"), expanded=expanded):
        st.caption(_tf(t, f"{key_ns}.prompt_editor_help"))
        # 어느 파일이 두 앱을 잇는지 화면에 밝힌다 — "저장했는데 저쪽엔 왜 안 뜨지"의 답
        st.caption(_tf(t, f"{key_ns}.prompt_store_note",
                       path=str(prompt_store_path()), n=len(_store)))
        _tabs = st.tabs([_tf(t, f"{key_ns}.prompt_tab_{s}") for s in PROMPT_SLOTS])
        for _tab, _slot in zip(_tabs, PROMPT_SLOTS):
            with _tab:
                _vh = _d["help"].get(_slot) or ""
                if _vh:
                    st.caption(f"**{_tf(t, f'{key_ns}.prompt_vars_label')}** — {_vh}"
                               if vars_label else _vh)
                _skey = f"prompt_ov_{_slot}"
                # 표시 우선순위 = prompt_overrides() 와 같아야 한다. 화면에 보이는
                #   프롬프트와 LLM 에 실제로 가는 프롬프트가 갈리면 안 된다.
                _cur = (st.session_state.get(_skey) or _store.get(_slot, "")
                        or _d["tpl"].get(_slot, ""))
                # ⚠ value= 를 쓰면 안 된다 — 모듈 상단 주석의 세 번 반복된 그 버그다.
                sync_widget(f"prompt_ta_{_slot}", _cur)
                _edited = st.text_area(_tf(t, f"{key_ns}.prompt_tab_{_slot}"),
                                       height=height, label_visibility="collapsed",
                                       key=f"prompt_ta_{_slot}")
                _c1, _c2 = st.columns(2)
                if _c1.button(_tf(t, f"{key_ns}.prompt_save"),
                              key=f"prompt_save_{_slot}", width="stretch"):
                    _txt = (_edited or "").strip()
                    _ok, _msg = save_prompt_override(_slot, _txt)
                    if _ok:
                        # ★ 파일에 들어갔으면 세션 사본은 **지운다.** 사본을 남기면
                        #   상대 앱이 나중에 저장한 프롬프트를 이 세션이 계속 무시한다
                        #   — 공유하려고 파일로 옮겨놓고 세션이 이기면 헛일이다.
                        st.session_state.pop(_skey, None)
                    else:
                        # 파일 저장이 실패해도 이번 세션 편집은 살린다(기능 저하).
                        st.session_state[_skey] = _txt
                    st.toast(_tf(t, f"{key_ns}.prompt_saved_both") if _ok
                             else _tf(t, f"{key_ns}.prompt_saved_session", e=_msg))
                    st.rerun()
                if _c2.button(_tf(t, f"{key_ns}.prompt_reset"),
                              key=f"prompt_reset_{_slot}", width="stretch"):
                    st.session_state.pop(_skey, None)
                    save_prompt_override(_slot, "")     # 파일에서도 지운다
                    st.rerun()
                if st.session_state.get(_skey) or _store.get(_slot):
                    st.caption(_tf(t, f"{key_ns}.prompt_active"))


def render_rag_editor(*, t, key_ns: str = "ai", on_change=None,
                      height: int = 240, alert=None, expanded: bool = False) -> None:
    """📚 RAG 지식베이스 문서 편집 (expander 포함).

    on_change(): 문서가 바뀌었을 때 호출 — 앱마다 자기 RAG 캐시를 비운다
      (`_get_rag_cached.clear()`). 이걸 안 부르면 편집해도 옛 색인이 계속 쓰인다.
    """
    _al = _alerter(alert)
    _touch = on_change or (lambda: None)

    with st.expander(_tf(t, f"{key_ns}.rag_editor_title"), expanded=expanded):
        st.caption(_tf(t, f"{key_ns}.rag_editor_help"))
        try:
            from pipeline.rag_searcher import DOCS_DIR as _RAG_DOCS, RAGSearcher as _RS
            _dir = Path(_RAG_DOCS)
            _dir.mkdir(parents=True, exist_ok=True)
            _files = sorted(_dir.glob("*.md"))
            st.caption(_tf(t, f"{key_ns}.rag_docs_path",
                           path=str(_dir.resolve()), n=len(_files)))

            if not _files:
                if st.button(_tf(t, f"{key_ns}.rag_create_samples"),
                             key="rag_mk_samples", width="stretch"):
                    try:
                        # RAGSearcher.__init__ 은 Chroma 초기화까지 한다. 문서 생성만
                        # 필요하므로 인스턴스 없이 메서드만 부른다.
                        object.__new__(_RS)._create_sample_docs()
                        _touch()
                        st.toast(_tf(t, f"{key_ns}.rag_saved")); st.rerun()
                    except Exception as e:
                        _al(_tf(t, f"{key_ns}.rag_fail", e=e), "error")
            else:
                for _tab, _f in zip(st.tabs([f.name for f in _files]), _files):
                    with _tab:
                        try:
                            _cur = _f.read_text(encoding="utf-8")
                        except Exception as e:
                            _cur = ""
                            _al(_tf(t, f"{key_ns}.rag_read_fail", name=_f.name, e=e),
                                "error")
                        # ⚠ value= 금지 — 파일이 디스크에서 바뀌었는데 편집창이 옛
                        #   내용이면, [저장]이 **남의 수정을 되돌린다.**
                        sync_widget(f"rag_ta_{_f.name}", _cur)
                        _ed = st.text_area(_f.name, height=height,
                                           label_visibility="collapsed",
                                           key=f"rag_ta_{_f.name}")
                        _c1, _c2, _c3 = st.columns(3)
                        if _c1.button(_tf(t, f"{key_ns}.rag_save"),
                                      key=f"rag_save_{_f.name}", width="stretch"):
                            try:
                                _f.write_text(_ed, encoding="utf-8")
                                _touch()               # 캐시 폐기 → 재임베딩
                                st.toast(_tf(t, f"{key_ns}.rag_saved")); st.rerun()
                            except Exception as e:
                                _al(_tf(t, f"{key_ns}.rag_fail", e=e), "error")
                        if _c2.button(_tf(t, f"{key_ns}.rag_reindex"),
                                      key=f"rag_reidx_{_f.name}", width="stretch"):
                            try:
                                # FDS_CHROMA_DIR 로 위치가 바뀔 수 있으니 경로를
                                # 하드코딩하지 않고 클래스 속성을 그대로 쓴다.
                                _sig = Path(_RS._SIG_PATH)
                                if _sig.exists():
                                    _sig.unlink()      # 서명 삭제 → 다음 init 에서 재구축
                                _touch()
                                st.toast(_tf(t, f"{key_ns}.rag_reindexed")); st.rerun()
                            except Exception as e:
                                _al(_tf(t, f"{key_ns}.rag_fail", e=e), "error")
                        # 삭제는 2단계 — 한 번 더 눌러야 지운다
                        if _c3.button(_tf(t, f"{key_ns}.rag_delete"),
                                      key=f"rag_del_{_f.name}", width="stretch"):
                            if st.session_state.get(f"_rag_del_ok_{_f.name}"):
                                try:
                                    _f.unlink(); _touch()
                                    st.session_state.pop(f"_rag_del_ok_{_f.name}", None)
                                    st.toast(_tf(t, f"{key_ns}.rag_deleted",
                                                 name=_f.name)); st.rerun()
                                except Exception as e:
                                    _al(_tf(t, f"{key_ns}.rag_fail", e=e), "error")
                            else:
                                st.session_state[f"_rag_del_ok_{_f.name}"] = True
                                _al(_tf(t, f"{key_ns}.rag_delete_confirm",
                                        name=_f.name), "warn")

            st.divider()
            _n1, _n2 = st.columns([3, 1])
            _new = _n1.text_input(_tf(t, f"{key_ns}.rag_new_label"),
                                  key="rag_new_name", placeholder="my_scenarios.md")
            if _n2.button(_tf(t, f"{key_ns}.rag_new_btn"), key="rag_new_btn",
                          width="stretch"):
                _nm = (_new or "").strip()
                if not _nm:
                    _al(_tf(t, f"{key_ns}.rag_new_empty"), "warn")
                elif ("/" in _nm) or ("\\" in _nm) or _nm.startswith("."):
                    _al(_tf(t, f"{key_ns}.rag_new_bad"), "error")   # 경로 탈출 방지
                else:
                    if not _nm.endswith(".md"):
                        _nm += ".md"
                    _np = _dir / _nm
                    if _np.exists():
                        _al(_tf(t, f"{key_ns}.rag_new_dup", name=_nm), "warn")
                    else:
                        _np.write_text(f"# {_nm[:-3]}\n\n", encoding="utf-8")
                        _touch()
                        st.toast(_tf(t, f"{key_ns}.rag_saved")); st.rerun()
        except Exception as e:
            _al(_tf(t, f"{key_ns}.rag_fail", e=e), "error")


# ══════════════════════════════════════════════════════════
# 입력 모드 6종 + 액션 바
# ══════════════════════════════════════════════════════════
def render_input_modes(*, t, lang: str = "ko", key_prefix: str = "det",
                       model_name: str = "", model_path: str = "",
                       threshold: float = 0.5,
                       dataset_name=None, dataset_found=None,
                       inbox_dir: str = "inbox",
                       fraud_label=None,
                       on_batch=None,
                       tab_key: str | None = None,
                       force_tab_key: str | None = None,
                       pending_scope_key: str | None = None,
                       modes=MODES) -> dict | None:
    """'탐지할 거래 1건'을 6가지 방법 중 하나로 고르게 하고, 그 row 를 돌려준다.

    **이 함수는 탐지하지 않는다.** ML 분류·DB 적재·경보·LLM 분석은 전부 호출부
    소관이다. 두 앱의 그 뒤 처리가 완전히 다르기 때문이다 — ops 는 원장에
    `ops:` 소스 태그로 적재하고 ops_alert 로 경보를 쏘지만, dashboard.py 는
    자체 발송 경로(리치 비주얼·HTML 메일·첨부)를 쓴다. 억지로 합치면 콜백이
    열 개 넘게 붙어서 '공용 모듈'이 아니라 '인자로 위장한 전역'이 된다.

    반환: 탐지할 row(dict) 또는 None. `_input_mode` 키에 출처가 들어 있다.

    key_prefix: 위젯 key 접두어. **두 앱이 같은 세션을 공유해도 안 겹치게** 한다.
      ops 는 "det" 를 쓴다(기존 key 를 그대로 유지해야 사용자 상태가 안 날아간다).
    on_batch(rows): '📦 일괄 분석' 버튼 콜백. None 이면 버튼을 숨긴다.
    """
    def _k(name: str) -> str:
        return f"{key_prefix}_{name}"

    _tab_key = tab_key or f"{key_prefix}_input_tab"
    _force_key = force_tab_key or f"_force_{key_prefix}_tab"
    _scope_key = pending_scope_key or "_pending_scope"
    _flabel = fraud_label or (lambda c, *a, **kw: str(c).upper())

    st.caption(_tf(t, "det.model_line", model=model_name, th=f"{float(threshold):.2f}"))
    if model_path and not Path(model_path).exists():
        st.warning(_tf(t, "det.model_missing", path=model_path))

    _LBL = {"dataset": _tf(t, "det.tab_dataset"), "manual": _tf(t, "det.tab1"),
            "test": _tf(t, "det.tab2"), "train": _tf(t, "det.tab3"),
            "synthetic": _tf(t, "det.tab4"), "folder": _tf(t, "det.tab5")}
    _order = [m for m in modes if m in _LBL]
    _labels = [_LBL[m] for m in _order]

    # 챗봇 에이전트가 입력 탭을 바꿀 수 있도록 예약값을 **위젯 생성 전에** 소비한다
    _fdt = st.session_state.pop(_force_key, None)
    if _fdt and _fdt in _LBL:
        st.session_state[_tab_key] = _LBL[_fdt]
    _tabs = st.tabs(_labels, key=_tab_key, default=_LBL[_order[0]])
    _T = dict(zip(_order, _tabs))
    row_to_predict = None

    # ══════════════════════════════════════════════════════
    # 💾 액션 바 — [CSV 저장 | inbox 전송 | 탐지 실행 | 일괄 분석]
    #   추출·합성한 데이터가 탐지에만 쓰이고 사라지던 문제를 해결한다.
    # ══════════════════════════════════════════════════════
    def _action_row(rows, sel_row, key, stem):
        """4버튼 한 줄. '탐지 실행'을 누르면 그 row 를 반환, 아니면 None."""
        if not rows:
            return None
        _clean = [{k: v for k, v in r.items() if not str(k).startswith('_')} for r in rows]
        _df = pd.DataFrame(_clean)
        _ts = time.strftime('%Y%m%d_%H%M%S')
        picked = None
        a1, a2, a3, a4 = st.columns([0.85, 0.9, 1.0, 1.25])
        with a1:
            st.download_button(_tf(t, "det.save_csv"),
                               _df.to_csv(index=False).encode('utf-8-sig'),
                               file_name=f"{stem}_{_ts}.csv", mime="text/csv",
                               key=f"dl_{key}", width="stretch")
        with a2:
            _ibx_cfg = inbox_dir or 'inbox'
            if st.button(_tf(t, "det.send_inbox"), key=f"ib_{key}", width="stretch",
                         help=_tf(t, "det.send_inbox_help", dir=_ibx_cfg)):
                try:
                    _ibx = Path(_ibx_cfg)
                    _new_dir = not _ibx.is_dir()
                    _ibx.mkdir(parents=True, exist_ok=True)
                    _fp = _ibx / f"{stem}_{_ts}.csv"
                    # 워처가 '쓰는 중인 반쪽 파일'을 읽지 않도록 임시파일 → 원자적 교체
                    _tmp = _fp.with_name(_fp.name + ".tmp")
                    _df.to_csv(_tmp, index=False, encoding='utf-8-sig')
                    _tmp.replace(_fp)
                    # 절대 경로를 보여준다 — 워처가 다른 폴더를 보고 있으면
                    #   "보냈는데 아무 일도 안 일어난다"의 원인이 이것이다
                    st.success(_tf(t, "det.send_ok", path=_fp.resolve()))
                    if _new_dir:
                        st.warning(_tf(t, "det.send_newdir"))
                except Exception as _ibe:
                    st.error(_tf(t, "det.send_fail", e=_ibe))
        with a3:
            if st.button(_tf(t, "det.run"), key=f"run_{key}", type="primary", width="stretch"):
                picked = sel_row
        with a4:
            if on_batch is not None and len(rows) >= 2:
                if st.button(_tf(t, "det.batch", n=len(rows)), key=f"batch_{key}",
                             width="stretch", help=_tf(t, "det.batch_help")):
                    on_batch(rows)
            elif on_batch is not None:
                st.caption(_tf(t, "det.batch_min"))
        return picked

    # ── 직접입력 ──
    if "manual" in _T:
        with _T["manual"]:
            # ⚠️ 자동채움 예약값은 **위젯을 만들기 전에** 소비한다.
            #   버튼은 위젯보다 아래에 있어서, 거기서 세션 값을 바로 쓰면
            #   "cannot be modified after the widget ... is instantiated" 예외가 난다.
            #   그래서 자동채움 버튼이 눌리는 순간 죽고, 그 아래 [탐지 실행] 렌더까지
            #   끊겼다 — 사기 프리셋이 사기를 못 만든 게 아니라 동작한 적이 없었다.
            _FIELD_WK = {"amount": _k('amount'), "distance": _k('dist'),
                         "balance": _k('bal'), "channel": _k('ch'), "os": _k('os')}
            if st.session_state.pop(f"_{key_prefix}_autofill_pending", False):
                st.session_state.update(
                    autofill_payload(_FIELD_WK, lambda f: _k(f"flag_{f}")))
                st.session_state[f"_{key_prefix}_hist_reset_pending"] = True

            # 계좌 이력 되돌리기도 같은 규칙 — 위젯 생성 **전에** 값을 넣는다
            if st.session_state.pop(f"_{key_prefix}_hist_reset_pending", False):
                for _hk, _hv in account_history_defaults().items():
                    st.session_state[_k(f"hist_{_hk}")] = _hv

            for _f, _wk in _FIELD_WK.items():
                st.session_state.setdefault(_wk, MANUAL_DEFAULTS[_f])

            m1, m2, m3 = st.columns(3)
            with m1:
                st.caption(_tf(t, "det.section_txn"))
                amount = st.number_input(_tf(t, "det.amount"), -400_000_000, 400_000_000,
                                         step=100_000, key=_k('amount'))
                distance = st.slider(_tf(t, "det.distance"), 0, 620, key=_k('dist'))
                balance = st.number_input(_tf(t, "det.balance"), -50_000_000, 410_000_000,
                                          step=100_000, key=_k('bal'))
            with m2:
                st.caption(_tf(t, "det.section_env"))
                channel = st.selectbox(_tf(t, "det.channel"), dio.CAT_OPTIONS['Channel'],
                                       key=_k('ch'))
                os_ = st.selectbox(_tf(t, "det.os"), dio.CAT_OPTIONS['Operating_System'],
                                   key=_k('os'))
                acc_med = st.selectbox("Access_Medium", dio.CAT_OPTIONS['Access_Medium'],
                                       key=_k('am'))
            with m3:
                st.caption(_tf(t, "det.section_flags"))
                flag_vals = {}
                for _fk in dio.BINARY_FLAGS[:12]:
                    if _k(f"flag_{_fk}") not in st.session_state:
                        st.session_state[_k(f"flag_{_fk}")] = False
                    flag_vals[_fk] = int(st.checkbox(_fk.replace("_", " "),
                                                     key=_k(f"flag_{_fk}")))

            _hist = render_account_history(key_prefix, t=t)

            fa1, fa2 = st.columns([1, 1.4])
            with fa1:
                if st.button(_tf(t, "det.autofill"), key=_k('autofill'), width="stretch"):
                    # 값 주입은 위쪽 예약 소비 지점에서 (위젯 생성 전에만 가능)
                    st.session_state[f"_{key_prefix}_autofill_pending"] = True
                    st.rerun()
            with fa2:
                if st.button(_tf(t, "det.run"), type="primary", key=_k('run_manual'),
                             width="stretch"):
                    row_to_predict = build_manual_row(
                        amount=amount, distance=distance, balance=balance,
                        channel=channel, os_=os_, access_medium=acc_med,
                        flags=flag_vals, history=_hist)

    # ── test.csv / train.csv — 로더 로직이 같아 한 함수로 묶는다 ──
    #   (원본은 두 탭이 거의 같은 25줄을 각각 들고 있었다)
    def _csv_tab(mode: str, slot: str, rows_slot: str, default_path: str, stacked: bool):
        nonlocal row_to_predict
        if stacked:
            path = st.text_input(_tf(t, "det.path_of", name=default_path), default_path,
                                 key=_k(f'{mode}_path'))
            n = st.number_input(_tf(t, "det.sample_n"), 1, 50, 1, key=_k(f'{slot}_n'))
            seed = st.number_input(_tf(t, "det.seed"), -1, 9999, -1, key=_k(f'{slot}_seed'))
        else:
            c1, c2, c3 = st.columns([1.5, 1.5, 1], vertical_alignment="bottom")
            path = c1.text_input(_tf(t, "det.path_of", name=default_path), default_path,
                                 key=_k(f'{mode}_path'))
            n = c2.number_input(_tf(t, "det.sample_n"), 1, 50, 1, key=_k(f'{slot}_n'))
            seed = c3.number_input(_tf(t, "det.seed"), -1, 9999, -1, key=_k(f'{slot}_seed'))
        if st.button(_tf(t, "det.extract"), key=_k(f'run_{mode}')):
            df = dio.load_test_df(path)                # 로더는 test/train 동일
            if df is not None:
                st.session_state[_k(rows_slot)] = df.sample(
                    min(int(n), len(df)),
                    random_state=dio.resolve_seed(seed)).to_dict('records')
            else:
                st.error(_tf(t, "det.no_testcsv", path=path))
        rows = st.session_state.get(_k(rows_slot))
        if rows:
            st.dataframe(pd.DataFrame(rows), width="stretch", height=180)
            i = (st.selectbox(_tf(t, "det.row_select"), range(len(rows)),
                              format_func=lambda i: f"#{i+1} · {rows[i].get('ID', i)}",
                              key=_k(f'{slot}_sel')) if len(rows) > 1 else 0)
            sr = dict(rows[i])
            sr['_input_mode'] = f'{mode}_csv'
            if sr.get('Fraud_Type'):
                sr['_true_label'] = sr['Fraud_Type']
            picked = _action_row(rows, sr, mode, f"{mode}_sample")
            if picked is not None:
                row_to_predict = picked

    if "test" in _T:
        with _T["test"]:
            _csv_tab("test", "t2", "tab2_rows", "data/test.csv", stacked=False)
    if "train" in _T:
        with _T["train"]:
            _csv_tab("train", "t3", "tab3_rows", "data/train.csv", stacked=True)

    # ── 합성생성 ──
    if "synthetic" in _T:
        with _T["synthetic"]:
            g1, g2, g3, g4 = st.columns([1.4, 1.4, 2, 0.9], vertical_alignment="bottom")
            g_n = g1.number_input(_tf(t, "det.gen_n"), 1, 500, 20, key=_k('g_n'))
            g_seed = g2.number_input(_tf(t, "det.seed"), -1, 9999, -1, key=_k('g_seed'))
            g_type = g3.selectbox(_tf(t, "det.gen_type"), ["random"] + list("abcdefghijkl"),
                                  key=_k('g_type'))
            if g4.button(_tf(t, "det.gen_run"), key=_k('run_gen'), width="stretch"):
                try:
                    from pipeline.data_streamer import DataStreamer
                    import numpy as _np
                    _np.random.seed(dio.resolve_seed(g_seed))
                    streamer = DataStreamer(
                        train_path=st.session_state.get(_k('train_path'), 'data/train.csv'))
                    rows_syn = streamer.from_synthetic(
                        n=int(g_n), fraud_type=None if g_type == "random" else g_type)
                    for r in rows_syn:
                        r['_input_mode'] = 'synthetic'
                    st.session_state[_k('tab4_rows')] = rows_syn
                except Exception as e:
                    st.error(f"{e}")
            if st.session_state.get(_k('tab4_rows')):
                rp4 = st.session_state[_k('tab4_rows')]
                st.dataframe(pd.DataFrame(
                    [{k: v for k, v in r.items() if not str(k).startswith('_')} for r in rp4]),
                    width="stretch", height=180)
                si4 = (st.selectbox(_tf(t, "det.row_select"), range(len(rp4)),
                                    format_func=lambda i: f"#{i+1}", key=_k('t4_sel'))
                       if len(rp4) > 1 else 0)
                _picked = _action_row(rp4, dict(rp4[si4]), "syn", f"synthetic_{g_type}")
                if _picked is not None:
                    row_to_predict = _picked

    # ── 폴더배치 ──
    if "folder" in _T:
        with _T["folder"]:
            folder_path = st.text_input(_tf(t, "det.folder_path"), "data/",
                                        key=_k('folder_path'))
            if st.button(_tf(t, "det.folder_scan"), key=_k('run_folder')):
                _fp = Path(folder_path)
                csv_files = sorted(_fp.glob("*.csv")) if _fp.is_dir() else []
                if csv_files:
                    st.success(_tf(t, "det.files_found", n=len(csv_files)))
                    st.caption(", ".join(f.name for f in csv_files))
                    df_first = dio.load_test_df(str(csv_files[0]))
                    if df_first is not None:
                        _row = df_first.iloc[0].to_dict()
                        _row['_input_mode'] = 'folder'
                        st.session_state[_k('tab5_row')] = _row
                        st.session_state[_k('tab5_fname')] = csv_files[0].name
                    else:
                        st.error(_tf(t, "det.read_fail", name=csv_files[0].name))
                else:
                    st.warning(_tf(t, "det.no_csv", path=folder_path))
            if st.session_state.get(_k('tab5_row')):
                st.caption(_tf(t, "det.first_row", name=st.session_state.get(_k("tab5_fname"), "")))
                st.dataframe(pd.DataFrame([
                    {k: v for k, v in st.session_state[_k('tab5_row')].items()
                     if not str(k).startswith('_')}]), width="stretch")
                if st.button(_tf(t, "det.run"), type="primary", key=_k('run_folder_go')):
                    row_to_predict = dict(st.session_state[_k('tab5_row')])

    # ── 선택 데이터셋 ──
    #   csv 뿐 아니라 parquet · X/y 분리 페어까지 dataset_loader 가 합쳐서 준다.
    #   경로를 직접 받는 test/train 탭과 달리 호출부(사이드바)의 선택을 따른다 —
    #   두 앱이 같은 표본을 보게 하는 통로다.
    if "dataset" in _T:
        with _T["dataset"]:
            if not dataset_name:
                st.caption(_tf(t, "det.pick_dataset"))
            else:
                _dsinfo = (dataset_found or {}).get(dataset_name)
                _has_label = bool(getattr(_dsinfo, "has_label", False))
                st.caption(f"🏷️ `{dataset_name}` · {getattr(_dsinfo, 'note', '')}")

                # ── 🎯 추출 범위 ────────────────────────────
                #   특정 유형만 뽑아 그 유형에서 모델이 어떻게 반응하는지 보는 것이
                #   실제 조사 방식이다. 라벨이 없으면 거를 근거가 없어 숨긴다.
                _SCOPE_OPTS = ["all_both", "all_fraud"] + list("abcdefghijkl") + ["m"]
                _SCOPE_DISP = {"all_both": "🌐 전체 (정상+사기)",
                               "all_fraud": "🚨 사기 전체 (a~l)",
                               "m": "✅ 정상만 (m)"}
                g1, g2, g3 = st.columns([1.6, 1, 1])
                if _has_label:
                    with g1:
                        # 챗봇이 범위를 바꿀 수 있게 예약값을 위젯 생성 직전에 소비
                        if _scope_key in st.session_state:
                            _ps = st.session_state.pop(_scope_key)
                            if _ps in _SCOPE_OPTS:
                                st.session_state[_k('t6_scope')] = _ps
                        t6_scope = st.selectbox(
                            _tf(t, "det.scope"), _SCOPE_OPTS, key=_k('t6_scope'),
                            format_func=lambda x: _SCOPE_DISP.get(
                                x, f"{x.upper()} — {_flabel(x, lang, short=True)}"),
                            help=_tf(t, "det.scope_help"))
                else:
                    t6_scope = "all_both"
                    g1.caption(_tf(t, "det.scope_nolabel"))
                t6_n = g2.number_input(_tf(t, "det.sample_n"), 1, 50, 1, key=_k('t6_n'))
                t6_seed = g3.number_input(_tf(t, "det.seed"), -1, 9999, -1, key=_k('t6_seed'))

                if st.button(_tf(t, "det.extract"), key=_k('run_ds'), width="stretch"):
                    try:
                        from pipeline.dataset_loader import load_dataset as _load_ds
                        _dsdf = _load_ds(_dsinfo)
                        # 라벨 디코딩이 실패해 정수가 남아온 경우 방어 — 'm' 비교가 깨진다
                        if _has_label and 'Fraud_Type' in _dsdf.columns:
                            _dsdf = _dsdf.copy()
                            _dsdf['Fraud_Type'] = _dsdf['Fraud_Type'].astype(str)
                        if not _has_label or t6_scope == "all_both":
                            _pool = _dsdf
                        elif t6_scope == "all_fraud":
                            _pool = _dsdf[_dsdf['Fraud_Type'] != 'm']
                        else:
                            _pool = _dsdf[_dsdf['Fraud_Type'] == t6_scope]
                        if len(_pool) == 0:
                            st.warning(_tf(t, "det.scope_empty",
                                           scope=_SCOPE_DISP.get(t6_scope, t6_scope.upper())))
                        else:
                            _s = _pool.sample(min(int(t6_n), len(_pool)),
                                              random_state=dio.resolve_seed(t6_seed))
                            st.session_state[_k('tab6_rows')] = _s.to_dict('records')
                            st.session_state[_k('tab6_scope')] = t6_scope
                    except Exception as _de:
                        st.error(_tf(t, "det.ds_load_fail", e=_de))

                if st.session_state.get(_k('tab6_rows')):
                    rp6 = st.session_state[_k('tab6_rows')]
                    _sc = st.session_state.get(_k('tab6_scope'), 'all_both')
                    st.caption(_tf(t, "det.extracted", n=len(rp6),
                                       scope=_SCOPE_DISP.get(_sc, _sc.upper())))
                    st.dataframe(pd.DataFrame(rp6), width="stretch", height=180)
                    si6 = (st.selectbox(_tf(t, "det.row_select"), range(len(rp6)),
                                        format_func=lambda i: (
                                            f"#{i+1} · {rp6[i].get('ID', i)}"
                                            + (f" · 정답 {rp6[i].get('Fraud_Type')}"
                                               if rp6[i].get('Fraud_Type') else "")),
                                        key=_k('t6_sel')) if len(rp6) > 1 else 0)
                    sr6 = dict(rp6[si6])
                    sr6['_input_mode'] = f'dataset:{dataset_name}'
                    # 라벨 보유 데이터셋이면 정답을 남겨 결과표의 '실제 정답' 칸을 채운다
                    if sr6.get('Fraud_Type'):
                        sr6['_true_label'] = sr6['Fraud_Type']
                    _picked = _action_row(rp6, sr6, "ds", f"dataset_{t6_scope}")
                    if _picked is not None:
                        row_to_predict = _picked

    return row_to_predict

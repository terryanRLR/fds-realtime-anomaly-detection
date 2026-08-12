"""
detect_ui — 탐지 결과 렌더링 컴포넌트 (dashboard.py · ops_dashboard.py 공용)

왜 이 모듈이 필요한가
  dashboard.py 세션5(4057~5450행)에만 있던 위험 게이지·확률 막대·사기유형 카드·
  규칙 체크리스트를 ops_dashboard.py 는 갖고 있지 않았다. 그대로 복붙하면
  같은 컴포넌트가 두 벌이 되어, 한쪽만 고치는 사고가 반드시 난다.
  → 여기로 뽑아 두 앱이 **같은 함수**를 호출한다.

설계 원칙 (이걸 지켜야 두 앱에서 같이 돈다)
  1. st.session_state 를 읽지 않는다. 필요한 값은 전부 인자로 받는다.
     (dashboard 는 selected_model/dual_threshold 등에 의존하지만 ops 는 그 상태가 없다)
  2. 테마는 `T` dict 를 인자로 받는다. dashboard 는 자기 THEMES, ops 는
     ops_ui.THEMES 를 넘긴다 — 같은 컴포넌트가 각자 색으로 그려진다.
  3. i18n 은 `lang` + 선택적 `t` 콜러블. `t` 가 없으면 내장 폴백 문구를 쓴다.
     (ops 는 ops_ui.make_ops_t 를, dashboard 는 자기 t 를 넘긴다)
  4. 필요한 CSS 는 build_css(T) 가 통째로 돌려준다. dashboard 는 이미
     같은 클래스를 갖고 있으므로 주입하지 않아도 되고, ops 는 주입해야 한다.

사용법 (ops_dashboard.py)
    from pipeline import detect_ui as dui
    st.markdown(dui.build_css(T), unsafe_allow_html=True)
    dui.verdict_hero(det, threshold, T, lang=LANG, t=t)
    dui.risk_gauge(det["risk_score"], T)
    dui.prob_bars(det["proba_dict"], T, lang=LANG)
"""

from __future__ import annotations

import logging
import math

import streamlit as st

DETECT_UI_VERSION = "v1"

log = logging.getLogger("detect_ui")

# ── i18n_data 브리지 (없어도 죽지 않는다 — ops_ui.py 와 같은 방어 패턴) ──
try:
    from i18n_data import (FRAUD_SHORT_I18N, FRAUD_TYPE_DETAILS_I18N,
                           FLAG_LABELS_I18N)
    HAS_I18N_DATA = True
except ImportError:                                    # pragma: no cover
    HAS_I18N_DATA = False
    _KO_SHORT = {'a': 'A 원거리', 'b': 'B 저신용', 'c': 'C 악성앱', 'd': 'D 약신호',
                 'e': 'E 입금→ATM', 'f': 'F 위장인출', 'g': 'G 중간단계',
                 'h': 'H 휴면실패', 'i': 'I 고액', 'j': 'J 대포통장',
                 'k': 'K 재사용', 'l': 'L 고령층', 'm': '정상'}
    FRAUD_SHORT_I18N = {lg: _KO_SHORT for lg in ("ko", "en", "ja", "zh")}
    FRAUD_TYPE_DETAILS_I18N = {lg: {} for lg in ("ko", "en", "ja", "zh")}
    FLAG_LABELS_I18N = {lg: {} for lg in ("ko", "en", "ja", "zh")}

# dashboard.py:859 원본 유지 — 결과 패널의 '위험 특징' 태그가 이 순서로 나온다
BINARY_FLAGS = [
    'Customer_rooting_jailbreak_indicator',
    'Customer_VPN_Indicator',
    'Customer_flag_terminal_malicious_behavior_1',
    'Customer_flag_terminal_malicious_behavior_2',
    'Customer_flag_terminal_malicious_behavior_3',
    'Unused_terminal_status',
    'Unused_account_status',
    'Recipient_account_suspend_status',
    'Account_release_suspention',
    'Transaction_Failure_Status',
    'Another_Person_Account',
    'Flag_deposit_more_than_tenMillion',
]

_TRUE_VALUES = ('1', '1.0', 'True', 'true')

# ── 폴백 문구 — t 를 넘기지 않아도 화면이 비지 않도록 ──────
_FALLBACK = {
    "ko": {"verdict_anomaly": "🚨 이상거래 탐지", "verdict_normal": "✅ 정상 거래",
           "threshold": "임계값", "model": "모델", "pred_type": "예측 유형",
           "true_answer": "실제 정답", "input_mode": "입력 방식",
           "risk_features": "위험 특징", "none": "없음",
           "fraud_info": "사기 유형 정보", "probability": "유형별 확률",
           "rules": "📋 규칙 적합도", "key_indicators": "주요 지표",
           "evidence": "실측 근거",
           "rule_disclaimer": "규칙만으로는 사기를 판정하지 않습니다 — "
                              "'사기라면 어느 유형 특징에 맞는가'만 보여줍니다.",
           "rule_score": "적합도 {idx}", "rule_ranking": "유형별 적합도: {r}",
           "rule_mismatch": "⚠ 모델은 이 거래를 다르게 봤지만, 규칙은 {tp}형에 "
                            "더 잘 맞습니다 ({a} vs {b}, 격차 {g}배) — 수동 검토 권장"},
    "en": {"verdict_anomaly": "🚨 Anomaly detected", "verdict_normal": "✅ Normal",
           "threshold": "Threshold", "model": "Model", "pred_type": "Predicted type",
           "true_answer": "Ground truth", "input_mode": "Input mode",
           "risk_features": "Risk features", "none": "None",
           "fraud_info": "Fraud type info", "probability": "Class probability",
           "rules": "📋 Rule match", "key_indicators": "Key indicators",
           "evidence": "Measured evidence",
           "rule_disclaimer": "Rules alone do not decide fraud — they only show "
                              "which type the transaction resembles.",
           "rule_score": "index {idx}", "rule_ranking": "Per-type match: {r}",
           "rule_mismatch": "⚠ The model disagrees with the rules, which fit type "
                            "{tp} better ({a} vs {b}, {g}x gap) — manual review advised"},
}


def _fb(key: str, lang: str = "ko", **kw) -> str:
    d = _FALLBACK.get(lang) or _FALLBACK["ko"]
    s = d.get(key) or _FALLBACK["ko"].get(key, key)
    return s.format(**kw) if kw else s


def _html(content: str, height: int = 0, **kw):
    """임의 HTML 삽입 래퍼.

    st.components.v1.html 은 2026-06-01 이후 제거 예정(st.iframe 로 대체)이라
    st.iframe 이 있으면 그걸 먼저 쓴다. 둘 다 없어도 죽지 않는다.
    """
    if hasattr(st, "iframe"):
        try:
            return st.iframe(content, height=height, **kw)
        except Exception as e:                         # pragma: no cover
            log.debug(f"st.iframe 실패 → components.html 폴백: {e}")
    try:
        import streamlit.components.v1 as components
        return components.html(content, height=height, **kw)
    except Exception as e:                             # pragma: no cover
        log.debug(f"HTML 삽입 사용 불가: {e}")
        return None


def _tr(t, key: str, fb_key: str, lang: str = "ko", **kw) -> str:
    """t 가 있으면 t(key), 없으면(또는 키가 없어 그대로 튀어나오면) 폴백 문구."""
    if t is not None:
        try:
            out = t(key, **kw)
            if out and out != key:
                return out
        except Exception:
            pass
    return _fb(fb_key, lang, **kw)


def short_label(code: str, lang: str = "ko") -> str:
    return (FRAUD_SHORT_I18N.get(lang) or FRAUD_SHORT_I18N.get("ko") or {}).get(code, code)


def _details(lang: str = "ko") -> dict:
    return FRAUD_TYPE_DETAILS_I18N.get(lang) or FRAUD_TYPE_DETAILS_I18N.get("ko") or {}


def _flag_labels(lang: str = "ko") -> dict:
    return FLAG_LABELS_I18N.get(lang) or FLAG_LABELS_I18N.get("ko") or {}


def _rgb(hexc: str) -> str:
    """'#e85d75' → '232,93,117'. 이미 'r,g,b' 형태면 그대로 돌려준다."""
    s = str(hexc).strip()
    if not s.startswith("#"):
        return s
    s = s.lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    try:
        return f"{int(s[0:2], 16)},{int(s[2:4], 16)},{int(s[4:6], 16)}"
    except ValueError:                                 # pragma: no cover
        return "128,128,128"


def _dim(T: dict, key: str, fallback_key: str) -> str:
    """red_dim 처럼 테마에 없을 수도 있는 키 — 없으면 본색으로 대체."""
    return T.get(key) or T.get(fallback_key, "#888888")


# ══════════════════════════════════════════════════════════
# CSS — dashboard.py 신 UI(544~660행) 계열을 컴포넌트 단위로만 발췌
# ══════════════════════════════════════════════════════════
def build_css(T: dict) -> str:
    """탐지 컴포넌트 전용 CSS.

    dashboard.py 는 이미 동일 클래스를 전역 CSS로 갖고 있어 주입이 불필요하다
    (중복 주입해도 나중 정의가 이기므로 깨지지는 않는다).
    ops_dashboard.py 는 ops_ui.build_css(T) **뒤에** 이걸 주입해야 한다.
    """
    R, G, A, B = _rgb(T['red']), _rgb(T['green']), _rgb(T['amber']), _rgb(T['blue'])
    AC = T.get('accent_rgb') or _rgb(T['accent'])
    accent_dim = _dim(T, 'accent_dim', 'accent')
    red_dim = _dim(T, 'red_dim', 'red')
    border = T.get('border') or f"rgba({AC},0.14)"
    return f"""<style>
/* ── detect_ui {DETECT_UI_VERSION} — 탐지 결과 컴포넌트 ── */
.du-scope {{ --du-red:{T['red']}; --du-green:{T['green']}; }}
.badge-danger{{display:inline-block;background:rgba({R},0.12);color:{T['red']};border:1px solid rgba({R},0.35);border-radius:7px;padding:3px 10px;font-size:12px;font-weight:700;}}
.badge-safe{{display:inline-block;background:rgba({G},0.12);color:{T['green']};border:1px solid rgba({G},0.35);border-radius:7px;padding:3px 10px;font-size:12px;font-weight:700;}}
.badge-warn{{display:inline-block;background:rgba({A},0.12);color:{T['amber']};border:1px solid rgba({A},0.35);border-radius:7px;padding:3px 10px;font-size:12px;font-weight:700;}}

.result-panel{{background:{T['bg_card']};border:1px solid {border};border-radius:14px;padding:22px 26px;margin:1rem 0;}}
.result-panel.anomaly{{border-left:4px solid {T['red']};}}
.result-panel.normal{{border-left:4px solid {T['green']};}}

/* 판정 히어로 배너 */
@keyframes duPulse{{0%,100%{{box-shadow:0 0 14px rgba({R},0.30);}}50%{{box-shadow:0 0 26px rgba({R},0.55);}}}}
.verdict-hero{{display:flex;align-items:center;justify-content:space-between;gap:18px;border-radius:16px;padding:20px 26px;margin:10px 0 14px;border:1px solid;position:relative;overflow:hidden;}}
.verdict-hero::before{{content:'';position:absolute;top:0;left:0;right:0;height:3px;}}
.verdict-hero.anomaly{{border-color:rgba({R},0.45);background:linear-gradient(100deg,rgba({R},0.13),rgba({R},0.04) 55%,transparent);}}
.verdict-hero.anomaly::before{{background:linear-gradient(90deg,{T['red']},transparent);}}
.verdict-hero.normal{{border-color:rgba({G},0.40);background:linear-gradient(100deg,rgba({G},0.11),rgba({G},0.03) 55%,transparent);}}
.verdict-hero.normal::before{{background:linear-gradient(90deg,{T['green']},transparent);}}
.verdict-hero .vh-icon{{width:46px;height:46px;min-width:46px;border-radius:13px;display:flex;align-items:center;justify-content:center;font-size:22px;}}
.verdict-hero.anomaly .vh-icon{{background:rgba({R},0.15);border:1px solid rgba({R},0.40);animation:duPulse 2s ease-in-out infinite;}}
.verdict-hero.normal .vh-icon{{background:rgba({G},0.12);border:1px solid rgba({G},0.35);}}
.verdict-hero .vh-title{{font-size:21px;font-weight:800;letter-spacing:-0.01em;line-height:1.15;}}
.verdict-hero .vh-meta{{font-size:10.5px;color:{T['text_muted']};font-family:var(--font-mono);margin-top:4px;letter-spacing:0.02em;}}
.verdict-hero .vh-score{{font-family:var(--font-mono);font-size:30px;font-weight:700;text-align:right;line-height:1;font-variant-numeric:tabular-nums;}}
@media (prefers-reduced-motion:reduce){{.verdict-hero.anomaly .vh-icon{{animation:none;}}}}
@media (max-width:760px){{.verdict-hero{{flex-direction:column;align-items:flex-start;}}.verdict-hero .vh-score{{text-align:left;}}}}

/* 위험 게이지 */
.gauge-wrap{{text-align:center;padding:8px 0;}}
.gauge-label{{font-size:11px;letter-spacing:0.06em;text-transform:uppercase;color:{T['text_secondary']};font-weight:700;}}

/* 확률 막대 */
.prob-bar-wrap{{margin:3px 0;}}
.prob-bar-label{{display:flex;justify-content:space-between;font-size:11.5px;font-family:var(--font-mono);color:{T['text_secondary']};margin-bottom:3px;}}
.prob-bar-bg{{background:{T['bg_surface']};border-radius:3px;height:6px;overflow:hidden;}}
.prob-bar-fill{{height:100%;border-radius:3px;background:linear-gradient(90deg,{accent_dim},{T['accent']});transition:width .6s cubic-bezier(.22,1,.36,1);}}
.prob-bar-fill.danger{{background:linear-gradient(90deg,{red_dim},{T['red']});}}

/* 사기유형 카드 · 특징 태그 */
.fraud-type-card{{background:{T['bg_card']};border:1px solid {border};border-radius:12px;padding:14px 18px;margin:6px 0;}}
.feature-tag{{display:inline-block;background:{T['bg_surface']};border:1px solid {border};border-radius:7px;padding:4px 10px;font-size:11.5px;font-family:var(--font-mono);color:{T['text_secondary']};margin:2px;}}
.feature-tag.danger{{border-color:{T['red']};color:{T['red']};background:transparent;}}
.feature-tag.safe{{border-color:{T['green']};color:{T['green']};background:transparent;}}

/* 알림 박스 */
.alert-box{{border-radius:10px;padding:13px 16px;font-size:13.5px;line-height:1.65;margin:8px 0;border:1px solid {border};border-left:3px solid;background:{T['bg_card']};}}
.alert-info{{border-left-color:{T['blue']};color:{T['text_secondary']};background:linear-gradient(90deg,rgba({B},0.07),{T['bg_card']} 45%);}}
.alert-warn{{border-left-color:{T['amber']};color:{T['text_secondary']};background:linear-gradient(90deg,rgba({A},0.08),{T['bg_card']} 45%);}}
.alert-error{{border-left-color:{T['red']};color:{T['red']};background:linear-gradient(90deg,rgba({R},0.09),{T['bg_card']} 45%);}}
.alert-ok{{border-left-color:{T['green']};color:{T['text_secondary']};background:linear-gradient(90deg,rgba({G},0.07),{T['bg_card']} 45%);}}

/* 규칙 체크리스트 */
.du-rule-hit{{font-size:11.5px;line-height:1.6;margin:1px 0;}}
.du-rule-miss{{font-size:11px;line-height:1.55;margin:1px 0;color:{T['text_muted']};}}
.du-detail-table{{width:100%;border-collapse:collapse;}}
.du-detail-table td{{padding:8px 0;}}
.du-detail-table td.k{{color:{T['text_muted']};font-size:11px;width:35%;}}
</style>"""


# ══════════════════════════════════════════════════════════
# 개별 컴포넌트
# ══════════════════════════════════════════════════════════
def alert_box(msg: str, level: str = "info"):
    """level: info · warn · error · ok"""
    st.markdown(f'<div class="alert-box alert-{level}">{msg}</div>',
                unsafe_allow_html=True)


def risk_gauge(score, T: dict, labels: dict | None = None):
    """반원 게이지 — 그라디언트 아크 + 25% 눈금 + 엔드포인트 마커.

    dashboard.py:1270 원본. SMIL <animate> 는 rerun 연쇄에서 시작값에 동결되는
    고질병이 있어 CSS 키프레임으로 그린다. 애니메이션이 실패해도 정적
    stroke-dasharray 가 최종값을 보장한다.
    """
    score = max(0.0, min(1.0, float(score or 0)))
    labels = labels or {}
    if score >= 0.8:
        color, dim = T['red'], _dim(T, 'red_dim', 'red')
        label = labels.get("high", "HIGH RISK")
    elif score >= 0.5:
        color, dim = T['amber'], T['amber']
        label = labels.get("mid", "ELEVATED")
    else:
        color, dim = T['green'], T['green']
        label = labels.get("low", "NORMAL")

    gid = f"du{int(score * 10000)}"
    ticks = ""
    for p in (0.0, 0.25, 0.5, 0.75, 1.0):
        a = math.pi * (1 - p)
        x1, y1 = 70 + 49 * math.cos(a), 75 - 49 * math.sin(a)
        x2, y2 = 70 + 55 * math.cos(a), 75 - 55 * math.sin(a)
        ticks += (f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                  f'stroke="{T["text_muted"]}" stroke-width="1.4" opacity="0.55"/>')

    ea = math.pi * (1 - score)
    ex, ey = 70 + 55 * math.cos(ea), 75 - 55 * math.sin(ea)
    dash = f"{score * 173:.0f} 173"
    st.markdown(
        f'<div class="gauge-wrap"><svg viewBox="0 0 140 88" width="185" xmlns="http://www.w3.org/2000/svg">'
        f'<defs><linearGradient id="{gid}" x1="0%" y1="0%" x2="100%" y2="0%">'
        f'<stop offset="0%" stop-color="{dim}" stop-opacity="0.55"/>'
        f'<stop offset="100%" stop-color="{color}"/></linearGradient></defs>'
        f'<path d="M15,75 A55,55,0,0,1,125,75" fill="none" stroke="{T["bg_surface"]}" '
        f'stroke-width="10" stroke-linecap="round"/>'
        f'{ticks}'
        f'<style>@keyframes gf_{gid}{{from{{stroke-dasharray:0 173}}to{{stroke-dasharray:{dash}}}}}</style>'
        f'<path d="M15,75 A55,55,0,0,1,125,75" fill="none" stroke="url(#{gid})" stroke-width="10" '
        f'stroke-linecap="round" stroke-dasharray="{dash}" '
        f'style="filter:drop-shadow(0 0 5px {color});animation:gf_{gid} 0.9s cubic-bezier(0.22,1,0.36,1) 1"></path>'
        f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="4.5" fill="{color}" opacity="0.35"/>'
        f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="2.4" fill="{T["text_primary"]}"/>'
        f'<text x="70" y="62" text-anchor="middle" font-family="JetBrains Mono,monospace" '
        f'font-size="22" font-weight="700" fill="{color}">{score:.3f}</text>'
        f'<text x="70" y="76" text-anchor="middle" font-family="JetBrains Mono,monospace" '
        f'font-size="8.5" fill="{T["text_muted"]}">{score * 100:.1f}%</text>'
        f'</svg><div class="gauge-label" style="color:{color}">{label}</div></div>',
        unsafe_allow_html=True)


def prob_bars(proba_dict: dict, T: dict = None, lang: str = "ko", top_n: int | None = None):
    """13클래스 확률 막대. 1위가 정상('m')이 아니면 붉게 강조한다.

    T 는 CSS 클래스로만 그려서 실제로는 쓰지 않지만, 다른 컴포넌트와
    호출 시그니처를 맞추기 위해 받는다(생략 가능).
    """
    if not proba_dict:
        return
    si = sorted(proba_dict.items(), key=lambda x: x[1], reverse=True)
    if top_n:
        si = si[:int(top_n)]
    html = ""
    for idx, (cls, prob) in enumerate(si):
        label = short_label(cls, lang)
        pct = float(prob) * 100
        is_top = (idx == 0)
        fc = "danger" if (cls != 'm' and is_top) else ""
        html += (f'<div class="prob-bar-wrap"><div class="prob-bar-label">'
                 f'<span>{"⚑ " if is_top else ""}{label}</span><span>{pct:.2f}%</span></div>'
                 f'<div class="prob-bar-bg"><div class="prob-bar-fill {fc}" '
                 f'style="width:{min(pct, 100):.1f}%"></div></div></div>')
    st.markdown(html, unsafe_allow_html=True)


def prob_chart(proba_dict: dict, T: dict, lang: str = "ko", height: int = 210):
    """확률 막대그래프 Figure 를 돌려준다 (렌더는 호출부가 st.plotly_chart 로).

    Figure 를 반환하는 이유: dashboard 는 컴팩트 모드에서 height 를 바꾸고,
    ops 는 탭 폭에 맞춰 다르게 그린다 — 렌더 시점 제어를 호출부에 남긴다.
    """
    try:
        import plotly.graph_objects as go
    except ImportError:                                # pragma: no cover
        return None
    if not proba_dict:
        return None
    pi = sorted(proba_dict.items(), key=lambda x: x[1], reverse=True)
    labels = [short_label(k, lang) for k, _ in pi]
    values = [float(v) for _, v in pi]
    colors = [T['red'] if (k != 'm' and i == 0) else (T['accent'] if k == 'm' else T['text_muted'])
              for i, (k, _) in enumerate(pi)]
    fig = go.Figure(go.Bar(
        x=labels, y=values, marker_color=colors, marker_line_width=0,
        text=[f"{v * 100:.1f}%" for v in values], textposition="outside", cliponaxis=False,
        textfont=dict(size=8.5, color=T['text_secondary'], family='JetBrains Mono, monospace')))
    grid = f"rgba({T.get('accent_rgb') or _rgb(T['accent'])},0.08)"
    fig.update_layout(
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        font=dict(color=T['text_secondary'], size=11),
        margin=dict(l=0, r=0, t=10, b=30), height=height, showlegend=False)
    fig.update_xaxes(tickfont=dict(size=9), gridcolor=grid, zeroline=False)
    fig.update_yaxes(tickformat='.2%', gridcolor=grid, zeroline=False)
    return fig


def fraud_type_card(code: str, T: dict, lang: str = "ko", t=None):
    """사기 유형 상세 카드 — 이름·설명·주요 지표·실측 근거.

    dashboard.py:1433 fraud_type_popup 원본. 유형 정보가 없으면 조용히 넘어간다.
    """
    info = _details(lang).get(code)
    if not info:
        return
    rc = {'HIGH': T['red'], 'MEDIUM': T['amber'],
          'LOW': T['green']}.get(info.get('risk'), T['text_secondary'])
    border = T.get('border') or f"rgba({T.get('accent_rgb') or _rgb(T['accent'])},0.14)"
    ind_html = ' '.join(f'<span class="feature-tag danger">{x}</span>'
                        for x in info.get('indicators', []))
    ev = info.get('evidence', '')
    ev_label = _tr(t, "common.measured_evidence", "evidence", lang)
    ind_label = _tr(t, "common.key_indicators", "key_indicators", lang)
    ev_html = (f'<div style="margin-top:7px;padding-top:7px;border-top:1px solid {border}">'
               f'<span style="color:{T["text_muted"]};font-size:10px;letter-spacing:0.06em;'
               f'text-transform:uppercase;margin-right:6px">{ev_label}</span>'
               f'<span style="color:{T["accent"]};font-size:11px;font-family:var(--font-mono);'
               f'line-height:1.65">{ev}</span></div>') if ev else ''
    st.markdown(
        f'<div class="fraud-type-card">'
        f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:6px">'
        f'<span style="font-family:var(--font-mono);font-size:13px;font-weight:700;'
        f'color:{T["accent"]}">{str(code).upper()}</span>'
        f'<span style="color:{rc};font-size:10px;font-weight:700;'
        f'font-family:var(--font-mono)">{info.get("risk", "")}</span></div>'
        f'<p style="font-size:14px;font-weight:600;color:{T["text_primary"]};margin:0 0 6px">'
        f'{info.get("name", "")}</p>'
        f'<p style="font-size:12.5px;color:{T["text_secondary"]};line-height:1.6;margin:0">'
        f'{info.get("desc", "")}</p>'
        f'<div style="margin-top:8px;padding-top:8px;border-top:1px solid {border}">'
        f'<span style="color:{T["text_muted"]};font-size:10px;letter-spacing:0.06em;'
        f'text-transform:uppercase;margin-right:6px">{ind_label}</span>{ind_html}</div>'
        f'{ev_html}</div>', unsafe_allow_html=True)


def verdict_hero(det: dict, threshold: float, T: dict, lang: str = "ko", t=None):
    """판정 배너 — 판정·위험점수·예측유형·모델 메타를 최상단 풀폭으로.

    det 는 dashboard 세션5 / ops 탐지 결과 공통 스키마를 기대한다:
      is_anomaly · fraud_type · risk_score · (선택) model
    """
    is_anomaly = bool(det.get('is_anomaly'))
    fraud_type = det.get('fraud_type', '')
    risk_score = float(det.get('risk_score') or 0)
    cls = "anomaly" if is_anomaly else "normal"
    color = T['red'] if is_anomaly else T['green']
    icon = "🚨" if is_anomaly else "🛡️"
    verdict = (_tr(t, "s5.verdict_anomaly", "verdict_anomaly", lang) if is_anomaly
               else _tr(t, "s5.verdict_normal", "verdict_normal", lang))
    badge_cls = "badge-danger" if is_anomaly else "badge-safe"
    badge = f'<span class="{badge_cls}">{short_label(fraud_type, lang)}</span>'
    model_txt = det.get('model') or det.get('model_name') or '—'
    meta = (f'{_fb("model", lang)} {model_txt} · '
            f'{_fb("threshold", lang)} {float(threshold):.2f}')
    st.markdown(
        f'<div class="verdict-hero {cls}">'
        f'<div style="display:flex;align-items:center;gap:14px">'
        f'<div class="vh-icon">{icon}</div>'
        f'<div><div class="vh-title" style="color:{color}">{verdict}</div>'
        f'<div class="vh-meta">{meta}</div></div></div>'
        f'<div><div class="vh-score" style="color:{color}">{risk_score:.3f}'
        f'<span style="font-size:12px;color:{T["text_muted"]};font-weight:400"> / 1.0</span></div>'
        f'<div style="text-align:right;margin-top:7px">{badge}</div></div>'
        f'</div>', unsafe_allow_html=True)


def detail_table(det: dict, T: dict, lang: str = "ko", t=None):
    """예측유형 · 실제정답 · 입력방식 · 위험특징 4행 표 (히어로 옆 오른쪽 패널)."""
    row = det.get('row') or {}
    is_anomaly = bool(det.get('is_anomaly'))
    fraud_type = det.get('fraud_type', '')
    flabels = _flag_labels(lang)
    hits = [f'<span class="feature-tag danger">{flabels.get(f, f)}</span>'
            for f in BINARY_FLAGS if str(row.get(f, '0')) in _TRUE_VALUES]
    flags_html = ''.join(hits) or f'<span class="feature-tag safe">{_fb("none", lang)}</span>'

    true_lbl = row.get('_true_label', '')
    true_html = (f'<span class="badge-warn">{short_label(true_lbl, lang)}</span>'
                 if true_lbl else '—')
    badge_cls = "badge-danger" if is_anomaly else "badge-safe"
    st.markdown(
        f'<table class="du-detail-table">'
        f'<tr><td class="k">{_fb("pred_type", lang)}</td>'
        f'<td style="font-weight:700;color:{T["text_primary"]}">'
        f'<span class="{badge_cls}">{short_label(fraud_type, lang)}</span></td></tr>'
        f'<tr><td class="k">{_fb("true_answer", lang)}</td><td>{true_html}</td></tr>'
        f'<tr><td class="k">{_fb("input_mode", lang)}</td>'
        f'<td style="font-family:var(--font-mono);font-size:12px;color:{T["text_secondary"]}">'
        f'{row.get("_input_mode", det.get("mode", "—"))}</td></tr>'
        f'<tr><td class="k">{_fb("risk_features", lang)}</td><td>{flags_html}</td></tr>'
        f'</table>', unsafe_allow_html=True)


def rule_panel(row: dict, fraud_type: str, T: dict, lang: str = "ko", t=None,
               show_disclaimer: bool = True):
    """규칙 체크리스트 — 모델 판정의 '근거'를 사람 말로 표시.

    ⚠️ 사기/정상 판정은 하지 않는다. 정상 거래도 같은 특징을 흔히 갖기 때문
    (수취정지 49% · 미사용계좌 51% · 고액입금 42%) — 규칙만으로 판정하면 정밀도 0.3%.
    여기서는 "사기라고 할 때 어느 유형 특징에 맞는가"만 보여준다.

    반환: RuleChecker 리포트 dict (렌더할 게 없으면 None) — 호출부가
    모델↔규칙 불일치를 후속 처리(트리아지 플래그 등)에 쓸 수 있다.
    """
    try:
        from pipeline.rule_checker import RuleChecker
    except ImportError:
        try:
            from rule_checker import RuleChecker                # pragma: no cover
        except ImportError:
            log.debug("rule_checker 미탑재 — 규칙 패널 생략")
            return None
    try:
        rr = RuleChecker(lang).report(row or {}, fraud_type)
    except Exception as e:
        log.debug(f"규칙 체크리스트 생략: {e}")
        return None
    if not rr.get("known") or not rr.get("n_total"):
        return None

    if show_disclaimer:
        st.caption(_tr(t, "s5.rule_disclaimer", "rule_disclaimer", lang))
    pct = rr["n_hit"] / max(rr["n_total"], 1)
    col = T['red'] if pct >= 0.7 else (T['amber'] if pct >= 0.4 else T['text_muted'])
    idx_txt = _tr(t, "s5.rule_score", "rule_score", lang, idx=f'{rr["index"]:.2f}')
    st.markdown(
        f'<div style="display:flex;align-items:baseline;gap:9px;margin-bottom:6px">'
        f'<span style="font-family:var(--font-mono);font-size:19px;font-weight:800;'
        f'color:{col}">{rr["n_hit"]}/{rr["n_total"]}</span>'
        f'<span style="color:{T["text_secondary"]};font-size:12px">{idx_txt}</span>'
        f'<span style="color:{T["text_muted"]};font-size:11px">{rr["title"]}</span></div>',
        unsafe_allow_html=True)
    for h in rr["hits"]:
        st.markdown(
            f'<div class="du-rule-hit">'
            f'<span style="color:{T["red"]};font-weight:700">✅</span> '
            f'<span style="color:{T["text_primary"]}">{h["label"]}</span> '
            f'<span style="color:{T["accent"]};font-family:var(--font-mono);'
            f'font-size:10.5px">→ {h.get("evidence", "")}</span></div>',
            unsafe_allow_html=True)
    for mi in rr["misses"]:
        st.markdown(f'<div class="du-rule-miss">⬜ {mi["label"]}</div>',
                    unsafe_allow_html=True)
    if rr.get("unknowns"):
        st.caption("❔ " + ", ".join(u["label"] for u in rr["unknowns"][:3]))

    # 모델↔규칙 불일치 → 수동 검토 신호 (실측에서 모델 오분류를 잡아낸 경로)
    if rr.get("best_rule_type") and rr.get("agreement") is False \
            and rr.get("gap", 1.0) >= 1.3:
        alert_box(_tr(t, "s5.rule_mismatch", "rule_mismatch", lang,
                      tp=str(rr["best_rule_type"]).upper(),
                      a=f"{rr['best_rule_index']:.2f}", b=f"{rr['index']:.2f}",
                      g=f"{rr['gap']:.1f}"), "warn")
    rank = ", ".join(f"{c.upper()} {v:.2f}" for c, v in rr.get("ranking", [])[:4])
    if rank:
        st.caption(_tr(t, "s5.rule_ranking", "rule_ranking", lang, r=rank))
    return rr


# ══════════════════════════════════════════════════════════
# 🔊 TTS — AI 분석문을 소리로 읽어준다
# ══════════════════════════════════════════════════════════
def tts_player(text: str, key: str, lang: str = "ko", T: dict | None = None):
    """브라우저 음성 자동 검색 + 드롭다운 선택 + 재생/정지.

    dashboard.py:929 _tts_player 원본. 관제 화면에서 화면을 못 볼 때
    (전화 통화 중, 다른 창 작업 중) 분석 요지를 귀로 받는 용도다.

    ⚠️ 소리(경보음)는 여기 없다 — ops 는 ops_alert.py 가 볼륨·조용한시간·
    중복억제까지 갖춘 알람 시스템을 이미 소유한다. 오디오 코드를 두 벌 두면
    '한쪽만 조용한 시간을 지키는' 사고가 난다.
    """
    if not text:
        return
    T = T or {}
    # 🛡 </script> 주입 및 템플릿 리터럴 이스케이프 차단
    clean = (str(text).replace("\\", "\\\\").replace("`", "\\`")
             .replace("${", "\\${").replace("</", "<\\/"))[:3000]
    bg = T.get("bg_surface", "#1a1a2e")
    fg = T.get("text_secondary", "#ccc")
    ac = T.get("accent", "#6c5ce7")
    bd = T.get("text_muted", "#444")
    _html(f"""
    <div id="tts_{key}" style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">
      <select id="voice_{key}" style="flex:1;min-width:140px;max-width:260px;padding:4px 6px;
        border-radius:6px;border:1px solid {bd};background:{bg};color:{fg};font-size:11px"></select>
      <button onclick="ttsPlay_{key}()" style="padding:4px 12px;border-radius:6px;
        border:1px solid {ac};background:{ac}22;color:{ac};cursor:pointer;font-size:12px;
        white-space:nowrap">🔊 읽기</button>
      <button onclick="speechSynthesis.cancel()" style="padding:4px 8px;border-radius:6px;
        border:1px solid {bd};background:transparent;color:{fg};cursor:pointer;font-size:11px">⏹</button>
    </div>
    <script>
    (function() {{
      var sel = document.getElementById("voice_{key}");
      var lang = "{lang}";
      function loadVoices() {{
        var voices = speechSynthesis.getVoices();
        sel.innerHTML = "";
        var filtered = voices.filter(function(v) {{ return v.lang.startsWith(lang); }});
        if (filtered.length === 0) filtered = voices;
        filtered.forEach(function(v, i) {{
          var o = document.createElement("option");
          o.value = i; o.textContent = v.name + " (" + v.lang + ")";
          sel.appendChild(o);
        }});
        sel._voices = filtered;
      }}
      loadVoices();
      if (speechSynthesis.onvoiceschanged !== undefined) speechSynthesis.onvoiceschanged = loadVoices;
      window.ttsPlay_{key} = function() {{
        speechSynthesis.cancel();
        var u = new SpeechSynthesisUtterance(`{clean}`);
        var voices = sel._voices || speechSynthesis.getVoices();
        if (voices.length > 0 && sel.value !== "") u.voice = voices[parseInt(sel.value)];
        u.lang = lang; u.rate = 1.0; u.pitch = 1.0;
        speechSynthesis.speak(u);
      }};
    }})();
    </script>
    """, height=38)


# ══════════════════════════════════════════════════════════
# 🕘 탐지 이력 — 임계값을 바꾸면 과거 판정이 어떻게 뒤집히는지
# ══════════════════════════════════════════════════════════
HISTORY_MAX = 50


def history_append(session_state, *, txn_id, is_anomaly, fraud_type, risk_score,
                   threshold, input_mode="-", model="-", key="det_history"):
    """세션 내 탐지 이력 적재 (최근 HISTORY_MAX 건).
    내부 키는 언어 무관(영문)으로 저장하고, 표시 시점에 번역한다 —
    언어를 바꿔도 과거 이력이 깨지지 않는다."""
    import time as _time
    hist = session_state.setdefault(key, [])
    hist.append({
        'time': _time.strftime('%H:%M:%S'),
        'txn_id': str(txn_id or '-')[:24],
        'is_anomaly': bool(is_anomaly),
        'type': fraud_type,
        'risk_score': round(float(risk_score or 0), 4),
        'threshold': round(float(threshold or 0), 2),
        'input': str(input_mode or '-'),
        'model': str(model or '-'),
    })
    del hist[:-HISTORY_MAX]
    return hist


def history_table(history: list, threshold: float, T: dict, lang: str = "ko", t=None,
                  key_prefix: str = "dui"):
    """이력 표 + **현재 임계값 기준 재계산**.

    이 표의 값어치는 '지금 임계값으로 다시 판정하면 몇 건이 뒤집히는가'다.
    임계값을 0.5→0.7 로 올릴 때 놓치게 될 건수를 눈으로 보고 정한다.
    """
    if not history:
        return
    try:
        import pandas as pd
    except ImportError:                                # pragma: no cover
        return
    import time as _time

    raw = pd.DataFrame(history[::-1])
    th = float(threshold)
    now_anom = raw.apply(
        lambda r: (str(r.get('type', 'm')) != 'm' or float(r.get('risk_score', 0)) >= th),
        axis=1)
    changed = (now_anom != raw.get('is_anomaly', False))
    n_flip, n_anom = int(changed.sum()), int(now_anom.sum())
    v_a = _tr(t, "hist.verdict_anomaly", "verdict_anomaly", lang)
    v_n = _tr(t, "hist.verdict_normal", "verdict_normal", lang)

    df = pd.DataFrame({
        "시각": raw.get('time', ''),
        "거래 ID": raw.get('txn_id', ''),
        "당시 판정": raw.get('is_anomaly', False).map({True: v_a, False: v_n}),
        "현재 판정": now_anom.map({True: v_a, False: v_n}),
        "변화": changed.map({True: '⚠️', False: ''}),
        "유형": raw.get('type', ''),
        "위험점수": raw.get('risk_score', 0),
        "당시 임계값": raw.get('threshold', 0),
        "입력": raw.get('input', ''),
        "모델": raw.get('model', ''),
    })
    fc = T['amber'] if n_flip else T['text_muted']
    st.markdown(
        f'<div style="font-size:12px;color:{T["text_secondary"]};margin-bottom:6px">'
        f'현재 임계값 <b style="color:{T["accent"]}">{th:.2f}</b> 기준 재계산 — '
        f'이상 <b style="color:{T["red"]}">{n_anom}</b>건 · '
        f'정상 <b style="color:{T["green"]}">{len(df) - n_anom}</b>건 · '
        f'판정 뒤집힘 <b style="color:{fc}">{n_flip}</b>건</div>',
        unsafe_allow_html=True)
    st.dataframe(df, width='stretch', height=min(320, 42 + 35 * len(df)), hide_index=True)

    c1, c2, _ = st.columns([1.2, 1.2, 4])
    with c1:
        st.download_button("⬇ CSV 저장", df.to_csv(index=False).encode('utf-8-sig'),
                           file_name=f"fds_history_{_time.strftime('%H%M%S')}.csv",
                           mime="text/csv", key=f"{key_prefix}_dl_hist", width='stretch')
    with c2:
        if st.button("🗑 이력 비우기", key=f"{key_prefix}_clear_hist", width='stretch'):
            return "clear"
    return None


# ══════════════════════════════════════════════════════════
# 합성 컴포넌트 — 흔한 배치를 한 번에
# ══════════════════════════════════════════════════════════
def detection_result(det: dict, threshold: float, T: dict, lang: str = "ko", t=None,
                     show_rules: bool = True, show_chart: bool = True,
                     chart_height: int = 210):
    """판정 배너 → 게이지+상세표 → (규칙) → 사기유형 카드 → 확률.

    dashboard.py 세션5의 결과 레이아웃과 같은 순서다. 세부 배치를 바꾸고 싶으면
    이 함수를 쓰지 말고 개별 컴포넌트를 직접 호출하면 된다.

    반환: rule_panel 리포트 (또는 None)
    """
    if det.get('error'):
        alert_box(str(det['error']), "error")
        return None

    verdict_hero(det, threshold, T, lang, t)

    cg, cm = st.columns([1, 2])
    with cg:
        st.markdown(
            f'<div class="result-panel {"anomaly" if det.get("is_anomaly") else "normal"}">',
            unsafe_allow_html=True)
        risk_gauge(det.get('risk_score'), T)
        st.markdown(
            f'<div style="text-align:center;margin-top:10px">'
            f'<div style="color:{T["text_muted"]};font-size:12px">{_fb("threshold", lang)} '
            f'<span style="font-family:var(--font-mono);color:{T["text_secondary"]}">'
            f'{float(threshold):.2f}</span></div></div></div>', unsafe_allow_html=True)
    with cm:
        st.markdown('<div class="result-panel">', unsafe_allow_html=True)
        detail_table(det, T, lang, t)
        st.markdown('</div>', unsafe_allow_html=True)

    rr = None
    if show_rules:
        with st.expander(_fb("rules", lang), expanded=bool(det.get('is_anomaly'))):
            rr = rule_panel(det.get('row') or {}, det.get('fraud_type', ''), T, lang, t)
            if rr is None:
                st.caption("—")

    if det.get('is_anomaly') and det.get('fraud_type') in _details(lang):
        st.markdown(f"###### {_fb('fraud_info', lang)}")
        fraud_type_card(det['fraud_type'], T, lang, t)

    proba = det.get('proba_dict') or {}
    if proba:
        st.markdown(f"###### {_fb('probability', lang)}")
        if show_chart:
            cp, cc = st.columns([1, 2])
            with cp:
                prob_bars(proba, T, lang)
            with cc:
                fig = prob_chart(proba, T, lang, chart_height)
                if fig is not None:
                    st.plotly_chart(fig, width='stretch')
        else:
            prob_bars(proba, T, lang)
    return rr

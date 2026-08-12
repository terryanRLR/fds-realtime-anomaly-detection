"""📨 리치 알림 컴포저 — 두 대시보드의 **단일 출처**.

왜 모듈로 뺐나
  dashboard.py 세션5 에는 리치 컴포저(_compose_slack_single 등 4개)가 있었고,
  ops_dashboard.py 세션1 은 ops_dispatch.compose_*_default(머리말 + LLM 텍스트)
  만 썼다. 같은 탐지 건이라도 어느 화면에서 보내느냐에 따라
    · Slack  — 위험도 게이지·확률 헤더가 있거나 / 없거나
    · Email  — KPI 카드 + HTML 리포트 첨부가 붙거나 / 평문 한 덩어리이거나
  로 결과물이 갈렸다. 컴포저를 여기 하나로 모아 그 갈림을 없앤다.

앱마다 다른 것은 **인자로 받는다** — 여기서 st.session_state 를 읽지 않는다.
  t / lang  : i18n (dashboard 는 tt, ops 는 ui.make_ops_t → 둘 다 i18n_data 폴백)
  head      : 등급 머리말 (dashboard _tier_head / ops_dispatch.tier_head)
  rich      : 리치 스위치 (dashboard 'rich_notify' / ops 'ai_rich_notify')
  masker    : 첨부 리포트용 **강제 마스킹** 마스커 (없으면 첨부 표를 비운다)
  body      : 본문 덮어쓰기. ops 는 화면에서 편집한 이메일 본문이 그대로 나가야
              하므로 여기에 편집본을 넘긴다(넘기지 않으면 det['llm']['email']).

실패는 조용히 평문으로 내려간다 — 시각화가 깨졌다고 경보 자체가 못 나가면 안 된다.
"""
from __future__ import annotations

import logging
import time

log = logging.getLogger(__name__)

NOTIFY_COMPOSE_VERSION = "v1"


# ── i18n 라벨 묶음 ────────────────────────────────────────
def labels(t) -> dict:
    """notify_visuals 에 넘길 현재 언어 라벨. 기존 i18n 키를 최대한 재사용한다."""
    return {
        'risk': t('notif.risk'), 'thr': t('notif.thr'), 'prob': t('notif.prob_top'),
        'model': t('s5.h_model'), 'cnt': t('notif.cnt'),
        'total': t('s5.batch_kpi_total'), 'anomaly': t('s5.batch_kpi_anomaly'),
        'avg': t('s5.batch_kpi_avg'), 'max': t('s5.batch_kpi_max'),
        'risk_dist': t('notif.risk_dist'), 'type_dist': t('notif.type_dist'),
        'verdict': t('s5.h_verdict'), 'type': t('s5.th_pred_type'),
        'anom': t('s5.verdict_anomaly'), 'norm': t('s5.verdict_normal'),
        'attached': t('notif.attached'), 'auto_note': t('notif.auto_note'),
        'masked': t('notif.masked'), 'analysis': t('notif.analysis'),
        'verdicts': t('notif.verdicts'),
    }


def fraud_short(code, lang: str = "ko") -> str:
    """사기 유형 짧은 라벨 — i18n_data 가 단일 출처(ops_ui.fraud_label 과 같은 표)."""
    try:
        from i18n_data import FRAUD_SHORT_I18N as _S
    except ImportError:                                # pragma: no cover
        return str(code)
    _c = str(code or '?')
    return ((_S.get(lang) or _S.get("ko") or {}).get(_c, _c))


def batch_type_counts(bres) -> dict:
    tc = {}
    for r in getattr(bres, 'rows_out', []) or []:
        if r.get('is_anomaly'):
            k = str(r.get('fraud_type', '?'))
            tc[k] = tc.get(k, 0) + 1
    return tc


def _head_join(head: str, txt: str) -> str:
    return (head + "\n\n" + txt) if head else txt


# ── 단건 ──────────────────────────────────────────────────
def slack_single(det: dict, threshold, *, t, lang: str = "ko",
                 head: str = "", rich: bool = True, body=None) -> str:
    """단건 Slack 본문. 리치 OFF/실패 시 '머리말 + LLM 텍스트' 로 내려간다."""
    txt = _head_join(head, body if body is not None
                     else ((det.get('llm') or {}).get('slack', '') or ""))
    if not rich:
        return txt
    try:
        from pipeline.notify_visuals import slack_visual_single
        L = labels(t)
        L['prob'] = t('notif.prob')        # 단건은 전체 확률표를 보여준다
        _ft = str(det.get('fraud_type', '?'))
        return slack_visual_single(L, _ft, fraud_short(_ft, lang),
                                   det.get('risk_score', 0), float(threshold),
                                   det.get('proba_dict'),
                                   str(det.get('model', ''))) + "\n" + txt
    except Exception as e:
        log.warning(f"리치 Slack 구성 실패 → 기본 텍스트로 발송: {e}")
        return txt


def email_single(det: dict, threshold, *, t, lang: str = "ko", head: str = "",
                 rich: bool = True, masker=None, body=None):
    """→ (plain_body, html|None, attachments|None). 리치 OFF/실패 시 기존 동작 유지."""
    llm = det.get('llm') or {}
    raw = _head_join(head, body if body is not None else (llm.get('email', '') or ""))
    if not rich:
        return raw, None, None
    try:
        from pipeline.notify_visuals import (email_html_single, wrap_email,
                                             report_html_single, html_to_text)
        L = labels(t)
        _ft = str(det.get('fraud_type', '?'))
        _short = fraud_short(_ft, lang)
        kpi = email_html_single(L, _ft, _short, bool(det.get('is_anomaly')),
                                det.get('risk_score', 0), float(threshold),
                                det.get('proba_dict'), str(det.get('model', '')))
        html_doc = wrap_email(L, t('notif.report_title_single'), kpi, raw,
                             attached_note=True)
        # ⚠ 첨부 리포트는 반드시 강제 마스킹 데이터만 쓴다 (이메일 = 유출 최다 매체).
        #   마스커가 없거나 실패하면 표를 비운다 — 원문이 새는 것보다 낫다.
        _masked = {}
        if masker is not None:
            _clean = {k: v for k, v in (det.get('row') or {}).items()
                      if not str(k).startswith('_')}
            try:
                # 마스커 객체와 '마스커를 만드는 함수' 둘 다 받는다 — 호출부가
                #   리치 OFF 일 때 굳이 마스커를 짓지 않아도 되게 하기 위해서다.
                _m = masker() if callable(masker) else masker
                _masked = _m.mask_row(_clean)
            except Exception as e:
                log.warning(f"첨부 리포트 마스킹 실패 → 거래 표 생략: {e}")
        rep = report_html_single(L, t('notif.report_title_single'), _ft, _short,
                                 bool(det.get('is_anomaly')), det.get('risk_score', 0),
                                 float(threshold), det.get('proba_dict') or {},
                                 str(det.get('model', '')), _masked,
                                 llm.get('analysis', ''))
        atts = [(f"fds_report_{_ft}_{time.strftime('%H%M%S')}.html", rep, "text/html")]
        return (html_to_text(raw) or raw), html_doc, atts
    except Exception as e:
        log.warning(f"리치 Email 구성 실패 → 기본 본문으로 발송: {e}")
        return raw, None, None


# ── 배치 ──────────────────────────────────────────────────
def slack_batch(bres, *, t, lang: str = "ko", rich: bool = True, body=None) -> str:
    txt = body if body is not None else (getattr(bres, 'slack', '') or "")
    if not rich:
        return txt
    try:
        from pipeline.notify_visuals import slack_visual_batch
        risks = [r.get('risk_score', 0) for r in getattr(bres, 'rows_out', []) or []]
        head = slack_visual_batch(labels(t), bres.total, bres.anomaly_count,
                                  bres.avg_risk, bres.max_risk, risks,
                                  batch_type_counts(bres))
        return head + "\n" + txt
    except Exception as e:
        log.warning(f"리치 Slack(배치) 구성 실패 → 기본 텍스트로 발송: {e}")
        return txt


# ── 📄 마크다운 보고서 — 화면에서 [저장]으로 받는 산출물 ──────
#
#   Slack/Email 은 '지금 알린다', 이 .md 는 '나중에 남긴다'가 목적이다.
#   dashboard.py 세션5 에만 있던 것을 여기로 올려 ops 관제 화면도 같은 서식으로
#   받게 한다 — 두 화면이 낸 보고서의 항목이 다르면 나중에 비교가 안 된다.
def report_md_single(det: dict, *, t, lang: str = "ko", fraud_name: str = "") -> str:
    llm = det.get('llm') or {}
    _ft = str(det.get('fraud_type', '-'))
    _name = fraud_name or fraud_short(_ft, lang)
    _tid = str(det.get('txn_id') or '')
    return (
        f"# FDS Detection Report\n\n"
        f"- {t('s5.report_generated_at')}: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        + (f"- ID: {_tid}\n" if _tid else "")
        + f"- {t('s5.h_verdict')}: "
        f"{t('s5.verdict_anomaly') if det.get('is_anomaly') else t('s5.verdict_normal')}\n"
        f"- {t('s5.th_pred_type')}: {_ft} ({_name})\n"
        f"- {t('s5.h_risk_score')}: {float(det.get('risk_score') or 0):.4f}\n"
        f"- {t('s5.h_model')}: {det.get('model', '-') or '-'}\n\n"
        f"## {t('s5.llm_section_title')}\n\n{llm.get('analysis', '')}\n\n"
        f"## {t('s5.slack_title')}\n\n```\n{llm.get('slack', '')}\n```\n\n"
        f"## {t('s5.email_title')}\n\n```\n{llm.get('email', '')}\n```\n")


def report_md_batch(bres, *, t, lang: str = "ko") -> str:
    tc = batch_type_counts(bres)
    lines = [f"# FDS Batch Report", "",
             f"- {t('s5.report_generated_at')}: {time.strftime('%Y-%m-%d %H:%M:%S')}",
             f"- {t('s5.batch_kpi_total')}: {getattr(bres, 'total', 0):,}",
             f"- {t('s5.batch_kpi_anomaly')}: {getattr(bres, 'anomaly_count', 0):,}",
             f"- {t('s5.batch_kpi_avg')}: {getattr(bres, 'avg_risk', 0):.4f}",
             f"- {t('s5.batch_kpi_max')}: {getattr(bres, 'max_risk', 0):.4f}"]
    if tc:
        lines.append(f"- {t('notif.type_dist')}: "
                     + ", ".join(f"{fraud_short(k, lang)} {v:,}"
                                 for k, v in sorted(tc.items(), key=lambda x: -x[1])))
    lines += ["", f"## {t('s5.llm_section_title')}", "",
              getattr(bres, 'analysis', '') or "",
              "", f"## {t('s5.slack_title')}", "", "```",
              getattr(bres, 'slack', '') or "", "```",
              "", f"## {t('s5.email_title')}", "", "```",
              getattr(bres, 'email', '') or "", "```", ""]
    return "\n".join(lines)


def email_batch(bres, *, t, lang: str = "ko", rich: bool = True, body=None):
    raw = body if body is not None else (getattr(bres, 'email', '') or "")
    if not rich:
        return raw, None, None
    try:
        from pipeline.notify_visuals import (email_html_batch, wrap_email,
                                             report_html_batch, html_to_text)
        L = labels(t)
        tc = batch_type_counts(bres)
        risks = [r.get('risk_score', 0) for r in getattr(bres, 'rows_out', []) or []]
        kpi = email_html_batch(L, bres.total, bres.anomaly_count,
                               bres.avg_risk, bres.max_risk, tc)
        html_doc = wrap_email(L, t('notif.report_title_batch'), kpi, raw,
                             attached_note=True)
        # rows_out 은 판정 결과만 담고 있어(원거래 PII 없음) 리포트 표에 안전
        rep = report_html_batch(L, t('notif.report_title_batch'), bres.total,
                                bres.anomaly_count, bres.avg_risk, bres.max_risk,
                                risks, tc, getattr(bres, 'rows_out', []) or [],
                                getattr(bres, 'analysis', ''))
        atts = [(f"fds_batch_report_{time.strftime('%H%M%S')}.html", rep, "text/html")]
        return (html_to_text(raw) or raw), html_doc, atts
    except Exception as e:
        log.warning(f"리치 Email(배치) 구성 실패 → 기본 본문으로 발송: {e}")
        return raw, None, None

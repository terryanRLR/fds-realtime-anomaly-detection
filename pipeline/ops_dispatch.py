"""
ops_dispatch — 자동 발송 · 감사 로그 · 연결 테스트 · LLM 단계 재실행

dashboard.py 세션5에는 있었지만 ops_dashboard.py 에는 없던 것들을 모았다.
"탐지했다"와 "사람에게 전달됐다" 사이를 채우는 층이다.

ops_alert.py 와 무엇이 다른가 (이름이 비슷해 헷갈리기 쉽다)
  · ops_alert  = **들어오는** 경보. DB 를 폴링해 화면·소리·데스크톱 알림을 띄운다.
                 담당자가 자리에 있을 때 눈치채게 하는 것이 목적.
  · ops_dispatch = **나가는** 통보. Slack/Email 로 사람에게 밀어낸다.
                 담당자가 화면 앞에 없어도 도달하는 것이 목적.
  둘 다 '등급(tier)' 개념을 쓰지만 값이 다르다 —
  ops_alert 는 (confirm, review, all) 로 *울릴 범위*를,
  여기는 (none, review, single, confirm) 로 *보낼 채널*을 정한다.

의존성 주입
  Notifier/LLM/RAG/마스커를 만드는 방법이 두 앱에서 다르다
  (dashboard=ov_* 키, ops=ai_* 키). 그래서 이 모듈은 객체를 직접 만들지 않고
  **팩토리 콜러블**을 인자로 받는다. 덕분에 어느 앱에서 부르든 그 앱의 설정을 쓴다.
"""

from __future__ import annotations

import logging
import time

import streamlit as st

OPS_DISPATCH_VERSION = "v5"

log = logging.getLogger("ops_dispatch")

# 발송 등급 — ops_alert.TIERS(울릴 범위)와 다른 축이다
DISPATCH_TIERS = ("none", "review", "single", "confirm")

AUDIT_KEY = "_send_audit"
AUDIT_MAX = 50

# 영속 저장소. 없어도 세션 기록은 그대로 동작한다(기능 저하만 발생).
try:
    from pipeline import audit_store as astore_audit
except ImportError:                                    # pragma: no cover
    try:
        import audit_store as astore_audit
    except ImportError:
        astore_audit = None


# ══════════════════════════════════════════════════════════
# 발송 등급 — 이중 임계값
# ══════════════════════════════════════════════════════════
def notify_tier(session_state, risk_score) -> str:
    """이중 임계값 모드의 발송 등급 결정 (dashboard.py:2096 원본).

      'single'  — 이중 모드 OFF: 단일 임계값 동작 그대로
      'confirm' — 위험도 ≥ 2차: Slack+Email 동시 · 확정 통보
      'review'  — 1차 ≤ 위험도 < 2차: Slack만 · 담당자 추가 검토 요청
      'none'    — 위험도 < 1차: 자동 발송 생략
    ※ 2차 < 1차로 잘못 설정된 경우 2차=max(1차,2차)로 보정.
    """
    if not session_state.get('dual_threshold', False):
        return 'single'
    t1 = float(session_state.get('th_review', 0.6))
    t2 = max(float(session_state.get('th_confirm', 0.8)), t1)
    r = float(risk_score or 0)
    if r >= t2:
        return 'confirm'
    if r >= t1:
        return 'review'
    return 'none'


def tier_head(session_state, tier: str, risk_score) -> str:
    """등급별 메시지 머리말 — 받는 사람이 '지금 뭘 해야 하나'를 첫 줄에서 알게 한다."""
    t1 = float(session_state.get('th_review', 0.6))
    t2 = max(float(session_state.get('th_confirm', 0.8)), t1)
    r = float(risk_score or 0)
    if tier == 'review':
        return (f"🟡 [검토 요청] 위험도 {r:.4f} — 1차 임계값 {t1:.2f} 초과. "
                f"확정 전 담당자 확인이 필요합니다.")
    if tier == 'confirm':
        return (f"🔴 [확정 경보] 위험도 {r:.4f} — 2차 임계값 {t2:.2f} 초과. "
                f"즉시 대응이 필요합니다.")
    return ""


def tier_subject(tier: str, fraud_type, risk_score) -> str:
    ft = str(fraud_type or '?').upper()
    r = float(risk_score or 0)
    if tier == 'review':
        return f"[FDS 검토요청] {ft}형 의심 거래 (위험도 {r:.4f})"
    if tier == 'confirm':
        return f"[FDS 긴급] {ft}형 이상거래 확정 (위험도 {r:.4f})"
    return f"[FDS] {ft}형 이상거래 탐지"


def tier_badge_html(det: dict, T: dict) -> str:
    """발송 등급 + 자동 발송 결과 뱃지. 실패 사유까지 화면에 노출한다 —
    로그에 접근할 수 없는 담당자가 '왜 안 갔는지' 알 수 있어야 한다."""
    out = ""
    tn = det.get('notify_tier')
    label = {'review': '🟡 검토 요청 등급', 'confirm': '🔴 확정 경보 등급',
             'none': '⚪ 발송 생략 (1차 미만)'}.get(tn)
    if label:
        cls = {'review': 'badge-warn', 'confirm': 'badge-danger',
               'none': 'badge-safe'}[tn]
        out += f'<span class="{cls}" style="margin-right:6px">{label}</span>'
    for k, ok_txt, ng_txt in (("auto_slack_sent", "Slack 발송✅", "Slack 실패❌"),
                              ("auto_email_sent", "Email 발송✅", "Email 실패❌")):
        if det.get(k) is True:
            out += f'<span class="badge-safe" style="margin-right:6px">{ok_txt}</span>'
        elif det.get(k) is False:
            out += f'<span class="badge-danger" style="margin-right:6px">{ng_txt}</span>'
    for k, lbl in (("notify_error_slack", "Slack"), ("notify_error_email", "Email")):
        if det.get(k):
            out += (f'<div style="color:{T["red"]};font-size:11px;margin-top:4px">'
                    f'{lbl} 실패 사유: {det[k]}</div>')
    return out


# ══════════════════════════════════════════════════════════
# 감사 로그 — 되돌릴 수 없는 발송을 남긴다
# ══════════════════════════════════════════════════════════
def audit_append(session_state, *, ok: bool, channel: str, fraud_type, risk_score,
                 to: str = "", mask_level: str = "", via: str = "auto",
                 txn_id: str = "", error: str = "", db_path=None):
    """발송 기록 1건. 외부로 나간 것은 회수할 수 없으므로, 누가·언제·어디로·
    어떤 마스킹으로 보냈는지는 반드시 남는다.

    두 곳에 남긴다
      · session_state — 지금 화면에 즉시 보여주기 위한 사본 (최근 50건)
      · DB(notify_audit) — **진짜 기록.** 새로고침·재시작에도 살아남는다.
        db_path 가 없거나 audit_store 가 없으면 세션 기록만 남는다(기능 저하).

    txn_id/error 는 나중에 추가된 필드다 — 옛 기록에는 없으므로 읽는 쪽은
    반드시 .get() 을 쓴다.
    """
    aud = session_state.setdefault(AUDIT_KEY, [])
    aud.append({
        "at": time.strftime("%m-%d %H:%M:%S"), "ok": bool(ok), "ch": channel,
        "ft": fraud_type, "risk": float(risk_score or 0), "to": to or "",
        "mask": mask_level or "-", "via": via, "txn": txn_id or "",
        "err": (error or "")[:200],
    })
    del aud[:-AUDIT_MAX]

    if db_path and astore_audit:
        # 기록 실패가 발송을 막으면 안 된다 — append() 는 예외를 던지지 않는다
        _ok, _msg = astore_audit.append(
            db_path, ok=ok, channel=channel, fraud_type=fraud_type,
            risk_score=risk_score, recipient=to, mask_level=mask_level,
            via=via, txn_id=txn_id, error=error,
            reviewer=str(session_state.get("reviewer") or ""))
        if not _ok:
            aud[-1]["err"] = ((aud[-1].get("err") or "")
                              + f" · ⚠ 감사 저장 실패({_msg})").strip(" ·")
    return aud


def send_manual(session_state, *, channel: str, body: str, notifier_factory,
                fraud_type=None, risk_score=0, to: str = "", subject: str = "",
                mask_level: str = "-", txn_id: str = "",
                via: str = "manual", db_path=None,
                html: str | None = None, attachments: list | None = None
                ) -> tuple[bool, str]:
    """**수동 발송 1건 — 보내고, 반드시 감사 로그를 남긴다.** (성공, 오류메시지) 반환.

    왜 함수로 묶는가
      예전에는 화면마다 `nn.send_slack(...)` 다음에 `audit_append(...)` 를 손으로
      짝지어 붙였다. 그 결과 6개 발송 경로 중 **4개에서 audit_append 가 빠졌고**
      (단건 분석 Slack/Email · 배치 Slack/Email), 진단 탭은 그런 줄도 모르고
      "자동·수동을 가리지 않고 모든 시도를 기록합니다" 라고 안내하고 있었다.
      기록을 빠뜨릴 수 없는 구조로 만드는 것이 유일한 재발 방지책이다.

    예외도 기록한다 — SMTP 가 끊겨 예외가 나는 것이야말로 감사 로그에
    남아야 할 사건이다. '성공만 기록되는 로그'는 감사 자료가 아니다.

    html/attachments (v5)
      리치 이메일(KPI 카드 + HTML 리포트 첨부)용 통로. 넘기지 않으면 예전처럼
      평문 한 파트로 나간다 — 기존 호출부는 한 줄도 고칠 필요가 없다.
    """
    ok, err = False, ""
    try:
        nn = notifier_factory()
        if channel == "slack":
            ok = bool(nn.send_slack(body))
        elif channel == "email":
            ok = bool(nn.send_email(to, subject, body,
                                    html=html, attachments=attachments))
        else:                                          # pragma: no cover
            raise ValueError(f"알 수 없는 채널: {channel}")
        if not ok:
            err = getattr(nn, "last_error", "") or "발송 실패"
    except Exception as e:
        ok, err = False, f"{type(e).__name__}: {e}"
        log.warning(f"{channel} 수동 발송 실패: {e}")
    audit_append(session_state, ok=ok, channel=channel, fraud_type=fraud_type,
                 risk_score=risk_score, to=(to or "webhook"),
                 mask_level=mask_level, via=via, txn_id=txn_id, error=err,
                 db_path=db_path)
    return ok, err


def _audit_line(ok, when, channel, ft, risk, txn, to, mask, via, err) -> str:
    _txn = f" · {txn}" if txn else ""
    _err = f" · ⚠ {err}" if err else ""
    _ft = f"{str(ft).upper()}형 " if ft else ""
    return (f"{'✅' if ok else '❌'} {when} · {channel} · {_ft}{float(risk or 0):.4f}"
            f"{_txn} · {to or '-'} · mask={mask or '-'} · {via or '-'}{_err}")



# ══════════════════════════════════════════════════════════
# 화면 문구 — 4개 국어
#   이 모듈은 ops 전용(dashboard.py 는 쓰지 않는다)이지만, ops_ui 를 import 하면
#   순환 참조가 생길 여지가 있어 watcher_panel 과 같은 방식으로 자기 표를 든다.
#   lang 기본값은 "ko" 라 lang 을 넘기지 않는 호출부는 그대로 동작한다.
# ══════════════════════════════════════════════════════════
_OD = {
"ko": {
 "kept": "📚 영구 보관 {n}건 (성공 {ok} · 실패 {ng})",
 "no_audit": "아직 발송 기록이 없습니다",
 "session_only": "⚠️ 세션 사본을 표시 중입니다 — 새로고침하면 사라집니다 (DB 저장이 비활성 상태)",
 "no_store": "audit_store 미탑재 — 삭제 기능이 비활성화됩니다.",
 "no_saved": "아직 저장된 감사 기록이 없습니다.",
 "scope": "삭제 범위", "scope_period": "기간", "scope_all": "전체",
 "keep_days": "보존 기간(일)", "keep_fail": "실패 기록은 보존",
 "keep_fail_help": "실패한 발송은 '왜 안 갔는지'의 증거라 남기는 쪽이 안전합니다",
 "prepare": "🧹 삭제 준비",
 "prepare_note": "삭제할 범위를 고르고 [삭제 준비]를 누르면, 몇 건이 지워지는지 먼저 확인할 수 있습니다.",
 "nothing": "{scope} 중 지울 것이 없습니다.", "close": "닫기",
 "confirm_cb": "위 내용을 확인했으며 {n}건을 삭제합니다",
 "purge": "🗑 영구 삭제", "cancel": "취소",
 "redo_fail": "재분석 실패: {e}",
 "t_ml": "🧪 ML 모델", "ml_ok": "✅ 모델 로드 성공 — {info}", "ml_ng": "❌ 모델 로드 실패: {e}",
 "rag_none": "RAG 팩토리 미설정", "rag_ok": "✅ RAG 검색 성공 — {n}건", "rag_ng": "❌ RAG 실패: {e}",
 "llm_none": "LLM 팩토리 미설정", "llm_ng": "❌ LLM 연결 실패: {e}",
 "t_notify": "📨 알림", "notifier_none": "Notifier 팩토리 미설정",
 "no_smtp": "⚠ SMTP 미설정 (SMTP_USER/PASS)", "no_slack": "⚠ Slack webhook 미설정",
 "notify_ng": "❌ 알림 진단 실패: {e}",
 "scope_all_txt": "**전체 기록**",
 "scope_days_txt": "**{d}일 이전** 기록",
 "mode_days": "N일 이전만",
 "mode_all": "⚠ 전체 기록",
 "purge_warn": "### ⚠️ 되돌릴 수 없습니다\n\n{scope} **{n}건**을 영구 삭제합니다.",
 "purge_keep": "\n\n실패 기록은 보존됩니다.",
 "purge_nokeep": "\n\n**실패 기록까지 함께 지웁니다** — '왜 안 갔는지'의 증거가 사라집니다.",
 "purge_tail": "\n\n삭제 사실(시각·건수·수행자)은 로그에 한 줄로 남습니다.",
},
"en": {
 "kept": "📚 {n} kept permanently ({ok} ok · {ng} failed)",
 "no_audit": "No sends recorded yet",
 "session_only": "⚠️ Showing a session copy — it disappears on refresh (DB persistence is off)",
 "no_store": "audit_store not installed — deletion is disabled.",
 "no_saved": "No audit records saved yet.",
 "scope": "Delete scope", "scope_period": "By period", "scope_all": "Everything",
 "keep_days": "Retention (days)", "keep_fail": "Keep failed sends",
 "keep_fail_help": "Failed sends are the evidence for 'why it never arrived' — keeping them is safer",
 "prepare": "🧹 Prepare deletion",
 "prepare_note": "Pick a scope and press [Prepare deletion] to see how many rows would go first.",
 "nothing": "Nothing to delete in {scope}.", "close": "Close",
 "confirm_cb": "I have reviewed the above and will delete {n} rows",
 "purge": "🗑 Delete permanently", "cancel": "Cancel",
 "redo_fail": "Re-analysis failed: {e}",
 "t_ml": "🧪 ML model", "ml_ok": "✅ Model loaded — {info}", "ml_ng": "❌ Model load failed: {e}",
 "rag_none": "No RAG factory configured", "rag_ok": "✅ RAG search worked — {n} hits",
 "rag_ng": "❌ RAG failed: {e}",
 "llm_none": "No LLM factory configured", "llm_ng": "❌ LLM connection failed: {e}",
 "t_notify": "📨 Notifications", "notifier_none": "No Notifier factory configured",
 "no_smtp": "⚠ SMTP not configured (SMTP_USER/PASS)", "no_slack": "⚠ Slack webhook not set",
 "notify_ng": "❌ Notification check failed: {e}",
 "scope_all_txt": "**all records**",
 "scope_days_txt": "records **older than {d} days**",
 "mode_days": "Older than N days",
 "mode_all": "⚠ Everything",
 "purge_warn": "### ⚠️ This cannot be undone\n\nPermanently deleting **{n} rows** of {scope}.",
 "purge_keep": "\n\nFailed sends will be kept.",
 "purge_nokeep": "\n\n**Failed sends will be deleted too** — the evidence for 'why it never arrived' disappears.",
 "purge_tail": "\n\nThe deletion itself (time, count, who) is recorded in the log.",
},
"ja": {
 "kept": "📚 永久保存 {n}件（成功 {ok} · 失敗 {ng}）",
 "no_audit": "まだ送信記録がありません",
 "session_only": "⚠️ セッションのコピーを表示中です — 再読み込みで消えます（DB保存が無効）",
 "no_store": "audit_store 未搭載 — 削除機能は無効です。",
 "no_saved": "まだ保存された監査記録がありません。",
 "scope": "削除範囲", "scope_period": "期間", "scope_all": "全体",
 "keep_days": "保存期間（日）", "keep_fail": "失敗記録は保存",
 "keep_fail_help": "失敗した送信は「なぜ届かなかったか」の証拠なので、残すほうが安全です",
 "prepare": "🧹 削除の準備",
 "prepare_note": "削除範囲を選び［削除の準備］を押すと、何件消えるか先に確認できます。",
 "nothing": "{scope} に削除するものがありません。", "close": "閉じる",
 "confirm_cb": "上記を確認し、{n}件を削除します",
 "purge": "🗑 完全に削除", "cancel": "キャンセル",
 "redo_fail": "再分析に失敗: {e}",
 "t_ml": "🧪 MLモデル", "ml_ok": "✅ モデル読み込み成功 — {info}",
 "ml_ng": "❌ モデル読み込み失敗: {e}",
 "rag_none": "RAGファクトリ未設定", "rag_ok": "✅ RAG検索成功 — {n}件",
 "rag_ng": "❌ RAG失敗: {e}",
 "llm_none": "LLMファクトリ未設定", "llm_ng": "❌ LLM接続失敗: {e}",
 "t_notify": "📨 通知", "notifier_none": "Notifierファクトリ未設定",
 "no_smtp": "⚠ SMTP未設定 (SMTP_USER/PASS)", "no_slack": "⚠ Slack webhook 未設定",
 "notify_ng": "❌ 通知診断に失敗: {e}",
 "scope_all_txt": "**全記録**",
 "scope_days_txt": "**{d}日以前**の記録",
 "mode_days": "N日以前のみ",
 "mode_all": "⚠ 全記録",
 "purge_warn": "### ⚠️ 元に戻せません\n\n{scope} **{n}件**を完全に削除します。",
 "purge_keep": "\n\n失敗記録は保存されます。",
 "purge_nokeep": "\n\n**失敗記録も一緒に消します** — 「なぜ届かなかったか」の証拠が失われます。",
 "purge_tail": "\n\n削除の事実（時刻・件数・実行者）はログに1行残ります。",
},
"zh": {
 "kept": "📚 永久保存 {n}条（成功 {ok} · 失败 {ng}）",
 "no_audit": "尚无发送记录",
 "session_only": "⚠️ 正在显示会话副本 — 刷新后会消失（数据库持久化已关闭）",
 "no_store": "未安装 audit_store — 删除功能已禁用。",
 "no_saved": "尚无已保存的审计记录。",
 "scope": "删除范围", "scope_period": "按期间", "scope_all": "全部",
 "keep_days": "保留期限（天）", "keep_fail": "保留失败记录",
 "keep_fail_help": "失败的发送是「为何未送达」的证据，保留更安全",
 "prepare": "🧹 准备删除",
 "prepare_note": "选择删除范围并点击［准备删除］，可先确认将删除多少条。",
 "nothing": "{scope} 中没有可删除的内容。", "close": "关闭",
 "confirm_cb": "我已确认以上内容，将删除 {n} 条",
 "purge": "🗑 永久删除", "cancel": "取消",
 "redo_fail": "重新分析失败: {e}",
 "t_ml": "🧪 ML 模型", "ml_ok": "✅ 模型加载成功 — {info}", "ml_ng": "❌ 模型加载失败: {e}",
 "rag_none": "未配置 RAG 工厂", "rag_ok": "✅ RAG 检索成功 — {n} 条",
 "rag_ng": "❌ RAG 失败: {e}",
 "llm_none": "未配置 LLM 工厂", "llm_ng": "❌ LLM 连接失败: {e}",
 "t_notify": "📨 通知", "notifier_none": "未配置 Notifier 工厂",
 "no_smtp": "⚠ 未配置 SMTP (SMTP_USER/PASS)", "no_slack": "⚠ 未设置 Slack webhook",
 "notify_ng": "❌ 通知诊断失败: {e}",
 "scope_all_txt": "**全部记录**",
 "scope_days_txt": "**{d} 天以前**的记录",
 "mode_days": "仅 N 天以前",
 "mode_all": "⚠ 全部记录",
 "purge_warn": "### ⚠️ 无法撤销\n\n将永久删除 {scope} 中的 **{n} 条**。",
 "purge_keep": "\n\n失败记录将被保留。",
 "purge_nokeep": "\n\n**失败记录也会一并删除** — 「为何未送达」的证据将消失。",
 "purge_tail": "\n\n删除行为本身（时间、条数、执行人）会在日志中留下一行。",
},
}


def _o(lang: str) -> dict:
    """언어별 문구. 모르는 언어는 한국어로 폴백."""
    return _OD.get(lang) or _OD["ko"]


def render_audit(session_state, T: dict, limit: int = 10, db_path=None,
                 lang: str = "ko"):
    O = _o(lang)
    """감사 로그 패널.

    DB(notify_audit)가 있으면 **그쪽이 진실**이다 — 세션 사본은 새로고침이면
    사라지므로 감사 자료가 될 수 없다. DB 를 못 읽을 때만 세션 사본으로 내려간다.
    """
    rows = []
    if db_path and astore_audit and astore_audit.table_exists(db_path):
        rows = astore_audit.recent(db_path, limit=limit)
    if rows:
        s = astore_audit.stats(db_path)
        st.caption(O["kept"].format(n=f"{s['rows']:,}", ok=f"{s['ok']:,}",
                                    ng=f"{s['fail']:,}")
                   + f" · {astore_audit.to_local(s['oldest'], db_path)} ~ "
                     f"{astore_audit.to_local(s['newest'], db_path)}")
        for r in rows:
            st.caption(_audit_line(
                r["ok"], astore_audit.to_local(r["sent_at"], db_path), r["channel"],
                r["fraud_type"], r["risk_score"], r["txn_id"], r["recipient"],
                r["mask_level"], r["via"], r["error"]))
        return

    aud = session_state.get(AUDIT_KEY) or []
    if not aud:
        st.caption(O["no_audit"])
        return
    st.caption(O["session_only"])
    for a in aud[-limit:][::-1]:
        st.caption(_audit_line(a["ok"], a["at"], a["ch"], a["ft"], a["risk"],
                               a.get("txn"), a["to"], a["mask"],
                               a.get("via"), a.get("err")))


def render_audit_purge(session_state, T: dict, db_path, key_prefix: str = "aud",
                       lang: str = "ko"):
    O = _o(lang)
    """🧹 감사 로그 삭제 — **2단계 확인**.

    왜 두 단계인가
      감사 로그는 '되돌릴 수 없는 발송'의 유일한 증거다. 버튼 한 번에 사라지면
      실수로 지운 뒤 복구할 방법이 없다. 그래서
        ① 범위를 고르고 [삭제 준비] → **몇 건이 지워지는지 세어서 보여준다**
        ② 경고를 읽고 체크 + [영구 삭제] 를 눌러야 실제로 지운다
      1단계에서 건수를 먼저 보여주는 것이 핵심이다 — 몇 건이 사라지는지 모르는
      채로 누르는 삭제는 확인 절차가 아니다.

    삭제 자체도 로그에 남는다(audit_store.purge 참조).
    """
    if not (db_path and astore_audit):
        st.caption(O["no_store"])
        return
    if not astore_audit.table_exists(db_path):
        st.caption(O["no_saved"])
        return

    _PEND = f"_{key_prefix}_purge_pending"
    pending = session_state.get(_PEND)

    c1, c2, c3 = st.columns([1.5, 1.2, 1.3], vertical_alignment="bottom")
    mode = c1.radio(O["scope"], ["기간", "전체"], horizontal=True,
                    key=f"{key_prefix}_purge_mode",
                    format_func=lambda m: (O["mode_days"] if m == "기간"
                                           else O["mode_all"]))
    days = c2.number_input(O["keep_days"], 1, 3650, 90,
                           key=f"{key_prefix}_purge_days",
                           disabled=(mode == "전체"))
    keep_failed = c3.toggle(O["keep_fail"], value=True,
                            key=f"{key_prefix}_purge_keepfail",
                            help=O["keep_fail_help"])

    _days = None if mode == "전체" else int(days)
    if st.button(O["prepare"], key=f"{key_prefix}_purge_prep", width="stretch"):
        n = astore_audit.count_matching(db_path, before_days=_days)
        session_state[_PEND] = {"days": _days, "n": n, "keep_failed": bool(keep_failed)}
        st.rerun()

    if not pending:
        st.caption(O["prepare_note"])
        return

    # ── 2단계: 실제로 무엇이 사라지는지 보여주고 다시 묻는다 ──
    n = int(pending.get("n") or 0)
    scope = (O["scope_all_txt"] if pending["days"] is None
             else O["scope_days_txt"].format(d=pending["days"]))
    if not n:
        st.info(O["nothing"].format(scope=scope))
        if st.button(O["close"], key=f"{key_prefix}_purge_none"):
            session_state.pop(_PEND, None)
            st.rerun()
        return

    st.warning(
        O["purge_warn"].format(scope=scope, n=f"{n:,}")
        + (O["purge_keep"] if pending.get("keep_failed") else O["purge_nokeep"])
        + O["purge_tail"])

    ok = st.checkbox(O["confirm_cb"].format(n=f"{n:,}"),
                     key=f"{key_prefix}_purge_ack")
    b1, b2 = st.columns(2)
    if b1.button(O["purge"], key=f"{key_prefix}_purge_go", type="primary",
                 width="stretch", disabled=not ok):
        n_del, msg = astore_audit.purge(
            db_path, before_days=pending["days"],
            reviewer=str(session_state.get("reviewer") or ""),
            keep_failed=bool(pending.get("keep_failed")))
        session_state.pop(_PEND, None)
        session_state.pop(f"{key_prefix}_purge_ack", None)
        if n_del:
            # 세션 사본도 함께 비운다 — DB 는 비었는데 화면엔 남아 있으면 혼란스럽다
            session_state[AUDIT_KEY] = []
            st.success(msg)
        else:
            st.info(msg)
        st.rerun()
    if b2.button(O["cancel"], key=f"{key_prefix}_purge_cancel", width="stretch"):
        session_state.pop(_PEND, None)
        session_state.pop(f"{key_prefix}_purge_ack", None)
        st.rerun()


# ══════════════════════════════════════════════════════════
# 자동 발송
# ══════════════════════════════════════════════════════════
def auto_send(det: dict, session_state, *, notifier_factory, email_resolver,
              compose_slack, compose_email, mask_level: str = "-",
              db_path=None) -> dict:
    """탐지 직후 자동 Slack/Email 발송. det 를 제자리에서 갱신하고 돌려준다.

    ⚠️ Notifier 는 실패 시 예외가 아니라 **False 를 반환**한다. '예외 없으면 성공'
    으로 판정하면 웹훅 미설정·발송 실패에도 "발송 완료" 뱃지가 뜬다(dashboard v5 버그).
    반환값을 그대로 기록하고, 수신 주소가 없으면 시도 자체를 건너뛴다.

    compose_slack(det, tier) -> str
    compose_email(det, tier) -> str  또는  (평문, html|None, 첨부|None)
      v5: 리치 컴포저(notify_compose.email_single)가 3-튜플을 돌려주므로 둘 다 받는다.
    """
    tier = notify_tier(session_state, det.get('risk_score', 0))
    det['notify_tier'] = tier

    slack_go = bool(session_state.get('auto_slack', False)) and tier != 'none'
    email_go = bool(session_state.get('auto_email', False)) and tier in ('single', 'confirm')

    _txn = str(det.get('txn_id') or '')

    if slack_go:
        try:
            _body = compose_slack(det, tier)
        except Exception as e:
            # 본문 생성 실패도 '나가지 못한 사건'이다 — 감사 로그에 남긴다.
            #   예전에는 이 경로의 예외가 audit_append 를 통째로 건너뛰어,
            #   화면에는 실패가 뜨는데 감사 로그는 비어 있었다.
            det['auto_slack_sent'] = False
            det['notify_error_slack'] = f"본문 생성 실패: {e}"
            audit_append(session_state, ok=False, channel="slack",
                         fraud_type=det.get('fraud_type'),
                         risk_score=det.get('risk_score'), to="webhook",
                         mask_level=mask_level, via="auto", txn_id=_txn,
                         error=f"본문 생성 실패: {e}", db_path=db_path)
            log.warning(f"자동 Slack 본문 생성 실패: {e}")
        else:
            ok, err = send_manual(
                session_state, channel="slack", body=_body,
                notifier_factory=notifier_factory,
                fraud_type=det.get('fraud_type'), risk_score=det.get('risk_score'),
                mask_level=mask_level, txn_id=_txn, via="auto", db_path=db_path)
            det['auto_slack_sent'] = ok
            if not ok:
                det['notify_error_slack'] = err

    if email_go:
        to = ""
        try:
            to = email_resolver()
        except Exception as e:
            log.warning(f"수신 이메일 확인 실패: {e}")
        if not to:
            # 시도조차 못 한 것도 기록한다 — "왜 메일이 안 왔지?"의 답이 여기 있어야 한다
            det['auto_email_sent'] = False
            det['notify_error_email'] = "수신 이메일 미설정"
            audit_append(session_state, ok=False, channel="email",
                         fraud_type=det.get('fraud_type'),
                         risk_score=det.get('risk_score'), to="",
                         mask_level=mask_level, via="auto", txn_id=_txn,
                         error="수신 이메일 미설정", db_path=db_path)
            log.warning("수신 이메일 미설정 — 자동 발송 생략")
        else:
            try:
                _body = compose_email(det, tier)
            except Exception as e:
                det['auto_email_sent'] = False
                det['notify_error_email'] = f"본문 생성 실패: {e}"
                audit_append(session_state, ok=False, channel="email",
                             fraud_type=det.get('fraud_type'),
                             risk_score=det.get('risk_score'), to=to,
                             mask_level=mask_level, via="auto", txn_id=_txn,
                             error=f"본문 생성 실패: {e}", db_path=db_path)
                log.warning(f"자동 Email 본문 생성 실패: {e}")
            else:
                # 컴포저가 (평문, html, 첨부) 를 주면 그대로 실어 보낸다
                _html, _atts = None, None
                if isinstance(_body, tuple):
                    _body, _html, _atts = (list(_body) + [None, None])[:3]
                ok, err = send_manual(
                    session_state, channel="email", body=_body or "",
                    notifier_factory=notifier_factory,
                    fraud_type=det.get('fraud_type'), risk_score=det.get('risk_score'),
                    to=to,
                    subject=tier_subject(tier, det.get('fraud_type'),
                                         det.get('risk_score')),
                    mask_level=mask_level, txn_id=_txn, via="auto",
                    db_path=db_path, html=_html, attachments=_atts)
                det['auto_email_sent'] = ok
                if not ok:
                    det['notify_error_email'] = err
    return det


def compose_slack_default(det: dict, tier: str, session_state) -> str:
    txt = (det.get('llm') or {}).get('slack', '') or ""
    head = tier_head(session_state, tier, det.get('risk_score', 0))
    return (head + "\n\n" + txt) if head else txt


def compose_email_default(det: dict, tier: str, session_state) -> str:
    txt = (det.get('llm') or {}).get('email', '') or ""
    head = tier_head(session_state, tier, det.get('risk_score', 0))
    return (head + "\n\n" + txt) if head else txt


# ══════════════════════════════════════════════════════════
# 🔁 LLM 단계 재실행 — 마음에 안 드는 한 단계만 다시
# ══════════════════════════════════════════════════════════
def redo_llm_step(det: dict, step: str, *, analyzer_factory, masker_factory,
                  rag_factory, lang: str = "ko", rag_k: int = 3) -> bool:
    """analysis / slack / email 중 **한 단계만** 재생성해 det['llm'] 을 갱신.

    왜 필요한가: 3단계를 통으로 다시 돌리면 최대 6분 45초(1536+200+1536 토큰)가
    걸린다. Slack 문구만 어색할 때 분석까지 다시 뽑을 이유가 없다.
    """
    try:
        row = det.get('row') or {}
        clean = {k: v for k, v in row.items() if not str(k).startswith('_')}
        masked = masker_factory().mask_row(clean)
        fraud_type = det.get('fraud_type', '')
        risk_score = float(det.get('risk_score') or 0)
        anlz = analyzer_factory()
        llm = dict(det.get('llm') or {})
        existing = llm.get('analysis', '')

        if step == "analysis":
            rag = rag_factory(rag_k)
            ctx = rag.search(f"사기유형 {fraud_type} 이상거래 탐지 원인 분석", fraud_type)
            full = anlz.analyze(masked, fraud_type, risk_score, ctx, lang=lang)
            # analyze() 가 dict 가 아닌 str 을 반환할 수 있다 → .get() AttributeError 방지
            if isinstance(full, dict):
                llm['analysis'] = full.get('analysis', existing)
                llm['_diag'] = full.get('_diag', {})
            elif isinstance(full, str) and full.strip():
                llm['analysis'] = full

        elif step == "slack":
            p = (f"아래 FDS 분석 결과를 Slack 알림 2줄로 요약해주세요. "
                 f"첫 줄: 위험 레벨 이모지 + 유형 + 거래 요약, "
                 f"둘째 줄: 위험점수 + 조치 필요:\n\n{existing[:400]}")
            p += _lang_suffix(lang)
            out = anlz._call(p, max_tokens=200, timeout=45)
            if out:
                llm['slack'] = out

        elif step == "email":
            tx = masked.get('ID', masked.get('transaction_id', 'N/A'))
            amount = masked.get('Transaction_Amount', 'N/A')
            channel = masked.get('Channel', 'N/A')
            p = (f"아래 FDS 탐지 결과를 담당자에게 보낼 공식 이메일로 작성하세요.\n"
                 f"마크다운 기호 절대 사용하지 마세요. 순수 텍스트만 출력하세요.\n"
                 f"제목: [FDS 긴급] {str(fraud_type).upper()}형 이상거래 탐지 (거래ID: {tx})\n\n"
                 f"담당자 귀중,\nFDS 시스템에서 이상거래를 탐지하였습니다.\n\n"
                 f"사기 유형: {str(fraud_type).upper()}형 / 위험 점수: {risk_score:.4f}\n"
                 f"거래 ID: {tx} / 금액: {amount}원 / 채널: {channel}\n\n"
                 f"AI 분석 결과:\n{existing}\n\n"
                 f"본 메일은 FDS 자동화 시스템에 의해 발송되었습니다.")
            p += _lang_suffix(lang)
            out = anlz._call(p, max_tokens=1536, timeout=180)
            if out:
                llm['email'] = out
        else:
            return False

        det['llm'] = llm
        return True
    except Exception as e:
        log.warning(f"{step} 재분석 실패: {e}")
        st.toast(f"❌ {step} 재분석 실패: {e}")
        return False


def _lang_suffix(lang: str) -> str:
    """UI 언어가 한국어가 아니면 해당 언어로 답하도록 지시.
    (RAG 지식베이스·기본 프롬프트는 한국어 코퍼스 기반이라 그대로 둔다)"""
    try:
        from i18n_data import llm_lang_directive
        return llm_lang_directive(lang)
    except Exception:
        return ""


# ══════════════════════════════════════════════════════════
# 🔌 연결 테스트 — "왜 알림이 안 오지?" 를 3초 안에 답한다
# ══════════════════════════════════════════════════════════
def render_connection_tests(T: dict, *, lang: str = "ko", model_path=None, rag_factory=None,
                            analyzer_factory=None, notifier_factory=None,
                            key_prefix: str = "ops"):
    """ML · RAG · LLM · 알림 4종 진단 버튼.

    ⚠️ LLM 테스트는 analyze() 풀 생성(3단계·최대 6분 45초)이 아니라
    test_connection()(32토큰 / 12초 ping)을 쓴다. 연결 확인에 6분을 쓸 이유가 없다.
    """
    c1, c2, c3, c4 = st.columns(4)

    with c1:
        if st.button(_o(lang)["t_ml"], key=f"{key_prefix}_test_ml", width='stretch'):
            try:
                from pipeline import detect_io as dio
                clf, mode, _ = dio.resolve_classifier(model_path, {})
                st.success(_o(lang)["ml_ok"].format(info=mode[0] if mode else "ok"))
            except Exception as e:
                st.error(_o(lang)["ml_ng"].format(e=e))

    with c2:
        if st.button("📚 RAG", key=f"{key_prefix}_test_rag", width='stretch'):
            if rag_factory is None:
                st.warning(_o(lang)["rag_none"])
            else:
                try:
                    ctx = rag_factory(1).search("이상거래 탐지", "a")
                    st.success(_o(lang)["rag_ok"].format(
                        n=len(ctx) if isinstance(ctx, list) else "OK"))
                except Exception as e:
                    st.error(_o(lang)["rag_ng"].format(e=e))

    with c3:
        if st.button("🧠 LLM", key=f"{key_prefix}_test_llm", width='stretch'):
            if analyzer_factory is None:
                st.warning(_o(lang)["llm_none"])
            else:
                try:
                    r = analyzer_factory().test_connection()
                    if r.get("ok"):
                        st.success(r.get("message", "✅ 연결 성공"))
                    else:
                        st.error(r.get("message", "❌ 연결 실패"))
                        for e in r.get("errors", [])[:4]:
                            st.caption(f"• {e}")
                except Exception as e:
                    st.error(_o(lang)["llm_ng"].format(e=e))

    with c4:
        if st.button(_o(lang)["t_notify"], key=f"{key_prefix}_test_notify", width='stretch'):
            if notifier_factory is None:
                st.warning(_o(lang)["notifier_none"])
            else:
                try:
                    # 객체 생성만 하고 성공 표시하면 안 된다 — 실제 접속·로그인까지 확인
                    n = notifier_factory()
                    stat = n.check_status()
                    if stat.get("smtp_configured"):
                        ok, detail = n.test_smtp()
                        (st.success if ok else st.error)(
                            f"{'✅' if ok else '❌'} SMTP: {detail}")
                    else:
                        st.warning(_o(lang)["no_smtp"])
                    if stat.get("slack_configured"):
                        st.success(f"✅ Slack webhook: {stat.get('slack_url_prefix', '')}")
                    else:
                        st.warning(_o(lang)["no_slack"])
                except Exception as e:
                    st.error(_o(lang)["notify_ng"].format(e=e))

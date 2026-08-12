"""
ops_ui — 관제 대시보드 테마 · 다국어 · 렌더 헬퍼  ✨ v19 신규

왜 별도 파일인가
  dashboard.py 는 5,700줄이고 테마·CSS·i18n·헬퍼가 전역 코드로 뒤섞여 있어
  import 하는 순간 st.set_page_config 까지 실행된다. 재사용이 불가능하다.
  이 파일은 그 중 **관제 화면에 필요한 부분만** 순수 함수로 추출한 것이다.

i18n 전략 — i18n_data.py 를 수정하지 않는다
  신규 문구(오탐 판정 등)는 여기 _OPS 표에 4개국어로 넣고,
  기존 문구(사기 유형명·테마명)는 i18n_data 에서 그대로 가져온다.
  dashboard.py 의 tt() + _V5_KO 폴백 패턴과 같은 방식이라,
  i18n_data.py 가 없거나 구버전이어도 한국어로는 동작한다.

테마
  dashboard.py:206 의 NEW_THEMES 7종을 그대로 옮겼다. 색상값은 손대지 않았다 —
  메인 대시보드와 관제 화면의 색이 다르면 같은 제품으로 안 보인다.
  기본값만 'amber' 로 바꿨다. i18n_data 가 이 테마에 붙인 이름이
  **"야간 관제 앰버(Night-watch Amber)"** 라, 24시간 관제 화면의 의도와 정확히 맞는다.
"""

from __future__ import annotations

import html
import logging

log = logging.getLogger(__name__)

OPS_UI_VERSION = "v30"


def _esc(v) -> str:
    """unsafe_allow_html 로 나가는 값은 전부 이걸 거친다.
    검토자 이름처럼 사람이 타이핑한 문자열이 섞이므로, `<` 하나에 레이아웃이
    통째로 깨지는 일을 막는다."""
    return html.escape(str(v if v is not None else ""))

# ── i18n_data 브리지 (없어도 죽지 않는다) ──────────────────
try:
    from i18n_data import (LANG_OPTIONS, LANG_DISPLAY, make_t,
                           FRAUD_LABELS_I18N, FRAUD_SHORT_I18N,
                           NEW_THEME_META_I18N, NEW_THEME_ORDER)
    HAS_I18N_DATA = True
except ImportError:                                   # pragma: no cover
    HAS_I18N_DATA = False
    LANG_OPTIONS = ["ko", "en", "ja", "zh"]
    LANG_DISPLAY = {"ko": "🇰🇷 한국어", "en": "🇺🇸 English",
                    "ja": "🇯🇵 日本語", "zh": "🇨🇳 中文"}
    NEW_THEME_ORDER = ['amber', 'dark', 'light', 'evergreen', 'ivory', 'crimson', 'slate']
    NEW_THEME_META_I18N = {}
    # detect_service.FRAUD_TYPE_NAMES 최소 사본 (한국어만)
    _KO_FT = {'a': '원격제어 사기', 'b': '단말 탈취 사기', 'c': '명의 도용 사기',
              'd': '대출 빙자 사기', 'e': 'ATM 사기', 'f': '피싱 사기',
              'g': '스미싱 사기', 'h': '계좌 이상 사기', 'i': '다중 시도 사기',
              'j': '수취 정지 사기', 'k': '오픈뱅킹 사기', 'l': '기타 사기',
              'm': '정상 거래'}
    FRAUD_LABELS_I18N = {lg: _KO_FT for lg in LANG_OPTIONS}
    FRAUD_SHORT_I18N = FRAUD_LABELS_I18N

    def make_t(session_state):
        def t(key, **kw):
            return key
        return t


# ══════════════════════════════════════════════════════════
# 테마 — dashboard.py:206 NEW_THEMES 원본 유지
# ══════════════════════════════════════════════════════════

THEMES = {
    'amber': {  # 기본 — "야간 관제 앰버"
        "bg_base": "#101216", "bg_surface": "#15181e", "bg_card": "#1a1e26", "bg_card_hover": "#212631",
        "accent": "#e0a13f", "accent_dim": "#c78a2c", "accent_rgb": "224,161,63",
        "red": "#e85d75", "red_dim": "#cc4560",
        "amber": "#e8c063", "green": "#4fc48f", "blue": "#6aa7e8", "purple": "#a68fe0",
        "text_primary": "#ece7dd", "text_secondary": "#9a948a", "text_muted": "#5d594f",
        "plotly_colors": ["#e0a13f", "#6aa7e8", "#a68fe0", "#e8c063", "#e85d75", "#4fc48f"],
    },
    'dark': {
        "bg_base": "#0b0f17", "bg_surface": "#10151f", "bg_card": "#141b28", "bg_card_hover": "#1a2233",
        "accent": "#6c8cff", "accent_dim": "#5272e8", "accent_rgb": "108,140,255",
        "red": "#ef5872", "red_dim": "#d43f5c",
        "amber": "#eab24a", "green": "#3ecf8e", "blue": "#58a6ff", "purple": "#a78bfa",
        "text_primary": "#e8edf7", "text_secondary": "#8b96ab", "text_muted": "#535e73",
        "plotly_colors": ["#6c8cff", "#58a6ff", "#a78bfa", "#eab24a", "#ef5872", "#3ecf8e"],
    },
    'light': {
        "bg_base": "#f6f8fb", "bg_surface": "#edf0f6", "bg_card": "#ffffff", "bg_card_hover": "#f7f9fc",
        "accent": "#3b5bdb", "accent_dim": "#2f4ac2", "accent_rgb": "59,91,219",
        "red": "#d6455f", "red_dim": "#b83350",
        "amber": "#b07310", "green": "#0e9f6e", "blue": "#1d6fd8", "purple": "#7c5cd6",
        "text_primary": "#131b2c", "text_secondary": "#4b566b", "text_muted": "#96a0b5",
        "plotly_colors": ["#3b5bdb", "#1d6fd8", "#7c5cd6", "#b07310", "#d6455f", "#0e9f6e"],
    },
    'evergreen': {
        "bg_base": "#0c1310", "bg_surface": "#101a15", "bg_card": "#14211b", "bg_card_hover": "#1a2a22",
        "accent": "#35c28f", "accent_dim": "#27a377", "accent_rgb": "53,194,143",
        "red": "#e56176", "red_dim": "#c74a60",
        "amber": "#d9a842", "green": "#52d6a2", "blue": "#57b3d9", "purple": "#9d92e0",
        "text_primary": "#e2efe8", "text_secondary": "#8aa396", "text_muted": "#4e6157",
        "plotly_colors": ["#35c28f", "#57b3d9", "#9d92e0", "#d9a842", "#e56176", "#52d6a2"],
    },
    'ivory': {
        "bg_base": "#faf7f2", "bg_surface": "#f1ece3", "bg_card": "#ffffff", "bg_card_hover": "#faf8f4",
        "accent": "#1f3a68", "accent_dim": "#16294c", "accent_rgb": "31,58,104",
        "red": "#b3324b", "red_dim": "#93263c",
        "amber": "#8a6410", "green": "#1a7d5c", "blue": "#2456a8", "purple": "#6a4fa8",
        "text_primary": "#201c14", "text_secondary": "#5a5344", "text_muted": "#a39a88",
        "plotly_colors": ["#1f3a68", "#2456a8", "#6a4fa8", "#8a6410", "#b3324b", "#1a7d5c"],
    },
    'crimson': {
        "bg_base": "#120d0e", "bg_surface": "#181114", "bg_card": "#1e1518", "bg_card_hover": "#271b1f",
        "accent": "#e0405a", "accent_dim": "#c22e47", "accent_rgb": "224,64,90",
        "red": "#ff7454", "red_dim": "#e05a3e",
        "amber": "#e5aa4e", "green": "#3fc98e", "blue": "#6b9fe8", "purple": "#b08cf0",
        "text_primary": "#f2e9eb", "text_secondary": "#a89298", "text_muted": "#63535a",
        "plotly_colors": ["#e0405a", "#6b9fe8", "#b08cf0", "#e5aa4e", "#ff7454", "#3fc98e"],
    },
    'slate': {
        "bg_base": "#0e0f16", "bg_surface": "#13141d", "bg_card": "#181a26", "bg_card_hover": "#1f2130",
        "accent": "#9d8cff", "accent_dim": "#8272e6", "accent_rgb": "157,140,255",
        "red": "#ee5d7d", "red_dim": "#d24565",
        "amber": "#e0ac52", "green": "#46c99a", "blue": "#64a5f0", "purple": "#bd9df5",
        "text_primary": "#eae9f5", "text_secondary": "#9694ad", "text_muted": "#585670",
        "plotly_colors": ["#9d8cff", "#64a5f0", "#bd9df5", "#e0ac52", "#ee5d7d", "#46c99a"],
    },
}

# 관제 기본 테마 — "야간 관제 앰버". 24시간 켜두는 화면이라 눈부심이 적어야 한다.
DEFAULT_THEME = "amber"
THEME_ORDER = [k for k in (["amber"] + list(NEW_THEME_ORDER)) if k in THEMES]
THEME_ORDER = list(dict.fromkeys(THEME_ORDER))


def theme_display(key: str, lang: str = "ko") -> str:
    meta = NEW_THEME_META_I18N.get(key, {})
    disp = (meta.get("display") or {}).get(lang, key)
    label = (meta.get("label") or {}).get(lang, "")
    return f"{disp} — {label}" if label else disp


def get_theme(key: str) -> dict:
    return THEMES.get(key, THEMES[DEFAULT_THEME])


def is_dark(theme: dict) -> bool:
    """배경 밝기로 다크/라이트 판정 — 차트 템플릿 선택에 쓴다."""
    h = theme["bg_base"].lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (0.299 * r + 0.587 * g + 0.114 * b) < 128


# ══════════════════════════════════════════════════════════
# 다국어 — 관제 화면 신규 문구
# ══════════════════════════════════════════════════════════

_OPS: dict[str, dict] = {}


def _a(key, ko, en, ja, zh):
    _OPS[key] = {"ko": ko, "en": en, "ja": ja, "zh": zh}


# ── 앱 ──
_a("app.title", "관제 · 오탐 대시보드", "Ops · False-Positive Console",
   "監視・誤検知コンソール", "监控 · 误报控制台")
_a("app.sub", "실시간 감시와 오탐 피드백을 한 화면에서",
   "Live monitoring and false-positive feedback in one place",
   "リアルタイム監視と誤検知フィードバックを一画面で",
   "实时监控与误报反馈，一屏掌握")

# ── 탭 ──
_a("tab.live", "🟢 실시간 감시", "🟢 Live", "🟢 リアルタイム", "🟢 实时监控")
_a("tab.triage", "🚨 알림 트리아지", "🚨 Triage", "🚨 トリアージ", "🚨 告警分诊")
_a("tab.log", "🗃 탐지 로그", "🗃 Detection log", "🗃 検知ログ", "🗃 检测日志")
_a("log.title", "탐지 로그", "Detection log", "検知ログ", "检测日志")
_a("log.search", "거래 ID 검색", "Search transaction ID", "取引ID検索", "搜索交易ID")
_a("log.pick", "행을 선택하면 그 시점의 데이터와 분석 결과를 함께 봅니다",
   "Select a row to see the data and the analysis captured at that moment",
   "行を選択すると、その時点のデータと分析結果を表示します",
   "选择一行以查看当时的数据和分析结果")
_a("log.cached", "분석 캐시 있음", "Analysis cached", "分析キャッシュあり", "已缓存分析")
_a("log.nocache", "이 시점에는 분석 결과가 캐시되지 않았습니다",
   "No analysis was cached at this point in time",
   "この時点の分析結果はキャッシュされていません",
   "该时间点未缓存分析结果")
_a("log.nocache_why",
   "캐시 훅을 붙이기 전에 탐지된 건입니다. LLM 리포트는 발송 시점에만 존재했고 DB에 기록되지 않아 복원할 수 없습니다. 훅을 붙이면 이후 탐지분부터 남습니다.",
   "This was detected before the capture hook was attached. The LLM report existed only at send time and was never written to the DB, so it cannot be recovered. Attach the hook and future detections will be preserved.",
   "キャプチャフック導入前に検知された件です。LLMレポートは送信時点にのみ存在しDBに記録されないため復元できません。フックを付ければ以降の検知分から保存されます。",
   "这是在附加捕获钩子之前检测到的。LLM 报告仅存在于发送时刻，未写入数据库，无法恢复。附加钩子后，后续检测将被保留。")
_a("log.tab_data", "📄 당시 데이터", "📄 Data", "📄 当時のデータ", "📄 当时数据")
_a("log.tab_llm", "🧠 LLM 분석", "🧠 LLM analysis", "🧠 LLM分析", "🧠 LLM 分析")
_a("log.tab_proba", "📊 확률 분포", "📊 Probabilities", "📊 確率分布", "📊 概率分布")
_a("log.tab_sent", "📨 발송 내역", "📨 Sent", "📨 送信内容", "📨 发送记录")
_a("log.tab_env", "⚙ 당시 환경", "⚙ Environment", "⚙ 当時の環境", "⚙ 当时环境")
_a("log.verdict_hist", "판정 이력", "Verdict history", "判定履歴", "判定历史")
_a("log.cache_size", "캐시 용량", "Cache size", "キャッシュ容量", "缓存容量")
_a("log.prune", "오래된 캐시 정리", "Prune old cache", "古いキャッシュを整理", "清理旧缓存")
_a("log.hook_missing", "캐시 훅이 아직 붙지 않았습니다 — 워처에 2줄을 추가하세요",
   "Capture hook not attached yet — add 2 lines to the watcher",
   "キャプチャフック未導入 — ウォッチャーに2行追加してください",
   "尚未附加捕获钩子 — 请在监视器中添加 2 行")

_a("tab.fp", "📉 오탐 분석", "📉 FP Analysis", "📉 誤検知分析", "📉 误报分析")
_a("tab.tune", "⚙ 임계값 튜닝", "⚙ Threshold", "⚙ 閾値調整", "⚙ 阈值调优")
_a("tab.ai", "🧠 AI 분석·알림", "🧠 AI Analysis", "🧠 AI分析・通知", "🧠 AI 分析与通知")
_a("tab.diag", "🩺 진단", "🩺 Diagnostics", "🩺 診断", "🩺 诊断")
_a("tab.shift", "🔄 교대 인수인계", "🔄 Shift handover", "🔄 シフト引継ぎ", "🔄 交接班")

# ── 압축 탭 라벨 (tabc.*) ─────────────────────────────────
#   왜 필요한가 — 기본 라벨 8개를 늘어놓으면 한국어 기준 탭바가 약 1,100px 다.
#   1366px 노트북에서 사이드바(약 336px)를 빼면 본문은 1,030px 남으므로 **넘친다**
#   (탭이 줄바꿈되거나 잘려 마지막 탭이 안 보인다). 관제실 모니터가 넓으면 문제가
#   없으므로 기본은 끄고, 좁은 화면에서만 켜는 옵션으로 둔다.
#   ⚠ 순서는 건드리지 않는다 — 첫 탭은 어느 모드에서도 🧠 AI 분석이다.
_a("tabc.ai", "🧠 AI", "🧠 AI", "🧠 AI", "🧠 AI")
_a("tabc.triage", "🚨 트리아지", "🚨 Triage", "🚨 トリアージ", "🚨 分诊")
_a("tabc.live", "🟢 감시", "🟢 Live", "🟢 監視", "🟢 监控")
_a("tabc.shift", "🔄 인계", "🔄 Shift", "🔄 引継ぎ", "🔄 交接")
_a("tabc.log", "🗃 로그", "🗃 Log", "🗃 ログ", "🗃 日志")
_a("tabc.fp", "📉 오탐", "📉 FP", "📉 誤検知", "📉 误报")
_a("tabc.tune", "⚙ 임계값", "⚙ Threshold", "⚙ 閾値", "⚙ 阈值")
_a("tabc.diag", "🩺 진단", "🩺 Diag", "🩺 診断", "🩺 诊断")

# ── AI 분석·알림 ──
_a("ai.title", "AI 분석 · 알림 발송", "AI Analysis · Notify", "AI分析・通知送信", "AI 分析与通知发送")
_a("ai.desc",
   "판정 대기 알림 하나를 골라 LLM 분석을 돌리고, 필요하면 Slack/Email로 바로 발송합니다.",
   "Pick a pending alert, run an LLM analysis, and send it to Slack/Email if needed.",
   "判定待ちアラートを選んでLLM分析を実行し、必要ならSlack/Emailに送信します。",
   "选择一条待审告警运行 LLM 分析，需要时直接发送到 Slack/Email。")
_a("ai.pick", "분석할 알림", "Alert to analyze", "分析するアラート", "选择要分析的告警")
_a("ai.no_alert", "판정 대기 알림이 없습니다. 트리아지 탭을 먼저 확인하세요.",
   "No alerts awaiting review. Check the Triage tab first.",
   "判定待ちアラートがありません。まずトリアージタブを確認してください。",
   "暂无待审告警。请先查看分诊标签页。")
_a("ai.no_row", "이 거래의 원본 피처를 찾을 수 없습니다 (detections.raw_json 없음). "
   "이 알림은 캐시 훅 도입 이전에 탐지되었을 수 있습니다.",
   "Couldn't find the raw features for this transaction (no detections.raw_json). "
   "This alert may predate the capture hook.",
   "この取引の元データが見つかりません（detections.raw_jsonなし）。"
   "キャプチャフック導入前に検知された可能性があります。",
   "找不到该交易的原始特征（无 detections.raw_json）。该告警可能在捕获钩子启用前生成。")
_a("ai.settings", "LLM 설정", "LLM settings", "LLM設定", "LLM 设置")
_a("ai.provider", "제공자", "Provider", "プロバイダー", "提供商")
_a("ai.run", "🧠 AI 분석 실행", "🧠 Run AI analysis", "🧠 AI分析を実行", "🧠 运行 AI 分析")
_a("ai.running", "분석 중… (RAG 검색 → LLM 호출)", "Analyzing… (RAG search → LLM call)",
   "分析中…（RAG検索→LLM呼び出し）", "分析中…（RAG 检索 → 调用 LLM）")
_a("ai.analysis_header", "🧾 분석 리포트", "🧾 Analysis report", "🧾 分析レポート", "🧾 分析报告")
_a("ai.slack_header", "💬 Slack 미리보기", "💬 Slack preview", "💬 Slackプレビュー", "💬 Slack 预览")
_a("ai.email_header", "✉️ Email 미리보기", "✉️ Email preview", "✉️ Emailプレビュー", "✉️ Email 预览")
_a("ai.send_slack", "Slack로 발송", "Send to Slack", "Slackに送信", "发送到 Slack")
_a("ai.send_email", "Email로 발송", "Send email", "Emailを送信", "发送邮件")
_a("ai.email_to", "받는 사람", "To", "宛先", "收件人")
_a("ai.sent_ok", "✅ 발송 완료", "✅ Sent", "✅ 送信完了", "✅ 已发送")
_a("ai.sent_fail", "❌ 발송 실패: {e}", "❌ Send failed: {e}", "❌ 送信失敗: {e}", "❌ 发送失败：{e}")
_a("ai.no_webhook", "Slack Webhook URL이 설정되지 않았습니다",
   "Slack webhook URL is not set", "Slack Webhook URLが未設定です", "未设置 Slack Webhook URL")
_a("ai.no_smtp", "수신 이메일 주소가 없습니다", "No recipient email address",
   "宛先メールアドレスがありません", "没有收件邮箱地址")
_a("ai.cached", "💾 분석 캐시에 저장됨 — 로그 탭에서 다시 볼 수 있습니다",
   "💾 Saved to analysis cache — viewable in the Log tab",
   "💾 分析キャッシュに保存 — ログタブで再確認できます",
   "💾 已保存到分析缓存 — 可在日志标签页查看")
_a("ai.mask_off_warn",
   "⚠ 마스킹 레벨이 'off'입니다 — 개인정보가 그대로 LLM·발송 채널에 전달됩니다.",
   "⚠ Masking level is 'off' — personal data will be sent to the LLM/notify channels as-is.",
   "⚠ マスキングレベルが「off」です — 個人情報がそのままLLM・送信チャネルに渡ります。",
   "⚠ 脱敏级别为「off」— 个人信息将原样发送给 LLM 及通知渠道。")

# ── AI 분석 서브탭 ──
_a("ai.sub_single", "🔍 단건 분석", "🔍 Single alert", "🔍 単件分析", "🔍 单条分析")
_a("ai.sub_batch", "📦 배치 분석", "📦 Batch analysis", "📦 バッチ分析", "📦 批量分析")

# ── 배치 분석 ──
_a("batch.title", "배치 분석 · 알림", "Batch analysis · Notify", "バッチ分析・通知", "批量分析与通知")
_a("batch.desc",
   "최근 판정 대기 알림을 한 번에 모아 LLM 통합 리포트를 만들고, Slack/Email로 요약 발송합니다.",
   "Gather recent pending alerts at once, build a combined LLM report, and send a summary to Slack/Email.",
   "最近の判定待ちアラートをまとめてLLM統合レポートを作成し、Slack/Emailに要約送信します。",
   "一次性汇总最近的待审告警，生成 LLM 综合报告，并将摘要发送到 Slack/Email。")
_a("batch.window", "조회 기간(시간)", "Lookback window (hours)", "照会期間（時間）", "回溯时间（小时）")
_a("batch.limit", "최대 건수", "Max alerts", "最大件数", "最多告警数")
_a("batch.run", "📦 배치 분석 실행", "📦 Run batch analysis", "📦 バッチ分析を実行", "📦 运行批量分析")
_a("batch.running", "배치 분석 중… (분류 집계 → RAG → LLM 통합 리포트)",
   "Running batch analysis… (aggregate → RAG → LLM report)",
   "バッチ分析中…（集計→RAG→LLM統合レポート）",
   "批量分析中…（聚合 → RAG → LLM 综合报告）")
_a("batch.no_alerts", "선택한 기간 안에 판정 대기 알림이 없습니다.",
   "No alerts awaiting review in the selected window.",
   "選択した期間に判定待ちアラートがありません。",
   "所选时间范围内没有待审告警。")
_a("batch.skip_note", "{skip}건은 원본 피처를 찾지 못해 이번 배치에서 제외했습니다.",
   "{skip} alert(s) were excluded — raw features not found.",
   "{skip}件は元データが見つからず今回のバッチから除外しました。",
   "{skip} 条因找不到原始特征已从本次批量中排除。")
_a("batch.kpi_total", "포함 건수", "Included", "対象件数", "纳入数")
_a("batch.kpi_anomaly", "이상거래", "Anomalies", "異常取引", "异常交易")
_a("batch.kpi_avg", "평균 위험도", "Avg risk", "平均リスク", "平均风险")
_a("batch.kpi_max", "최고 위험도", "Max risk", "最高リスク", "最高风险")
_a("batch.report_header", "🧾 통합 리포트", "🧾 Combined report", "🧾 統合レポート", "🧾 综合报告")
_a("batch.top_risky", "고위험 상위 건", "Top risky", "高リスク上位", "高风险 Top")
_a("batch.included_ids", "포함된 거래 ID", "Included transaction IDs",
   "対象取引ID", "纳入的交易ID")

# ── AI 어시스턴트(챗봇) ──
_a("ai.sub_chat", "🤖 AI 어시스턴트", "🤖 AI Assistant", "🤖 AIアシスタント", "🤖 AI 助手")
_a("chat.desc",
   "지금 관제 화면의 실시간 상태(워처·알림 큐·오탐률·임계값)를 근거로만 답합니다. "
   "설정을 바꾸는 조작은 하지 않는 읽기 전용 어시스턴트입니다.",
   "Answers using only the live console state (watcher, alert queue, FP rate, thresholds). "
   "Read-only — it never changes settings for you.",
   "現在の管制画面のライブ状態(ウォッチャー・アラートキュー・誤検知率・閾値)のみを根拠に回答します。"
   "設定を変更しない読み取り専用アシスタントです。",
   "仅根据当前控制台的实时状态(监视器、告警队列、误报率、阈值)作答。"
   "只读助手，不会替你更改任何设置。")
_a("chat.empty", "아직 대화가 없습니다. 아래에 질문을 입력해보세요.",
   "No messages yet. Type a question below.",
   "まだ会話がありません。下に質問を入力してください。",
   "暂无对话。请在下方输入问题。")
_a("chat.input_ph", "예: 지금 워처 상태 어때? / 오탐률 추이 어때?",
   "e.g. How's the watcher doing? / What's the FP rate trend?",
   "例: ウォッチャーの状態は? / 誤検知率の推移は?",
   "例：监视器现在状态如何？/ 误报率趋势怎样？")
_a("chat.thinking", "생각 중…", "Thinking…", "考え中…", "思考中…")
_a("chat.clear", "대화 초기화", "Clear chat", "会話をクリア", "清空对话")
_a("chat.voice", "🎤 음성으로 질문", "🎤 Ask by voice", "🎤 音声で質問", "🎤 语音提问")
_a("chat.voice_record", "녹음", "Record", "録音", "录音")
_a("chat.voice_upload", "오디오 파일 업로드", "Upload audio file", "音声ファイルをアップロード",
   "上传音频文件")
_a("chat.voice_transcribing", "음성 인식 중…", "Transcribing…", "音声認識中…", "语音识别中…")
_a("chat.voice_fail", "음성 인식 실패: {why}", "Transcription failed: {why}",
   "音声認識失敗: {why}", "语音识别失败：{why}")
_a("chat.voice_ok", "🎤 인식됨: {text}", "🎤 Recognized: {text}",
   "🎤 認識結果: {text}", "🎤 识别结果：{text}")

# ── 탐지 입력 (세션5 5종 입력모드 이식) ──
_a("ai.sub_detect", "🎯 탐지 입력", "🎯 Detection Input", "🎯 検知入力", "🎯 检测输入")
_a("det.model_title", "탐지 모델", "Detection model", "検知モデル", "检测模型")
_a("det.tab1", "✏️ 직접입력", "✏️ Manual", "✏️ 手動入力", "✏️ 手动输入")
_a("det.tab2", "📄 test.csv", "📄 test.csv", "📄 test.csv", "📄 test.csv")
_a("det.tab3", "📊 train.csv", "📊 train.csv", "📊 train.csv", "📊 train.csv")
_a("det.tab4", "🧪 합성생성", "🧪 Synthetic", "🧪 合成生成", "🧪 合成生成")
_a("det.tab5", "📁 폴더배치", "📁 Folder batch", "📁 フォルダ一括", "📁 文件夹批量")
_a("det.run", "▶ 탐지 실행", "▶ Run detection", "▶ 検知実行", "▶ 运行检测")
_a("det.autofill", "⚡ 고위험 시나리오 자동입력", "⚡ Autofill high-risk scenario",
   "⚡ 高リスクシナリオ自動入力", "⚡ 自动填充高风险场景")
_a("det.section_txn", "거래 정보", "Transaction info", "取引情報", "交易信息")
_a("det.section_env", "환경 정보", "Environment info", "環境情報", "环境信息")
_a("det.section_flags", "위험 플래그", "Risk flags", "リスクフラグ", "风险标志")
_a("det.amount", "거래 금액", "Transaction amount", "取引金額", "交易金额")
_a("det.distance", "거리(km)", "Distance (km)", "距離(km)", "距离(km)")
_a("det.balance", "계좌 잔액", "Account balance", "口座残高", "账户余额")
_a("det.channel", "채널", "Channel", "チャネル", "渠道")
_a("det.os", "운영체제", "OS", "OS", "操作系统")
_a("det.sample_n", "표본 수", "Sample count", "サンプル数", "样本数")
_a("det.seed", "시드(-1=랜덤)", "Seed (-1=random)", "シード(-1=ランダム)", "种子(-1=随机)")
_a("det.extract", "🎲 무작위 추출", "🎲 Random sample", "🎲 ランダム抽出", "🎲 随机抽取")
_a("det.row_select", "행 선택", "Select row", "行選択", "选择行")
_a("det.gen_n", "생성 건수", "Count to generate", "生成件数", "生成数量")
_a("det.gen_type", "목표 유형", "Target type", "目標タイプ", "目标类型")
_a("det.gen_run", "🧪 합성 생성", "🧪 Generate", "🧪 合成生成", "🧪 生成合成数据")
_a("det.folder_path", "폴더 경로", "Folder path", "フォルダパス", "文件夹路径")
_a("det.folder_scan", "📂 폴더 스캔", "📂 Scan folder", "📂 フォルダスキャン", "📂 扫描文件夹")
_a("det.files_found", "{n}개 CSV 발견", "{n} CSV file(s) found", "{n}件のCSVを発見",
   "发现 {n} 个 CSV 文件")
_a("det.no_csv", "폴더에 CSV가 없습니다: {path}", "No CSV files in: {path}",
   "フォルダにCSVがありません: {path}", "文件夹中没有 CSV：{path}")
_a("det.no_testcsv", "test.csv를 찾을 수 없습니다: {path}", "test.csv not found: {path}",
   "test.csvが見つかりません: {path}", "找不到 test.csv：{path}")
_a("det.ds_source", "데이터 소스", "Data source", "データソース", "数据源")
_a("det.result_title", "탐지 결과", "Detection result", "検知結果", "检测结果")
_a("det.anomaly", "🔴 이상거래", "🔴 Anomaly", "🔴 異常取引", "🔴 异常交易")
_a("det.normal", "🟢 정상", "🟢 Normal", "🟢 正常", "🟢 正常")
_a("det.clf_bundle", "배포 번들 · {n}피처 · {shape}", "Deployment bundle · {n} features · {shape}",
   "配布バンドル・{n}特徴量・{shape}", "部署包 · {n}个特征 · {shape}")
_a("det.clf_encoded", "전처리 완료 행(RowClassifier)", "Pre-encoded row (RowClassifier)",
   "前処理済み行(RowClassifier)", "预处理行(RowClassifier)")
_a("det.clf_bridge", "브리지 모델 ({ck})", "Bridged model ({ck})", "ブリッジモデル({ck})",
   "桥接模型({ck})")
_a("det.clf_mlclf", "표준 분류기", "Standard classifier", "標準分類器", "标准分类器")
_a("det.classify_fail", "탐지 실패: {e}", "Detection failed: {e}", "検知失敗: {e}", "检测失败：{e}")
_a("det.saved", "💾 detections에 저장됨 (거래ID: {tid})", "💾 Saved to detections (txn: {tid})",
   "💾 detectionsに保存(取引ID: {tid})", "💾 已保存到 detections（交易ID：{tid}）")

# ── 프롬프트 · RAG 편집기 (세션5 이식) ──
_a("ai.prompt_editor_title", "🖊 AI 프롬프트 편집", "🖊 Edit AI prompts", "🖊 AIプロンプト編集",
   "🖊 编辑 AI 提示词")
_a("ai.prompt_editor_help",
   "저장하면 이 프롬프트가 기본값 대신 쓰입니다. 초기화하면 pipeline 기본값으로 되돌아갑니다.",
   "Saved prompts override the defaults. Reset restores the pipeline defaults.",
   "保存すると既定の代わりにこのプロンプトが使われます。リセットでpipeline既定値に戻ります。",
   "保存后将使用此提示词覆盖默认值。重置将恢复 pipeline 默认值。")
_a("ai.prompt_tab_analysis", "단건 분석", "Single analysis", "単件分析", "单条分析")
_a("ai.prompt_tab_slack", "Slack", "Slack", "Slack", "Slack")
_a("ai.prompt_tab_email", "Email", "Email", "Email", "Email")
_a("ai.prompt_tab_batch", "배치", "Batch", "バッチ", "批量")
_a("ai.prompt_save", "저장", "Save", "保存", "保存")
_a("ai.prompt_reset", "초기화", "Reset", "リセット", "重置")
_a("ai.prompt_active", "✓ 사용자 정의 프롬프트 적용 중", "✓ Custom prompt active",
   "✓ カスタムプロンプト適用中", "✓ 已应用自定义提示词")
_a("ai.rag_editor_title", "📚 RAG 지식베이스 편집", "📚 Edit RAG knowledge base",
   "📚 RAGナレッジベース編集", "📚 编辑 RAG 知识库")
_a("ai.rag_editor_help",
   "AI 분석이 참고하는 문서입니다. 저장하면 다음 분석부터 자동 재인덱싱됩니다.",
   "Documents the AI analysis references. Saving triggers automatic re-indexing.",
   "AI分析が参照する文書です。保存すると次回分析から自動的に再インデックスされます。",
   "AI 分析所参考的文档。保存后将在下次分析时自动重新索引。")
_a("ai.rag_docs_path", "경로: {path} · {n}개 문서", "Path: {path} · {n} doc(s)",
   "パス: {path} ・ {n}件", "路径：{path} · {n} 个文档")
_a("ai.rag_create_samples", "샘플 문서 생성", "Create sample docs", "サンプル文書を作成", "创建示例文档")
_a("ai.rag_save", "저장", "Save", "保存", "保存")
_a("ai.rag_reindex", "재인덱싱", "Re-index", "再インデックス", "重新索引")
_a("ai.rag_delete", "삭제", "Delete", "削除", "删除")
_a("ai.rag_delete_confirm", "다시 누르면 {name} 삭제됩니다", "Press again to delete {name}",
   "もう一度押すと{name}が削除されます", "再次点击将删除 {name}")
_a("ai.rag_new_label", "새 문서 이름", "New document name", "新規文書名", "新文档名称")
_a("ai.rag_new_btn", "➕ 새 문서", "➕ New doc", "➕ 新規文書", "➕ 新建文档")
_a("ai.rag_saved", "저장됨", "Saved", "保存済み", "已保存")
_a("ai.rag_reindexed", "재인덱싱 예약됨", "Re-index scheduled", "再インデックス予約済み", "已安排重新索引")
_a("ai.rag_fail", "실패: {e}", "Failed: {e}", "失敗: {e}", "失败：{e}")

# ── 워처 ──
_a("live.title", "워처 상태", "Watcher Status", "ウォッチャー状態", "监视器状态")
_a("live.never", "워처를 아직 실행한 적이 없습니다",
   "The watcher has never been started", "ウォッチャーは未実行です", "监视器尚未运行")
_a("live.nodb", "DB 파일을 찾을 수 없습니다 — 워처와 다른 서버에서 실행 중일 수 있습니다",
   "DB file not found — you may be running on a different server than the watcher",
   "DBファイルが見つかりません — ウォッチャーと別サーバの可能性があります",
   "找不到数据库文件 — 可能与监视器不在同一服务器")
_a("live.autorefresh", "자동 새로고침", "Auto-refresh", "自動更新", "自动刷新")
_a("live.feed", "최근 탐지 피드", "Recent detections", "最近の検知", "最近检测")
_a("live.kpi_polls", "폴링", "Polls", "ポーリング", "轮询")
_a("live.kpi_rows", "처리 행", "Rows", "処理行", "处理行数")
_a("live.kpi_anom", "이상거래", "Anomalies", "異常取引", "异常交易")
_a("live.kpi_sent", "알림 발송", "Notified", "通知送信", "已通知")
_a("live.kpi_err", "오류", "Errors", "エラー", "错误")

# ── 트리아지 ──
_a("tri.title", "판정 대기 알림", "Alerts awaiting review", "判定待ちアラート", "待审告警")
_a("tri.empty", "판정할 알림이 없습니다. 워처가 새 이상거래를 탐지하면 여기에 쌓입니다.",
   "No alerts to review. New anomalies from the watcher will appear here.",
   "判定するアラートがありません。新しい異常取引がここに表示されます。",
   "暂无待审告警。监视器检测到新异常后会显示在这里。")
_a("tri.verdict", "판정", "Verdict", "判定", "判定")
_a("tri.tp", "✅ 정탐", "✅ True positive", "✅ 正検知", "✅ 真报")
_a("tri.fp", "🟡 오탐", "🟡 False positive", "🟡 False positive", "🟡 误报")
_a("tri.fn", "🔴 미탐", "🔴 Missed (FN)", "🔴 見逃し", "🔴 漏报")
_a("tri.unclear", "⏸ 보류", "⏸ Unclear", "⏸ 保留", "⏸ 待定")
_a("tri.reason", "오탐 사유", "FP reason", "誤検知理由", "误报原因")
_a("tri.memo", "메모", "Memo", "メモ", "备注")
_a("tri.reviewer", "검토자", "Reviewer", "検討者", "审核人")
_a("tri.save", "판정 저장", "Save verdict", "判定を保存", "保存判定")
_a("tri.detail", "거래 상세", "Transaction detail", "取引詳細", "交易明细")
_a("tri.masked_note", "개인정보는 마스킹되어 표시됩니다",
   "Personal data is shown masked", "個人情報はマスキング表示されます", "个人信息以脱敏形式显示")
_a("tri.recheck", "🔄 현재 모델로 재검증", "🔄 Re-check with current model",
   "🔄 現行モデルで再検証", "🔄 用当前模型复核")

# ── 트리아지 · i18n 1단계 (필터 · 일괄 판정 · 잠금) ──
#   ⚠ 정렬 옵션은 **코드값**(age/score)으로 다룬다. 예전엔 라디오가 돌려준
#     한글 라벨을 `if tri_sort == "대기순"` 으로 비교했는데, 그 상태로 번역하면
#     영어에서는 조건이 영원히 거짓이 되어 정렬이 조용히 점수순으로 굳는다.
_a("tri.only_new", "미판정만", "Unreviewed only", "未判定のみ", "仅未审核")
_a("tri.min_score", "최소 점수", "Min score", "最小スコア", "最低分数")
_a("tri.show_n", "표시 건수", "Rows shown", "表示件数", "显示条数")
_a("tri.show_n_help", "한 화면에 너무 많이 띄우면 판정 자체가 느려집니다",
   "Showing too many at once makes reviewing itself sluggish.",
   "一度に多く表示すると判定操作そのものが重くなります。",
   "一次显示过多会让审核操作变慢。")
_a("tri.sort", "정렬", "Sort", "並び替え", "排序")
_a("tri.sort_age", "대기순", "By wait time", "待ち時間順", "按等待时长")
_a("tri.sort_score", "점수순", "By score", "スコア順", "按分数")
_a("tri.sort_desc", "내림차순", "Descending", "降順", "降序")
_a("tri.sort_desc_help",
   "대기순 내림차순 = 오래 기다린 순 · 점수순 내림차순 = 위험한 순 (각각 기본값)",
   "Wait time descending = longest waiting first · Score descending = riskiest first (both are the defaults)",
   "待ち時間の降順 = 長く待った順 · スコアの降順 = リスクの高い順（いずれも既定）",
   "等待时长降序 = 等待最久优先 · 分数降序 = 风险最高优先（均为默认）")
_a("tri.jumped", "🔔 경보에서 이동: **{tid}**", "🔔 Jumped from alert: **{tid}**",
   "🔔 アラートから移動: **{tid}**", "🔔 从告警跳转: **{tid}**")
_a("tri.kpi_pending", "대기", "Waiting", "待機", "等待")
_a("tri.kpi_over", "SLA {n}분 초과", "Over SLA {n}m", "SLA {n}分超過", "超出 SLA {n}分")
_a("tri.kpi_warn", "임박", "Due soon", "期限間近", "即将超时")
_a("tri.kpi_oldest", "최장 대기", "Longest wait", "最長待機", "最长等待")
_a("tri.need_check", "확인 필요", "Needs attention", "要確認", "需要确认")
_a("tri.heartbeat", "🔒 검토 중 {n}건 · {ts} 갱신",
   "🔒 {n} locked by you · refreshed {ts}",
   "🔒 検討中 {n}件 · {ts} 更新", "🔒 审核中 {n}件 · {ts} 已刷新")
_a("tri.drafts", "💾 임시저장 {n}건 — 새로고침해도 남아 있습니다",
   "💾 {n} drafts saved — they survive a refresh",
   "💾 一時保存 {n}件 — 再読み込みしても残ります",
   "💾 已暂存 {n}件 — 刷新后仍保留")
_a("tri.title_n", "{title} — {n}건", "{title} — {n}", "{title} — {n}件", "{title} — {n}件")
_a("tri.sel_all", "☑️ 모두 선택", "☑️ Select all", "☑️ すべて選択", "☑️ 全选")
_a("tri.sel_none", "⬜ 선택 해제", "⬜ Clear selection", "⬜ 選択解除", "⬜ 取消选择")
_a("tri.sel_over", "🔴 SLA 초과만", "🔴 Over-SLA only", "🔴 SLA超過のみ", "🔴 仅超时")
_a("tri.sel_over_help", "SLA를 넘긴 건만 선택합니다", "Selects only alerts past the SLA",
   "SLAを超えた案件のみ選択します", "仅选择已超出 SLA 的告警")
_a("tri.sel_count", "선택 **{n}건** / 표시 {m}건", "Selected **{n}** / shown {m}",
   "選択 **{n}件** / 表示 {m}件", "已选 **{n}件** / 显示 {m}件")
_a("tri.sel_hint", "  — 아래에서 판정을 고르고 일괄 저장",
   "  — pick a verdict below and save them together",
   "  — 下で判定を選び、まとめて保存",
   "  — 在下方选择判定并批量保存")
_a("tri.bulk_reason_hint", "오탐을 고르면 사유를 함께 선택합니다",
   "Choosing false positive also asks for a reason",
   "誤検知を選ぶと理由も選択します", "选择误报时需一并选择原因")
_a("tri.bulk_memo", "일괄 메모 (선택)", "Bulk memo (optional)",
   "一括メモ（任意）", "批量备注（可选）")
_a("tri.bulk_memo_ph", "예) 내부 테스트 계정 일괄 정리",
   "e.g. bulk cleanup of internal test accounts",
   "例）内部テスト口座の一括整理", "例）批量清理内部测试账户")
_a("tri.bulk_blocked", "🔒 {n}건은 다른 담당자가 검토 중이라 제외됩니다 ({ids}…)",
   "🔒 {n} excluded — another reviewer is working on them ({ids}…)",
   "🔒 {n}件は他の担当者が検討中のため除外されます（{ids}…）",
   "🔒 {n}件因其他审核人正在处理而被排除（{ids}…）")
_a("tri.bulk_save", "💾 선택한 {n}건 일괄 판정", "💾 Judge {n} selected together",
   "💾 選択した{n}件を一括判定", "💾 批量判定所选 {n}件")
_a("tri.bulk_done", "✅ {n}건 일괄 판정 완료", "✅ {n} judged in bulk",
   "✅ {n}件を一括判定しました", "✅ 已批量判定 {n}件")
_a("tri.cb_label", "선택", "Select", "選択", "选择")
_a("tri.cb_help", "{tid} 일괄 판정 대상에 포함", "Include {tid} in the bulk verdict",
   "{tid} を一括判定の対象に含める", "将 {tid} 纳入批量判定")
_a("tri.locked",
   "🔒 **{who}** 님이 {min}분 전부터 검토 중입니다. 같은 알림을 둘이 판정하면 "
   "서로 다른 결론이 두 줄 쌓입니다 — 먼저 확인하세요.",
   "🔒 **{who}** has been reviewing this for {min} min. If two people judge the same "
   "alert you end up with two conflicting rows — check with them first.",
   "🔒 **{who}** さんが{min}分前から検討中です。同じアラートを二人で判定すると "
   "異なる結論が二行残ります — 先に確認してください。",
   "🔒 **{who}** 从 {min} 分钟前开始审核。两人判定同一告警会留下两条互相矛盾的记录 — 请先确认。")
_a("tri.steal", "🔓 잠금 무시하고 내가 검토", "🔓 Override lock and take over",
   "🔓 ロックを無視して自分が検討", "🔓 忽略锁定并接手")
_a("tri.recheck_now", "현재 모델: {ft} · {score}", "Current model: {ft} · {score}",
   "現行モデル: {ft} · {score}", "当前模型: {ft} · {score}")
_a("tri.draft_saved", "💾 임시저장됨 · {age} 전", "💾 Draft saved · {age} ago",
   "💾 一時保存済み · {age}前", "💾 已暂存 · {age}前")
_a("tri.unlock", "🔓 검토 취소(잠금 해제)", "🔓 Cancel review (release lock)",
   "🔓 検討を取り消す（ロック解除）", "🔓 取消审核（释放锁定）")

# ── 실시간 감시 · i18n 2단계 ──
_a("live.sec", "초", "sec", "秒", "秒")
_a("live.from_push",
   "☁ 로컬 DB 가 아니라 워처가 내보낸 스냅샷을 읽었습니다 (`{path}`) — "
   "이 화면은 워처와 다른 서버에서 돌고 있습니다",
   "☁ Read from the watcher's exported snapshot rather than the local DB (`{path}`) — "
   "this console is running on a different host than the watcher",
   "☁ ローカルDBではなくウォッチャーが出力したスナップショットを読みました（`{path}`）— "
   "この画面はウォッチャーとは別のサーバーで動いています",
   "☁ 读取的是监视器导出的快照而非本地数据库（`{path}`）— 此界面运行在与监视器不同的服务器上")
_a("live.need_check", "확인 필요", "Needs attention", "要確認", "需要确认")
_a("live.no_fragment",
   "⚠️ 이 Streamlit 버전은 st.fragment 를 지원하지 않아 자동 갱신이 비활성화됩니다 (1.33+ 필요).",
   "⚠️ This Streamlit version lacks st.fragment, so auto-refresh is disabled (1.33+ required).",
   "⚠️ このStreamlitバージョンは st.fragment に未対応のため自動更新は無効です（1.33以上が必要）。",
   "⚠️ 当前 Streamlit 版本不支持 st.fragment，自动刷新已禁用（需要 1.33 以上）。")

# ── 경보 패널 ──
_a("alarm.on", "🟢 켜짐", "🟢 On", "🟢 オン", "🟢 已开启")
_a("alarm.off", "⚫ 꺼짐", "⚫ Off", "⚫ オフ", "⚫ 已关闭")
_a("alarm.panel_title", "🚨 이상거래 경보 — {state} ({tier})",
   "🚨 Fraud alarm — {state} ({tier})", "🚨 不正取引アラート — {state}（{tier}）",
   "🚨 异常交易告警 — {state}（{tier}）")
_a("alarm.tier_basis",
   "등급 기준: 검토 **{thr}↑** · 확정 **{thc}↑** — 워처 설정(`watcher_config.json`)을 "
   "그대로 따릅니다. 바꾸려면 '⚙ 임계값 튜닝' 탭에서 적용하세요.",
   "Tier boundaries: review **{thr}+** · confirmed **{thc}+** — taken straight from the "
   "watcher config (`watcher_config.json`). Change them on the '⚙ Threshold' tab.",
   "等級基準: 検討 **{thr}以上** · 確定 **{thc}以上** — ウォッチャー設定"
   "（`watcher_config.json`）に従います。変更は「⚙ 閾値調整」タブで。",
   "等级标准: 待审 **{thr}以上** · 确认 **{thc}以上** — 直接沿用监视器配置"
   "（`watcher_config.json`）。如需修改请在「⚙ 阈值调优」标签页操作。")
_a("alarm.fc_expected", "예상 알람", "Expected alarms", "想定アラート", "预计告警")
_a("alarm.fc_fp", "오탐률", "FP rate", "誤検知率", "误报率")
_a("alarm.fc_wasted", "헛 알람", "Wasted alarms", "無駄アラート", "无效告警")
_a("alarm.per_day", "{n}회/일", "{n}/day", "{n}回/日", "{n}次/日")
_a("alarm.raise_tier", "줄이려면 등급↑", "Raise tier to reduce", "減らすには等級↑",
   "如需减少请提高等级")
_a("alarm.noisy",
   "하루 {n}회가 거짓 경보로 예상됩니다. 등급을 '확정만'으로 올리거나 임계값 탭에서 "
   "th_confirm 을 조정하세요. — 소음이 이 수준이면 담당자가 알람을 꺼버립니다.",
   "About {n} false alarms a day are expected. Raise the tier to 'confirmed only' or tune "
   "th_confirm on the threshold tab — at this noise level operators simply switch the alarm off.",
   "1日あたり約{n}回の誤アラートが見込まれます。等級を「確定のみ」に上げるか、閾値タブで "
   "th_confirm を調整してください — この騒音レベルでは担当者はアラームを切ってしまいます。",
   "预计每天约 {n} 次误报。请将等级提高为「仅确认」或在阈值标签页调整 th_confirm — "
   "噪音到这个程度，值班人员会直接关掉告警。")
_a("alarm.state_line", "**경보 {state}**", "**Alarm {state}**", "**アラート {state}**",
   "**告警 {state}**")
_a("alarm.master_note", "켜기/끄기는 사이드바 '🛡 관제 설정'에서",
   "Turn it on/off in the sidebar under '🛡 Ops settings'",
   "オン/オフはサイドバーの「🛡 管制設定」で", "开关请在侧边栏「🛡 管制设置」中操作")
_a("alarm.sound", "🔊 사운드", "🔊 Sound", "🔊 サウンド", "🔊 声音")
_a("alarm.desktop", "🖥 데스크톱 알림", "🖥 Desktop notification", "🖥 デスクトップ通知",
   "🖥 桌面通知")
_a("alarm.popup", "🛰 플로팅 카드", "🛰 Floating card", "🛰 フローティングカード",
   "🛰 浮动卡片")
_a("alarm.popup_help",
   "우상단에 레이더 경보 카드를 띄웁니다. 카드를 클릭하면 탐지 로그로, ✕ 로 닫습니다",
   "Shows a radar alert card at the top right. Click it to open the detection log, ✕ to dismiss.",
   "右上にレーダー警報カードを表示します。カードをクリックすると検知ログへ、✕ で閉じます",
   "在右上角显示雷达告警卡片。点击卡片进入检测日志，✕ 关闭")
_a("alarm.banner", "📋 상단 배너(폴백)", "📋 Top banner (fallback)",
   "📋 上部バナー（フォールバック）", "📋 顶部横幅（后备）")
_a("alarm.banner_help",
   "플로팅 카드가 안 보이는 환경용 대안입니다. 둘 다 켜면 같은 경보가 두 번 보입니다",
   "A fallback for environments where the floating card is blocked. "
   "With both on you see the same alert twice.",
   "フローティングカードが表示されない環境向けの代替です。両方オンにすると同じ警報が二重に見えます",
   "适用于浮动卡片被拦截的环境。两者同时开启会看到同一告警两次")
_a("alarm.tier_pick", "울릴 등급", "Alert at tier", "鳴らす等級", "触发等级")
_a("alarm.volume", "음량", "Volume", "音量", "音量")
_a("alarm.beeps", "삐- 반복 횟수", "Beep repeats", "ビープ反復回数", "提示音重复次数")
_a("alarm.beeps_help",
   "경보 1건당 소리를 몇 번 반복할지. 관제실에서 3회는 짧고 10회는 고문입니다 — "
   "소음 허용치에 맞춰 정하세요",
   "How many times to repeat the sound per alert. In a control room 3 is brief and 10 is "
   "torture — match it to your noise tolerance.",
   "1件あたり音を何回繰り返すか。管制室では3回は短く、10回は拷問です — 騒音許容度に合わせて。",
   "每条告警重复播放几次。在监控室里 3 次偏短、10 次是折磨 — 请按噪音容忍度设定。")
_a("alarm.dedup", "같은 거래 재알람 억제(분)", "Re-alert suppression for same txn (min)",
   "同一取引の再アラート抑制（分）", "同一交易重复告警抑制（分钟）")
_a("alarm.quiet_from", "조용한 시간 시작", "Quiet hours from", "静音時間 開始", "静音时段 开始")
_a("alarm.quiet_to", "종료", "to", "終了", "结束")
_a("alarm.quiet_note",
   "시작=종료면 사용 안 함 · 예) 22~7 이면 밤 10시~아침 7시 무음",
   "Start = end disables it · e.g. 22–7 means silent from 10pm to 7am",
   "開始＝終了で無効 · 例）22〜7 なら22時〜翌7時は無音",
   "开始=结束即停用 · 例）22~7 表示晚上10点至早上7点静音")
_a("alarm.arm_header", "🔌 활성화 · 진단", "🔌 Enable · diagnose", "🔌 有効化・診断",
   "🔌 启用 · 诊断")
_a("alarm.arm_note",
   "브라우저는 사용자가 클릭하기 전엔 소리와 데스크톱 알림을 차단합니다. "
   "**탭을 새로 열 때마다** 아래 버튼을 한 번 눌러주세요 — 권한은 페이지 단위라 "
   "새로고침하면 초기화됩니다.",
   "Browsers block sound and desktop notifications until the user clicks. Press the button "
   "below once **every time you open a new tab** — the permission is per page and resets on refresh.",
   "ブラウザはユーザーがクリックするまで音とデスクトップ通知をブロックします。"
   "**タブを開くたびに**下のボタンを一度押してください — 権限はページ単位で、再読み込みで初期化されます。",
   "浏览器在用户点击前会拦截声音和桌面通知。**每次新开标签页**都请按一次下方按钮 — "
   "权限以页面为单位，刷新后会重置。")
_a("alarm.test_confirm", "🔴 확정 경보", "🔴 Confirmed alert", "🔴 確定アラート", "🔴 确认告警")
_a("alarm.test_review", "🟡 검토 경보", "🟡 Review alert", "🟡 検討アラート", "🟡 待审告警")
_a("alarm.test_none", "🔵 관찰 경보", "🔵 Watch alert", "🔵 観察アラート", "🔵 观察告警")
_a("alarm.arm_first",
   "🔊 소리는 '활성화' 버튼을 먼저 누른 뒤부터 납니다 "
   "(이번 클릭으로 방금 활성화됐으니 다음 경보부터 들립니다)",
   "🔊 Sound only plays after you press the 'enable' button "
   "(this click just enabled it, so you'll hear it from the next alert on)",
   "🔊 音は「有効化」ボタンを押した後から鳴ります"
   "（今のクリックで有効化されたので、次のアラートから聞こえます）",
   "🔊 声音需先按「启用」按钮才会播放（本次点击刚刚启用，从下一条告警开始可听到）")
_a("alarm.test_note",
   "테스트 경보는 등급 필터·조용한 시간을 무시하고 무조건 표시합니다. "
   "우상단 카드는 확정 45초 · 그 외 22초 뒤 자동으로 사라지며, ✕ 로 즉시 닫을 수 있습니다. "
   "카드를 클릭하면 탐지 로그로 이동합니다.",
   "Test alerts ignore the tier filter and quiet hours and always show. The top-right card "
   "disappears after 45s for confirmed alerts and 22s otherwise; ✕ closes it immediately. "
   "Clicking the card opens the detection log.",
   "テストアラートは等級フィルタと静音時間を無視して必ず表示します。右上のカードは確定は45秒・"
   "それ以外は22秒で自動的に消え、✕ で即座に閉じられます。カードをクリックすると検知ログへ移動します。",
   "测试告警会忽略等级过滤和静音时段，始终显示。右上角卡片在确认告警45秒、其他22秒后自动消失，"
   "✕ 可立即关闭。点击卡片将跳转到检测日志。")
_a("live.watcher_panel", "⚙ 워처 제어 · 설정 · 로그", "⚙ Watcher control · config · log",
   "⚙ ウォッチャー制御・設定・ログ", "⚙ 监视器控制 · 配置 · 日志")

# ── 교대 인수인계 · i18n 3단계 (화면 UI만) ──
#   ⚠ 인수인계서 **문서 본문**(ops_shift.handover_markdown)은 여기 없다.
#     그건 저장·다운로드되어 조직 밖으로 나가는 산출물이라, 화면 언어와
#     문서 언어를 같이 묶으면 "영어로 보다가 저장했더니 영문 인계서"가 된다.
#     문서 쪽 번역은 별도 결정 사항으로 남긴다.
_a("shift.no_module", "ops_shift 모듈 미탑재 — 교대 인수인계가 비활성화됩니다.",
   "ops_shift module not installed — shift handover is disabled.",
   "ops_shift モジュール未搭載 — シフト引継ぎは無効です。",
   "未安装 ops_shift 模块 — 交接班功能已禁用。")
_a("shift.prev_header", "📥 앞 근무자가 남긴 것", "📥 Left by the previous shift",
   "📥 前の担当者が残したもの", "📥 上一班次留下的内容")
_a("shift.prev_empty", "아직 저장된 인수인계가 없습니다", "No handovers saved yet",
   "保存された引継ぎはまだありません", "尚无已保存的交接记录")
_a("shift.prev_entry", "**{who}** · {age} 전", "**{who}** · {age} ago",
   "**{who}** · {age}前", "**{who}** · {age}前")
_a("shift.prev_more", "이전 인수인계 {n}건", "{n} earlier handovers",
   "以前の引継ぎ {n}件", "更早的交接 {n}条")
_a("shift.prev_snapshot", "당시 요약 보기", "View the summary from then",
   "当時のサマリーを見る", "查看当时的摘要")
_a("shift.summary_header", "📊 최근 {h}시간 요약", "📊 Last {h} hours",
   "📊 直近{h}時間のサマリー", "📊 最近 {h} 小时汇总")
_a("shift.recalc", "🔄 새로 계산", "🔄 Recalculate", "🔄 再計算", "🔄 重新计算")
_a("shift.arrived", "유입 알림", "Alerts arrived", "流入アラート", "新增告警")
_a("shift.judged", "판정 완료", "Judged", "判定完了", "已判定")
_a("shift.left", "미처리 잔여", "Left unhandled", "未処理の残り", "未处理剩余")
_a("shift.sla_over_delta", "SLA 초과 {n}", "Over SLA {n}", "SLA超過 {n}", "超时 {n}")
_a("shift.fp_rate_note", "오탐률 {rate}% — 분모는 정탐+오탐입니다(보류·미탐 제외)",
   "FP rate {rate}% — denominator is true+false positives (excludes unclear and missed)",
   "誤検知率 {rate}% — 分母は正検知+誤検知です（保留・見逃しは除外）",
   "误报率 {rate}% — 分母为真报+误报（不含待定与漏报）")
_a("shift.by_reviewer", "판정자별", "By reviewer", "判定者別", "按审核人")
_a("shift.col_reviewer", "담당자", "Reviewer", "担当者", "审核人")
_a("shift.col_tp", "정탐", "TP", "正検知", "真报")
_a("shift.col_fp", "오탐", "FP", "誤検知", "误报")
_a("shift.col_fn", "미탐", "FN", "見逃し", "漏报")
_a("shift.col_unclear", "보류", "Unclear", "保留", "待定")
_a("shift.col_total", "합계", "Total", "合計", "合计")
_a("shift.pending_header", "넘기는 미처리 — 오래 기다린 순 (상위 15)",
   "Handing over — longest waiting first (top 15)",
   "引き継ぐ未処理 — 長く待った順（上位15）",
   "移交的未处理 — 等待最久优先（前15条）")
_a("shift.col_wait", "대기", "Wait", "待機", "等待")
_a("shift.col_txn", "거래 ID", "Txn ID", "取引ID", "交易ID")
_a("shift.col_type", "유형", "Type", "種別", "类型")
_a("shift.col_score", "점수", "Score", "スコア", "分数")
_a("shift.col_time", "시각", "Time", "時刻", "时刻")
_a("shift.urg_over", "🔴 초과", "🔴 Over", "🔴 超過", "🔴 超时")
_a("shift.urg_warn", "🟡 임박", "🟡 Due soon", "🟡 間近", "🟡 临近")
_a("shift.pending_none", "미처리 없음 — 큐를 비우고 넘깁니다 ✅",
   "Nothing left — handing over an empty queue ✅",
   "未処理なし — キューを空にして引き継ぎます ✅",
   "无未处理 — 清空队列后移交 ✅")
_a("shift.write_header", "📤 인수인계 작성", "📤 Write the handover",
   "📤 引継ぎの作成", "📤 撰写交接")
_a("shift.note_label", "다음 근무자에게 남길 메모", "Note for the next shift",
   "次の担当者へのメモ", "留给下一班次的备注")
_a("shift.note_ph",
   "예) 새벽 2시경 j형(대포통장) 급증 — 같은 수취계좌 3건 확인. "
   "TX_8821은 고객 확인 대기 중이라 보류로 뒀습니다.",
   "e.g. Spike of type-j (mule accounts) around 2am — 3 cases share the same payee account. "
   "TX_8821 left unclear pending customer confirmation.",
   "例）午前2時ごろ j型（借名口座）が急増 — 同一の受取口座3件を確認。"
   "TX_8821 は顧客確認待ちのため保留にしています。",
   "例）凌晨2点左右 j 型（傀儡账户）激增 — 确认有3笔为同一收款账户。"
   "TX_8821 因等待客户确认而暂列待定。")
_a("shift.save", "💾 인수인계 저장", "💾 Save handover", "💾 引継ぎを保存", "💾 保存交接")
_a("shift.download", "⬇ 인수인계서(.md)", "⬇ Handover doc (.md)",
   "⬇ 引継ぎ書(.md)", "⬇ 交接文档(.md)")
_a("shift.author_note", "작성자: **{who}** — 사이드바 '검토자'에서 바꿉니다",
   "Author: **{who}** — change it under 'Reviewer' in the sidebar",
   "作成者: **{who}** — サイドバーの「検討者」で変更します",
   "作者: **{who}** — 可在侧边栏「审核人」中修改")
_a("shift.preview", "📄 인수인계서 미리보기", "📄 Preview the handover doc",
   "📄 引継ぎ書のプレビュー", "📄 交接文档预览")

# ── i18n 4단계 : 발송 확인 · 오탐/FN · 튜닝 · 진단 ──
_a("common.cancel", "취소", "Cancel", "キャンセル", "取消")

# 발송 전 확인 카드
_a("send.confirm_title", "✋ {ch} 발송 확인", "✋ Confirm {ch} send",
   "✋ {ch} 送信の確認", "✋ 确认发送 {ch}")
_a("send.recipients",
   "**받는 곳** `{to}` &nbsp;·&nbsp; **거래** `{tid}` &nbsp;·&nbsp; **마스킹** `{mask}`",
   "**To** `{to}` &nbsp;·&nbsp; **Txn** `{tid}` &nbsp;·&nbsp; **Masking** `{mask}`",
   "**送信先** `{to}` &nbsp;·&nbsp; **取引** `{tid}` &nbsp;·&nbsp; **マスキング** `{mask}`",
   "**收件方** `{to}` &nbsp;·&nbsp; **交易** `{tid}` &nbsp;·&nbsp; **脱敏** `{mask}`")
_a("send.empty_body", "본문이 비어 있습니다 — 이대로 보내면 빈 메시지가 나갑니다.",
   "The body is empty — sending now delivers a blank message.",
   "本文が空です — このまま送ると空のメッセージが届きます。",
   "正文为空 — 现在发送将投递一条空消息。")
_a("send.preview_note", "본문 {n}자 · 앞부분 미리보기", "{n} characters · preview of the start",
   "本文 {n}文字 · 冒頭のプレビュー", "正文 {n} 字 · 开头预览")
_a("send.rich_note", "📎 첨부 {n}개 · {names} (강제 마스킹된 HTML 리포트)",
   "📎 {n} attachment(s) · {names} (HTML report, masking always applied)",
   "📎 添付 {n}件 · {names}（強制マスキング済み HTML レポート）",
   "📎 附件 {n} 个 · {names}（强制脱敏的 HTML 报告）")
_a("send.irreversible",
   "🚨 한 번 나가면 회수할 수 없습니다 — 수신처와 마스킹 레벨을 확인하세요.",
   "🚨 Once sent it cannot be recalled — check the recipient and masking level.",
   "🚨 一度送ると取り消せません — 送信先とマスキングレベルを確認してください。",
   "🚨 发出后无法撤回 — 请确认收件方与脱敏级别。")
_a("send.go", "📨 확인 — 지금 발송", "📨 Confirm — send now", "📨 確認 — 今すぐ送信",
   "📨 确认 — 立即发送")

# 오탐 분석 · 미탐 등록
_a("fp.dim_label", "기준", "Group by", "基準", "分组依据")
_a("fn.title", "🔴 미탐(FN) 등록 — 시스템이 놓친 사기 (최근 {d}일 {n}건)",
   "🔴 Log a missed fraud (FN) — last {d}d: {n}",
   "🔴 見逃し(FN)の登録 — システムが逃した不正（直近{d}日 {n}件）",
   "🔴 登记漏报(FN) — 系统漏掉的欺诈（最近{d}天 {n}件）")
_a("fn.desc",
   "고객 민원·사고 접수 등으로 **뒤늦게 확인된 사기**를 기록합니다. "
   "알림이 나가지 않은 거래라 트리아지 큐에는 뜨지 않습니다.",
   "Records fraud **confirmed after the fact** — via customer complaints or incident reports. "
   "No alert fired for these, so they never appear in the triage queue.",
   "顧客からの申告や事故受付などで**後から判明した不正**を記録します。"
   "アラートが出ていない取引のため、トリアージのキューには表示されません。",
   "记录通过客户投诉、事故受理等**事后确认的欺诈**。这些交易没有触发告警，因此不会出现在分诊队列中。")
_a("fn.txn_label", "거래 ID", "Transaction ID", "取引ID", "交易ID")
_a("fn.txn_ph", "예) TX_8821", "e.g. TX_8821", "例）TX_8821", "例）TX_8821")
_a("fn.lookup_fail", "조회 실패(등록은 가능): {e}", "Lookup failed (you can still log it): {e}",
   "照会に失敗しました（登録は可能）: {e}", "查询失败（仍可登记）: {e}")
_a("fn.found", "원장에서 찾았습니다 — 위험도 **{score}** · {ftype} · {ts}",
   "Found in the ledger — risk **{score}** · {ftype} · {ts}",
   "元帳で見つかりました — リスク **{score}** · {ftype} · {ts}",
   "已在流水中找到 — 风险 **{score}** · {ftype} · {ts}")
_a("fn.below_th",
   "이 거래는 **{score} < 현재 1차 임계값 {thr}** 이라 알림이 나가지 않았습니다. "
   "이런 건이 쌓이면 임계값을 내릴 근거가 됩니다.",
   "No alert fired because **{score} < the current review threshold {thr}**. "
   "As these accumulate they become the evidence for lowering it.",
   "この取引は **{score} < 現在の一次閾値 {thr}** のためアラートが出ませんでした。"
   "こうした案件が積み上がると閾値を下げる根拠になります。",
   "该交易因 **{score} < 当前一级阈值 {thr}** 而未触发告警。此类案例积累后即可作为下调阈值的依据。")
_a("fn.not_found",
   "원장에 없는 거래 ID입니다 — 점수 없이 '미탐'만 기록됩니다. "
   "(워처가 처리한 적 없는 거래일 수 있습니다)",
   "This transaction ID is not in the ledger — it will be logged as a miss without a score. "
   "(The watcher may never have processed it.)",
   "元帳にない取引IDです — スコアなしで「見逃し」のみ記録されます。"
   "（ウォッチャーが処理したことのない取引の可能性があります）",
   "流水中没有该交易ID — 将仅记录为「漏报」且无分数。（该交易可能从未被监视器处理过）")
_a("fn.memo_label", "경위 — 어떻게 알게 됐나", "How it came to light",
   "経緯 — どのように判明したか", "经过 — 如何发现的")
_a("fn.memo_ph",
   "예) 2026-08-09 고객센터 접수. 수취계좌 동일 건 3건 중 1건. 내부 조사 결과 대포통장 확인.",
   "e.g. Reported to the call centre on 2026-08-09. One of 3 cases sharing a payee account. "
   "Internal investigation confirmed a mule account.",
   "例）2026-08-09 コールセンター受付。同一受取口座3件のうち1件。内部調査で借名口座と確認。",
   "例）2026-08-09 客服受理。同一收款账户3笔中的1笔。内部调查确认为傀儡账户。")
_a("fn.memo_warn",
   "⚠️ 경위는 나중에 이 판정을 되짚는 **유일한 근거**입니다. "
   "비워두면 몇 달 뒤 왜 미탐으로 찍었는지 알 수 없습니다.",
   "⚠️ This note is the **only record** of why the call was made. "
   "Leave it blank and in a few months nobody will know why this was marked a miss.",
   "⚠️ 経緯は後からこの判定を辿る**唯一の根拠**です。"
   "空欄のままだと数か月後になぜ見逃しとしたのか分からなくなります。",
   "⚠️ 经过是日后回溯此判定的**唯一依据**。留空的话，几个月后将无从得知为何标记为漏报。")
_a("fn.save", "🔴 미탐으로 기록", "🔴 Log as missed (FN)", "🔴 見逃しとして記録",
   "🔴 记录为漏报")
_a("fn.scope_note",
   "ℹ️ 등록한 미탐은 판정 이력·교대 요약·재학습 라벨에 반영됩니다. "
   "다만 위 **기대비용 곡선은 아직 정탐/오탐만** 사용합니다 — 미탐을 곡선에 넣으려면 "
   "비용 모델을 함께 바꿔야 해서 분리해 두었습니다.",
   "ℹ️ Logged misses feed the verdict history, shift summary and retraining labels. "
   "The **expected-cost curve above still uses only true/false positives** — folding misses in "
   "would require changing the cost model too, so it is kept separate.",
   "ℹ️ 登録した見逃しは判定履歴・シフトサマリー・再学習ラベルに反映されます。"
   "ただし上の**期待コスト曲線はまだ正検知/誤検知のみ**を使います — "
   "見逃しを曲線に入れるにはコストモデルの変更も必要なため分離しています。",
   "ℹ️ 已登记的漏报会计入判定历史、交接汇总与再训练标签。但上方**期望成本曲线目前仅使用真报/误报** — "
   "将漏报纳入曲线还需同时修改成本模型，因此暂作分离。")
_a("fp.export", "📤 재학습용 라벨 내보내기", "📤 Export labels for retraining",
   "📤 再学習用ラベルの書き出し", "📤 导出再训练标签")
_a("fp.export_note",
   "판정 결과 + 당시 피처를 재학습 데이터로 뽑습니다. ⚠️ 워처가 저장한 피처는 "
   "마스킹본이라 파생 피처(금액·시각·채널)만 쓰세요.",
   "Exports verdicts plus the features as they were, for retraining. ⚠️ The features the watcher "
   "stored are masked — use only derived ones (amount, time, channel).",
   "判定結果と当時の特徴量を再学習データとして書き出します。⚠️ ウォッチャーが保存した特徴量は"
   "マスキング済みのため、派生特徴量（金額・時刻・チャネル）のみ使用してください。",
   "导出判定结果与当时的特征作为再训练数据。⚠️ 监视器保存的特征已脱敏，请仅使用派生特征（金额、时刻、渠道）。")
_a("fp.export_go", "생성", "Generate", "生成", "生成")
_a("fp.export_dl", "⬇ {n}건 다운로드", "⬇ Download {n}", "⬇ {n}件ダウンロード", "⬇ 下载 {n}件")

# 임계값 튜닝
_a("th.sample_n", "판정 표본 {n}건", "{n} judged samples", "判定サンプル {n}件", "判定样本 {n}件")
_a("th.apply_label", "적용할 1차(검토) 임계값", "Review threshold to apply",
   "適用する一次（検討）閾値", "要应用的一级（待审）阈值")
_a("th.apply_help",
   "대략적인 위치를 잡습니다. 정확한 값은 오른쪽 칸에 직접 입력하세요",
   "Sets the rough position — type the exact value in the box to the right",
   "おおよその位置を決めます。正確な値は右の欄に直接入力してください",
   "用于大致定位。精确数值请在右侧输入框直接填写")
_a("th.exact", "정확한 값", "Exact value", "正確な値", "精确值")
_a("th.exact_help",
   "슬라이더는 0.01 단위라 0.005 같은 값을 표현할 수 없습니다 — 여기에 직접 입력하세요. "
   "**적용되는 값은 이 칸입니다.**",
   "The slider steps by 0.01 and cannot express values like 0.005 — type it here. "
   "**This box is what gets applied.**",
   "スライダーは0.01刻みのため0.005のような値を表現できません — ここに直接入力してください。"
   "**適用されるのはこの欄の値です。**",
   "滑块以 0.01 为步长，无法表示 0.005 这类数值 — 请在此直接输入。**实际应用的是本输入框的值。**")
_a("th.apply_help_btn", "바로 저장하지 않습니다 — 확인 단계가 한 번 더 있습니다",
   "Does not save immediately — there is one more confirmation step",
   "すぐには保存しません — 確認ステップがもう一度あります",
   "不会立即保存 — 还有一次确认步骤")
_a("th.same_as_now", "현재 설정과 같습니다", "Same as the current setting", "現在の設定と同じです",
   "与当前设置相同")
_a("th.precise_note", "정밀값 `{v}` 적용 (슬라이더 표시는 반올림)",
   "Applying the precise value `{v}` (the slider display is rounded)",
   "精密値 `{v}` を適用（スライダー表示は四捨五入）",
   "将应用精确值 `{v}`（滑块显示为四舍五入）")
_a("th.confirm_title", "✋ 적용 전 확인", "✋ Confirm before applying", "✋ 適用前の確認",
   "✋ 应用前确认")
_a("th.confirm_change", "**1차(검토) 임계값** &nbsp; `{old}` &nbsp;→&nbsp; **`{new}`**",
   "**Review threshold** &nbsp; `{old}` &nbsp;→&nbsp; **`{new}`**",
   "**一次（検討）閾値** &nbsp; `{old}` &nbsp;→&nbsp; **`{new}`**",
   "**一级（待审）阈值** &nbsp; `{old}` &nbsp;→&nbsp; **`{new}`**")
_a("th.confirm_delta",
   "판정 표본 **{n}건** 기준의 상대 비교입니다(하루 알림 수가 아닙니다) · "
   "알림 {da:+d}건 · 놓친 사기 {dm:+d}건",
   "Relative comparison over **{n}** judged samples (not alerts per day) · "
   "alerts {da:+d} · missed fraud {dm:+d}",
   "判定サンプル **{n}件** に対する相対比較です（1日あたりのアラート数ではありません）· "
   "アラート {da:+d}件 · 見逃し {dm:+d}件",
   "基于 **{n}件** 判定样本的相对比较（不是每日告警数）· 告警 {da:+d}件 · 漏报 {dm:+d}件")
_a("th.below_valid",
   "🚨 **{v} 아래는 판정 데이터가 없는 구간**입니다. 임계값을 내리면 지금까지 알림이 "
   "나가지 않던 거래가 새로 올라오는데, 그게 몇 건이고 몇 %가 오탐일지 이 곡선은 알지 "
   "못합니다 (관측된 건 = 실제로 알림이 나간 건뿐). 위 표의 '변경 후'도 그만큼 "
   "과소평가된 값입니다.",
   "🚨 **Below {v} there is no judged data.** Lowering the threshold surfaces transactions that "
   "never alerted before — this curve cannot tell you how many that is, nor what share are false "
   "positives (we only ever observed alerts that actually fired). The 'after' row above is "
   "understated by exactly that unknown.",
   "🚨 **{v} 未満は判定データがない区間**です。閾値を下げると、これまでアラートが出ていなかった"
   "取引が新たに上がってきますが、それが何件でそのうち何%が誤検知かをこの曲線は知りません"
   "（観測できたのは実際にアラートが出た件のみ）。上の表の「変更後」もその分だけ過小評価です。",
   "🚨 **{v} 以下没有判定数据。** 下调阈值会带来此前从未告警的交易，而本曲线无法得知那是多少件、"
   "其中多少比例是误报（我们只观测到实际触发过告警的案例）。上表的「变更后」正因此被低估。")
_a("th.prev_rationale", "📌 **현재 값에 기록된 결정 근거**\n\n{note}\n\n— 최종 변경: {who} ({when})",
   "📌 **Recorded rationale for the current value**\n\n{note}\n\n— last changed by {who} ({when})",
   "📌 **現在の値に記録された決定根拠**\n\n{note}\n\n— 最終変更: {who}（{when}）",
   "📌 **当前取值已记录的决策依据**\n\n{note}\n\n— 最后变更: {who}（{when}）")
_a("th.hot_reload",
   "저장하면 워처가 **재시작 없이 즉시** 새 기준으로 경보를 냅니다. "
   "되돌리려면 같은 자리에서 이전 값을 다시 적용하세요.",
   "On save the watcher switches to the new threshold **immediately, without a restart**. "
   "To roll back, apply the old value from this same place.",
   "保存するとウォッチャーは**再起動なしで直ちに**新しい基準でアラートを出します。"
   "戻すには同じ場所で以前の値を再適用してください。",
   "保存后监视器将**无需重启、立即**按新阈值告警。如需回退，请在同一位置重新应用旧值。")
_a("th.confirm_go", "✅ 확인했습니다 — 적용", "✅ Confirmed — apply", "✅ 確認しました — 適用",
   "✅ 已确认 — 应用")
_a("th.col_kind", "구분", "Scenario", "区分", "场景")
_a("th.row_now", "현재", "Now", "現在", "当前")
_a("th.row_after", "변경 후", "After", "変更後", "变更后")
_a("th.col_threshold", "임계값", "Threshold", "閾値", "阈值")
_a("th.col_alerts", "알림", "Alerts", "アラート", "告警")
_a("th.col_missed", "놓친사기", "Missed fraud", "見逃し", "漏报")
_a("th.col_fp_rate", "오탐률(%)", "FP rate (%)", "誤検知率(%)", "误报率(%)")
_a("th.col_cost", "기대비용", "Expected cost", "期待コスト", "期望成本")
# 차트 라벨 — plotly 의 name/title/annotation 이라 st.* 스캐너에 안 잡힌다(주의)
_a("th.chart_title", "임계값별 기대비용", "Expected cost by threshold", "閾値別の期待コスト",
   "各阈值的期望成本")
_a("th.series_cost", "기대비용", "Expected cost", "期待コスト", "期望成本")
_a("th.series_unknown", "기대비용(추정불가 구간)", "Expected cost (no data)",
   "期待コスト（推定不可区間）", "期望成本（无数据区间）")
_a("th.vline_border", "데이터 경계", "Data boundary", "データ境界", "数据边界")
_a("th.vline_min", "최소비용 {v}", "Min cost {v}", "最小コスト {v}", "最低成本 {v}")
# ── 미탐 반영 곡선 ──
_a("th.fn_toggle", "🔴 등록된 미탐을 곡선에 반영", "🔴 Include logged misses (FN) in the curve",
   "🔴 登録した見逃し(FN)を曲線に反映", "🔴 将已登记的漏报(FN)纳入曲线")
_a("th.fn_toggle_help",
   "📉 오탐 분석 탭에서 등록한 미탐을 두 번째 곡선으로 겹쳐 그립니다. "
   "기존 곡선은 그대로 두고 나란히 비교합니다.",
   "Overlays a second curve using the misses you logged on the 📉 FP analysis tab. "
   "The original curve stays as it is, side by side.",
   "📉 誤検知分析タブで登録した見逃しを2本目の曲線として重ねて描きます。"
   "既存の曲線はそのまま残して並べて比較します。",
   "将你在 📉 误报分析标签页登记的漏报作为第二条曲线叠加绘制。原曲线保持不变，并排比较。")
_a("th.fn_none", "등록된 미탐이 없습니다 — 📉 오탐 분석 탭에서 먼저 기록하세요.",
   "No misses logged yet — record them on the 📉 FP analysis tab first.",
   "登録された見逃しがありません — まず📉誤検知分析タブで記録してください。",
   "尚未登记漏报 — 请先在 📉 误报分析标签页记录。")
_a("th.fn_series", "기대비용(미탐 반영)", "Expected cost (with misses)",
   "期待コスト（見逃し反映）", "期望成本（含漏报）")
_a("th.fn_vline", "미탐반영 최소 {v}", "Min with misses {v}", "見逃し反映の最小 {v}",
   "含漏报最低 {v}")
_a("th.fn_summary",
   "미탐 **{n}건** 반영 · 최소비용 지점 **{a} → {b}**",
   "**{n}** misses included · min-cost point **{a} → {b}**",
   "見逃し **{n}件** 反映 · 最小コスト地点 **{a} → {b}**",
   "已纳入 **{n}** 条漏报 · 最低成本点 **{a} → {b}**")
_a("th.fn_unscored", "⚠️ 미탐 {n}건은 원장에 점수가 없어 곡선에 반영되지 않았습니다.",
   "⚠️ {n} misses have no score in the ledger and are not on the curve.",
   "⚠️ 見逃し {n}件は元帳にスコアがなく曲線に反映されていません。",
   "⚠️ 有 {n} 条漏报在流水中没有分数，未能纳入曲线。")
_a("th.fn_howto",
   "**읽는 법** — 곡선의 *높이*가 올라간 것은 정상입니다. 기존 곡선이 아예 보지 못했던 "
   "실제 손실이 이제 계산에 들어왔기 때문입니다. 쓸모 있는 것은 **최소점의 위치**이고, "
   "그것이 왼쪽으로 갔다면 임계값을 내릴 근거입니다.\n\n"
   "🚨 다만 미탐 데이터는 임계값을 내렸을 때의 **이득만** 알려줍니다. 내려서 새로 올라올 "
   "**오탐이 몇 건일지는 여전히 관측된 적이 없습니다.** 이동한 거리를 그대로 믿지 말고 "
   "방향의 근거로만 쓰세요. 추천 슬라이더는 기존 곡선을 그대로 따릅니다.",
   "**How to read this** — the curve moving *up* is expected: real losses the original curve was "
   "blind to are now counted. What matters is **where the minimum sits**, and if it moved left "
   "that is your evidence for lowering the threshold.\n\n"
   "🚨 But logged misses only tell you the **upside** of lowering. How many **new false positives** "
   "a lower threshold would surface has still never been observed. Treat the shift as a direction, "
   "not a distance. The recommendation slider still follows the original curve.",
   "**読み方** — 曲線の*高さ*が上がるのは正常です。既存の曲線が見えていなかった実際の損失が"
   "計算に入ったためです。重要なのは**最小点の位置**で、左に動いたなら閾値を下げる根拠です。\n\n"
   "🚨 ただし見逃しデータは閾値を下げたときの**利得しか**教えません。下げて新たに上がってくる"
   "**誤検知が何件かは依然として未観測です。** 移動距離をそのまま信じず、方向の根拠としてのみ"
   "使ってください。推奨スライダーは既存の曲線に従います。",
   "**如何解读** — 曲线*高度*上升是正常的：原曲线完全看不到的真实损失现在被计入了。"
   "有价值的是**最低点的位置**，若它向左移动，那就是下调阈值的依据。\n\n"
   "🚨 但漏报数据只告诉你下调阈值的**收益**。下调后新出现的**误报有多少，仍然从未被观测过。**"
   "请把这个位移当作方向依据而非距离。推荐滑块仍然沿用原曲线。")

# 진단
_a("diag.conn_test", "🔌 연결 테스트", "🔌 Connection tests", "🔌 接続テスト", "🔌 连接测试")
_a("diag.conn_target", "대상 모델 `{model}` · 제공자 `{prov}` — 사이드바에서 바꿉니다",
   "Target model `{model}` · provider `{prov}` — change them in the sidebar",
   "対象モデル `{model}` · プロバイダ `{prov}` — サイドバーで変更します",
   "目标模型 `{model}` · 提供方 `{prov}` — 可在侧边栏修改")
_a("diag.no_dispatch", "ops_dispatch 모듈 미탑재 — 연결 테스트가 비활성화됩니다.",
   "ops_dispatch module not installed — connection tests are disabled.",
   "ops_dispatch モジュール未搭載 — 接続テストは無効です。",
   "未安装 ops_dispatch 模块 — 连接测试已禁用。")
_a("diag.no_dispatch_short", "ops_dispatch 모듈 미탑재", "ops_dispatch module not installed",
   "ops_dispatch モジュール未搭載", "未安装 ops_dispatch 模块")
_a("diag.audit", "📤 발송 감사 로그", "📤 Send audit log", "📤 送信監査ログ", "📤 发送审计日志")
_a("diag.audit_desc",
   "자동·수동을 가리지 않고 Slack/Email **발송 시도 전부**를 기록합니다 — 성공뿐 아니라 "
   "실패·수신처 미설정·본문 생성 오류까지 남습니다. 탐지 결과 · 단건 분석 · 배치 리포트 "
   "6개 경로 모두 같은 함수를 지나므로 기록이 빠지는 경로는 없습니다.",
   "Logs **every Slack/Email send attempt**, automatic or manual — successes as well as failures, "
   "missing recipients and body-generation errors. All six paths (detection result, single "
   "analysis, batch report) go through the same function, so no path can skip the log.",
   "自動・手動を問わずSlack/Emailの**送信試行すべて**を記録します — 成功だけでなく失敗・"
   "宛先未設定・本文生成エラーも残ります。検知結果・単件分析・バッチレポートの6経路すべてが"
   "同じ関数を通るため、記録が抜ける経路はありません。",
   "记录 Slack/Email 的**全部发送尝试**，无论自动还是手动 — 成功、失败、未设置收件方、"
   "正文生成错误都会留存。检测结果、单件分析、批量报告共6条路径都经过同一函数，不存在漏记的路径。")
_a("diag.audit_n", "표시 건수", "Rows shown", "表示件数", "显示条数")
_a("diag.audit_persist",
   "📚 기록은 DB(`notify_audit`)에 **영구 보관**됩니다 — 새로고침·재시작해도 남습니다.",
   "📚 Records are kept **permanently** in the DB (`notify_audit`) — they survive refreshes and restarts.",
   "📚 記録はDB（`notify_audit`）に**永久保存**されます — 再読み込み・再起動しても残ります。",
   "📚 记录**永久保存**在数据库（`notify_audit`）中 — 刷新或重启后仍然保留。")
_a("diag.audit_purge", "🧹 감사 로그 정리 — 삭제는 되돌릴 수 없습니다",
   "🧹 Purge audit log — deletion cannot be undone",
   "🧹 監査ログの整理 — 削除は取り消せません", "🧹 清理审计日志 — 删除不可撤销")
_a("diag.tz_offset", "로컬 오프셋 {n}초", "Local offset {n}s", "ローカルオフセット {n}秒",
   "本地时差 {n}秒")
_a("diag.no_recheck", "ops_recheck 모듈 미탑재 — 재검증 기능이 비활성화됩니다.",
   "ops_recheck module not installed — re-checking is disabled.",
   "ops_recheck モジュール未搭載 — 再検証機能は無効です。",
   "未安装 ops_recheck 模块 — 复核功能已禁用。")
_a("diag.layout_header", "🧪 화면 배치 비교 (실험)", "🧪 Tab layout comparison (experimental)",
   "🧪 画面配置の比較（実験）", "🧪 界面布局对比（实验）")
_a("diag.layout_label", "탭 배치", "Tab layout", "タブ配置", "标签页布局")
_a("diag.layout_help", "저장되지 않습니다 — 새로고침하면 기본(확정)안으로 돌아옵니다",
   "Not saved — a refresh returns you to the default (approved) layout",
   "保存されません — 再読み込みすると既定（確定）案に戻ります",
   "不会保存 — 刷新后将恢复为默认（确定）方案")
_a("diag.layout_go", "↔ 이 배치로 바꿔 보기", "↔ Try this layout", "↔ この配置を試す",
   "↔ 试用此布局")
_a("diag.layout_experimental", "지금은 **비교용 배치**입니다 — 확정안이 아닙니다.",
   "You are on the **comparison layout** — this is not the approved one.",
   "現在は**比較用の配置**です — 確定案ではありません。",
   "当前为**对比用布局** — 并非确定方案。")
_a("diag.layout_reset", "↩ 기본(확정)안으로 되돌리기", "↩ Back to the default (approved) layout",
   "↩ 既定（確定）案に戻す", "↩ 恢复默认（确定）方案")
_a("diag.layout_default", "현재 기본(확정)안입니다.", "You are on the default (approved) layout.",
   "現在は既定（確定）案です。", "当前为默认（确定）方案。")
_a("diag.layout_ai_first", "🧠 AI 분석 우선 (기본 · 확정안)",
   "🧠 AI analysis first (default · approved)", "🧠 AI分析を優先（既定・確定案）",
   "🧠 AI 分析优先（默认 · 确定方案）")
_a("diag.layout_ops_first", "🚨 관제 흐름 우선 (비교용)", "🚨 Ops workflow first (for comparison)",
   "🚨 管制フロー優先（比較用）", "🚨 管制流程优先（用于对比）")
_a("diag.modules", "모듈 버전", "Module versions", "モジュールバージョン", "模块版本")
_a("diag.compact", "🗜 좁은 화면용 압축 탭 라벨", "🗜 Compact tab labels for narrow screens",
   "🗜 狭い画面向けの圧縮タブラベル", "🗜 适用于窄屏的紧凑标签")
_a("diag.compact_help",
   "탭 라벨을 짧게 줄입니다. 순서와 내용은 그대로이고, 첫 탭도 그대로입니다. "
   "1366px 노트북처럼 좁은 화면에서 마지막 탭이 잘릴 때 켜세요.",
   "Shortens the tab labels. Order and content are unchanged, and so is the first tab. "
   "Turn it on when the last tab gets cut off on a narrow screen such as a 1366px laptop.",
   "タブラベルを短くします。順序と内容はそのまま、最初のタブも変わりません。"
   "1366px のノートPCなど狭い画面で最後のタブが切れるときに有効にしてください。",
   "缩短标签页名称。顺序与内容不变，首个标签也不变。"
   "当在 1366px 笔记本等窄屏上最后一个标签被截断时开启。")
_a("diag.compact_now", "현재 탭바 폭 약 **{px}px** ({mode})",
   "Tab bar is about **{px}px** wide ({mode})",
   "現在のタブバー幅 約 **{px}px**（{mode}）", "当前标签栏宽度约 **{px}px**（{mode}）")
_a("diag.compact_on", "압축", "compact", "圧縮", "紧凑")
_a("diag.compact_off", "기본", "default", "既定", "默认")
_a("live.nodb_hint",
   "워처가 도는 PC에서 이 대시보드를 열거나, 왼쪽 사이드바 "
   "'🛡 관제 설정 → 📁 경로'에서 DB 경로를 바꿔주세요.",
   "Open this dashboard on the machine the watcher runs on, or change the DB path under "
   "'🛡 Ops settings → 📁 Paths' in the left sidebar.",
   "ウォッチャーが動いているPCでこのダッシュボードを開くか、左サイドバーの"
   "「🛡 管制設定 → 📁 パス」でDBパスを変更してください。",
   "请在运行监视器的机器上打开本仪表板，或在左侧边栏「🛡 管制设置 → 📁 路径」中修改数据库路径。")

# ── 탐지 로그 · i18n 5단계 ──
_a("log.no_astore", "analysis_store 모듈이 없습니다.", "The analysis_store module is missing.",
   "analysis_store モジュールがありません。", "缺少 analysis_store 模块。")
_a("log.search_ph", "거래 ID 일부 — 원장 전체에서 찾습니다",
   "Part of a transaction ID — searches the whole ledger",
   "取引IDの一部 — 元帳全体から検索します", "交易ID的一部分 — 在整个流水中查找")
_a("log.search_help",
   "표시 건수와 무관하게 원장 전체를 검색합니다. 비우면 최신순 목록으로 돌아갑니다.",
   "Searches the entire ledger regardless of the row limit. Clear it to return to the newest-first list.",
   "表示件数に関係なく元帳全体を検索します。空にすると新しい順の一覧に戻ります。",
   "无论显示条数如何，都会检索整个流水。清空后返回按最新排序的列表。")
_a("log.n", "건수", "Rows", "件数", "条数")
_a("log.anomaly_only", "이상거래만", "Anomalies only", "異常取引のみ", "仅异常交易")
_a("log.cache_ok",
   "📼 분석 캐시는 **정상 연결**돼 있습니다 — 아직 담긴 게 없을 뿐입니다.\n\n"
   "캐시는 워처가 **이상거래로 판정한 건**만 남깁니다. 부착 이후 처리한 행이 없거나"
   "(inbox 가 비어 있음), 처리한 행이 전부 정상이었다면 0건이 맞습니다.\n\n"
   "· 워처 처리 실적은 '🟢 실시간 감시' 탭의 KPI(처리 행·이상거래)에서 확인하세요\n"
   "· inbox 에 CSV 를 넣으면 다음 폴링부터 쌓이기 시작합니다",
   "📼 The analysis cache **is connected** — there is simply nothing in it yet.\n\n"
   "The cache only keeps rows the watcher **judged anomalous**. Zero is correct if no rows have "
   "been processed since it was attached (empty inbox) or if every processed row was normal.\n\n"
   "· Check the watcher's throughput on the '🟢 Live' tab KPIs (rows processed / anomalies)\n"
   "· Drop a CSV into the inbox and it starts filling from the next poll",
   "📼 分析キャッシュは**正常に接続**されています — まだ中身がないだけです。\n\n"
   "キャッシュはウォッチャーが**異常取引と判定した件**のみ残します。接続後に処理した行がない"
   "（inboxが空）か、処理した行がすべて正常だった場合は0件で正しいです。\n\n"
   "· ウォッチャーの処理実績は「🟢 リアルタイム監視」タブのKPI（処理行・異常取引）で確認してください\n"
   "· inbox にCSVを入れると次のポーリングから蓄積が始まります",
   "📼 分析缓存**连接正常** — 只是还没有内容。\n\n"
   "缓存仅保留监视器**判定为异常的交易**。若挂载后没有处理过任何行（inbox 为空），"
   "或处理过的行全部正常，那么 0 条是正确的。\n\n"
   "· 监视器的处理量请在「🟢 实时监控」标签页的 KPI（处理行数 / 异常交易）中查看\n"
   "· 将 CSV 放入 inbox，下一次轮询开始即会累积")
_a("log.hook_snippet",
   "```python\n# watcher.py — DetectService 생성 직후\n"
   "from pipeline import analysis_store as astore\nastore.attach(svc)\n```\n"
   "탐지 시점의 LLM 리포트는 그 프로세스 메모리에만 존재합니다. "
   "대시보드가 나중에 주워올 수 없어, 워처 쪽에서 캡처해야 합니다.",
   "```python\n# watcher.py — right after creating DetectService\n"
   "from pipeline import analysis_store as astore\nastore.attach(svc)\n```\n"
   "The LLM report exists only in that process's memory at detection time. The dashboard cannot "
   "pick it up afterwards, so it has to be captured on the watcher side.",
   "```python\n# watcher.py — DetectService 生成直後\n"
   "from pipeline import analysis_store as astore\nastore.attach(svc)\n```\n"
   "検知時点のLLMレポートはそのプロセスのメモリ内にのみ存在します。"
   "ダッシュボードが後から拾えないため、ウォッチャー側でキャプチャする必要があります。",
   "```python\n# watcher.py — 创建 DetectService 之后\n"
   "from pipeline import analysis_store as astore\nastore.attach(svc)\n```\n"
   "检测时刻的 LLM 报告仅存在于该进程内存中。仪表板事后无法获取，必须在监视器侧捕获。")
_a("log.cache_stat",
   "📼 {label}: {rows}건 / 거래 {txns}건 · {mb}MB (원본 {raw}MB · 압축률 {ratio}) · {a} ~ {b} UTC",
   "📼 {label}: {rows} rows / {txns} txns · {mb}MB (raw {raw}MB · ratio {ratio}) · {a} ~ {b} UTC",
   "📼 {label}: {rows}件 / 取引 {txns}件 · {mb}MB（元 {raw}MB · 圧縮率 {ratio}）· {a} ~ {b} UTC",
   "📼 {label}: {rows}条 / 交易 {txns}笔 · {mb}MB（原始 {raw}MB · 压缩率 {ratio}）· {a} ~ {b} UTC")
_a("log.focus_note", "🔔 알림에서 이동: **{tid}** — 아래에 이 거래를 열어 두었습니다",
   "🔔 Jumped from alert: **{tid}** — opened below",
   "🔔 アラートから移動: **{tid}** — 下に開いてあります",
   "🔔 从告警跳转: **{tid}** — 已在下方展开")
_a("log.focus_clear", "✕ 포커스 해제", "✕ Clear focus", "✕ フォーカス解除", "✕ 取消聚焦")
_a("log.search_result", "🔎 `{q}` — 원장 **전체**에서 검색해 최신 {n}건 (표시 상한 {cap})",
   "🔎 `{q}` — searched the **whole** ledger, newest {n} (display cap {cap})",
   "🔎 `{q}` — 元帳**全体**を検索し最新 {n}件（表示上限 {cap}）",
   "🔎 `{q}` — 检索**整个**流水，最新 {n}条（显示上限 {cap}）")
_a("log.focus_missing",
   "`{tid}` 를 최근 500건에서 찾지 못했습니다 — 오래된 거래이거나 원장에 없는 건일 수 있습니다.",
   "`{tid}` was not among the most recent 500 — it may be older, or not in the ledger at all.",
   "`{tid}` は直近500件で見つかりませんでした — 古い取引か、元帳にない可能性があります。",
   "`{tid}` 未出现在最近 500 条中 — 可能是较早的交易，或根本不在流水里。")
_a("log.col_txn", "거래 ID", "Txn ID", "取引ID", "交易ID")
_a("log.col_time", "시각", "Time", "時刻", "时刻")
_a("log.col_risk", "위험", "Risk", "リスク", "风险")
_a("log.col_type", "유형", "Type", "種別", "类型")
_a("log.col_verdict", "판정", "Verdict", "判定", "判定")
_a("log.col_source", "출처", "Source", "出所", "来源")
_a("log.m_risk", "위험도", "Risk score", "リスクスコア", "风险分数")
_a("log.m_tier", "등급", "Tier", "等級", "等级")
_a("log.unreviewed", "미판정", "Unreviewed", "未判定", "未审核")
_a("log.from_rawjson", "⚠️ 캐시가 없어 detections.raw_json 에서 읽었습니다 (마스킹본)",
   "⚠️ No cache — read from detections.raw_json instead (masked copy)",
   "⚠️ キャッシュがないため detections.raw_json から読みました（マスキング版）",
   "⚠️ 无缓存 — 改从 detections.raw_json 读取（脱敏副本）")
_a("log.col_field", "필드", "Field", "フィールド", "字段")
_a("log.col_value", "값", "Value", "値", "值")
_a("log.rag_docs", "📚 RAG 근거 문서", "📚 RAG source documents", "📚 RAG 根拠文書",
   "📚 RAG 依据文档")
_a("log.no_llm",
   "이 건은 LLM 분석 없이 처리됐습니다 (use_llm=False 이거나 서킷 브레이커 작동).",
   "This one was processed without LLM analysis (use_llm=False, or the circuit breaker tripped).",
   "この件はLLM分析なしで処理されました（use_llm=False またはサーキットブレーカー作動）。",
   "该条目在未经 LLM 分析的情况下处理（use_llm=False 或熔断器触发）。")
_a("log.proba_note", "위험점수 = 1 − P(정상). 상위 8개 클래스만 표시합니다.",
   "Risk score = 1 − P(normal). Only the top 8 classes are shown.",
   "リスクスコア = 1 − P(正常)。上位8クラスのみ表示します。",
   "风险分数 = 1 − P(正常)。仅显示前 8 个类别。")
_a("log.sent_summary",
   "- 등급: `{tier}`\n- Slack: {slack}\n- Email: {email}\n- 중복 억제: {dedup}",
   "- Tier: `{tier}`\n- Slack: {slack}\n- Email: {email}\n- Deduplicated: {dedup}",
   "- 等級: `{tier}`\n- Slack: {slack}\n- Email: {email}\n- 重複抑制: {dedup}",
   "- 等级: `{tier}`\n- Slack: {slack}\n- Email: {email}\n- 重复抑制: {dedup}")
_a("log.sent_yes", "✅ 발송", "✅ Sent", "✅ 送信", "✅ 已发送")
_a("log.dedup_yes", "🔕 예", "🔕 Yes", "🔕 はい", "🔕 是")
_a("log.dedup_no", "아니오", "No", "いいえ", "否")
_a("log.slack_body", "💬 실제 발송된 Slack 본문", "💬 The Slack body actually sent",
   "💬 実際に送信されたSlack本文", "💬 实际发送的 Slack 正文")
_a("log.email_body", "✉ 실제 발송된 Email 본문", "✉ The email body actually sent",
   "✉ 実際に送信されたEmail本文", "✉ 实际发送的邮件正文")
_a("log.col_item", "항목", "Item", "項目", "项目")
_a("log.env_captured", "탐지 시각(UTC)", "Detected at (UTC)", "検知時刻(UTC)", "检测时刻(UTC)")
_a("log.env_model", "모델", "Model", "モデル", "模型")
_a("log.env_th", "임계값 (검토/확정)", "Thresholds (review/confirm)", "閾値（検討/確定）",
   "阈值（待审/确认）")
_a("log.env_pii", "마스킹 레벨", "Masking level", "マスキングレベル", "脱敏级别")
_a("log.env_llm_used", "LLM 사용", "LLM used", "LLM使用", "使用 LLM")
_a("log.env_elapsed", "처리 시간", "Processing time", "処理時間", "处理时间")
_a("log.env_errors", "오류 수", "Error count", "エラー数", "错误数")
_a("log.env_source", "출처", "Source", "出所", "来源")
_a("log.yes", "예", "Yes", "はい", "是")
_a("log.no", "아니오", "No", "いいえ", "否")
_a("log.seconds", "{n}초", "{n}s", "{n}秒", "{n}秒")
_a("log.th_hotreload",
   "⚠️ 임계값은 핫 리로드되므로 **현재 설정과 다를 수 있습니다.** "
   "이 값이 이 판정의 실제 기준이었습니다.",
   "⚠️ Thresholds hot-reload, so these **may differ from the current settings.** "
   "These are the values this particular decision was actually made against.",
   "⚠️ 閾値はホットリロードされるため**現在の設定と異なる場合があります。**"
   "この値がこの判定の実際の基準でした。",
   "⚠️ 阈值会热重载，因此**可能与当前设置不同。** 这些才是本次判定实际使用的取值。")
_a("log.reanalyzed", "🔁 재분석 {n}회 — 최신 항목을 표시 중입니다",
   "🔁 Re-analyzed {n}× — showing the latest",
   "🔁 再分析 {n}回 — 最新の項目を表示中です", "🔁 已重新分析 {n} 次 — 显示最新一条")
_a("log.col_reviewed_at", "시각(UTC)", "Time (UTC)", "時刻(UTC)", "时刻(UTC)")
_a("log.col_reason", "사유", "Reason", "理由", "原因")
_a("log.col_reviewer", "검토자", "Reviewer", "検討者", "审核人")
_a("log.col_memo", "메모", "Memo", "メモ", "备注")
_a("log.col_score_then", "당시 점수", "Score then", "当時のスコア", "当时分数")
_a("log.no_history", "아직 판정 이력이 없습니다.", "No verdict history yet.",
   "まだ判定履歴がありません。", "尚无判定历史。")
_a("log.prune_note",
   "판정이 달린 거래의 캐시는 감사 자료이자 재학습 라벨의 출처라 나이와 무관하게 보존합니다.",
   "Caches for judged transactions are audit evidence and the source of retraining labels, "
   "so they are kept regardless of age.",
   "判定が付いた取引のキャッシュは監査資料であり再学習ラベルの出所でもあるため、"
   "古さに関わらず保存します。",
   "已判定交易的缓存既是审计凭据也是再训练标签的来源，因此无论多久都会保留。")
_a("log.prune_days", "보존 기간(일)", "Retention (days)", "保存期間（日）", "保留期限（天）")
_a("log.prune_keep", "판정된 건은 보존", "Keep judged ones", "判定済みは保存", "保留已判定的")
_a("log.prune_go", "정리 실행", "Run cleanup", "整理を実行", "执行清理")
# 오탐 탭 KPI — _kpi_row() 로 넘기는 라벨이라 st.* 스캐너에 안 잡힌다(주의)
_a("fp.kpi_alerts", "알림", "Alerts", "アラート", "告警")
_a("fp.kpi_judged", "판정", "Judged", "判定", "已判定")
_a("common.days", "{n}일", "{n}d", "{n}日", "{n}天")
# coverage() 가 돌려주는 '신뢰도' 값 — 데이터 계약은 그대로 두고 표시만 번역한다
_a("fp.conf_높음", "높음", "High", "高い", "高")
_a("fp.conf_보통", "보통", "Moderate", "中程度", "中")
_a("fp.conf_낮음", "낮음", "Low", "低い", "低")
_a("fp.conf_표본없음", "표본없음", "No samples", "サンプルなし", "无样本")
_a("common.hours", "{n}시간", "{n}h", "{n}時間", "{n}小时")

# ── AI 탭 · i18n 6단계 ──
_a("ai.provider_now", "⚙ 제공자 `{prov}` · RAG top_k {k} — 설정은 왼쪽 사이드바 '🤖 분석 설정'에서 바꿉니다",
   "⚙ Provider `{prov}` · RAG top_k {k} — change it under '🤖 Analysis settings' in the left sidebar",
   "⚙ プロバイダ `{prov}` · RAG top_k {k} — 設定は左サイドバーの「🤖 分析設定」で変更します",
   "⚙ 提供方 `{prov}` · RAG top_k {k} — 请在左侧边栏「🤖 分析设置」中修改")
_a("ai.editors_moved", "🖊 프롬프트 · 📚 RAG 편집은 왼쪽 사이드바 아래쪽으로 옮겼습니다",
   "🖊 Prompt and 📚 RAG editing moved to the bottom of the left sidebar",
   "🖊 プロンプト・📚 RAG の編集は左サイドバー下部に移動しました",
   "🖊 提示词与 📚 RAG 编辑已移至左侧边栏下方")
_a("ai.no_workbench",
   "`pipeline/detect_workbench.py` 가 없어 탐지 입력을 쓸 수 없습니다 — "
   "🩺 진단 탭의 모듈 버전을 확인하세요",
   "`pipeline/detect_workbench.py` is missing, so detection input is unavailable — "
   "check the module versions on the 🩺 Diagnostics tab",
   "`pipeline/detect_workbench.py` がないため検知入力を使えません — "
   "🩺 診断タブのモジュールバージョンを確認してください",
   "缺少 `pipeline/detect_workbench.py`，无法使用检测输入 — 请在 🩺 诊断标签页检查模块版本")
_a("det.detecting", "탐지 중…", "Detecting…", "検知中…", "检测中…")
_a("ai.alarm_skipped", "🔕 경보 등급 설정('{tier}')보다 낮아 알람은 생략했습니다",
   "🔕 Below the configured alarm tier ('{tier}'), so no alarm was raised",
   "🔕 アラート等級設定（'{tier}'）より低いためアラームは省略しました",
   "🔕 低于所配置的告警等级（'{tier}'），因此未触发告警")
_a("ai.auto_run", "🧠 탐지와 동시에 AI 분석 실행", "🧠 Run AI analysis together with detection",
   "🧠 検知と同時にAI分析を実行", "🧠 检测的同时运行 AI 分析")
_a("ai.auto_run_help",
   "켜면 이상거래 탐지 즉시 LLM 분석(원인·Slack·Email 초안)까지 한 번에 진행합니다. "
   "끄면 아래 버튼으로 따로 실행합니다.",
   "When on, an anomaly goes straight into LLM analysis (cause, Slack and email drafts) in one "
   "step. When off, run it separately with the button below.",
   "オンにすると異常取引の検知後すぐにLLM分析（原因・Slack・Emailの下書き）まで一度に進みます。"
   "オフの場合は下のボタンで別途実行します。",
   "开启后，检测到异常交易会立即一并进行 LLM 分析（原因、Slack、邮件草稿）。关闭时请用下方按钮单独运行。")
# 경보 세부 설정 — dashboard.py 사이드바도 이 표를 그대로 읽는다(_at()).
#   같은 스위치가 두 화면에서 다른 이름으로 불리면 "그거 어디 있어요"가 된다.
_a("sb.alarm_adv", "🔔 경보 세부 설정", "🔔 Alert settings",
   "🔔 アラート詳細設定", "🔔 告警详细设置")
_a("sb.alarm_shared_note",
   "이 설정은 **관제 대시보드(ops)와 함께 씁니다** — 한쪽에서 바꾸면 양쪽에 적용됩니다.",
   "These settings are **shared with the ops console** — changing one changes both.",
   "この設定は**監視コンソール(ops)と共有**します — 片方を変えると両方に適用されます。",
   "该设置**与监控台(ops)共享** — 在一侧修改会同时应用于两侧。")
_a("sb.alarm_desktop_help",
   "브라우저 알림 권한이 필요합니다. 창을 내려놔도 데스크톱에 뜹니다 — "
   "보고 있는 PC 에 뜨므로 팀에 공유해도 각자 자기 화면에서 받습니다.",
   "Requires browser notification permission. Appears on the desktop even when the window is "
   "minimised — it shows on the viewer's own PC, so shared links still notify each person.",
   "ブラウザの通知許可が必要です。ウィンドウを最小化しても表示されます — 見ている本人のPCに出ます。",
   "需要浏览器通知权限。即使窗口最小化也会弹出 — 显示在查看者本人的电脑上。")
_a("alarm.arm_short", "소리·윈도우 알림 켜기 (1회만)", "Enable sound & desktop alerts (once)",
   "音・デスクトップ通知を有効化（1回のみ）", "启用声音与桌面通知（仅一次）")
_a("alarm.arm_why",
   "브라우저는 이 버튼을 누르기 전까지 소리도 윈도우 알림도 막습니다 — 탭을 새로 열 때마다 한 번씩 필요합니다.",
   "Browsers block sound and desktop notifications until you click this — once per new tab.",
   "ブラウザはこのボタンを押すまで音もデスクトップ通知もブロックします — 新しいタブごとに1回必要です。",
   "在点击此按钮前，浏览器会阻止声音和桌面通知 — 每个新标签页需点击一次。")
_a("alarm.skip_off",
   "🔕 경보가 꺼져 있어 알리지 않았습니다 — 사이드바에서 켤 수 있습니다.",
   "🔕 Alerts are off, so nothing was sent — turn them on in the sidebar.",
   "🔕 アラートがオフのため通知しませんでした — サイドバーで有効にできます。",
   "🔕 告警已关闭，未发送通知 — 可在侧边栏开启。")
_a("alarm.skip_tier",
   "🔕 위험도 {r} — 현재 ‘{want}’ 설정이라 알리지 않았습니다 (확정 경계 {thc}). "
   "사이드바 ‘경보 세부 설정 → 울릴 등급’에서 낮출 수 있습니다.",
   "🔕 Risk {r} — not alerted because the level is set to ‘{want}’ (confirm boundary {thc}). "
   "Lower it under ‘Alert settings → Alert at’ in the sidebar.",
   "🔕 リスク {r} — 現在「{want}」設定のため通知しませんでした（確定境界 {thc}）。"
   "サイドバーの「アラート詳細設定 → 鳴らす等級」で下げられます。",
   "🔕 风险 {r} — 当前设置为「{want}」，故未告警（确定边界 {thc}）。"
   "可在侧边栏「告警详细设置 → 触发等级」中调低。")
_a("alarm.desktop_hint",
   "🖥 윈도우 알림이 안 뜬다면 사이드바의 ‘소리·윈도우 알림 켜기’를 한 번 누르세요 "
   "(브라우저 권한이 필요합니다).",
   "🖥 No desktop notification? Click ‘Enable sound & desktop alerts’ in the sidebar "
   "— the browser needs permission.",
   "🖥 デスクトップ通知が出ない場合はサイドバーの「音・デスクトップ通知を有効化」を押してください（ブラウザの許可が必要です）。",
   "🖥 没有收到桌面通知？请点击侧边栏的「启用声音与桌面通知」— 浏览器需要授权。")
_a("alarm.render_fail", "⚠ 경보 표시 실패 — {e}", "⚠ Could not show the alert — {e}",
   "⚠ アラート表示に失敗 — {e}", "⚠ 告警显示失败 — {e}")
_a("sb.alarm_polling_only",
   "‘조용한 시간’·‘중복 억제’는 워처가 무인으로 올리는 경보용이라 관제 대시보드에 있습니다 "
   "— 이 화면의 경보는 직접 실행한 탐지 결과입니다.",
   "‘Quiet hours’ and ‘repeat suppression’ live in the ops console: they govern unattended "
   "watcher alerts, while alerts here come from detections you ran yourself.",
   "「静かな時間」「重複抑制」は無人のウォッチャー警報用のため監視コンソールにあります "
   "— この画面の警報は自分で実行した検知の結果です。",
   "「安静时段」和「重复抑制」用于无人值守的监视器告警，位于监控台 — 此界面的告警来自你手动执行的检测。")
_a("alarm.shared_note",
   "이 설정은 분석 대시보드(dashboard)와 함께 씁니다 — `{path}` 한 벌을 읽습니다.",
   "Shared with the analysis dashboard — both read one `{path}`.",
   "分析ダッシュボードと共有します — `{path}` を1つ読みます。",
   "与分析仪表板共享 — 双方读取同一个 `{path}`。")
_a("ai.report_md", "📄 보고서 저장 (.md)", "📄 Save report (.md)",
   "📄 レポート保存 (.md)", "📄 保存报告 (.md)")
_a("ai.report_md_help",
   "판정·위험도·원인 분석·Slack/Email 초안을 한 파일로 내려받습니다. "
   "발송과 달리 밖으로 나가지 않습니다.",
   "Downloads the verdict, risk score, cause analysis and Slack/email drafts as one file. "
   "Unlike sending, nothing leaves your machine.",
   "判定・リスク・原因分析・Slack/Email下書きを1ファイルで保存します。送信と違い外部には出ません。",
   "将判定、风险分、原因分析和 Slack/邮件草稿保存为一个文件。与发送不同，内容不会外流。")
_a("ai.auto_run_off_note",
   "AI 분석은 탐지 결과 아래의 [🧠 AI 분석] 버튼으로 따로 실행합니다 — 탐지는 즉시 끝납니다.",
   "AI analysis runs separately via the [🧠 Run AI] button below the result — detection finishes immediately.",
   "AI分析は結果の下の[🧠 AI分析]ボタンで別途実行します — 検知はすぐ終わります。",
   "AI 分析请用结果下方的 [🧠 AI 分析] 按钮单独运行 — 检测会立即完成。")
_a("ai.redo_analysis", "🔁 원인 분석만 다시", "🔁 Redo the cause analysis only",
   "🔁 原因分析のみやり直す", "🔁 仅重做原因分析")
_a("ai.redo", "🔁 재생성", "🔁 Regenerate", "🔁 再生成", "🔁 重新生成")
_a("ai.redoing", "재분석 중…", "Re-analyzing…", "再分析中…", "重新分析中…")
_a("ai.regenerating", "재생성 중…", "Regenerating…", "再生成中…", "重新生成中…")
_a("ai.editable_note", "✏️ 고쳐서 보낼 수 있습니다 — 이 칸의 내용 그대로 발송됩니다",
   "✏️ You can edit before sending — exactly what is in this box goes out",
   "✏️ 修正して送信できます — この欄の内容がそのまま送信されます",
   "✏️ 可修改后发送 — 此框中的内容将原样发出")
_a("ai.as_is_note", "✏️ 이 칸의 내용 그대로 발송됩니다", "✏️ Exactly what is in this box goes out",
   "✏️ この欄の内容がそのまま送信されます", "✏️ 此框中的内容将原样发出")
_a("det.history_n", "🕘 탐지 이력 ({n}건)", "🕘 Detection history ({n})",
   "🕘 検知履歴（{n}件）", "🕘 检测历史（{n}条）")
_a("batch.src_label", "분석 대상", "Analyze", "分析対象", "分析对象")
_a("batch.src_queue", "🚨 알림 큐 (미판정)", "🚨 Alert queue (unreviewed)",
   "🚨 アラートキュー（未判定）", "🚨 告警队列（未审核）")
_a("batch.src_handoff", "📦 넘겨받은 추출분 ({n}건)", "📦 Handed-off extract ({n})",
   "📦 引き継いだ抽出分（{n}件）", "📦 已移交的抽取数据（{n}条）")
_a("batch.handoff_note",
   "'탐지 입력' 탭에서 넘어온 {n}건입니다 — 라이브 알림이 아니라 임의 추출 데이터라 "
   "**실제 모델로 재분류**합니다",
   "{n} rows handed over from the 'Detection input' tab — these are arbitrary extracts, not live "
   "alerts, so they are **re-classified with the real model**",
   "「検知入力」タブから引き継いだ{n}件です — ライブアラートではなく任意の抽出データのため"
   "**実モデルで再分類**します",
   "从「检测输入」标签页移交的 {n} 条 — 这是任意抽取的数据而非实时告警，因此会**用真实模型重新分类**")
_a("batch.failed", "배치 분석 실패: {e}", "Batch analysis failed: {e}",
   "バッチ分析に失敗しました: {e}", "批量分析失败: {e}")
_a("chat.stt_go", "🎤 → 텍스트 변환", "🎤 → Transcribe", "🎤 → テキスト変換", "🎤 → 转为文本")
_a("chat.stt_cloud", "클라우드 STT 허용(로컬 모델 없을 때)",
   "Allow cloud STT (when no local model is available)",
   "クラウドSTTを許可（ローカルモデルがない場合）", "允许云端语音识别（无本地模型时）")
_a("ai.subject_single", "[FDS] {ft}형 이상거래 탐지 (거래ID: {tid})",
   "[FDS] Type-{ft} fraud detected (txn {tid})",
   "[FDS] {ft}型 不正取引を検知（取引ID: {tid}）", "[FDS] 检测到 {ft} 型异常交易（交易ID: {tid}）")
_a("ai.subject_batch", "[FDS] 배치 분석 리포트 ({n}건)", "[FDS] Batch analysis report ({n})",
   "[FDS] バッチ分析レポート（{n}件）", "[FDS] 批量分析报告（{n}条）")

# ── 사이드바 · i18n 7단계 ──
_a("sb.brand_sub", "관제 · 오탐 판정 · 임계값 운영",
   "Monitoring · FP review · threshold ops", "管制・誤検知判定・閾値運用",
   "管制 · 误报判定 · 阈值运维")
_a("sb.identity", "👤 판정자", "👤 Reviewer", "👤 判定者", "👤 审核人")
_a("sb.dual", "📮 이중 임계값 발송", "📮 Dual-threshold dispatch", "📮 二段階閾値の送信",
   "📮 双阈值发送")
_a("sb.dual_help",
   "이 콘솔에서 내보내는 통보의 등급입니다(워처 경보 등급과 별개). 위험도 구간을 둘로 나눠 "
   "채널·메시지를 이원화합니다 — 검토 구간은 Slack만, 확정 구간은 Slack+Email 같은 식으로.",
   "The tier for notifications this console sends (separate from the watcher's alert tier). "
   "Splits the risk range in two and routes them differently — e.g. Slack only for the review "
   "band, Slack+Email for the confirmed band.",
   "このコンソールから送る通知の等級です（ウォッチャーのアラート等級とは別）。リスク区間を"
   "二つに分けてチャネル・メッセージを分岐します — 検討区間はSlackのみ、確定区間はSlack+Email のように。",
   "本控制台发出的通知等级（与监视器告警等级不同）。将风险区间一分为二并分流 — "
   "例如待审区间仅 Slack，确认区间 Slack+邮件。")
_a("sb.th_review", "① 검토 요청 임계값", "① Review-request threshold", "① 検討依頼の閾値",
   "① 待审请求阈值")
_a("sb.th_confirm", "② 확정 경보 임계값", "② Confirmed-alert threshold", "② 確定アラートの閾値",
   "② 确认告警阈值")
_a("sb.ds_folder", "데이터 폴더", "Data folder", "データフォルダ", "数据文件夹")
_a("sb.ds_folder_help", "이 폴더를 스캔해 csv/parquet 데이터셋을 찾습니다",
   "Scans this folder for csv/parquet datasets",
   "このフォルダをスキャンして csv/parquet データセットを探します",
   "扫描此文件夹以查找 csv/parquet 数据集")
_a("sb.ds_none", "`{path}` 에서 데이터셋을 찾지 못했습니다", "No datasets found in `{path}`",
   "`{path}` にデータセットが見つかりませんでした", "在 `{path}` 中未找到数据集")
_a("sb.dataset", "데이터셋", "Dataset", "データセット", "数据集")
_a("sb.rag_k_help", "LLM 분석에 함께 넣을 참고 문서 개수",
   "How many reference documents to include in the LLM analysis",
   "LLM分析に添える参考文書の数", "随 LLM 分析一并提供的参考文档数量")
_a("sb.llama_url", "llama.cpp URL (선택)", "llama.cpp URL (optional)",
   "llama.cpp URL（任意）", "llama.cpp URL（可选）")
_a("sb.pii_skip_local", "로컬 모델이면 PII 마스킹 생략", "Skip PII masking for local models",
   "ローカルモデルならPIIマスキングを省略", "本地模型时跳过 PII 脱敏")
_a("sb.pii_skip_local_help",
   "로컬 llama.cpp 로만 보낼 때는 외부로 나가지 않으므로 마스킹을 건너뛰어 분석 품질을 높입니다",
   "When everything stays on local llama.cpp nothing leaves the machine, so skipping masking "
   "improves analysis quality",
   "ローカルの llama.cpp にのみ送る場合は外部に出ないため、マスキングを省いて分析品質を上げます",
   "仅发送到本地 llama.cpp 时数据不会外传，跳过脱敏可提升分析质量")
_a("sb.env_note", "💡 여기 입력한 값이 .env 보다 우선합니다",
   "💡 Values entered here take precedence over .env",
   "💡 ここに入力した値が .env より優先されます", "💡 此处输入的值优先于 .env")
_a("sb.auto_slack", "🚀 Slack 자동 발송", "🚀 Auto-send to Slack", "🚀 Slack自動送信",
   "🚀 自动发送 Slack")
_a("sb.auto_slack_help", "이상거래 탐지 + AI 분석 완료 시 즉시 Slack으로 보냅니다",
   "Sends to Slack as soon as an anomaly is detected and analyzed",
   "異常取引の検知とAI分析が完了し次第、直ちにSlackへ送ります",
   "异常交易检测与 AI 分析完成后立即发送到 Slack")
_a("sb.auto_email", "🚀 Email 자동 발송", "🚀 Auto-send email", "🚀 Email自動送信",
   "🚀 自动发送邮件")
_a("sb.auto_email_help", "이중 임계값 모드에서는 '확정' 등급만 메일이 나갑니다",
   "In dual-threshold mode only the 'confirmed' tier is emailed",
   "二段階閾値モードでは「確定」等級のみメールが出ます", "双阈值模式下仅「确认」等级会发邮件")
_a("sb.tts_lang", "TTS 언어", "TTS language", "TTS言語", "语音合成语言")
_a("sb.reviewer_help",
   "판정 기록에 남는 이름입니다. 여러 명이 공유하는 화면이면 꼭 바꾸세요. "
   "잠금(누가 검토 중인지)과 임시저장이 이 이름으로 묶입니다.",
   "The name recorded on every verdict. Change it if several people share this screen — "
   "locks (who is reviewing what) and drafts are keyed to this name.",
   "判定記録に残る名前です。複数人で共有する画面なら必ず変更してください。"
   "ロック（誰が検討中か）と一時保存はこの名前で紐づきます。",
   "记录在每条判定上的名字。多人共用此界面时务必修改 — 锁定（谁在审核）与暂存都以此名字关联。")
_a("sb.sla", "SLA(분)", "SLA (min)", "SLA（分）", "SLA（分钟）")
_a("sb.sla_help",
   "알림이 뜬 뒤 이 시간 안에 판정한다는 약속. 초과분은 트리아지에서 🔴로 표시됩니다.",
   "The promise to judge an alert within this many minutes. Overruns show as 🔴 in triage.",
   "アラートが出てからこの時間内に判定するという約束。超過分はトリアージで🔴と表示されます。",
   "承诺在告警出现后的这段时间内完成判定。超时项在分诊中显示为 🔴。")
_a("sb.shift_h", "근무(시간)", "Shift (hours)", "勤務（時間）", "班次（小时）")
_a("sb.shift_h_help", "교대 인수인계가 요약할 구간", "The window the shift handover summarizes",
   "シフト引継ぎが要約する区間", "交接班汇总所覆盖的时间范围")
_a("sb.claim", "🔒 동시 판정 잠금", "🔒 Concurrent-review lock", "🔒 同時判定ロック",
   "🔒 并发审核锁定")
_a("sb.claim_help",
   "알림을 펼치면 '내가 본다'를 선언해 다른 담당자에게 표시합니다. {n}분간 응답이 없으면 자동 해제됩니다.",
   "Expanding an alert declares 'I'm on it' to other reviewers. Released automatically after "
   "{n} minutes of inactivity.",
   "アラートを開くと「自分が見る」と宣言し、他の担当者に表示されます。{n}分間応答がないと自動解除されます。",
   "展开告警即向其他审核人声明「我在处理」。{n} 分钟无响应后自动释放。")
_a("sb.pii_level", "마스킹 레벨", "Masking level", "マスキングレベル", "脱敏级别")
_a("sb.pii_level_help", "트리아지 화면에 거래 상세를 띄울 때 적용됩니다",
   "Applied when transaction details are shown on the triage screen",
   "トリアージ画面に取引詳細を表示する際に適用されます", "在分诊界面显示交易明细时生效")
_a("sb.alarm_master", "🔔 이상거래 경보", "🔔 Fraud alarm", "🔔 不正取引アラート", "🔔 异常交易告警")
_a("sb.alarm_master_help",
   "새 이상거래가 들어오면 소리·카드·데스크톱 알림으로 알립니다. "
   "세부 설정은 아래 버튼으로 '🟢 실시간 감시' 탭에서.",
   "Announces new anomalies with sound, a card and a desktop notification. "
   "Use the button below for detailed settings on the '🟢 Live' tab.",
   "新しい異常取引が入ると音・カード・デスクトップ通知で知らせます。"
   "詳細設定は下のボタンから「🟢 リアルタイム監視」タブで。",
   "有新的异常交易时以声音、卡片和桌面通知提醒。详细设置请用下方按钮前往「🟢 实时监控」标签页。")
_a("sb.alarm_tier_now", "울릴 등급: {tier}", "Alerts at: {tier}", "鳴らす等級: {tier}",
   "触发等级: {tier}")
_a("sb.alarm_open", "⚙ 경보 세부 설정", "⚙ Alarm details", "⚙ アラート詳細設定", "⚙ 告警详细设置")
_a("sb.alarm_open_help", "사운드·데스크톱 알림·조용한 시간·테스트 경보",
   "Sound, desktop notifications, quiet hours, test alerts",
   "サウンド・デスクトップ通知・静音時間・テストアラート", "声音、桌面通知、静音时段、测试告警")
_a("sb.paths", "📁 경로", "📁 Paths", "📁 パス", "📁 路径")
_a("sb.log_path", "워처 로그", "Watcher log", "ウォッチャーログ", "监视器日志")
_a("sb.model_dir", "모델 폴더", "Model folder", "モデルフォルダ", "模型文件夹")
_a("sb.inbox", "워처 감시 폴더", "Watcher inbox folder", "ウォッチャー監視フォルダ",
   "监视器监听文件夹")
_a("sb.inbox_help",
   "'📤 inbox 전송'이 CSV 를 저장할 폴더입니다. 워처가 실제로 감시하는 폴더와 같아야 "
   "자동 탐지로 이어집니다 (런처 기본값은 inbox).",
   "Where '📤 Send to inbox' saves the CSV. It must match the folder the watcher actually "
   "watches for automatic detection to follow (the launcher default is inbox).",
   "「📤 inbox送信」がCSVを保存するフォルダです。ウォッチャーが実際に監視するフォルダと"
   "同じでないと自動検知につながりません（ランチャーの既定は inbox）。",
   "「📤 发送到 inbox」保存 CSV 的文件夹。必须与监视器实际监听的文件夹一致，才能触发自动检测"
   "（启动器默认为 inbox）。")
_a("sb.chat", "🤖 AI 어시스턴트", "🤖 AI assistant", "🤖 AIアシスタント", "🤖 AI 助手")
_a("sb.chat_help", "어느 탭에 있든 여기서 바로 물어볼 수 있습니다 (단축키 없이 상시)",
   "Ask from here no matter which tab you are on (always available, no shortcut needed)",
   "どのタブにいてもここからすぐ質問できます（ショートカット不要で常時）",
   "无论在哪个标签页都能从这里直接提问（无需快捷键，始终可用）")
_a("sb.advanced", "⚙ 고급 설정", "⚙ Advanced settings", "⚙ 詳細設定", "⚙ 高级设置")
_a("sb.advanced_note", "LLM 제공자·API 키·알림 채널·표시 — 대개 처음 한 번만 정합니다",
   "LLM provider, API keys, notification channels, display — usually set once",
   "LLMプロバイダ・APIキー・通知チャネル・表示 — 通常は最初の一度だけ設定します",
   "LLM 提供方、API 密钥、通知渠道、显示 — 通常只需设置一次")
_a("sb.editors_note", "🖊 프롬프트 · 📚 RAG — LLM 이 무엇을 어떻게 쓸지",
   "🖊 Prompts · 📚 RAG — what the LLM writes and how",
   "🖊 プロンプト・📚 RAG — LLMが何をどう書くか", "🖊 提示词 · 📚 RAG — LLM 写什么、怎么写")
_a("sb.guide_again", "🎓 사용 안내 다시 보기", "🎓 Show the guide again", "🎓 使い方を再表示",
   "🎓 重新查看使用指南")
_a("sb.guide_again_help", "처음 실행 때 떴던 안내를 다시 엽니다",
   "Reopens the guide shown on first run", "初回実行時に表示された案内を再度開きます",
   "重新打开首次运行时显示的指南")
_a("sb.modules", "ℹ 모듈 버전", "ℹ Module versions", "ℹ モジュールバージョン", "ℹ 模块版本")
_a("alarm.tier_confirm_short", "확정만", "Confirmed only", "確定のみ", "仅确认")
_a("alarm.tier_review_short", "검토 이상", "Review and above", "検討以上", "待审及以上")
_a("alarm.tier_all_short", "전부", "All", "すべて", "全部")
_a("alarm.banner_header", "##### 🔔 새 경보 {n}건", "##### 🔔 {n} new alerts",
   "##### 🔔 新しいアラート {n}件", "##### 🔔 {n} 条新告警")
# 사이드바 섹션 제목·주석 (_section/_note 로 넘어가 스캐너에 안 잡힘 — 주의)
_a("sb.sec_dataset", "📂 데이터셋", "📂 Dataset", "📂 データセット", "📂 数据集")
_a("sb.sec_channel", "📨 알림 채널", "📨 Notification channels", "📨 通知チャネル", "📨 通知渠道")
_a("sb.sec_voice", "🗣 음성", "🗣 Voice", "🗣 音声", "🗣 语音")
_a("sb.sec_ops", "🛡 관제 설정", "🛡 Ops settings", "🛡 管制設定", "🛡 管制设置")
_a("sb.sec_appearance", "🎨 표시", "🎨 Appearance", "🎨 表示", "🎨 显示")
_a("sb.dual_inverted", "⚠ ②가 ①보다 낮습니다 — ②를 {v}로 간주합니다",
   "⚠ ② is lower than ① — treating ② as {v}",
   "⚠ ②が①より低いです — ②を {v} とみなします", "⚠ ② 低于 ① — 将 ② 视为 {v}")
_a("sb.dual_active", "이중 임계값 적용 중 — 검토 등급은 Slack만, 확정 등급은 Slack+Email",
   "Dual threshold active — review tier goes to Slack only, confirmed tier to Slack+Email",
   "二段階閾値が有効 — 検討等級はSlackのみ、確定等級はSlack+Email",
   "双阈值已启用 — 待审等级仅 Slack，确认等级为 Slack+邮件")
_a("sb.no_recipient", "⚠ 받는 사람이 비어 있어 메일이 나가지 않습니다",
   "⚠ No recipient set — email will not be sent",
   "⚠ 宛先が空のためメールは送信されません", "⚠ 未设置收件人，邮件不会发出")
_a("sb.no_name_hint", "이름 없음 — 아래에서 설정하세요", "No name — set it below",
   "名前未設定 — 下で設定してください", "未设置姓名 — 请在下方设置")

# ── detect_workbench · i18n 8단계 ──
#   detect_workbench 는 _tf(t, key) 로 이 표를 먼저 찾고, 없으면 자기 안의
#   한국어 폴백을 쓴다. 그래서 여기 키를 넣으면 ops 만 번역되고
#   dashboard.py(다른 t 를 쓴다)는 한국어 그대로 — 공유 모듈을 건드리되
#   저쪽 화면은 흔들지 않는 구조다.
_a("det.acct_hist", "🏦 계좌 이력 — 판정에 크게 영향을 줍니다",
   "🏦 Account history — strongly affects the verdict",
   "🏦 口座履歴 — 判定に大きく影響します", "🏦 账户历史 — 对判定影响很大")
_a("det.acct_hist_desc",
   "직접입력은 58개 피처 중 22개만 채웁니다. 나머지는 모델 번들의 기본값이 쓰이는데, "
   "**계좌 이력이 0(거래가 전혀 없던 계좌)** 으로 채워져 있어 무엇을 입력해도 정상으로 "
   "판정되곤 했습니다. 아래 기본값은 `train.csv` 의 **정상 계좌 중앙값** — 즉 '평범한 "
   "실제 계좌'입니다. 값을 0 으로 되돌리면 그 증상이 그대로 재현됩니다.",
   "Manual entry fills only 22 of the 58 features; the rest come from the model bundle's "
   "defaults, where **account history is 0 (an account that never transacted)** — which used to "
   "make everything you typed come out normal. The defaults below are the **median of normal "
   "accounts in `train.csv`**, i.e. an ordinary real account. Set them back to 0 and the old "
   "symptom reappears exactly.",
   "直接入力は58個の特徴量のうち22個しか埋めません。残りはモデルバンドルの既定値が使われますが、"
   "**口座履歴が0（取引が一度もない口座）**で埋まっているため、何を入力しても正常と判定されがちでした。"
   "下の既定値は `train.csv` の**正常口座の中央値** — つまり「普通の実在口座」です。"
   "0 に戻すとその症状がそのまま再現されます。",
   "手动录入只填充 58 个特征中的 22 个，其余使用模型包的默认值，而其中**账户历史为 0"
   "（从未发生过交易的账户）**，导致无论输入什么都容易被判为正常。下面的默认值是 `train.csv` 中"
   "**正常账户的中位数** — 即「普通的真实账户」。改回 0 就会原样重现该症状。")
_a("det.acct_reset", "↩ 계좌 이력 기본값으로", "↩ Reset account history",
   "↩ 口座履歴を既定値へ", "↩ 恢复账户历史默认值")
_a("det.acct_reset_help", "train.csv 정상 계좌 중앙값으로 되돌립니다",
   "Restores the median of normal accounts from train.csv",
   "train.csv の正常口座中央値に戻します", "恢复为 train.csv 中正常账户的中位数")
_a("det.model_line", "🧠 `{model}` · 임계값 {th} — 사이드바에서 바꿉니다",
   "🧠 `{model}` · threshold {th} — change it in the sidebar",
   "🧠 `{model}` · 閾値 {th} — サイドバーで変更します",
   "🧠 `{model}` · 阈值 {th} — 可在侧边栏修改")
_a("det.model_missing", "⚠ {path} 없음 — 모델 파일을 models/ 에 두세요",
   "⚠ {path} not found — put the model file in models/",
   "⚠ {path} がありません — モデルファイルを models/ に置いてください",
   "⚠ 未找到 {path} — 请将模型文件放入 models/")
_a("det.tab_dataset", "📂 선택 데이터셋", "📂 Selected dataset", "📂 選択データセット",
   "📂 所选数据集")
_a("det.save_csv", "💾 CSV 저장", "💾 Save CSV", "💾 CSV保存", "💾 保存 CSV")
_a("det.send_inbox", "📤 inbox 전송", "📤 Send to inbox", "📤 inbox へ送信", "📤 发送到 inbox")
_a("det.send_inbox_help",
   "워처 감시 폴더({dir})에 CSV로 저장합니다. 워처가 실행 중이면 몇 초 안에 자동 "
   "탐지·알림까지 진행됩니다. 폴더는 사이드바 '📁 경로'에서 바꿉니다.",
   "Saves a CSV into the watcher's inbox folder ({dir}). If the watcher is running, detection and "
   "alerting follow automatically within seconds. Change the folder under '📁 Paths' in the sidebar.",
   "ウォッチャー監視フォルダ（{dir}）にCSVとして保存します。ウォッチャーが実行中なら数秒以内に"
   "自動検知・通知まで進みます。フォルダはサイドバーの「📁 パス」で変更します。",
   "将 CSV 保存到监视器监听文件夹（{dir}）。若监视器正在运行，几秒内会自动完成检测与告警。"
   "文件夹可在侧边栏「📁 路径」中修改。")
_a("det.send_ok", "📤 전송 완료 — `{path}`", "📤 Sent — `{path}`", "📤 送信完了 — `{path}`",
   "📤 已发送 — `{path}`")
_a("det.send_newdir",
   "이 폴더는 방금 새로 만들어졌습니다 — 워처가 감시하는 폴더가 맞는지 확인하세요. "
   "다르면 탐지가 일어나지 않습니다.",
   "This folder was just created — make sure it is the one the watcher actually watches, "
   "otherwise nothing will be detected.",
   "このフォルダは今作成されました — ウォッチャーが監視しているフォルダか確認してください。"
   "異なると検知は起きません。",
   "该文件夹刚刚被创建 — 请确认它就是监视器实际监听的文件夹，否则不会触发检测。")
_a("det.send_fail", "저장 실패 — {e}", "Save failed — {e}", "保存に失敗 — {e}", "保存失败 — {e}")
_a("det.batch", "📦 일괄 분석 ({n}건)", "📦 Batch analyze ({n})", "📦 一括分析（{n}件）",
   "📦 批量分析（{n}条）")
_a("det.batch_help", "추출한 전체를 '📦 배치 분석' 탭으로 넘깁니다",
   "Hands the whole extract over to the '📦 Batch' tab",
   "抽出した全件を「📦 バッチ分析」タブへ渡します", "将抽取的全部数据移交到「📦 批量分析」标签页")
_a("det.batch_min", "일괄 분석은 2건 이상", "Batch needs at least 2 rows", "一括分析は2件以上",
   "批量分析需至少 2 条")
_a("det.path_of", "{name} 경로", "{name} path", "{name} のパス", "{name} 路径")
_a("det.read_fail", "읽기 실패: {name}", "Failed to read: {name}", "読み込み失敗: {name}",
   "读取失败: {name}")
_a("det.first_row", "📄 {name} · 첫 행", "📄 {name} · first row", "📄 {name} · 先頭行",
   "📄 {name} · 首行")
_a("det.pick_dataset", "사이드바 '📂 데이터셋'에서 먼저 데이터셋을 고르세요",
   "Pick a dataset first under '📂 Dataset' in the sidebar",
   "先にサイドバーの「📂 データセット」でデータセットを選んでください",
   "请先在侧边栏「📂 数据集」中选择数据集")
_a("det.scope", "추출 범위", "Extraction scope", "抽出範囲", "抽取范围")
_a("det.scope_help", "특정 사기 유형만 뽑아 모델 반응을 확인할 수 있습니다",
   "Pull a single fraud type to see how the model reacts",
   "特定の不正種別だけ抽出してモデルの反応を確認できます",
   "可仅抽取特定欺诈类型以查看模型反应")
_a("det.scope_nolabel", "범위 선택 불가 — 이 데이터셋에는 라벨(Fraud_Type)이 없습니다",
   "Scope unavailable — this dataset has no label (Fraud_Type)",
   "範囲選択不可 — このデータセットにはラベル（Fraud_Type）がありません",
   "无法选择范围 — 该数据集没有标签（Fraud_Type）")
_a("det.scope_empty", "'{scope}' 범위에 해당하는 행이 없습니다",
   "No rows match the '{scope}' scope", "「{scope}」範囲に該当する行がありません",
   "没有符合「{scope}」范围的行")
_a("det.ds_load_fail", "데이터셋 로드 실패: {e}", "Failed to load dataset: {e}",
   "データセットの読み込みに失敗: {e}", "数据集加载失败: {e}")
_a("det.extracted", "{n}건 추출 · 범위 {scope}", "{n} extracted · scope {scope}",
   "{n}件抽出 · 範囲 {scope}", "已抽取 {n} 条 · 范围 {scope}")

# ── 헤더 배지 ──
_a("hdr.pending", "미판정", "Unreviewed", "未判定", "未审核")
_a("hdr.sla_over", "SLA {n}분 초과", "Over SLA {n}m", "SLA {n}分超過", "超出 SLA {n}分")
_a("hdr.oldest", "최장 대기", "Longest wait", "最長待機", "最长等待")
_a("hdr.reviewer", "판정자", "Reviewer", "判定者", "审核人")
_a("hdr.no_name", "이름 없음", "No name set", "名前未設定", "未设置姓名")

# ── 공용 ──
_a("common.cases", "{n}건", "{n}", "{n}件", "{n}件")

# ── 오탐 분석 ──
_a("fp.rate", "오탐률", "FP rate", "誤検知率", "误报率")
_a("fp.coverage", "판정 커버리지", "Review coverage", "判定カバレッジ", "审核覆盖率")
_a("fp.cov_warn",
   "커버리지가 낮습니다 — 오탐률은 참고용입니다. 검토가 쉬운 건에 판정이 몰렸을 수 있습니다.",
   "Coverage is low — treat the FP rate as indicative only; reviews may be skewed toward easy cases.",
   "カバレッジが低いです — 誤検知率は参考値です。判定しやすい案件に偏った可能性があります。",
   "覆盖率偏低 — 误报率仅供参考，审核可能集中在容易判断的案例。")
_a("fp.timeline", "오탐률 추이", "FP rate over time", "誤検知率の推移", "误报率趋势")
_a("fp.by_dim", "차원별 오탐", "FP by dimension", "次元別誤検知", "分维度误报")
_a("fp.reasons", "오탐 사유 분포", "FP reasons", "誤検知理由の分布", "误报原因分布")
_a("fp.no_data", "아직 판정 데이터가 없습니다. 트리아지 탭에서 몇 건 판정하면 여기에 그래프가 그려집니다.",
   "No verdicts yet. Review a few alerts in the Triage tab and charts will appear here.",
   "判定データがありません。トリアージタブで判定するとグラフが表示されます。",
   "暂无判定数据。请先在分诊标签页审核几条告警。")

# ── 임계값 ──
_a("th.title", "임계값 시뮬레이터", "Threshold simulator", "閾値シミュレータ", "阈值模拟器")
_a("th.desc", "실제 담당자 판정을 기준으로 계산합니다 (검증셋이 아님)",
   "Computed from actual reviewer verdicts (not the validation set)",
   "実際の担当者判定に基づく計算です（検証セットではありません）",
   "基于实际审核判定计算（非验证集）")
_a("th.bias",
   "회색 구간은 데이터가 없습니다 — 임계값을 그 아래로 내렸을 때 새로 생길 알림은 판정 이력이 없어 추정할 수 없습니다.",
   "The grey band has no data — alerts that would newly fire below that threshold have never been reviewed.",
   "グレー区間はデータがありません — その閾値未満で新たに発生するアラートは判定履歴がありません。",
   "灰色区间无数据 — 低于该阈值新产生的告警没有审核记录，无法估算。")
_a("th.apply", "워처에 적용", "Apply to watcher", "ウォッチャーに適用", "应用到监视器")
_a("th.applied", "저장했습니다. 워처가 다음 폴링에 스스로 다시 읽습니다 (재시작 불필요).",
   "Saved. The watcher will reload it on the next poll — no restart needed.",
   "保存しました。次のポーリングでウォッチャーが自動再読込します（再起動不要）。",
   "已保存。监视器将在下次轮询时自动重新加载（无需重启）。")
_a("th.fp_cost", "오탐 1건 비용", "Cost per FP", "誤検知1件コスト", "单次误报成本")
_a("th.fn_cost", "미탐 1건 비용", "Cost per FN", "見逃し1件コスト", "单次漏报成本")

# ── 진단 ──
_a("diag.tz", "시간대 정합성", "Timestamp consistency", "タイムゾーン整合性", "时区一致性")
_a("diag.tz_warn",
   "이 컬럼에 UTC 값과 로컬시각 값이 섞여 있습니다. 조회 시 자동 보정되지만, 근본 해결은 기록하는 쪽을 통일하는 것입니다.",
   "This column mixes UTC and local timestamps. Queries correct for it automatically, but the real fix is to unify the writers.",
   "この列にUTCとローカル時刻が混在しています。照会時に自動補正されますが、根本解決は書き込み側の統一です。",
   "该列混有 UTC 与本地时间。查询时会自动校正，但根本解决办法是统一写入端。")
_a("diag.model", "모델 상태", "Model status", "モデル状態", "模型状态")

# ── 공통 ──
_a("common.refresh", "새로고침", "Refresh", "更新", "刷新")
_a("common.window", "기간", "Window", "期間", "时间范围")
_a("common.none", "데이터 없음", "No data", "データなし", "无数据")
_a("common.saved", "저장됨", "Saved", "保存しました", "已保存")
_a("common.db", "DB 경로", "DB path", "DBパス", "数据库路径")
_a("common.lang", "언어", "Language", "言語", "语言")
_a("common.theme", "테마", "Theme", "テーマ", "主题")

# 오탐 사유 코드 4개국어 (review_store.FP_REASONS 의 한국어판을 확장)
REASON_I18N = {
    "legit_customer": ("정상 고객 확인됨 (본인 거래)", "Verified legitimate customer",
                       "正常顧客と確認（本人取引）", "已确认为正常客户（本人交易）"),
    "known_pattern":  ("기존 예외 패턴 (해외출장·급여일 등)", "Known exception pattern",
                       "既知の例外パターン", "已知例外模式"),
    "test_data":      ("테스트/내부 거래", "Test or internal transaction",
                       "テスト・内部取引", "测试/内部交易"),
    "data_error":     ("데이터 오류·중복 유입", "Data error or duplicate ingest",
                       "データ誤り・重複取込", "数据错误或重复导入"),
    "model_drift":    ("모델 오작동 의심 (근거 불명)", "Suspected model drift",
                       "モデル誤作動の疑い", "疑似模型漂移"),
    "rule_overfit":   ("룰 과민반응", "Rule over-triggering", "ルール過敏反応", "规则过度触发"),
    "other":          ("기타 (메모 참조)", "Other (see memo)", "その他（メモ参照）", "其他（见备注）"),
}
_LG_IDX = {"ko": 0, "en": 1, "ja": 2, "zh": 3}


def reason_label(code: str, lang: str = "ko") -> str:
    tup = REASON_I18N.get(code)
    return tup[_LG_IDX.get(lang, 0)] if tup else code


def make_ops_t(session_state):
    """t(key) — 관제 신규 키는 _OPS 에서, 나머지는 i18n_data 에서.

    dashboard.py 의 tt() 와 같은 폴백 철학: 우리 표에 있으면 그것을 쓰고,
    없으면 i18n_data 로 넘기고, 거기도 없으면 키를 그대로 돌려준다.
    덕분에 i18n_data.py 를 한 줄도 수정하지 않아도 4개국어가 나온다.
    """
    base_t = make_t(session_state)

    def t(key, **kw):
        lang = session_state.get("lang", "ko")
        d = _OPS.get(key)
        if d:
            s = d.get(lang) or d.get("ko") or key
        else:
            s = base_t(key, **kw)
        if kw and isinstance(s, str):
            try:
                return s.format(**kw)
            except Exception:
                return s
        return s
    return t


def fraud_label(code: str, lang: str = "ko", short: bool = False) -> str:
    """사기 유형 표기 — 메인 대시보드와 반드시 같은 문구를 쓴다."""
    table = FRAUD_SHORT_I18N if short else FRAUD_LABELS_I18N
    return (table.get(lang) or table.get("ko") or {}).get(code, code or "-")


# ══════════════════════════════════════════════════════════
# CSS
# ══════════════════════════════════════════════════════════

def build_css(T: dict) -> str:
    """관제 화면 CSS. dashboard.py 의 3중 CSS 블록 중 관제에 필요한 것만 남겼다."""
    return f"""<style>
:root {{
  --bg-base:{T['bg_base']}; --bg-surface:{T['bg_surface']}; --bg-card:{T['bg_card']};
  --accent:{T['accent']}; --accent-rgb:{T['accent_rgb']};
  --red:{T['red']}; --green:{T['green']}; --amber:{T['amber']}; --blue:{T['blue']};
  --text-primary:{T['text_primary']}; --text-secondary:{T['text_secondary']};
  --text-muted:{T['text_muted']}; --radius:12px;
  --font-mono:ui-monospace,'SFMono-Regular','Cascadia Code',Consolas,monospace;
}}
.stApp {{ background:var(--bg-base); color:var(--text-primary); }}
[data-testid="stHeader"] {{ background:transparent; }}
h1,h2,h3,h4 {{ color:var(--text-primary)!important; letter-spacing:-0.01em; }}
[data-testid="stTabs"] [data-baseweb="tab-list"]{{
  background:var(--bg-surface)!important; border-radius:var(--radius)!important;
  padding:4px!important; gap:2px!important; border:1px solid rgba(var(--accent-rgb),.14)!important;}}
[data-testid="stTabs"] [data-baseweb="tab"]{{
  background:transparent!important; color:var(--text-secondary)!important;
  border-radius:9px!important; font-size:13px!important; font-weight:500!important;
  padding:6px 16px!important;}}
[data-testid="stTabs"] [aria-selected="true"]{{
  background:rgba(var(--accent-rgb),.16)!important; color:var(--accent)!important;}}
[data-testid="stMetric"]{{
  background:var(--bg-card); border:1px solid rgba(var(--accent-rgb),.12);
  border-radius:var(--radius); padding:12px 14px;}}
[data-testid="stMetricValue"]{{ font-family:var(--font-mono); font-size:24px!important; }}
.ops-hero {{
  display:flex; align-items:center; gap:12px; padding:14px 18px; margin-bottom:10px;
  background:linear-gradient(135deg, rgba(var(--accent-rgb),.13), transparent 70%);
  border:1px solid rgba(var(--accent-rgb),.20); border-radius:var(--radius);}}
.ops-hero .icon {{
  width:38px;height:38px;min-width:38px;border-radius:11px;display:flex;
  align-items:center;justify-content:center;font-size:19px;
  background:linear-gradient(135deg,var(--accent),{T['accent_dim']});
  box-shadow:0 4px 14px rgba(var(--accent-rgb),.35);}}
.ops-hero .ttl {{ font-size:17px;font-weight:800;color:var(--text-primary);line-height:1.15; }}
.ops-hero .sub {{ font-size:11.5px;color:var(--text-muted);margin-top:2px;letter-spacing:.02em; }}
.ops-hero .grow {{ flex:1 1 auto; }}
.ops-hero .badges {{ display:flex; gap:8px; flex-wrap:wrap; justify-content:flex-end; }}
.hero-badge {{
  display:flex; flex-direction:column; align-items:flex-end; min-width:76px;
  padding:5px 12px; border-radius:10px; background:var(--bg-card);
  border:1px solid rgba(var(--accent-rgb),.14);}}
.hero-badge .v {{
  font-size:15px; font-weight:800; line-height:1.15; color:var(--text-primary);
  font-family:var(--font-mono); font-variant-numeric:tabular-nums;}}
.hero-badge .k {{ font-size:9.5px; color:var(--text-muted); letter-spacing:.04em; margin-top:2px; }}
.hero-badge.ok   .v {{ color:var(--green); }}
.hero-badge.warn .v {{ color:var(--amber); }}
.hero-badge.warn    {{ border-color:rgba(232,192,99,.35); }}
.hero-badge.bad  .v {{ color:var(--red); }}
.hero-badge.bad     {{ border-color:rgba(232,93,117,.40); }}
@media (max-width:900px) {{ .ops-hero .badges {{ display:none; }} }}
.alert-card {{
  background:var(--bg-card); border:1px solid rgba(var(--accent-rgb),.12);
  border-left:3px solid var(--accent); border-radius:10px;
  padding:10px 14px; margin-bottom:8px;}}
.alert-card.hi {{ border-left-color:var(--red); }}
.alert-card.mid {{ border-left-color:var(--amber); }}
.mono {{ font-family:var(--font-mono); font-variant-numeric:tabular-nums; }}
.pill {{
  display:inline-block;padding:2px 9px;border-radius:999px;font-size:10.5px;
  font-weight:700;letter-spacing:.03em;}}
.pill.ok  {{ background:rgba(78,196,143,.16); color:var(--green); }}
.pill.warn{{ background:rgba(232,192,99,.16); color:var(--amber); }}
.pill.bad {{ background:rgba(232,93,117,.16); color:var(--red); }}
.note {{ font-size:11.5px; color:var(--text-muted); line-height:1.55; }}
.th-map {{
  border:1px solid rgba(var(--accent-rgb),.16); border-radius:var(--radius);
  overflow:hidden; margin:2px 0 10px;}}
.th-map .row {{
  display:flex; align-items:baseline; gap:10px; padding:8px 13px;
  border-top:1px solid rgba(var(--accent-rgb),.10);}}
.th-map .row:first-child {{ border-top:none; }}
.th-map .what {{ flex:0 0 40%; font-size:12px; color:var(--text-primary); font-weight:600; }}
.th-map .val {{
  flex:0 0 27%; font-family:var(--font-mono); font-variant-numeric:tabular-nums;
  font-size:12.5px; font-weight:700; color:var(--accent);}}
.th-map .where {{ flex:1 1 auto; font-size:10.5px; color:var(--text-muted); text-align:right; }}
.th-map .why {{
  padding:7px 13px; font-size:10.5px; color:var(--text-muted); line-height:1.5;
  background:rgba(var(--accent-rgb),.05);}}
.th-map.compact .row {{ display:block; padding:6px 10px; }}
.th-map.compact .what {{ font-size:10.5px; font-weight:700; }}
.th-map.compact .val {{ font-size:11.5px; }}
.th-map.compact .where {{ text-align:left; }}
</style>"""


def fmt_th(v) -> str:
    """임계값 표기 — 0.0050 처럼 꼬리 0 을 달지 않는다. 워처 값은 0.005 같은
    작은 수라 소수 2자리로 반올림하면 0.01/0.00 이 되어 뜻이 달라진다."""
    if v is None:
        return "—"
    try:
        return f"{float(v):.4f}".rstrip("0").rstrip(".") or "0"
    except (TypeError, ValueError):
        return "—"


def threshold_matrix(watcher=(None, None), detect=None,
                     dispatch=(None, None), dual: bool = False,
                     compact: bool = False) -> str:
    """'임계값이 왜 3개인가'를 한 표로 보여준다.

    이 콘솔에는 **이름이 같고 뜻이 다른** 임계값이 셋 있다.
      ① 워처 경보 등급   watcher_config.json  — 알림이 울릴지 말지
      ② 탐지 판정 임계값 사이드바 th_slider   — 이 화면에서 돌린 탐지의 사기 판정선
      ③ 발송 등급        사이드바 이중 임계값 — 이 콘솔이 내보내는 Slack/Email 등급
    셋 다 'th_review/th_confirm' 이라 불려서, 사이드바가 0.50 을 보여주는 동안
    워처는 0.005/0.9 로 돌고 있어도 아무도 몰랐다. 나란히 놓으면 설명이 필요 없다.

    compact=True 는 사이드바용(세로 배치, 폭 좁음).
    """
    wr, wc = watcher
    dr, dc = dispatch
    rows = [
        ("🛰 워처 경보 등급",
         f"검토 {fmt_th(wr)}↑ · 확정 {fmt_th(wc)}↑",
         "watcher_config.json · ⚙ 임계값 튜닝 탭에서 변경"),
        ("🎯 탐지 판정 임계값",
         fmt_th(detect),
         "사이드바 🎯 임계값 — 이 화면에서 돌린 탐지에만 적용"),
        ("📮 발송 등급 (이 콘솔)",
         (f"검토 {fmt_th(dr)}↑ · 확정 {fmt_th(dc)}↑" if dual
          else f"단일 {fmt_th(dr)}↑"),
         "사이드바 📮 이중 임계값 — Slack/Email 이 나가는 기준"),
    ]
    body = "".join(
        f'<div class="row"><div class="what">{_esc(w)}</div>'
        f'<div class="val">{_esc(v)}</div>'
        f'<div class="where">{_esc(where)}</div></div>'
        for w, v, where in rows)
    why = ("" if compact else
           '<div class="why">세 값은 <b>서로 다른 것을 정합니다</b> — 달라도 정상입니다. '
           '알림이 안 울리면 ①을, 탐지 결과가 이상하면 ②를, 메일이 안 나가면 ③을 보세요.</div>')
    return f'<div class="th-map{" compact" if compact else ""}">{body}{why}</div>'


def hero(t, icon="🛡", badges: list | None = None) -> str:
    """헤더. badges 는 [(라벨, 값, kind)] — kind 는 ''|'ok'|'warn'|'bad'.

    왜 헤더인가: 미판정 건수는 지금까지 트리아지 탭을 눌러야만 보였다. 첫 화면이
    'AI 분석'인 이상, 밀린 일이 있어도 탭을 옮기기 전엔 알 수 없다는 뜻이다.
    헤더는 모든 탭 위에 있으므로 어디서 일하든 눈에 들어온다.
    """
    _b = ""
    if badges:
        _b = ('<div class="badges">' + "".join(
            f'<div class="hero-badge {_esc(kind)}">'
            f'<div class="v">{_esc(val)}</div>'
            f'<div class="k">{_esc(lbl)}</div></div>'
            for lbl, val, kind in badges) + "</div>")
    return (f'<div class="ops-hero"><div class="icon">{icon}</div><div>'
            f'<div class="ttl">{t("app.title")}</div>'
            f'<div class="sub">{t("app.sub")}</div></div>'
            f'<div class="grow"></div>{_b}</div>')


def plotly_layout(T: dict) -> dict:
    """차트 공통 레이아웃 — 테마 색을 그대로 따른다."""
    return {
        "paper_bgcolor": "rgba(0,0,0,0)", "plot_bgcolor": "rgba(0,0,0,0)",
        "font": {"color": T["text_secondary"], "size": 11},
        "margin": {"l": 46, "r": 16, "t": 34, "b": 36},
        "colorway": T["plotly_colors"],
        "xaxis": {"gridcolor": f"rgba({T['accent_rgb']},0.08)", "zeroline": False},
        "yaxis": {"gridcolor": f"rgba({T['accent_rgb']},0.08)", "zeroline": False},
        "legend": {"orientation": "h", "y": -0.18},
    }

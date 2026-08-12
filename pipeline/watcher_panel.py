"""
watcher_panel — 대시보드용 워처 상태 패널 (읽기 전용)  ✨ v15 신규

설계 원칙
  · **읽기 전용** — 이 모듈은 DB에 절대 쓰지 않는다. 워처가 남긴
    watcher_status / watch_cursor / transactions / notified 를 조회만 한다.
  · **대시보드를 죽이지 않는다** — 테이블이 아직 없거나(워처 미실행) DB가
    잠겨 있어도 조용히 빈 상태를 그린다. 모든 조회가 try/except로 격리된다.
  · **의존성 최소** — dashboard.py의 테마 헬퍼(csec/kpi_card/t)에 기대지 않고
    기본 Streamlit 위젯만 쓴다. 대시보드가 개편돼도 이 파일은 안 깨진다.
    (dashboard.py는 5,000줄이 넘고 백업이 130개다 — 최소 침습이 원칙)

⏱ 시각 처리 주의
  워처는 sqlite의 datetime('now')로 기록한다 = **UTC**.
  파이썬 로컬시각과 직접 빼면 9시간이 어긋나므로,
  경과 시간은 반드시 SQL 안에서 strftime('%s') 끼리 계산한다.

dashboard.py 연동 (2줄)
    from pipeline.watcher_panel import render_watcher_panel   # ← 상단 import 근처
    render_watcher_panel()                                    # ← 원하는 세션 안
"""

from __future__ import annotations

import sqlite3
import logging
from pathlib import Path

log = logging.getLogger(__name__)

PANEL_VERSION = "v16"
_PROJ = Path(__file__).resolve().parent.parent

DEFAULT_DB = "fds_results.db"
DEFAULT_LOG = "watcher.log"


# ══════════════════════════════════════════════════════════
# 조회 (Streamlit 무관 — 테스트·MCP에서도 재사용 가능)
# ══════════════════════════════════════════════════════════

def _conn(db_path: str):
    con = sqlite3.connect(db_path, timeout=5)
    try:
        con.execute("PRAGMA busy_timeout=5000")
    except Exception:
        pass
    return con


def _table_exists(con, name: str) -> bool:
    try:
        cur = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,))
        return cur.fetchone() is not None
    except Exception:
        return False


def read_status(db_path: str = DEFAULT_DB) -> dict | None:
    """워처 하트비트. 워처를 한 번도 안 돌렸으면 None."""
    try:
        con = _conn(db_path)
        if not _table_exists(con, "watcher_status"):
            con.close()
            return None
        cur = con.execute("""
            SELECT started_at, last_poll, polls, rows_done, anomalies, notified, errors, note,
                   CAST(strftime('%s','now') - strftime('%s', last_poll) AS INTEGER) AS age_sec,
                   CAST(strftime('%s','now') - strftime('%s', started_at) AS INTEGER) AS uptime_sec
            FROM watcher_status WHERE id = 1""")
        r = cur.fetchone()
        con.close()
        if not r:
            return None
        keys = ("started_at", "last_poll", "polls", "rows_done", "anomalies",
                "notified", "errors", "note", "age_sec", "uptime_sec")
        return dict(zip(keys, r))
    except Exception as e:
        log.debug(f"워처 상태 조회 실패: {e}")
        return None


def read_cursors(db_path: str = DEFAULT_DB, limit: int = 50) -> list[dict]:
    """감시 중인 파일별 처리 진행도."""
    try:
        con = _conn(db_path)
        if not _table_exists(con, "watch_cursor"):
            con.close()
            return []
        cur = con.execute("""
            SELECT path, size, rows_done, updated_at,
                   CAST(strftime('%s','now') - strftime('%s', updated_at) AS INTEGER) AS age_sec
            FROM watch_cursor ORDER BY updated_at DESC LIMIT ?""", (limit,))
        rows = cur.fetchall()
        con.close()
        return [{"파일": Path(r[0]).name, "크기(KB)": round((r[1] or 0) / 1024, 1),
                 "처리행": r[2], "마지막 갱신": r[3], "_age": r[4],
                 "_full_path": r[0]} for r in rows]
    except Exception as e:
        log.debug(f"커서 조회 실패: {e}")
        return []


def read_recent_detections(db_path: str = DEFAULT_DB, limit: int = 30,
                           only_anomaly: bool = True) -> list[dict]:
    """워처가 처리한 최근 거래. 대시보드/워처 어느 스키마든 동작한다."""
    try:
        con = _conn(db_path)
        if not _table_exists(con, "transactions"):
            con.close()
            return []
        cols = {r[1] for r in con.execute("PRAGMA table_info(transactions)")}
        ts = "detected_at" if "detected_at" in cols else (
             "processed_at" if "processed_at" in cols else "id")
        has_mode = "input_mode" in cols
        sel = f"transaction_id, fraud_type, risk_score, is_anomaly, {ts}" + \
              (", input_mode" if has_mode else "")
        q = f"SELECT {sel} FROM transactions WHERE 1=1 "
        if has_mode:
            q += "AND input_mode LIKE 'watcher%' "     # 워처가 넣은 행만
        if only_anomaly:
            q += "AND is_anomaly = 1 "
        q += "ORDER BY id DESC LIMIT ?"
        rows = con.execute(q, (limit,)).fetchall()
        con.close()
        out = []
        for r in rows:
            d = {"거래 ID": r[0], "유형": r[1], "위험점수": round(r[2] or 0, 4),
                 "이상": "🚨" if r[3] else "✅", "시각": r[4]}
            if has_mode:
                d["출처"] = r[5]
            out.append(d)
        return out
    except Exception as e:
        log.debug(f"탐지 이력 조회 실패: {e}")
        return []


def read_notified(db_path: str = DEFAULT_DB, limit: int = 20) -> list[dict]:
    try:
        con = _conn(db_path)
        if not _table_exists(con, "notified"):
            con.close()
            return []
        rows = con.execute(
            "SELECT txn_id, tier, sent_at FROM notified ORDER BY sent_at DESC LIMIT ?",
            (limit,)).fetchall()
        con.close()
        _icon = {"confirm": "🚨 확정", "review": "⚠️ 검토요청", "single": "🚨 경보"}
        return [{"거래 ID": r[0], "등급": _icon.get(r[1], r[1]), "발송(UTC)": r[2]} for r in rows]
    except Exception as e:
        log.debug(f"발송 이력 조회 실패: {e}")
        return []


def tail_log(log_path: str = DEFAULT_LOG, n: int = 25) -> str:
    """watcher.log 꼬리. 서비스로 돌릴 땐 콘솔이 없으므로 유일한 관측 창구다."""
    p = Path(log_path)
    if not p.is_absolute():
        p = _PROJ / log_path
    try:
        if not p.exists():
            return ""
        # 큰 로그 대비 — 뒤쪽 64KB만 읽는다
        size = p.stat().st_size
        with open(p, "rb") as f:
            if size > 65536:
                f.seek(size - 65536)
                f.readline()          # 잘린 첫 줄 버림
            data = f.read().decode("utf-8", errors="replace")
        lines = data.splitlines()
        return "\n".join(lines[-n:])
    except Exception as e:
        return f"(로그 읽기 실패: {e})"


def liveness(status: dict | None, expected_interval: float = 5.0) -> tuple[str, str]:
    """(아이콘 상태, 설명). 하트비트가 폴링 간격의 4배를 넘으면 죽은 것으로 본다."""
    if status is None:
        return "⚫", "워처를 아직 실행한 적이 없습니다"
    age = status.get("age_sec")
    note = (status.get("note") or "").strip()
    if note == "stopped":
        return "🔴", f"정상 종료됨 ({_ago(age)} 전)"
    if note == "once":
        return "🔵", f"1회 실행 모드로 동작함 ({_ago(age)} 전) — 상시 감시 중이 아닙니다"
    if age is None:
        return "⚫", "하트비트 시각을 읽지 못했습니다"
    # ⏰ 미래 하트비트 — 시계가 어긋났거나, UTC 컬럼에 **로컬시각이 들어간** 것이다.
    #   이 프로젝트에서 반복된 사고 유형이라 '정상 동작 중'으로 넘기면 안 된다.
    #   (예: 로컬시각을 그대로 쓰면 KST 기준 9시간 미래로 보인다)
    if age < -60:
        return "🟡", (f"하트비트가 **{_ago(-age)} 미래**입니다 — 시계가 어긋났거나 "
                      f"UTC 컬럼에 로컬시각이 기록됐을 수 있습니다. "
                      f"🩺 진단 탭의 시간대 점검을 확인하세요")
    limit = max(30, expected_interval * 4)
    if age <= limit:
        return "🟢", f"정상 동작 중 (마지막 폴링 {_ago(age)} 전)"
    return "🔴", (f"응답 없음 — 마지막 폴링이 {_ago(age)} 전입니다. "
                  f"프로세스가 죽었거나 멈췄을 수 있습니다")


def _ago(sec) -> str:
    try:
        s = int(sec)
    except (TypeError, ValueError):
        return "?"
    if s < 60:
        return f"{s}초"
    if s < 3600:
        return f"{s // 60}분"
    if s < 86400:
        return f"{s // 3600}시간"
    return f"{s // 86400}일"


def summary_line(db_path: str = DEFAULT_DB, expected_interval: float = 5.0) -> str:
    """사이드바·헤더용 한 줄 요약 (MCP 도구에서도 그대로 재사용 가능)."""
    st_ = read_status(db_path)
    icon, desc = liveness(st_, expected_interval)
    if st_ is None:
        return f"{icon} 워처 미실행"
    return (f"{icon} 워처 · {st_['polls']:,}폴링 · {st_['rows_done']:,}행 · "
            f"이상 {st_['anomalies']:,} · 발송 {st_['notified']:,}"
            + (f" · 오류 {st_['errors']:,}" if st_["errors"] else ""))


# ══════════════════════════════════════════════════════════
# 렌더링
# ══════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════
# 화면 문구 — 4개 국어
#
#   ⚠ 이 모듈은 ops_dashboard 와 dashboard 두 앱이 함께 쓴다. 그래서 ops_ui 의
#     t() 에 의존하지 않고 자기 표를 들고 있고, lang 기본값은 "ko" 다 —
#     lang 을 넘기지 않는 dashboard.py 쪽 화면은 한 글자도 바뀌지 않는다.
# ══════════════════════════════════════════════════════════
_WP = {
"ko": {
 "panel_fail": "⚠️ 워처 패널을 표시할 수 없습니다 — {e}",
 "title": "워처 상태",
 "no_db": "이 대시보드에서는 워처 상태를 볼 수 없습니다.\n\n`{db}` 를 찾을 수 없습니다. "
          "Streamlit Cloud 등 **워처와 다른 서버**에서 실행 중이라면 정상입니다 — 워처는 "
          "사내 PC의 DB에 기록하므로, 그 PC에서 대시보드를 열어야 상태가 보입니다.",
 "never": "워처를 아직 실행한 적이 없습니다.\n\n```\nconda activate qaqc_st\n"
          "set HF_HUB_OFFLINE=1\npython watcher.py --interval 5 --startup-ping\n```\n"
          "처음이라면 `--once --dry-run` 으로 먼저 확인하세요.",
 "k_polls": "폴링", "k_rows": "처리 행", "k_anom": "이상거래", "k_sent": "알림 발송",
 "k_err": "오류", "need_check": "확인 필요",
 "uptime": "가동 시작 {up} 전 · 마지막 폴링 {age} 전 · 상태 `{note}`",
 "hist": "🚨 워처 탐지 이력", "anom_only": "이상거래만 보기",
 "hist_none": "아직 탐지 이력이 없습니다.",
 "sent_hist": "📨 알림 발송 이력 (중복 억제 기준)",
 "sent_note": "같은 거래 ID로는 설정된 시간(기본 24h) 안에 동급 이하 알림이 재발송되지 않습니다.",
 "sent_none": "발송 이력이 없습니다.",
 "cursors": "📂 감시 파일 진행도",
 "cursors_note": "행이 추가된 파일은 '처리행' 이후 분만 다시 읽습니다. "
                 "전량 재처리하려면 해당 파일의 커서를 삭제하세요.",
 "cursors_none": "등록된 파일이 없습니다. inbox 폴더에 CSV를 넣어보세요.",
 "log": "📜 watcher.log (최근 25줄)", "log_none": "로그 파일이 없습니다: {path}",
 "refresh": "🔄 새로고침",
 "settings": "⚙️ 워처 임계값·알림 설정 — {desc}",
 "no_cfg": "아직 `watcher_config.json` 이 없습니다. 워처를 한 번 실행하면 현재 설정으로 "
           "자동 생성되고, 여기서 저장해도 새로 만들어집니다.",
 "dual": "이중 임계값 사용",
 "dual_help": "ON: 1차는 Slack만(검토 요청), 2차는 Slack+Email(확정 통보). "
              "OFF: 단일 임계값으로 한 번에 발송",
 "th1": "1차 · 검토 요청 (Slack)", "th2": "2차 · 확정 통보 (Slack+Email)",
 "th_inverted": "⚠️ 2차가 1차보다 낮습니다 → 저장 시 {v} 로 보정됩니다.",
 "th_expl": "위험 {r} 이상 → Slack · {c} 이상 → Slack+Email · 점수가 낮아도 "
            "**예측 유형이 사기면 검토 요청**으로 올라갑니다 "
            "(이 모델의 사기 재현율은 검증셋 기준 0.53이라 미탐 안전망이 필요합니다)",
 "th_single": "임계값", "pii": "마스킹 레벨",
 "pii_help": "LLM·Slack·Email로 나가기 전과 DB 적재 전에 적용됩니다",
 "dedup": "같은 거래 재알림 억제(시간)",
 "slack": "Slack 발송", "email": "Email 발송", "llm": "LLM 분석",
 "llm_help": "OFF면 기본 양식으로만 발송합니다 (빠르지만 원인 분석 없음)",
 "dry": "🧪 DRY-RUN (판정만 하고 발송 안 함)", "save": "💾 저장 (즉시 반영)",
 "saved": "{msg}\n\n워처가 다음 폴링(최대 {sec}초) 안에 스스로 다시 읽습니다. 재시작 불필요.",
 "copy_sb": "⬅️ 사이드바 설정 복사",
 "copy_sb_help": "사이드바의 이중 임계값 슬라이더 값을 워처 설정으로 가져옵니다",
 "immutable": "⚠️ 모델 경로·감시 폴더·폴링 간격은 여기서 바꿀 수 없습니다 "
              "(프로세스 시작 시점에만 쓰이는 값이라 워처 재시작이 필요합니다).",
},
"en": {
 "panel_fail": "⚠️ Cannot display the watcher panel — {e}",
 "title": "Watcher status",
 "no_db": "This dashboard cannot see the watcher's status.\n\n`{db}` was not found. That is "
          "normal if you are running on **a different host than the watcher** (e.g. Streamlit "
          "Cloud) — the watcher writes to a DB on the office PC, so the dashboard has to be "
          "opened there.",
 "never": "The watcher has never been run.\n\n```\nconda activate qaqc_st\n"
          "set HF_HUB_OFFLINE=1\npython watcher.py --interval 5 --startup-ping\n```\n"
          "If this is your first time, try `--once --dry-run` first.",
 "k_polls": "Polls", "k_rows": "Rows done", "k_anom": "Anomalies", "k_sent": "Alerts sent",
 "k_err": "Errors", "need_check": "Needs attention",
 "uptime": "Up for {up} · last poll {age} ago · state `{note}`",
 "hist": "🚨 Watcher detection history", "anom_only": "Anomalies only",
 "hist_none": "No detections yet.",
 "sent_hist": "📨 Alert send history (dedup basis)",
 "sent_note": "The same transaction ID is not re-alerted at the same or lower tier within the "
              "configured window (24h by default).",
 "sent_none": "No sends yet.",
 "cursors": "📂 Watched-file progress",
 "cursors_note": "For files that grew, only rows after 'rows done' are re-read. To reprocess "
                 "everything, delete that file's cursor.",
 "cursors_none": "No files registered. Try dropping a CSV into the inbox folder.",
 "log": "📜 watcher.log (last 25 lines)", "log_none": "No log file: {path}",
 "refresh": "🔄 Refresh",
 "settings": "⚙️ Watcher thresholds and alerting — {desc}",
 "no_cfg": "There is no `watcher_config.json` yet. Running the watcher once creates it from the "
           "current settings, and saving here creates it too.",
 "dual": "Use dual thresholds",
 "dual_help": "ON: tier 1 goes to Slack only (review request), tier 2 to Slack+Email "
              "(confirmed). OFF: a single threshold sends everything at once.",
 "th1": "Tier 1 · review request (Slack)", "th2": "Tier 2 · confirmed (Slack+Email)",
 "th_inverted": "⚠️ Tier 2 is below tier 1 → it will be corrected to {v} on save.",
 "th_expl": "Risk {r}+ → Slack · {c}+ → Slack+Email · even at a low score, **a predicted fraud "
            "type is escalated to a review request** (this model's fraud recall is 0.53 on the "
            "validation set, so a safety net against misses is needed)",
 "th_single": "Threshold", "pii": "Masking level",
 "pii_help": "Applied before anything goes to the LLM/Slack/email and before it lands in the DB",
 "dedup": "Re-alert suppression for same txn (hours)",
 "slack": "Send to Slack", "email": "Send email", "llm": "LLM analysis",
 "llm_help": "OFF sends the plain template only (fast, but with no cause analysis)",
 "dry": "🧪 DRY-RUN (judge only, send nothing)", "save": "💾 Save (takes effect immediately)",
 "saved": "{msg}\n\nThe watcher re-reads it by itself within the next poll (up to {sec}s). "
          "No restart needed.",
 "copy_sb": "⬅️ Copy from sidebar",
 "copy_sb_help": "Pulls the sidebar's dual-threshold slider values into the watcher config",
 "immutable": "⚠️ Model path, watched folder and poll interval cannot be changed here (they are "
              "only read at process start, so the watcher must be restarted).",
},
"ja": {
 "panel_fail": "⚠️ ウォッチャーパネルを表示できません — {e}",
 "title": "ウォッチャー状態",
 "no_db": "このダッシュボードではウォッチャーの状態を見られません。\n\n`{db}` が見つかりません。"
          "Streamlit Cloud など**ウォッチャーとは別のサーバー**で実行中なら正常です — "
          "ウォッチャーは社内PCのDBに記録するため、そのPCでダッシュボードを開く必要があります。",
 "never": "ウォッチャーをまだ実行したことがありません。\n\n```\nconda activate qaqc_st\n"
          "set HF_HUB_OFFLINE=1\npython watcher.py --interval 5 --startup-ping\n```\n"
          "初めてなら `--once --dry-run` で先に確認してください。",
 "k_polls": "ポーリング", "k_rows": "処理行", "k_anom": "異常取引", "k_sent": "通知送信",
 "k_err": "エラー", "need_check": "要確認",
 "uptime": "稼働開始 {up}前 · 最終ポーリング {age}前 · 状態 `{note}`",
 "hist": "🚨 ウォッチャー検知履歴", "anom_only": "異常取引のみ表示",
 "hist_none": "まだ検知履歴がありません。",
 "sent_hist": "📨 通知送信履歴（重複抑制の基準）",
 "sent_note": "同じ取引IDには設定時間（既定24h）以内、同等以下の通知は再送されません。",
 "sent_none": "送信履歴がありません。",
 "cursors": "📂 監視ファイルの進捗",
 "cursors_note": "行が追加されたファイルは「処理行」以降のみ読み直します。"
                 "全量を再処理するには該当ファイルのカーソルを削除してください。",
 "cursors_none": "登録されたファイルがありません。inbox フォルダにCSVを入れてみてください。",
 "log": "📜 watcher.log（最新25行）", "log_none": "ログファイルがありません: {path}",
 "refresh": "🔄 更新",
 "settings": "⚙️ ウォッチャー閾値・通知設定 — {desc}",
 "no_cfg": "まだ `watcher_config.json` がありません。ウォッチャーを一度実行すると現在の設定で"
           "自動生成され、ここで保存しても新規作成されます。",
 "dual": "二段階閾値を使う",
 "dual_help": "ON: 一次はSlackのみ（検討依頼）、二次はSlack+Email（確定通知）。"
              "OFF: 単一閾値で一度に送信",
 "th1": "一次 · 検討依頼 (Slack)", "th2": "二次 · 確定通知 (Slack+Email)",
 "th_inverted": "⚠️ 二次が一次より低いです → 保存時に {v} に補正されます。",
 "th_expl": "リスク {r} 以上 → Slack · {c} 以上 → Slack+Email · スコアが低くても"
            "**予測種別が不正なら検討依頼**に上がります"
            "（このモデルの不正再現率は検証セット基準0.53のため、見逃しの安全網が必要です）",
 "th_single": "閾値", "pii": "マスキングレベル",
 "pii_help": "LLM・Slack・Emailへ出る前とDB格納前に適用されます",
 "dedup": "同一取引の再通知抑制（時間）",
 "slack": "Slack送信", "email": "Email送信", "llm": "LLM分析",
 "llm_help": "OFFなら既定の様式のみで送信します（高速ですが原因分析なし）",
 "dry": "🧪 DRY-RUN（判定のみで送信しない）", "save": "💾 保存（即時反映）",
 "saved": "{msg}\n\nウォッチャーが次のポーリング（最大{sec}秒）以内に自ら読み直します。再起動不要。",
 "copy_sb": "⬅️ サイドバー設定をコピー",
 "copy_sb_help": "サイドバーの二段階閾値スライダーの値をウォッチャー設定に取り込みます",
 "immutable": "⚠️ モデルパス・監視フォルダ・ポーリング間隔はここでは変更できません"
              "（プロセス開始時のみ読まれる値のため、ウォッチャーの再起動が必要です）。",
},
"zh": {
 "panel_fail": "⚠️ 无法显示监视器面板 — {e}",
 "title": "监视器状态",
 "no_db": "本仪表板无法查看监视器状态。\n\n未找到 `{db}`。如果运行在**与监视器不同的服务器**"
          "（如 Streamlit Cloud）上，这是正常的 — 监视器写入的是公司内部 PC 上的数据库，"
          "需要在那台 PC 上打开仪表板。",
 "never": "尚未运行过监视器。\n\n```\nconda activate qaqc_st\n"
          "set HF_HUB_OFFLINE=1\npython watcher.py --interval 5 --startup-ping\n```\n"
          "如果是第一次，请先用 `--once --dry-run` 确认。",
 "k_polls": "轮询", "k_rows": "处理行数", "k_anom": "异常交易", "k_sent": "已发告警",
 "k_err": "错误", "need_check": "需要确认",
 "uptime": "已运行 {up} · 最后轮询 {age}前 · 状态 `{note}`",
 "hist": "🚨 监视器检测历史", "anom_only": "仅显示异常交易", "hist_none": "尚无检测历史。",
 "sent_hist": "📨 告警发送历史（去重依据）",
 "sent_note": "同一交易ID在设定时间内（默认24小时）不会重复发送同级或更低级别的告警。",
 "sent_none": "尚无发送记录。",
 "cursors": "📂 监听文件进度",
 "cursors_note": "对于新增了行的文件，只重新读取「处理行数」之后的部分。"
                 "如需全量重新处理，请删除该文件的游标。",
 "cursors_none": "没有已登记的文件。可以尝试把 CSV 放入 inbox 文件夹。",
 "log": "📜 watcher.log（最近 25 行）", "log_none": "没有日志文件: {path}",
 "refresh": "🔄 刷新",
 "settings": "⚙️ 监视器阈值与告警设置 — {desc}",
 "no_cfg": "尚无 `watcher_config.json`。运行一次监视器会按当前设置自动生成，在这里保存也会新建。",
 "dual": "使用双阈值",
 "dual_help": "开启: 一级仅 Slack（待审请求），二级 Slack+邮件（确认通知）。"
              "关闭: 用单一阈值一次性发送",
 "th1": "一级 · 待审请求 (Slack)", "th2": "二级 · 确认通知 (Slack+邮件)",
 "th_inverted": "⚠️ 二级低于一级 → 保存时将修正为 {v}。",
 "th_expl": "风险 {r} 以上 → Slack · {c} 以上 → Slack+邮件 · 即使分数较低，"
            "**只要预测类型为欺诈也会升级为待审请求**"
            "（该模型在验证集上的欺诈召回率为 0.53，因此需要防漏报的安全网）",
 "th_single": "阈值", "pii": "脱敏级别",
 "pii_help": "在发往 LLM、Slack、邮件之前以及写入数据库之前生效",
 "dedup": "同一交易重复告警抑制（小时）",
 "slack": "发送 Slack", "email": "发送邮件", "llm": "LLM 分析",
 "llm_help": "关闭时仅按默认模板发送（速度快，但没有原因分析）",
 "dry": "🧪 DRY-RUN（仅判定，不发送）", "save": "💾 保存（立即生效）",
 "saved": "{msg}\n\n监视器会在下一次轮询（最多 {sec} 秒）内自行重新读取。无需重启。",
 "copy_sb": "⬅️ 从侧边栏复制",
 "copy_sb_help": "把侧边栏的双阈值滑块数值导入监视器配置",
 "immutable": "⚠️ 模型路径、监听文件夹与轮询间隔无法在此修改"
              "（这些值仅在进程启动时读取，需要重启监视器）。",
},
}


def _w(lang: str) -> dict:
    """언어별 문구. 모르는 언어는 한국어로 폴백."""
    return _WP.get(lang) or _WP["ko"]


def render_watcher_panel(db_path: str = DEFAULT_DB,
                         log_path: str = DEFAULT_LOG,
                         expected_interval: float = 5.0,
                         key_prefix: str = "wp",
                         expanded: bool = True,
                         lang: str = "ko"):
    """대시보드에 워처 상태 패널을 그린다. 어떤 실패도 밖으로 던지지 않는다."""
    try:
        import streamlit as st
    except ImportError:
        print(summary_line(db_path, expected_interval))
        return

    try:
        _render(st, db_path, log_path, expected_interval, key_prefix, expanded, lang)
    except Exception as e:
        log.warning(f"워처 패널 렌더 실패(무시): {type(e).__name__}: {e}")
        try:
            st.caption(_w(lang)["panel_fail"].format(e=f"{type(e).__name__}: {e}"))
        except Exception:
            pass


def _render(st, db_path, log_path, expected_interval, key_prefix, expanded, lang="ko"):
    W = _w(lang)
    status = read_status(db_path)
    icon, desc = liveness(status, expected_interval)

    st.markdown(f"### {icon} {W['title']} &nbsp;<span style='font-size:13px;opacity:.6'>"
                f"{PANEL_VERSION}</span>", unsafe_allow_html=True)

    # ── 미실행 안내 ──
    if status is None:
        # DB 파일 자체가 없으면 '미실행'이 아니라 '다른 서버'일 가능성이 높다
        import os as _os
        if not _os.path.exists(db_path):
            st.info(W["no_db"].format(db=db_path))
            return
        st.info(W["never"])
        return

    if icon == "🔴":
        st.error(desc)
    elif icon == "🟢":
        st.success(desc)
    elif icon == "🔵":
        st.info(desc)          # 1회 실행은 '경고'가 아니라 상태 안내
    else:
        st.warning(desc)

    # ── KPI ──
    c = st.columns(5)
    c[0].metric(W["k_polls"], f"{status['polls']:,}")
    c[1].metric(W["k_rows"], f"{status['rows_done']:,}")
    c[2].metric(W["k_anom"], f"{status['anomalies']:,}")
    c[3].metric(W["k_sent"], f"{status['notified']:,}")
    c[4].metric(W["k_err"], f"{status['errors']:,}",
                delta=None if not status["errors"] else W["need_check"],
                delta_color="inverse")

    st.caption(W["uptime"].format(up=_ago(status.get("uptime_sec")),
                                  age=_ago(status.get("age_sec")),
                                  note=status.get("note") or "-"))

    # ── 🔌 시작·중지 (기본 잠김 — watcher_control 참고) ──
    try:
        try:
            from pipeline.watcher_control import render_controls
        except ImportError:
            from watcher_control import render_controls
        render_controls(st, key_prefix)
    except Exception as _wce:
        log.debug(f"제어 UI 생략: {_wce}")

    # ── ⚙️ 워처 설정 (즉시 반영) ──
    _render_settings(st, db_path, key_prefix, expected_interval, lang)

    # ── 탐지 이력 ──
    with st.expander(W["hist"], expanded=True):
        only_anom = st.checkbox(W["anom_only"], value=True,
                                key=f"{key_prefix}_only_anom")
        rows = read_recent_detections(db_path, limit=50, only_anomaly=only_anom)
        if rows:
            st.dataframe(rows, width="stretch", hide_index=True)
        else:
            st.caption(W["hist_none"])

    # ── 발송 이력 ──
    with st.expander(W["sent_hist"]):
        sent = read_notified(db_path)
        if sent:
            st.dataframe(sent, width="stretch", hide_index=True)
            st.caption(W["sent_note"])
        else:
            st.caption(W["sent_none"])

    # ── 파일 커서 ──
    with st.expander(W["cursors"]):
        curs = read_cursors(db_path)
        if curs:
            view = [{k: v for k, v in c_.items() if not k.startswith("_")} for c_ in curs]
            st.dataframe(view, width="stretch", hide_index=True)
            st.caption(W["cursors_note"])
        else:
            st.caption(W["cursors_none"])

    # ── 로그 ──
    with st.expander(W["log"]):
        txt = tail_log(log_path, 25)
        if txt:
            st.code(txt, language="log")
        else:
            st.caption(W["log_none"].format(path=log_path))

    if st.button(W["refresh"], key=f"{key_prefix}_refresh"):
        st.rerun()


def _render_settings(st, db_path, key_prefix, expected_interval, lang="ko"):
    W = _w(lang)
    """워처 임계값·알림 설정 편집. 저장하면 다음 폴링에 워처가 스스로 다시 읽는다."""
    try:
        from pipeline import watcher_config as wcfg
    except ImportError:
        try:
            import watcher_config as wcfg
        except ImportError:
            return

    cur = wcfg.load()
    with st.expander(W["settings"].format(desc=wcfg.describe(cur)), expanded=False):
        if not cur:
            st.caption(W["no_cfg"])

        dual = st.toggle(W["dual"], value=bool(cur.get("dual_threshold", True)),
                         key=f"{key_prefix}_dual", help=W["dual_help"])
        if dual:
            c1, c2 = st.columns(2)
            th_r = c1.slider(W["th1"], 0.0, 1.0,
                             float(cur.get("th_review", 0.45)), 0.01, key=f"{key_prefix}_thr")
            th_c = c2.slider(W["th2"], 0.0, 1.0,
                             float(cur.get("th_confirm", 0.80)), 0.01, key=f"{key_prefix}_thc")
            if th_c < th_r:
                st.caption(W["th_inverted"].format(v=f"{th_r:.2f}"))
            th_single = float(cur.get("threshold", 0.5))
            st.caption(W["th_expl"].format(r=f"{th_r:.2f}", c=f"{max(th_r, th_c):.2f}"))
        else:
            th_single = st.slider(W["th_single"], 0.0, 1.0, float(cur.get("threshold", 0.5)), 0.01,
                                  key=f"{key_prefix}_ths")
            th_r = float(cur.get("th_review", 0.45))
            th_c = float(cur.get("th_confirm", 0.80))

        c3, c4 = st.columns(2)
        pii = c3.selectbox(
            W["pii"], wcfg.PII_LEVELS,
            index=(list(wcfg.PII_LEVELS).index(cur.get("pii_level", "standard"))
                   if cur.get("pii_level", "standard") in wcfg.PII_LEVELS else 2),
            key=f"{key_prefix}_pii",
            help=W["pii_help"])
        dedup = c4.number_input(W["dedup"], 0, 720,
                                int(cur.get("dedup_hours", 24)), 1, key=f"{key_prefix}_dedup")

        c5, c6, c7 = st.columns(3)
        n_slack = c5.toggle(W["slack"], value=bool(cur.get("notify_slack", True)),
                            key=f"{key_prefix}_slack")
        n_email = c6.toggle(W["email"], value=bool(cur.get("notify_email", True)),
                            key=f"{key_prefix}_email")
        use_llm = c7.toggle(W["llm"], value=bool(cur.get("use_llm", True)),
                            key=f"{key_prefix}_llm", help=W["llm_help"])

        dry = st.toggle(W["dry"],
                        value=bool(cur.get("dry_run", False)), key=f"{key_prefix}_dry")

        b1, b2 = st.columns([1, 1])
        if b1.button(W["save"], key=f"{key_prefix}_save", type="primary",
                     width="stretch"):
            ok, msg = wcfg.save({
                "dual_threshold": dual, "threshold": th_single,
                "th_review": th_r, "th_confirm": th_c,
                "pii_level": pii, "dedup_hours": dedup,
                "notify_slack": n_slack, "notify_email": n_email,
                "use_llm": use_llm, "dry_run": dry,
            })
            if ok:
                st.success(W["saved"].format(msg=msg, sec=f"{expected_interval:.0f}"))
            else:
                st.error(msg)

        if b2.button(W["copy_sb"], key=f"{key_prefix}_copy", width="stretch",
                     help=W["copy_sb_help"]):
            st.session_state[f"{key_prefix}_dual"] = bool(
                st.session_state.get("dual_threshold", True))
            st.session_state[f"{key_prefix}_thr"] = float(
                st.session_state.get("th_review", 0.45))
            st.session_state[f"{key_prefix}_thc"] = float(
                st.session_state.get("th_confirm", 0.80))
            st.rerun()

        st.caption(W["immutable"])


def render_watcher_badge(db_path: str = DEFAULT_DB, expected_interval: float = 5.0):
    """사이드바용 한 줄 배지 (선택)."""
    try:
        import streamlit as st
        st.caption(summary_line(db_path, expected_interval))
    except Exception:
        pass


# ── CLI 확인용:  python -m pipeline.watcher_panel ──
if __name__ == "__main__":
    print(summary_line())
    s = read_status()
    if s:
        print(f"  마지막 폴링: {s['last_poll']} (UTC) · {_ago(s['age_sec'])} 전")
    for r in read_recent_detections(limit=10):
        print("  ", r)

"""
ops_agent — 관제 콘솔 전용 챗 에이전트 액션

왜 chat_agent.ACTIONS 를 그대로 못 쓰나
  저쪽 액션은 dashboard.py 전용이다 — `goto_session(1~5)`, `set_manual_field`,
  세션2 지표 전환 등. ops 에는 '세션'이 없고 탭이 있으며, 조작 대상도 다르다.
  그리고 ACTIONS 는 **모듈 전역 딕셔너리**라 앱별로 나눌 수 없다. 여기에 ops
  액션을 밀어 넣으면 dashboard 챗봇 프롬프트에도 섞여 들어가, 있지도 않은
  기능을 안내하게 된다.
  → 같은 프로토콜([[ACTION: name(arg)]])만 재사용하고 레지스트리는 분리한다.

무엇을 허용하고 무엇을 막았나
  · 허용 — 화면 이동 · 조회 · **되돌릴 수 있는** 설정 변경(임계값·SLA·정렬·범위·
    기간·필터·검색어·새로고침)
  · 허용(v2) — **실행형**: AI 분석 실행 · 일괄 분석 실행. 시간은 걸리지만
    결과를 화면에 띄울 뿐 아무것도 밖으로 내보내지 않는다. 발송은 그 뒤에
    사람이 누르는 별도 버튼이다(det_send_slack / det_send_email).
  · 차단 — 발송(Slack/Email) · 판정 기록 · 워처 시작/중지
    되돌릴 수 없거나 감사 대상인 행위는 사람이 버튼을 눌러야 한다. 자연어는
    "오탐으로 찍어줘"와 "오탐이면 어떻게 돼?"를 구분하지 못한다.
  · 차단 — 경보 등급 임계값(th_review/th_confirm) 저장. 화면 설정처럼 보이지만
    watcher_config.json 은 **핫 리로드**라, 저장하는 순간 무인 워처의 경보
    기준이 바뀐다(ops_dashboard `_tier_th` 주석 참조). 실질적으로 워처 제어다.
    비용곡선을 보고 사람이 확인 카드를 거쳐 누른다.

동작 방식
  ops_dashboard 가 ChatAgent(enable_actions=False) 로 부르되, 시스템 지시문에
  ops_actions_prompt() 를 덧붙이고, 응답을 parse(...) 로 해석해 apply(...) 로
  실행한다. 실행은 전부 st.session_state 예약값 쓰기 → rerun 이다
  (Streamlit 은 위젯 생성 후 그 key 를 바꾸면 예외를 던지므로).
"""

from __future__ import annotations

import logging
import re

OPS_AGENT_VERSION = "v2"

log = logging.getLogger("ops_agent")

# ops_dashboard.TAB_ORDER 의 키와 일치해야 한다
TAB_KEYS = ["ai", "triage", "live", "shift", "log", "fp", "tune", "diag"]
DET_TAB_KEYS = ["dataset", "manual", "test", "train", "synthetic", "folder"]
SCOPE_KEYS = ["all_both", "all_fraud"] + list("abcdefghijkl") + ["m"]

# ── 이산 위젯의 허용값 ─────────────────────────────────────
#   ⚠ select_slider 는 목록에 **없는 값**을 세션에 넣으면 ops_dashboard 의
#     방어 코드가 조용히 pop 해 버린다(구버전 값 정리용). 즉 액션은 "성공했다"고
#     말하는데 화면은 그대로다 — sort_queue 가 정확히 그 방식으로 죽어 있었다.
#     그래서 자유 숫자가 아니라 **화면과 똑같은 목록**을 enum 으로 못 박는다.
WINDOW_OPTS = ["24", "72", "168", "720", "2160"]      # ops_dashboard: common.window
QUEUE_LIMITS = ["10", "20", "30", "50"]               # ops_dashboard: tri_n
LOG_LIMITS = ["25", "50", "100", "200"]               # ops_dashboard: log_n
FP_DIMS = ["fraud_type", "score_bucket", "tier", "model", "reviewer"]
ONOFF = ["on", "off"]

TAB_HUMAN = {
    "ai": "AI 분석·알림", "triage": "알림 트리아지", "live": "실시간 감시",
    "shift": "교대 인수인계", "log": "탐지 로그", "fp": "오탐 분석",
    "tune": "임계값 튜닝", "diag": "진단",
}


# ══════════════════════════════════════════════════════════
# 액션 레지스트리
# ══════════════════════════════════════════════════════════
ACTIONS: dict[str, dict] = {
    "goto_tab": {
        "kind": "enum", "values": TAB_KEYS,
        "example": "goto_tab(triage)",
        "label": {
            "ko": "탭 이동. ai=AI분석, triage=알림 트리아지, live=실시간 감시, "
                  "shift=교대 인수인계, log=탐지 로그, fp=오탐 분석, tune=임계값 튜닝, diag=진단",
            "en": "Switch tab. ai/triage/live/shift/log/fp/tune/diag",
            "ja": "タブ移動。ai/triage/live/shift/log/fp/tune/diag",
            "zh": "切换标签页。ai/triage/live/shift/log/fp/tune/diag",
        },
    },
    "goto_input_tab": {
        "kind": "enum", "values": DET_TAB_KEYS,
        "example": "goto_input_tab(dataset)",
        "label": {
            "ko": "AI 분석 안의 '탐지 입력' 방식 전환. dataset=선택 데이터셋, manual=직접입력, "
                  "test=test.csv, train=train.csv, synthetic=합성생성, folder=폴더배치",
            "en": "Switch detection input mode. dataset/manual/test/train/synthetic/folder",
            "ja": "検知入力の方式を切替。dataset/manual/test/train/synthetic/folder",
            "zh": "切换检测输入方式。dataset/manual/test/train/synthetic/folder",
        },
    },
    "set_scope": {
        "kind": "enum", "values": SCOPE_KEYS,
        "example": "set_scope(all_fraud)",
        "label": {
            "ko": "선택 데이터셋의 추출 범위. all_both=전체, all_fraud=사기 전체, m=정상만, "
                  "a~l=개별 사기 유형",
            "en": "Extraction scope. all_both / all_fraud / m / a-l",
            "ja": "抽出範囲。all_both / all_fraud / m / a〜l",
            "zh": "抽取范围。all_both / all_fraud / m / a-l",
        },
    },
    "set_threshold": {
        "kind": "float", "min": 0.0, "max": 1.0,
        "example": "set_threshold(0.7)",
        "label": {
            "ko": "위험점수 임계값 변경 (0~1). 되돌릴 수 있는 설정이라 바로 적용된다",
            "en": "Set risk threshold (0-1).",
            "ja": "リスク閾値を変更 (0〜1)。",
            "zh": "设置风险阈值 (0-1)。",
        },
    },
    "set_sla": {
        "kind": "int", "min": 5, "max": 480,
        "example": "set_sla(30)",
        "label": {
            "ko": "SLA(분) 변경 — 알림 발생 후 판정까지의 목표 시간",
            "en": "Set SLA minutes.",
            "ja": "SLA(分)を変更。",
            "zh": "设置SLA(分钟)。",
        },
    },
    "sort_queue": {
        "kind": "enum", "values": ["wait", "score"],
        "example": "sort_queue(wait)",
        "label": {
            "ko": "트리아지 정렬. wait=대기 오래된 순(기본), score=위험점수 순",
            "en": "Sort triage queue. wait / score",
            "ja": "トリアージ並び替え。wait / score",
            "zh": "分诊队列排序。wait / score",
        },
    },
    "select_pending": {
        "kind": "enum", "values": ["all", "over", "none"],
        "example": "select_pending(over)",
        "label": {
            "ko": "트리아지 일괄 선택. all=표시된 전체, over=SLA 초과만, none=해제. "
                  "선택만 하고 판정은 하지 않는다 — 저장 버튼은 사람이 누른다",
            "en": "Bulk-select triage rows. all / over / none (selection only, no verdict)",
            "ja": "トリアージ一括選択。all / over / none(選択のみ・判定はしない)",
            "zh": "批量选择分诊行。all / over / none(仅选择，不判定)",
        },
    },
    "show_summary": {
        "kind": "enum", "values": ["queue", "shift", "fp", "watcher"],
        "example": "show_summary(shift)",
        "label": {
            "ko": "요약 표시. queue=대기 현황·SLA, shift=근무 요약, fp=오탐 통계, watcher=워처 상태. "
                  "답변에 수치를 함께 설명하라",
            "en": "Show summary. queue / shift / fp / watcher",
            "ja": "サマリ表示。queue / shift / fp / watcher",
            "zh": "显示摘要。queue / shift / fp / watcher",
        },
    },
    "open_guide": {
        "kind": "none",
        "example": "open_guide()",
        "label": {
            "ko": "사용 안내(온보딩) 다시 열기",
            "en": "Reopen the usage guide.",
            "ja": "使い方ガイドを再表示。",
            "zh": "重新打开使用指南。",
        },
    },

    # ══ v2 추가 ═══════════════════════════════════════════
    # 화면에 조작 위젯이 분명히 있는데 챗봇만 손을 못 대던 것들을 채운다.
    # 전부 되돌릴 수 있는 표시 설정이거나(필터·기간·정렬), 밖으로 아무것도
    # 내보내지 않는 실행이다(run_*).
    "set_window": {
        "kind": "enum", "values": WINDOW_OPTS,
        "example": "set_window(168)",
        "label": {
            "ko": "분석 기간(시간). 24=1일, 72=3일, 168=7일, 720=30일, 2160=90일. "
                  "오탐 분석·판정 이력 요약이 이 값을 쓴다",
            "en": "Analysis window in hours. 24/72/168/720/2160",
            "ja": "分析期間(時間)。24/72/168/720/2160",
            "zh": "分析时间窗(小时)。24/72/168/720/2160",
        },
    },
    "set_min_score": {
        "kind": "float", "min": 0.0, "max": 1.0,
        "example": "set_min_score(0.5)",
        "label": {
            "ko": "트리아지 목록의 최소 위험도 필터 (0~1). 낮은 점수 건을 화면에서 감춘다",
            "en": "Minimum risk score filter for the triage list (0-1).",
            "ja": "トリアージ一覧の最小リスクフィルタ (0〜1)。",
            "zh": "分诊列表最小风险分过滤 (0-1)。",
        },
    },
    "set_queue_limit": {
        "kind": "enum", "values": QUEUE_LIMITS,
        "example": "set_queue_limit(50)",
        "label": {
            "ko": "트리아지에 한 번에 표시할 건수. 10/20/30/50 중 하나",
            "en": "Triage rows to show at once. 10/20/30/50",
            "ja": "トリアージ表示件数。10/20/30/50",
            "zh": "分诊显示条数。10/20/30/50",
        },
    },
    "set_only_new": {
        "kind": "enum", "values": ONOFF,
        "example": "set_only_new(off)",
        "label": {
            "ko": "트리아지 '미판정만 보기' 필터. off 로 두면 이미 판정한 건도 함께 보인다",
            "en": "Triage 'unreviewed only' filter. on/off",
            "ja": "トリアージ「未判定のみ」フィルタ。on/off",
            "zh": "分诊「仅未判定」过滤。on/off",
        },
    },
    "set_sort_dir": {
        "kind": "enum", "values": ["desc", "asc"],
        "example": "set_sort_dir(desc)",
        "label": {
            "ko": "트리아지 정렬 방향. desc=큰 값(오래 기다린/위험한) 먼저, asc=반대",
            "en": "Triage sort direction. desc / asc",
            "ja": "トリアージ並び順。desc / asc",
            "zh": "分诊排序方向。desc / asc",
        },
    },
    "search_log": {
        "kind": "text", "max_len": 80,
        "example": "search_log(T20250810)",
        "label": {
            "ko": "탐지 로그 검색 — 거래 ID·유형 등으로 찾는다. 검색어를 비우려면 "
                  "search_log() 처럼 인자 없이 부른다. 자동으로 탐지 로그 탭으로 이동한다",
            "en": "Search the detection log (empty arg clears the query).",
            "ja": "検知ログを検索(引数なしで解除)。",
            "zh": "搜索检测日志(空参数清除)。",
        },
    },
    "set_log_limit": {
        "kind": "enum", "values": LOG_LIMITS,
        "example": "set_log_limit(100)",
        "label": {
            "ko": "탐지 로그 표시 건수. 25/50/100/200 중 하나",
            "en": "Detection log rows. 25/50/100/200",
            "ja": "検知ログ表示件数。25/50/100/200",
            "zh": "检测日志显示条数。25/50/100/200",
        },
    },
    "set_log_anomaly_only": {
        "kind": "enum", "values": ONOFF,
        "example": "set_log_anomaly_only(off)",
        "label": {
            "ko": "탐지 로그 '이상거래만' 필터. off 로 두면 정상 판정 건까지 전부 보인다",
            "en": "Detection log 'anomalies only' filter. on/off",
            "ja": "検知ログ「異常のみ」フィルタ。on/off",
            "zh": "检测日志「仅异常」过滤。on/off",
        },
    },
    "set_fp_dim": {
        "kind": "enum", "values": FP_DIMS,
        "example": "set_fp_dim(reviewer)",
        "label": {
            "ko": "오탐 분석의 집계 기준. fraud_type=사기유형, score_bucket=점수구간, "
                  "tier=경보등급, model=모델, reviewer=판정자",
            "en": "False-positive breakdown dimension. fraud_type/score_bucket/tier/model/reviewer",
            "ja": "誤検知分析の集計軸。fraud_type/score_bucket/tier/model/reviewer",
            "zh": "误报分析维度。fraud_type/score_bucket/tier/model/reviewer",
        },
    },
    "set_auto_refresh": {
        "kind": "enum", "values": ONOFF,
        "example": "set_auto_refresh(on)",
        "label": {
            "ko": "실시간 감시 탭의 자동 새로고침 on/off",
            "en": "Toggle live-monitor auto refresh. on/off",
            "ja": "リアルタイム監視の自動更新。on/off",
            "zh": "实时监控自动刷新。on/off",
        },
    },
    "set_refresh_sec": {
        "kind": "int", "min": 1, "max": 60,
        "example": "set_refresh_sec(5)",
        "label": {
            "ko": "자동 새로고침 주기(초, 1~60)",
            "en": "Auto-refresh interval in seconds (1-60).",
            "ja": "自動更新の間隔(秒, 1〜60)。",
            "zh": "自动刷新间隔(秒, 1-60)。",
        },
    },
    "set_compact_tabs": {
        "kind": "enum", "values": ONOFF,
        "example": "set_compact_tabs(on)",
        "label": {
            "ko": "탭 라벨 압축 모드 — 좁은 화면에서 탭바가 잘릴 때 켠다",
            "en": "Compact tab labels for narrow screens. on/off",
            "ja": "タブラベル圧縮モード。on/off",
            "zh": "标签页标签压缩模式。on/off",
        },
    },
    "open_keymap": {
        "kind": "none",
        "example": "open_keymap()",
        "label": {
            "ko": "키보드 단축키 모음 열기",
            "en": "Open the keyboard shortcut list.",
            "ja": "キーボードショートカット一覧を開く。",
            "zh": "打开键盘快捷键列表。",
        },
    },
    "run_ai_analysis": {
        "kind": "none",
        "example": "run_ai_analysis()",
        "label": {
            "ko": "선택된 건에 대해 AI 분석을 지금 실행한다. 결과를 화면에 띄울 뿐 "
                  "발송은 하지 않는다 — 발송은 사람이 따로 누른다. 로컬 모델이면 수십 초 걸린다",
            "en": "Run AI analysis on the selected case now (no sending).",
            "ja": "選択中の件をAI分析する(送信はしない)。",
            "zh": "对所选案件执行AI分析(不发送)。",
        },
    },
    "run_batch": {
        "kind": "none",
        "example": "run_batch()",
        "label": {
            "ko": "일괄 분석을 지금 실행한다. 결과 보고서를 화면에 만들 뿐 발송은 하지 않는다",
            "en": "Run batch analysis now (report on screen only, no sending).",
            "ja": "一括分析を実行する(送信はしない)。",
            "zh": "立即执行批量分析(仅生成报告，不发送)。",
        },
    },
    "set_batch_window": {
        "kind": "int", "min": 1, "max": 720,
        "example": "set_batch_window(24)",
        "label": {
            "ko": "일괄 분석이 훑을 기간(시간, 1~720)",
            "en": "Batch analysis window in hours (1-720).",
            "ja": "一括分析の対象期間(時間, 1〜720)。",
            "zh": "批量分析时间窗(小时, 1-720)。",
        },
    },
}

_HEADER = {
    # 로컬 모델의 준수율을 올리려면 '규칙'보다 **형식 예시**가 효과적이다.
    #   맞는 예/틀린 예를 같이 주면 표기 흔들림이 눈에 띄게 준다.
    "ko": ("\n\n[사용 가능한 동작]\n"
           "요청이 화면 조작이면 답변 **맨 끝 줄**에 마커를 정확히 한 줄 덧붙여라.\n"
           "형식: [[ACTION: 이름(인자)]]   ← 대괄호 두 겹, 콜론 뒤 한 칸\n"
           "  올바른 예: 트리아지로 이동하겠습니다.\n"
           "            [[ACTION: goto_tab(triage)]]\n"
           "  잘못된 예: [ACTION goto_tab triage]  ·  「goto_tab 실행」  ·  마커 없이 말만 하기\n"
           "설명만 요구하면 붙이지 마라. 목록에 없는 동작은 만들지 마라.\n"
           "⚠ 알림 발송·판정 기록·워처 제어·경보 등급 임계값 저장은 네가 할 수 없다 — "
           "사람이 버튼을 눌러야 한다고 안내하라.\n"
           "   (분석 실행 run_ai_analysis·run_batch 는 할 수 있다. 결과를 화면에 띄울 뿐 "
           "발송은 아니기 때문이다.)\n"),
    "en": ("\n\n[Available actions]\n"
           "If the request is a UI operation, append exactly one [[ACTION: name(arg)]] line.\n"
           "Do not invent actions. You cannot send alerts, record verdicts, control the watcher,\n"
           "or save alert-tier thresholds. You may run analysis (results stay on screen).\n"),
    "ja": ("\n\n[利用可能な操作]\n"
           "画面操作の依頼なら [[ACTION: 名前(引数)]] を1行だけ付けろ。\n"
           "通知送信・判定記録・ワッチャー制御・警報閾値の保存はできない。\n"
           "分析の実行は可能(結果は画面に表示するだけ)。\n"),
    "zh": ("\n\n[可用操作]\n"
           "若为界面操作请求，请附加一行 [[ACTION: 名称(参数)]]。\n"
           "你不能发送告警、记录判定、控制监视器或保存告警阈值。\n"
           "可以执行分析(结果仅显示在屏幕上)。\n"),
}

# ── 마커 인식 ──────────────────────────────────────────────
#
# 🐛 준수율 문제 — 로컬 모델은 형식을 **조금씩** 틀린다
#   26B 로컬 모델(Gemma 계열)은 지시를 따르려 하지만 표기가 흔들린다. 실제로
#   관측되는 변형들:
#       [ACTION: goto_tab(triage)]        괄호 한 겹
#       [[action: goto_tab(triage)]]      소문자 (IGNORECASE 로 이미 처리)
#       [[ACTION: goto_tab (triage)]]     이름과 괄호 사이 공백
#       ```\n[[ACTION: goto_tab(triage)]]\n```   코드펜스로 감쌈
#       **[[ACTION: goto_tab(triage)]]**  굵게 강조
#   전부 '무엇을 하려는지'는 명확한데 형식만 어긋난 경우다. 이런 것까지 버리면
#   담당자 눈에는 "챗봇이 말만 하고 안 움직인다"로 보인다.
#
# ⚠️ 관용은 **형식에만** 적용한다. 자연어에서 의도를 추론하지는 않는다 —
#   "오탐으로 찍어줘"와 "오탐이면 어떻게 돼?"를 구분할 수 없기 때문이고,
#   그래서 발송·판정·워처 제어는 애초에 레지스트리에 없다(모듈 상단 주석).
#   여기서 늘리는 것은 '알아듣는 표기의 폭'이지 '할 수 있는 일'이 아니다.
_RE = re.compile(
    r"\[{1,2}\s*ACTION\s*[:：]\s*(\w+)\s*\(([^)]*)\)\s*\]{1,2}", re.IGNORECASE)


def actions_prompt(lang: str = "ko") -> str:
    lang = lang if lang in _HEADER else "ko"
    lines = "\n".join(
        f" - {name}: {meta['label'].get(lang, meta['label']['ko'])}"
        f"  예) [[ACTION: {meta['example']}]]"
        for name, meta in ACTIONS.items())
    return _HEADER[lang] + lines


def parse(text: str):
    """응답에서 [[ACTION: …]] 파싱·검증 → (마커 제거 텍스트, [검증된 액션]).
    화이트리스트에 없거나 인자 검증에 실패하면 **조용히 버린다**(안전)."""
    if not text:
        return text, []
    acts = []
    for m in _RE.finditer(text):
        name, raw = m.group(1), m.group(2).strip()
        meta = ACTIONS.get(name)
        if not meta:
            continue
        kind = meta["kind"]
        try:
            if kind == "enum":
                v = raw.strip("'\"").lower()
                if v in meta["values"]:
                    acts.append({"name": name, "arg": v})
            elif kind == "float":
                v = float(raw.strip("'\"").rstrip("%"))
                if 1.0 < v <= 100.0:            # "70%" 관용 처리
                    v /= 100.0
                if meta["min"] <= v <= meta["max"]:
                    acts.append({"name": name, "arg": round(v, 4)})
            elif kind == "int":
                v = int(float(raw.strip("'\"")))
                if meta["min"] <= v <= meta["max"]:
                    acts.append({"name": name, "arg": v})
            elif kind == "text":
                # 검색어. 인자 없이 부르면(빈 문자열) '검색 해제'가 정상 의도다.
                #   따옴표·괄호만 벗기고 길이만 자른다 — 내용은 해석하지 않는다.
                v = raw.strip().strip("'\"")[: meta.get("max_len", 80)]
                acts.append({"name": name, "arg": v})
            elif kind == "none":
                acts.append({"name": name, "arg": None})
        except (ValueError, TypeError):
            continue
    return _RE.sub("", text).strip(), acts


# ══════════════════════════════════════════════════════════
# 실행
# ══════════════════════════════════════════════════════════
def apply(actions: list, ss, queue: list | None = None) -> list[str]:
    """검증된 액션을 st.session_state 에 반영하고, 사용자에게 보일 메모를 돌려준다.

    ⚠️ 위젯 key 를 **직접** 쓰지 않고 `_pending_*` 예약값을 쓰는 경우가 있다.
       Streamlit 은 위젯이 이미 만들어진 뒤 그 key 를 바꾸면 예외를 던지기 때문이다.
       예약값은 해당 위젯 생성 직전에 소비된다.

    queue: 트리아지 큐(선택). select_pending 이 대상 ID 를 뽑는 데 쓴다.
    """
    notes = []
    for a in actions or []:
        name, arg = a.get("name"), a.get("arg")
        try:
            if name == "goto_tab":
                ss["_force_tab"] = arg
                notes.append(f"➡ '{TAB_HUMAN.get(arg, arg)}' 탭으로 이동했습니다")

            elif name == "goto_input_tab":
                ss["_force_tab"] = "ai"
                ss["_force_det_tab"] = arg
                notes.append(f"➡ 탐지 입력 방식을 '{arg}' 로 바꿨습니다")

            elif name == "set_scope":
                ss["_pending_scope"] = arg          # 위젯 생성 직전에 소비
                ss["_force_tab"] = "ai"
                ss["_force_det_tab"] = "dataset"
                notes.append(f"🎯 추출 범위를 '{arg}' 로 설정했습니다")

            elif name == "set_threshold":
                ss["_pending_threshold"] = float(arg)
                notes.append(f"🎯 임계값을 {float(arg):.2f} 로 바꿨습니다")

            elif name == "set_sla":
                # ⚠ `ss["sla_min"] = …` 로 직접 쓰면 안 된다. sla_min 은 사이드바
                #   위젯 key 이고, 사이드바는 챗 처리보다 **먼저** 그려진다 —
                #   이미 만들어진 위젯의 key 를 고치는 셈이라 Streamlit 이 예외를
                #   던지고, 그 예외가 아래 except 에 먹혀 "바꿨습니다" 메모조차
                #   안 나온 채 조용히 실패했다. 바로 위 set_threshold 와 같은
                #   예약값 패턴으로 통일한다(사이드바가 위젯 생성 직전에 소비).
                ss["_pending_sla"] = int(arg)
                notes.append(f"⏱ SLA를 {int(arg)}분으로 바꿨습니다")

            elif name == "sort_queue":
                # 🐛 FIX(v2): 예전엔 "대기순"/"점수순"이라는 **한국어 표시 문구**를
                #   넣었다. 그런데 위젯(ops_dashboard `tri_sort`)의 실제 옵션은
                #   ["age","score"] 이고, 바로 위에 "목록에 없는 값이면 pop"
                #   하는 구버전 값 정리 코드가 있다. 결과적으로 이 액션은
                #   **매번 조용히 버려졌다** — 챗봇은 "정렬을 바꿨습니다"라고
                #   답하는데 화면은 그대로. 위젯 옵션값을 그대로 쓴다.
                ss["tri_sort"] = "age" if arg == "wait" else "score"
                ss["_force_tab"] = "triage"
                notes.append("↕ 트리아지 정렬을 "
                             f"'{'대기 오래된 순' if arg == 'wait' else '위험점수 순'}'으로 바꿨습니다")

            # ── v2: 표시 설정 ────────────────────────────────
            elif name == "set_window":
                ss["window_h"] = int(arg)
                _h = int(arg)
                notes.append(f"📅 분석 기간을 {_h // 24}일({_h}시간)로 바꿨습니다"
                             if _h >= 24 else f"📅 분석 기간을 {_h}시간으로 바꿨습니다")

            elif name == "set_min_score":
                ss["tri_min"] = float(arg)
                ss["_force_tab"] = "triage"
                notes.append(f"🔎 최소 위험도 필터를 {float(arg):.2f} 로 바꿨습니다")

            elif name == "set_queue_limit":
                ss["tri_n"] = int(arg)
                ss["_force_tab"] = "triage"
                notes.append(f"📋 트리아지 표시 건수를 {int(arg)}건으로 바꿨습니다")

            elif name == "set_only_new":
                ss["tri_only_new"] = (arg == "on")
                ss["_force_tab"] = "triage"
                notes.append("🆕 '미판정만 보기'를 "
                             f"{'켰습니다' if arg == 'on' else '껐습니다 — 판정 완료 건도 함께 보입니다'}")

            elif name == "set_sort_dir":
                ss["tri_sort_desc"] = (arg == "desc")
                ss["_force_tab"] = "triage"
                notes.append(f"↕ 정렬 방향을 {'내림차순' if arg == 'desc' else '오름차순'}으로 바꿨습니다")

            elif name == "search_log":
                ss["log_q"] = arg or ""
                ss["_force_tab"] = "log"
                notes.append(f"🔍 탐지 로그에서 '{arg}' 를 검색합니다" if arg
                             else "🔍 탐지 로그 검색어를 해제했습니다")

            elif name == "set_log_limit":
                ss["log_n"] = int(arg)
                ss["_force_tab"] = "log"
                notes.append(f"📜 탐지 로그 표시 건수를 {int(arg)}건으로 바꿨습니다")

            elif name == "set_log_anomaly_only":
                ss["log_anom"] = (arg == "on")
                ss["_force_tab"] = "log"
                notes.append("⚠ '이상거래만 보기'를 "
                             f"{'켰습니다' if arg == 'on' else '껐습니다 — 정상 건도 함께 보입니다'}")

            elif name == "set_fp_dim":
                ss["fp_dim"] = arg
                ss["_force_tab"] = "fp"
                notes.append(f"📊 오탐 분석 집계 기준을 '{arg}' 로 바꿨습니다")

            elif name == "set_auto_refresh":
                ss["auto_refresh"] = (arg == "on")
                ss["_force_tab"] = "live"
                notes.append(f"🔄 자동 새로고침을 {'켰습니다' if arg == 'on' else '껐습니다'}")

            elif name == "set_refresh_sec":
                ss["_refresh_sec"] = int(arg)
                ss["_force_tab"] = "live"
                notes.append(f"⏲ 자동 새로고침 주기를 {int(arg)}초로 바꿨습니다")

            elif name == "set_compact_tabs":
                ss["ops_tab_compact"] = (arg == "on")
                notes.append(f"🗜 탭 라벨 압축을 {'켰습니다' if arg == 'on' else '껐습니다'}")

            elif name == "open_keymap":
                ss["_ops_keymap_open"] = True
                notes.append("⌨ 단축키 모음을 엽니다")

            # ── v2: 실행형 ───────────────────────────────────
            #   ⚠ 버튼은 세션 상태로 누를 수 없다(위젯 반환값이라 쓰기 불가).
            #     예약 플래그를 두고, 버튼 자리에서 `버튼 or 플래그` 로 받는다.
            elif name == "run_ai_analysis":
                ss["_pending_ai_run"] = True
                ss["_force_tab"] = "ai"
                notes.append("🧠 AI 분석을 실행합니다 — 로컬 모델이면 수십 초 걸립니다. "
                             "발송은 결과를 보고 직접 눌러 주세요")

            elif name == "run_batch":
                ss["_pending_batch_run"] = True
                ss["_force_tab"] = "ai"
                notes.append("📦 일괄 분석을 실행합니다 — 결과 보고서는 화면에만 만들어집니다")

            elif name == "set_batch_window":
                ss["batch_window_h"] = int(arg)
                ss["_force_tab"] = "ai"
                notes.append(f"📦 일괄 분석 대상 기간을 {int(arg)}시간으로 바꿨습니다")

            elif name == "select_pending":
                ids = set()
                if arg == "all":
                    ids = {r["txn_id"] for r in (queue or [])}
                elif arg == "over":
                    ids = {r["txn_id"] for r in (queue or [])
                           if r.get("urgency") == "over"}
                ss["tri_bulk_sel"] = ids
                ss["_force_tab"] = "triage"
                notes.append(f"☑️ {len(ids)}건을 선택했습니다 — "
                             f"판정은 '선택한 N건 일괄 판정' 버튼을 눌러 주세요")

            elif name == "show_summary":
                ss["_force_tab"] = {"queue": "triage", "shift": "shift",
                                    "fp": "fp", "watcher": "live"}.get(arg, "triage")
                notes.append("📊 해당 화면으로 이동했습니다")

            elif name == "open_guide":
                ss["_ops_guide_open"] = True
                notes.append("🎓 사용 안내를 엽니다")
        except Exception as e:                          # pragma: no cover
            log.warning(f"액션 실행 실패({name}): {e}")
    return notes

"""
ops_guide — 첫 실행 온보딩 · 사용 안내

dashboard.py 의 온보딩(2944~3031행)과 같은 구조를 관제용으로 다시 만든 것이다.
왜 그대로 못 쓰는가: 저쪽은 '세션 1~5'를 설명하고 beginner_mode·session_idx 를
건드린다 — ops 에는 그런 상태가 없고, 설명해야 할 것도 완전히 다르다.

설계 의도
  · 처음 여는 사람이 **3분 안에** 무엇부터 눌러야 하는지 알게 한다.
    관제 도구는 급할 때 처음 열리는 경우가 많다.
  · 한 번 보면 다시 안 뜬다(.ops_onboarded 마커). 대신 사이드바에서 언제든 다시 부른다.
  · st.dialog 이 없거나 다른 모달과 충돌하면 인라인 카드로 폴백한다 —
    안내가 안 떠서 앱을 못 쓰는 상황만은 피한다.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import streamlit as st

OPS_GUIDE_VERSION = "v3"

log = logging.getLogger("ops_guide")

MARK_FILE = Path(".ops_onboarded")
MANUAL_FILE = "ops_dashboard_사용설명서.md"


def _is_shared_deploy() -> bool:
    """여러 사람이 같은 컨테이너를 공유하는 배포 환경인가.

    dashboard.py 에 같은 함수가 있다 — 두 앱이 서로를 import 하지 않으므로 각자 둔다.

    Streamlit Cloud 는 저장소를 /mount/src/<repo> 에 마운트한다(구버전은 /app).
    로컬에는 그런 경로가 없다. 판별이 빗나갈 때를 대비해 환경변수로도 강제할 수 있다.
    """
    if os.getenv("FDS_SHARED_DEPLOY", "") == "1":
        return True
    try:
        here = str(Path(__file__).resolve()).replace("\\", "/")
        return here.startswith("/mount/src") or here.startswith("/app/")
    except Exception:
        return False


#  🐛 FIX — 배포본에서는 파일 마커를 쓰지 않는다.
#    마커 파일은 "내 PC 에서 한 번 봤다"는 뜻인데, Streamlit Cloud 는 컨테이너 하나를
#    모든 방문자가 공유한다. 그래서 첫 방문자가 안내를 여는 순간 파일이 생기고,
#    그 뒤로는 링크를 받은 누구도 안내를 못 본다. 공유 배포에서는 세션 상태만 본다.
SHARED_DEPLOY = _is_shared_deploy()

# (아이콘, 탭 이름, 색 키, 한 줄 설명)
TAB_GUIDE = [
    ("🧠", "AI 분석·알림", "accent",
     "**첫 화면입니다.** 데이터를 넣어 즉석에서 탐지하고, LLM 해설·Slack/Email 초안까지 만듭니다. "
     "추출 범위(전체/사기 전체/개별 유형)를 고르고 `CSV 저장·inbox 전송·탐지·일괄 분석`을 바로 실행합니다."),
    ("🚨", "알림 트리아지", "red",
     "워처가 올린 알림을 정탐/오탐/미탐/보류로 찍습니다. 이 판정이 쌓여야 오탐 분석도 임계값 튜닝도 "
     "의미가 생깁니다. 체크박스로 **여러 건을 한 번에** 판정할 수도 있습니다."),
    ("🟢", "실시간 감시", "green",
     "워처가 살아 있는지, 새 경보가 들어오는지 보는 상황판입니다. "
     "경보음·데스크톱 알림 설정과 🩺 진단 버튼이 여기 있습니다."),
    ("🔄", "교대 인수인계", "blue",
     "근무를 **시작할 때** 앞사람이 남긴 메모를 읽고, **끝낼 때** 남길 것을 적습니다. "
     "근무 구간 요약(유입·판정·미처리·최장대기)이 자동으로 붙습니다."),
    ("🗃", "탐지 로그", "accent",
     "지난 탐지를 거래 ID로 찾아 **그때 그 데이터와 그때 그 AI 분석**을 그대로 봅니다. "
     "AI 분석 탭에서 직접 돌린 탐지도 여기 남습니다."),
    ("📉", "오탐 분석", "amber",
     "쌓인 판정으로 '무엇이 헛 알람이었나'를 셉니다. 오탐 사유별 분포를 보고 "
     "임계값을 올릴지 피처를 고칠지 정합니다."),
    ("⚙", "임계값 튜닝", "purple",
     "검증셋이 아니라 **담당자가 실제로 찍은 판정**으로 비용을 계산해 임계값을 추천합니다. "
     "운영 분포와 검증셋이 다르기 때문에 이 값이 진짜입니다."),
    ("🩺", "진단", "text_muted",
     "\"왜 알림이 안 오지?\"에 3초 안에 답합니다. ML·RAG·LLM·SMTP 연결을 각각 눌러 확인하고, "
     "나간 발송 기록(감사 로그)을 봅니다."),
]

QUICK_START = [
    ("1", "사이드바에서 **검토자 이름**을 내 이름으로 바꾸세요",
     "판정 기록·잠금·임시저장이 전부 이 이름으로 묶입니다. 여러 명이 같은 화면을 쓰면 필수입니다."),
    ("2", "화면을 **한 번 클릭**하세요 — 경보음이 켜집니다",
     "브라우저는 사용자가 페이지를 건드리기 전엔 소리를 막습니다. 아무 곳이나 클릭하면 자동으로 활성화됩니다."),
    ("3", "**🚨 알림 트리아지**에서 위에 있는 것부터 처리하세요",
     "기본 정렬이 '대기순'이라 가장 오래 방치된 건이 맨 위에 옵니다. 🔴는 SLA 초과입니다."),
]

TIPS = [
    "🔒 알림을 열어 입력을 시작하면 자동으로 **잠금**이 걸립니다 — 다른 담당자 화면에 "
    "'내가 검토 중'으로 표시돼 같은 건을 둘이 판정하는 사고를 막습니다 (15분 무응답 시 자동 해제).",
    "💾 판정·사유·메모는 입력하는 즉시 **DB에 임시저장**됩니다. 브라우저를 새로고침하거나 "
    "실수로 닫아도 그대로 남아 있습니다.",
    "☑️ 트리아지에서 체크박스로 여러 건을 고른 뒤 **한 번에 판정**할 수 있습니다 "
    "(모두 선택 / SLA 초과만 버튼 제공).",
    "⏱ 알림 옆 `⏱ 1시간 30분`은 **방치된 시간**입니다. 점수보다 이 값이 더 위험한 신호일 때가 많습니다.",
    "🔔 경보는 **기본 켜짐**입니다. 새 경보는 화면 맨 위에 뜨고 `확인하기`로 바로 이동합니다. "
    "윈도우 알림을 클릭하면 '탐지 로그'로 갑니다.",
    "🤖 사이드바의 **AI 어시스턴트** 토글을 켜면 어느 탭에 있든 챗봇에게 바로 묻고, "
    "\"오탐 분석 탭으로 가줘\" 같은 화면 조작도 시킬 수 있습니다.",
    "⚠️ 이 대시보드는 **워처가 도는 그 PC**에서 열어야 합니다. fds_results.db 가 로컬 파일이라 "
    "다른 서버에서는 워처 상태가 보이지 않습니다.",
]

# ══════════════════════════════════════════════════════════
# 다국어 본문
#
#   ⚠ 여기는 ops_ui 의 t() 를 쓰지 않는다. 안내문은 라벨이 아니라 **문단**이라
#     키 표에 넣으면 표가 문서로 부풀고 줄바꿈·강조가 뒤섞인다. 대신 언어별
#     한 벌을 두고 lang 으로 고른다.
#   ⚠ 한국어는 **위의 TAB_GUIDE/QUICK_START/TIPS 를 그대로 재사용**한다.
#     기존 문구를 이 dict 로 옮겨 적으면 옮겨 적는 순간 오타가 들어갈 수 있고,
#     확정된 한국어 화면이 흔들린다. 여기에는 다른 언어만 둔다.
# ══════════════════════════════════════════════════════════
_KO_LABELS = {
    "title": "🛡 FDS 관제 콘솔 — 사용 안내",
    "intro": "이 화면은 <b>무인 워처가 24시간 올리는 알림을 사람이 판정</b>하는 관제 "
             "도구입니다. 모델 성능을 보거나 합성 데이터를 만드는 일은 "
             "<code>dashboard.py</code>(분석용)에서 합니다.",
    "quick_h": "⚡ 처음 3분",
    "tabs_h": "🗂 탭 8개는 이런 순서입니다 (자주 쓰는 순)",
    "tips_h": "💡 알아두면 좋은 것",
    "reviewer_now": "현재 검토자 이름: **{who}**",
    "manual": "📖 더 자세한 내용은 프로젝트 폴더의 `{f}` 를 보세요.",
    "go": "🚨 트리아지로 시작",
    "close": "닫기",
}

_GUIDE_I18N = {
"en": {
 "title": "🛡 FDS Ops Console — Guide",
 "intro": "This screen is the ops tool where <b>a person judges the alerts an unattended watcher "
          "raises around the clock</b>. Model performance and synthetic data belong to "
          "<code>dashboard.py</code> (the analysis tool).",
 "quick_h": "⚡ Your first 3 minutes",
 "tabs_h": "🗂 The 8 tabs, in this order (most used first)",
 "tips_h": "💡 Worth knowing",
 "reviewer_now": "Current reviewer name: **{who}**",
 "manual": "📖 For more detail see `{f}` in the project folder.",
 "go": "🚨 Start with triage", "close": "Close",
 "quick": [
  ("1", "Change the **reviewer name** in the sidebar to your own",
   "Verdicts, locks and drafts are all keyed to this name. Essential when several people share one screen."),
  ("2", "**Click once** anywhere — this enables the alarm sound",
   "Browsers block audio until the user interacts with the page. Any click arms it automatically."),
  ("3", "Work top-down in **🚨 Triage**",
   "The default sort is by wait time, so the most neglected alert is at the top. 🔴 means past SLA."),
 ],
 "tabs": [
  ("🧠", "AI Analysis", "accent",
   "**The landing screen.** Feed in data to detect on the spot and produce an LLM explanation plus "
   "Slack/email drafts. Pick an extraction scope (all / all fraud / a single type) and run "
   "`Save CSV · Send to inbox · Detect · Batch analyze` directly."),
  ("🚨", "Triage", "red",
   "Mark the watcher's alerts as true/false positive, missed or unclear. Nothing downstream — FP "
   "analysis, threshold tuning — means anything until these accumulate. Checkboxes let you judge "
   "**many at once**."),
  ("🟢", "Live", "green",
   "The status board: is the watcher alive, are new alerts arriving. Alarm sound, desktop "
   "notification settings and the 🩺 diagnostics buttons live here."),
  ("🔄", "Shift handover", "blue",
   "**At the start** of a shift read what the previous person left; **at the end** write what you "
   "hand over. A summary of the window (arrived, judged, outstanding, longest wait) is attached "
   "automatically."),
  ("🗃", "Detection log", "accent",
   "Look up a past detection by transaction ID and see **the data as it was and the AI analysis as "
   "it was**. Detections you ran yourself on the AI tab show up here too."),
  ("📉", "FP analysis", "amber",
   "Count what turned out to be noise, using the verdicts you have collected. The breakdown by FP "
   "reason tells you whether to raise the threshold or fix a feature."),
  ("⚙", "Threshold", "purple",
   "Recommends a threshold from cost computed on **the verdicts your reviewers actually made**, not "
   "on a validation set. Production traffic differs from the validation set — that is why this one counts."),
  ("🩺", "Diagnostics", "text_muted",
   "Answers \"why am I not getting alerts?\" in three seconds. Test the ML, RAG, LLM and SMTP "
   "connections individually, and review everything that was sent (the audit log)."),
 ],
 "tips": [
  "🔒 Opening an alert and starting to type takes a **lock** — other reviewers see 'being reviewed', "
  "so two people never judge the same case (released automatically after 15 idle minutes).",
  "💾 Verdict, reason and memo are **drafted to the DB** as you type. Refresh or close the browser "
  "by accident and they are still there.",
  "☑️ In triage you can tick several alerts and **judge them together** (Select all / Over-SLA only).",
  "⏱ The `⏱ 1h 30m` next to an alert is **how long it has been sitting**. That is often a more "
  "dangerous signal than the score.",
  "🔔 Alarms are **on by default**. New alerts appear at the top of the screen with a Review button. "
  "Clicking the desktop notification takes you to the detection log.",
  "🤖 Turn on the **AI assistant** toggle in the sidebar to ask the chatbot from any tab — it can "
  "also drive the screen, e.g. \"take me to the FP analysis tab\".",
  "⚠️ Open this dashboard **on the machine the watcher runs on**. fds_results.db is a local file, so "
  "from another server you cannot see the watcher's state.",
 ],
},
"ja": {
 "title": "🛡 FDS 管制コンソール — 使い方",
 "intro": "この画面は<b>無人ウォッチャーが24時間上げるアラートを人が判定する</b>管制ツールです。"
          "モデル性能の確認や合成データの作成は<code>dashboard.py</code>（分析用）で行います。",
 "quick_h": "⚡ 最初の3分",
 "tabs_h": "🗂 タブ8つはこの順です（よく使う順）",
 "tips_h": "💡 知っておくとよいこと",
 "reviewer_now": "現在の検討者名: **{who}**",
 "manual": "📖 詳しくはプロジェクトフォルダの `{f}` を参照してください。",
 "go": "🚨 トリアージから始める", "close": "閉じる",
 "quick": [
  ("1", "サイドバーで**検討者名**を自分の名前に変更してください",
   "判定記録・ロック・一時保存がすべてこの名前で紐づきます。複数人で同じ画面を使う場合は必須です。"),
  ("2", "画面を**一度クリック**してください — アラート音が有効になります",
   "ブラウザはユーザーがページに触れるまで音をブロックします。どこでもクリックすれば自動的に有効化されます。"),
  ("3", "**🚨 トリアージ**で上から順に処理してください",
   "既定の並びが「待ち時間順」なので、最も放置された案件が一番上に来ます。🔴はSLA超過です。"),
 ],
 "tabs": [
  ("🧠", "AI分析・通知", "accent",
   "**最初の画面です。** データを入れてその場で検知し、LLM解説・Slack/Emailの下書きまで作ります。"
   "抽出範囲（全体/不正全体/個別種別）を選び、`CSV保存・inbox送信・検知・一括分析`をすぐ実行できます。"),
  ("🚨", "トリアージ", "red",
   "ウォッチャーが上げたアラートを正検知/誤検知/見逃し/保留で判定します。これが積み上がって初めて"
   "誤検知分析も閾値調整も意味を持ちます。チェックボックスで**複数件を一度に**判定できます。"),
  ("🟢", "リアルタイム監視", "green",
   "ウォッチャーが生きているか、新しいアラートが来ているかを見る状況板です。"
   "アラート音・デスクトップ通知の設定と🩺診断ボタンがここにあります。"),
  ("🔄", "シフト引継ぎ", "blue",
   "勤務の**開始時**に前任者のメモを読み、**終了時**に残すことを書きます。"
   "勤務区間のサマリー（流入・判定・未処理・最長待機）が自動で付きます。"),
  ("🗃", "検知ログ", "accent",
   "過去の検知を取引IDで探し、**当時のデータと当時のAI分析**をそのまま見ます。"
   "AI分析タブで自分が実行した検知もここに残ります。"),
  ("📉", "誤検知分析", "amber",
   "積み上がった判定から「何が無駄アラートだったか」を数えます。誤検知理由別の分布を見て、"
   "閾値を上げるか特徴量を直すかを決めます。"),
  ("⚙", "閾値調整", "purple",
   "検証セットではなく**担当者が実際に付けた判定**でコストを計算し、閾値を推奨します。"
   "運用分布と検証セットは異なるため、この値が本物です。"),
  ("🩺", "診断", "text_muted",
   "「なぜアラートが来ないのか」に3秒で答えます。ML・RAG・LLM・SMTPの接続を個別に確認し、"
   "送信済みの記録（監査ログ）を見ます。"),
 ],
 "tips": [
  "🔒 アラートを開いて入力を始めると自動的に**ロック**がかかります — 他の担当者の画面に"
  "「検討中」と表示され、同じ案件を二人で判定する事故を防ぎます（15分無応答で自動解除）。",
  "💾 判定・理由・メモは入力した時点で**DBに一時保存**されます。ブラウザを再読み込みしても"
  "誤って閉じてもそのまま残ります。",
  "☑️ トリアージではチェックボックスで複数件を選び**一括判定**できます（すべて選択 / SLA超過のみ）。",
  "⏱ アラート横の `⏱ 1時間30分` は**放置された時間**です。スコアよりこの値のほうが危険な信号のことが多いです。",
  "🔔 アラートは**既定でオン**です。新しいアラートは画面上部に出て「確認する」ですぐ移動できます。"
  "デスクトップ通知をクリックすると「検知ログ」に移動します。",
  "🤖 サイドバーの**AIアシスタント**をオンにすると、どのタブにいてもチャットボットに質問でき、"
  "「誤検知分析タブに行って」のような画面操作も頼めます。",
  "⚠️ このダッシュボードは**ウォッチャーが動いているPC**で開いてください。fds_results.db は"
  "ローカルファイルのため、別サーバーからはウォッチャーの状態が見えません。",
 ],
},
"zh": {
 "title": "🛡 FDS 管制控制台 — 使用指南",
 "intro": "本界面是<b>由人来判定无人监视器全天候上报告警</b>的管制工具。"
          "查看模型性能或生成合成数据请使用<code>dashboard.py</code>（分析工具）。",
 "quick_h": "⚡ 最初 3 分钟",
 "tabs_h": "🗂 8 个标签页的顺序（按使用频率）",
 "tips_h": "💡 值得了解",
 "reviewer_now": "当前审核人姓名: **{who}**",
 "manual": "📖 更多细节请查看项目文件夹中的 `{f}`。",
 "go": "🚨 从分诊开始", "close": "关闭",
 "quick": [
  ("1", "在侧边栏把**审核人姓名**改成你自己的",
   "判定记录、锁定与暂存全部以此名字关联。多人共用同一界面时这是必需的。"),
  ("2", "**点击一次**画面 — 告警声会被启用",
   "浏览器在用户与页面交互前会拦截声音。点击任意位置即可自动启用。"),
  ("3", "在**🚨 告警分诊**中自上而下处理",
   "默认按等待时长排序，因此被搁置最久的排在最上面。🔴 表示已超出 SLA。"),
 ],
 "tabs": [
  ("🧠", "AI 分析与通知", "accent",
   "**这是首屏。** 输入数据即刻检测，并生成 LLM 解读与 Slack/邮件草稿。"
   "选择抽取范围（全部/全部欺诈/单一类型），可直接执行`保存CSV · 发送到inbox · 检测 · 批量分析`。"),
  ("🚨", "告警分诊", "red",
   "把监视器上报的告警判定为真报/误报/漏报/待定。只有这些判定积累起来，误报分析与阈值调优才有意义。"
   "用复选框可以**一次判定多条**。"),
  ("🟢", "实时监控", "green",
   "查看监视器是否存活、是否有新告警的状态板。告警声、桌面通知设置与 🩺 诊断按钮都在这里。"),
  ("🔄", "交接班", "blue",
   "**上班时**阅读上一班留下的备注，**下班时**写下要移交的内容。"
   "班次区间汇总（新增、判定、未处理、最长等待）会自动附上。"),
  ("🗃", "检测日志", "accent",
   "按交易ID查找过去的检测，原样查看**当时的数据与当时的 AI 分析**。"
   "你在 AI 分析标签页自行运行的检测也会留存在这里。"),
  ("📉", "误报分析", "amber",
   "用已积累的判定统计「什么是无效告警」。查看按误报原因的分布，决定是提高阈值还是修正特征。"),
  ("⚙", "阈值调优", "purple",
   "不是用验证集，而是用**审核人实际做出的判定**计算成本并推荐阈值。"
   "生产分布与验证集不同，因此这个数值才是真实的。"),
  ("🩺", "诊断", "text_muted",
   "三秒内回答「为什么收不到告警」。分别测试 ML、RAG、LLM、SMTP 连接，并查看已发出的记录（审计日志）。"),
 ],
 "tips": [
  "🔒 打开告警并开始输入会自动**锁定** — 其他审核人的界面会显示「正在审核」，"
  "防止两人判定同一条（15 分钟无响应后自动释放）。",
  "💾 判定、原因与备注在输入的同时就会**暂存到数据库**。刷新浏览器或误关闭后依然保留。",
  "☑️ 在分诊中可用复选框选中多条后**批量判定**（提供全选 / 仅超时按钮）。",
  "⏱ 告警旁的 `⏱ 1小时30分` 是**被搁置的时长**。它往往比分数更危险。",
  "🔔 告警**默认开启**。新告警会出现在界面顶部，点「查看」即可跳转。"
  "点击桌面通知会进入「检测日志」。",
  "🤖 打开侧边栏的 **AI 助手** 开关后，在任意标签页都能直接向聊天机器人提问，"
  "还能让它操作界面，例如「带我去误报分析标签页」。",
  "⚠️ 请在**运行监视器的那台机器**上打开本仪表板。fds_results.db 是本地文件，"
  "从其他服务器看不到监视器状态。",
 ],
},
}


def _g(lang: str) -> dict:
    """언어별 안내 본문. 한국어는 기존 상수를 그대로 쓰고, 모르는 언어는 한국어로 폴백."""
    ko = {**_KO_LABELS, "quick": QUICK_START, "tabs": TAB_GUIDE, "tips": TIPS}
    return {**ko, **_GUIDE_I18N.get(lang, {})}


# ══════════════════════════════════════════════════════════
# 마커 — 한 번 보면 다시 뜨지 않게
# ══════════════════════════════════════════════════════════
def seen() -> bool:
    if st.session_state.get("_ops_onboard_done"):
        return True
    if SHARED_DEPLOY:
        return False      # 공유 배포 — 방문자마다 새 세션이므로 한 번씩 보여 준다
    try:
        return MARK_FILE.exists()
    except Exception:
        return False


def mark():
    st.session_state["_ops_onboard_done"] = True
    if SHARED_DEPLOY:
        return            # 컨테이너를 공유하므로 디스크에 남기지 않는다
    try:
        MARK_FILE.write_text("1", encoding="utf-8")
    except Exception:
        pass          # 쓰기 권한이 없어도 세션 내에서는 다시 뜨지 않는다


# ══════════════════════════════════════════════════════════
# 본문
# ══════════════════════════════════════════════════════════
def _card(T: dict, icon: str, title: str, color: str, body: str):
    c = T.get(color, T["accent"])
    st.markdown(
        f'<div style="background:{T["bg_card"]};border:1px solid rgba({T["accent_rgb"]},.14);'
        f'border-left:3px solid {c};border-radius:9px;padding:9px 13px;margin-bottom:7px">'
        f'<div style="display:flex;align-items:baseline;gap:8px;margin-bottom:3px">'
        f'<span style="font-size:15px">{icon}</span>'
        f'<span style="color:{T["text_primary"]};font-weight:800;font-size:13px">{title}</span>'
        f'</div>'
        f'<div style="color:{T["text_secondary"]};font-size:11.5px;line-height:1.55">{body}</div>'
        f'</div>', unsafe_allow_html=True)


def render_body(T: dict, reviewer: str = "", lang: str = "ko"):
    G = _g(lang)
    st.markdown(
        f'<div style="font-size:13px;color:{T["text_secondary"]};line-height:1.6;'
        f'margin-bottom:10px">{G["intro"]}</div>', unsafe_allow_html=True)

    st.markdown(f'<div style="color:{T["accent"]};font-weight:800;font-size:12px;'
                f'margin:12px 0 6px">{G["quick_h"]}</div>', unsafe_allow_html=True)
    for n, title, body in G["quick"]:
        st.markdown(
            f'<div style="display:flex;gap:9px;margin-bottom:6px">'
            f'<span style="min-width:19px;height:19px;border-radius:50%;background:{T["accent"]};'
            f'color:{T["bg_base"]};font-size:11px;font-weight:800;display:flex;'
            f'align-items:center;justify-content:center">{n}</span>'
            f'<div><div style="color:{T["text_primary"]};font-size:12.5px">{title}</div>'
            f'<div style="color:{T["text_muted"]};font-size:11px;line-height:1.5">{body}</div>'
            f'</div></div>', unsafe_allow_html=True)
    if reviewer:
        st.caption(G["reviewer_now"].format(who=reviewer))

    st.markdown(f'<div style="color:{T["accent"]};font-weight:800;font-size:12px;'
                f'margin:14px 0 6px">{G["tabs_h"]}</div>',
                unsafe_allow_html=True)
    for icon, title, color, body in G["tabs"]:
        _card(T, icon, title, color, body)

    st.markdown(f'<div style="background:rgba({T["accent_rgb"]},.08);'
                f'border:1px solid rgba({T["accent_rgb"]},.33);border-radius:9px;'
                f'padding:10px 13px;margin-top:8px">'
                f'<div style="color:{T["accent"]};font-weight:800;font-size:12px;'
                f'margin-bottom:6px">{G["tips_h"]}</div>'
                + "".join(
                    f'<div style="color:{T["text_secondary"]};font-size:11.5px;'
                    f'line-height:1.65;margin-bottom:4px">· {x}</div>' for x in G["tips"])
                + '</div>', unsafe_allow_html=True)

    if Path(MANUAL_FILE).exists():
        st.caption(G["manual"].format(f=MANUAL_FILE))


def _go_triage():          # (구 API 호환용 · 현재 미사용)
    st.session_state["_force_tab"] = "triage"
    mark()


OPEN_KEY = "_ops_guide_showing"


def _actions(lang: str = "ko") -> bool:
    """버튼 2개. 눌렸으면 True (호출부가 닫고 rerun 한다).

    🐛 FIX(v2) — 두 버튼이 먹통이던 진짜 이유
      예전 구현은 안내를 띄우는 **그 순간** '봤음'으로 확정해 버렸다. 그래서
      버튼을 누른 뒤의 rerun 에서 maybe_show() 가 일찍 return 했고, 모달 본문이
      다시 실행되지 않았다. Streamlit 의 모달은 **매 rerun 마다 데코레이트된
      함수를 다시 호출해야** 열린 상태가 유지되는데 그러지 않으니
      ① 모달이 닫히고 ② 그 안의 위젯이 재생성되지 않아 클릭이 관측되지 않았다.
      on_click 콜백으로 바꿔도 마찬가지였다 — 닫힌 모달의 위젯은 이벤트를
      전달할 대상이 없다.

      → 해결: 열림 상태를 **세션 플래그(OPEN_KEY)로 유지**하고, 그 플래그가
        True 인 동안 매 rerun 마다 모달을 다시 그린다(= Streamlit 공식 패턴).
        버튼은 평범한 반환값 방식으로 돌아가고, 눌리면 플래그를 내려 닫는다.
    """
    G = _g(lang)
    a1, a2 = st.columns([1, 1])
    if a1.button(G["go"], type="primary", key="opsonb_go",
                 width="stretch"):
        st.session_state["_force_tab"] = "triage"
        return True
    if a2.button(G["close"], key="opsonb_close", width="stretch"):
        return True
    return False


# ══════════════════════════════════════════════════════════
# 진입점
# ══════════════════════════════════════════════════════════
_DLG = getattr(st, "dialog", None) or getattr(st, "experimental_dialog", None)


def maybe_show(T: dict, reviewer: str = "", force: bool = False,
               lang: str = "ko") -> bool:
    """첫 실행이거나 force 면 안내를 띄운다. 띄웠으면 True.

    상태 규칙
      · mark() 는 **여는 즉시** 실행한다 — X 로 닫든 버튼으로 닫든, 한 번 본
        안내가 다음 실행에서 또 뜨면 안 된다. 다시 보려면 사이드바 버튼.
      · OPEN_KEY 는 **버튼을 누를 때까지** 유지된다 — 모달이 매 rerun 다시
        그려져야 버튼이 동작하기 때문이다(위 _actions 주석 참조).
    """
    if force:
        st.session_state[OPEN_KEY] = True
    elif not seen() and OPEN_KEY not in st.session_state:
        st.session_state[OPEN_KEY] = True
        st.session_state["_ops_onboard_done"] = True
        mark()

    if not st.session_state.get(OPEN_KEY):
        return False

    def _close():
        st.session_state[OPEN_KEY] = False
        st.session_state["_ops_onboard_done"] = True
        mark()
        st.rerun()

    def _dismiss():
        """X(또는 바깥 클릭)로 닫았을 때도 닫힌 것으로 친다.

        OPEN_KEY 는 버튼을 눌러야 내려가도록 설계돼 있어서(위 docstring 참조),
        X 로 닫으면 플래그가 True 로 남아 다음 rerun 에 안내가 되살아난다.
        on_dismiss 콜백 뒤에는 Streamlit 이 알아서 rerun 하므로 st.rerun() 은 부르지 않는다.
        """
        st.session_state[OPEN_KEY] = False
        st.session_state["_ops_onboard_done"] = True
        mark()

    if _DLG is not None:
        try:
            # on_dismiss= 는 1.49+, width= 는 1.37+. 낮은 버전에서도 죽지 않게 단계적으로 내려간다.
            try:
                dec = _DLG(_g(lang)["title"], width="large", on_dismiss=_dismiss)
            except TypeError:
                try:
                    dec = _DLG(_g(lang)["title"], width="large")
                except TypeError:
                    dec = _DLG(_g(lang)["title"])

            @dec
            def _dlg():
                render_body(T, reviewer, lang)
                if _actions(lang):
                    _close()

            _dlg()
            return True
        except Exception as e:                         # 다른 모달과 충돌 등
            log.warning(f"온보딩 모달 실패 → 인라인 표시: {e}")

    # 폴백 — 모달을 못 쓰면 페이지 상단 카드로. 버튼 동작은 동일하다.
    with st.container(border=True):
        st.markdown("##### " + _g(lang)["title"])
        render_body(T, reviewer, lang)
        if _actions(lang):
            _close()
    return True

"""selftest_ui — 화면 계층 회귀 (AppTest)  ✨ v24 신규

무엇을 지키려는가
  v24 에서 고친 UI 결함들은 **예외를 던지지 않는 부류**라 눈으로는 잘 안 보인다.
  "닫히긴 하는데 아무 일도 안 일어난다", "미리보기는 그대로인데 보내는 건 다르다"
  같은 것들이다. 그래서 화면을 실제로 띄우고 눌러 본다.

    · 앱이 예외 없이 뜬다 (표시 건수 100 — 중복키 크래시 재현 경로 포함)
    · 경보 카드 딥링크(?goto=…&gototab=log)가 그 거래를 **연다**
    · 편집 가능한 미리보기: 원본이 바뀌면 따라오고, 사람이 고친 건 보존된다
    · 감사 로그 삭제는 **2단계 확인**을 거친다
    · 직접입력 [자동채움] → [탐지 실행] 이 사기를 만들어낸다
    · (v25) 사이드바가 '만지는 빈도' 순인가 — 순서는 눈으로 지켜지지 않는다
    · (v25) 접힌 ⚙ 고급 설정 안의 API 키가 살아남는가 (toggle 로 바꾸면 날아간다)
    · (v25) 헤더 배지 숫자가 실제 큐와 일치하는가
    · (v25) 챗봇 set_sla 가 조용히 실패하지 않는가
    · (v26) detect_workbench 이관 후에도 위젯 key 27종이 그대로인가
      — 리팩터링에서 가장 조용히 깨지는 것이 위젯 key 다. 이름이 바뀌어도
        예외는 안 나고, 사용자 입력값과 챗봇 액션만 소리 없이 끊긴다.
    · (v26 A1) 두 앱이 같은 직접입력에 **같은 판정**을 내리는가
    · (v26 A2) 편집기 계층이 다시 두 벌로 갈라지지 않았는가
      — `value=` 함정이 '코드가 두 벌'이라는 이유로 세 번 재발했다. 셋 다
        예외가 안 나므로, 구현이 갈라지는 것 자체를 테스트로 막는다.

⚠️ 두 가지 원칙
  ① **운영 DB 를 절대 건드리지 않는다.** 탐지·발송은 DB 에 쓰므로 항상 사본을 쓴다.
  ② 네트워크로 나가지 않는다. 발송 버튼은 누르지 않는다.

⚠️ AppTest 함정 (v24 에서 두 번 속았다)
  `st.rerun()` 이 끼면 **rerun 직전 패스의 위젯이 element 목록에 잔상으로 남는다**
  (객체는 있는데 상태는 이미 정리돼 .value 접근 시 KeyError). 그래서 '닫혔는가' 는
  버튼 목록이 아니라 **세션 상태**로 판정한다.
  또 `AppTest.run()` 은 같은 객체를 변형해 돌려준다 — 스냅샷이 아니다.

실행:  python -m pipeline.selftest_ui     (느림 — 모델 로딩 포함)
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

fails: list[str] = []
skips: list[str] = []


def check(name: str, cond, detail: str = ""):
    print(("  ✅ " if cond else "  ❌ ") + name + (f" — {detail}" if detail else ""))
    if not cond:
        fails.append(name)


def skip(name: str, why: str):
    print(f"  ⏭  {name} — 건너뜀 ({why})")
    skips.append(name)


try:
    from streamlit.testing.v1 import AppTest
except ImportError:                                    # pragma: no cover
    print("streamlit.testing 을 쓸 수 없습니다 — 건너뜁니다")
    sys.exit(0)

from pipeline import ops_queries as oq

APP = ROOT / "ops_dashboard.py"
SRC_DB = ROOT / "fds_results.db"
if not APP.exists() or not SRC_DB.exists():
    print(f"⏭  ops_dashboard.py 또는 fds_results.db 없음 — 건너뜁니다")
    sys.exit(0)

DB = str(Path(tempfile.gettempdir()) / "selftest_ui.db")
for suf in ("", "-wal", "-shm"):
    if os.path.exists(DB + suf):
        os.remove(DB + suf)
shutil.copy(SRC_DB, DB)          # ★ 사본 — 운영 DB 보호

# ★ 프롬프트 저장소도 사본을 쓴다 — 이 테스트는 편집기의 [저장]/[복원]을 실제로
#   누르므로, 리다이렉트하지 않으면 사용자가 쓰는 prompts/overrides.json 을 지운다.
PROMPT_STORE = str(Path(tempfile.gettempdir()) / "selftest_prompts.json")
os.environ["FDS_PROMPT_STORE"] = PROMPT_STORE
if os.path.exists(PROMPT_STORE):
    os.remove(PROMPT_STORE)

# ★ 경보 설정도 마찬가지. AppTest 가 위젯 값을 바꾸면 on_change 가 실제로 발화해
#   alarm_prefs.json 이 테스트 위젯 기본값(전부 꺼짐·0)으로 덮여 쓰인다 —
#   실제로 그렇게 됐고, 다음 실행에서 selftest_alert 의 중복억제 검증이 깨졌다.
ALARM_PREFS = str(Path(tempfile.gettempdir()) / "selftest_alarm.json")
os.environ["FDS_ALARM_PREFS"] = ALARM_PREFS
if os.path.exists(ALARM_PREFS):
    os.remove(ALARM_PREFS)

from pipeline import detect_workbench as _dwb_ps      # 저장소 계약 검증용


def ss(app, key, default=None):
    """AppTest 의 session_state 는 .get() 이 없다."""
    try:
        return app.session_state[key]
    except Exception:
        return default


def blob(app) -> str:
    out = []
    for coll in (app.markdown, app.caption, app.info, app.warning):
        for e in coll:
            out.append(str(e.value))
    return "\n".join(out)


def fresh(**state):
    a = AppTest.from_file(str(APP), default_timeout=600)
    a.session_state["db_path"] = DB
    for k, v in state.items():
        a.session_state[k] = v
    a.run()
    return a


print("=" * 62)
print("[1] 앱이 뜨는가")
at = fresh()
check("예외 0", len(at.exception) == 0, str([e.value[:180] for e in at.exception[:2]]))
check("에러 0", len(at.error) == 0)
check("탭 렌더", len(at.tabs) > 0, str(len(at.tabs)))

print("\n[2] 표시 건수 100 — 중복키 크래시 재현 경로")
#   원장은 append-only 라 같은 txn_id 가 여러 줄일 수 있다. 조회 계층이 최신 1줄만
#   남기지 않으면 위젯 key 가 겹쳐 트리아지 탭 전체가 예외로 죽는다.
at.session_state["tri_n"] = 100
at.run()
check("예외 0", len(at.exception) == 0, str([e.value[:180] for e in at.exception[:2]]))

print("\n[3] 경보 카드 딥링크 — 그 거래를 여는가")
wide = oq.alert_queue(DB, limit=500, min_score=-1.0, only_unreviewed=False)
if len(wide) < 30:
    skip("딥링크", f"거래가 {len(wide)}건뿐이라 '표시 밖' 상황을 만들 수 없음")
else:
    target = wide[min(40, len(wide) - 1)]["txn_id"]
    base = fresh(log_n=25)
    check("딥링크 없이는 상세가 닫혀 있다", f"### `{target}`" not in blob(base))

    a = AppTest.from_file(str(APP), default_timeout=600)
    a.session_state["db_path"] = DB
    a.session_state["log_n"] = 25
    a.query_params["goto"] = target
    a.query_params["gototab"] = "log"
    a.run()
    check("예외 0", len(a.exception) == 0, str([e.value[:180] for e in a.exception[:2]]))
    check("탐지 로그 탭 선택", "로그" in str(ss(a, "ops_tab", "")), str(ss(a, "ops_tab")))
    check("★ 그 거래의 상세가 열린다", f"### `{target}`" in blob(a))
    check("포커스 유지(필터를 만져도 닫히지 않게)", ss(a, "log_focus") == target)
    check("쿼리 파라미터 소비(새로고침 재이동 방지)", "goto" not in a.query_params)

    a2 = AppTest.from_file(str(APP), default_timeout=600)
    a2.session_state["db_path"] = DB
    a2.query_params["goto"] = "NO_SUCH_TXN_XYZ"
    a2.query_params["gototab"] = "log"
    a2.run()
    check("없는 거래는 '못 찾았다'고 알린다", "찾지 못했습니다" in blob(a2))

print("\n[4] 검색 — 표시 건수 밖도 찾는가")
if len(wide) >= 30:
    target = wide[min(40, len(wide) - 1)]["txn_id"]
    a = fresh(log_n=25)
    box = [w for w in a.text_input if w.key == "log_q"]
    if not box:
        skip("검색", "log_q 입력란 없음")
    else:
        box[0].set_value(target).run()
        check("★ 표시 밖 거래도 검색된다", target in blob(a))
        check("전체 검색임을 알린다", "원장 **전체**에서 검색" in blob(a))

print("\n[5] 편집 가능한 미리보기 — 원본 추종 + 편집 보존")
q = oq.alert_queue(DB, limit=100, only_unreviewed=True)
if not q:
    skip("미리보기", "미판정 알림이 없음")
else:
    tid = q[0]["txn_id"]
    key = f"ai_email_prev_{tid}"

    def seed(app, body):
        app.session_state[f"_ai_result_{tid}"] = {
            "txn_id": tid, "fraud_type": "f", "risk_score": 0.9,
            "llm": {"analysis": "분석", "slack": "슬랙", "email": body}}

    a = AppTest.from_file(str(APP), default_timeout=600)
    a.session_state["db_path"] = DB
    seed(a, "EMAIL_V1")
    a.run()
    check("원본이 표시된다", ss(a, key) == "EMAIL_V1", str(ss(a, key)))
    seed(a, "EMAIL_V2")
    a.run()
    check("★ 재생성하면 미리보기도 바뀐다", ss(a, key) == "EMAIL_V2", str(ss(a, key)))
    w = [x for x in a.text_area if x.key == key]
    if w:
        w[0].set_value("사람이 고친 문장").run()
        a.run()                                    # 원본 변화 없는 단순 리런
        check("★ 사람이 고친 내용은 보존된다", ss(a, key) == "사람이 고친 문장",
              str(ss(a, key)))

print("\n[6] 감사 로그 삭제 — 2단계 확인이 강제되는가")
from pipeline import audit_store as aust
import sqlite3
aust.ensure_schema(DB)
con = sqlite3.connect(DB)
for i in range(5):
    con.execute(f"INSERT INTO {aust.TABLE} (sent_at, ok, channel, txn_id, via) "
                f"VALUES (datetime('now','-100 days'),1,'slack',?,'manual')", (f"UI_{i}",))
con.commit()
con.close()

a = fresh(reviewer="셀프테스트")
prep = [b for b in a.button if b.key == "diag_purge_prep"]
check("[삭제 준비] 버튼 존재", bool(prep))
check("★ 준비 전에는 [영구 삭제] 버튼이 아예 없다",
      not [b for b in a.button if b.key == "diag_purge_go"])
if prep:
    prep[0].click().run()
    go = [b for b in a.button if b.key == "diag_purge_go"]
    ack = [c for c in a.checkbox if c.key == "diag_purge_ack"]
    check("준비 후 삭제 버튼 등장", bool(go))
    check("확인 체크박스 등장", bool(ack))
    check("★ 체크 전에는 비활성", go and go[0].disabled is True,
          str(go[0].disabled if go else None))
    check("건수를 미리 보여준다",
          any("되돌릴 수 없습니다" in str(w.value) for w in a.warning))
    if ack:
        ack[0].set_value(True).run()
        go = [b for b in a.button if b.key == "diag_purge_go"]
        check("체크하면 활성화", go and go[0].disabled is False)

print("\n[7] 온보딩 안내 — 버튼이 실제로 동작하는가 (ops_guide)")
#   `st.dialog` 은 매 rerun 마다 다시 호출해야 열린 상태가 유지된다. 여는 순간
#   '봤음'으로 확정해 버리면 버튼을 누른 뒤의 rerun 에서 본문이 실행되지 않아
#   **클릭이 관측되지 않는다** — 예외도 안 난다. dashboard.py 가 v24 까지 그랬다.
a = fresh(_ops_guide_open=True)
onb = [b.key for b in a.button if str(b.key or "").startswith("opsonb_")]
if not onb:
    skip("온보딩", "ops_guide 미탑재 또는 버튼 없음")
else:
    check("안내 버튼 렌더", len(onb) >= 2, str(onb))
    go = [b for b in a.button if b.key == "opsonb_go"]
    if go:
        go[0].click().run()
        check("예외 0", len(a.exception) == 0,
              str([e.value[:180] for e in a.exception[:2]]))
        check("★ 버튼이 실제로 동작한다(트리아지로 이동)",
              "리아지" in str(ss(a, "ops_tab", "")), str(ss(a, "ops_tab")))
        check("모달이 닫힌다(세션 플래그로 판정)",
              ss(a, "_ops_guide_showing") is False, str(ss(a, "_ops_guide_showing")))

print("\n[8] 직접입력 [자동채움] → [탐지 실행]")
af = [b for b in at.button if b.key == "det_autofill"]
if not af:
    skip("자동채움", "직접입력 탭 버튼 없음")
else:
    a = fresh()
    [b for b in a.button if b.key == "det_autofill"][0].click().run()
    check("금액이 채워진다", ss(a, "det_amount") == -85_000_000, str(ss(a, "det_amount")))
    check("★ 계좌 이력도 채워진다",
          (ss(a, "det_hist_Account_one_month_max_amount") or 0) > 1_000_000,
          str(ss(a, "det_hist_Account_one_month_max_amount")))
    run = [b for b in a.button if b.key == "det_run_manual"]
    check("탐지 실행 버튼 존재 (예전엔 자동채움 예외로 렌더가 끊겼다)", bool(run))
    if run:
        run[0].click().run()
        check("탐지 후 예외 0", len(a.exception) == 0,
              str([e.value[:180] for e in a.exception[:2]]))
        last = ss(a, "_det_last") or {}
        check("★ 사기로 판정된다", last.get("fraud_type") not in (None, "m"),
              f"{last.get('fraud_type')} / {last.get('risk_score')}")
        check("이상거래로 처리된다", bool(last.get("is_anomaly")))

print("\n[9] 화면 동선 (v25) — 배치가 '만지는 빈도' 순인가")
#   순서는 눈으로만 지켜지지 않는다. 섹션을 하나 추가하면서 무심코 위로 올리면
#   검토자 이름이 다시 스크롤 밖으로 밀린다 — 그래서 순서를 테스트로 못박는다.
a = fresh(reviewer="테스트관제")
_ti = [w.key for w in a.sidebar.text_input]
_sb = [w.key for w in a.sidebar.selectbox]
check("검토자가 사이드바 첫 입력칸", _ti and _ti[0] == "reviewer", str(_ti[:3]))
check("★ 관제 설정이 모델·데이터셋보다 위 (model_dir 반영이 한 런 늦지 않게)",
      _ti.index("reviewer") < _ti.index("model_dir") < _ti.index("ds_folder"))
check("고급 설정은 마지막", _sb.index("pii_level") < _sb.index("model_sel_global")
      < _sb.index("ai_llm_provider"))

#   ⚠ 고급 설정을 st.toggle+if 로 감싸면 접힌 동안 위젯이 안 만들어지고
#     Streamlit 이 key 를 청소한다 = API 키가 날아간다. expander 여야 한다.
for _k in ("ai_slack_webhook", "ai_smtp_pass", "ai_notify_email"):
    check(f"★ 접힌 고급 설정 안에서도 {_k} 가 살아 있다", _k in _ti)
a.session_state["ai_slack_webhook"] = "https://hooks.slack.test/KEEP"
a.run()
check("★ 값이 재실행 후에도 보존된다",
      ss(a, "ai_slack_webhook") == "https://hooks.slack.test/KEEP",
      str(ss(a, "ai_slack_webhook")))

_hdr = "\n".join(str(e.value) for e in a.markdown)
_q = oq.alert_queue(DB, limit=500, min_score=0.0, only_unreviewed=True)
check("헤더 배지 렌더", "hero-badge" in _hdr)
check("★ 미판정 건수가 실제 큐와 일치",
      f'<div class="v">{len(_q)}</div><div class="k">미판정' in _hdr, str(len(_q)))
check("판정자 이름이 헤더에 뜬다", "테스트관제" in _hdr)

_sbmd = "\n".join(str(e.value) for e in a.sidebar.markdown)
check("임계값 대조표(사이드바)", "th-map compact" in _sbmd)
for _row in ("워처 경보 등급", "탐지 판정 임계값", "발송 등급"):
    check(f"대조표 행 — {_row}", _row in _sbmd)

print("\n[10] 챗봇 set_sla — 예전엔 메모조차 없이 조용히 실패했다")
try:
    from pipeline import ops_agent as oag
except ImportError:                                    # pragma: no cover
    oag = None
if oag is None:
    skip("set_sla", "ops_agent 없음")
else:
    a = fresh()
    _, _acts = oag.parse("[[ACTION: set_sla(90)]]")
    _notes = oag.apply(_acts, a.session_state)
    check("메모가 나온다", any("90분" in n for n in _notes), str(_notes))
    a.run()
    check("★ 다음 런에서 sla_min 이 실제로 바뀐다", ss(a, "sla_min") == 90,
          str(ss(a, "sla_min")))
    check("헤더 배지도 따라간다", "SLA 90분 초과" in
          "\n".join(str(e.value) for e in a.markdown))
    check("예외 0", len(a.exception) == 0,
          str([e.value[:180] for e in a.exception[:2]]))

print("\n[11] dashboard.py — 스모크 + 프롬프트 '기본값 복원' 회귀")
#   여기까지 이 파일은 ops_dashboard.py 만 띄웠다. 그래서 **두 앱에 복사된 화면**
#   중 dashboard.py 쪽만 조용히 썩었다 — 프롬프트 편집기의 `value=` 버그가
#   v24 에 ops 만 고쳐지고 이쪽엔 v25 까지 남아 있었다(같은 코드, 다른 파일).
#   detect_workbench 로 조립 계층을 합치려면 이쪽에도 최소한의 그물이 필요하다.
DASH = ROOT / "dashboard.py"           # §13 도 쓴다
if not DASH.exists():
    skip("dashboard.py 스모크", "파일 없음")
else:
    d = AppTest.from_file(str(DASH), default_timeout=900)
    d.run()
    check("dashboard.py 가 예외 없이 뜬다", len(d.exception) == 0,
          str([e.value[:180] for e in d.exception[:2]]))
    check("에러 0", len(d.error) == 0, str([e.value[:160] for e in d.error[:2]]))

    d.session_state["session_idx"] = 4          # 세션5 (AI 분석·알림)
    d.run()
    check("세션5 로 이동해도 예외 0", len(d.exception) == 0,
          str([e.value[:180] for e in d.exception[:2]]))
    _pt = [w.key for w in d.text_area if w.key and w.key.startswith("prompt_ta_")]
    check("프롬프트 편집창 4종 렌더", len(_pt) == 4, str(_pt))

    if "prompt_ta_analysis" in _pt:
        _default = ss(d, "prompt_ta_analysis") or ""
        # ① 사람이 고치고 저장 → 오버라이드가 걸린다
        d.session_state["prompt_ta_analysis"] = "MY EDITED PROMPT"
        [b for b in d.button if b.key == "prompt_save_analysis"][0].click().run()
        # v27: 저장 대상은 세션이 아니라 파일이다(두 앱 공용). LLM 에 실제로
        #   전달되는 값 = prompt_overrides() 로 확인한다 — 그것이 계약이다.
        check("저장하면 오버라이드가 걸린다",
              _dwb_ps.prompt_overrides().get("analysis") == "MY EDITED PROMPT",
              str(_dwb_ps.prompt_overrides().get("analysis"))[:40])
        check("★ dashboard 저장분을 ops 도 본다 (같은 파일 한 벌)",
              _dwb_ps.load_prompt_store().get("analysis") == "MY EDITED PROMPT")
        # ② 기본값 복원 → **편집창까지** 돌아와야 한다
        #    예전엔 세션 값만 지워지고 화면은 'MY EDITED PROMPT' 그대로였다
        [b for b in d.button if b.key == "prompt_reset_analysis"][0].click().run()
        check("복원하면 오버라이드가 지워진다",
              not _dwb_ps.prompt_overrides().get("analysis"),
              str(_dwb_ps.prompt_overrides().get("analysis")))
        check("★ 복원하면 편집창도 기본값으로 돌아온다 (v25 수정)",
              ss(d, "prompt_ta_analysis") != "MY EDITED PROMPT"
              and bool(ss(d, "prompt_ta_analysis")),
              str(ss(d, "prompt_ta_analysis"))[:40])
        check("복원 후 예외 0", len(d.exception) == 0,
              str([e.value[:180] for e in d.exception[:2]]))
    else:
        skip("프롬프트 복원 회귀", "prompt_ta_analysis 없음")

print("\n[12] detect_workbench 이관 — 위젯 key·탭·챗봇 액션이 그대로인가 (v26)")
#   '탐지 입력' 385줄을 pipeline/detect_workbench.py 로 옮겼다. 리팩터링에서
#   가장 조용히 깨지는 것이 **위젯 key** 다 — 이름이 바뀌면 예외도 안 나고
#   사용자가 입력해 둔 값과 챗봇 액션(_force_det_tab)만 소리 없이 끊긴다.
a = fresh()
a.session_state["ops_tab"] = "🧠 AI 분석·알림"
a.run()
check("AI 탭 예외 0", len(a.exception) == 0,
      str([e.value[:180] for e in a.exception[:2]]))
_labels = [tb.label for tb in a.tabs]
for _lb in ("📂 선택 데이터셋", "✏️ 직접입력", "📄 test.csv", "📊 train.csv",
            "🧪 합성생성", "📁 폴더배치"):
    check(f"입력 탭 '{_lb}'", _lb in _labels)

_keys = set()
for _coll in (a.number_input, a.text_input, a.selectbox, a.slider,
              a.checkbox, a.button, a.toggle):
    for _w in _coll:
        if _w.key:
            _keys.add(_w.key)
_MUST = ["det_amount", "det_dist", "det_bal", "det_ch", "det_os", "det_am",
         "det_autofill", "det_run_manual", "det_hist_reset",
         "det_test_path", "det_t2_n", "det_t2_seed", "det_run_test",
         "det_train_path", "det_t3_n", "det_t3_seed", "det_run_train",
         "det_g_n", "det_g_seed", "det_g_type", "det_run_gen",
         "det_folder_path", "det_run_folder",
         "det_t6_scope", "det_t6_n", "det_t6_seed", "det_run_ds"]
_miss = [k for k in _MUST if k not in _keys]
check(f"★ 위젯 key {len(_MUST)}종이 이관 전과 동일", not _miss, f"누락={_miss}")
check("플래그 12종", sum(1 for k in _keys if k.startswith("det_flag_")) == 12,
      str(sum(1 for k in _keys if k.startswith("det_flag_"))))

try:
    from pipeline import ops_agent as _oag
except ImportError:                                    # pragma: no cover
    _oag = None
if _oag is None:
    skip("챗봇 입력탭 액션", "ops_agent 없음")
else:
    b = fresh()
    _, _acts = _oag.parse("[[ACTION: goto_input_tab(synthetic)]]")
    _oag.apply(_acts, b.session_state)
    b.run()
    check("★ 챗봇이 입력 탭을 바꾼다", ss(b, "ops_det_tab") == "🧪 합성생성",
          str(ss(b, "ops_det_tab")))
    c = fresh()
    c.session_state["ops_tab"] = "🧠 AI 분석·알림"
    c.run()
    _, _acts = _oag.parse("[[ACTION: set_scope(m)]]")
    _oag.apply(_acts, c.session_state)
    c.run()
    check("★ 챗봇이 추출 범위를 바꾼다", ss(c, "det_t6_scope") == "m",
          str(ss(c, "det_t6_scope")))

print("\n[13] dashboard.py 직접입력 — 두 앱이 같은 판정을 내리는가 (v26 A1)")
#   여기서 잡은 것 두 가지. 둘 다 ops 는 v24 에 고쳤는데 화면이 두 벌이라
#   dashboard.py 만 v25 까지 깨진 채였다:
#     ① 자동입력 버튼이 눌리는 순간 StreamlitAPIException 으로 죽고
#        그 아래 [탐지 실행] 렌더까지 끊겼다 (버튼이 화면에서 사라진다)
#     ② row 에 계좌 이력이 아예 없어, 설령 눌렸어도 '거래가 전혀 없던 계좌'가
#        만들어져 고위험 프리셋조차 정상(m)으로 판정됐다
#   → 값 세트·row 조립·계좌 이력을 detect_workbench 가 단일 출처로 갖는다.
if not DASH.exists():
    skip("dashboard 직접입력", "파일 없음")
else:
    try:
        from pipeline import detect_workbench as _dwb
    except ImportError:                                # pragma: no cover
        _dwb = None
    d = AppTest.from_file(str(DASH), default_timeout=900)
    d.run()
    d.session_state["session_idx"] = 4
    d.session_state["s5_active_tab"] = "tab1"          # 직접입력
    d.session_state["run_with_llm"] = False            # LLM 호출 회피
    d.run()
    check("직접입력 예외 0", len(d.exception) == 0,
          str([e.value[:180] for e in d.exception[:2]]))
    check("🏦 계좌 이력이 화면에 있다",
          any(w.key and w.key.startswith("s5_hist_") for w in d.number_input))

    _af = [b for b in d.button if b.key == "manual_autofill"]
    check("자동입력 버튼 존재", bool(_af))
    if _af:
        _af[0].click().run()
        check("★ 자동입력 클릭이 예외를 내지 않는다", len(d.exception) == 0,
              str([e.value[:180] for e in d.exception[:2]]))
        check("금액이 채워진다", ss(d, "amount_in") == -85_000_000,
              str(ss(d, "amount_in")))
        _rm = [b for b in d.button if b.key == "run_manual"]
        check("★ [탐지 실행] 버튼이 살아 있다 (예전엔 렌더가 끊겨 사라졌다)", bool(_rm))
        if _rm:
            _rm[0].click().run()
            _det = ss(d, "det") or {}
            check("탐지 예외 0", not _det.get("error"), str(_det.get("error", ""))[:180])
            check("★ 고위험 프리셋이 사기로 판정된다 (예전엔 정상 m)",
                  _det.get("fraud_type") not in (None, "m"),
                  f"{_det.get('fraud_type')} / {_det.get('risk_score')}")
            check("★ row 에 계좌 이력이 들어간다",
                  (_det.get("row") or {}).get("Account_one_month_max_amount", 0) > 1e6,
                  str((_det.get("row") or {}).get("Account_one_month_max_amount")))

    if _dwb is None:
        skip("계약 단일 출처", "detect_workbench 없음")
    else:
        _r = _dwb.build_manual_row(amount=-85_000_000, distance=480,
                                   balance=120_000_000, channel="ATM", os_="Others",
                                   access_medium="a",
                                   flags={f: 1 for f in _dwb.AUTOFILL_FLAGS})
        check("★ build_manual_row 는 history 를 생략해도 계좌 이력을 넣는다",
              all(k in _r for k in _dwb.account_history_defaults()))
        check("계좌 이력이 0 이 아니다", _r["Account_one_month_max_amount"] > 1e6)
        # 두 앱의 자동채움이 같은 '값'을 쓰는가 (위젯 key 만 다르다)
        _p1 = _dwb.autofill_payload({"amount": "det_amount", "distance": "det_dist",
                                     "balance": "det_bal", "channel": "det_ch",
                                     "os": "det_os"}, lambda f: f"det_flag_{f}")
        _p2 = _dwb.autofill_payload(dict(zip(
            ["amount", "distance", "balance", "channel", "os"],
            ["amount_in", "dist_in", "bal_in", "ch_in", "os_in"])),
            lambda f: f"flag_{f}")
        check("★ 두 앱의 자동채움 값 세트가 동일",
              sorted(map(str, _p1.values())) == sorted(map(str, _p2.values())),
              f"ops={len(_p1)} dash={len(_p2)}")

print("\n[14] 편집기 계층 — 두 앱이 한 벌을 쓰는가 (v26 A2)")
#   `value=` 함정이 **같은 편집기 코드가 두 벌**이라는 이유로 세 번 반복됐다
#   (ops 이메일 미리보기 v24 / dashboard 프롬프트·RAG 편집기 v26).
#   셋 다 예외가 안 나므로 눈으로는 못 찾는다 — 구현이 다시 갈라지는 것 자체를 막는다.
try:
    from pipeline import detect_workbench as _dwb2
except ImportError:                                    # pragma: no cover
    _dwb2 = None
if _dwb2 is None:
    skip("편집기 계층", "detect_workbench 없음")
else:
    _ops_src = (ROOT / "ops_dashboard.py").read_text(encoding="utf-8")
    _dsh_src = DASH.read_text(encoding="utf-8") if DASH.exists() else ""
    for _nm, _s in (("ops", _ops_src), ("dashboard", _dsh_src)):
        if not _s:
            continue
        check(f"★ {_nm}: 편집기 본문이 다시 생기지 않았다",
              "_PROMPT_SLOTS" not in _s and "rag_reidx_" not in _s)
        check(f"★ {_nm}: prompt_ov_ 4키를 다시 하드코딩하지 않았다",
              _s.count("prompt_ov_") <= 1, f"count={_s.count('prompt_ov_')}")
        check(f"{_nm}: 공용 편집기를 부른다",
              "render_prompt_editor" in _s and "render_rag_editor" in _s)

    check("프롬프트 슬롯 4종",
          tuple(_dwb2.PROMPT_SLOTS) == ("analysis", "slack", "email", "batch"),
          str(_dwb2.PROMPT_SLOTS))

    # i18n — 두 앱의 접두어가 다르다(ai./s5.). 아무것도 모르는 번역기를 넣어
    #   폴백이 실제 문구를 내는지 본다(키가 그대로 나오면 화면에 's5.rag_save' 가 뜬다).
    _dumb = lambda k, **kw: k
    _bad = [f"{_ns}.{_sf}" for _ns in ("ai", "s5")
            for _sf in ("prompt_editor_title", "prompt_save", "prompt_reset",
                        "prompt_active", "rag_editor_title", "rag_save",
                        "rag_reindex", "rag_delete", "rag_new_empty",
                        "rag_new_bad", "rag_new_dup")
            if _dwb2._tf(_dumb, f"{_ns}.{_sf}") == f"{_ns}.{_sf}"]
    check("★ i18n 폴백이 두 접두어 모두 커버", not _bad, str(_bad[:4]))

    # ops 편집기가 실제로 뜨고, 저장→복원이 화면까지 반영되는가
    a = fresh()
    a.session_state["ops_tab"] = "🧠 AI 분석·알림"
    a.run()
    _pt = [w.key for w in a.text_area if w.key and w.key.startswith("prompt_ta_")]
    check("ops 프롬프트 편집창 4종", len(_pt) == 4, str(_pt))
    check("ops RAG 편집창 렌더",
          any(w.key and w.key.startswith("rag_ta_") for w in a.text_area))
    if "prompt_ta_analysis" in _pt:
        a.session_state["prompt_ta_analysis"] = "OPS EDIT"
        [b for b in a.button if b.key == "prompt_save_analysis"][0].click().run()
        # ★ v27: 저장은 이제 **파일**로 간다 — 세션 사본이 아니라 그쪽이 진실이다.
        #   세션에 사본이 남으면 상대 앱이 나중에 저장한 프롬프트를 이 세션이
        #   영원히 무시한다(= 공유가 안 된다). 그래서 사본이 없는 것까지 확인한다.
        check("★ ops 저장 → 파일에 남는다",
              _dwb2.load_prompt_store().get("analysis") == "OPS EDIT",
              str(_dwb2.load_prompt_store())[:60])
        check("★ 저장 후 세션 사본을 남기지 않는다 (안 그러면 상대 앱 저장을 무시)",
              not ss(a, "prompt_ov_analysis"))
        check("★ LLM 에 실제로 가는 프롬프트가 그 값",
              _dwb2.prompt_overrides().get("analysis") == "OPS EDIT")
        [b for b in a.button if b.key == "prompt_reset_analysis"][0].click().run()
        check("★ ops 복원 → 편집창도 기본값",
              ss(a, "prompt_ta_analysis") != "OPS EDIT" and bool(ss(a, "prompt_ta_analysis")),
              str(ss(a, "prompt_ta_analysis"))[:30])
        check("★ 복원 → 파일에서도 지워진다 (다른 앱도 기본값으로 돌아간다)",
              not _dwb2.load_prompt_store().get("analysis"),
              str(_dwb2.load_prompt_store())[:60])

    # 두 앱이 정말 한 벌을 보는가 — ops 가 저장한 것을 dashboard 쪽 경로로 읽는다.
    #   프로세스가 갈려도 파일은 하나이므로, 여기서 통과하면 실제 배포에서도 통한다.
    _dwb2.save_prompt_override("slack", "SHARED BY BOTH APPS")
    check("★ 두 앱 공용 — 한쪽이 저장하면 다른 쪽이 읽는다",
          _dwb2.load_prompt_store().get("slack") == "SHARED BY BOTH APPS")
    _dwb2.save_prompt_override("slack", "")
    check("★ 빈 값 저장 = 삭제 (기본 프롬프트로 복귀)",
          not _dwb2.load_prompt_store().get("slack"))

print("\n[⌨] 키보드 단축키 · 챗 에이전트 배선  ✨ v38")
#
# 여기서 지키려는 것은 **하나의 규칙**이다:
#   "이미 만들어진 위젯의 key 를 나중에 건드리지 마라."
# 이 규칙을 어기면 Streamlit 이 예외를 던지는데, 화면에는 빨간 박스가 뜨고
# 정작 토글은 안 먹는다. 개발 중 실제로 두 번 밟았다.
#   · 단축키 V/A — 히든 버튼이 파일 **끝**에 있어서 진단탭 압축 토글과
#     실시간탭 자동새로고침 위젯보다 뒤였다 → 예약값(_pending_*)으로 우회
#   · 자가진단 '이 액션 실행' — 버튼이 AI 탭 안이라 대부분의 위젯보다 뒤였다
#     → 챗 입력과 같은 '적재 후 드레인'으로 우회
# 그래서 아래 검사들은 값이 바뀌었는지와 함께 **예외가 0인지**를 항상 같이 본다.
# (값만 보면 예외가 나도 통과해 버린다 — 실제로 그렇게 놓쳤다)

at = fresh()
check("앱이 뜬다 (단축키 블록 포함)", len(at.exception) == 0,
      str([e.value[:180] for e in at.exception[:1]]))
_btn_keys = {b.key for b in at.button}
for _hk in ("hk_theme", "hk_lang", "hk_guide", "hk_keymap",
            "hk_compact", "hk_autorf", "hk_refresh", "hk_chat"):
    check(f"히든 버튼 {_hk}", _hk in _btn_keys)

# T — 테마는 위젯 key 가 아니라 일반 상태(theme)다. 대신 사이드바 셀렉트박스
#   (_theme_pick)에 옛 값이 남으면 다음 런에서 되돌려 놓는다 → pop 이 핵심.
at = fresh()
_th0 = ss(at, "theme")
at.button(key="hk_theme").click().run()
_th1 = ss(at, "theme")
check("T — 테마가 바뀐다", _th0 != _th1, f"{_th0} -> {_th1}")
check("T — 예외 0", len(at.exception) == 0, str([e.value[:180] for e in at.exception[:1]]))
at.run()
check("★ T — 다음 런에서 되돌아가지 않는다", ss(at, "theme") == _th1,
      f"{_th1} -> {ss(at, 'theme')}")

# L — 언어도 같은 구조(_lang_pick).
#   ⚠ 여기서 두 번째 .run() 은 부르지 않는다. 비한국어 상태에서 AppTest 가
#     batch_src 라디오의 index 를 계산하다 죽는데(포맷 라벨과 옵션 불일치),
#     이건 단축키와 **무관한 기존 현상**이다 — 단축키 블록을 들어낸 사본에서도,
#     사이드바 언어 라디오를 직접 조작해도 똑같이 난다. 되돌림 방지의 증거만 본다.
at = fresh()
_lg0 = ss(at, "lang")
at.button(key="hk_lang").click().run()
_lg1 = ss(at, "lang")
check("L — 언어가 바뀐다", _lg0 != _lg1, f"{_lg0} -> {_lg1}")
check("★ L — 사이드바 라디오가 새 언어를 따라간다(되돌림 방지)",
      ss(at, "_lang_pick") == _lg1, f"{ss(at, '_lang_pick')} vs {_lg1}")
check("L — 예외 0", len(at.exception) == 0, str([e.value[:180] for e in at.exception[:1]]))

# V / A — ★ 둘 다 위젯 key 다. 예외 검사가 이 항목의 핵심이다.
for _hk, _wk, _dflt, _nm in (("hk_compact", "ops_tab_compact", False, "V 탭라벨 압축"),
                             ("hk_autorf", "auto_refresh", True, "A 자동새로고침")):
    at = fresh()
    _b4 = bool(ss(at, _wk, _dflt))
    at.button(key=_hk).click().run()
    check(f"★ {_nm} — 예외 0 (위젯 key 직접 수정 아님)", len(at.exception) == 0,
          str([e.value[:180] for e in at.exception[:1]]))
    check(f"{_nm} — 토글된다", bool(ss(at, _wk)) != _b4, str(ss(at, _wk)))

for _hk, _nm in (("hk_guide", "H 사용안내"), ("hk_keymap", "? 단축키"),
                 ("hk_refresh", "R 새로고침"), ("hk_chat", "C 챗 이동")):
    _a = fresh()
    _a.button(key=_hk).click().run()
    check(f"{_nm} — 예외 0", len(_a.exception) == 0,
          str([e.value[:180] for e in _a.exception[:1]]))

at = fresh(_ops_keymap_open=True)
check("? — 모음 플래그가 소비된다", not ss(at, "_ops_keymap_open", False))
check("? — 단축키 표가 그려진다", "<kbd" in blob(at), blob(at)[:120])

# 실행형 액션 플래그는 **탭 밖에서** 꺼내야 한다. 탭 안에서 꺼내면 조건이 안 맞은
#   런에서 남아, 다음 자동 새로고침 때 시키지도 않은 분석이 돈다.
for _flag in ("_pending_ai_run", "_pending_batch_run"):
    _a = fresh(**{_flag: True})
    check(f"★ {_flag} 가 남지 않는다", not ss(_a, _flag, False), str(ss(_a, _flag)))
    check(f"{_flag} — 예외 0", len(_a.exception) == 0,
          str([e.value[:180] for e in _a.exception[:1]]))

# 챗 UX — 퀵프롬프트·자가진단
at = fresh()
_bk = {b.key for b in at.button}
check("퀵프롬프트 4개", all(f"ops_chat_quick_{i}" in _bk for i in range(4)))
check("자가진단 실행 버튼", "ops_agent_live_go" in _bk)
try:
    from pipeline import ops_agent as _oag_ui
    # ⚠ blob() 은 markdown/caption/info/warning 만 모은다. 진단 패널은 st.code 와
    #   st.success 로 그려지므로 그쪽을 직접 본다(예전엔 blob 으로 보고 헛되이 실패했다).
    _diag = "\n".join(str(e.value) for coll in (at.code, at.success) for e in coll)
    check("등록 액션 수가 화면에 보인다", f"{len(_oag_ui.ACTIONS)}종" in _diag, _diag[:160])
    check("파서 자가검증이 초록불", "파서 정상" in _diag, _diag[:160])
except ImportError:                                    # pragma: no cover
    skip("자가진단 표시", "ops_agent 없음")

# ★ 자가진단의 '이 액션 실행' — AI 탭 안이라 apply() 를 인라인으로 부르면 터진다.
at = fresh()
at.session_state["ops_agent_live_sel"] = "set_window"
at.run()
at.button(key="ops_agent_live_go").click().run()
check("★ 자가진단 액션 실행 — 예외 0", len(at.exception) == 0,
      str([e.value[:220] for e in at.exception[:1]]))
check("자가진단 액션이 실제 반영된다", ss(at, "window_h") == 168, repr(ss(at, "window_h")))
check("적재값이 남지 않는다", "_ops_agent_live" not in at.session_state)

# 🐛 회귀 — 챗봇 액션이 '구버전 값 정리'에 걸려 조용히 사라지지 않는가.
#   sort_queue 는 예전에 표시 문구("점수순")를 넣어, 위젯 옵션(["age","score"])에
#   없는 값이라 매번 pop 됐다. 챗봇은 성공했다고 답하는데 화면은 그대로였다.
try:
    from pipeline import ops_agent as _oag2
    at = fresh()
    for _mk in ("sort_queue(score)", "set_queue_limit(50)", "set_window(720)",
                "search_log(REGRESSION)", "set_fp_dim(reviewer)"):
        _, _ac = _oag2.parse(f"[[ACTION: {_mk}]]")
        _oag2.apply(_ac, at.session_state)
    at.run()
    check("★ sort_queue 가 살아남는다", ss(at, "tri_sort") == "score", repr(ss(at, "tri_sort")))
    check("set_queue_limit 반영", ss(at, "tri_n") == 50, repr(ss(at, "tri_n")))
    check("set_window 반영", ss(at, "window_h") == 720, repr(ss(at, "window_h")))
    check("search_log 반영", ss(at, "log_q") == "REGRESSION", repr(ss(at, "log_q")))
    check("set_fp_dim 반영", ss(at, "fp_dim") == "reviewer", repr(ss(at, "fp_dim")))
    check("액션 반영 후 예외 0", len(at.exception) == 0,
          str([e.value[:180] for e in at.exception[:1]]))
except ImportError:                                    # pragma: no cover
    skip("챗봇 액션 회귀", "ops_agent 없음")

for suf in ("", "-wal", "-shm"):
    try:
        os.remove(DB + suf)
    except OSError:
        pass
for _f in (PROMPT_STORE, ALARM_PREFS):
    try:
        os.remove(_f)
    except OSError:
        pass

print("\n" + "=" * 62)
if skips:
    print(f"⏭  건너뜀 {len(skips)}건: {skips}")
if fails:
    print(f"❌ 실패 {len(fails)}건: {fails}")
    sys.exit(1)
print("✅ 전체 통과")

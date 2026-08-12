"""selftest_agent — ops_agent(관제 챗봇 액션) 자체 검증  ✨ v24 신규

무엇을 지키려는가
  챗봇이 만든 텍스트에서 액션을 **파싱하고 실행**하는 층이다. 여기가 조용히
  느슨해지면, LLM 이 뱉은 아무 문자열이 관제 화면의 상태를 바꾸게 된다.
  그래서 이 테스트의 절반은 '**하면 안 되는 것을 안 하는가**' 를 본다.

  · 화이트리스트에 없는 액션 → 버린다
  · 범위를 벗어난 인자 → 버린다
  · 발송·판정·워처 제어 액션은 **애초에 레지스트리에 없어야** 한다

실행:  python -m pipeline.selftest_agent
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import ops_agent as oag

fails: list[str] = []


def check(name: str, cond, detail: str = ""):
    print(("  ✅ " if cond else "  ❌ ") + name + (f" — {detail}" if detail else ""))
    if not cond:
        fails.append(name)


print("=" * 62)
print("[1] 레지스트리 — 위험한 액션이 섞여 있지 않은가")
names = set(oag.ACTIONS)
check("액션 25종", len(names) == 25, str(sorted(names)))
FORBIDDEN = ("send", "slack", "email", "notify", "record", "verdict", "judge",
             "start_watcher", "stop_watcher", "delete", "purge")
leaked = [n for n in names for f in FORBIDDEN if f in n.lower()]
check("발송·판정·워처제어 액션 없음", not leaked, str(leaked))
check("모든 액션에 kind/label/example", all(
    {"kind", "label", "example"} <= set(m) for m in oag.ACTIONS.values()))

print("\n[2] 파싱 — 정상 마커")
txt, acts = oag.parse("확인했습니다. [[ACTION: goto_tab(triage)]] 이동합니다.")
check("액션 1건 파싱", len(acts) == 1 and acts[0]["name"] == "goto_tab", str(acts))
check("인자 정상", acts and acts[0]["arg"] == "triage", str(acts))
check("마커가 본문에서 제거됨", "[[ACTION" not in txt, txt)
check("본문은 남는다", "확인했습니다" in txt and "이동합니다" in txt, txt)

_, acts = oag.parse("[[ACTION: goto_tab(triage)]][[ACTION: set_sla(45)]]")
check("여러 액션 파싱", len(acts) == 2, str(acts))

print("\n[3] 파싱 — **버려야 할 것들**")
for bad, why in (
        ("[[ACTION: send_slack(all)]]", "화이트리스트 밖"),
        ("[[ACTION: record_verdict(fp)]]", "판정 액션"),
        ("[[ACTION: goto_tab(없는탭)]]", "enum 값 오류"),
        ("[[ACTION: set_threshold(150)]]", "범위 초과(퍼센트로 봐도 초과)"),
        ("[[ACTION: set_threshold(-0.5)]]", "음수"),
        ("[[ACTION: set_threshold(abc)]]", "형변환 실패"),
        ("[[ACTION: set_sla(99999)]]", "int 범위 초과"),
        ("[[ACTION: select_pending(3)]]", "enum 자리에 숫자"),
):
    _, a = oag.parse(bad)
    check(f"{why} 무시", not a, f"{bad} → {a}")

_, a = oag.parse("")
check("빈 입력 안전", a == [])
_, a = oag.parse("액션 없는 평범한 답변입니다")
check("마커 없는 텍스트 안전", a == [])

print("\n[3-B] 형식 관용성 — 로컬 모델이 흔들리는 표기까지 알아듣는가")
#   ⚠️ 관용은 **형식에만**. 자연어 의도 추론은 하지 않는다(모듈 주석 참조).
for variant, why in (
        ("[ACTION: goto_tab(triage)]", "괄호 한 겹"),
        ("[[action: goto_tab(triage)]]", "소문자"),
        ("[[ACTION:goto_tab(triage)]]", "콜론 뒤 공백 없음"),
        ("[[ACTION: goto_tab (triage)]]", "이름과 괄호 사이 공백"),
        ("```\n[[ACTION: goto_tab(triage)]]\n```", "코드펜스로 감쌈"),
        ("**[[ACTION: goto_tab(triage)]]**", "굵게 강조"),
        ("[[ACTION：goto_tab(triage)]]", "전각 콜론"),
):
    _, a = oag.parse(variant)
    check(f"{why} 인식", a and a[0]["name"] == "goto_tab" and a[0]["arg"] == "triage",
          f"{variant!r} → {a}")

# 형식이 맞아도 **없는 동작**은 여전히 버린다 (관용 ≠ 무방비)
for variant in ("[ACTION: send_slack(all)]", "[[action: record_verdict(fp)]]"):
    _, a = oag.parse(variant)
    check(f"관용 표기여도 화이트리스트 밖은 버린다", not a, f"{variant} → {a}")

# 자연어로만 말한 것은 **동작하지 않는다** (의도 추론 금지)
for nl in ("트리아지 탭으로 이동해줘", "goto_tab triage 실행", "「트리아지로 가기」"):
    _, a = oag.parse(nl)
    check("자연어만으로는 실행하지 않는다", not a, f"{nl!r} → {a}")

print("\n[4] float 관용 처리 — '70%' 같은 표기")
#   임계값은 0~1 이므로 1 을 넘는 값은 퍼센트로 해석한다(의도된 동작).
#   따라서 9.9 → 9.9% → 0.099 다. '범위 초과'가 아니다.
_, a = oag.parse("[[ACTION: set_threshold(70%)]]")
check("70% → 0.7", a and abs(a[0]["arg"] - 0.7) < 1e-9, str(a))
_, a = oag.parse("[[ACTION: set_threshold(0.35)]]")
check("0.35 그대로", a and abs(a[0]["arg"] - 0.35) < 1e-9, str(a))
_, a = oag.parse("[[ACTION: set_threshold(9.9)]]")
check("9.9 → 0.099 (퍼센트 해석)", a and abs(a[0]["arg"] - 0.099) < 1e-9, str(a))

print("\n[5] 실행 — 세션 상태에 반영되는가")
ss: dict = {}
_, a = oag.parse("[[ACTION: goto_tab(log)]]")
notes = oag.apply(a, ss)
check("탭 이동이 예약된다", ss.get("_force_tab") == "log", str(ss))
check("사용자에게 보일 메모 반환", bool(notes), str(notes))

ss = {}
_, a = oag.parse("[[ACTION: set_sla(45)]]")
notes = oag.apply(a, ss)
check("SLA 예약", ss.get("_pending_sla") == 45, str(ss))
check("SLA 메모 반환", any("45분" in n for n in notes), str(notes))

print("\n[6] ⚠️ 위젯 key 를 직접 건드리지 않는가")
#   화면이 이미 만든 위젯의 key 를 바꾸면 Streamlit 이 예외를 던진다.
#   그래서 액션은 반드시 _pending_* 예약값으로 우회해야 한다(모듈 주석 참조).
#   ⚠ set_sla 는 예전에 이 규칙을 어기고 `ss["sla_min"]`을 직접 썼다. 예외가
#     apply() 의 try/except 에 먹혀 **메모조차 안 나온 채 조용히 실패**했다 —
#     그래서 여기서 "예약값을 쓰는가"와 "메모가 나오는가"를 함께 본다.
_SB_WIDGET_KEYS = {"sla_min", "th_slider", "th_review", "th_confirm",
                   "selected_model", "selected_dataset", "ds_folder",
                   "reviewer", "pii_level", "db_path"}
for _marker, _label in (("set_threshold(0.5)", "임계값"),
                        ("set_sla(45)", "SLA"),
                        ("set_scope(m)", "추출 범위")):
    ss = {}
    _, a = oag.parse(f"[[ACTION: {_marker}]]")
    oag.apply(a, ss)
    check(f"{_label}은 예약값으로 전달", any(k.startswith("_pending") for k in ss),
          str(list(ss)))
    check(f"{_label} — 사이드바 위젯 key 를 직접 쓰지 않는다",
          not (_SB_WIDGET_KEYS & set(ss)), str(sorted(_SB_WIDGET_KEYS & set(ss))))

print("\n[7] select_pending — 큐를 참조하는 액션 (all / over / none)")
queue = [{"txn_id": f"T{i}", "urgency": "over" if i < 2 else "ok"} for i in range(5)]

ss = {}
_, a = oag.parse("[[ACTION: select_pending(all)]]")
oag.apply(a, ss, queue=queue)
check("all → 표시된 전체", ss.get("tri_bulk_sel") == {f"T{i}" for i in range(5)},
      str(ss.get("tri_bulk_sel")))

ss = {}
_, a = oag.parse("[[ACTION: select_pending(over)]]")
oag.apply(a, ss, queue=queue)
check("over → SLA 초과분만", ss.get("tri_bulk_sel") == {"T0", "T1"},
      str(ss.get("tri_bulk_sel")))

ss = {}
_, a = oag.parse("[[ACTION: select_pending(none)]]")
oag.apply(a, ss, queue=queue)
check("none → 해제", ss.get("tri_bulk_sel") == set(), str(ss.get("tri_bulk_sel")))

# ★ 선택만 하고 **판정은 하지 않는다** — 저장 버튼은 사람이 누른다
ss = {}
_, a = oag.parse("[[ACTION: select_pending(all)]]")
oag.apply(a, ss, queue=queue)
check("★ 판정은 하지 않는다(저장은 사람 몫)",
      not any("verdict" in str(k).lower() or str(k).startswith("v_") for k in ss),
      str(list(ss)))
check("트리아지 탭으로 보낸다", ss.get("_force_tab") == "triage")

oag.apply(a, {}, queue=[])          # 빈 큐에서도 죽지 않아야 한다
oag.apply(a, {}, queue=None)
check("빈 큐·None 에서도 예외 없음", True)

print("\n[7-B] 🐛 회귀 — sort_queue 는 위젯 '옵션값'을 써야 한다")
#   과거 버그: 표시 문구("대기순"/"점수순")를 넣었는데 위젯(tri_sort)의 실제
#   옵션은 ["age","score"] 였다. ops_dashboard 에는 '목록에 없는 값이면 pop'
#   하는 구버전 값 정리 코드가 있어서, 이 액션은 **매번 조용히 버려졌다** —
#   챗봇은 "바꿨습니다"라고 답하는데 화면은 그대로. 표시 문구를 넣지 않는지 본다.
_SORT_WIDGET_OPTS = {"age", "score"}          # ops_dashboard._SORT_OPTS 와 일치
for _arg, _want in (("wait", "age"), ("score", "score")):
    ss = {}
    _, a = oag.parse(f"[[ACTION: sort_queue({_arg})]]")
    notes = oag.apply(a, ss)
    check(f"sort_queue({_arg}) → 위젯 옵션값 {_want!r}", ss.get("tri_sort") == _want,
          str(ss.get("tri_sort")))
    check(f"sort_queue({_arg}) — 메모는 사람 말로", bool(notes), str(notes))
check("정렬값이 위젯 옵션 집합 안에 있다", ss.get("tri_sort") in _SORT_WIDGET_OPTS)

print("\n[9] v2 액션 — 표시 설정·필터·검색")
#   ⚠ 이산 위젯(select_slider)은 목록에 없는 값을 넣으면 화면이 조용히 pop 한다.
#     그래서 enum 허용값이 **화면 옵션과 글자 그대로** 같아야 한다.
check("기간 옵션이 화면과 일치", oag.WINDOW_OPTS == ["24", "72", "168", "720", "2160"],
      str(oag.WINDOW_OPTS))
check("트리아지 건수 옵션이 화면과 일치", oag.QUEUE_LIMITS == ["10", "20", "30", "50"],
      str(oag.QUEUE_LIMITS))
check("로그 건수 옵션이 화면과 일치", oag.LOG_LIMITS == ["25", "50", "100", "200"],
      str(oag.LOG_LIMITS))

# 이산 액션은 **숫자**로 들어가야 한다 — 문자열 "168" 을 넣으면 select_slider 가
#   목록에 없는 값으로 보고 버린다(위와 같은 실패 방식).
for _marker, _key, _want in (("set_window(168)", "window_h", 168),
                             ("set_queue_limit(50)", "tri_n", 50),
                             ("set_log_limit(100)", "log_n", 100)):
    ss = {}
    _, a = oag.parse(f"[[ACTION: {_marker}]]")
    oag.apply(a, ss)
    check(f"{_marker} → {_key}={_want} (문자열 아님)",
          ss.get(_key) == _want and isinstance(ss.get(_key), int), repr(ss.get(_key)))

# on/off 는 bool 로 — 위젯이 toggle 이라 문자열 "on" 을 넣으면 항상 참이 된다
for _marker, _key, _want in (("set_only_new(off)", "tri_only_new", False),
                             ("set_log_anomaly_only(off)", "log_anom", False),
                             ("set_auto_refresh(on)", "auto_refresh", True),
                             ("set_compact_tabs(on)", "ops_tab_compact", True),
                             ("set_sort_dir(asc)", "tri_sort_desc", False)):
    ss = {}
    _, a = oag.parse(f"[[ACTION: {_marker}]]")
    oag.apply(a, ss)
    check(f"{_marker} → {_key}={_want} (bool)",
          ss.get(_key) is _want, repr(ss.get(_key)))

ss = {}
_, a = oag.parse("[[ACTION: search_log(T20250810)]]")
oag.apply(a, ss)
check("search_log → 검색어 설정 + 로그 탭",
      ss.get("log_q") == "T20250810" and ss.get("_force_tab") == "log", str(ss))
ss = {}
_, a = oag.parse("[[ACTION: search_log()]]")
oag.apply(a, ss)
check("search_log() → 검색어 해제(빈 문자열)", ss.get("log_q") == "", repr(ss.get("log_q")))
_, a = oag.parse("[[ACTION: search_log(" + "가" * 300 + ")]]")
check("긴 검색어는 잘린다", a and len(a[0]["arg"]) <= 80, str(len(a[0]["arg"]) if a else -1))

print("\n[10] v2 실행형 — 실행은 하되 **밖으로 내보내지는 않는다**")
#   run_* 는 결과를 화면에 띄울 뿐이다. 발송(Slack/Email)은 사람이 따로 누른다.
#   버튼은 세션 상태로 누를 수 없으므로 예약 플래그를 쓴다.
for _marker, _flag in (("run_ai_analysis()", "_pending_ai_run"),
                       ("run_batch()", "_pending_batch_run")):
    ss = {}
    _, a = oag.parse(f"[[ACTION: {_marker}]]")
    notes = oag.apply(a, ss)
    check(f"{_marker} → 예약 플래그 {_flag}", ss.get(_flag) is True, str(ss))
    check(f"{_marker} — 발송 키를 건드리지 않는다",
          not any(("send" in str(k).lower() or "slack" in str(k).lower()
                   or "email" in str(k).lower()) for k in ss), str(list(ss)))
    check(f"{_marker} — 메모 반환", bool(notes), str(notes))

# ★ 경보 등급 임계값 저장은 **없어야** 한다 — watcher_config 는 핫 리로드라
#   저장하는 순간 무인 워처의 경보 기준이 바뀐다(= 실질적 워처 제어).
check("★ 경보 등급 임계값 저장 액션 없음",
      not any(n in names for n in ("set_tier_threshold", "apply_threshold",
                                   "save_threshold", "set_watcher_threshold")),
      str(sorted(names)))

print("\n[11] v2 — 모든 액션이 '조용한 실패' 없이 무언가를 남기는가")
#   실패 방식이 늘 같았다: 상태는 안 바뀌는데 챗봇은 성공했다고 말한다.
#   전 액션의 example 을 실행해 (a) 예외 없음 (b) 메모 반환 을 확인한다.
_silent = []
for _n, _m in oag.ACTIONS.items():
    ss = {}
    _, a = oag.parse(f"[[ACTION: {_m['example']}]]")
    try:
        _notes = oag.apply(a, ss, queue=queue)
    except Exception as _e:                     # pragma: no cover
        _silent.append(f"{_n}(예외: {_e})")
        continue
    if not _notes or not ss:
        _silent.append(_n)
check("전 액션이 상태 변경 + 메모를 남긴다", not _silent, str(_silent))

# 새 액션도 사이드바 위젯 key 를 직접 건드리면 안 된다(위 [6]과 같은 규칙)
_touched = set()
for _m in oag.ACTIONS.values():
    ss = {}
    _, a = oag.parse(f"[[ACTION: {_m['example']}]]")
    oag.apply(a, ss, queue=queue)
    _touched |= set(ss)
check("★ 어떤 액션도 사이드바 위젯 key 를 직접 쓰지 않는다",
      not (_SB_WIDGET_KEYS & _touched), str(sorted(_SB_WIDGET_KEYS & _touched)))

print("\n[8] 프롬프트 생성")
p = oag.actions_prompt("ko")
check("모든 액션이 프롬프트에 포함", all(n in p for n in oag.ACTIONS), "")
check("언어 폴백(모르는 언어 → ko)", oag.actions_prompt("xx") == p)

print("\n" + "=" * 62)
if fails:
    print(f"❌ 실패 {len(fails)}건: {fails}")
    sys.exit(1)
print("✅ 전체 통과")

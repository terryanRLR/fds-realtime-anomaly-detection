# 🛡 FDS QA Dashboard — 디버깅 & 최적화 리포트 **(1차 16건 상세)**

> 📎 **이 문서는 `DASHBOARD_개선_리포트_v2.md` 와 중복이 아니다 — 짝이다.**
> · **이 문서(1차)** — 16건의 **상세 내역** (위치·문제·수정). 아래 전부.
> · `DASHBOARD_개선_리포트_v2.md`(2차) — 추가 12건 상세 + 1·2차 통합 요약(합계 28건).
>
> v2 는 1차의 상세를 다시 싣지 않고 **건수만** 집계한다. 1차 내용을 보려면 이 문서를 봐야 한다.

## 📋 요약

총 **16건**의 이슈를 발견하여 수정 완료했습니다.

| 분류 | 건수 | 심각도 |
|------|------|--------|
| 🐛 버그 (Bug) | 6 | Critical ~ Medium |
| ⚡ 성능 최적화 (Performance) | 5 | Medium |
| 🧹 코드 품질 (Quality) | 3 | Low ~ Medium |
| 🔒 안정성 (Robustness) | 2 | Medium |

---

## 🐛 버그 수정

### Fix #1 — 파일 핸들 누수 (File Handle Leak)
- **위치**: `load_eval_result()` (L239~241)
- **문제**: `json.load(open(p))` 패턴은 파일을 열기만 하고 닫지 않음. GC가 처리해주지만 장시간 운영 시 파일 디스크립터 고갈 가능
- **수정**: `with open(p) as f:` 컨텍스트 매니저 사용

### Fix #2 — 확률 바 O(n²) 연산 + float 동치비교
- **위치**: `prob_bars()` (L256~263)
- **문제**: 루프 내에서 매 반복마다 `max(v*100 for v in proba_dict.values())` 재계산 → O(n²). 또한 부동소수점 `==` 비교는 정밀도 이슈 가능
- **수정**: `max_pct`를 루프 밖에서 1회만 계산 → O(n)

### Fix #3 — Bare `except:` 무조건 삼킴
- **위치**: `_do_llm_analysis()` 내 자동발송 (L512~522)
- **문제**: `except:` 는 `KeyboardInterrupt`, `SystemExit` 포함 모든 예외를 잡아 디버깅 불가
- **수정**: `except Exception:` 으로 변경

### Fix #7 — 차트 막대 색상이 배경과 동일 (보이지 않음)
- **위치**: 세션05 확률 바차트 (L1150)
- **문제**: 비-top 클래스 막대 색상이 `T['bg_card']` → 배경색과 동일해서 **투명하게 렌더링**
- **수정**: `T['text_muted']` 로 변경하여 시각적으로 구분 가능

### Fix #10 — 폴더 배치처리 CSV 미캐싱
- **위치**: tab5 폴더 배치 (L1073)
- **문제**: `pd.read_csv(csv_files[0])` 캐시 없이 매번 디스크 I/O
- **수정**: `load_test_df()` 캐시 함수 활용 + 읽기 실패 시 에러 핸들링 추가

### Fix #11 — 이상거래 판정 로직 문서화 (잠재 버그)
- **위치**: 탐지 실행 (L1084)
- **문제**: `is_anomaly = fraud_type!='m' or risk_score>=threshold` — 사기 유형이면 risk_score 무관하게 **무조건** 이상거래. 의도적일 수 있으나 주의 필요
- **수정**: 의도를 명확히 하는 주석 추가. 만약 risk_score 기반 필터링이 필요하면 `and`로 변경 고려

---

## ⚡ 성능 최적화

### Fix #4 — test.csv 캐시 함수 추가
- **문제**: `pd.read_csv(test_path)` 가 tab2에서 버튼 클릭마다 디스크에서 재읽기
- **수정**: `@st.cache_data` 래핑된 `load_test_df(path)` 함수 신규 추가

### Fix #6 — `get_available_models()` 캐시
- **문제**: `Path.exists()` + `Path.glob("*.pkl")` 매 rerun마다 디스크 I/O
- **수정**: `@st.cache_data(ttl=30)` 추가 — 30초간 캐시 유지

### Fix #8 — `session_state` 초기화 통합
- **문제**: 초기값 설정이 코드 곳곳에 흩어져 있어 관리 어려움 + 매 rerun마다 조건분기 반복
- **수정**: `_DEFAULTS` 딕셔너리로 통합하여 한곳에서 일괄 관리

### Fix #12 — JavaScript 폴링 최적화
- **문제**: `setTimeout` 3회 + `setInterval(2초)` 30초 + `MutationObserver` 60초 → 과도한 DOM 조작
- **수정**: setTimeout 2회로 축소, interval 3초/15초로 조정, observer 30초로 단축

### Fix #13 — MutationObserver 디바운싱
- **문제**: DOM 변경마다 `fixSidebarBtns()` 즉시 호출 → Streamlit rerender 시 수백 회 연속 실행 가능
- **수정**: 200ms 디바운스 타이머 적용

---

## 🔒 안정성 강화

### Fix #14 — `eval_result.json` 파싱 실패 방어
- **문제**: 손상된 JSON 파일 시 `json.JSONDecodeError` 로 대시보드 전체 크래시
- **수정**: `try/except` 로 `JSONDecodeError`, `UnicodeDecodeError` 처리 → `None` 반환

### Fix #16 — 사이드바 eval_data 중첩 키 안전 접근
- **문제**: `eval_data["model_comparison"]["LightGBM"]["macro_f1"]` — LightGBM 키 없거나 구조 변경 시 `KeyError` 크래시
- **수정**: `try/except (KeyError, TypeError)` 래핑 → 실패 시 `0.0` 폴백

---

## 🔮 추가 개선 제안 (미적용)

다음 단계로 고려할 수 있는 추가 개선사항입니다:

1. **CSS를 별도 파일로 분리** — 1200줄 중 약 30%가 CSS. `assets/theme.css.template` 으로 분리하면 유지보수성 대폭 향상
2. **HTML 템플릿 엔진 도입** — 인라인 f-string HTML이 가독성을 크게 저해. `jinja2` 템플릿 또는 Streamlit `st.html()` 컴포넌트 활용
3. **에러 바운더리 패턴** — 각 세션(01~05)을 `try/except`로 래핑하여 한 세션의 에러가 다른 세션에 영향주지 않도록
4. **pipeline 모듈 lazy import 최적화** — `from pipeline.xxx import ...` 가 버튼 클릭 시마다 호출됨. `@st.cache_resource`로 모듈 레벨 캐싱 고려
5. **Plotly 레이아웃 상수 통합** — `PLOTLY_LAYOUT`, `_M_DEFAULT`, `_M_COMPACT` 등을 테마 변경 시 자동 갱신되도록 함수화
6. **다크/라이트 모드 자동 감지** — `prefers-color-scheme` 미디어 쿼리로 OS 설정에 따른 자동 테마 전환

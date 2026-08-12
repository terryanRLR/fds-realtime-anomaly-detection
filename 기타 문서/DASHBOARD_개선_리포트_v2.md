# 🛡 FDS QA Dashboard — 디버깅 & 최적화 & 추가개선 리포트 (v3 → v4) **(2차 12건 상세)**

> 📎 **이 문서는 `DASHBOARD_개선_리포트.md` 와 중복이 아니다 — 짝이다.**
> · `DASHBOARD_개선_리포트.md`(1차) — 16건의 **상세 내역**.
> · **이 문서(2차)** — 추가 12건 상세 + 1·2차 통합 요약(합계 28건).
>
> 아래 요약표의 '1차' 열은 **건수만** 옮긴 것이다. 1차의 상세는 위 문서에 있다.

## 📋 전체 요약

| 분류 | 1차 | 2차 추가 | 합계 |
|------|-----|----------|------|
| 🐛 버그 (Bug) | 6 | — | 6 |
| ⚡ 성능 최적화 (Performance) | 5 | 1 | 6 |
| 🧹 코드 품질 (Quality) | 3 | 4 | 7 |
| 🔒 안정성 (Robustness) | 2 | 1 | 3 |
| 🎨 UX 개선 (UX) | — | 2 | 2 |
| 🔧 랜덤 시드 기본값 | — | 4곳 | 4 |
| **합계** | **16** | **12** | **28** |

- 원본: **1,236줄** → 개선: **1,362줄** (+126줄, 주로 헬퍼/안전장치 추가)

---

## 🔧 랜덤 시드 기본값 변경 (42 → -1)

모든 사용자 입력 시드의 기본값을 **42(고정) → -1(자동 랜덤)** 으로 변경했습니다.

| 위치 | 설명 | 변경 |
|------|------|------|
| 세션04 합성데이터 QA | `syn_seed` | `42` → `-1` |
| 세션05 tab2 test.csv | `t2_seed` | `42` → `-1` |
| 세션05 tab3 train.csv | `t3_seed` | `42` → `-1` |
| 세션05 tab4 합성 생성 | `t4_seed` | `42` → `-1` |

> 📌 분포 비교 히스토그램의 내부 샘플링 (`random_state=42`)은 재현성을 위해 유지

---

## 🆕 2차 추가 개선 사항 (6개 제안 → 모두 적용)

### 개선 ① HTML 헬퍼 함수 도입

반복되는 HTML 패턴을 함수로 통합하여 코드 가독성과 일관성 대폭 향상:

```python
# Before (매번 이렇게 써야 했음)
st.markdown('<div class="alert-box alert-warn">⚠ 경고 메시지</div>', unsafe_allow_html=True)

# After (한 줄로 끝)
alert_box("⚠ 경고 메시지", "warn")
```

추가된 헬퍼 함수:
- `alert_box(msg, level)` — info/warn/error/ok 알림 박스
- `badge(text, style)` — danger/safe/warn 뱃지
- `themed_text(text, color_key, size, mono)` — 테마 반응형 텍스트

### 개선 ② Plotly 레이아웃 함수화

```python
# Before: 상수라서 테마 변경 시 수동 갱신 필요
PLOTLY_LAYOUT = dict(paper_bgcolor=..., font=dict(color=T['text_secondary']...))

# After: 함수 호출로 항상 현재 테마 반영
def get_plotly_layout(**overrides): ...
def styled_axis(fig, grid_color=...): ...  # X/Y축 공통 스타일
```

`styled_axis()` 헬퍼로 매번 반복되던 `update_xaxes + update_yaxes` 패턴도 1줄로 단축.

### 개선 ③ 에러 바운더리 (Error Boundary)

- `session_error_boundary(name)` 컨텍스트 매니저 추가
- 세션05 탐지 결과 표시 블록에 `try/except` 적용
- 에러 발생 시 대시보드 전체가 아닌 **해당 패널만** 에러 표시 + 접을 수 있는 상세 로그

```
❌ 탐지 결과 렌더링 오류: KeyError: 'proba_dict'
🔍 상세 에러 로그 [▶ 펼치기]
```

### 개선 ④ Pipeline 모듈 캐시 (Lazy Import)

```python
@st.cache_resource
def _get_ml_classifier(model_path):
    """ML 분류기 인스턴스를 캐시하여 매 탐지마다 재로드 방지"""
    from pipeline.ml_classifier import MLClassifier
    return MLClassifier(model_path)
```

- `MLClassifier` 를 `@st.cache_resource` 로 캐싱 → 모델 파일을 매번 디스크에서 읽지 않음
- 세션05 탐지 실행 + ML 테스트 버튼 양쪽에 적용

### 개선 ⑤ 테마 전환 애니메이션

CSS `transition` 속성 추가로 테마 전환 시 부드러운 색상 변화:

```css
html, body, [data-testid="stAppViewContainer"] {
  transition: background-color 0.3s ease, color 0.3s ease;
}
.kpi-card, .result-panel, .fraud-type-card, .alert-box {
  transition: all 0.3s ease;
}
```

### 개선 ⑥ OS 다크/라이트 모드 감지

사이드바에 **"🌗 OS 테마 자동 감지"** 버튼 추가:
- JavaScript `prefers-color-scheme` 미디어쿼리로 OS 설정 감지
- 현재 다크 모드 → Arctic Frost (라이트) 전환
- 현재 라이트 모드 → Cyber Teal (다크) 전환
- 테마 스와치 아래에 위치하여 직관적 접근

---

## 📊 1차 수정 사항 (이전 리포트 요약)

### 🐛 버그 수정 (6건)
1. **파일 핸들 누수** — `open()` without `close()` → `with` 문 사용
2. **prob_bars O(n²)** — 루프 내 `max()` 재계산 → 외부에서 1회 계산
3. **bare `except:`** — `except Exception:` 으로 변경
4. **차트 막대 투명** — `bg_card` 색상 → `text_muted` 로 가시성 확보
5. **폴더 배치 CSV 미캐싱** — `load_test_df()` 활용 + 에러 핸들링
6. **이상거래 판정 로직** — 의도 명확화 주석 추가

### ⚡ 성능 최적화 (5건)
7. **test.csv 캐시** — `@st.cache_data` 래핑
8. **get_available_models() 캐시** — `@st.cache_data(ttl=30)`
9. **session_state 통합** — `_DEFAULTS` 딕셔너리로 일괄 관리
10. **JS 폴링 최적화** — setTimeout/setInterval 횟수 축소
11. **MutationObserver 디바운싱** — 200ms 디바운스 적용

### 🔒 안정성 강화 (2건)
12. **JSON 파싱 방어** — `JSONDecodeError` + `UnicodeDecodeError` 처리
13. **eval_data 중첩 키 안전 접근** — `try/except (KeyError, TypeError)`

---

## 📁 산출물

| 파일 | 설명 |
|------|------|
| `dashboard.py` | v4 개선 완료 버전 |
| `DASHBOARD_개선_리포트_v2.md` | 이 리포트 |

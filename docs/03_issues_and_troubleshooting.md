# 03. 이슈 & 트러블슈팅 — 마스터 인덱스

이 프로젝트에서 실제로 발생한 문제 **72건**을 증상 · 재현조건 · 원인 · 해결까지 추적한 기록입니다.
분량이 커서 계층별로 나눴고, 이 문서가 전체 색인 역할을 합니다.

| 문서 | 범위 | 건수 |
|---|---|---|
| [**03a**](03a_issues_data_modeling.md) | 데이터 · 모델링 — 전처리, 통계검정, 학습, 임계값 | 18 |
| [**03b**](03b_issues_dashboard_pipeline.md) | 대시보드 · 파이프라인 — 모델을 화면에 태우는 구간 | 24 |
| [**03c**](03c_issues_ops_runtime.md) | 관제 · 런타임 — 24시간 켜 두는 시스템에서만 나오는 것 | 30 |

---

## 이 프로젝트를 관통하는 하나의 주제 — 조용한 실패

72건을 다 정리하고 나서 보이는 패턴이 하나 있습니다.

> **치명적이었던 버그는 전부 예외를 던지지 않았습니다.**

스택 트레이스가 뜨는 버그는 5분이면 고칩니다. 이 프로젝트에서 시간을 잡아먹은 것들은
**화면이 멀쩡히 그려지고, 저장도 되고, 로그도 남는데, 값이 틀린** 것들이었습니다.

### 조용한 실패 12건

| # | 증상 | 진짜 원인 | 왜 안 잡혔나 |
|---|---|---|---|
| [A-1](03a_issues_data_modeling.md#a-1) | Macro-F1 0.7103 — 좋아 보였다 | `is_fraud` 라벨 누수 | **성능이 올라간다.** 나빠져야 의심한다 |
| [B-3](03b_issues_dashboard_pipeline.md#b-3) | 전 지표가 **정확히 0.0** | 정수 클래스 vs 문자 라벨 | 0.0 은 "모델이 나쁘다"로 읽힌다 |
| [B-2](03b_issues_dashboard_pipeline.md#b-2) | 입력을 바꿔도 결과가 같다 | `"1" in np.array([0,1,2,3])` 이 항상 False | 예측은 정상적으로 나온다 |
| [B-8](03b_issues_dashboard_pipeline.md#b-8) | 파일을 바꿔도 화면 그대로 | 캐시 키 인자에 `_` 를 붙여 해싱 제외 | 캐시는 원래 안 보인다 |
| [B-9](03b_issues_dashboard_pipeline.md#b-9) | macro-F1 이 0.7%p 낮다 | NaN 을 기본값으로 대체 | 0.6070 도 그럴듯한 숫자다 |
| [B-11](03b_issues_dashboard_pipeline.md#b-11) | **보이는 본문 ≠ 발송 본문** | Streamlit 이 `key` 있으면 `value=` 무시 | 화면도 발송도 성공한다. **3회 재발** |
| [B-18](03b_issues_dashboard_pipeline.md#b-18) | 조용한 오예측 | dict 키 순서로 피처 배열 | 값이 뒤섞여도 예측은 나온다 |
| [C-2](03c_issues_ops_runtime.md#c-2) | 시간대 판별이 전부 오진 | `strftime()` 이 TEXT 반환 → 비교가 **항상 참** | SQLite 타입 서열은 안 보인다 |
| [C-3](03c_issues_ops_runtime.md#c-3) | 판정 이력이 사라진다 | `detections` UPSERT | 최신 값은 멀쩡히 있다 |
| [C-5](03c_issues_ops_runtime.md#c-5) | 재검증이 "성공"한다 | 마스킹본으로 예측 → 기본값으로 메워짐 | **예외 없이 숫자가 나온다** |
| [C-6](03c_issues_ops_runtime.md#c-6) | 판정이 이상하다 | 더미 모드 15% 랜덤 | 반환값으로 진짜와 구분 불가 |
| [C-11](03c_issues_ops_runtime.md#c-11) | 경보가 절반으로 줄었다 | 슬라이더 `step=0.01` 이 `0.005` 를 못 만듦 | 저장도 되고 로그도 남는다 |

### 이 프로젝트가 조용한 실패에 대응한 방식

버그를 하나씩 고치는 것으로는 재발을 막지 못했습니다.
**같은 병이 3번 재발**한 [B-11](03b_issues_dashboard_pipeline.md#b-11) 이후 방식이 바뀝니다.

| 대응 | 구체적으로 | 어디서 나왔나 |
|---|---|---|
| **불변식을 테스트로 고정** | `selftest_preprocessor` 가 "58피처 전부 99.9% 이상 일치"를 검사 | [B-12](03b_issues_dashboard_pipeline.md#b-12) |
| **정적 검사로 재발 차단** | `selftest_ui` §14 — 앱 파일에 `_PROMPT_SLOTS` 가 다시 나타나면 **실패** | [B-11](03b_issues_dashboard_pipeline.md#b-11) |
| **구현을 한 벌로** | 편집기·발송 확인 카드를 공용 모듈로. 줄 수는 +64 늘었지만 두 벌이 한 벌이 됐다 | [B-11](03b_issues_dashboard_pipeline.md#b-11) · [C-11](03c_issues_ops_runtime.md#c-11) |
| **폴백을 금지** | 더미 모드 감지 시 재검증 **거부**. 조용히 계속하지 않는다 | [C-6](03c_issues_ops_runtime.md#c-6) |
| **무거운 작업 전에 차단** | `mask_damage()` 가 모델 로드 **전에** 막는다 | [C-5](03c_issues_ops_runtime.md#c-5) |
| **못 하는 것을 화면에 그린다** | 임계값 시뮬레이터의 데이터 없는 구간을 **회색 점선**으로 | [C-19](03c_issues_ops_runtime.md#c-19) |
| **에러 대신 안내** | 버전 미달 시 `st.stop()` + "무엇을 하면 되는지" | [C-24](03c_issues_ops_runtime.md#c-24) |
| **오염 상태를 스스로 보고** | `diagnose_timestamps()` 가 🩺 진단 탭에 현재 오염도 표시 | [C-1](03c_issues_ops_runtime.md#c-1) |

---

## 이슈 기록 형식

각 항목은 아래 형식을 따릅니다.

- **증상** — 무엇이 이상했는가
- **재현 조건** — 어떤 데이터 · 설정 · 코드 경로에서 발생하는가
- **원인 진단** — 왜 그런 현상이 생겼는가
- **해결/결정** — 실제로 취한 조치 (또는 **안 하기로 한 이유**)
- **근거** — 이 기록의 출처 (패치노트 버전, 코드 위치, 노트북 셀)
- **상태** — `✅ 해결` / `⚠️ 완화·부분` / `🔲 미해결` / `설계 결정`

**심각도**: 🔴 치명 · 🟠 중대 · 🟡 보통 · 🟢 경미

> **표기 원칙** — 코드·출력으로 직접 확인되는 것과 문서로만 추정되는 것을 구분합니다.
> 후자는 본문에 "추정" 을 명시했습니다.

---

## 전체 이슈 목록

### 🔴 치명 (19건)

| # | 제목 | 상태 |
|---|---|---|
| [A-1](03a_issues_data_modeling.md#a-1) | `is_fraud` 라벨 누수 — Macro-F1 0.7103 이 거짓이었다 | ✅ |
| [A-2](03a_issues_data_modeling.md#a-2) | look-ahead 의심 피처 5개 | ⚠️ **미확정** |
| [A-14](03a_issues_data_modeling.md#a-14) | `l` 유형 사실상 탐지 실패 (Recall 0.048) | 🔲 **처방 확보** |
| [A-17](03a_issues_data_modeling.md#a-17) | **3차 전처리에서 실질 신호 9개가 함께 사라졌다** | 🔲 **복원 제안** |
| [B-1](03b_issues_dashboard_pipeline.md#b-1) | joblib 번들을 `pickle.load` → 전체 더미 모드 | ✅ |
| [B-2](03b_issues_dashboard_pipeline.md#b-2) | 범주형 9개가 입력과 무관하게 0으로 고정 | ✅ |
| [B-3](03b_issues_dashboard_pipeline.md#b-3) | 정수 클래스 vs 문자 라벨 → 전 지표 0.0 | ✅ |
| [B-4](03b_issues_dashboard_pipeline.md#b-4) | 더미 모드 `risk` 역전 | ✅ |
| [B-11](03b_issues_dashboard_pipeline.md#b-11) | 위젯 `value=` 함정 (3회 재발) | ✅ |
| [B-20](03b_issues_dashboard_pipeline.md#b-20) | 이메일 미리보기 HTML 인젝션 | ✅ |
| [C-1](03c_issues_ops_runtime.md#c-1) | 같은 컬럼에 UTC 와 KST 혼재 | ✅ |
| [C-2](03c_issues_ops_runtime.md#c-2) | `strftime()` TEXT 반환 → 비교가 항상 참 | ✅ |
| [C-3](03c_issues_ops_runtime.md#c-3) | UPSERT 가 판정을 조용히 덮어쓴다 | ✅ |
| [C-4](03c_issues_ops_runtime.md#c-4) | LLM 근거가 발송 순간 사라진다 | ✅ |
| [C-5](03c_issues_ops_runtime.md#c-5) | 마스킹본 재예측이 "성공"한다 | ✅ |
| [C-6](03c_issues_ops_runtime.md#c-6) | 더미→판정→재학습 폐쇄 오염 루프 | ✅ |
| [C-11](03c_issues_ops_runtime.md#c-11) | 슬라이더가 `0.005` 를 만들 수 없었다 | ✅ |
| [C-22](03c_issues_ops_runtime.md#c-22) | 자체 테스트가 운영 DB 를 오염 (2회) | ✅ |
| [C-29](03c_issues_ops_runtime.md#c-29) | **인증이 없다** | 🔲 **미해결** |

### 🟠 중대 (27건)

<details>
<summary>펼쳐 보기</summary>

| # | 제목 | 상태 |
|---|---|---|
| [A-3](03a_issues_data_modeling.md#a-3) | 2계층 구조의 오류 전파 | ✅ 기각 |
| [A-4](03a_issues_data_modeling.md#a-4) | 임계값 0 에서 Macro-F1 붕괴 | ✅ |
| [A-5](03a_issues_data_modeling.md#a-5) | FN 고정 단가가 최대 47% 어긋남 | ✅ 완화 |
| [A-6](03a_issues_data_modeling.md#a-6) | 생성 AI 증강이 성능을 떨어뜨림 | ✅ 미채택 |
| [A-15](03a_issues_data_modeling.md#a-15) | 유형 정확도 53.5% | 🔲 한계 |
| [B-5](03b_issues_dashboard_pipeline.md#b-5) | 48피처 모델 × 81피처 데이터 | ✅ |
| [B-6](03b_issues_dashboard_pipeline.md#b-6) | 조립이 필요한 모델 '세트' | ✅ |
| [B-7](03b_issues_dashboard_pipeline.md#b-7) | 세션5 입력이 전부 원본 행 → FeatureBridge | ✅ |
| [B-8](03b_issues_dashboard_pipeline.md#b-8) | Streamlit 캐시 무효화 전멸 | ✅ |
| [B-9](03b_issues_dashboard_pipeline.md#b-9) | NaN 대체가 macro-F1 0.7%p 손실 | ✅ |
| [B-10](03b_issues_dashboard_pipeline.md#b-10) | 인코더를 제대로 적용하면 더 망가진다 | ✅ 금지 |
| [B-13](03b_issues_dashboard_pipeline.md#b-13) | 자동입력 버튼이 누르면 죽었다 | ✅ |
| [B-14](03b_issues_dashboard_pipeline.md#b-14) | '실재하지 않는 계좌'를 그리고 있었다 | ✅ |
| [B-15](03b_issues_dashboard_pipeline.md#b-15) | `predict_batch` 단건/배치 불일치 | ✅ |
| [B-18](03b_issues_dashboard_pipeline.md#b-18) | dict 키 순서로 피처 배열 | ✅ |
| [B-21](03b_issues_dashboard_pipeline.md#b-21) | 발송 성공 뱃지가 '예외 없음' 기준 | ✅ |
| [B-24](03b_issues_dashboard_pipeline.md#b-24) | `docs/` 를 RAG 가 먹는다 | ✅ |
| [C-7](03c_issues_ops_runtime.md#c-7) | 수동 탐지가 관제 화면에 없었다 | ✅ |
| [C-8](03c_issues_ops_runtime.md#c-8) | 경보 등급이 실제 임계값을 안 읽었다 | ✅ |
| [C-9](03c_issues_ops_runtime.md#c-9) | 브라우저 오디오 정책 | ✅ |
| [C-10](03c_issues_ops_runtime.md#c-10) | 주입 HTML 버튼은 못 쓴다 | ✅ |
| [C-12](03c_issues_ops_runtime.md#c-12) | 미탐 등록 창구 부재 | ✅ |
| [C-13](03c_issues_ops_runtime.md#c-13) | 검색이 최근 N건 안에서만 | ✅ |
| [C-18](03c_issues_ops_runtime.md#c-18) | 신규 DB 첫 실행 시 앱 전체 사망 | ✅ |
| [C-19](03c_issues_ops_runtime.md#c-19) | 임계값 시뮬레이터 선택 편향 | ✅ 표기 |
| [C-20](03c_issues_ops_runtime.md#c-20) | 경보가 과해서 죽는다 | ✅ |
| [C-24](03c_issues_ops_runtime.md#c-24) | requirements 하한 미달 → 앱 자체가 안 뜸 | ✅ |

</details>

### 🟡🟢 보통 · 경미 (26건)

<details>
<summary>펼쳐 보기</summary>

| # | 제목 | 상태 |
|---|---|---|
| [A-7](03a_issues_data_modeling.md#a-7) | 규칙+ML 결합 순이득 없음 | ✅ 미채택 |
| [A-8](03a_issues_data_modeling.md#a-8) | `Time_difference_seconds` 음수 156건 | ✅ |
| [A-9](03a_issues_data_modeling.md#a-9) | `_composite_cols` 미정의 — 수정 셀도 고장 | ✅ |
| [A-10](03a_issues_data_modeling.md#a-10) | 거래일자 2003~2058 | ✅ |
| [A-11](03a_issues_data_modeling.md#a-11) | 고객·계좌 그룹 누수 | ✅ |
| [A-12](03a_issues_data_modeling.md#a-12) | 잔액 항등식 0.65% | ✅ 정책 |
| [A-13](03a_issues_data_modeling.md#a-13) | 이름 키워드 자동 추론 오분류 | ✅ |
| [A-16](03a_issues_data_modeling.md#a-16) | ISF — 실행됐으나 피처 결합은 미실행 | ✅ **실측 답변** |
| [A-18](03a_issues_data_modeling.md#a-18) | `cert_or_auth_risk` 이름·내용 불일치 | ✅ |
| [B-12](03b_issues_dashboard_pipeline.md#b-12) | `Time_difference_seconds` 99.866% | ✅ |
| [B-16](03b_issues_dashboard_pipeline.md#b-16) | 유형 A 막대가 안 보인다 (값이 0) | ✅ |
| [B-17](03b_issues_dashboard_pipeline.md#b-17) | 온보딩 버튼 먹통 | ✅ |
| [B-19](03b_issues_dashboard_pipeline.md#b-19) | 브리지 없는 환경 — 테스트 설계 실수 | ✅ |
| [B-22](03b_issues_dashboard_pipeline.md#b-22) | 데이터셋 캐시에 mtime 없음 | ✅ |
| [B-23](03b_issues_dashboard_pipeline.md#b-23) | 기본 데이터셋이 라벨 없는 `test.csv` | ✅ |
| [C-14](03c_issues_ops_runtime.md#c-14) | 챗봇 `set_sla` 조용한 실패 | ✅ |
| [C-15](03c_issues_ops_runtime.md#c-15) | CSV 행 번호가 거래 ID 로 둔갑 | ✅ |
| [C-16](03c_issues_ops_runtime.md#c-16) | `watch_inbox` 는 아무도 안 쓰는 키 | ✅ |
| [C-17](03c_issues_ops_runtime.md#c-17) | `coverage()` 가 132% 반환 | ✅ |
| [C-21](03c_issues_ops_runtime.md#c-21) | 잠금이 조사 중에 풀린다 | ✅ |
| [C-23](03c_issues_ops_runtime.md#c-23) | 미래 하트비트를 '정상'이라 말함 | ✅ |
| [C-25](03c_issues_ops_runtime.md#c-25) | watchdog 대신 5초 폴링 | ✅ 설계 |
| [C-26](03c_issues_ops_runtime.md#c-26) | 윈도우 알림이 서버 PC 에 떴다 | ✅ |
| [C-27](03c_issues_ops_runtime.md#c-27) | 비한국어 연속 렌더 자동검증 불가 | 🔲 **보류** |
| [C-28](03c_issues_ops_runtime.md#c-28) | 계좌이력 필드명 다국어화 | 🔲 **보류** |
| [C-30](03c_issues_ops_runtime.md#c-30) | `st.components.v1.html` 지원 종료 | ⚠️ 폴백만 |

</details>

---

## 상태별 집계

| 상태 | 건수 | 항목 |
|---|---|---|
| ✅ **해결** | 58 | 대부분 |
| ⚠️ **완화 · 부분** | 4 | [A-2](03a_issues_data_modeling.md#a-2) look-ahead · [A-5](03a_issues_data_modeling.md#a-5) FN 단가 · [B-7](03b_issues_dashboard_pipeline.md#b-7) 브리지 공식 2건 · [C-30](03c_issues_ops_runtime.md#c-30) 폐기 API |
| 설계 결정 | 3 | [A-12](03a_issues_data_modeling.md#a-12) 잔액 항등식 · [B-10](03b_issues_dashboard_pipeline.md#b-10) 인코더 금지 · [C-25](03c_issues_ops_runtime.md#c-25) 폴링 |
| 🔲 **미해결** | 8 | 아래 표 |

### 🔲 미해결 8건 — 우선순위 순

| # | 항목 | 왜 안 됐나 | 다음 행동 |
|---|---|---|---|
| [C-29](03c_issues_ops_runtime.md#c-29) | 🔴 **인증 없음** | 발표·시연용 임시 공개 | 운영 전환 전 **필수**. `ngrok --basic-auth` 또는 앱 로그인 |
| [A-14](03a_issues_data_modeling.md#a-14) | 🔴 `l` 유형 Recall 0.048 | 100건 few-shot. 증강도 실패 | 고령층 표적 전용 파생변수 탐색 |
| [A-2](03a_issues_data_modeling.md#a-2) | 🔴 look-ahead 5피처 | 명세 해석으로 유지, 미검증 | 명세 원문 확인 → `as-of` 재설계 → 재측정 |
| [A-17](03a_issues_data_modeling.md#a-17) | 🔴 **3차에서 9피처 소실** | 1차→2차 재설계 시 함께 사라짐. 기록 없음 | 복원 시 최고 Macro-F1 **0.6395→0.6779** · `l` F1 **3.2배**. 별도 홀드아웃 재확인 필요 |
| [A-15](03a_issues_data_modeling.md#a-15) | 🟠 유형 정확도 53.5% | `e·f·g`, `k↔b`, `d` 신호 유사 | 확률 분포 표시 + 담당자 확인으로 완화 중 |
| [C-27](03c_issues_ops_runtime.md#c-27) | 🟡 i18n 회귀 자동검증 불가 | 실사용 영향 없음 · 의도적 보류 | 하네스 우회 또는 위젯 패턴 변경 (둘 다 대가 있음) |
| [C-28](03c_issues_ops_runtime.md#c-28) | 🟢 계좌이력 필드명 i18n | 넷을 동시에 고쳐야 하는 사전 마이그레이션 | 손댈 때 4곳 한 번에 |

### 🔲 팀원 확인이 필요한 것

| 항목 | 무엇을 확인해야 하나 |
|---|---|
| [A-9](03a_issues_data_modeling.md#a-9) `_composite_cols` | 이 저장소가 복원한 5개 컬럼이 팀 의도와 같은가 |
| [B-3](03b_issues_dashboard_pipeline.md#b-3) 모델 재학습 의혹 | `lgbm_fds.pkl` / `rf_fds.pkl` 이 검증셋 포함 재학습본인가 |
| [B-7](03b_issues_dashboard_pipeline.md#b-7) 브리지 공식 | `balance_depletion_ratio` · `high_risk_device_flag` 생성 공식 |
| [A-17](03a_issues_data_modeling.md#a-17) 9피처 소실 | 1차→2차에서 33개를 뺀 것이 **의도인가 누락인가** |
| 1·2차 전처리 노트북 | 존재하는가 (현재 결과 parquet 만 남음 → [`09`](09_reconstruction_log.md) 에서 재구성) |
| Baseline 5모델 비교 코드 | 존재하는가 (PDF 결과만 남음 → [노트북 11](../notebooks/team_final/11_baseline_and_anomaly_score.ipynb) 로 재현) |

---

## 근거 자료

이 문서 계열의 출처입니다.

| 자료 | 규모 | 무엇이 들어 있나 |
|---|---|---|
| [`PATCH_NOTES5.md`](../PATCH_NOTES5.md) | 191KB · 헤딩 279개 | **v10 → v39** 버전별 패치 + 버전마다 `트러블슈팅 추가` 절 |
| [`기타 문서/FIX_REPORT.md`](../기타%20문서/FIX_REPORT.md) | 33KB | **v5.0 → v6.5** 버그 검증 리포트 (Critical/Medium/Minor 등급) |
| [`OPS_BACKLOG.md`](../OPS_BACKLOG.md) | 16KB | **아직 안 한 일**만 모은 목록 + `일부러 안 하기로 한 것` |
| [`pipeline/ARCHITECTURE.md`](../pipeline/ARCHITECTURE.md) | — | 모듈 설계 결정 + §8 개발 중 발견한 버그 |
| [`reports/18_대시보드_구현내역_일자별.pdf`](../reports/18_대시보드_구현내역_일자별.pdf) | 19KB | 5주차 일자별 패치노트 (2026-07-29 ~ 07-30) |
| 노트북 실행 출력 | 138건 | 수치 근거 (Macro-F1, 혼동행렬, SHAP, 임계값 스캔) |
| [`reports/05_중간보고서_튜터피드백정리.pdf`](../reports/05_중간보고서_튜터피드백정리.pdf) | — | 튜터·멘토 피드백 원문 |
| 코드 주석 | — | `🐛 FIX(v5)` 등 diff 추적 마커 |

> 새 이슈를 발견하면 해당 계층 문서(03a/03b/03c)에 같은 형식으로 추가하고,
> 이 문서의 목록과 집계표를 함께 갱신해 주세요.

# 02. 분석 파이프라인 — 원본 CSV 에서 운영 임계값까지

원본 거래 1건이 어떤 변환을 거쳐 판정과 알림이 되는지, **전 구간을 한 번에** 따라갑니다.
각 단계마다 실제 코드 위치와 실측 수치를 함께 답니다.

```
train.csv (120,000 × 64)
   │
   │ ① 타입 명시 분류 · 품질 점검                     노트북 01
   │ ② 형식 검증 · 음수 금액 · 날짜 · 그룹 누수        노트북 02
   │ ③ Time_difference · 금액 부호 · 층화그룹 분할     노트북 03
   │ ④ 통계 검정 (통합 vs 정상대비 이진)               노트북 04
   │ ⑤ 파생변수 7종 · 인코딩                          노트북 05
   ▼
X_tr (96,140 × 58) / X_va (23,860 × 58)
   │
   │ ⑥ LightGBM 13-class 학습                        노트북 06
   │ ⑦ 아키텍처 비교 (한방 vs 2계층)                   노트북 07
   │ ⑧ 비용 기반 임계값                               노트북 08
   │ ⑨ 규칙+ML 결합 검증                              노트북 09
   │ ⑩ 생성 증강 검증                                 노트북 10
   ▼
models/  (모델 + 메타 4종)  ·  th_review = 0.005
   │
   │ ⑪ 원본 행 → 58피처 실시간 변환                   pipeline/preprocessor.py
   │ ⑫ 추론 → risk = 1 − P(m)                        pipeline/ml_classifier.py
   │ ⑬ 이중 임계값 등급 판정                          pipeline/detect_service.py
   │ ⑭ PII 마스킹 게이트                              pipeline/pii_masker.py
   │ ⑮ LLM 3단계 분석 + RAG 근거                      pipeline/llm_analyzer.py
   ▼
Slack / Email  +  fds_results.db  +  관제 콘솔 판정 루프
```

---

## [1] 원본 로드와 타입 분류 — 자동 추론을 쓰지 않은 이유

**노트북**: [`01_preprocessing_load_and_quality.ipynb`](../notebooks/team_final/01_preprocessing_load_and_quality.ipynb)

| 항목 | 값 |
|---|---|
| 입력 | `train_final.csv` 120,000행 × 64컬럼 |
| 결측 | **0건** (그래서 결측 처리 비교는 비중 축소) |
| 중복 행 | 0건 |
| 타깃 | `Fraud_Type` — `a`~`l` 각 100건 + `m` 118,800건 |

> 🐛 **이름 키워드 자동 추론은 여기서 첫 함정을 만든다.**
> `First_time_iOS_by_vulnerable_user` 는 0/1 플래그인데 이름에 `time` 이 들어가 datetime 으로 오분류된다.
> → §1-1 에서 컬럼을 **손으로** 분류한다. 파싱 6종(등록·계좌개설·거래·마지막 ATM/영업점·재개일)만 datetime.

**변환 전 문자열 사본을 따로 뜬다** — `train_raw = train.copy()`.
타입 변환 후에는 파싱 실패가 `NaT`/`NaN` 으로 삼켜져 **진짜 형식 위반이 안 잡히기 때문**입니다.

---

## [2] 데이터 무결성 — 발견된 품질 이슈 5가지

**노트북**: [`02_data_integrity_negative_dates_leakage.ipynb`](../notebooks/team_final/02_data_integrity_negative_dates_leakage.ipynb)

| # | 발견 | 판정 | 조치 |
|---|---|---|---|
| 1 | `Transaction_Amount` 음수 약 **30%** | **오류 아님** — 출금/입금 방향 | `Transaction_is_withdrawal` 파생 + 절댓값 분리. **제거 금지** |
| 2 | 거래일자 **2003~2058년** (미래 포함) | 시간 기반 분할 부적절 | `StratifiedGroupKFold` 채택 |
| 3 | 잔액 항등식 **0.65%** 만 성립 | 이상값 아님 — 합성 데이터 특성 | 후처리 강제 적용 **금지** 원칙 수립 |
| 4 | `Time_difference_seconds` 음수 **156건** | 비물리적 (최소 ≈ −33년) | 절댓값 대신 **NaN** → LightGBM 이 결측을 분기로 흡수 |
| 5 | 고객·계좌가 여러 유형에 걸쳐 중복 등장 | **그룹 누수 위험** | 개인식별자 41% · 계좌 24% 중복 → group split 필수 |

> **④가 왜 절댓값이 아니라 NaN 인가** — `-33년` 의 절댓값 `33년` 은 **없던 신호를 만들어낸다.**
> 결측은 "모른다"이고 절댓값은 "33년 걸렸다"는 거짓 주장이다.
> 이 판단은 나중에 시스템 쪽에서도 재확인된다 — [`03b` #B-12](03b_issues_dashboard_pipeline.md).

---

## [3] 분할 확정 — 층화 + 그룹

**노트북**: [`03_time_difference_amount_sign_split.ipynb`](../notebooks/team_final/03_time_difference_amount_sign_split.ipynb)

```
StratifiedGroupKFold(n_splits=5) → 80/20
  층화 축: Fraud_Type   (유형당 100건이라 층화 없이는 한쪽이 0건이 될 위험)
  그룹 축: 고객·계좌     (같은 사람이 train/valid 양쪽에 있으면 누수)
```

| 검증 항목 | 결과 |
|---|---|
| 고객 누수 | **0건** |
| 계좌 누수 | **0건** |
| train / valid | 96,140행 / 23,860행 |
| 13클래스 양쪽 분포 | 사기 12유형 각 100건 균등 유지 |
| IP/MAC 신규값 안전 처리 | 100% (Frequency Encoding — train fit, valid transform) |

동시에 만든 파생 2종이 이후 SHAP 상위권에 오릅니다.

| 파생 | SHAP 순위 |
|---|---|
| `Transaction_is_withdrawal` | **1위** (0.4471) |
| `Transaction_Amount_abs` | 3위 (0.2949) |

---

## [4] 통계 검정 — 이 프로젝트 통계 설계의 핵심

**노트북**: [`04_eda_and_statistical_testing.ipynb`](../notebooks/team_final/04_eda_and_statistical_testing.ipynb)

### 문제 — 13클래스 통합검정만 보면 모든 변수가 negligible 이다

정상 118,800건이 표본을 지배해 효과크기가 희석됩니다.

| 변수 | 13클래스 통합 (Kruskal-Wallis ε²) | 정상 대비 이진 재검정 (Cliff's δ) |
|---|---|---|
| `Distance` | 0.0022 → **negligible** | `a` 유형 **δ = 0.95 (large, 전체 최댓값)** |
| `Transaction_Amount_abs` | 0.0053 → negligible | δ = 0.395 (medium, 사기 큼) |
| `Account_balance` | 0.0040 → negligible | δ = −0.361 (medium, 사기 작음) |

**같은 변수, 정반대 결론.**

### 해법 — 두 단계 검정 설계

| 단계 | 수치형 | 범주형 | 이진 플래그 |
|---|---|---|---|
| ① 13클래스 통합 | Kruskal-Wallis H + ε² | Chi-square + Cramér's V | — |
| ② **정상 대비 1:1 재검정** | Mann-Whitney U + **Cliff's δ** | Chi-square + Cramér's V + Odds Ratio | **Phi + Odds Ratio** |

> **우선순위는 p-value 가 아니라 효과크기다.** 대규모 표본에서 p-value 는 항상 쉽게 유의해진다.

### ②에서만 드러난 신호

| 변수 | 결과 |
|---|---|
| `Transaction_is_withdrawal` | Phi = 0.142 · **OR = 41.4배** |
| `Flag_deposit_more_than_tenMillion` | p = 4.4e−23 |
| `Customer_rooting_jailbreak_indicator` | p = 4.8e−09 |
| `Account_release_suspention` | p = 2.8e−06 |

> ⚠️ **1차 EDA 는 `df_tr` 에서만 본다.** valid 를 보고 피처를 설계하면 그 자체가 누수다.
> 노트북 04 첫 셀에 이 원칙이 주석으로 박혀 있다.

---

## [5] 신호 시각화와 파생변수 7종

**노트북**: [`05_signal_visualization_features_encoding.ipynb`](../notebooks/team_final/05_signal_visualization_features_encoding.ipynb)

### 시각화 3종

| 방법 | 정의 | 무엇을 본다 |
|---|---|---|
| **z-score 히트맵** | 유형별 중앙값을 정상 `m` 의 평균/표준편차로 환산 | 정상과의 괴리 크기 |
| **Lift** | 유형 플래그 발생률 ÷ 정상 발생률 | 정상 대비 몇 배 자주 발생하는가 |
| **범주형 조합** | 신용등급 × 채널 × 계좌유형 × 지역 | 단독 Cramér's V 는 낮아도 조합하면 신호 |

핵심 발견 예:

| 유형 | 신호 |
|---|---|
| `b` | 루팅 **7.0x** · VPN **5.8x** · 로밍 **4.6x** 동시 상승 / 악성행위는 정상 수준 → 위치·신원 위장형 |
| `c` | 단말 악성행위 **4.4x** 인데 VPN 은 **0.3x** (정상 이하) → 이미 기기 장악, 숨길 필요 없음 |
| `h` | `Transaction_Failure_Status` **7.3x** (표 전체 최댓값) → 소액 계좌에서 규모 안 맞는 시도 → 잔액부족 실패 급증 |
| `e`/`f` | 채널이 완전히 갈림 — `e` = ATM 100% / `f` = Others 100% |
| `b` | 신용등급 A/B **0건** — 저신용 집중 (D 3.9x · E 4.4x) |

### 파생변수 7종

| 파생 | 정의 | 검증 결과 |
|---|---|---|
| `Amount_vs_monthly_max_ratio` | 거래금액 ÷ 월간 최대거래금액 | **최상위 판별 변수** — 정상 median 0.11 vs 사기 0.83~1.00 |
| `Amount_vs_remaining_balance` | 거래금액 ÷ (잔여잔액+1) | `i` = 7.66배 · `b` = 7.44배 |
| `Transaction_Hour` / `Is_dawn` | 거래 시각 · 0~5시 여부 | `d` 1.48배 · `i` 6.91배 — **`d` 유형에 최초 정량 시그니처** |
| `Amount_vs_daily_limit` | 거래금액 ÷ 일일한도 | `h` 0.32 · `k` 0.31 |
| `unused_terminal_and_internet` | 미사용단말=1 **AND** Channel=internet | `d` 45% vs 정상 22% (2배) |
| `limit_check_then_transfer` | 한도조회·상향=1 **AND** Channel=internet | `d` 33% vs 정상 18% — 한도상향 직후 초고액 출금 |
| `large_deposit_and_remote_control` | 대량입금=1 **AND** 원격제어=1 | `e` = 0.26 (정상 대비 6.5배) — `e`/`f`/`g` 3분할 확정 필터 |

> 🐛 **원본 코드 결함** — `weak_signal_composite_score` 가 참조하는 `_composite_cols` 가
> 어디에도 정의돼 있지 않아 `NameError` 로 죽는다. 노트북 05 §13 첫 셀에 복원해 두었다.
> → [`03a` #A-9](03a_issues_data_modeling.md)

> ⚠️ **`Amount_vs_monthly_max_ratio` 는 튜터가 look-ahead 로 지적한 피처다.**
> → [`04_tutor_feedback.md`](04_tutor_feedback.md) §1, [`03a` #A-2](03a_issues_data_modeling.md)

### 인코딩과 산출

```
범주형(object) → LabelEncoder → label_encoders.pkl
Fraud_Type     → 알파벳순 0~12 (m=12=정상) → le_target.pkl
식별자·원본 datetime·타깃 제외 → 최종 58피처
9절 확정 분할(tr_idx/va_idx)로 분리 → X_tr/X_va/y_tr/y_va.parquet
```

> **`le_target.pkl` 은 나중에 시스템에서도 결정적으로 중요해진다.**
> parquet 정수 라벨(0~12)을 디코딩하는 유일한 경로라, 이게 없으면
> 예측이 `"0"~"12"`, 정답이 `"a"~"m"` 이 되어 **에러 없이 전 지표가 0.0** 이 된다.
> → [`03b` #B-3](03b_issues_dashboard_pipeline.md)

### 전처리 세대

이 저장소의 `data/` 에는 세 세대가 나란히 남아 있습니다.

| 파일 | 피처 수 | 세대 |
|---|---|---|
| `구구 X_tr.parquet` | 81 | 1차 (`is_fraud` 누수 포함 추정) |
| `구 X_tr.parquet` | 61 | 2차 |
| `X_tr.parquet` | **58** | **3차 — 현행** |

---

## [6] 모델 학습과 성능 해부

**노트북**: [`06_model_outputs_shap_cm.ipynb`](../notebooks/team_final/06_model_outputs_shap_cm.ipynb)

```python
LGBMClassifier(n_estimators=300, learning_rate=0.05, num_leaves=31,
               subsample=0.9, colsample_bytree=0.9,
               class_weight="balanced", random_state=42)
```

| 지표 | 값 | 해석 |
|---|---|---|
| **Macro-F1** | **0.6138** | 주 평가지표 |
| Weighted-F1 | 0.9942 | 정상이 지배 |
| Accuracy | 0.9949 | **무의미** — 전부 정상 예측해도 98.92% |

### 유형별 F1 — 어디가 무너지는가

| 강함 | F1 | 중간 | F1 | **약함** | **F1** |
|---|---|---|---|---|---|
| `a` | 0.978 | `k` | 0.774 | **`c`** | **0.378** |
| `f` | 0.800 | `i` | 0.703 | **`d`** | **0.343** |
| `b` | 0.781 | `h` | 0.667 | **`l`** | **0.083** |
| | | `j` · `e` · `g` | 0.54 / 0.53 / 0.40 | | |

### SHAP 상위 — EDA 추정과 실제 기여의 대조

| 순위 | 피처 | mean\|SHAP\| |
|---|---|---|
| 1 | `Transaction_is_withdrawal` | 0.4471 |
| 2 | `Channel` | 0.3272 |
| 3 | `Transaction_Amount_abs` | 0.2949 |
| 4 | `Flag_deposit_more_than_tenMillion` | 0.2381 |
| 5 | `Amount_vs_monthly_max_ratio` | 0.2288 |
| 6 | `Time_difference_seconds` | 0.2049 |

> 이 표가 **튜터 피드백에 대한 직접 응답**이다 — "파생변수 근거가 순환논리다.
> 진짜 근거는 홀드아웃 lift 또는 실제 모델의 SHAP/importance 여야 한다."
> `Transaction_Hour` 가 13위로 확인되며 파생 설계의 실효성이 재확인됐다.

### 혼동행렬 — 무엇을 무엇으로 헷갈리나

| 유형 | 정상(m) 흡수 | 주요 오분류 | 해석 |
|---|---|---|---|
| `a` | 0% | `d` 4% | 사실상 완전 분리 |
| `l` | **62%** | `e` 14% · `h` 10% | **사실상 탐지 실패** |
| `c` | 37% | `j` 11% | 정상 흡수 최다 |
| `g` | 21% | `d` 18% · `f` 14% | `e`·`f`·`g` 신호 유사성과 일치 |
| `d` | 12% | `h` 12% (동률) | 고유 신호 미약 |

### 확신도 등급 — 튜터 지적을 기준으로 바꾼 것

중간보고에서 "높음/중간/낮음의 기준이 불명확하다"는 지적을 받고,
**주관 서술 → 계산 가능한 규칙**으로 재정의했습니다.

```
높음 = Recall ≥ 0.7  AND  다른유형혼동율 ≤ 0.10
낮음 = Recall < 0.4  OR   다른유형혼동율 > 0.25
중간 = 나머지
```

| 등급 | 유형 |
|---|---|
| 높음 (3) | `a` · `f` · `h` |
| 중간 (5) | `b` · `k` · `i` · `e` · `j` |
| 낮음 (4) | `d` · `g` · `c` · `l` |

---

## [7] 아키텍처 확정

**노트북**: [`07_model_comparison_oneshot_vs_twostage.ipynb`](../notebooks/team_final/07_model_comparison_oneshot_vs_twostage.ipynb)

| 모델 | 임계값 | Macro-F1 | 미탐 | 오탐 |
|---|---|---|---|---|
| 한방 13-class (argmax) | — | 0.6138 | 59 | 1 |
| **한방 + 임계값 조정** | **0.03** | **0.6395** | 37 | 17 |
| 2계층 TwoStage | 0.5 | 0.6105 | 43 | 51 |
| 2계층 + 임계값 조정 | 0.5 | 0.6105 | 43 | 51 |

**2계층 기각 사유**: stage1 에서 정상으로 걸러진 건은 stage2 가 볼 기회조차 없다 —
1단계 FN 이 **영구 미탐**으로 굳는 오류 전파. 임계값을 어떻게 움직여도 한방 기본보다 낮다.

---

## [8] 비용 기반 임계값

**노트북**: [`08_cost_based_threshold.ipynb`](../notebooks/team_final/08_cost_based_threshold.ipynb)
**상세**: [`07_model_and_thresholds.md`](07_model_and_thresholds.md)

```
기대비용 = (FN 건수 × 1,700만원) + (FP 건수 × FP 단가)
FP 단가 시나리오: A 5천 / B 1만 / C 5만원
```

| 임계값 | Macro-F1 | 미탐 | 오탐 | 비용(C, 억) |
|---|---|---|---|---|
| 0 | 0.021 | 0 | 23,602 | **11.80** |
| 0.0002 | 0.469 | 13 | 389 | 2.41 |
| **0.005** | **0.603** | 27 | 69 | **4.62** ← **채택** |
| 0.03 | 0.640 | 37 | 17 | 6.30 |

**순수 비용최소화의 함정** — 제약 없이 비용만 최소화하면 0.0002 가 나오지만 Macro-F1 이 0.469 로 무너집니다.
임계값 0(전량 의심)은 오히려 11.8억으로 폭증합니다.
→ **`Macro-F1 ≥ 0.60` 제약 하에서 비용 최소화** → **0.005**.

**FN 고정 단가의 한계 보완** — 유형별 실제 금액으로 재계산하면 임계값 0.0005 에서 **+47.1%** 차이.
`i` 유형 평균 피해액 8,097만원은 `h`(347만원)의 **23배**입니다.

---

## [9]·[10] 검증된 두 개의 "안 한다"

| 노트북 | 시도 | 결과 |
|---|---|---|
| [09](../notebooks/team_final/09_rule_ml_hybrid.ipynb) | 규칙 기반 + ML 결합 (튜터 권고) | override **−0.0040** · boost 0.0000 → **미채택** |
| [10](../notebooks/team_final/10_synthetic_augmentation.ipynb) | CTGAN · TVAE · SMOTE 증강 (기획서 목표) | −0.0928 / −0.0371 / −0.0466 → **미채택** |

두 노트북 모두 **"해봤더니 안 되더라"를 수치로 남긴 기록**입니다.

---

## [11]~[15] 운영 구간 — 학습이 끝난 뒤

여기서부터는 노트북이 아니라 코드입니다.

### [11] 원본 행 → 58피처 실시간 변환

**코드**: [`pipeline/preprocessor.py`](../pipeline/preprocessor.py) (495줄)

노트북의 전처리를 **원본 1행에 대해** 재현합니다. 학습 파이프라인과 어긋나면 조용히 틀리므로,
`tools/verify_bundle.py` 가 원본 CSV ↔ `X_tr.parquet` 을 대조해 **58피처 전부 99.9% 이상 일치**를 확인합니다.

| 검증 | 결과 |
|---|---|
| 파생 공식 해독 | 11개 100% |
| 피처 일치 | **58 / 58** |
| `Location_region` 시도 매핑 | 17종 전수 실측 확정 |

> 여기서 마지막까지 안 맞던 것이 `Time_difference_seconds` 99.866% 였습니다.
> 원인은 음수 경과시간 126행(0.134%) — 팀은 NaN 으로 뒀는데 코드는 거대한 음수를 넣고 있었습니다.
> → [`03b` #B-12](03b_issues_dashboard_pipeline.md)

### [12] 추론

**코드**: [`pipeline/ml_classifier.py`](../pipeline/ml_classifier.py) · [`pipeline/model_loader.py`](../pipeline/model_loader.py)

```
risk = 1 − P(정상 m)
예측 유형 = 정상 제외 최고확률 클래스
```

지원 형식: `.pkl` (pickle/joblib) · LightGBM native `.txt` · `.onnx` · `.pmml` · `.sql`

> ⚠️ 모델 로드 실패 시 `_dummy_predict()` 로 폴백하는데 **15% 확률 랜덤 사기 판정**입니다.
> 반환값만으론 진짜와 구분이 안 됩니다 → [`03c` #C-6](03c_issues_ops_runtime.md)

### [13] 이중 임계값 등급 판정

**코드**: [`pipeline/detect_service.py`](../pipeline/detect_service.py) (794줄)

| 구간 | 등급 | 동작 |
|---|---|---|
| `risk < th_review` (0.005) | `none` | 발송 없이 종료 |
| `th_review ≤ risk < th_confirm` (0.90) | `review` | **Slack** |
| `risk ≥ th_confirm` | `confirm` | **Slack + Email** |

임계값은 [`watcher_config.json`](../watcher_config.json) 에서 **핫 리로드**됩니다 — 재시작 없이 5초 내 반영.

### [14] PII 마스킹 게이트

**코드**: [`pipeline/pii_masker.py`](../pipeline/pii_masker.py)

외부(LLM · Slack · Email)로 나가는 모든 데이터의 **단일 통로**입니다.

```
이상호            → 이○○
171.237.22.26    → 171.237.*.*
oVZASOzgcm       → oV******cm
강원도 고성군 ...   → 강원도 ***
1980             → 1980년대
```

레벨: `off` / `basic` / `standard`(워처 기본) / `strict`

### [15] LLM 3단계 분석 + RAG

**코드**: [`pipeline/llm_analyzer.py`](../pipeline/llm_analyzer.py) · [`pipeline/rag_searcher.py`](../pipeline/rag_searcher.py)

| 단계 | 산출 |
|---|---|
| 1 | 판정 근거 · 이상 패턴 · 오탐 체크 · 권장 조치 |
| 2 | Slack 요약 (mrkdwn + Block Kit) |
| 3 | Email 본문 (multipart: plain + HTML) |

**환각 통제** — 멘토 지적("RAG 환각 위험을 어떻게 담보하는가")에 대한 대응:

| 장치 | 내용 |
|---|---|
| 근거 문서 인용 | Chroma 벡터 검색 결과를 프롬프트에 첨부하고 화면에 함께 표시 |
| **문서에 수치를 박음** | [`tools/build_rag_docs.py`](../tools/build_rag_docs.py) 가 120,000행 전수 검증 결과를 유형별 문서에 씀 — *숫자가 문서에 있으면 LLM 은 그것을 인용한다. 없으면 만들어낸다* |
| 사람 검수 | 관제 콘솔은 발송 전 본문을 **편집 가능**하게 미리보기 |
| 규칙 대조 | `rule_checker.py` 가 규칙 결과와 모델 판정 불일치를 표시 |

---

## 전 구간 요약

| 단계 | 코드/노트북 | 핵심 수치 |
|---|---|---|
| 전처리 | 노트북 01~05 | 64컬럼 → **58피처**, 누수 0건 |
| 학습 | 노트북 06 | **Macro-F1 0.6138** |
| 아키텍처 | 노트북 07 | 2계층 기각 (0.6105) |
| 임계값 | 노트북 08 | **0.005** · 기대비용 **4.62억** |
| 반증 2건 | 노트북 09·10 | 규칙결합 −0.004 · 증강 −0.09 |
| 실시간 변환 | `preprocessor.py` | 58/58 피처 99.9%+ 일치 |
| 판정 | `detect_service.py` | 이중 임계값 · 핫 리로드 |
| 보호 | `pii_masker.py` | 단일 통로 · 4레벨 |
| 설명 | `llm_analyzer.py` + RAG | 3단계 · 근거 문서 인용 |

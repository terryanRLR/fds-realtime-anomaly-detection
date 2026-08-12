# data/ — 데이터셋

> ⚠️ **이 폴더의 실제 데이터 파일은 저장소에 포함되지 않습니다** (합계 141MB, `.gitignore` 처리).
> 아래는 스키마와 재생성 방법입니다.

---

## 1. 원본

| 파일 | 크기 | 내용 |
|---|---|---|
| `train.csv` | 54MB | **120,000행 × 64컬럼** — 학습 원본 |
| `test.csv` | 54MB | 라벨 없음 (제출용) |

**출처** — [DACON 금융 AI 챌린지](https://dacon.io/competitions/official/236297/data)
한국 은행 전자금융 계좌이체 거래 기반 **합성 데이터**입니다.

**분석 단위** — 거래 1건 = 1행 (고객 · 계좌 · 거래 · 단말 정보가 한 행에 결합)

### 타깃 분포

| 클래스 | 건수 | 비율 |
|---|---|---|
| `m` (정상) | 118,800 | **99.0%** |
| `a`~`l` (사기 12종) | 각 **100** · 합 1,200 | 각 **0.083%** |

---

## 2. 전처리 산출물 — 세 세대가 나란히 있습니다

| 파일 | 형상 | 세대 | 비고 |
|---|---|---|---|
| `구구 X_tr/X_va/y_tr/y_va.parquet` | 96,140 / 23,860 × **81** | 1차 | `is_fraud` 누수 포함 추정 |
| `구 X_tr/X_va/y_tr/y_va.parquet` | 96,140 / 23,860 × **61** | 2차 | |
| **`X_tr/X_va/y_tr/y_va.parquet`** | 96,140 / 23,860 × **58** | **3차 — 현행** | 운영 모델의 입력 |

> **접두어(`구`, `구구`)가 붙어도 로더가 인식합니다** —
> [`pipeline/dataset_loader.py`](../pipeline/dataset_loader.py) 가 `X_*`/`y_*` 페어를 자동 결합하므로
> 세대별 데이터셋을 나란히 두고 대시보드에서 골라 비교할 수 있습니다.

**`y_*.parquet` 은 정수 라벨(0~12)입니다.** `m`(정상) = **12**.
문자 라벨 복원에는 `models/le_target.pkl` 이 필요합니다.

> X·y 결합은 **위치 기준**입니다 (인덱스로 결합하면 어긋납니다).

---

## 3. 재생성

```bash
# 1) 원본을 data/ 에 배치
#    train.csv, test.csv

# 2) 노트북 01 → 05 를 순서대로 실행
#    notebooks/team_final/01_preprocessing_load_and_quality.ipynb
#    ...
#    notebooks/team_final/05_signal_visualization_features_encoding.ipynb
#    → X_tr/X_va/y_tr/y_va.parquet + label_encoders.pkl + le_target.pkl 생성

# 3) 변환 규칙 검증 (58피처 전부 99.9% 이상 일치해야 함)
python -m tools.verify_bundle --raw data/train.csv --x data/X_tr.parquet
```

---

## 4. 원본 스키마 (64컬럼)

### 고객 정보 (22)

| # | 컬럼 | 비고 |
|---|---|---|
| 1 | `ID` | 거래 식별자. **행 번호일 수 있음** → [`03c` #C-15](../docs/03c_issues_ops_runtime.md#c-15) |
| 2 | `Customer_Birthyear` | `l` 유형 최상위 신호 (1955~1965 집중) |
| 3 | `Customer_Gender` | |
| 4 | `Customer_personal_identifier` | **PII** |
| 5 | `Customer_identification_number` | **PII** · 그룹 분할 축 |
| 6 | `Customer_registration_datetime` | datetime |
| 7 | `Customer_credit_rating` | `b` 유형: A/B 등급 **0건** |
| 8~11 | `Customer_flag_change_of_authentication_1~4` | 인증 변경 플래그 |
| 12 | `Customer_rooting_jailbreak_indicator` | `b` 유형 **7.0x** |
| 13 | `Customer_mobile_roaming_indicator` | `b` 유형 4.6x |
| 14 | `Customer_VPN_Indicator` | `b` 5.8x / `c` **0.3x** (정상 이하) |
| 15 | `Customer_loan_type` | |
| 16~21 | `Customer_flag_terminal_malicious_behavior_1~6` | `c` 유형 4.4x |
| 22~23 | `Customer_inquery_atm_limit` · `Customer_increase_atm_limit` | `d` 유형 파생 재료 |

### 계좌 정보 (14)

| # | 컬럼 | 비고 |
|---|---|---|
| 24 | `Account_account_number` | **PII** · 그룹 분할 축 |
| 25 | `Account_account_type` | `b~g` 입출금 / `h~k` ISA·저축 |
| 26 | `Account_creation_datetime` | datetime |
| 27~28 | `Account_initial_balance` · `Account_balance` | 잔액 항등식 **0.65%** 만 성립 |
| 29 | `Account_indicator_release_limit_excess` | |
| 30 | `Account_amount_daily_limit` | `Amount_vs_daily_limit` 분모 |
| 31 | `Account_indicator_Openbanking` | |
| 32 | `Account_remaining_amount_daily_limit_exceeded` | |
| 33 | `Account_release_suspention` | p=2.8e−06 |
| 34~37 | `Account_one_month_max_amount` · `_std_dev` · `Account_dawn_one_month_*` | ⚠️ **look-ahead 의심 4종** → [`03a` #A-2](../docs/03a_issues_data_modeling.md#a-2) |

### 거래 정보 (17)

| # | 컬럼 | 비고 |
|---|---|---|
| 38 | `Transaction_Datetime` | datetime · **2003~2058년** 분포 |
| 39 | `Transaction_Amount` | **약 30% 음수** = 출금 방향. 제거 금지 |
| 40 | `Channel` | SHAP **2위** · `e`=ATM 100% / `f`=Others 100% |
| 41 | `Operating_System` | |
| 42~43 | `Error_Code` · `Transaction_Failure_Status` | `h` 유형 **7.3x** (표 전체 최댓값) |
| 44 | `Type_General_Automatic` | |
| 45~46 | `IP_Address` · `MAC_Address` | **PII** · Frequency Encoding |
| 47 | `Access_Medium` | `d` 유형 SHAP 상위 |
| 48 | `Location` | **PII** → `Location_region` 파생 (17개 시도) |
| 49 | `Recipient_Account_Number` | **PII** |
| 50 | `Transaction_num_connection_failure` | |
| 51 | `Another_Person_Account` | |
| 52 | `Distance` | `a` 유형 **Cliff's δ = 0.95** (전체 최댓값) |
| 53 | `Time_difference` | `"0 days HH:MM:SS"` · **음수 156건** → NaN 처리 |
| 54 | `Unused_terminal_status` | `d` 유형 파생 재료 |
| 55~56 | `Last_atm_transaction_datetime` · `Last_bank_branch_transaction_datetime` | datetime |

### 행위 · 관계 (7)

| # | 컬럼 | 비고 |
|---|---|---|
| 57 | `Flag_deposit_more_than_tenMillion` | SHAP **4위** · `g` 유형 최상위 |
| 58 | `Unused_account_status` | |
| 59 | `Recipient_account_suspend_status` | SHAP 15위 |
| 60~61 | `Number_of_transaction_with_the_account` · `Transaction_history_with_the_account` | `k` 유형 최고 |
| 62 | `First_time_iOS_by_vulnerable_user` | 0/1 플래그 — ⚠️ 이름에 `time` 이 있어 **datetime 으로 오분류됨** → [`03a` #A-13](../docs/03a_issues_data_modeling.md#a-13) |
| 64 | `Transaction_resumed_date` | datetime |

### 타깃

| # | 컬럼 | 값 |
|---|---|---|
| 63 | **`Fraud_Type`** | `a`~`l` (사기 12종) + `m` (정상) |

---

## 5. 파생변수 7종 (3차 전처리에서 추가)

| 파생 | 정의 |
|---|---|
| `Transaction_is_withdrawal` · `Transaction_Amount_abs` | 금액 부호 분리 (SHAP **1위**·3위) |
| `Amount_vs_monthly_max_ratio` | 거래금액 ÷ 월간 최대거래금액 ⚠️ look-ahead |
| `Amount_vs_remaining_balance` | 거래금액 ÷ (잔여잔액+1) |
| `Amount_vs_daily_limit` | 거래금액 ÷ 일일한도 |
| `Transaction_Hour` / `Is_dawn` | 거래 시각 · 0~5시 여부 |
| `unused_terminal_and_internet` | 미사용단말=1 AND Channel=internet |
| `limit_check_then_transfer` | 한도조회·상향=1 AND Channel=internet |
| `large_deposit_and_remote_control` | 대량입금=1 AND 원격제어=1 |
| `Location_region` | `Location` → 17개 시도 |

---

## 6. `inbox/` — 워처 감시 폴더

워처가 5초마다 폴링하는 폴더입니다. 여기에 CSV 를 넣으면 자동 탐지됩니다.
운영 데이터라 `.gitignore` 처리돼 있습니다.

```bash
cp 거래파일.csv inbox/
```

---

## 7. 개인정보 주의

이 데이터는 **합성 데이터**이지만, 스키마상 실제 PII 컬럼과 동일한 구조입니다.

| 컬럼 | 마스킹 처리 |
|---|---|
| `Customer_personal_identifier` | 이상호 → `이○○` |
| `Customer_identification_number` | 부분 마스킹 |
| `Account_account_number` | `oVZASOzgcm` → `oV******cm` |
| `IP_Address` | `171.237.22.26` → `171.237.*.*` |
| `Location` | `강원도 고성군 …` → `강원도 ***` |
| `Customer_Birthyear` | `1980` → `1980년대` |

외부(LLM · Slack · Email)로 나가는 모든 데이터는
[`pipeline/pii_masker.py`](../pipeline/pii_masker.py) 를 통과합니다.

> ⚠️ **마스킹본으로 재예측하면 안 됩니다.** 예외 없이 무의미한 결과가 나옵니다
> → [`03c` #C-5](../docs/03c_issues_ops_runtime.md#c-5)

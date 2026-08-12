# team_final — 팀 공식 분석 노트북 (실행 순서대로)

원본 노트북 **2개**를 절 경계 그대로 **10개**로 나누고, **재구성 노트북 2개**를 더한 것입니다.
코드는 손대지 않았고, **원본 실행 출력(표 · 그래프)을 전부 그대로 옮겨 붙였습니다.**
데이터가 없어도 결과를 볼 수 있고, 데이터가 있으면 그대로 재실행됩니다.

---

## 실행 순서

### 0부 — 재구성 (원본에 없던 노트북)

| # | 노트북 | 하는 일 |
|---|---|---|
| **00** | [`00_preprocessing_generations_forensics.ipynb`](00_preprocessing_generations_forensics.ipynb) | **전처리 1차/2차/3차 포렌식** — 1·2차 노트북이 없어 결과 parquet 으로 전환 과정을 복원. 세대별 재학습 · 절제 실험 · 복원 실험 · 사라진 9피처 공식 역산 |
| **11** | [`11_baseline_and_anomaly_score.ipynb`](11_baseline_and_anomaly_score.ipynb) | **Baseline 5모델 · 2계층 stage2 · IsolationForest 재현** — `reports/04` 에 결과만 있고 코드가 없던 1주차 작업. 기획서 **M5** 에 실측으로 답함 |

> 이 둘은 팀이 만든 것이 아니라 **남은 데이터로 재구성한 것**입니다.
> 무엇이 비어 있었고 어떻게 채웠는지는 [`docs/09_reconstruction_log.md`](../../docs/09_reconstruction_log.md) 참조.

### 1부 — 전처리 · EDA (`원본/FDS_전처리_정리본.ipynb` 109셀 분리)

| # | 노트북 | 하는 일 | 원본 셀 |
|---|---|---|---|
| 01 | [`01_preprocessing_load_and_quality.ipynb`](01_preprocessing_load_and_quality.ipynb) | 원본 로드 · **명시적 타입 분류** · 결측/중복/고유값 점검 | `[0]~[11]` |
| 02 | [`02_data_integrity_negative_dates_leakage.ipynb`](02_data_integrity_negative_dates_leakage.ipynb) | 형식 검증(원본 문자열 기준) · 음수 금액 · 날짜 현실성 · 그룹 누수 구조 | `[12]~[23]` |
| 03 | [`03_time_difference_amount_sign_split.ipynb`](03_time_difference_amount_sign_split.ipynb) | `Time_difference` 음수 처리 결정 · 금액 부호 분리 · **StratifiedGroupKFold 80/20** | `[24]~[40]` |
| 04 | [`04_eda_and_statistical_testing.ipynb`](04_eda_and_statistical_testing.ipynb) | 1차 EDA · **13클래스 통합검정 vs 정상 대비 이진 재검정** | `[41]~[74]` |
| 05 | [`05_signal_visualization_features_encoding.ipynb`](05_signal_visualization_features_encoding.ipynb) | z-score/Lift 시각화 · **파생변수 7종** · 인코딩 → `X/y parquet` 추출 | `[75]~[108]` |

**변수를 이어받는 구조입니다.** 01→05 를 순서대로 실행해야 합니다.
단독 실행하면 `train` · `df_tr` · `tr_idx` 등이 없어 `NameError` 가 납니다.
각 노트북 상단에 무엇을 이어받는지 적어 두었습니다.

### 2부 — 모델링 · 임계값 (`원본/최종_3차_통합분석.ipynb` 1셀 30KB 분리)

| # | 노트북 | 하는 일 | 원본 파트 |
|---|---|---|---|
| 06 | [`06_model_outputs_shap_cm.ipynb`](06_model_outputs_shap_cm.ipynb) | 클래스별 성능 · **SHAP** · 13×13 혼동행렬 · 임계값 곡선 | `RUN_PART1` |
| 07 | [`07_model_comparison_oneshot_vs_twostage.ipynb`](07_model_comparison_oneshot_vs_twostage.ipynb) | **한방 vs 2계층** 실측 비교 — 기획서의 2단계 구조를 반증 | `RUN_COMPARE` |
| 08 | [`08_cost_based_threshold.ipynb`](08_cost_based_threshold.ipynb) | 기대비용 곡선 · FN 실제금액 재계산 · **thr=0.005 채택 근거** | `RUN_PART2` |
| 09 | [`09_rule_ml_hybrid.ipynb`](09_rule_ml_hybrid.ipynb) | 규칙+ML 결합 — 튜터 권고를 구현하고 **이득 없음을 실측** | `RUN_PART3` |
| 10 | [`10_synthetic_augmentation.ipynb`](10_synthetic_augmentation.ipynb) | CTGAN · TVAE · SMOTE 증강 전/후 — **세 방식 전부 성능 하락** | `RUN_PART4` |

**00 · 06~10 · 11 은 서로 독립입니다.** 각 노트북이 앞부분에서 데이터를 로드하고 모델을 다시 학습합니다(약 13초).
원본이 `if RUN_PARTn:` 로 켜고 끄던 구조라, 그 경계를 그대로 노트북 경계로 삼았습니다.

> 원본의 `if RUN_PARTn:` 가드는 제거하고 들여쓰기를 풀었습니다.
> 파트별 노트북이므로 그 파트는 항상 실행됩니다 — **로직은 원본과 동일합니다.**

---

## 재현에 필요한 것

| 노트북 | 입력 | 저장소 포함 |
|---|---|---|
| **00** | 세 세대 parquet 전부 + `data/train.csv` | ❌ — `구구 *` · `구 *` · `*` 세 벌이 모두 필요합니다 |
| 01~05 | `data/train.csv` (원본 120,000행 × 64컬럼, 54MB) | ❌ — [`data/README.md`](../../data/README.md) |
| 06~10 | `data/X_tr,X_va,y_tr,y_va.parquet` (3차 전처리 58피처) | ❌ — 01~05 를 돌리면 생성됩니다 |
| **11** | 3차 parquet | ❌ — 동일 |

```bash
pip install pandas numpy scikit-learn lightgbm matplotlib seaborn scipy
pip install shap              # 06 SHAP
pip install sdv imbalanced-learn   # 10 CTGAN/TVAE/SMOTE
```

소요 시간: **00** 약 5~7분(모델 12회 학습) · **11** 약 2~3분 · 06~10 각 20~30초.

00·06~10 의 `DATA_DIR`(또는 `DATA`) 기본값은 `"../../data"` 입니다.
원본 실행 경로(`/mnt/c/Users/dkstj/Desktop/test_uv/3차 전처리 파일`)는 주석으로 남겨 두었습니다.

---

## 이 노트북들이 산출한 핵심 수치

| 항목 | 값 | 어느 노트북 |
|---|---|---|
| 분할 | train 96,140 / valid 23,860 · 고객·계좌 누수 **0건** | 03 |
| 피처 | **58개** (3차 전처리) | 05 |
| Macro-F1 (argmax) | **0.6138** | 06 |
| Macro-F1 (thr=0.03 최고점) | 0.6395 | 06 · 07 |
| **채택 임계값** | **0.005** — Macro-F1 0.6030 · 기대비용 **4.62억** | 08 |
| 2계층 비교 | 0.6105 — 한방 기본(0.6138)보다도 낮음 | 07 |
| 규칙+ML 결합 | override **−0.0040** · boost 0.0000 | 09 |
| 생성 증강 | CTGAN **−0.0928** · TVAE −0.0371 · SMOTE −0.0466 | 10 |
| 최약 유형 | `l` F1 **0.08** · `d` 0.34 · `c` 0.38 | 06 |
| 이상점수(ISF) 결합 | **−0.0084** — 이득 없음 (기획서 M5 답) | 11 |
| **전처리 세대** | 1차 0.6844 / 2차 정식 0.6218 / **3차 0.6138** | 00 |
| **9피처 복원 시** | 최고 Macro-F1 0.6395 → **0.6779** · `l` F1 0.083 → **0.267** | 00 |

수치의 해석과 채택 근거는 [`docs/07_model_and_thresholds.md`](../../docs/07_model_and_thresholds.md) 에 정리돼 있습니다.

---

## 알려진 한계

- **01~10 은 재실행 검증을 하지 못했습니다.** 원본 노트북에서 셀을 그대로 옮기고
  **원본 실행 출력을 보존**한 것이며, 분리 후 다시 돌려 같은 수치가 나오는지는 확인하지 않았습니다.
  셀 내용은 원본과 바이트 단위로 동일합니다.
- **00 과 11 은 반대입니다.** 이 저장소 환경에서 **실제로 실행한 출력**을 담고 있습니다
  (LightGBM 4.6.0 / scikit-learn 1.9.0 / Python 3.11). 그래서 원본 PDF 수치와
  소수 셋째 자리에서 다를 수 있습니다 — 각 노트북이 원본과의 대조표를 함께 싣고 있습니다.
- **`look-ahead` 의심 피처 5개가 남아 있습니다.** 06~10 을 실행하면 매번 경고가 뜹니다.
  튜터 지적 사항이며 팀이 명세서 해석으로 유지 결정했습니다 — [`docs/03a_issues_data_modeling.md`](../../docs/03a_issues_data_modeling.md) `#A-2`.
- **1차 · 2차 전처리 노트북은 존재하지 않습니다.** 남아 있는 것은 3차뿐이고,
  1·2차의 결과물만 `data/구 *.parquet`(61피처) · `data/구구 *.parquet`(81피처)로 남아 있습니다.
  → [노트북 00](00_preprocessing_generations_forensics.ipynb) 이 그 결과물로 **전환 과정을 재구성**합니다.
- **`00` 과 `11` 의 수치에는 valid 선택 편향이 있습니다.** 여러 구성을 valid 에서 비교해 고른 것이라,
  채택 전에 별도 홀드아웃 재확인이 필요합니다. 노트북 안에 이 경고를 명시해 두었습니다.

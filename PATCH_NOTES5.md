# FDS 대시보드 업데이트 총정리 (v10 → v39)

새 팀 배포 번들(`lgbm_13class(최종)`, 58피처 13클래스) 호환 작업 + 요청 기능.
**v20에서 관제 콘솔(`ops_dashboard.py`)이 독립 도구로 분리**됐고,
**v21~v22에서 AI 작업대 전면 배치 · 경보 시스템 전면 재작성**이 이뤄졌다.
**v38에서 두 대시보드의 발송물·프롬프트·경보 설정이 한 벌로 합쳐졌다** —
분리 이후 갈라져 있던 '결과물을 만드는 계층'을 공용 모듈로 되돌린 작업이다.
**v39에서 관제 콘솔의 조작 계층(키보드 단축키 · 챗 에이전트 액션)이
분석용 대시보드 수준으로 올라왔다.**

**검증 기준선:** `model_meta.json`의 `macro_f1_valid = 0.6138`
**최종 상태:** 전 전처리 경로에서 **0.6138 정확히 재현** · 전체 컴파일 통과 · selftest_all 12/12
**최종 갱신:** 2026-08-10 (v39)

> **문서 지도**
> · 이 문서 — 버전별 변경 내역(개발자용)
> · `ops_dashboard_사용설명서.md` — 관제 콘솔 실무자 매뉴얼
> · `README_WATCHER.md` — 워처·관제 운영 문서
> · `PIPELINE_DIAGRAM.md` — 발표용 모식도

---

## 0. 한눈에 보기

| Phase | 내용 | 결과 |
|---|---|---|
| **0** | 배포 번들 호환 블로커 3건 + 기반 정리 7건 | 번들이 "더미 모드"에서 정상 예측으로 |
| **1** | 원본→58피처 결정론적 변환기 + 분류기 선택 관문 + 검증 하니스 | 파생 공식 11개 100% 해독 |
| **2** | 배치 리포트 행별 위험점수 · RAG 문서 편집기 | 요청 1·3 |
| **3** | 챗봇 점검(버그 3건) · 음성 입력(로컬+클라우드) | 요청 2 |
| **4** | 컴팩트 모드 재배치 + CSS 보강 | 요청 4 |

### 파일 변경 규모

```
수정  dashboard.py           4,424 → 4,730 (+306)
      i18n_data.py           1,179 → 1,348 (+169)   593 → 657키 × 4개국어
      batch_analyzer.py        358 →   494 (+136)
      ml_classifier.py         269 →   310  (+41)
      model_loader.py          540 →   563  (+23)
      evaluator.py             448 →   466  (+18)
      chat_agent.py            310 →   323  (+13)
      dataset_loader.py        320 →   331  (+11)
      llm_analyzer.py          747 →   745   (-2)   죽은 변수 제거
      requirements.txt          20 →    33         누락 4종 + 전 항목 버전 핀

신규  pipeline/bundle_io.py            183줄   번들 안전 로드 단일 진입점
      pipeline/preprocessor.py         447줄   원본 → 58피처 결정론적 변환
      pipeline/speech_to_text.py       227줄   STT (로컬/클라우드)
      tools/verify_bundle.py           203줄   호환 검증 하니스
      tools/__init__.py                  0줄   (빈 파일 필요)
```

### 배치 구조

```
프로젝트루트/
├── dashboard.py            ← streamlit run dashboard.py
├── i18n_data.py
├── requirements.txt
├── PATCH_NOTES.md          ← 이 문서
├── pipeline/
│   ├── __init__.py
│   ├── bundle_io.py        ★신규
│   ├── preprocessor.py     ★신규
│   ├── speech_to_text.py   ★신규
│   ├── ml_classifier.py · model_loader.py · evaluator.py
│   ├── dataset_loader.py · batch_analyzer.py · chat_agent.py
│   ├── llm_analyzer.py · feature_bridge.py · notifier.py
│   ├── notify_visuals.py · pii_masker.py · rag_searcher.py · data_streamer.py
├── tools/
│   ├── __init__.py         ★신규(빈 파일)
│   └── verify_bundle.py    ★신규
├── models/                 lgbm_13class(최종).pkl · label_encoders.pkl · le_target.pkl
│                           feature_cols.json · feature_defaults.json · model_meta.json
├── data/                   X_tr/y_tr/X_va/y_va.parquet · train.csv
├── docs/                   RAG 참고문서 (*.md) — 대시보드에서 편집 가능
└── chroma_db/              벡터 인덱스 + .docs_sig
```

### 적용 후 확인 순서

```bash
pip install -r requirements.txt
python -m tools.verify_bundle          # 30초 판정 → "✅ 전 경로 정상"
streamlit run dashboard.py             # 첫 실행은 완전 재시작 (캐시 키 변경됨)
```

정상 배선이면 기동 로그에 다음 3줄이 보인다:
```
lgbm_13class(최종).pkl: joblib 형식으로 로드 (pickle 실패: UnpicklingError)
수치형 인코더 45개 감지 → 해당 컬럼은 인코딩 없이 원본 수치 통과
모델 로드 완료 — 피처 58개
```

---

## 1. Phase 0 — 배포 번들 호환 블로커

### 🔴 A. 번들 3파일이 joblib 형식인데 코드는 `pickle.load` → **전체 더미 모드**

```
lgbm_13class(최종).pkl   pickle ❌ invalid load key '\x05'   joblib ✅
label_encoders.pkl       pickle ❌ invalid load key '\x0a'   joblib ✅
le_target.pkl            pickle ❌ invalid load key '\x08'   joblib ✅
```

`ml_classifier._load_all`은 **모델 본체에만** joblib 폴백(v5.6)이 있었고, 메타 2파일은 맨 `pickle.load`였다. 그 `UnpicklingError`가 바깥 `except Exception`으로 전파되어 **번들 전체가 더미 모드**(세션5 랜덤 예측)로 빠졌다.

**수정:** `bundle_io.safe_load()` 신설(pickle → joblib) 후 6곳 교체.

| 파일 | 영향 |
|---|---|
| `ml_classifier.py:109,111` | 🔴 더미 모드 → 정상 |
| `dataset_loader.py:229` | 라벨 디코딩 실패 → 세션2 F1 0 → 정상 |
| `dashboard.py:1176` | 세션3 세그먼트 디코딩 실패 → 정상 |
| `model_loader.py:289,310` | 클래스 복원 실패(알파벳 폴백이 우연히 일치해 살아있었음) → 정상 |

버전 불일치(`ModuleNotFoundError`/`AttributeError`)는 joblib으로도 해결되지 않으므로 별도 `TypeError`로 승격해 "requirements 기준으로 버전을 맞추라"는 실행 가능한 안내를 낸다.

### 🔴 B. 범주형 9개가 입력과 무관하게 0으로 고정

새 `label_encoders.pkl`의 `classes_`는 문자열이 아니라 **정수**다 (`Channel → array([0,1,2,3])`, `Customer_Gender → array([0,1])`). 팀 전처리가 문자열을 먼저 인코딩한 뒤 그 결과로 다시 `LabelEncoder`를 fit한 결과다.

`_preprocess`는 `str(raw).strip() in le.classes_`로 비교했는데 `"1" in np.array([0,1,2,3])`은 **항상 False**. 기본값도 `"1"`이라 또 False → `data[col] = [0]`.

```
before:  Channel 0→0  1→0  2→0  3→0      (뭘 넣어도 0)
after :  Channel 0→0  1→1  2→2  3→3  ·  Gender 1→1 · Birthyear 1980→1980
```

**수정:** `is_numeric_encoder()`로 "수치형으로 학습된 인코더" 45개를 자동 감지 → 해당 컬럼은 **인코딩을 건너뛰고 원본 수치를 통과**. `로드예제.py`의 계약과 정확히 일치한다. 문자 인코더 번들에는 기존 경로를 유지하고, 비교는 `[str(c) for c in le.classes_]`로 dtype 무관하게 고쳤다.

### ⚠️ C. 인코더를 "제대로" 적용하면 더 크게 망가진다 — 하지 말 것

`model_meta.json`의 `categorical_cols_encoded`가 45개라서 `CAT_COLS`를 45개로 늘리는 게 자연스러워 보이지만 **절대 금지**. 부스터 분기 임계값이 증거다:

```
Customer_Birthyear          분기 591회 · 임계 1951 ~ 2004      ← 생년 원본
Account_amount_daily_limit  분기  43회 · 임계 1.5e6 ~ 3e7      ← 원 단위 원본
```

인코더를 적용하면 `1980 → 30`, `2000000 → 1`이 되는데 모델은 그걸 "서기 30년"으로 읽는다. `bundle_io.is_numeric_encoder`의 docstring에 이 경고를 남겨두었다.

### 🔴 D. NaN 대체가 macro F1을 0.7%p 깎고 있었다 (신규 발견)

`X_va`에 **진짜 NaN이 2,196행** 있다 — `Amount_vs_monthly_max_ratio` 2,195건(분모 0 → 0/0), `Time_difference_seconds` 30건. LightGBM은 이를 native 분기로 처리하는데, `make_batch_preprocess`가 `feature_defaults` 값으로 일괄 대체하고 있었다.

```
keep_nan=True  (신규 기본) → macro F1 0.6138  ✅
keep_nan=False (구 동작)   → macro F1 0.6070  ← 조용한 손실
```

**수정:** `make_batch_preprocess(clf, keep_nan=True)` — **'컬럼 자체가 없음'과 '값이 NaN'을 구분**한다. 컬럼 부재는 기본값으로 채우고, 계산 결과 NaN은 보존. `keep_nan=False`는 NaN 비허용 모델(LogReg/SVM/ONNX) 비교용으로 남겼다.

### 그 외 Phase 0

| # | 내용 |
|---|---|
| 0-3 | `load_model_meta()` — `model_meta.json`(n_features/n_classes/normal_index/class_index_to_label)을 아무도 읽지 않았다. `class_index_to_label`을 `labels` 배열로 정규화 |
| 0-4 | `resolve_model_path()` — 파일명이 `lgbm_13class(최종).pkl`(괄호·한글)이라 기존 `models/lgbm_fds.pkl` 탐색으로는 못 찾았다. 우선순위 목록 + glob으로 자동 탐색, `MODEL_REGISTRY`에 `🎯 lgbm_13class (최종·58피처)`로 등록 + **기본 선택** |
| 0-4b | `is_non_model_pkl()` — `get_available_models()`가 `🔍 Le Target`·`🔍 Label Encoders`를 **선택 가능한 "모델"로 노출**했다(고르면 예측이 깨짐). 필터 추가 |
| 0-5 | **Streamlit 캐시 무효화 전멸** — Streamlit은 `_`로 시작하는 인자를 캐시 키 해싱에서 **의도적으로 제외**한다. `_mt`/`_mtimes`/`_lep_mt`/`_lang` 6곳이 전부 no-op이어서 "파일 교체했는데 화면은 그대로"가 발생했다. 밑줄 제거 + `_get_ml_classifier`에 mtime 인자 추가 |
| 0-6 | requirements — **streamlit이 없었다**. `streamlit>=1.49,<2` `plotly` `openai` `joblib` 추가, 전 항목 버전 핀 |
| 0-7a | i18n 17키를 `_V5_KO`(한국어 전용 폴백)에서 TR로 이관 → EN/JA/ZH에서 프롬프트 편집기·챗봇 퀵프롬프트가 한국어로 나오던 문제 해소 |
| 0-7b | LLM 연결 테스트 중복 — 한쪽이 `analyze()` 풀 3콜(1536+200+1536 토큰 / 타임아웃 180+45+180초 = **최대 6분 45초**)을 돌렸다. `test_connection()`(32토큰/12초)으로 통일 |
| 0-7c | `batch_analyzer`: `_call()` 전 `_errors.clear()` — 직전 단건 분석의 스테일 오류가 배치 결과 화면에 유령처럼 섞였다 |
| 0-7d | `run_batch`: 실패 행에서 `progress_cb`가 건너뛰어져 진행바가 멈춘 채 남던 문제 |
| 0-7e | `evaluator.flag_on_ratio`: `float(mean or 0)`은 mean이 NaN일 때 NaN이 truthy라 그대로 통과 → `pd.isna` 분기 |
| 0-7f | `llm_analyzer`: 죽은 변수 `_amount`/`_channel`/`_tx_id` 제거 |

---

## 2. Phase 1 — 원본 → 58피처 변환 + 분류기 선택

### 파생 공식 11개 100% 해독

팀에서 받은 것은 전처리 *코드*가 아니라 산출물(X/y parquet)이었고, **`X_tr`은 셔플 + `reset_index` 상태**라 `FeatureBridge.fit()`은 정렬 자가검증에서 정당하게 거부된다. 대신 고카디널리티 identity 컬럼(`Customer_Birthyear`+`Account_balance`+`Account_initial_balance`) 조인으로 행 대응을 복구해 공식을 역산했다.

```
Transaction_Amount_abs           = |Transaction_Amount|
Transaction_is_withdrawal        = (Transaction_Amount < 0)
Time_difference_seconds          = to_timedelta(Time_difference).total_seconds()
Transaction_Hour                 = Transaction_Datetime.dt.hour
Location_region                  = 시도명 정렬 인덱스 (강원도=0, 경기도=1, 경상남도=2, 경상북도=3 …)
Amount_vs_daily_limit            = |amt| / Account_amount_daily_limit          (±inf → NaN)
Amount_vs_monthly_max_ratio      = |amt| / Account_one_month_max_amount        (±inf → NaN)
Amount_vs_remaining_balance      = |amt| / max(Account_balance + 1, 1)         (±inf → NaN)
unused_terminal_and_internet     = Unused_terminal_status & (Channel == internet)
limit_check_then_transfer        = inquery_atm_limit & increase_atm_limit & (Channel == internet)
large_deposit_and_remote_control = Flag_deposit_more_than_tenMillion
                                   & Customer_flag_terminal_malicious_behavior_2
```

**검증 결과**
```
원본 2행 → 58피처 대조 (train_head2 ↔ X_va 0·1행)   일치 58/58  🎉
X_va  23,860행 × 58 → 재현 불일치 0개  (0.30초)
X_tr  96,140행 × 58 → 재현 불일치 0개  (1.43초)
Preprocessor 경유 macro F1 = 0.6138  (손실 0)
```

범주형 문자→코드 매핑도 `sorted()` 규칙(대문자 < 소문자)으로 9개 전부 클래스 수가 일치하고, `Channel 'internet'→2`, `Customer_Gender 'male'→1`은 원본 대조로 실측 확인했다.

### `pipeline/preprocessor.py`

- **`Preprocessor`** — 원본 47개 통과 + 파생 11개 확정 공식. NaN 정책은 Phase 0-D와 동일(계산 NaN 보존, 컬럼 부재만 기본값)
- **`learn_from_pair(raw_df, eng_df)`** — 원본 CSV와 산출물 X를 받아 범주형·시도 매핑을 **데이터 기준으로 자동 교정**하고 피처별 일치율을 리포트. `Location_region`의 17개 시도 중 4개까지만 실측 확인했으므로(나머지는 정렬 가정), 원본 `train.csv`가 준비되면 다음 한 줄로 전부 확정된다:
  ```bash
  python -m pipeline.preprocessor data/train.csv data/X_tr.parquet
  ```
- **`RawRowClassifier`** — `MLClassifier.predict(row)`와 동일한 `(fraud_type, risk_score, proba_dict)` 반환. `predict_batch()`는 행별 루프 대신 한 번에 변환(5,000건 1.89초)
- 강건성 8종 통과: 컬럼 12개만 있는 행 / 미등록 범주 / 미등록 시도 / `Transaction_Amount` 없음 / NaN / Channel을 코드(2)로 / 내부키 섞임

### 분류기 선택 단일 관문 (`_resolve_classifier`)

기존 판정은 **"row의 값이 전부 수치면 전처리 완료된 행"** 이라는 값-타입 휴리스틱이었다. 실제 오판을 확인했다:

```
                              구 휴리스틱      신 판정
① 직접입력(원본 12필드)         원본        → unknown      ✅
② test.csv 행(원본)           원본        → raw          ✅
③ train.csv 행(라벨포함)        원본        → raw          ✅
④ 합성 행(전부 수치·원본계열)      전처리완료   → raw          ❌ 구버전 오판!
⑤ parquet 전처리완료 행         전처리완료   → engineered   ✅
```

**④가 핵심.** 세션5 방식4(합성 생성)는 문자 컬럼 없이 전부 수치가 나오는데, 구 코드는 이를 "전처리 완료"로 오판해 `RowClassifier`로 보냈다. 원본 컬럼명으로 58피처 모델을 때리니 **조용히 오예측**했다.

**수정:** `_classify_row_shape()`가 컬럼 집합을 대조한다(원본 전용 마커 존재 여부 + feature_cols 커버리지 90%). 단건·배치가 같은 관문을 쓰므로 판정 불일치가 원천 제거됐다. 배포 번들이 선택되면 `RawRowClassifier`가 원본·전처리완료 **양쪽을 정확히 처리**하므로 5개 입력 경로가 하나로 통일된다. 어떤 경로로 예측했는지 UI 캡션으로 표시한다.

### `RowClassifier` 조용한 오예측 → 예외 승격

피처명 불일치 시 경고 로그만 남기고 **row dict 키 순서 그대로 위치 기반 예측을 계속**했다. 값이 전부 엉뚱한 컬럼에 들어가는데 화면에는 정상 결과처럼 보이는 최악의 실패 모드 → `ValueError`로 승격해 `alert_box`로 노출. `predict()`의 `float(row.get(c,0) or 0)`도 문자값 크래시 방어 + NaN 보존으로 교체.

### 검증 하니스 `tools/verify_bundle.py`

```
 모델            : lgbm_13class(최종).pkl  (12.8 MB)
   ✅ label_encoders.pkl ✅ le_target.pkl ✅ feature_cols.json
   ✅ feature_defaults.json ✅ model_meta.json
 기준 macro F1   : 0.6138
 데이터           : X_va.parquet  23,860행 × 58열 · NaN 보유 행 2,196
──────────────────────────────────────────────────────────────────
 경로                      macro F1   µF1(사기)    재현율    정확도  판정
──────────────────────────────────────────────────────────────────
 ① passthrough (기준선)      0.6138    0.6026   0.5349   0.9949  ✅ 기준 일치
 ② Preprocessor           0.6138    0.6026   0.5349   0.9949  ✅ 기준 일치
 ③ MLClassifier           0.6138    0.6026   0.5349   0.9949  ✅ 기준 일치
 ④ MLClassifier(구동작)      0.6070    0.5929   0.5194   0.9948  ⚠️  -0.0068
──────────────────────────────────────────────────────────────────
 Preprocessor 재현 : 58/58피처 일치  🎉
 ✅ 전 경로 정상 — 번들이 파이프라인에 올바르게 붙었습니다.
```

④는 회귀 감시용으로 남긴 구 동작이며 판정에서 제외된다. `③−④ = +0.0068`이 보이면 NaN 보존이 살아있다는 증거다.

---

## 3. Phase 2 — 요청 1·3

### 요청 1 · 배치 리포트 행별 위험점수

기존엔 상위 5건만 프롬프트에 들어가고 나머지는 `avg_risk`/`max_risk` 집계값뿐이라 LLM이 전체 평균으로만 총평했다.

**신설 자리표시자 6개** — `{row_lines}` `{row_lines_note}` `{risk_hist}` `{min_risk}` `{median_risk}` (+ 기존 유지). 프롬프트 편집기 도움말(`PROMPT_VARS_HELP_BATCH`)이 단일 진실 공급원이라 배선 추가 없이 UI에 자동 노출된다.

```
【행별 위험도 판정】
위험점수 최저 0.0000 · 중앙 0.0000 · 최고 0.9999
구간별 0.0~0.2 6건, 0.2~0.4 0건, 0.4~0.6 0건, 0.6~0.8 1건, 0.8~1.0 2건
    4. TXN_******283      | B형 | 위험 0.9999 (+0.4999) | 임계 초과 → 이상
    3. TXN_******259      | G형 | 위험 0.9995 (+0.4995) | 임계 초과 → 이상
    1. TXN_******122      | E형 | 위험 0.7048 (+0.2048) | 임계 초과 → 이상
    2. TXN_******179      | M형 | 위험 0.0002 (-0.4998) | 임계 미만 → 정상
```

괄호는 **임계값과의 마진**이고 ±0.1 이내면 `⚠경계`가 붙는다. 프롬프트 지시문도 *"전체 평균이 아니라 거래 건별 위험점수를 그대로 인용하라, 절대 평균값 하나로 뭉개지 마라"* 로 명시했다.

**🔒 함께 챙긴 것 — 전 행 거래ID 마스킹.** 행별 목록이 LLM으로 나가므로 상위 5건만 마스킹하던 기존 방식으론 부족했다. `_mask_txn_id()`가 ID 마스커만 직접 호출(전체 `mask_row()`는 느림)해 `TRAIN_000283 → TXN_******283`으로 처리한다.

**60건 초과 시**(`MAX_PROMPT_ROWS`) 위험도 상위만 넣고 `… 이하 N건 생략 (위험점수 X 이하, 그 중 임계 초과 M건)`으로 요약해 프롬프트 폭발을 막는다.

**🐛 작업 중 발견한 죽은 코드:** `build_fallback_report`의 `if _t:` 분기는 — `_bt('ko')`도 truthy라 — **한국어 리터럴 블록이 도달 불가**였다. 처음엔 그 죽은 코드를 패치했다가 발견하고, 행별 블록을 두 분기 공통으로 조립하도록 재구성했다. LLM이 실패해도 폴백 보고서에 행별 판정이 남고, ko/en/ja/zh 전부 현지화된다.

### 요청 3 · RAG 참고문서 편집기

세션5 환경설정에 **📚 RAG 참고문서 편집** 패널 추가. 프롬프트 편집기와 동일한 UX.

- `docs/*.md` 파일별 탭 + `text_area` + **💾 저장+재색인** / **🔄 강제 재색인** / **🗑 삭제**(2단 확인)
- **➕ 새 문서 추가** — `../escape.md`·`.hidden` 같은 경로 탈출 시도 거부
- 문서가 없으면 **📄 샘플 문서 생성**

핵심은 `rag_searcher`가 이미 `.docs_sig`(mtime 해시)로 변경을 감지해 자동 재임베딩한다는 점이었다(v10 FIX). 파일만 쓰고 `_get_rag_cached.clear()`로 캐시된 인스턴스를 폐기하면 끝. 강제 재색인의 서명 경로는 `FDS_CHROMA_DIR` 오버라이드를 고려해 하드코딩 대신 `RAGSearcher._SIG_PATH`를 참조한다.

```
① 샘플 생성 → ['fraud_types.md', 'response_manual.md']
② 편집 감지: 75bb9cb0 → abf488b4  ✅ 서명 변경(재임베딩 트리거)
③ 강제 재색인: .docs_sig 삭제 → 다음 init에서 전체 재구축 ✅
④ '../escape.md' / '.hidden' → ❌ 거부   'my_scenarios' → ✅ .md 자동 부착
```

---

## 4. Phase 3 — 요청 2

### 3-a. 챗봇 점검

액션 파이프라인은 튼튼했다. 스텁 환경에서 `_apply_chat_actions`를 실제 실행:

```
✅ goto_session(2) → session_idx=1              ✅ goto_s5_tab(synthetic) → _pending_s5_tab='tab4'
✅ set_manual_field(amount, 90000000)            ✅ set_manual_field(channel, internet)
✅ set_manual_flag(vpn, on)                      ✅ run_detection() → _pending_run_manual=True
✅ goto_batch_subtab(analysis)                   ✅ set_beginner_mode(on)

악성 입력:  ✅ 차단 exec_shell(rm -rf /)   ✅ 차단 goto_session(99)
           ✅ 차단 goto_s5_tab(../../etc) ✅ 차단 set_manual_field(channel, DROP TABLE)
           ✅ 클램프 amount=9e99 → 400,000,000
```

`_pending_*` 키 4개 전부 소비되고(3693/3701/3738/4104행), 세션1~5 컨텍스트도 모두 주입된다.

**고친 버그 3건**

| 버그 | 증상 | 수정 |
|---|---|---|
| 챗 시스템 프롬프트 `text_area`에 `key` 없음 | 질문 전송·액션 적용(=리런)마다 **편집 내용이 날아감** | `key="chat_sys_ta"` + 초기화 버튼이 위젯 값도 복원 |
| `channel`/`os` 완전일치만 허용 | LLM이 `Internet`/`windows`로 쓰면 **조용히 무시**(알림도 안 뜸) | 대소문자·공백 관용 매칭 후 정식 값으로 정규화 |
| 응답이 액션 마커뿐일 때 | 사용자에게 `[[ACTION: goto_session(2)]]` **원문 노출** | 검증된 액션이면 "네, 적용했어요" 안내로 치환(4개국어) |

### 3-b. 음성 입력 — `pipeline/speech_to_text.py`

`st.audio_input`(Streamlit 1.42+, 현재 1.58) + 로컬/클라우드 선택.

- **로컬** `faster-whisper` — 오프라인, tiny~large-v3(base 권장), 프로세스당 1회 로드
- **클라우드** OpenAI 호환 `/v1/audio/transcriptions` — 사내 프록시용 `base_url` 지원
- **자동** — 로컬 우선(개인정보 안전) → 없으면 클라우드
- 같은 녹음 재처리 방지(해시 서명) · 25MB 상한 · `인식되면 바로 전송` 토글 · 구버전 Streamlit 안내

#### 🔒 PII 락 승계 — 이 기능의 핵심 설계

음성은 **마스킹이 불가능한 원본 개인정보**다. 고객 이름·계좌번호·주소를 그대로 말할 수 있다. 따라서 클라우드 STT는 `LLMAnalyzer.cloud_fallback=False` 락(로컬 LLM + 마스킹 스킵)을 우회하는 **새로운 유출 경로**가 된다.

**규칙:** LLM이 로컬 모드면 STT도 로컬만 허용. `allow_cloud=False`면 cloud 백엔드 요청을 거부하고 4개국어로 사유를 설명한다.

```
llm_p5   skip_local  STT     allow_cloud  백엔드   판정
local    True        cloud   False        None    ✅ 차단 (🔒 안내)
local    True        auto    False        local   ✅ 로컬만
local    False       cloud   True         cloud   ✅ 허용
openai   *           *       True         cloud   ✅ 허용
```

가용성 24조합 라우팅을 전수 검증했고, **`allow_cloud=False`인데 `cloud`가 선택되는 경우는 0건**이다.

---

## 5. Phase 4 — 컴팩트 모드

프리미티브(`crow`/`csec`/`csec_row`/`_ch`/`_hc`)는 이미 잘 만들어져 있어 **적용률을 올리는 작업**이었다.

```
세션별 컴팩트 헬퍼 사용   before → after
  세션 01 (147줄)         7 →  7
  세션 02 (488줄)         5 →  5
  세션 03 (147줄)         4 →  4
  세션 04 (103줄)         3 →  3
  세션 05 (1,346줄)       4 →  7   ← 격차가 가장 컸던 곳
```

- **프롬프트 편집기 + RAG 편집기를 좌우 2단**(`crow`) — 세로 2칸 → 1칸
- **자동알림 · PII 마스킹을 `csec()` 접이식으로 재배치** — 삭제가 아니라 재배치(접근 가능 유지). 내부 컬럼 비율도 컴팩트에서 좁게 조정
- **컴팩트 CSS +28줄** — Phase 2·3에서 늘어난 요소를 압축: expander 헤더/본문 패딩, 탭 높이, `stAudioInput` 최소 높이, 채팅 버블/입력창 여백, **행별 판정 블록에 `max-height:260px` + 스크롤**, 버튼 높이, 체크박스(직접입력 12개 플래그 열), 캡션·구분선 여백

⚠️ 초기에 자동알림/PII를 `crow`로 좌우 배치하려 했으나 내부에 이미 `st.columns`가 있어 **중첩 2레벨** 위험이 있었다. 되돌리고 `csec()`(설계된 패턴, expander 안 columns는 1레벨) 방식으로 변경했다.

---

## 6. 전체 코드 검토 결과

```
① 컴파일 · 정적분석
   전체 컴파일 ✅   pyflakes 잔여 경고 = 가용성 탐지용 import 3건(noqa 명시) + f-string 트리비아

② i18n 완전성
   TR 키 수: ko 657 · en 657 · ja 657 · zh 657  (완전 일치)
   dashboard 사용 키 587개 — TR·폴백 모두 없는 키: 없음 ✅
   batch_analyzer / llm_analyzer 누락: 없음 ✅

③ AST 구조 무결성 (들여쓰기 조작 구간)
   dashboard.py      함수 87 · with 177 · try 77   ✅
   batch_analyzer    함수 11 · try 8                ✅
   speech_to_text    함수 11 · try 3                ✅
   preprocessor      함수 19 · with 2 · try 2       ✅
   bundle_io         함수  5 · with 2 · try 7       ✅
   verify_bundle     함수  3 · try 3                ✅
   i18n_data         함수  5 · try 1                ✅

④ 빈 블록 / 도달불가 코드: 이상 없음 ✅

⑤ 잔여 위험 패턴
   맨 pickle.load        3곳 — 전부 안전 확인:
       ml_classifier:32    bundle_io 미배치 시의 폴백 shim
       model_loader:187    joblib 폴백 보유(_load_pickle)
       feature_bridge:455  우리가 pickle.dump로 만든 파일
   Streamlit 캐시 밑줄 인자   없음 ✅
   localStorage/sessionStorage   0건 ✅
   crow → columns 중첩         1레벨(Streamlit 허용 범위) ✅

⑥ 최종 회귀
   ① passthrough 0.6138 ✅  ② Preprocessor 0.6138 ✅  ③ MLClassifier 0.6138 ✅
   Preprocessor 재현 58/58 🎉
```

---

## 7. 남은 과제 / 알려진 제한

> 🔚 **이 표는 v24 에서 전부 정리됐다.** 아래는 당시 기록을 그대로 두되 결론을
> 덧붙인 것이다. 지금 살아 있는 목록은 `OPS_BACKLOG.md` 를 볼 것.
>
> | 당시 항목 | v24 결론 |
> |---|---|
> | `Location_region` 17개 매핑 | **확정** — 94,006행 대조로 17종 전수 일치. 명시적 dict 로 못박음(§11) |
> | `feature_defaults.json` "극단적 정상" | **진단이 부정확했다.** 진짜 원인은 계좌 이력이 0 이라 '실재하지 않는 계좌'가 되는 것 + 자동채움 버튼이 예외로 죽던 것. 번들은 건드리지 않고 우회(§9) |
> | `FeatureBridge` 제거 | **제거 불가** — dashboard 세션2 의 원본 데이터셋 평가에서 실제로 쓰인다(§13) |
> | `MODEL_REGISTRY` 정리 | **실익 없음** — 파일 없으면 이미 자동 숨김, `type` 은 미사용. 주석으로 못박음(§13) |
> | `moonshot` 키 배선 | **수정** — dashboard 사이드바에 입력란 추가(§13) |
> | 실행 검증 미완 | **해소** — AppTest 기반 자체 테스트 12종(§12) |

| 우선순위 | 항목 | 비고 |
|---|---|---|
| 🔸 중 | **`Location_region` 17개 시도 매핑 확정** | 강원도=0 / 경기도=1 / 경상남도=2 / 경상북도=3까지 실측 확인. 나머지 13개는 `sorted()` 가정(확신도 높음). 원본 `train.csv`로 `python -m pipeline.preprocessor data/train.csv data/X_tr.parquet` 한 번 돌리면 자동 교정·확정된다. 세션5 직접입력/합성 경로의 정확도가 여기 달려 있다 |
| 🔸 중 | **`feature_defaults.json`의 기본값이 "극단적 정상"** | 기본값 행의 m margin이 +11.15(2위와 격차 +21.6). 세션5 UI가 만지는 필드는 12개 남짓이고 나머지 46개가 이 값으로 고정되므로, **직접입력으로는 사기 판정이 거의 안 나온다.** 사기 프리셋 버튼 또는 train 분포 기반 기본값 도입 권장 |
| 🔹 낮 | `FeatureBridge` 역할 축소 | 배포 번들에는 `Preprocessor`가 정확하므로 브리지는 다른 계열 모델(🧩컴포지트) 전용으로만 남았다. 사용하지 않으면 제거 가능(510줄) |
| 🔹 낮 | `MODEL_REGISTRY` 기존 6개 항목 | 파일이 없으면 자동 숨김이므로 무해하지만, 새 번들 중심으로 정리하면 세션2 모델 비교 UI가 단순해진다 |
| 🔹 낮 | `moonshot` 키 배선 없음 | `_build_llm_analyzer`가 `ov_moonshot_key`를 읽는데 사이드바에 입력이 없어 항상 `.env`만 사용 |
| 🔹 낮 | 실행 검증 미완 | 이 환경에서 Streamlit을 실제 기동하지는 못했다. 컴파일·AST·파이프라인 단위 테스트는 전부 통과했지만, **UI 렌더는 오빠 환경에서 확인 필요** |

### 작업 중 내가 넣었다가 잡은 버그 (기록용)

1. **세션5 탐지 결과 렌더링 차단** — 모드 캡션을 `elif`로 붙여 `else: try:` 블록을 단락시켰다. 즉시 `if / if / else` 구조로 수정. 만약 탐지 결과가 안 보이면 이 지점(dashboard.py 약 4164행 부근)부터 확인.
2. **죽은 코드 패치** — `build_fallback_report`의 도달 불가 한국어 분기를 먼저 고쳤다가 발견하고 재구성.
3. **컴팩트 2단 배치 중첩 위험** — 자동알림/PII를 `crow`로 감쌌다가 내부 `st.columns` 중첩을 발견하고 되돌린 뒤 `csec()`로 변경.

---

## 8. 트러블슈팅 빠른 참조

| 증상 | 원인 후보 | 확인 |
|---|---|---|
| 세션5 예측이 매번 랜덤 | 번들이 더미 모드 | 로그에 `→ 더미 모드`가 있는지. `pipeline/bundle_io.py` 배치 확인 |
| Channel/OS를 바꿔도 결과 동일 | 수치형 인코더 미감지 | 로그에 `수치형 인코더 45개 감지`가 있는지 |
| 세션2 F1이 0 또는 비정상 | 라벨 디코딩 실패 | `models/le_target.pkl` 존재 + `dataset_loader.py` 갱신본인지 |
| macro F1이 0.6070 | NaN이 채워짐 | `make_batch_preprocess(clf)` 호출에 `keep_nan=False`가 없는지 |
| 파일 교체했는데 화면 그대로 | 캐시 키 밑줄 | `dashboard.py` 갱신본인지 + 완전 재시작 |
| `🔍 Le Target`이 모델 목록에 | `is_non_model_pkl` 미적용 | `dashboard.py` + `bundle_io.py` 배치 확인 |
| 모델 목록에 번들이 안 뜸 | 파일명 탐색 실패 | `python -c "from pipeline.bundle_io import resolve_model_path; print(resolve_model_path('models'))"` |
| 음성 패널이 안 보임 | Streamlit < 1.42 | `pip install -U streamlit` |
| 음성이 로컬만 됨 | PII 락(정상 동작) | 세션5 LLM 제공자를 외부로 바꾸거나 `pii_skip_local` 해제 |
| RAG 문서 수정이 반영 안 됨 | 캐시된 인스턴스 | 🔄 강제 재색인 버튼. 로그에 `docs/ 변경 감지 → 인덱스 재구축` |

---

*작성: v13 기준 · 검증 데이터 `X_va.parquet` 23,860행 / `X_tr.parquet` 96,140행*

---

# v14 — 스크린샷 기반 버그 수정 & 기능 추가 (요청 7건)

## 1. 음성 입력 "An error has occurred, please try again." 원인

**진단:** 스크린샷 캡션이 원인을 그대로 보여준다 — `로컬: — faster-whisper 미설치 · 클라우드: — OPENAI_API_KEY 미설정`.
**STT 백엔드가 하나도 없는 상태**인데 v12 코드가 녹음 위젯을 그대로 렌더해서, 사용자가 3초 녹음한 뒤에야 실패했다.

`An error has occurred, please try again.`(↻ 재시도 아이콘 + 00:03) 자체는 Streamlit `st.audio_input` **위젯/브라우저 단계**의 오류다. 주요 원인 순서:

1. **백엔드 부재** — 인식할 수단이 없는데 녹음을 권하는 UI 자체가 문제 (이 케이스)
2. **마이크 권한 거부 / 입력 장치 없음**
3. **비보안 컨텍스트** — 브라우저는 `localhost` 또는 HTTPS에서만 마이크를 허용한다. 사내 IP(`http://192.168.x.x:8501`)로 접속했다면 마이크가 차단된다

**수정**
- 백엔드가 하나도 없으면 **녹음기를 렌더하지 않고** 설치 안내(`pip install faster-whisper`)와 클라우드 키 안내를 먼저 보여준다
- `🩺 음성 입력 진단` 패널 신설 — Streamlit 버전 / `audio_input` 존재 여부 / 백엔드 가용성 / `llm_p5` / `pii_skip_local` / `allow_cloud` / 마지막 예외 트레이스
- 보안 컨텍스트 안내를 4개국어로 명시
- 최상위 `except`에서 `traceback`을 세션에 저장해 진단 패널에 노출

## 2. 오디오 파일 업로드 입력 (신규)

마이크를 전혀 사용하지 않는 대체 경로. 마이크 권한/HTTPS 문제를 완전히 우회한다.

- `st.file_uploader` — `wav mp3 m4a mp4 ogg oga webm flac aac` (최대 25MB)
- 업로드 후 `st.audio()` 재생 미리듣기 + `🔤 문자로 변환` 버튼
- 인식 결과 확인 → `전송` / `버리기` 선택 (자동 전송 토글도 유지)
- 녹음·업로드 공통 처리 함수 `_stt_run(raw, filename, src)`로 통합, 입력 서명(`src:len:hash`)으로 재처리 방지

**`speech_to_text.py` 보강**
- `AUDIO_EXTS` / `_mime_of()` 추가. 🐛 기존엔 클라우드 전송 MIME이 `audio/wav` 고정이라 **업로드한 mp3/m4a가 서버에서 거부**됐다 → 실제 확장자 기준으로 전송
- 로컬 백엔드: 일부 컨테이너(m4a/webm)는 `BytesIO` 경로에서 실패 → **임시파일 폴백** 추가

## 3. 챗봇 도구 호출 / 에이전트 검증

**핵심 진단:** 스크린샷의 `프로바이더: local · 로컬 전용`은 llama.cpp가 기동돼 있어야 한다. 미기동이면 LLM 응답이 아예 없으므로 **액션이 0건**이 되고, 이것이 "에이전트가 작동하지 않는다"로 보인다. 액션 파이프라인 자체는 정상이다(v12에서 7종 + 악성 입력 방어 전수 검증 완료).

**추가:** `🩺 에이전트 도구 호출 진단` 패널 — **LLM 연결 문제와 파이프라인 문제를 분리**한다.
- `① LLM 연결 확인` → `test_connection()` (32토큰/12초)
- `② 액션 파이프라인 확인` → LLM을 거치지 않고 7종 예시 마커 + 악성 입력 3종을 파싱·검증까지 통과시켜 표로 출력
- `▶ 실제로 실행해보기` → 선택한 액션을 실제 상태에 적용(라이브 테스트)

②가 전부 ✅인데 화면이 안 바뀌면 원인은 100% ①(LLM 연결)이다.

## 4. 세션5 일괄 분석 — 컴팩트 우측 공간 활용

스크린샷에서 우측 패널은 `아직 탐지 결과가 없습니다`로 비어 있는데 배치 결과가 좌측 아래로 쌓여 스크롤을 유발했다.

**수정:** placeholder 패턴 — `crow()` 직후 우측에 컨테이너를 미리 확보하고, `CV and batch_res and not det` 조건에서 배치 결과를 그 컨테이너에 그린다. 단건 결과가 있으면 기존처럼 좌측 아래(상호 배타 유지).

## 5. 합성 데이터 사기 유형 강조

`from_synthetic()`이 각 행에 심는 `_target_type`을 근거로 강조 표시를 추가했다.

- **세션4**: 좌측 컬러 스파인 배너 — 유형 코드 칩(`H형`) + 한글 유형명(`계좌 이상 사기`) + 행 수. `random`이면 보라색 `RANDOM — 전 유형 혼합` 칩 + "실제 유형은 모델 예측으로 확인" 안내
- **세션5 합성 탭**: 미리보기 위에 🎯 유형 칩, 미리보기 **첫 컬럼에 `목표유형`** 노출, 컴팩트에서 표 높이 상한

## 6. 세션4 → 세션5 전송 버튼

`🚀 이 데이터로 세션5 탐지` — 세션5 합성 탭이 읽는 `tab4_rows`와 배치용 `batch_rows`에 그대로 주입하고, `session_idx=4` + `_pending_s5_tab='tab4'`로 탭까지 예약한 뒤 `st.rerun()`. 재생성 없이 **동일한 행**으로 단건 탐지·일괄 분석 모두 즉시 실행된다. 이전 단건 결과(`det`)는 정리한다.

## 7. 컴팩트 무스크롤 최적화 (CSS +30줄)

"한 화면에 한 세션" 목표로 세로 점유를 추가 회수했다.

| 대상 | 조치 |
|---|---|
| 페이지 상단 | `padding-top:0.1rem`, 세션 진행 인디케이터 22px로 축소 |
| 입력 위젯 | 라벨 11px, number/text input 패딩 0.22rem, select 최소높이 32px, slider 패딩 제거 |
| 데이터프레임 | `max-height:300px` 상한 + 헤더 10.5px / 셀 11px |
| 커스텀 HTML 표 | 셀 패딩 5×9px (세션4 PASS/FAIL 표) |
| 알림/배너 | `.alert-box` 패딩 7×12px, 11.5px |
| 결과 패널 | `.result-panel` 패딩 축소, 확률 막대 간격 3px |
| 사이드바 | 챗봇·음성·진단 패널이 늘어난 만큼 상단 패딩·블록 gap 축소 |
| 스페이서 | 인라인 `<br>`까지 `display:none`으로 회수 |
| 파일 업로더 | section 패딩 0.5rem |

## v14 검증

```
컴파일 전체 통과 · pyflakes 클린 · AST 함수 89 · with 184
i18n: ko/en/ja/zh 각 685키 완전 일치 · 누락 0
STT: 백엔드 부재 감지 ✅ · PII 락 유지 ✅ · MIME 매핑 ✅ (wav/mp3→audio/mpeg/m4a→audio/mp4)
에이전트: 액션 7/7 검증통과 · 악성 통과 0건 ✅
모델: ①②③ 경로 macro F1 0.6138 ✅ · Preprocessor 재현 58/58 🎉
```

## v14 트러블슈팅 추가

| 증상 | 조치 |
|---|---|
| 녹음 버튼이 안 보임 | 정상 동작 — STT 백엔드가 없다. `pip install faster-whisper` 또는 OpenAI 키 + 세션5 제공자를 외부로 |
| `An error has occurred` (녹음 중) | ① 마이크 권한 허용 ② `localhost`로 접속(사내 IP는 브라우저가 마이크 차단) ③ 그래도 안 되면 **파일 업로드** 사용 |
| 챗봇이 화면을 안 바꿈 | `🩺 에이전트 진단` → ②가 ✅면 원인은 LLM 연결. ①로 확인 후 llama.cpp 기동 또는 제공자 변경 |
| 업로드한 mp3가 클라우드에서 거부 | v14에서 수정됨 (MIME 고정 → 확장자 기준) |

---

# v15 — 에이전트 확장 · 녹음 파일화 · 온보딩 · 세션2 기본값 (요청 4건)

## 1. 에이전트 액션 7종 → **15종** (요청 1)

기존 7종은 화면 이동과 직접입력 폼에만 닿아서, **대시보드의 핵심 제어를 말로 바꿀 수 없었다**(사용자가 결국 손으로 만져야 했다). 실제 제어 위젯을 감사해 8종을 추가했다.

| 신규 액션 | 예시 | 하는 일 |
|---|---|---|
| `set_threshold` | `set_threshold(0.7)` | 이상거래 판정 임계값. `70%` 표기도 관용 처리 |
| `select_model` | `select_model(lgbm_13class)` | 탐지·평가 모델 (부분매칭) |
| `select_dataset` | `select_dataset(X_va)` | 분석 데이터셋 (부분매칭) |
| `set_eval_mode` | `set_eval_mode(dynamic)` | 세션2 평가 모드 + 세션2로 이동 |
| `run_batch` | `run_batch()` | 일괄 분석 실행 (2건 미만이면 안내) |
| `set_pii_level` | `set_pii_level(strict)` | 개인정보 마스킹 강도 |
| `set_compact_mode` | `set_compact_mode(on)` | 컴팩트 모드 |
| `autofill_high_risk` | `autofill_high_risk()` | 고위험 시나리오 예시값 일괄 입력 |

**🐛 함께 고친 것: 임계값 슬라이더에 `key`가 없었다.** `st.slider(...)`에 `key`가 없어 세션상태로 조작할 방법이 아예 없었다 → `key="th_slider"` 부여.

**⚠️ Streamlit 제약 준수:** Streamlit은 위젯이 생성된 *뒤에* 그 key를 수정하면 `StreamlitAPIException`을 던진다. 챗봇은 스크립트 **맨 아래**에서 렌더되므로, 사이드바 위젯(임계값·언어·데이터셋)을 직접 쓸 수 없다. → 신규 액션도 전부 `_pending_*` 예약 패턴을 따르고, 각 위젯 **생성 직전**에 소비한다.

소비 지점 5곳 신설: `_pending_threshold`(슬라이더 직전) · `_pending_lang`(언어 라디오) · `_pending_dataset`(데이터셋 셀렉터, 부분매칭) · `_pending_pii`(PII 셀렉터) · `_pending_s2_mode`(세션2 라디오). `selected_model`·`compact_view`·`batch_go`는 plain state라 즉시 반영한다.

**파서 확장:** `kind="float"`(0.0~1.0, `%` 관용) · `kind="text"`(1~60자, 실행기에서 화이트리스트 부분매칭).

**검증 (스텁 실행)**
```
액션 15/15 파싱·실행 통과 · 악성 입력 통과 0건
set_threshold(-1) / select_model(존재안함) / set_pii_level(hack) / set_eval_mode(evil) → 전부 차단
run_batch() 데이터 2건 미만 → "먼저 여러 건을 추출하세요" 안내
프롬프트 안내 블록 ko 1,878자 / en 2,376자 (LLM에 자동 부착)
```

## 2. 즉석 녹음 → 파일화 → 입력 (요청 2)

녹음 직후 세 가지 경로를 제공한다. 브라우저 마이크가 불안정한 환경에서도 **한 번 성공한 녹음을 파일로 굳혀두면** 이후엔 안정적으로 재사용할 수 있다.

- **⬇ 파일로 저장** — `st.download_button`으로 내 PC에 `rec_YYYYMMDD_HHMMSS.wav` 저장
- **📌 서버에 보관** — 프로젝트 `recordings/` 폴더에 저장
- **🗂 저장된 녹음** — 최근 12개를 셀렉터로 골라 즉시 재인식 (마이크 불필요)
- 녹음 직후 `st.audio()` 재생 미리듣기 + `🔤 문자로 변환` 수동 버튼 (자동 전송 토글과 병행)

## 3. 첫 방문 온보딩 도우미 (요청 3)

`st.dialog` 모달로 세션 01~05가 각각 무엇을 하고 무엇을 눌러볼 수 있는지 안내한다.

- 세션별 카드 5장 — 컬러 스파인 + 아이콘 + 제목 + 2~3문장 설명(통계 용어를 풀어서)
- **💡 알아두면 편한 것** — 초보자 설명 토글 / 단축키 1~5·C / **"AI 챗봇에게 말로 시킬 수 있다"**(요청 1과 연결) / 컴팩트 모드 / 더미·폴백 모드 안내
- 액션 버튼 3개 — `🔰 초보자 모드로 시작`(초보자 설명 ON + 세션1) / `🚨 바로 탐지해보기`(세션5) / `닫기`
- 사이드바 **`🎓 사용 안내 다시 보기`** 버튼으로 언제든 재호출
- 4개국어 전문 번역

**호환성·재등장 처리**
- `st.dialog`(1.37+) → `st.experimental_dialog` → **인라인 배너** 3단 폴백. `width=` 미지원 버전은 `TypeError`를 잡아 인자 없이 재시도
- 모달 X로 닫으면 `_onboard_mark()`가 호출되지 않아 **매 rerun마다 재등장**하는 문제 → 열자마자 `_onboard_done`으로 이번 세션 표시, 파일 마커(`.fds_onboarded`)는 버튼 클릭 시에만 기록
- 마커 로직 단위 테스트: 첫 방문 표시 ✅ / 같은 세션 리런 숨김 ✅ / 앱 재시작 후 숨김 ✅ / 마커 삭제 후 재표시 ✅
- 파일 쓰기 권한이 없어도 세션 내에서는 정상 동작(예외 무시)

## 4. 세션2 기본값 → 실시간 재평가 (요청 4)

`s2_mode` 기본값을 `static` → **`dynamic`**으로 변경했다. `static`(학습 시점 리포트)은 `eval_result.json` 스냅샷이라 **현재 선택한 데이터셋·모델과 무관한 수치**를 보여줘서, 실제 운용 판단에 쓰기 어려웠다. 이제 진입하면 곧바로 `선택 데이터셋 × 모델` 실시간 재평가가 뜬다. `static`은 라디오로 여전히 선택 가능하고, 에이전트도 `set_eval_mode(static)`으로 바꿀 수 있다.

## v15 검증

```
컴파일 전체 통과 · AST 함수 94 · with 185 · 빈 블록 0 · pyflakes 클린
i18n: ko/en/ja/zh 각 719키 완전 일치 · 정적 키 누락 0 · 동적 온보딩 키(onb.sNN_*) 누락 0
에이전트: 15/15 파싱·실행 통과 · 악성 통과 0건
온보딩: 마커 로직 4케이스 전부 기대대로
모델: ①②③ macro F1 0.6138 ✅ · Preprocessor 재현 58/58 🎉
```

## v15 트러블슈팅 추가

| 증상 | 조치 |
|---|---|
| 온보딩이 매번 뜸 | 버튼(초보자 모드 / 바로 탐지 / 닫기) 중 하나를 눌러야 `.fds_onboarded`가 기록됨. 쓰기 권한 확인 |
| 온보딩을 다시 보고 싶음 | 사이드바 `🎓 사용 안내 다시 보기` · 또는 `.fds_onboarded` 삭제 |
| 챗봇이 임계값을 못 바꿈 | v15에서 슬라이더에 `key="th_slider"` 부여 + `_pending_threshold` 소비 추가 — 갱신본인지 확인 |
| `run_batch()`가 안 됨 | 정상 — `batch_rows`가 2건 이상이어야 한다. test/train/합성 탭에서 여러 건을 먼저 추출 |
| 저장된 녹음이 안 보임 | `📌 서버에 보관`을 눌러야 `recordings/`에 생성된다 |
| 세션2가 예전 수치를 보여줌 | v15에서 기본값이 `dynamic`으로 바뀌었다. 라디오에서 `static`이 선택돼 있는지 확인 |

---

*v15 기준 · 액션 15종 · i18n 719키 × 4개국어 · macro F1 0.6138 유지*

---

# v17 — 세션1 유형 사전 반영 · 단축키 정비 (요청 3건)

## 1. 세션1 사기 유형 사전 — 누락 맞았습니다 🙇

v16에서 `batch_analyzer.FRAUD_TYPE_NAMES`만 고쳤는데, **세션1이 쓰는 사전은 `i18n_data.py`에 따로 3개** 있었다. 전부 옛 정의(원격제어/피싱/스미싱/대출빙자…)로 남아 있었다.

| 사전 | 용도 | 조치 |
|---|---|---|
| `FRAUD_LABELS_I18N` | 차트 범례·라벨 | 13유형 × 4개국어 교체 |
| `FRAUD_SHORT_I18N` | 분포 차트 축 라벨 | 13유형 × 4개국어 교체 |
| `FRAUD_TYPE_DETAILS_I18N` | **세션1 유형 사전 카드**(`fraud_type_popup`) | 13유형 × 4개국어 교체 + `evidence` 필드 신설 |

`evidence`는 신설 필드로, 실측 수치를 카드에 직접 노출한다. 담당자와 AI가 같은 근거를 보게 하려는 것 — 예:

```
J — 대포통장 초기 자금유입                                   [HIGH]
설명: 새로 확보한 대포통장에 처음으로 자금을 유입시키려는 시도입니다.
      수취계좌 정지 이력과 휴면 상태가 동시에 100%인 것이 이 유형의 지문입니다.
핵심 지표: [수취계좌 정지] [미사용 계좌] [거래이력 없음]
실측 근거: 수취계좌 거래중지 100% + 미사용계좌 100% 동시 (전체 각 49%·51%)
          · 수취계좌 거래이력 z=-0.72 전 유형 최저 = 첫 송금 · 저축계좌 34%
```

`risk` 등급도 실측에 맞춰 재배정했다 (F형 MEDIUM→**HIGH** — 규칙 Top-1 96%로 가장 명확히 분리되고 자금세탁 의심 / D·I·L형은 확신도가 낮아 MEDIUM 유지).

m형 카드에는 **경고를 명시**했다: *"정상 거래도 수취계좌 정지 49%·미사용계좌 51%·고액입금 42%·미사용단말 92%를 가지므로, 이 항목들은 사기 판별에 쓸 수 없습니다."*

## 2. 온보딩 단축키 — `H` 신설

`?`는 단축키 모음, `H`는 사용 안내로 나눴다. 온보딩은 **첫 방문에만** 자동으로 뜨고(`.fds_onboarded` 파일 마커), 이후에는 `H` 키 또는 사이드바 버튼으로 호출한다. 온보딩 팁 문구에도 `H`·`?`를 4개국어로 추가했다.

## 3. `?` 단축키 — 비활성이 아니라 **내용이 낙후**돼 있었다

**조사 결과: `?` 핸들러는 정상 작동 중이었다.** (`dashboard.py` 1493행, `e.key==='?'||k==='/'`)

문제는 두 가지였다:
1. **표시 방식** — 우측 하단 12px 토스트 한 줄이라 놓치기 쉬웠다 (`bottom:28px;right:28px`, 9초 후 페이드)
2. **목록 누락** — `kbd.hint`가 `1–5 / ←→ / U / T / L / S / ? / Ctrl+/`만 나열하고, **실제로 구현돼 있던 `C`(챗봇)와 `V`(컴팩트)가 빠져 있었다.** "전체 단축키 모음"이 아니었던 셈

**조치**
- `?`·`/` → **전체 단축키 모음 모달**(`st.dialog`)로 승격. `kbd` 태그로 키캡을 그리고 11개 항목을 전부 나열
- `Ctrl+/`는 기존 토스트 유지 (빠른 참조용) + 토스트 내용에 `C`·`V`·`H` 추가
- 사이드바에 `⌨ 단축키 모음` 버튼 추가 (`🎓 사용 안내` 옆 2단)
- 모달에 두 가지 주의사항 명시: 입력창 포커스 중 비활성(오타 방지) · **한글 IME 조합 중 무시**(`e.isComposing` 가드 때문). 한글 입력 상태에서 눌러도 안 되는 이유가 이것이다

**JS 구현 ↔ 모달 나열 전수 대조 (누락 0)**
```
JS 단일키: . c h l s t u v  + 1~5 · ←→ · ? · / · Ctrl+/
모달 나열: 1 2 3 4 5 · ← → · H · ? / · C · V · U · T · L · S . · Ctrl+/
```

## v17 검증

```
컴파일 ✅ · pyflakes 클린(dashboard) · AST OK
i18n: ko/en/ja/zh 각 739키 완전 일치 · 정적 0 · 동적 온보딩 0 · KEYMAP 라벨 0 누락
유형 사전: 4개국어 × 13유형 · evidence 필드 전부 존재
에이전트 액션 15 · 규칙 13유형 56지표
모델: macro F1 0.6138 ✅ · Preprocessor 58/58 🎉
```

## v17 트러블슈팅 추가

| 증상 | 원인 / 조치 |
|---|---|
| `?` 눌러도 아무 것도 안 뜸 | 한글 입력 상태(IME)면 무시된다 — 영문 입력으로 전환 후 다시. 또는 사이드바 `⌨ 단축키 모음` 버튼 |
| 세션1 유형 이름이 옛 이름 | `i18n_data.py` v17 갱신본인지 확인 (3개 사전이 여기 있다) |
| 유형 카드에 실측 근거가 없음 | `dashboard.py`의 `fraud_type_popup`도 함께 갱신해야 한다 (`evidence` 렌더) |
| 온보딩이 매번 뜸 / 안 뜸 | `.fds_onboarded` 파일 마커. 삭제하면 재등장, 버튼 클릭 시 기록 |

---

# v18 — 발송 에이전트 액션 + 레이아웃 정리 (요청 7건)

## 1. 챗봇 발송 액션 — **2단계 확인 방식** (액션 15종 → 17종)

발송은 다른 14종과 성질이 다르다. 임계값·모델·화면은 되돌릴 수 있지만 **메일은 한 번 나가면 회수가 불가능**하다. LLM이 문맥을 오해해 `send_email()`을 뱉으면 담당자에게 오발송된다.

→ 액션은 **'요청'까지만** 하고, 대시보드가 확인 카드를 띄운 뒤 **사람이 승인 버튼을 눌러야** 전송된다 (Human-in-the-loop).

| 신규 액션 | 예시 | 동작 |
|---|---|---|
| `request_send` | `request_send(slack\|email\|both)` | `_send_request` 적재 + 세션5로 이동. **전송 안 함** |
| `cancel_send` | `cancel_send()` | 대기 중 요청 취소 |

**확인 카드에 표시하는 것** — 채널 · 수신자 · 등급별 제목(`[검토요청]`/`[확정]`) · **마스킹 수준** · 본문 미리보기(Slack/Email 각각) · 첨부 건수. 승인 후 채널별 성공/실패를 개별 표시한다.

**안전성 실측**
```
request_send(both) 실행 후 세션상태:
  {'_send_request': {'ch':'both','at':…,'ft':'e','risk':0.93}, 'session_idx':4}
  → 적재만 되고 발송 코드 미실행 ✅

탐지 결과 없이 request_send(email):
  → "먼저 탐지를 실행해야…" 안내 · _send_request 생성 안 됨 ✅

request_send(hack) → 파싱 단계에서 차단 (enum 검증) ✅
```

액션 17종 전부 파싱→실행 E2E 통과, 실패 0건.

## 2. 사이드바 정리 — 데이터 경로 이주

`📁 데이터 경로`(train/test) 섹션과 그 아래 `데이터 폴더` 입력을 **⋮ 설정 팝오버 → 📁 데이터 경로**로 이주했다. 한 번 정하면 거의 바꾸지 않는 값이 사이드바 상단의 귀한 세로 공간을 3줄이나 차지하고 있었다.

사이드바 데이터셋 섹션에는 이제 **`평가 데이터셋 선택` 하나만** 남는다. 세션상태 키(`cfg_train_path`/`cfg_test_path`/`ds_folder`)는 유지되므로 기존 참조는 그대로 동작한다.

## 3. `🏗️ dashboard build` 캡션 → 사이드바 최하단

기존엔 데이터셋 섹션 중간(누출 경고 토글 바로 아래)에 있어서, 정보성 캡션이 조작 위젯보다 위에 놓여 있었다. 사이드바 맨 끝으로 이동.

## 4. 컴팩트 — 데이터셋 배지 베이스라인 정렬 🐛

**원인:** 배지가 `st.markdown` raw div라 **라벨이 없었다.** 옆의 `비교할 모델`·`표본 상한`은 위젯 라벨이 있어 `vertical_alignment="bottom"`만으로는 라벨 높이 차이를 보정할 수 없었다.

**수정:** 배지 위에 같은 스타일의 라벨 줄(`평가 데이터셋 선택`)을 명시적으로 붙이고, 배지 높이를 컴팩트 select와 동일한 `32px`로 고정. 컬럼 비율도 `1.4:2.2:0.9:0.85` → `1.5:2.1:0.9:0.85`로 미세 조정.

## 5. 컴팩트 — 지표 pills 줄바꿈 침범 🐛

**원인:** `µF1 · Precision · Recall · F1-score` 4개 pills가 `[1, 1.6]` 컬럼의 좁은 폭에서 **2줄로 접히며** 위쪽 차트 영역을 밀어 올렸다.

**수정:**
- 헤더:pills 비율 `1:1.6` → **`0.75:2.25`** 로 재배분
- 컴팩트 CSS 신설 — `flex-wrap:nowrap` · 버튼 높이 24px · 폰트 10.5px · gap 2px
- 헤더 폰트도 11.5px로 축소해 한 줄 확보

## 6. 사이드바 `🎓 사용 안내 다시 보기` → `🎓 사용 안내`

전용 짧은 키(`onb.reopen_short`) 신설. 4개국어 모두 축약 (`Guide` / `使い方` / `使用指南`).

## 7. 컴팩트 — 고위험 자동입력을 탐지 실행과 나란히

기존엔 입력 폼 **위**에 `st.columns([2,5])`의 좌측 버튼으로 있어서, 컴팩트에서 2줄로 접히며 세로를 낭비했다. 게다가 **입력을 다 채운 뒤 누르는 경우가 없다**(누르면 값을 덮어씀) — 폼 앞에 있을 이유가 없었다.

→ 계좌 잔액·접근 매체 **아래**로 내려 `[⚡고위험 자동입력 | ▶탐지 실행]` 2단 배치. 컴팩트는 `1.15:1`, 일반은 `1:1.4` 비율. `width='stretch'`로 가로를 채워 버튼 라벨이 접히지 않는다. 툴팁도 추가(`현재 입력값은 덮어써집니다`).

## v18 검증

```
컴파일 ✅ · pyflakes 클린 · AST OK 함수 96
i18n: ko/en/ja/zh 각 759키 완전 일치 · 누락 0
에이전트 액션 17종 파싱·실행 E2E 통과 (실패 0) · 발송 안전성 3케이스 통과
모델: macro F1 0.6138 ✅ · Preprocessor 58/58 🎉
요청 항목 9개 반영 자동 확인 전부 ✅
```

## v18 트러블슈팅 추가

| 증상 | 조치 |
|---|---|
| 챗봇에 "메일 보내줘" 했는데 안 나감 | 정상 — 확인 카드가 세션5에 뜬다. `✅ 승인하고 발송`을 눌러야 전송 |
| 확인 카드에 수신자가 `(미설정)` | 세션5 `⚙ 탐지 환경 설정`에서 수신 이메일 입력 (`notify_email`) |
| 데이터 경로를 못 찾겠음 | 우측 상단 `⋮` → `📁 데이터 경로` |
| 발송 요청을 취소하고 싶음 | 확인 카드의 `취소` 또는 챗봇에 "발송 취소해줘" |

---

# v19 — 에이전트 승인 게이트 토글

## 설계 원칙: 액션을 "가역성"으로 나눈다

모든 액션에 확인을 붙이면 에이전트를 쓸 이유가 없어지고, 아무 것에도 안 붙이면 LLM 오판이 실제 피해가 된다. 그래서 **되돌릴 수 있는가**를 기준으로 나눴다.

| | 액션 | 처리 |
|---|---|---|
| **가역 15종** | 화면 이동 · 입력 조작 · 실행 · 설정 전체 | 즉시 실행 (확인 요구가 오히려 방해) |
| **비가역 2종** | `request_send` · `cancel_send` | 🚦 승인 게이트 통과 필요 |

## 🚦 승인 게이트 토글 (`agent_send_confirm`, 기본 `True`)

**위치:** 세션5 → `⚙ 탐지 환경 설정` → `자동 발송 설정`

- **ON (기본)** — 챗봇이 발송을 요청하면 확인 카드가 뜨고, 사람이 승인해야 전송
- **OFF (⚡ 즉시 발송)** — 챗봇 요청만으로 바로 발송. 빠른 업무 선호 사용자용

### 게이트를 껐을 때도 유지되는 3가지

| 유지 항목 | 구현 |
|---|---|
| **PII 마스킹** | 컴포저(`_compose_slack_single`/`_compose_email_single`) 내부에서 적용 — 게이트와 독립 |
| **감사 로그** | `_send_audit`에 시각·채널·유형·위험도·수신자·마스킹 수준·성공여부 기록. `🧾 게이트 없이 발송된 기록` 확장 패널에 최근 8건 표시 |
| **경고 표시** | 토글 아래 상시 경고. 마스킹까지 `off`면 🔴 `위험 조합: 마스킹 OFF + 승인 게이트 OFF` 추가 경고 |

### 동작 검증 (스텁 실행)

```
✅ 기본값(키 없음)      → 게이트 적재 O · 즉시 발송 X   ← 기본이 안전측
✅ 게이트 ON 명시       → 게이트 적재 O · 즉시 발송 X
✅ 게이트 OFF          → 게이트 적재 X · 즉시 발송 O
✅ 탐지 결과 없이 요청   → 두 모드 모두 차단 (발송 호출 0회)
```

`_agent_send_now(det, ch, thr)` 헬퍼를 `_build_notifier` 옆에 신설. 채널별 성공/실패를 개별 note로 반환해 챗봇 답변에 그대로 표시된다.

## 모식도 반영

`PIPELINE_DIAGRAM.md`에 3곳 반영 + 상세 절 신설:
- **상세판 ⊕ 횡단 계층** — 가역/비가역 분기 박스 추가
- **간략판** — 승인 게이트 흐름 한 줄 추가
- **대비표** — `에이전트 안전` 행 신설
- **⑤ 에이전트 승인 게이트 — 상세** — 액션 분류표 · ON/OFF 흐름도 · 발표 스크립트

## v19 검증

```
컴파일 ✅ · pyflakes 클린 · AST OK 함수 97
i18n: ko/en/ja/zh 각 767키 완전 일치 · 누락 0
액션 17종 · 게이트 기본값 ON 확인
모델: macro F1 0.6138 ✅ · Preprocessor 58/58 🎉
모식도 370줄 · 최대 표시폭 95자 (슬라이드 안전)
```

## v19 트러블슈팅 추가

| 증상 | 조치 |
|---|---|
| 챗봇 발송이 확인 없이 바로 나감 | `🚦 챗봇 발송 승인 게이트`가 꺼져 있다. 세션5 자동 발송 설정에서 다시 켜기 |
| 게이트 껐는데 마스킹이 걱정됨 | 마스킹은 게이트와 독립적으로 유지된다. 단 `off`로 두면 🔴 경고가 표시된다 |
| 게이트 없이 뭘 보냈는지 확인 | `🧾 게이트 없이 발송된 기록` 확장 패널 (최근 8건) |

---

# v20 — 관제 콘솔 독립 (`ops_dashboard.py` 재구성)

`ops_dashboard.py`를 **dashboard.py에 기대지 않는 자립형 실무자 도구**로 재구성했다.
기능 이식 + 구조 정리 + 관제 도구로서 빠져 있던 4가지(동시 판정·상태 영속·SLA·교대) 신설.

## 0. 한눈에 보기

| 단계 | 내용 | 결과 |
|---|---|---|
| **A** | 공용 렌더 모듈 추출 + 사이드바 이식 | 세션5 UI를 두 앱이 공유 |
| **B** | 누락 기능 이식 (자동발송·감사로그·연결테스트·TTS·이력·단계 재실행) | ops가 세션5 기능 대부분 확보 |
| **C** | 탭 순서 재배치 + 인덱스→이름 | 첫 화면이 "도구"에서 "할 일"로 |
| **D** | 동시 판정 잠금 · 임시저장 · SLA · 교대 인수인계 | 여러 명이 교대로 쓸 수 있게 |
| **E** | 온보딩 팝업 · 사이드바 챗봇 · 사용설명서 | 처음 여는 사람도 3분에 시작 |

### 처음 제안된 방식과 실제 채택안

초안은 **"dashboard.py를 복사해 세션1~4를 지우고 세션5를 남긴 뒤 ops 기능을 이식"** 이었다.
검토 결과 **방향을 반대로 잡았다.**

| | dashboard.py | ops_dashboard.py |
|---|---|---|
| 본체 | 5,807줄 단일 모놀리스 | 1,768줄 |
| 분리 모듈 | 거의 없음 | ops_ui·ops_queries·review_store·ops_alert 등 |
| 자체 테스트 | 없음 | selftest_ops / selftest_alert / selftest_recheck |

- 세션5는 독립 함수가 아니라 `elif current_session=="05":` 블록(약 1,400줄)이고
  `selected_model`·`dual_threshold`·`CV`/`_ch`/`csec`·`SESSION_KEYS` 등 전역에 강결합
- 세션5의 데이터 소스는 **검증셋**, 관제의 소스는 **라이브 DB** — 이미 끝난 재배선을 되돌리는 셈
- 세션5는 이미 ops에 이식돼 있었다 (당시 968~1738행)

→ **ops_dashboard를 베이스로 유지하고, 세션5에서 빠진 부품만 `pipeline/`으로 추출해 공유.**

### 파일 변경 규모

```
신규  pipeline/detect_ui.py        732줄  게이지·확률·유형카드·규칙·TTS·이력  ★공용
      pipeline/ops_dispatch.py     360줄  자동발송·감사로그·연결테스트·단계재실행
      pipeline/ops_sidebar.py      352줄  사이드바 전체
      pipeline/ops_shift.py        340줄  SLA 경과시간·교대 인수인계
      pipeline/asset_registry.py   191줄  모델·데이터셋 탐색            ★공용
      pipeline/ops_guide.py        220줄  첫 실행 온보딩
      ops_dashboard_사용설명서.md         10장 실무자 매뉴얼

수정  ops_dashboard.py          1,768 → 2,195 (+427)
      pipeline/review_store.py    550 →   773 (+223)   v19 → v20
      dashboard.py              5,807 → 5,771  (-36)   중복 3함수 → 위임
```

---

## 1. A단계 — 공용 렌더 모듈 추출

### 문제

`ops_dashboard`의 탐지 결과가 `st.metric` 3개뿐이었다. 세션5에 있던 것들이 통째로 빠져 있었다.

실측 누락 (ops=0건 / dashboard=존재): `risk_gauge` · `prob_bars` · 규칙 체크리스트 ·
사기유형 상세카드 · `_redo_llm_step` · 자동알림 · 감사로그 · 연결테스트 · TTS · `det_history`

### `pipeline/detect_ui.py` (신규)

두 앱이 **같은 함수**를 부른다. 설계 원칙 4가지:

1. `st.session_state`를 읽지 않는다 — 필요한 값은 전부 인자
2. 테마 `T`를 인자로 받는다 (dashboard는 자기 THEMES, ops는 ops_ui.THEMES)
3. i18n은 `lang` + 선택적 `t` 콜러블, 없으면 내장 폴백
4. 필요한 CSS는 `build_css(T)`가 통째로 반환

| 함수 | 역할 |
|---|---|
| `risk_gauge(score, T)` | 반원 게이지 (SMIL 대신 CSS 키프레임 — rerun 연쇄 동결 회피) |
| `prob_bars` / `prob_chart` | 13클래스 확률 |
| `fraud_type_card` | 유형 상세 + 실측 근거 |
| `rule_panel` | 규칙 적합도 (리포트 dict 반환) |
| `verdict_hero` / `detail_table` | 판정 배너 · 4행 상세표 |
| `detection_result` | 위 전부를 세션5와 같은 순서로 |
| `tts_player` | 분석문 음성 재생 |
| `history_append` / `history_table` | 탐지 이력 + 임계값 재계산 |

### dashboard.py 위임

`risk_gauge` / `prob_bars` / `fraud_type_popup` → 얇은 래퍼로 축소 (-36줄).
이제 게이지 모양을 고치면 두 앱에 함께 반영된다.

### 사이드바 이식 (`pipeline/ops_sidebar.py`)

ops에는 사이드바가 아예 없었다 (⋮ 팝오버 하나). dashboard.py 사이드바(1796~2008행)를 이식.

임계값·이중임계값 · 전역 탐지모델 · 데이터셋 · AI 설정 · 알림 채널 · TTS ·
검토자/SLA/마스킹/경로 · 언어/테마 · 워처 배지 · 모듈 버전

**설정의 단일 출처 원칙** — 같은 값을 두 곳에서 고칠 수 있으면 반드시 어긋난다.

- ⋮ 팝오버(db_path/reviewer/lang/theme/pii_level) → 사이드바로 이주, 팝오버 제거
- AI 탭 '분석 설정' 익스팬더 → 사이드바로 이주 (위젯 key `ai_*` 유지 → 본문 무수정)
- 탐지 탭 자체 모델 셀렉터 + 워처설정 임계값 → 사이드바를 따르도록 재배선

### 📂 선택 데이터셋 입력 모드 (신규)

사이드바 데이터셋 선택이 장식으로 끝나지 않게 6번째 입력 모드 추가.
csv뿐 아니라 **parquet X/y 분리 페어**까지 `dataset_loader`가 합쳐서 준다.
라벨 보유 시 `_true_label`을 채워 결과표의 '실제 정답' 칸이 살아난다.

---

## 2. B단계 — 누락 기능 이식

### `pipeline/ops_dispatch.py` (신규)

"탐지했다"와 "사람에게 전달됐다" 사이를 채우는 층.

> **`ops_alert`와 헷갈리지 말 것**
> `ops_alert` = **들어오는** 경보 (DB 폴링 → 화면·소리). 자리에 있을 때 눈치채게 하는 것
> `ops_dispatch` = **나가는** 통보 (Slack/Email 푸시). 화면 앞에 없어도 도달하게 하는 것
> 둘 다 '등급'을 쓰지만 축이 다르다 — `(confirm, review, all)` vs `(none, review, single, confirm)`

| 기능 | 내용 |
|---|---|
| `notify_tier` | 이중 임계값 발송 등급. ②<① 이면 `max(①,②)` 보정 |
| `auto_send` | 자동 Slack/Email + 실패 사유 기록 + 감사 로그 |
| `audit_append` / `render_audit` | 발송 감사 로그 (자동·수동 구분, 최근 50건) |
| `redo_llm_step` | analysis/slack/email **한 단계만** 재생성 |
| `render_connection_tests` | ML·RAG·LLM·SMTP 4종 진단 |

**의존성 주입** — Notifier/LLM/RAG/마스커 생성 방법이 두 앱에서 다르다
(dashboard=`ov_*` 키, ops=`ai_*` 키). 객체를 직접 만들지 않고 **팩토리 콜러블**을 받는다.

### 판단해서 다르게 한 것

- **`_play_alarm`은 이식하지 않았다.** `ops_alert`가 볼륨·조용한시간·중복억제·데스크톱
  알림까지 갖춘 알람 시스템을 이미 소유한다. 오디오 코드를 두 벌 두면 "한쪽만 조용한
  시간을 지키는" 사고가 난다. 수동 탐지도 DB에 저장되므로 ops_alert 폴링이 집어간다.
- **LLM 연결 테스트는 `test_connection()`(32토큰/12초)** — `analyze()` 풀 생성은
  최대 6분 45초다. 연결 확인에 6분을 쓸 이유가 없다.

---

## 3. C단계 — 탭 재배치

### 손이 자주 가는 순서로

| # | 탭 | 빈도 | 근거 |
|---|---|---|---|
| 1 | 🚨 알림 트리아지 | 매시간 | **이 앱의 존재 이유** |
| 2 | 🟢 실시간 감시 | 상시 | 켜 두는 상황판 |
| 3 | 🔄 교대 인수인계 | 하루 2회 | 근무 시작/종료 |
| 4 | 🗃 탐지 로그 | 주 단위 | 조회·조사 |
| 5 | 📉 오탐 분석 | 주/월 | 판정 누적 후 회고 |
| 6 | ⚙ 임계값 튜닝 | 월 단위 | ⑤의 결론을 숫자로 (⑤→⑥ 인과) |
| 7 | 🧠 AI 분석·알림 | 필요시 | 즉석 탐지·배치·챗봇 |
| 8 | 🩺 진단 | 고장시 | 연결·감사·타임존 |

이전에는 **AI 분석이 0번(첫 화면)** 이었다. 관제 도구를 열었을 때 처음 보여야 하는 것은
"지금 내가 처리할 것"이지 도구가 아니다. 코드 주석은 이미 트리아지를 "★ 이 앱의 핵심"이라
적어놓고도 3번째에 뒀었다.

### 인덱스 → 이름

```python
TABS = st.tabs([...], key=TAB_KEY, default=TAB_LABEL["triage"])
(TAB_TRIAGE, TAB_LIVE, TAB_SHIFT, TAB_LOG, TAB_FP, TAB_TUNE, TAB_AI, TAB_DIAG) = TABS
```

이전엔 표시 순서와 `with` 블록 순서가 어긋나(1,2,3,4,5,0,6) 읽기 어려웠고 탭을 추가할
때마다 번호를 다시 세야 했다.

---

## 4. D단계 — 자립성 4종

### ① 동시 판정 잠금 (`alert_claim`)

두 담당자가 같은 알림을 각자 판정하면 `alert_review`에 서로 다른 결론이 두 줄 쌓인다
(`record`는 덮어쓰지 않는다). 어느 쪽이 맞는지 나중에 아무도 모른다.

- 입력을 시작하면 자동 잠금 → 다른 화면에 `🔒 이름`
- **TTL 15분** — 브라우저를 그냥 닫으면 `release`가 오지 않는다. TTL이 없으면 영구 잠금
- **협조적 잠금** — 물리적으로 막지 않는다. DB 레벨 강제 잠금은 워처의 쓰기까지 물릴 수
  있어 위험하고, 현장에선 "누가 보고 있다"를 보여주는 것만으로 충돌 대부분이 사라진다

### ② 상태 영속 (`review_draft`)

판정 중이던 입력이 `st.session_state`에만 있어 새로고침 한 번에 날아갔다.
"켜 두는" 도구에서는 치명적이다.

- `on_change`로 저장 — 바뀐 행 하나만 쓴다 (매 rerun 20행 쓰기 낭비 없음)
- **사람마다 따로** 보관 — 같은 알림을 둘이 볼 때 서로의 메모를 덮어쓰면 잠금이 무의미
- `record()` 성공 시 잠금·임시저장을 **같은 트랜잭션에서** 정리 — "기록은 됐는데 잠금이
  남아 남들이 못 보는" 상태 방지

### ③ SLA 경과시간 (`ops_shift.py`)

큐가 **미판정 여부**만 봐서 3분 전 알림과 6시간 전 알림이 같은 모습이었다.
관제에서 중요한 건 "판정했나"가 아니라 "얼마나 오래 방치됐나"다.

- KPI 4개: 대기 / SLA 초과 / 임박 / 최장 대기
- 헤더에 `🔴 0.930 · … · ⏱ 1시간 30분`
- **기본 정렬을 '대기순'으로** — 점수 높은 건은 이미 누가 봤을 확률이 높고, 방치된 건은
  아무도 안 봤다

> **시간 규약** — DB의 `reviewed_at`·`ts_utc`는 UTC 문자열이다. naive `datetime.now()`로
> 비교하면 9시간이 통째로 어긋난다. UTC로만 계산하고 표시 직전에만 사람 말로 바꾼다.

### ④ 교대 인수인계 (`shift_handover`)

- **📥 앞 근무자가 남긴 것**이 맨 위 — 근무 시작에 볼 것은 내 실적이 아니라 인계 사항
- 📊 근무 요약: 유입/판정/미처리/최장대기 + 정탐·오탐·미탐·보류 + 판정자별
- 📤 작성 → 저장 또는 `.md` 다운로드
- 저장 시 **당시 요약 스냅샷 동봉** — 나중에 숫자가 바뀌어도 "그날 상황"이 남는다

### 스키마 — 신규 테이블 3개

`ALTER`가 아니라 **별도 테이블**이라 기존 `alert_review`에 영향이 없다.
읽기 경로는 테이블을 만들지 않는다 — 대시보드를 열기만 해서는 생성되지 않고, 첫 쓰기에 생긴다.

```sql
alert_claim    (txn_id PK, reviewer, claimed_at)                     -- TTL 15분
review_draft   (txn_id, reviewer, verdict, reason, memo, updated_at) -- 복합 PK
shift_handover (id, author, hours, note, snapshot, created_at)
```

---

## 5. E단계 — 접근성

### 첫 실행 온보딩 (`pipeline/ops_guide.py`)

`st.dialog` 모달(실패 시 인라인 폴백) · 마커 `.ops_onboarded` · 사이드바 `🎓 사용 안내 다시 보기`.
**DB 확인(`st.stop`)보다 먼저** 띄운다 — 처음 여는 사람은 DB 경로부터 틀리기 쉬운데
그때 안내가 안 나오면 빈 에러 화면만 본다.

### 사이드바 상시 챗봇

사이드바 **맨 위**에 `🤖 AI 어시스턴트` 토글. 설정 아래로 내리면 스크롤해야 닿는다 —
급할 때 쓰는 물건이라 "항상 같은 자리, 스크롤 없이"가 접근성의 전부다.

- AI 탭과 **같은 대화**를 공유 (`ops_chat_history`)
- 사이드바는 LLM 빌더보다 먼저 그려지므로, 질문을 **바로 처리하지 않고 세션에 적재**만
  하고 헬퍼가 갖춰진 뒤 처리한다. 이 순서를 어기면 "질문을 보낼 때만 NameError"가 난다

---

## 6. 이번에 잡은 버그 8건

| # | 증상 | 원인 | 조치 |
|---|---|---|---|
| 1 | 앱이 죽음 (`StreamlitDuplicateElementKey`) | 사이드바 `alarm_on`이 `ops_alert` 키와 충돌 | 사이드바는 상태 표시만, 소유권은 실시간 감시 탭 |
| 2 | 경보 카드 클릭해도 탭이 안 바뀜 | `_force_tab`을 세팅만 하고 읽는 곳이 없음 (죽은 코드) | `st.tabs(key=, default=)`(1.58+)로 실제 전환 |
| 3 | AI 탭 단건분석 기본선택이 항상 안 됨 | 트리아지가 `jump_txn`을 pop → 뒤 탭은 항상 None | 소비 지점을 탭 밖 `JUMP_TXN`으로 |
| 4 | "왜 이 유형인가"를 화면에서 못 봄 | `_proba`를 받아놓고 저장 안 함 | `proba_dict` 보존 → 확률 막대 |
| 5 | 멀쩡한 워처에 "훅을 붙이세요" 안내 | `rows==0`을 훅 부재로 단정 | 테이블 존재로 구분 (있음=훅 동작, 0건=캐시할 이상거래 없음) |
| 6 | 온보딩 버튼 먹통 | 모달이 다음 런에 안 그려져 반환값 관측 불가 | `on_click` 콜백으로 전환 |
| 7 | 모델 레지스트리 중복 | `asset_registry`가 `detect_io`와 별개 목록 생성 | `detect_io`에 위임 — "목록엔 있는데 탐지가 깨지는" 모델 방지 |
| 8 | Streamlit 폐기 예정 API | `st.components.v1.html` (2026-06-01 제거) | `st.iframe` 우선 + 폴백 |

> **5번 상세** — `watcher.py:560`에 훅이 이미 있고 `watcher.log`에 부착 로그가 9회
> 찍혀 있었다. `analysis_cache`가 0건인 건 워처가 부착 이후 처리한 행이 0건이었기 때문
> (`watcher_status.rows_done=0`, inbox 파일은 8/4자로 이미 소비됨). 훅은 `is_anomaly=True`
> 인 건만 캐시한다.

---

## 7. v20 검증

Streamlit **AppTest 하네스**(`streamlit.testing.v1`)로 실제 실행 검증.
UI 코드는 컴파일만으로는 아무것도 보장하지 못한다 — 위젯 키 충돌·세션 순서 문제는
실행해야만 드러난다 (실제로 1·6번 버그가 이 방식으로 잡혔다).

```
ops_dashboard 전체 실행     예외 0 · 에러 0 · 탭 25개(중첩 포함)
dashboard.py 전체 실행      예외 0 · 에러 0
dashboard.py 세션5          게이지 1 · 유형카드 1 · 확률막대 1 렌더 확인

[탐지 체인] parquet X+y(96,140행) → 모델 → 예측 m / 정답 m 일치
            배너·게이지·상세표(정답 배지)·확률막대 전부 렌더
[규칙 패널] test.csv 첫 행 → J 대포통장 0.9975 · 규칙 3/4 적중(근거 문구 포함)

[발송 등급] 0.95→confirm  0.80→confirm  0.70→review  0.60→review  0.30→none
            ②<① 보정: t1=.6, t2=.4 → t2=0.6 적용 (원본과 동일)
[자동 발송] 성공: tier=confirm, slack ✅ email ✅
            실패: auto_slack_sent=False + 사유 "webhook 404" 화면 노출
            수신자 없음: 시도 자체를 건너뜀
            review 등급: slack만, email 미시도
[감사 로그] 6건 · 자동/수동 구분

[트리아지 통합]  ① 메모 입력 → DB 영속 + 잠금 자동 획득
                ② 완전 새 세션(=새로고침) → 메모·판정 둘 다 복원
                ③ 타인 잠금 → 경고 표시 · 초안은 사람별 격리
                ④ 저장 → 판정 기록 + 잠금 해제 + 초안 삭제 동시 확인
[잠금 TTL]      만료 시 탈취 · purge_expired_claims 정상
[SLA]           0.5~3000분 전 값 정확 · ISO+Z 파싱 · 깨진 값 None
[교대]          저장 → 다른 사용자 세션에서 앞사람 메모 노출

[탭]  기본 첫 화면 = 🚨 알림 트리아지
      _force_tab 전환 · 선택 유지 · default+session_state 충돌 경고 0
[온보딩] 표시 → 버튼 클릭 시 탭 이동 · 재실행 시 안 뜸 · 강제 재표시
[챗봇]  사이드바 전송 → 실제 답변 수신
        "현재 판정을 기다리고 있는 거래는 총 200건입니다…" (라이브 DB 조회 확인)
```

---

## 8. v20 트러블슈팅 추가

| 증상 | 조치 |
|---|---|
| `🔒 다른이름 님이 검토 중` | 먼저 확인하고 넘어가거나 `🔓 잠금 무시하고 내가 검토`. 15분 후 자동 해제 |
| 잠금이 안 걸림 | 사이드바 `🔒 동시 판정 잠금`이 꺼져 있거나, 검토자 이름이 서로 같다 |
| 메모가 자꾸 날아감 | v20부터 DB 임시저장. `💾` 배지가 안 보이면 검토자 이름이 매번 바뀌는지 확인 |
| SLA 초과가 전부 🔴 | 오래된 미판정이 쌓인 것. 사이드바 SLA(분)로 기준 조정 |
| 교대 요약의 유입 ≠ 판정 | 정상. 유입은 `ops_queries`, 판정은 `review_store`로 출처가 다르다 |
| 캐시 훅 안내가 파란색 info | 정상 연결됨. 캐시할 이상거래가 아직 없다는 뜻 |
| 캐시 훅 안내가 노란색 warning | 진짜 훅 부재. `watcher.py`의 `DetectService` 생성 직후 2줄 추가 |
| 사이드바 챗봇이 안 보임 | `🤖 AI 어시스턴트` 토글이 꺼져 있다 (기본 접힘) |
| 온보딩이 안 뜸 | 이미 봤다. 사이드바 `🎓 사용 안내 다시 보기` 또는 `.ops_onboarded` 삭제 |
| 탭이 8개가 아님 | `ops_shift`/`ops_guide` 미탑재. 🩺 진단 → 모듈 버전 확인 |

## 9. v20 남은 과제

| 항목 | 내용 |
|---|---|
| **잠금 하트비트** | 위젯을 만질 때만 갱신된다. 15분 넘게 한 건을 조사하면 잠금이 풀린다 |
| **selftest 미작성** | 신규 모듈 6개에 기존 `selftest_*.py` 패턴의 자체 테스트가 없다 |
| **dashboard.py 발송 로직** | `_notify_tier`/`_redo_llm_step`이 여전히 별개. 리치 비주얼·HTML 메일·첨부·에이전트 게이트가 얽혀 있어 치환 보류 |
| **dashboard.py 온보딩** | ops와 같은 버튼 먹통 구조로 추정 (`if st.button` 방식) — 미검증 |
| **ops 챗봇 액션** | `enable_actions=False`. 워처 시작/중지는 별도 확인 카드 설계 필요 |

---

# v21 — AI 작업대 전면 · 챗봇 액션 · 일괄 판정 (요청 3건)

## 1. AI 분석·알림을 첫 화면으로

| 항목 | 내용 |
|---|---|
| 탭 순서 | AI 분석이 1번 (`default=TAB_LABEL["ai"]`) |
| 입력 기본 탭 | `📂 선택 데이터셋` — parquet X/y 페어까지 다루는 범용 경로 |
| **추출 범위 부활** | 전체 / 사기 전체 / 정상만 / 개별 유형 a~l |
| **액션 바 복원** | `💾 CSV 저장 │ 📤 inbox 전송 │ ▶ 탐지 실행 │ 📦 일괄 분석 (N건)` |

- 범위 필터는 dashboard.py 세션5 tab3에서 이식. 라벨 없는 데이터셋은 거를 근거가
  없으므로 선택을 숨기고 이유를 표시한다. 라벨 디코딩 실패로 정수가 남아온 경우도
  방어했다(`'m'` 비교가 깨진다).
- inbox 전송은 `.tmp` → 원자적 교체 — 워처가 반쪽 파일을 읽지 않는다.
- **일괄 분석 인계** — 배치 탭에 `분석 대상` 라디오 신설.
  `🚨 알림 큐`(이미 판정된 라이브 → 재분류 안 함)와 `📦 넘겨받은 추출분`
  (미판정 임의 데이터 → 실제 모델로 분류)은 성격이 달라 같은 로직으로 처리하면 안 된다.

## 2. 챗봇 관제 액션 — `pipeline/ops_agent.py` (신규)

`chat_agent.ACTIONS`는 **모듈 전역**이라 ops 액션을 넣으면 dashboard 챗봇 프롬프트에도
섞여 없는 기능을 안내하게 된다. 프로토콜(`[[ACTION: name(arg)]]`)만 재사용하고
레지스트리를 분리했다.

**액션 9종** — `goto_tab` · `goto_input_tab` · `set_scope` · `set_threshold` ·
`set_sla` · `sort_queue` · `select_pending` · `show_summary` · `open_guide`

**차단** — 발송(Slack/Email) · 판정 기록 · 워처 시작/중지.
자연어는 "오탐으로 찍어줘"와 "오탐이면 어떻게 돼?"를 구분하지 못한다.
`select_pending`은 **선택만** 하고 저장 버튼은 사람이 누른다.

> ⚠️ 순서 함정 — AI 탭의 챗 입력은 트리아지 위젯이 이미 생성된 뒤라, 액션이 그 key를
> 건드리면 Streamlit이 예외를 던진다. 사이드바와 같은 경로(적재 → 다음 런에서 처리)로 통일.

## 3. 트리아지 일괄 판정

- 체크박스를 expander **밖**에 배치 — 안에 두면 펼쳐야만 선택할 수 있어
  "훑어보며 여러 건 고르기"라는 목적이 사라진다
- `☑️ 모두 선택` / `⬜ 선택 해제` / `🔴 SLA 초과만`
- **남이 잠근 건은 자동 제외** + 사전 경고
- `record_many()`로 단일 트랜잭션 커밋 — 50번 커밋하면 그만큼 WAL 체크포인트가
  워처 폴링을 밀어낸다

## v21 검증

```
첫 탭 = 🧠 AI 분석·알림 · 입력 기본탭 = 📂 선택 데이터셋 · 범위 셀렉트 존재
액션바: 추출 후 ib_ds/run_ds 렌더, 3건 시 "📦 일괄 분석 (3건)"
배치 인계: rows 3건 전달 · batch_src=handoff 자동 전환
일괄 판정: 모두선택 20건 → DB 0→20건 기록 · 선택 초기화
액션 파싱: 화이트리스트 밖(send_slack)·잘못된 enum 모두 무시
챗봇 실행: "오탐 분석 탭으로 가줘" → 실제 탭 이동
임계값 예약값: 슬라이더 0.5 → 0.75 반영
회귀: ops 예외 0·에러 0 / dashboard.py 예외 0·에러 0
```

---

# v22 — 경보 시스템 전면 재작성 (요청 5건)

## 0. 핵심 — "주입 HTML 버튼은 못 쓴다"

이번 버전에서 가장 값진 배움이다. 같은 함정을 **두 번** 밟았다(경보 카드 · 온보딩 모달).

### 경보 카드가 안 사라지고 버튼도 안 눌리던 이유

`components.html` / `st.iframe` 은 **iframe** 을 만든다. 예전 코드는 그 안에서 카드 DOM 을
만들어 **부모 문서**에 append 했다. 그런데 `onclick` 클로저와 `setTimeout` 은
**iframe 의 실행 컨텍스트** 소유다.

Streamlit 은 리런마다 컴포넌트 iframe 을 파괴·재생성한다. 그 순간
- 예약된 `setTimeout` 이 **취소** → 카드가 영원히 안 사라짐
- `onclick` 이 참조하던 함수의 realm 이 죽음 → 버튼 무반응

카드 DOM 은 부모에 있으니 화면에는 그대로 남는다. 정확히 신고된 증상이다.

1차 수정(컨트롤러를 부모 realm 으로 주입)으로도 실제 브라우저에서는 동작하지 않았다
— CSP·샌드박스 조합에 따라 주입 자체가 막히면 방법이 없다.

### 최종 해결

**클릭이 필요한 것은 전부 `st.button`(네이티브 위젯)으로.**
Streamlit 이 이벤트를 직접 받으므로 realm·CSP 와 무관하게 동작한다.
JS 는 클릭이 필요 없는 것(소리·데스크톱 알림)에만 남긴다.

| | 이전 | 현재 |
|---|---|---|
| 카드 | 주입 HTML (우상단 고정) | **네이티브 위젯** (탭 위, 어느 탭에서든 보임) |
| 버튼 | iframe realm onclick | **`st.button`** |
| 자동 소멸 | JS `setTimeout` | **타임스탬프 비교** (리런마다 재계산) |
| 상태 | DOM | `st.session_state["_ops_active_alerts"]` |

대가: 우상단 고정이 아니라 페이지 상단에 놓인다. **버튼이 실제로 눌리는 것**과 바꿨다.

## 1. 기본값 ON + 소리 자동 무장

- `alarm_on: False → True`. 관제 도구를 열어 둔 사람은 경보를 받으려고 연 것이다.
  기본 등급이 confirm(0.80↑)로 보수적이라 소음은 크지 않다.
- **자동 무장** — 브라우저는 사용자 제스처 전 오디오를 막는다. 예전엔 매번 '활성화'
  버튼을 눌러야 했고 안 누르면 조용히 무음이었다. 이제 페이지 어디든 첫
  `pointerdown`/`keydown` 에 AudioContext 를 깨운다(그것도 정당한 제스처다).

## 2. 삐- 반복 횟수 설정

하드코딩 3회 → `alarm_beeps` 1~10 슬라이더.
관제실에서 3회는 짧고 10회는 고문이다 — 소음 허용치는 현장마다 다르다.

## 3. 트리아지 정렬 방향

`내림차순` 토글 추가. 대기순/점수순 × 오름/내림 4가지 조합.

| 설정 | 상위 점수(검증) |
|---|---|
| 대기순 내림 | 0.047 (가장 오래 기다린 건) |
| 대기순 오름 | 1.0 |
| 점수순 내림 | 1.0 |
| 점수순 오름 | 0.0 |

## 4. 윈도우 알림 → 탐지 로그

알림 클릭 시 `gototab=log` 를 붙여 **탐지 로그**로 보낸다.
알림을 누르는 사람이 보고 싶은 건 "그 건이 무엇이었나"(당시 데이터·분석)다.
경보 카드의 `확인하기` 는 판정이 목적이라 트리아지로 간다 — **의도적으로 다르다.**

## 5. AI 탭 탐지도 로그에 남긴다

수동 탐지 시 `analysis_store.save()` 를 호출한다. 예전엔 AI 분석을 돌린 경우에만
저장돼, 수동 탐지는 로그 목록에는 떠도 내용이 비어 있었다.
LLM 리포트는 나중에 같은 `txn_id` 로 합류한다.

## 6. AI 분석 자동/수동 토글

`🧠 탐지와 동시에 AI 분석 실행` — **기본 ON**.
이상거래를 본 담당자가 원하는 다음 동작은 거의 항상 "이유 알기"다.
LLM 이 느릴 때(로컬 모델 수십 초) 탐지 결과 확인까지 막히므로 끌 수 있게 남겼다.

## 7. 온보딩 버튼 먹통 — 같은 함정, 다른 얼굴

`st.dialog` 은 **매 rerun 마다 데코레이트된 함수를 다시 호출해야** 열린 상태가 유지된다.
예전 구현은 안내를 띄우는 그 순간 '봤음'으로 확정해, 버튼을 누른 뒤의 rerun 에서
`maybe_show()` 가 일찍 return → 모달 본문 미실행 → ① 모달이 닫히고 ② 위젯이
재생성되지 않아 클릭이 관측되지 않았다. `on_click` 콜백으로 바꿔도 마찬가지였다
— 닫힌 모달의 위젯은 이벤트를 전달할 대상이 없다.

→ 열림 상태를 **세션 플래그(`_ops_guide_showing`)로 유지**하고, True 인 동안 매 rerun
모달을 다시 그린다(Streamlit 공식 패턴). 버튼은 평범한 반환값 방식으로 복귀.

## v22 검증

```
alarm_on 기본 True · alarm_sound True · 삐 반복 슬라이더(기본 3) 존재
정렬 내림차순 토글 존재 · 4가지 조합 모두 의도대로 정렬
테스트 경보 → 배너 카드 렌더 → [확인하기] 클릭 → 트리아지 이동 · 경보 0건
                              → [닫기] 클릭 → 경보 0건
수동 탐지 → 분석 캐시 rows 5→6 · astore.load() 조회 성공
AI 자동 분석: 토글 ON → 자동 실행·수동버튼 없음 / OFF → 수동버튼 표시·미실행
온보딩: 표시 → [트리아지로 시작] → 탭 이동·닫힘 → 추가 리런에도 재출현 없음
        [닫기] → 닫힘 · 리런 2회 후에도 버튼 생존(= 클릭 가능)
회귀: ops 예외 0·에러 0 / dashboard.py 예외 0
```

> 소리·Windows 알림은 브라우저 영역이라 AppTest 로 검증할 수 없다.
> `🟢 실시간 감시 → 🩺 소리·알림 상태 진단` 이 오디오 상태·알림 권한·컨트롤러 주입을
> 읽어 표시하고, 권한이 있으면 테스트 알림을 실제로 1건 띄운다.

## v22 트러블슈팅 추가

| 증상 | 조치 |
|---|---|
| 경보음이 안 남 | 화면 아무 곳이나 클릭(자동 무장) → 🩺 진단에서 오디오 상태 확인 |
| 윈도우 알림이 안 뜸 | 🩺 진단의 `데스크톱 알림` 항목 · `denied`면 자물쇠 아이콘에서 허용 · Windows 집중 지원 확인 |
| 경보 카드 버튼 무반응 | v22에서 네이티브 위젯으로 전환돼 해결. 그래도 안 되면 F5 |
| 경보가 너무 자주/드물게 | 울릴 등급(확정만/검토+확정/전체)과 재알람 억제 분을 조정 |
| 삐 소리가 길다/짧다 | `삐- 반복 횟수` 1~10 |
| 온보딩 버튼 무반응 | v22에서 해결(지속 플래그 패턴) |
| 수동 탐지가 로그에 안 보임 | v22부터 저장된다. 이전 탐지는 소급되지 않는다 |

## v22 남은 과제

| 항목 | 내용 |
|---|---|
| **경보 위치** | 우상단 고정 오버레이를 원하면 커스텀 컴포넌트(React)를 만들어야 한다 |
| **잠금 하트비트** | 여전히 위젯 조작 시에만 갱신 (15분 초과 조사 시 잠금 해제) |
| **selftest 미작성** | 신규 모듈 8개에 자체 테스트 없음 |
| **dashboard.py 온보딩** | ops 와 같은 함정 구조 — 미검증·미수정 |
| **LLM 액션 준수율** | 로컬 모델이 `[[ACTION:]]` 마커를 항상 붙이지는 않는다 |


---

# v23 — 레이더 경보 카드 복원 (클로저 없는 재구현)

## 왜 되돌렸나

v22에서 경보를 네이티브 위젯으로 바꾸며 **동작은 보장했지만 시각을 잃었다** —
우상단 플로팅 · 레이더 스윕 SVG · 헤일로 펄스가 모두 사라지고 페이지 상단의
평범한 카드가 됐다. 관제실 화면에서 '탐지'의 시각 언어는 레이더다.

## 핵심 — 카드가 문제가 아니었다

깨진 것은 **클로저와 JS 타이머**였지 카드·CSS가 아니었다.
그래서 **클로저를 하나도 쓰지 않고** 같은 카드를 다시 만들었다.

| 요소 | v21 이전 (깨짐) | v23 (동작) |
|---|---|---|
| 닫기 | `el.onclick = function(){…}` — iframe realm 클로저 | **인라인 `onclick` 속성** |
| 자동 소멸 | `setTimeout` — iframe 파괴 시 취소 | **CSS 애니메이션** (`animation-delay`) |
| 클릭 이동 | `W.location.href` 클로저 | **`<a href>`** — JS 없는 내비게이션 |

인라인 `onclick` **속성**은 그 요소를 소유한 문서(=부모)의 realm 에서 컴파일된다.
클로저와 결정적으로 다른 지점이고, 이것이 이번 복원을 가능하게 한 열쇠다.

CSS 자동 소멸은 `opsOut … var(--ttl) forwards` 로 구현했다. 마지막 프레임에서
`height/padding/border` 를 0으로 접어 빈칸도 남지 않는다.

## 바뀐 UI

버튼 칸을 없애고 **정보 + ✕** 만 남겼다. 대신 **카드 전체가 링크**라
어디를 눌러도 탐지 로그로 간다 — 버튼이 사라졌는데 조작은 더 쉬워졌다.

## 배너는 폴백으로

v22의 네이티브 배너는 지우지 않고 `alarm_banner`(기본 OFF)로 남겼다.
엄격한 CSP 등으로 플로팅 카드가 안 보이는 환경의 대안이다.
알림 방식 토글이 4개가 됐다: 사운드 · 데스크톱 · 🛰 플로팅 카드(ON) · 📋 상단 배너(OFF).

## v23 검증

```
미치환 토큰 0 · 레이더 SVG(opsRadarSweep/Blip) 포함 · 우상단 고정 CSS 확인
CSS 자동소멸(opsOut var(--ttl)) · X 인라인 속성 · <a href> + gototab=log 확인
JS 클로저 핸들러: 1건(데스크톱 알림 n.onclick — 정상)
setTimeout 실제 사용: 0회 (검출된 1건은 주석 안 설명문)
배너 폴백 ON → 네이티브 버튼 3종 렌더 → 확인하기 → 트리아지 이동
회귀: ops 예외 0·에러 0 / dashboard.py 예외 0
```

## 런처 정리 — `start_fds_all_ops.bat`

**이 파일은 `start_fds_all.bat` 과 바이트 단위로 동일했다.** 이름만 ops 였고
`TUNNEL_TARGET=dashboard` 라, ops 런처를 써도 실제로 외부에 공개되는 것은
**분석용 dashboard.py** 였다.

| 항목 | 변경 |
|---|---|
| `TUNNEL_TARGET` | `dashboard` → **`ops`** (ngrok 이 :8502 를 공개) |
| 창 제목 | `FDS Ops Server - ngrok publishes ops_dashboard.py (:8502)` |
| 로그 파일 | `start_fds_all_ops_log.txt` 로 분리 (두 런처 동시 실행 시 덮어쓰기 방지) |
| 요약 출력 | ops 를 먼저 · `<== PUBLISHED via ngrok` 표시 |

> ngrok 무료 플랜은 동시 터널이 1개뿐이라 둘 중 하나만 공개된다.
> 분석 대시보드를 공개하려면 `start_fds_all.bat` 을 쓴다.

---

# v24 — 관제 콘솔 전면 점검 (점검 10건 + 이월 과제 전부 + 자체 테스트 12종)

v23 까지의 '남은 과제'를 진행하기 전에 `ops_dashboard` 를 전수 점검했다.
문서에 적힌 과제보다 **먼저 닫아야 할 것 9건**이 나왔고, 셋 다 공통점이 있다 —
**화면이 사실과 다른 것을 말하고 있었다.** 기능이 없는 게 아니라, 있다고 표시된
것이 실제와 달랐다. 그래서 이 셋을 우선 처리했다.

## 1. 수동 탐지가 관제 화면 어디에도 없었다 — 원장 이원화

### 증상

AI 탭 `▶ 탐지 실행` 으로 만든 건이 **트리아지 큐 · 탐지 로그 목록 · 경보 폴링**
어디에도 나오지 않았다. 저장은 되는데 화면에서 도달할 수 없는 상태로,
`analysis_cache` 에 그렇게 갇힌 건이 8건 쌓여 있었다.

### 원인

| 주체 | 쓰는 곳 | 읽는 곳 |
|---|---|---|
| `detect_io.save_detection` (ops) | `detections` 만 | — |
| `detect_service._save_transactions` (워처) | `transactions` | — |
| `ops_queries._ledger` | — | **`transactions` 가 있으면 그쪽만** |

`_ledger` 가 `transactions` 를 우선하는 것은 옳다(주석 270행: `detections` 는
PK UPSERT 라 재탐지하면 이전 판정이 덮어써져 판정 대상 원장으로 부적격).
빠진 것은 ops 쪽 writer 였다.

> PATCH_NOTES5 v22 의 "수동 탐지도 DB에 저장되므로 ops_alert 폴링이 집어간다"(L994),
> "로그 목록에는 떠도 내용이 비어 있었다"(L1319) 두 서술은 이 때문에 사실이 아니었다.
> v22 에서 `_det_alert_pending` 으로 수동 경보를 UI 에서 직접 쏘게 만든 것이
> 이 증상의 흔적이다 — 폴링이 못 집으니 우회한 것이다.

### 조치

- `save_detection` 이 **두 테이블 모두**에 쓴다. `detect_service._save_transactions`
  와 같은 '존재하는 컬럼에만 INSERT' 방식이라 구/신 스키마 어디서든 동작한다.
  원장은 append-only 를 지킨다 — 재탐지는 새 알림으로 쌓이고 판정 이력이 안 덮인다.
- `source` 인자 신설. `input_mode` 에 `ops:manual` / `ops:dataset:…` 로 남아
  워처 건(`watcher:파일명`)과 구분된다.
- 두 테이블이 **같은 UTC 문자열** 하나를 공유한다.
- `TZ_DECLARED[("detections","detected_at")]` `local` → **`auto`**.
  두 writer(`dashboard._save_detection_to_db`, `detect_io.save_detection`) 모두
  `datetime('now')`(UTC)로 쓰는데 `local` 로 선언돼 있어, 🩺 진단이 74행 전부를
  불일치로 표시하고 있었다. 폴백 경로에서는 9시간이 어긋났을 값이다.
- 수동 탐지가 원장에 들어가면 폴링이 같은 건을 **두 번째로** 울린다.
  `poll_new` 가 '아직 화면에 떠 있는 경보'를 건너뛰고, `fire()` 가 재알람 억제
  기록도 남긴다. 재알람 억제(분)를 0으로 둔 사람의 설정을 뒤엎지 않는 방식이다.

### 부수 발견 — 트리아지 탭 크래시 (실데이터 재현)

원장이 append-only 라 워처가 같은 파일을 재처리하면 같은 `transaction_id` 가
2~3줄이 된다. 판정은 `txn_id` 단위(`alert_review`)라 두 줄을 따로 찍을 수도 없는데,
화면에서는 위젯 key(`cb_{tid}`)가 겹쳐 **`StreamlitDuplicateElementKey` 로 탭 전체가
예외**로 죽었다.

```
표시 20 → 중복 0종     표시 50 → 중복 0종
표시 100 → 중복 5종   ← 트리아지 탭 사망 (운영 DB 에서 재현됨)
```

→ `alert_queue` 가 `txn_id` 기준 최신 1줄만 남긴다. 재탐지 이력은 탐지 로그의
`astore.history`("🔁 재분석 N회")가 따로 보여주므로 정보 손실이 없다.

### 과거분 복구 — `tools/backfill_ops_ledger.py` (신규, 선택)

원장에 없는 detections 가 72건(최근 2일 17건 · 이상거래 13건). 되살리는 도구를
두되 **기본은 미리보기**다. 적재분은 `input_mode='ops:backfill'` 이라 한 줄로 되돌린다.

```
python -m tools.backfill_ops_ledger --days 2          # 미리보기
python -m tools.backfill_ops_ledger --days 2 --apply  # 적재
```

> 적재하면 트리아지 큐에 '미판정'으로 올라온다. 시연·테스트 탐지가 섞여 있다면
> 그냥 두는 편이 깔끔하다 — 그래서 자동 실행하지 않는다.

## 2. 경보 등급이 실제 임계값을 안 읽었다

### 증상 — 같은 화면에 세 가지 기준

| 위치 | 쓰던 기준 |
|---|---|
| 폴링 · 실시간 피드 · 트리아지 | 워처 설정 **0.005 / 0.9** ✅ |
| 소음 예보 `noise_forecast` | 하드코딩 **0.45 / 0.80** ❌ |
| 등급 라벨 `"확정만 (0.80↑)"` | 문자열 고정 ❌ |
| 수동 탐지 tier | 사이드바 **0.5 / 0.5** ❌ |

"켜기 전에 대가를 보여준다"는 소음 예보 패널이 **실제와 다른 기준으로 계산된
숫자**를 보여주고 있었으니, 그 패널의 존재 이유가 무너져 있었다.

### 근본 원인 — '등급'이 두 체계인데 이름이 같다

- **경보(alert) 등급** — 워처가 이 건을 어떻게 취급했는가. `watcher_config.json` 소유.
- **발송(dispatch) 등급** — 이 콘솔이 내보내는 통보 정책. 사이드바 세션 상태 소유
  (`ops_dispatch.notify_tier`).

둘 다 `th_review` / `th_confirm` 이라 불리고 화면 어디에도 구분이 없었다.
사이드바가 `0.50` 을 보여주는 동안 워처는 `0.005/0.9` 로 돌고 있었다.

### 조치

| 대상 | 변경 |
|---|---|
| `ops_dashboard._tier_th()` / `_tier_of()` | 신설. **경보 등급의 단일 출처 = 워처 설정.** 호출부 6곳 전부 교체 |
| `ops_alert.tier_label(key, lang, thr, thc)` | 신설. 4개 언어 라벨의 숫자를 실제 임계값으로 치환 |
| `ops_alert.fmt_th()` | `0.005` 가 `0.01` 로 뭉개지지 않게 |
| `ops_alert.noise_forecast(…, th_review, th_confirm)` | 하드코딩 제거 — 호출부가 넘긴다 |
| `DEFAULT_TH_REVIEW/CONFIRM` | 폴백 숫자를 모듈 한 곳에만 |
| 테스트 경보 점수 | `0.93/0.55/0.30` 고정 → 실제 경계에서 산출 |
| 경보 패널 · 사이드바 | `등급 기준: 검토 0.005↑ · 확정 0.9↑ — watcher_config.json` 상시 표시 |

`tier_label` 은 모르는 key 를 그대로 돌려준다 — 예전처럼 조용히 `confirm` 으로
폴백하면 잘못된 key 를 넘겨도 그럴듯한 화면이 나와 원인을 못 찾는다.

## 3. 발송 감사 로그가 6개 경로 중 2개만 기록했다

### 증상

| 경로 | 예전 |
|---|---|
| 탐지 결과 → Slack / Email | ✅ 기록 |
| 단건 분석 → Slack / Email | ❌ **누락** |
| 배치 리포트 → Slack / Email | ❌ **누락** |

그런데 진단 탭은 *"자동·수동을 가리지 않고 Slack/Email 로 나간 모든 시도를
기록합니다"* 라고 안내하고 있었다. **감사 로그 자체가 거짓말을 하고 있었다.**

원인은 단순하다 — 버튼마다 `nn.send_slack(...)` 다음에 `audit_append(...)` 를
손으로 짝지어 붙이는 구조였다. 복붙이 6번 반복되면 4번은 빠진다.

### 조치 — 기록을 빠뜨릴 수 없는 구조로

- `ops_dispatch.send_manual()` 신설 — **보내고, 반드시 감사 로그를 남기고**,
  `(성공, 오류메시지)` 를 돌려준다. 발송과 기록이 한 함수 안에 묶여 분리 불가능하다.
- `ops_dashboard._send()` — 화면의 **모든 발송 버튼이 이 함수 하나만** 부른다.
  6개 경로 전부 교체. 화면 코드에서 `audit_append` 직접 호출은 0건이 됐다.
- **실패도 기록한다.** `send_manual` 은 예외도 잡아 기록한다 — SMTP 가 끊겨
  예외가 나는 것이야말로 감사 로그에 남아야 할 사건이다.
  `auto_send` 도 마찬가지로 고쳤다: 예전에는 예외가 `audit_append` 를 통째로
  건너뛰어, 화면에는 실패가 뜨는데 감사 로그는 비어 있었다.
  수신 이메일 미설정처럼 **시도조차 못 한 경우**도 남는다 — "왜 메일이 안 왔지?"의
  답이 거기 있어야 한다.
- 감사 항목에 `txn_id` · `err` 추가. 옛 기록에는 없는 필드라 읽는 쪽은 `.get()` 을 쓴다.

## 4. 미리보기가 옛 본문인데 전송은 새 본문이 나갔다 — 위젯 스테일

### 증상

Streamlit 은 위젯 key 가 이미 세션에 있으면 **`value=` 를 무시한다.**
그래서 `st.text_area(value=새본문, key="…")` 는 두 번째 렌더부터 새 본문을
보여주지 않는다. 이 앱의 6곳이 정확히 그 형태였다.

| 위치 | 증상 |
|---|---|
| `det_email_prev` | 🔁 재생성해도 미리보기는 옛 본문 — **그런데 전송은 새 본문**이 나갔다 |
| `batch_email_prev` | 배치를 다시 돌려도 이전 배치의 이메일이 그대로 |
| `ai_email_prev_{tid}` | 같은 건을 재분석하면 미리보기가 안 바뀜 |
| `prompt_ta_{slot}` | **'기본값 복원'이 화면에 반영 안 됨** — 세션 값은 지워지는데 편집창은 그대로 |
| `rag_ta_{name}` | 파일이 밖에서 바뀌어도 편집창은 옛 내용 |
| `apply_thr` | 비용을 바꿔 최소비용 지점이 이동해도 슬라이더는 첫 계산값에 고정 |

첫 줄이 가장 위험하다. **보이는 것과 실제로 나가는 것이 달랐다.**
담당자는 A 를 검토하고 보냈는데 상대는 B 를 받는다.

> 반대로 트리아지 '☑️ 모두 선택' 은 멀쩡하다 — 버튼이 위젯 생성 **전에**
> `st.rerun()` 을 부르면 Streamlit 이 그 위젯 상태를 정리해 주기 때문이다.
> AppTest 로 두 패턴을 실측해 이 차이를 확인했다.

### 조치 — `_sync_widget(key, source)`

원본의 해시를 함께 들고 있다가 **원본이 바뀐 순간에만** 위젯 값을 덮어쓴다.

- 재생성·배치 재실행처럼 **원본이 바뀌면** 미리보기가 따라간다.
- 원본이 그대로면 건드리지 않으므로 **사람이 고친 내용은 보존된다.**
  (매번 동기화하면 편집이 불가능해진다 — 그 사이를 가르는 것이 해시다.)

이메일 미리보기 3곳은 여기서 한 걸음 더 갔다. 예전에는 편집해도 그 내용이
버려지고 원본이 나갔다 — 편집 가능한 것처럼 보이는데 아니었다.
이제 **그 칸에 보이는 그대로 발송**되며, 캡션으로도 그렇게 안내한다.

### v24 과제4 검증

```
재생성 시나리오   원본 V1 → V2 로 교체 시 미리보기 갱신 ✅ (예전엔 V1 고정)
                  세션 값 = 발송 대상 = 화면 표시  일치 ✅
편집 보존         손으로 고친 문장이 리런 후에도 생존 ✅ · 발송 대상도 편집본 ✅
                  이후 재생성하면 새 본문이 이긴다 ✅ (의도된 동작)
프롬프트 복원     초기화 클릭 → 편집창이 기본 템플릿으로 ✅ (예전엔 그대로)
튜닝 슬라이더     fp_cost 3만→300만 → 추천 0.1→0.45, 슬라이더가 따라감 ✅
                  (판정 표본 40건을 심은 DB 사본에서 검증)
AppTest 회귀      예외 0 · 에러 0
```

## 5. 경보 카드를 눌러도 그 거래가 열리지 않았다

### 증상

경보 카드는 `?goto=<txn>&gototab=log` 로 탐지 로그 탭을 연다(ops_alert.py:702).
그런데 **탭만 바뀌고 그 거래는 선택되지 않았다.** 담당자는 표에서 손으로 찾아야 했고,
표시 건수 밖(기본 50건)이면 검색까지 해야 했다.

원인은 단순하다 — `JUMP_TXN` 을 트리아지·AI 단건분석만 소비하고 **탐지 로그 탭은
읽지 않았다.** 사용설명서 L341 은 "카드 클릭 → 그 거래의 당시 데이터·분석"이라고
안내하고 있었으니, 여기도 문서와 동작이 어긋난 자리였다.

### 조치

- 딥링크로 들어온 거래를 **목록 맨 위로 끌어올리고 상세를 바로 연다.**
  필터(이상거래만·검색어)나 표시 건수에 걸려 안 보일 수 있으므로, 없으면
  최근 500건에서 따로 찾아 붙인다 — 눌렀는데 빈 화면이 나오는 것이 최악이다.
- 못 찾으면 **못 찾았다고 말한다.** 오래된 거래이거나 원장에 없는 건일 수 있다.
- 포커스를 세션(`log_focus`)에 담는다. `JUMP_TXN` 은 첫 런에서 소비되므로,
  이게 없으면 필터를 한 번만 건드려도 상세가 닫힌다.
- 표에서 **다른 행을 직접 고르면** 포커스는 역할을 다한 것으로 보고 해제된다.
  `✕ 포커스 해제` 버튼도 뒀다.

### v24 과제6 검증

```
대조군        딥링크 없이 열면 상세 닫힘 ✅
딥링크 진입   탐지 로그 탭 선택 ✅ · 안내 표시 ✅
              ★ 목록 40번째(=표시 25건 밖) 거래의 상세가 열림 ✅
              쿼리 파라미터 소비됨 — 새로고침해도 재이동 안 함 ✅
지속성        필터를 바꿔도 상세·포커스 유지 ✅ (예전 구조로는 즉시 닫혔다)
해제          ✕ 클릭 → 상세 닫힘 · 세션 포커스 제거 ✅
없는 거래     "찾지 못했습니다" 안내 ✅ (조용한 빈 화면 아님)
```

## 6. 검색이 "최근 N건 안에서만" 동작했다 — 필터 순서

### 증상

탐지 로그의 조회는 이 순서였다.

```python
rows = oq.alert_queue(DB, limit=lg_n, …)          # ① N건을 뽑고
rows = [r for r in rows if r["is_anomaly"]]        # ② 파이썬에서 거르고
rows = [r for r in rows if q in r["txn_id"]]       # ③ 파이썬에서 검색
```

`limit` 이 **거르기 전의 건수**를 뜻하게 된다. 그래서

- 검색어는 **최근 N건 안에서만** 매치했다. 그 밖의 거래는 아무리 정확한 ID 를
  넣어도 영원히 안 나온다. placeholder 는 "TXN_ / 비우면 전체"라고 적혀 있었다.
- `이상거래만` 을 켜면 화면에 표시 건수보다 훨씬 적게 남는다.
- 실시간 피드도 같은 구조였다(`live_feed` 가 12건을 뽑아 파이썬에서 걸렀다).

### 조치 — 조건을 SQL 로 내린다

`alert_queue` 에 `txn_like` · `only_anomaly` 를 추가했다. 이제 `limit` 은
**거른 뒤의 건수**를 뜻한다. `live_feed` 도 파이썬 필터를 버리고 넘겨준다.

- 검색어의 `%` · `_` 는 `_like_escape()` 로 리터럴 처리한다. 특히 `_` 는 거래 ID 에
  흔한 문자라, 이스케이프하지 않으면 '아무 글자 하나'로 해석돼 엉뚱한 결과가 나온다.
- SQLite 의 `LIKE` 는 ASCII 대소문자를 구분하지 않는다 — 거래 ID 는 ASCII 라
  기존 `.lower()` 비교와 결과가 같다.
- 화면은 검색 중임을 `🔎 <검색어> — 원장 **전체**에서 검색해 최신 N건` 으로 알린다.
  검색 중에는 알림 포커스(과제5)를 끌어올리지 않는다 — 검색 결과가 아닌 거래가
  맨 위에 끼면 '내가 찾은 것'과 섞인다. 검색어를 비우면 포커스가 다시 살아난다.

> 📌 측정 주의 — 운영 DB 는 `is_anomaly=1` 이 **총 4건뿐**이라, '건수 50 → 4행' 은
> 잘림이 아니라 정상 출력이다. 이 결함은 *이상거래가 최신 구간 밖에 있을 때*
> 드러나므로, 검증은 그런 분포를 만든 사본에서 했다.

### v24 과제5 검증

```
검색(운영 DB · 읽기만)
  최신에서 41번째 거래를 표시 25건 상태에서 검색
    예전 방식 0건 (재현) → 새 방식 1건 ✅
  부분 문자열 ✅ · 대소문자 무시 ✅
  '%' → 0건 (전체 107건이 아님) ✅   '_' → 7건(밑줄 포함 거래만) ✅
이상거래 필터(사본에 시드 — 최신 40행을 정상으로 채움)
  limit=10 · 예전 0건 → 새 10건, 전부 이상거래 ✅
  실시간 피드 12건 · 예전 0건 → 새 12건 ✅
  검색+이상거래 동시 30건 ✅ · 중복 제거와 함께 동작(70행 고유 70) ✅
화면
  표시 25건 밖 거래를 검색으로 찾아낸다 ✅ · '원장 전체에서 검색' 안내 ✅
```

## 7. 자잘하지만 조용히 틀리던 것 3종

앞의 여섯 건과 달리 각각은 짧다. 공통점은 **아무 에러도 안 내면서 틀린 값을
쓰고 있었다**는 것이라 묶어서 처리했다.

### 7-1. CSV 의 행 번호가 거래 식별자로 둔갑했다

`save_detection` 은 `row['ID']` 를 그대로 `transaction_id` 로 썼다. test.csv /
train.csv 의 ID 가 `1`, `2` 같은 **행 번호**면 그건 거래 식별자가 아니다.
파일이 다르면 같은 `1` 이 전혀 다른 거래인데, `detections` 는 PK 라 **서로
덮어쓴다.** 실제 DB 에 `'1'` 과 빈 문자열 키가 남아 있는 것이 그 흔적이다.

→ `make_txn_id(row, source)` 신설.

| 입력 | 결과 |
|---|---|
| `TXN-F14A75AE24`, `TRAIN_000009` | 그대로 — 같은 거래 재탐지는 같은 행 갱신이 옳다 |
| `1` (test.csv) | `TEST_CSV_20260809_024417_1` |
| `1` (train.csv) | `TRAIN_CSV_20260809_024417_1` — 출처가 다르면 다른 ID |
| `''`, `nan`, 없음 | `MANUAL_20260809_024417_7691` (기존 형식 유지) |

행 번호를 뒤에 남겨 추적성을 지키고, 원본 `ID` 는 `raw_json` 에 그대로 있다.

### 7-2. `watch_inbox` 는 아무도 설정하지 않는 키였다

`📤 inbox 전송` 이 `st.session_state.get('watch_inbox', 'inbox')` 를 읽는데
**이 키를 어디서도 쓰지 않았다.** 항상 폴백을 타서, 워처 감시 폴더를 바꿔도
전송은 늘 `inbox/` 로 갔다. (같은 코드가 dashboard.py 사본 3개에도 있다.)

- `_DEFAULTS` 에 `os.getenv("FDS_INBOX", "inbox")` 로 배선 — `db_path`/`log_path`/
  `model_dir` 과 같은 규칙이다.
- 사이드바 `📁 경로` 에 **워처 감시 폴더** 입력란 추가.
- 전송 후 **해석된 절대 경로**를 보여준다. 폴더가 그 자리에서 새로 만들어졌으면
  경고한다 — "보냈는데 아무 일도 안 일어난다"의 원인이 대개 이것이다.
- `watcher.py` 의 `--inbox` 기본값도 같은 환경변수를 읽는다.
  > ⚠️ 런처(`run_watcher.bat` 등)는 `--inbox inbox` 를 **명시적으로** 넘긴다 —
  > 인자가 환경변수를 이긴다. `FDS_INBOX` 로 폴더를 옮기려면 런처의 그 인자도
  > 함께 지워야 한다.

### 7-3. `requirements.txt` 하한이 실제보다 낮았다

`streamlit>=1.49` 였는데 이 콘솔은 `st.tabs(key=…, default=…)` 를 쓴다 — **1.58+**
다. 1.49~1.57 환경에서는 탭을 만드는 순간 `TypeError` 로 앱이 아예 뜨지 않고,
화면에는 스택 트레이스만 남는다.

- 하한을 `>=1.58` 로 올리고 이유를 주석으로 남겼다.
- 앱 최상단에 **버전 가드**를 뒀다. 낮으면 `st.stop()` 으로 멈추고
  "무엇이 필요하고 무엇을 하면 되는지"를 화면에 쓴다.

### 7-4. 문서의 옛 임계값

`pipeline/ARCHITECTURE.md` 의 소음 예보 표에서 `(0.80↑)`·`(0.45↑)` 표기를 걷어내고,
그 수치가 **측정 당시 기본값 기준**이며 현재 경계는 `watcher_config.json` 이
정한다는 주석을 달았다. (`consolidated_codes.md` 는 코드 덤프 생성물이라
재생성 시 자동으로 따라온다 — 손대지 않았다.)

### v24 과제7 검증

```
txn_id   진짜 ID 3종 보존 ✅ · 숫자 ID 는 출처+시각으로 한정 ✅
         test.csv 의 1 ≠ train.csv 의 1 ✅ · 쓰레기 ID 6종 → 생성 ✅
         실제 저장: 두 파일의 '행 1' 이 각각 저장(74→76행) ✅
         원본 ID 는 raw_json 에 보존 ✅
inbox    세션에 실제 값 존재 ✅ (예전엔 키 자체가 없었다)
         사이드바 필드 렌더 ✅ · FDS_INBOX 환경변수 반영 ✅
         절대 경로 표시 ✅ · 워처도 같은 환경변수 ✅
버전     requirements >=1.58 ✅ · 가드 존재 ✅
         1.50 을 흉내내면 st.stop() 으로 막힌다 ✅ (본문 렌더 0)
```

## 8. 감사 로그 영속화 + 2단계 확인 삭제 (결정 D2)

### 왜

과제3 에서 "기록이 빠지는 발송 경로"는 없앴지만, 기록은 여전히 **세션 상태에만**
있었다. 새로고침 한 번이면 사라진다. "외부로 나간 것은 회수할 수 없다"가 이
로그의 존재 이유인데, 휘발성 로그는 감사 자료가 될 수 없다.

### `pipeline/audit_store.py` (신규)

같은 DB 에 `notify_audit` 테이블 하나. `review_store`/`analysis_store` 와 같은 규칙:

| 원칙 | 이유 |
|---|---|
| 어떤 실패도 던지지 않는다 | **감사 기록 실패가 통보를 막으면 주객전도.** DB 가 잠겨 있어도 발송은 진행되고, 대신 화면에 "감사 저장 실패"를 덧붙인다 |
| 시각은 UTC 저장 | 표시 직전에만 로컬로. `ops_queries` 와 같은 규칙 |
| 읽기 경로는 테이블을 만들지 않는다 | '아직 발송이 없었다'와 '연결이 안 됐다'를 구분해야 한다 |

기록 항목: 시각·성공여부·채널·거래ID·유형·위험도·수신처·마스킹 레벨·경로(auto/manual)·
실패사유·수행자. `session_state` 사본은 화면 즉시 표시용으로 남기되, **DB 가 있으면
그쪽이 진실**이다(`render_audit` 이 DB 를 우선한다).

### 삭제 — 2단계 확인

담당자가 지울 수 있어야 한다는 요청. 다만 감사 로그는 되돌릴 수 없는 발송의 유일한
증거라, 버튼 한 번에 사라지면 안 된다.

```
① 범위 선택(N일 이전 / 전체 · 실패 기록 보존 여부) → [삭제 준비]
     ↓  몇 건이 지워지는지 세어서 보여준다
② ⚠️ 되돌릴 수 없습니다 · "N건을 삭제합니다" 체크 → [영구 삭제]
```

- **1단계에서 건수를 먼저 보여주는 것이 핵심이다.** 몇 건이 사라지는지 모르는 채로
  누르는 삭제는 확인 절차가 아니다. 지울 것이 0건이면 삭제 버튼 자체를 만들지 않고
  "지울 것이 없습니다"만 띄운다.
- 체크박스를 켜기 전에는 [영구 삭제] 가 **비활성**이다.
- `실패 기록은 보존` 이 기본값 — 실패는 '왜 안 갔는지'의 증거라 남기는 쪽이 안전하다.
- 언제든 [취소] 로 빠져나올 수 있다.

### 삭제 자체도 기록한다

지운 뒤 같은 테이블에 `via='purge'` 한 줄을 남긴다 — **언제 · 누가 · 몇 건 · 어떤
범위**. 전체 삭제를 해도 이 흔적은 남고, 다음 삭제 대상에서도 제외된다.
로그가 조용히 비어 있는 것과 "2026-08-09 에 홍길동이 120건을 지웠다"가 남아 있는
것은 완전히 다른 이야기다.

### v24 과제8 검증

```
영속화    성공/실패/거래ID/수행자/실패사유/UTC 시각 저장 ✅
          ★ 빈 session_state(새 세션)에서도 DB 에서 그대로 읽힌다 ✅
          감사 저장이 실패해도(없는 경로) 발송은 성공 보고 ✅
삭제 1단계 전체 22건 / 90일 이전 20건 — 미리 정확히 센다 ✅
삭제 2단계 실패 보존 옵션 동작(성공분 15건만 삭제) ✅
          ★ 삭제 사실이 로그에 남는다(수행자·건수·범위) ✅
          전체 삭제 후에도 삭제 흔적만 남는다 ✅
화면      준비 전에는 [영구 삭제] 버튼이 아예 없다 ✅
          체크 전 비활성 → 체크하면 활성 ✅ · 건수 미리 표시 ✅
          취소 → 확인 단계 닫힘 · 아무것도 안 지워짐 ✅
          끝까지 눌러 8건 삭제 → 최근 기록 보존 · 흔적 1줄 추가 ✅
```

> 📌 결정 D1(과거 탐지 백필)은 **하지 않기로** 했다. `tools/backfill_ops_ledger.py`
> 는 남겨 두었으니 나중에 필요하면 쓸 수 있다.

### 검증이 운영 DB 를 건드린 사고 (2건째)

과제3 의 검증은 **실제 발송 버튼을 누른다.** 발송 시도가 DB 에 기록되기 시작하면서,
그 테스트가 운영 DB 에 감사 기록 1건(127.0.0.1:9 연결 거부)을 남겼다.
→ 그 행을 지우고, 해당 테스트가 **DB 사본**을 쓰도록 고쳤다.
`selftest_alert` 때와 같은 교훈이다 — **쓰기를 하는 테스트는 반드시 사본에서.**
(`notify_audit` 테이블 자체는 비어 있는 상태로 남겨 두었다. 기능이 설치된 이상
첫 발송에서 어차피 만들어진다.)

## 9. 직접입력이 '실재하지 않는 계좌'를 그리고 있었다

### 문서의 진단이 틀렸다 — 먼저 실측

PATCH_NOTES5 §7 은 *"기본값이 극단적 정상이라 직접입력으로는 사기 판정이 거의
안 나온다 · UI 가 만지는 필드는 12개, 나머지 46개 고정"* 이라고 적고 있었다.
실제로 재보니 **셋 다 부정확했다.**

| 문서 | 실측 |
|---|---|
| UI 12개 / 고정 46개 | **22개 제공 / 36개 고정** |
| 사기 판정이 거의 안 나온다 | 6,912개 조합 스윕에서 **17.2% 가 사기**, 최고 risk 0.99996 (중앙값은 0.000008 — '어쩌다 맞춰야 나온다'가 정확한 표현) |
| 기본값이 극단적 정상 | 기본값 vs 사기 중앙값 z-score 최대 **0.69**. 진짜 사기 행의 UI 밖 피처를 **전부 기본값으로 덮어도 탐지 185→199 로 유지**된다 |

### 진짜 원인 두 가지

**① 자동채움 버튼은 눌리는 순간 예외로 죽고 있었다**

버튼이 위젯들보다 **아래**에 있는데 `st.session_state['det_amount']` 를 직접 고쳤다.
→ `StreamlitAPIException: cannot be modified after the widget ... is instantiated`.
그 아래 [탐지 실행] 버튼까지 렌더가 끊겼다. **사기 프리셋이 사기를 못 만든 게
아니라 아예 동작한 적이 없었다.** (v22 '온보딩 버튼 먹통'과 같은 함정 —
예약 → 다음 런에서 소비하는 패턴으로 풀었다.)

**② 계좌 이력이 0 인 계좌는 학습 데이터에 없다**

| 피처 | 번들 기본값 | 정상 계좌 중앙값 | 정상 데이터의 0 비율 |
|---|---:|---:|---:|
| `Account_one_month_max_amount` | **0** | 14,140,000 | 9.4% |
| `Account_one_month_std_dev` | 0 | 4,798,938 | 35.2% |
| `Account_initial_balance` | 750,207 | 9,680,268 | **0.0%** |

"한 달간 거래가 전혀 없던 계좌에서 8,500만원이 빠져나갔다" 는 조합이 학습 분포에
없어, 모델이 그 지점을 자신 있게 'm' 으로 읽는다.

```
자동채움 현재            → m · 0.1839   (= 정상 판정)
one_month_max_amount 만 현실값으로 → j · 0.9871  (+0.80)
계좌 이력 5개 모두 현실값으로      → d · 0.8781
기본 상태(정상이어야 함)           → m · 0.0000  ← 보정해도 그대로 ✅
```

**정상은 정상으로 두면서 사기 프리셋만 살아난다** — 이것이 이 수정의 핵심 근거다.

### 조치 (B) — 번들을 건드리지 않는다

`models/feature_defaults.json` 을 고치는 안은 **버렸다.** 그 파일은 팀 배포 번들의
일부(읽기 전용)이고 `evaluator`·`ml_classifier`·`preprocessor` 가 공유해서,
dashboard.py 세션2 평가 결과까지 함께 바뀐다.

대신 `detect_io.ACCOUNT_HISTORY_DEFAULTS` 를 두고 **직접입력 행이 계좌 이력을
직접 채우게** 했다. 값은 `train.csv` 의 **정상 행 중앙값** — 사기 값이 아니라
'평범한 실제 계좌'다. 프리셋이 사기가 되는 이유는 계좌를 사기처럼 꾸며서가 아니라,
**계좌가 실재하게 되어** 나머지 사기 신호(거액 출금·원거리·루팅·VPN)가 비로소
의미를 갖기 때문이다.

### 조치 (C) — 보이지 않던 값을 화면으로

`🏦 계좌 이력` 익스팬더 신설. 5개 값을 직접 조절할 수 있고, 각 항목에 그것이
무엇이고 왜 중요한지 도움말을 붙였다. `↩ 기본값으로` 버튼도 뒀다.
**값을 0 으로 되돌리면 옛 증상이 그대로 재현된다** — 원인을 화면에서 확인할 수 있다.

### v24 과제9 검증

```
상수      계좌 이력 5개 · one_month_max_amount 가 0 이 아님 ✅
판정      기본 상태 m/0.0000 유지(오탐 유발 없음) ✅
          ★ 자동채움 m/0.1839 → d/0.8781 사기 판정 ✅
회귀      실제 사기 186/200 탐지 · 실제 정상 0/200 오탐 ✅
스윕      직접입력 반응성 26.2% → 38.9% (떨어지지 않음) ✅
화면      계좌 이력 5개 입력란 노출 ✅ · 되돌리기 버튼 ✅
          ★ [자동채움] → [탐지 실행] → d · 0.8781 · is_anomaly=True ✅
          ★ 계좌 이력만 0 으로 → 0.8781 → 0.4747 로 하락(원인 확정) ✅
          자동채움이 사용자가 0 으로 둔 값도 되돌린다 ✅
```

> 📌 진단 과정에서 내가 한 번 틀렸다. `predict_batch` 로 재보다가 "같은 값 0.0 을
> 넣기만 해도 risk 가 뛴다"는 결과를 얻었는데, 변환 벡터를 직접 비교하니 차이가 0
> 이었다. 원인은 **배치 병합**이었다(아래 참조). 단건 `predict()` 로 다시 측정해
> 결론을 바로잡았다.

### 🐛 함께 발견 — `predict_batch` 의 단건/배치 불일치 (→ 아래 후속에서 수정)

`predict_batch` 는 행들을 하나의 DataFrame 으로 합치는데, **키 구성이 다른 행이
섞이면** 없는 값이 기본값이 아니라 **NaN** 이 된다(pandas 열 합집합).
`predict()` 는 기본값 경로라 같은 입력에 다른 답이 나온다.

```
같은 행:  단건 0.183917  vs  배치 0.993156
```

배치는 보통 같은 CSV 에서 오므로 평소엔 드러나지 않지만, `📦 일괄 분석` 으로 넘긴
추출분에 직접입력 행이 섞이면 재현된다. → `OPS_BACKLOG.md` 에 남겨 두었다.

### 🔧 후속 — `predict_batch` 단건/배치 불일치 수정

위에서 남겨 뒀던 그 버그를 닫았다.

**메커니즘** — `pd.DataFrame(리스트)` 는 **열의 합집합**을 만든다. 키 구성이 다른
행을 한꺼번에 넣으면, 어떤 행에는 원래 없던 컬럼이 'NaN 을 가진 컬럼'으로 생긴다.
그 순간 두 가지가 어긋난다:

1. `transform()` 의 기본값 채우기는 **컬럼 자체가 없을 때만** 동작한다.
   계산 결과의 NaN 은 일부러 보존하기 때문이다(LightGBM 이 native 로 처리하는 신호).
   → NaN 이 그대로 모델에 들어간다.
2. `_derive()` 는 **컬럼이 있는가**로 파생 여부를 정한다(`has(...)`).
   → 없어야 할 파생이 켜지고, 입력이 NaN 이라 결과도 NaN 이 된다.

**수정** — 행을 **키 구성별로 묶어** 변환한다. 각 행이 '혼자 왔을 때'와 똑같이
처리되고, 같은 CSV 에서 온 행들은 그룹이 하나뿐이라 속도 이점도 그대로다.

```
[1] 예전에 깨지던 조합   단건 0.183917/0.987341 == 배치 0.183917/0.987341 ✅
[2] 역순으로 넣어도 대응 ✅ (그룹핑이 순서를 망치지 않는다)
[3] 무작위 이질 행 60개(그룹 50개) 전부 단건과 일치 ✅
[4] 동질 400행 = 그룹 1개 · 배치 0.05초 vs 단건환산 6.41초 — 속도 유지 ✅
[5] 빈 리스트 · 1행 배치 ✅
```

> `MLClassifier.predict_batch` 는 행별 루프라 애초에 이 문제가 없다.

## 10. dashboard.py 온보딩 — '추정'이 아니라 사실이었다

v20 부터 *"ops 와 같은 버튼 먹통 구조로 추정 — 미검증"* 으로 남아 있던 항목.
AppTest 로 세 버튼을 실제로 눌러 확인했다.

### 증상 — 예외는 안 나는데 아무 일도 안 일어난다

```
[온보딩 시작] 클릭 → 예외 0 · 모달은 닫힘 · beginner_mode = None  (True 여야 함)
[탐지로 이동] 클릭 → 예외 0 · 모달은 닫힘 · session_idx   = 0     (4 여야 함)
```

**ops v22 §7 과 완전히 같은 함정이었다.** `st.dialog` 은 매 rerun 마다 데코레이트된
함수를 다시 호출해야 열린 상태가 유지되는데, 예전 구현은 **안내를 띄우는 그 순간**
`_onboard_done = True` 로 확정했다. 그래서 버튼을 누른 뒤의 rerun 에서
`not _onboard_seen()` 가 False → 모달 본문 미실행 → ① 모달이 닫히고 ② 위젯이
재생성되지 않아 **클릭이 관측되지 않았다.** `_onboard_done` 이 True 로 보이는 것도
버튼이 눌려서가 아니라 **열 때 찍힌 값**이었다 — 그래서 '닫히니까 동작한 것 같다'는
착시가 생긴다.

### 조치 — ops_guide 와 같은 지속 플래그 패턴

- 열림 상태를 `_onboard_showing` 플래그로 **유지**하고, True 인 동안 매 rerun 모달을
  다시 그린다. 버튼이 눌리면 `_onboard_close()` 가 플래그를 내리고 rerun 한다.
- 파일 마커(`.fds_onboarded`)는 **여는 즉시** 남긴다 — X 로 닫아도 다음 실행에
  또 뜨지 않게. 다시 보려면 사이드바 '🎓 사용 안내' 또는 단축키 `H`.

### v24 과제10 검증

```
[온보딩 시작] → beginner_mode = True ✅   [탐지로 이동] → session_idx = 4 ✅
[닫기]        → 닫힘 ✅
세 버튼 모두: 예외 0 · _onboard_showing=False · 파일 마커 True
              추가 렌더에도 재출현 없음 ✅
단축키 H(사용 안내 다시 보기) → 온보딩 재호출 ✅
회귀: dashboard.py 예외 0·에러 0 / ops_dashboard 예외 0·에러 0
```

> 검증 중 두 번, AppTest 의 **잔상**에 속을 뻔했다. `st.rerun()` 이 끼면 rerun 직전
> 패스의 위젯이 element 목록에 남아 '모달이 안 닫혔다'처럼 보인다(클릭한 버튼까지의
> 것들이 순서대로 남는 것으로 정체가 드러났다). 닫힘 판정은 **세션 플래그**로 해야 한다.

## 11. `Location_region` 17개 시도 매핑 — 확정

§7 이 *"강원도=0 / 경기도=1 / 경상남도=2 / 경상북도=3 까지 실측 확인. 나머지 13개는
`sorted()` 가정(확신도 높음)"* 으로 남겨 둔 항목. 재료(`data/train.csv` +
`data/X_tr.parquet`)가 그대로 있어서 문서가 적어둔 명령을 그대로 돌렸다.

```
python -m pipeline.preprocessor data/train.csv data/X_tr.parquet
  → learn_from_pair: 94,006행 정렬 성공
  → ↻ 데이터 재학습: Location_region(17개 시도 확인 (가정과 일치))
```

**가정이 옳았다. 17종 전부, 불일치 0.** train.csv·test.csv 양쪽 모두 미등록 시도 0개.

| 코드 | 시도 | 행 수 | 코드 | 시도 | 행 수 |
|---:|---|---:|---:|---|---:|
| 0 | 강원도 | 11,351 | 9 | 세종특별자치시 | 1,315 |
| 1 | 경기도 | 18,411 | 10 | 울산광역시 | 1,670 |
| 2 | 경상남도 | 10,077 | 11 | 인천광역시 | 2,371 |
| 3 | 경상북도 | 14,692 | 12 | 전라남도 | 12,181 |
| 4 | 광주광역시 | 1,877 | 13 | 전라북도 | 8,016 |
| 5 | 대구광역시 | 2,745 | 14 | 제주특별자치도 | 619 |
| 6 | 대전광역시 | 1,587 | 15 | 충청남도 | 12,200 |
| 7 | 부산광역시 | 2,190 | 16 | 충청북도 | 14,423 |
| 8 | 서울특별시 | 4,275 | | | |

### 조치 — 계산에서 **명시**로

값 자체는 그대로 두되, `REGION_MAP_DEFAULT` 를 `sorted(SIDO_LEVELS)` 에서 파생시키지
않고 **명시적 dict** 로 못박았다.

파생 방식의 위험: 시도 이름을 한 줄 추가·삭제·수정하는 것만으로 **그 뒤 코드가 전부
밀린다.** 에러는 나지 않고 예측만 조용히 틀어지는데, 모델은 이 정수를 그대로 학습한
값이라 나중에 되돌릴 방법도 없다. '확정'의 의미는 값을 알아낸 것뿐 아니라
**다시 흔들리지 않게 고정하는 것**까지다.

### v24 과제11 검증

```
매핑     17종 · 코드 0~16 중복 없음 · **예전 sorted() 결과와 동일**(값 변화 0)
실측     learn_from_pair 교정 0건 · "17개 시도 확인 (가정과 일치)"
커버리지 train/test 미등록 시도 0개 · 인코딩 NaN 0 · 범위 0~16
회귀     17개 시도가 서로 다른 코드로 인코딩 ✅
         실제 300행 예측 분포 정상 · selftest 5종 · verify 7종 통과
```

> 같은 CLI 가 `Time_difference_seconds` 일치율 **99.866%** 도 보고했다.
> 파싱 실패(NaT)는 0건이라 포맷 문제는 아니고, 원본↔산출물의 미세한 계산 차이로 보인다.
> 이번 과제 범위 밖이라 손대지 않고 `OPS_BACKLOG.md` 에 남겼다.

## 12. 자체 테스트 정착 — `python -m pipeline.selftest_all`

§9~11 을 진행하며 만든 검증 스크립트가 열 개를 넘었는데, 전부 임시 폴더에 있어
세션이 끝나면 사라졌다. **다음 사람이 손대기 전후로 돌려볼 것이 없다**는 뜻이라
영구 테스트로 옮겼다. v22 부터 남아 있던 '신규 모듈 selftest 부재' 항목도 함께 닫는다.

### 새로 만든 것

| 파일 | 지키는 계약 |
|---|---|
| `selftest_agent.py` | 챗봇 액션 — **화이트리스트 밖·범위 밖은 조용히 버린다.** 발송·판정·워처제어 액션이 레지스트리에 없는지, 위젯 key 를 직접 건드리지 않는지(`_pending_*` 우회) |
| `selftest_shift.py` | SLA 경계값(29분 vs 30분) · 시각 파싱 · 교대 인수인계 저장/조회 |
| `selftest_dispatch.py` | **시도했으면 반드시 기록된다**(성공·실패·예외·수신처 미설정) · 세션이 비어도 DB 에서 읽힌다 · 감사 기록 실패가 발송을 막지 않는다 · 2단계 삭제와 삭제 흔적 |
| `selftest_detect_io.py` | 원장 이원화(두 테이블) · 행 번호가 거래ID 로 둔갑하지 않음 · 계좌 이력 기본값 · 재탐지는 append / detections 는 upsert |
| `selftest_preprocessor.py` | **`predict_batch` == `predict`** (키 구성이 달라도) · `Location_region` 17개 매핑 고정 |
| `selftest_ui.py` | 화면 회귀(AppTest) — 딥링크 · 검색 · 편집 미리보기 · 2단계 삭제 · 온보딩 버튼 · 자동채움→탐지 |
| `selftest_all.py` | 러너. `--fast` 로 느린 것 제외, 이름으로 골라 실행 |

### 결과

```
python -m pipeline.selftest_all
  ✅ agent 0.1s · shift 0.2s · dispatch 0.7s · detect_io 0.6s · alert 0.3s
  ✅ ops 0.2s · analysis 0.7s · recheck 0.6s · migrate 0.6s
  ✅ preprocessor 5.1s · ui 58.5s
  11/11 통과 · 총 67.5초
```

`--fast` 로 돌리면 UI·원본대조를 빼고 **4초** 안에 끝난다 — 코드를 만질 때마다
부담 없이 돌릴 수 있는 수준이다.

### 설계 규칙 (새 테스트를 추가할 때도 지킬 것)

- **운영 DB 를 절대 건드리지 않는다.** 임시 DB 나 사본만 쓴다.
  v24 에서 `selftest_alert` 가 운영 원장에 테스트 행 18건을 남긴 사고가 있었고,
  과제3 검증은 감사 로그 1건을 남겼다. 둘 다 '쓰기를 하는 테스트가 운영 경로를
  기본값으로 물고 있던' 같은 원인이다.
- **네트워크로 나가지 않는다.** 가짜 Notifier 를 주입하거나 연결 거부 주소를 쓴다.
- 모델·데이터가 없는 환경에서는 **건너뛴다**(실패로 세지 않는다) — 다른 PC 에서도
  돌아가야 의미가 있다.

### 테스트를 짜며 배운 함정 (주석으로 남겨 둠)

1. **AppTest 잔상** — `st.rerun()` 이 끼면 rerun 직전 패스의 위젯이 element 목록에
   남는다(상태는 이미 정리돼 `.value` 접근 시 KeyError). '닫혔는가' 는 버튼 목록이
   아니라 **세션 상태**로 판정해야 한다. 이것 때문에 멀쩡한 코드를 두 번 의심했다.
2. **`AppTest.run()` 은 같은 객체를 변형해 돌려준다** — 스냅샷이 아니다.
   독립 시나리오는 새 인스턴스로 시작해야 한다.
3. **모델을 glob 으로 고르면 안 된다** — 로드에 실패한 `MLClassifier` 는 조용히
   더미 모드(15% 랜덤)로 떨어져서 "1행 배치 != 단건" 같은 불가능한 결과를 만든다.
   정식 `resolve_model_path()` 를 쓰고, 비결정적이면 건너뛴다.

## 13. 이월 과제 3건 마무리

v22 이전부터 문서에 남아 있던 마지막 항목들.

### 13-1. 잠금 하트비트 — 조사 중에 잠금이 풀리던 문제

`claim()` 은 **위젯을 만질 때(on_change)만** 불렸다. 한 건을 진지하게 들여다보면
15분(`CLAIM_TTL_MIN`)은 금방 지나가고, 그 사이 아무것도 건드리지 않았다면 잠금이
만료돼 다른 담당자가 같은 알림을 집는다 — **서로 다른 결론이 두 줄** 쌓인다.

→ `review_store.renew_claims(db, reviewer)` 신설. 트리아지 탭이 열려 있는 동안
`st.fragment(run_every=TTL/3)` 로 내 잠금 전부를 한 번의 UPDATE 로 민다.

**왜 '화면이 열려 있는 동안'이 옳은 기준인가** — TTL 이 존재하는 이유는
"브라우저를 그냥 닫으면 release 가 오지 않기 때문"이다. 구분해야 할 것은
**세션이 살아 있는가**지 위젯을 만졌는가가 아니다. 브라우저를 닫으면 리런이
멈춰 TTL 이 제 역할을 한다.

### 13-2. LLM 액션 준수율 — 의도가 아니라 **형식**을 관용한다

로컬 26B 모델은 지시를 따르려 하지만 표기가 흔들린다. 실제 관측되는 변형:
`[ACTION: …]`(괄호 한 겹) · 소문자 · 콜론 뒤 공백 없음 · 코드펜스로 감쌈 ·
`**굵게**` · 전각 콜론. 전부 **무엇을 하려는지는 명확한데 형식만 어긋난** 경우다.
이런 것까지 버리면 담당자 눈에는 "챗봇이 말만 하고 안 움직인다"로 보인다.

→ 마커 정규식을 관용적으로 넓히고, 프롬프트에 **맞는 예/틀린 예**를 넣었다
(규칙 나열보다 형식 예시가 준수율에 효과적이다).

> ⚠️ 관용은 **형식에만** 적용한다. 자연어에서 의도를 추론하지 않는다 —
> "오탐으로 찍어줘"와 "오탐이면 어떻게 돼?"를 구분할 수 없기 때문이고,
> 그래서 발송·판정·워처 제어는 애초에 레지스트리에 없다.
> 늘린 것은 **알아듣는 표기의 폭**이지 할 수 있는 일이 아니다.
> selftest 가 "자연어만으로는 실행하지 않는다"를 함께 못박는다.

### 13-3. 클라우드 배포 시 워처 상태 — `pipeline/status_push.py` (신규)

Streamlit Cloud 는 오빠 PC 가 아니라 Streamlit 서버에서 돌기 때문에, 워처 상태가
로컬 `fds_results.db` 안에만 있으면 **영원히 '실행한 적 없음'** 으로 보인다.
대시보드 쪽에서는 풀 수 없는 문제라 워처가 밖으로 밀어야 한다.

| 대상 | 설정 |
|---|---|
| 파일 | `FDS_STATUS_FILE` — 공유 폴더·OneDrive·S3 마운트에 JSON 을 떨어뜨린다 |
| HTTP | `FDS_STATUS_URL` (+`FDS_STATUS_HEADERS`) — Supabase REST·사내 API 등으로 POST |
| 간격 | `FDS_STATUS_MIN_SEC` (기본 30초) — 5초 폴링마다 네트워크를 두드리지 않는다 |

- **미설정이면 아무 일도 하지 않는다.** 기존 동작과 100% 같다.
- **어떤 실패도 워처를 멈추지 않는다** — 상태 보고가 탐지를 죽이면 주객전도다.
- 파일은 임시파일 → 원자적 교체(읽는 쪽이 반쪽 JSON 을 보지 않게).
- 키 이름을 `read_status()` 와 맞춰서, 되읽은 스냅샷을 `liveness()` 에 **그대로**
  넘길 수 있다 — 클라우드에서도 같은 화면이 나온다.
- ops_dashboard 는 로컬 DB 에 워처 흔적이 없으면 이 스냅샷을 폴백으로 읽고,
  "다른 서버에서 돌고 있습니다"라고 화면에 밝힌다.

### ⏰ 덤 — 미래 하트비트를 '정상'이라 말하던 문제

검증 중 `age_sec` 가 음수인 경우 `liveness()` 가 **"정상 동작 중 (마지막 폴링
-13482초 전)"** 이라고 답하는 것을 발견했다. 시계가 어긋났거나 UTC 컬럼에
로컬시각이 들어간 경우인데, 이 프로젝트가 반복해 겪은 사고 유형이라 그냥
넘길 수 없다. → 🟡 로 경고하고 시간대 점검을 안내한다.

### v24 과제13 검증

```
상태 내보내기  미설정이면 잠잠 ✅ · 파일 원자적 교체 ✅ · 임시파일 잔존 0 ✅
               되읽어 liveness() 에 그대로 → 🟢/🔴/🟡 정확 ✅
               최소 간격 준수 ✅ · 경로 오류·네트워크 실패에도 예외 0 ✅
잠금 하트비트  TTL 초과로 사라진 잠금이 renew 후 되살아남 ✅
               내 것 2건만 갱신 · 남의 잠금은 그대로 ✅
액션 준수율    변형 표기 7종 인식 ✅ · 화이트리스트 밖은 여전히 차단 ✅
               자연어만으로는 실행 안 함 ✅
회귀           selftest 12/12 (64초) · 두 앱 예외 0·에러 0
```

## 14. 낮은 우선순위 4건 — 확인하고 닫는다

'낮음'으로 미뤄둔 항목들. 셋은 **고쳐야 할 게 아니었고**, 하나는 진짜 결함이었다.

### 14-1. `Time_difference_seconds` 99.866% → **100%** (진짜 결함이었다)

58피처 중 유일하게 99.9% 미만이던 항목. 파고드니 원본 `Time_difference` 에
**음수 시간차**가 섞여 있었다(타임스탬프 순서가 뒤집힌 행).

```
원본                         우리 계산        팀 산출물(X_tr)
-11381 days +21:39:31    -983,240,429.00            NaN
-17 days +14:43:23         -1,415,797.00            NaN
```

팀은 그 자리를 NaN 으로 뒀는데 우리는 **거대한 음수**를 넣고 있었다. LightGBM 은
NaN 을 native 로 처리하지만 극단적 이상치는 전혀 다른 신호라, 그 126행(0.134%)의
예측이 학습 때와 어긋난다. → `_derive` 에서 음수 경과시간을 NaN 으로 마스킹.

```
python -m pipeline.preprocessor data/train.csv data/X_tr.parquet
  → ✅ 58개 피처 전부 99.9% 이상 일치 — 변환 규칙 확정   (경고 사라짐)
```

selftest 가 `Time_difference_seconds == 100.0` 과 '58피처 전부 99.9% 이상'을
불변식으로 고정한다.

### 14-2. `FeatureBridge` 제거 — **하면 안 된다**

"배포 번들에는 Preprocessor 가 정확하니 브리지는 제거 가능(510줄)" 이라는 메모가
오래 있었지만, 도달 경로를 확인하니 조건이 성립하지 않았다.

- `dashboard.py:3427` — 세션2 모델 비교에서 **원본(비인코딩) 데이터셋**을 고르면
  호출된다. pkl 이 없으면 train.csv × X_tr.parquet 로 **자동 학습까지** 한다.
- `detect_io.py:275` — ops 는 `feature_bridge.pkl` + 🧩컴포지트 모델이 **둘 다**
  있어야 진입. 현재 둘 다 없어 미도달.

즉 **ops 에서는 안 쓰이지만 dashboard 세션2 에서는 쓰인다.** 두 앱이 같은 모듈을
공유하므로 지우면 세션2 가 깨진다. → 모듈 머리에 이 사실을 적어 두었다.

### 14-3. `MODEL_REGISTRY` 정리 — **실익이 없다**

"안 쓰는 항목을 지워 세션2 UI 를 단순하게"가 목표였는데, 확인해 보니

- 파일이 없는 항목은 `get_available_models()` 가 **이미 자동으로 숨긴다** → 런타임 비용 0
- `"type"` 필드는 **어디서도 쓰이지 않는다**(로더가 스스로 판별)
- 지우면 나중에 그 파일이 생겼을 때 `🔍 Xgb Fds` 같은 자동 발견 이름으로만 뜬다

→ 이름표로서만 값이 있으므로 그대로 둔다. **"다시 열지 말 것"** 을 주석으로 못박았다
(두 사본 모두).

### 14-4. `moonshot` 키 배선 — 수정

dashboard 의 제공자 목록에 `moonshot` 이 있고 `_build_llm_analyzer` 도
`ov_moonshot_key` 를 읽는데 **입력란만 없어서** 항상 `.env` 폴백이었다.
사이드바에 입력란을 추가했다 — 화면에서 고를 수 있는 제공자는 화면에서 키도
넣을 수 있어야 한다. (ops 쪽은 이미 배선돼 있었다.)

### v24 과제14 검증

```
Time_difference  58피처 전부 100% · selftest 불변식 추가 ✅
FeatureBridge    도달 경로 확인 → 유지 · 근거를 모듈 주석에 기록 ✅
MODEL_REGISTRY   동작 변경 없음 · 결론을 두 사본에 주석 ✅
moonshot         dashboard 사이드바 입력란 렌더 확인 ✅
회귀             selftest 12/12 (68초) · 두 앱 예외 0
```

## 개발 도구 사고 — `selftest_alert` 가 운영 DB 에 썼다

회귀 테스트를 돌리다 발견했다. `pipeline/selftest_alert.py` 는 `DB="fds_results.db"`
— **운영 DB에 직접** 합성 알림(`TXN_NEW_*`/`TXN_DUP`/`TXN_BURST_*`)을 INSERT 한다.
실행 한 번으로 원장에 테스트 행 18건이 영구히 남는다.

- 백업(`fds_results.db.bak-*`) 후 해당 18행만 삭제, 228행/max id 228 로 원복 확인.
- 이 테스트가 **자기 임시 DB를 만들어 쓰도록** 고쳤다. 과거 알림 30건을 시드로
  깔아 `[1] 첫 폴링은 침묵` 검증의 기준선도 유지한다.

## selftest 5종이 Windows 에서 처음으로 돌았다

`selftest_ops` / `analysis` / `recheck` / `migrate` 가 `/tmp/` 를 하드코딩하고 있어
**이 환경에서 한 번도 실행된 적이 없었다.** (`selftest_ops` 는 이번에 고친
`ops_queries` 를 검증하는 테스트다.)

| 문제 | 조치 |
|---|---|
| `/tmp/` 하드코딩 (4개 파일) | `tempfile.gettempdir()` |
| `selftest_migrate` CP949 디코딩 크래시 | 자식 프로세스 출력 `encoding="utf-8"` 명시 |
| 커넥션 누수 → `PermissionError` | Windows 는 열린 파일을 못 지운다. `q1()` 헬퍼로 즉시 close |
| `TZ=Asia/Seoul` 강제 | POSIX 전용. Windows CRT 가 IANA 이름을 못 읽어 +1시간으로 떨어졌다 → `tzset` 있을 때만 고정, 기대 오프셋은 sqlite 에 직접 질의 |

## v24 검증

```
[과제1] 전용 16항목 (DB 복사본)
  트리아지 큐 · 탐지 로그 · 실시간 피드 · 커버리지 분모에 모두 등장
  시각 오차 0초 · 정답 라벨/출처 보존
  transactions=append(2줄) / detections=upsert(1줄·최신값)
  폴링 집음 ✅ / 에코 0건 ✅ / 시간대 불일치 해소 ✅
[과제2] 라벨 4개 언어 치환 · 미치환 토큰 0
  예보 ↔ 폴링 3가지 임계값 조합 전부 건수 일치  ★ 핵심 불변식
  등급 분포 실제{확정5,검토3,없음4} vs 옛표시{확정6,검토1,없음5} — 달랐음이 입증
[과제3] send_manual 성공/실패(False)/예외 3종 모두 기록 · 거래ID·사유 보존
  auto_send 수신처 미설정 · 본문 생성 예외도 기록
  정적(AST) 검사: 직접 발송 호출 0 · _send() 6곳 · 화면의 audit_append 0
  AppTest 실클릭(단건 분석 Slack, 예전 누락 경로) → 감사 0→1건 · via=manual
selftest 5종 (ops·alert·analysis·recheck·migrate)  전부 통과
AppTest 회귀  예외 0 · 에러 0 / 표시100(크래시 재현 경로) 예외 0
운영 DB       transactions 228 · detections 74 (작업 전과 동일)
```

> 검증 중 과제2 테스트가 3건 실패했는데 원인은 코드가 아니라 데이터였다 —
> 최근 30일 7건의 점수가 전부 `1.0`/`0.0` 극단이라 어떤 임계값을 써도 결과가
> 같았다. 경계 사이 점수(0.85 등)를 주입해 민감도를 제대로 확인했다.

## 버전

`ops_dashboard v19→v24` · `ops_queries v19→v21` · `audit_store v1`(신규) · `ops_alert v23→v24` ·
`ops_sidebar v19→v20` · `ops_dispatch v1→v3` · `preprocessor`(predict_batch 수정)

## v24 남은 과제

| 항목 | 내용 |
|---|---|
| (v22 에서 이월) | 잠금 하트비트 · dashboard.py 온보딩 미검증 · LLM 액션 준수율 |

---

# v25 — 화면 동선 재설계 (사이드바 3층 · 헤더 배지 · 임계값 대조표)

기능을 더한 버전이 아니라, **있는 기능을 찾기 쉽게** 만든 버전이다.
공통 진단은 하나다 — 화면이 *만드는 순서*대로 배치돼 있고, *쓰는 순서*를 따르지 않았다.

## 1. 사이드바 — '만지는 빈도' 순으로 3층

v20 까지는 `dashboard.py` 에서 이식한 순서(임계값→모델→데이터셋→AI→음성→관제→표시)를
그대로 썼다. 그 결과 **근무를 시작할 때마다 고치는 검토자 이름이 8번째**라 스크롤해야
닿았다. 온보딩(`ops_guide`) 퀵스타트 1번이 "검토자 이름을 바꾸세요"인데도 그랬다.

| 층 | 내용 | 빈도 |
|---|---|---|
| ① 상태 | 👤 판정자 · 🛰 워처 배지 | 설정이 아니라 '지금 어떤가' — 항상 보인다 |
| ② 매일 | 🛡 관제 설정 · 🎯 임계값 · 🧠 모델 · 📂 데이터셋 | 근무마다 / 작업할 때 |
| ③ 1회 | ⚙ 고급 설정 (LLM·알림 채널·음성·표시·버전) | 대개 최초 1회 |

`🎓 사용 안내`는 4번째 자리에서 맨 아래로 내렸다(평생 한두 번 누른다).

### ⚠️ 고급 설정을 `st.toggle` + `if` 로 감싸면 안 된다

접힌 동안 위젯이 인스턴스화되지 않으면 **Streamlit 이 그 key 를 세션에서 청소한다** —
API 키·Slack Webhook 이 접을 때마다 사라진다. `st.expander` 는 접혀 있어도 내용을 항상
만들기 때문에(접기는 CSS다) 값이 유지된다. 그 대가로 expander 중첩이 금지되므로,
안에 있던 `🤖 AI 설정`/`📨 알림 채널` 두 expander 는 소제목으로 폈다.

### 곁가지로 고쳐진 것 2개

| 문제 | 원인 | 결과 |
|---|---|---|
| 모델 폴더를 바꿔도 목록이 한 박자 늦게 갱신 | `model_dir` 입력(관제 설정)이 모델 섹션 **아래**에 있었다 | 관제 설정이 위로 가면서 같은 런에 반영 |
| 워처 배지가 **다른 DB** 의 하트비트를 보여줌 | `render_watcher_badge()` 를 인자 없이 호출 → `watcher_panel.DEFAULT_DB` | `db_path`/`poll_interval` 을 넘긴다 |

## 2. 헤더 상시 배지 — 밀린 일을 숨기지 않는다

첫 화면이 `🧠 AI 분석`이라(v21 결정, 유지), 미판정이 쌓여 있어도 **트리아지 탭을
손으로 누르기 전에는 알 수 없었다.** 헤더는 모든 탭 위에 있으므로 여기에 붙인다.

`미판정 N` · `SLA M분 초과 K` · `최장 대기` · `판정자`

- `ops_ui.hero(t, badges=[...])` — 값은 `_esc()` 로 이스케이프(검토자 이름이 사람 입력이다)
- `@st.cache_data(ttl=15)` + **DB mtime** 을 캐시 키에 넣어, 새 탐지가 들어오면 즉시 갱신
- 집계 상한 500건(`_HDR_CAP`) — 넘으면 `500+`
- 배지 계산이 실패해도 헤더는 뜬다(예외를 삼키고 배지만 생략)

> ⚠️ 캐시 인자를 `_mtime` 처럼 밑줄로 시작하게 쓰면 안 된다. `st.cache_data` 는
> 밑줄 인자를 **해시에서 제외**하므로 무효화가 통째로 죽는다. `db_mtime` 으로 둔다.

## 3. 임계값 대조표 — "왜 3개인가"를 화면이 답한다

이 콘솔에는 이름이 같고(`th_review`/`th_confirm`) 뜻이 다른 임계값이 셋 있다.
v24 까지는 각자 자기 화면에만 있어서, 사이드바가 `0.50` 을 보여주는 동안 워처는
`0.005/0.9` 로 돌아도 아무도 몰랐다(v24 §2 에서 캡션 한 줄로 임시 대응했던 그 문제).

| 무엇을 정하나 | 단일 출처 | 어디서 바꾸나 |
|---|---|---|
| 🛰 워처 경보 등급 | `watcher_config.json` | ⚙ 임계값 튜닝 탭 |
| 🎯 탐지 판정 임계값 | `th_slider` | 사이드바 🎯 임계값 |
| 📮 발송 등급 | `th_review`/`th_confirm` | 사이드바 📮 이중 임계값 |

`ops_ui.threshold_matrix()` 한 벌로 두 곳에 그린다 — 사이드바(compact, 세로)와
⚙ 임계값 튜닝 탭(전체판, 설명문 포함). 튜닝 탭은 셋 중 ①만 바꾸는데 이름이 같아
"여기서 적용했는데 왜 안 바뀌지"가 반복됐다.

## 4. AI 탭 — 작업이 먼저, 도구가 나중

`🖊 프롬프트 편집기` · `📚 RAG 편집기`(설정에 가까운 도구)가 화면 맨 위를 차지하고
정작 할 일(`🎯 탐지 입력 · 🔍 단건 · 📦 배치 · 🤖 챗`)이 그 아래에 있었다.

`st.tabs()` 는 **호출한 자리에 컨테이너를 박고**, 나중에 `with AI_SUB[i]:` 로 채워도
내용이 그 자리에 들어간다. 그래서 **생성 한 줄만 위로 올려** 편집기 코드는 한 줄도
옮기지 않고 화면 순서를 뒤집었다.

## 5. 챗봇 `set_sla` 가 조용히 실패하던 버그

```python
elif name == "set_sla":
    ss["sla_min"] = int(arg)      # ← sla_min 은 사이드바 위젯 key
```

사이드바는 챗 처리보다 **먼저** 그려진다 → 이미 만들어진 위젯의 key 수정 →
Streamlit 예외 → `apply()` 의 `try/except` 가 삼킴 → **"바꿨습니다" 메모조차 안 나온 채
아무 일도 안 일어남.** 바로 위 `set_threshold` 와 같은 예약값 패턴(`_pending_sla`)으로
통일했다. 사이드바가 위젯 생성 직전에 소비한다.

`selftest_agent` §6 도 함께 고쳤다 — 예전 테스트는 `ss["sla_min"] == 45` 를 확인해
**깨진 동작을 정답으로 못박고 있었다.** 이제 3개 액션 전부에 대해
"예약값을 쓰는가 + 사이드바 위젯 key 를 직접 건드리지 않는가 + 메모가 나오는가"를 본다.

## v25 검증

```
selftest_all           12/12 통과 (70.9초)
사이드바 재배치        reviewer 첫 번째 · reviewer<model_dir<ds_folder
                       pii_level<model_sel_global<ai_llm_provider
고급 설정 상태 보존    접힌 채로 ai_slack_webhook/smtp/tts/theme 6종 전부 렌더
                       Webhook 입력 후 재실행 → 값 유지
헤더 배지              미판정 108건 = 실제 큐 108건 · 판정자 이름 반영
                       SLA 라벨이 sla_min 변경(30→90)을 따라감
임계값 대조표          사이드바 compact · 튜닝 탭 전체판 3행 모두 렌더
set_sla                메모 반환 O · _pending_sla 예약 → 다음 런에 sla_min=90 · 예약값 소비
AI 탭                  서브탭 4종 렌더 · 프롬프트 편집창 4종 그대로 동작
```

## 버전

`ops_dashboard v24→v25` · `ops_ui v19→v20` · `ops_sidebar v20→v21` ·
`ops_agent`(set_sla 예약값) · `selftest_agent`(§6 확장)

## v25 남은 과제

| 항목 | 내용 |
|---|---|
| AI 탭 분리 | 1,100줄(전체의 40%)로 사실상 별개 앱이다. 탭 중첩도 3단(탭→서브탭→입력탭)이 남아 있다 |
| (v22 에서 이월) | dashboard.py 온보딩 미검증 · LLM 액션 준수율 |

---

# v26 — 조립 계층 공용화 (`detect_workbench.py` 신설)

v25 가 **배치**를 고쳤다면 v26 은 **구조**를 고친다. 백로그 A(AI 탭 분리)의 1단계다.

## 1. 진단 — "AI 탭이 크다"는 증상이었다

| 대상 | 줄수 |
|---|---|
| ops_dashboard.py AI 탭 | 1,105 (전체의 36%) |
| └ 그중 '🎯 탐지 입력' | **624** (AI 탭의 57%) |
| dashboard.py 세션5 | ~1,400 — **같은 일을 하는 두 번째 구현** |

헬퍼 결합도를 재 보니 **AI 탭 전용 헬퍼는 0개**였다. `_send`(안6/밖1) ·
`_build_llm_analyzer`(안4/밖5) · `_build_rag`(안4/밖3) · `_build_masker`(안4/밖2) ·
`_redo_step`(안3/밖1) · `_get_rag_cached`(안5/밖2) · `_sync_widget`(안5/밖2) —
7개 전부 탭 안팎에서 함께 쓰인다. **탭만 파일로 뜯어내면 인자 7개짜리 함수**가 되고,
파일 크기만 줄 뿐 결합은 그대로다. 그래서 그 안은 버렸다.

진짜 문제는 이중화였고, 이미 피해가 나 있었다 — 프롬프트 편집기의 `value=` 버그가
v24 에 ops 만 고쳐지고 dashboard.py 에는 **v25 까지 남아 있었다.** 같은 코드가
두 파일에 있으니 한쪽만 고쳐진 것이다. 부품(`detect_ui` 렌더 · `detect_io` I/O)은
이미 공유하고 있었는데, **그 부품을 조립하는 계층**만 두 벌이었다.

## 2. `pipeline/detect_workbench.py` (신규 516줄)

`render_input_modes()` — '거래 1건 고르기' 6종 + 액션 바.

```python
row = dwb.render_input_modes(
    t=t, lang=LANG, key_prefix="det",              # ← 두 앱이 세션을 공유해도 안 겹친다
    model_name=…, model_path=…, threshold=…,
    dataset_name=SEL_DS, dataset_found=DS_FOUND,
    fraud_label=ui.fraud_label, on_batch=_handoff_batch,   # ← 헬퍼는 콜백
    tab_key="ops_det_tab", force_tab_key="_force_det_tab")
```

**이 함수는 탐지하지 않는다.** ML 분류·DB 적재·경보·LLM 분석·발송은 호출부에 남겼다.
두 앱의 그 뒤 처리가 완전히 다르기 때문이다 — ops 는 `ops:` 소스 태그로 원장에
적재하고 ops_alert 로 경보를 쏘지만, dashboard.py 는 자체 발송 경로(리치 비주얼·
HTML 메일·첨부)를 쓴다. 억지로 합치면 콜백이 열 개 넘게 붙어서 '공용 모듈'이 아니라
**인자로 위장한 전역**이 된다.

설계상 지킨 것 3가지 (어기면 "ops 전용 모듈"이 되어 공용화가 불가능해진다):

| 원칙 | 이유 |
|---|---|
| 앱 전역 상태를 읽지 않는다 | 필요한 값은 전부 인자로 |
| 위젯 key 에 `key_prefix` | dashboard.py 는 `"s5"` 로 갈아끼우면 된다 |
| 헬퍼는 콜백으로 받는다 | import 방향을 뒤집지 않는다 |

i18n 키 접두어가 다르므로(`det.*`/`ai.*` vs `s5.*`) `_tf()` 가 키 부재 시 한국어
폴백을 쓴다 — 한쪽 앱 i18n 에 종속되면 나머지가 이 모듈을 못 쓴다.

## 3. dashboard.py 프롬프트 편집기 버그 (v24 부터 남아 있던 것)

```python
_edited = st.text_area(_label, value=_cur, key=f"prompt_ta_{_slot}")   # ← before
```

`value=` 는 key 가 이미 세션에 있으면 **무시된다.** 그래서 `기본값 복원`을 눌러도
오버라이드만 지워지고 편집창은 그대로였다. `detect_workbench.sync_widget` 을
두 앱이 함께 쓰도록 배선했다.

## 4. 결과

| | before | after |
|---|---|---|
| ops_dashboard.py | 3,061 | **2,730** (−331) |
| 그중 '탐지 입력' | 624 | **33** (호출부) |
| 공용 모듈 | — | detect_workbench 516 |
| dashboard.py 채택 | — | 아직 (세션5 손댈 때 `key_prefix="s5"`) |

## v26 검증

```
selftest_all              12/12 통과 (78.2초)
★ 탐지 결과 비트 동일     자동채움 → 탐지 = d / 0.8780781629912902  (이관 전과 같은 값)
위젯 key 27종             det_amount … det_run_ds 전부 이관 전과 동일 · 플래그 12종
입력 탭 6종               라벨 그대로 (📂선택 데이터셋 · ✏️직접입력 · 📄test · 📊train · 🧪합성 · 📁폴더)
챗봇 액션                 goto_input_tab(synthetic) → 탭 이동 · set_scope(m) → 범위 반영
dashboard.py 스모크       앱 기동 · 세션5 이동 · 프롬프트 4슬롯 (신규 커버리지)
★ 복원 회귀               버그를 되살리면 테스트가 실제로 실패함을 확인 (MY EDITED PROMPT 잔존)
```

> 회귀 테스트는 `selftest_ui` §11·§12 로 영구 편입했다. 임시 스크립트로 두면
> 다음 사람이 같은 것을 다시 깨뜨린다.

## 버전

`ops_dashboard v25→v26` · `detect_workbench v1`(신규) · `selftest_ui`(§11~§13 신설)
`dashboard.py` — 프롬프트 편집기 · RAG 편집기 · 자동입력 · 계좌 이력 · 챗 필드표 (5건 수정)

## 6. A1 — 직접입력 '계약' 통일 (같은 입력 → 같은 판정)

세션5 를 `key_prefix="s5"` 로 통째 교체하려다 **실측하고 방향을 바꿨다.**
dashboard.py 세션5 는 `st.tabs` 가 아니라 `_seg_nav`(segmented_control) 를 쓰고,
컴팩트 뷰(CV)·`t3_src`(원본 CSV/전처리 Parquet 선택)·`FLAG_LABELS`/`FLAG_HELP`
같은 **자기 것**을 갖고 있다. 통째로 갈아끼우면 그 UI 를 전부 잃는다.

그래서 **화면이 아니라 계약을 합쳤다.** 라벨·컬럼·컴팩트 모드는 앱마다 달라도
되지만, 아래 셋이 갈리면 **같은 값을 넣어도 다른 판정이 나온다**:

| 계약 | 단일 출처 |
|---|---|
| 자동채움 값 세트 | `AUTOFILL_PRESET` + `AUTOFILL_FLAGS` |
| row 조립(계좌 이력 포함) | `build_manual_row()` |
| 🏦 계좌 이력 패널 | `render_account_history()` |

### 그 과정에서 나온 dashboard.py 버그 2건 (둘 다 ops 는 v24 에 고쳤던 것)

**① 자동입력 버튼이 눌리는 순간 죽었다**

```
StreamlitAPIException: `st.session_state.amount_in` cannot be modified
                       after the widget with key `amount_in` is instantiated.
탐지 실행 버튼: 0          ← 예외로 렌더가 끊겨 버튼이 화면에서 사라진다
```

버튼이 폼 **아래**에 있어서 버튼 안에서 세션을 고칠 수 없다. 예약값 패턴으로 전환.

**② row 에 계좌 이력이 아예 없었다**

```python
row_to_predict={... 'Customer_Gender':'male', **flag_vals, '_input_mode':'manual'}
#                                              ↑ 계좌 이력 5개 없음
```

번들 기본값 0 이 쓰여 '한 달간 거래가 전혀 없던 계좌'가 되고, **고위험 프리셋조차
정상(m)으로 판정**됐다. 즉 dashboard.py 의 시연용 '고위험 시나리오 자동입력'은
지금까지 눌러도 아무 일도 안 일어났고, 억지로 눌렸어도 사기가 안 나왔다.

### 곁가지 2건

- **챗 액션 필드표 이중화** — `_apply_chat_actions` 의 `_FIELD_WK` 와 세션5 렌더가
  각자 같은 표를 들고 있었다. 갈리면 "챗봇으로 금액을 바꿨는데 폼은 그대로"가 된다.
  → `_S5_FIELD_WK` 한 벌 참조.
- **RAG 편집기 `value=` 버그** (§A2 준비 중 발견) — 파일이 디스크에서 바뀌어도
  편집창은 옛 내용을 보여주는데 `[저장]` 을 누르면 **그 옛 내용으로 덮어써
  남의 수정을 되돌린다.**

### A1 검증

```
★ 두 앱이 같은 판정        ops = dashboard = d / 0.8773517059743291
dashboard 자동입력         클릭 시 예외 0 · [탐지 실행] 버튼 생존 · 금액/플래그 주입 확인
dashboard 계좌 이력        s5_hist_* 5종 렌더 · row 에 14,140,000 반영
계약 단일 출처             build_manual_row 가 history 생략 시에도 계좌 이력 주입
자동채움 값 세트           두 앱 값 동일(위젯 key 만 다름) · 위험 플래그 5종
selftest_all               12/12 통과 (83.2초)
```

> ⚠️ 프리셋을 두 앱의 **합집합**(위험 플래그 5종)으로 통일하면서 ops 점수가
> `0.8780781629912902` → `0.8773517059743291` 로 미세 변동했다. 사기 유형은 `d` 로 동일.

## v26 남은 과제

| 항목 | 내용 |
|---|---|
| **A2 (범위 변경됨)** | 조사 결과 '단건/배치/챗 본문'은 **공용화 대상이 아니다** — 발송 경로가 설계상 다르다(ops=편집 가능한 평문+감사로그 / dashboard=리치 HTML+마스킹 첨부). 진짜 대상은 **프롬프트·RAG 편집기 + `prompt_overrides` dict** (두 벌 × ~130줄). 자세한 근거는 `OPS_BACKLOG.md` §A2 준비 |
| 세션5 나머지 입력 모드 | test/train/synthetic/folder 는 아직 두 벌. 알려진 버그는 없고 `t3_src` 같은 dashboard 고유 기능이 있어 서두를 이유 없음 |

---

# v27 — A2: 편집기 계층 공용화 (`value=` 함정의 재발을 구조로 막는다)

v26 A1 조사에서 **같은 병이 세 번** 나온 것이 이 버전의 이유다.

| # | 위치 | 발견 | 증상 (셋 다 **예외가 안 난다**) |
|---|---|---|---|
| ① | ops 이메일 미리보기 | v24 | 보이는 본문 ≠ 실제 발송 본문 |
| ② | dashboard 프롬프트 편집기 | v26 | '기본값 복원'이 화면에 반영 안 됨 |
| ③ | dashboard RAG 편집기 | v26 | `[저장]`이 **남의 수정을 되돌림** |

Streamlit 은 key 가 세션에 있으면 `value=` 를 무시한다. 같은 편집기 코드가
두 벌인 한, 한쪽만 고쳐지는 이 사고는 계속 재발한다. 줄 수가 아니라 이게 이유다.

## 1. 범위를 바꿨다 — '단건/배치/챗'은 대상이 아니다

v26 백로그의 A2 는 '단건/배치/챗 서브탭 공용화'였는데, 발송 경로를 실측하고 **뺐다.**

| | ops_dashboard | dashboard.py |
|---|---|---|
| 이메일 본문 | 평문 + **편집 가능한 미리보기** | 리치 HTML + 등급 머리말 |
| 첨부 | 없음 | **강제 마스킹 HTML 리포트** |
| 발송 기록 | `ops_dispatch` 감사 로그 | 없음 |

두 앱은 이메일을 **다른 물건으로 보고 있다.** 합치려면 "이메일이 무엇인가"를
하나로 정해야 하는데 그건 리팩터링이 아니라 제품 결정이다 → 범위에서 제외.

## 2. 진짜 대상 — 편집기 계층 (거의 동일했다)

`pipeline/detect_workbench.py` 에 3종 신설:

| 함수 | 대체한 것 |
|---|---|
| `render_prompt_editor(t, key_ns, height, vars_label)` | 프롬프트 편집기 두 벌 |
| `render_rag_editor(t, key_ns, on_change, alert, height)` | RAG 편집기 두 벌 |
| `prompt_overrides()` | 두 앱 `_build_llm_analyzer` 의 4키 dict 두 벌 |

- **i18n** — 접미어가 같고 접두어만 다르다(`ai.*` vs `s5.*`) → `key_ns` 로 받고,
  키가 없으면 `_tf()` 가 접미어로 한 번 더 찾아 한국어 폴백을 쓴다.
- **오류 표시** — ops 는 `st.error`, dashboard 는 `alert_box` → `alert=` 콜백.
- **RAG 캐시 무효화** — 앱마다 자기 `_get_rag_cached` → `on_change=` 콜백.
  안 부르면 문서를 고쳐도 옛 색인이 계속 쓰인다.

### ops 가 덤으로 얻은 것

dashboard 쪽 구현이 더 완전해서, 합치면서 ops 가 **새 문서 이름 검증 3종**을
얻었다 — 빈 이름 · 경로 탈출(`/`, `\`, 앞점) · 중복. 예전 ops 는 조용히 무시했다.

## 3. 결과

| | v26 | v27 |
|---|---|---|
| ops_dashboard.py | 2,730 | **2,613** (−117) |
| dashboard.py | 5,866 | **5,733** (−133) |
| detect_workbench.py | 516 | 830 (+314) |
| **합계** | 9,112 | **9,176** |

> 합계는 +64 줄이다. **줄 수를 줄이는 게 목적이 아니었다** — 같은 화면의 구현이
> 두 벌에서 한 벌이 된 것이 결과다. 공용 모듈은 두 앱의 기능 합집합(파일명 검증
> 3종 등)을 갖고, 주석으로 함정의 이유까지 들고 있어서 원본보다 길다.

## v27 검증

```
selftest_all                 12/12 통과 (80.1초)
구현 단일화(정적)            두 앱 모두 _PROMPT_SLOTS / rag_reidx_ 본문 0
                             prompt_ov_ 하드코딩 0 (양쪽 count=0)
i18n 폴백                    ai.* / s5.* × 11키 전부 실제 문구로 해석 (키 노출 0)
                             포맷 인자 처리 — rag_new_dup(name=abc.md) 정상
ops 편집기                   프롬프트 4슬롯 · RAG 편집창 · rag_new_btn 렌더
                             저장 → 오버라이드 → 복원 → **편집창까지** 기본값 복귀
dashboard 편집기             동일 시나리오 통과 · 편집창 key 가 ops 와 완전히 동일
```

> `selftest_ui` §14 로 영구 편입 — **구현이 다시 갈라지는 것 자체**를 정적 검사로
> 막는다(`_PROMPT_SLOTS` 나 `rag_reidx_` 가 앱 파일에 다시 나타나면 실패).

## 버전

`ops_dashboard v26→v27` · `detect_workbench v1→v2` · `dashboard.py`(편집기 2종 이관) ·
`selftest_ui`(§14 신설)

## v27 남은 과제

| 항목 | 내용 |
|---|---|
| 세션5 나머지 입력 모드 | test/train/synthetic/folder 는 아직 두 벌. 알려진 버그는 없고, dashboard 고유 기능(`t3_src` 원본CSV/Parquet 선택 · 컴팩트 뷰 · `_seg_nav`)이 있어 서두를 이유 없음 |
| 발송 경로 | **의도적으로 두 벌로 둔다.** 합치려면 "이메일을 어떤 물건으로 볼 것인가"부터 정해야 한다 |

---

# v28~v37 — 실무자 사용성 점검 반영 (9건 + i18n 전면 + 미탐 곡선 · 압축 탭)

시작은 기능 요청이 아니라 **점검 요청**이었다 — "이 콘솔이 실무자용으로 적절한가,
복잡하거나 난잡하지 않은가, 기능은 충분한가". 점검에서 나온 9건을 순서대로 반영했고
그중 하나(i18n)가 8단계로 커졌다.

**확정 요구사항 두 가지는 끝까지 유지했다** — 첫 탭은 `🧠 AI 분석`,
워처 1차 임계값은 `0.005`. 비교용 전환은 **세션 한정**으로만 만들었다(파일에 안 쓴다).

## 1. 점검에서 나온 것 중 진짜 버그 — 슬라이더가 `0.005`를 만들 수 없었다

| | |
|---|---|
| 증상 | 임계값 슬라이더 `step=0.01` → 표현 가능한 값은 `0.00 / 0.01 / 0.02 …` |
| 그래서 | **현재 운영값 `0.005`는 격자 위에 없다.** 튜닝 탭을 열고 `[적용]`만 눌러도 `0.005 → 0.01`(2배) |
| 왜 안 잡혔나 | **예외가 안 난다.** 저장도 되고 로그도 남는다. 경보가 절반으로 줄 뿐이다 |

→ 오른쪽에 `정확한 값` 숫자 칸(`step=0.001`, `%.4f`)을 붙이고 슬라이더와 양방향
동기화했다. **적용값은 항상 숫자 칸**이다(슬라이더는 대략 위치를 잡는 용도).

이 한 건이 나머지 8건을 정당화했다 — 조용히 틀리는 것이 가장 비싸다.

## 2. 되돌릴 수 없는 동작에 확인 카드 (7곳)

| 동작 | 확인 카드가 보여주는 것 |
|---|---|
| 임계값 저장 | 현재→변경 대조표 · 알림/놓친사기 증감 · 신뢰불가 구간 경고 · `watcher_config.json`에 기록될 결정 근거 |
| 발송 6곳 (단건·AI·일괄 × Slack·이메일) | 수신처 · 마스킹 레벨 · **본문 미리보기** |

구현은 한 벌이다 — `_send_ask(slot, channel, body, **kw)`가 세션에 담고 rerun,
`_send_confirm(slot)`이 카드를 그린 뒤 `_send(...)`를 부른다.
6곳이 같은 코드를 쓴다. **v27(A2)의 교훈** — 같은 화면이 여러 벌이면 한쪽만 고쳐진다.

## 3. 미탐(FN) 등록 창구 — 집계의 미탐 칸이 늘 `0`이었다

트리아지 큐는 **알림이 나간 건**만 담는다. 미탐은 정의상 **알림이 안 나간 건**이라
화면에 올라올 경로가 아예 없었다. 집계가 0이었던 건 미탐이 없어서가 아니다.

`📉 오탐 분석`에서 거래 ID로 직접 등록한다. 원장에 있으면
"이 거래는 `0.0031 < 임계값 0.005`라 알림이 안 갔습니다"까지 보여준다.

## 4. i18n — 토글은 있는데 화면 절반이 한국어였다 (8단계)

| | 전 | 후 |
|---|---:|---:|
| 영어 화면의 한국어 라벨 | 94개 | **5개** (전부 모델 피처명 — 의도적) |
| `ops_ui` 번역 키 | — | **571키 × 4개국어 · 누락 0** |

모듈마다 방식이 다른데, 이유가 있다.

| 모듈 | 방식 | 왜 |
|---|---|---|
| `ops_ui` | `_a()` 중앙 테이블 | ops 전용이라 한곳에 모을 수 있다 |
| `ops_sidebar` · `ops_guide` · `ops_shift` | `lang` 인자 (기본 `ko`) | ops 전용이지만 시그니처는 안정적으로 |
| `watcher_panel` · `ops_dispatch` | 자체 테이블 + `lang="ko"` 기본값 | **`dashboard.py`가 같이 쓴다.** 인자를 안 넘기는 저쪽 호출은 이전과 완전히 동일 |
| `detect_workbench` | `_tf(t, key)` + 한국어 `_FALLBACK` | 두 앱의 키 접두어가 다르다(`ai.*` vs `s5.*`) — v27 구조 재사용 |

**의도적으로 번역하지 않은 것**

| 대상 | 이유 |
|---|---|
| 인수인계서 **문서 본문**(`.md` 저장물) | 조직에 남는 산출물. 화면 언어를 따라가면 "영어로 보다 저장했더니 영문 인계서" |
| 계좌 이력 **피처 이름** | 화면 장식이 아니라 **모델 피처 사전**. `model_meta.json`·임계값 리포트·설명서가 같은 이름을 쓴다 |
| Streamlit 버전 경고(부팅 실패 화면) | 번역 함수가 만들어지기 **전**에 뜨는 하드 스톱 |
| `log.*` 개발자 로그 | 사용자 화면이 아니다 |

> `dashboard.py`는 이번 작업에서 **화면이 한 글자도 바뀌지 않았다.**
> 공유 모듈은 언어 인자 기본값이 한국어이고, `detect_workbench`는 한국어로 폴백한다.

## 5. 미탐 반영 곡선 — 덮어쓰지 않고 **겹쳐 그린다** (v37)

`oq.threshold_whatif_fn()`을 **별도 함수로** 만들었다. 기존 `threshold_whatif()`는
한 줄도 바뀌지 않았다. 이 프로젝트에는 임계값 숫자가 이미 두 개 있기 때문이다.

| | 출처 | 미탐을 보는가 |
|---|---|---|
| ① `tools/threshold_report.py` | 검증셋(정답 라벨) — **현재 `0.005`가 여기서 나왔다** | 전부 |
| ② 기존 곡선 | 운영 판정(정탐/오탐) | **구조적으로 못 봄** |
| ③ 미탐 반영 곡선 (신규) | 운영 판정 + 등록 미탐 | 등록된 것만 |

숫자를 조용히 바꿔치기하면 "어제 본 추천치와 오늘이 다른데 왜인지 모르는" 상태가
된다. 임계값 도구가 절대 만들면 안 되는 상태다 → 빨간 점선으로 겹쳐 그리고,
추천 슬라이더는 계속 ②를 따른다.

### 내가 처음에 틀렸던 것

주석에 "미탐 곡선이 기존보다 **싸게** 나온다"고 썼는데 검증에서 반대로 나왔다.
당연한 결과였다 — 기존 곡선이 **아예 몰랐던 실제 손실**을 더하니 항상 비싸진다.

주석과 화면 안내를 고쳤다. 읽는 법은 두 가지다.
1. **높이가 올라간 건 정상** — 원래 있던 손실이 이제 보이는 것이다.
2. **쓸모 있는 건 최소점의 위치** — 왼쪽으로 갔다면 임계값을 내릴 근거다.

> 🚨 **비대칭** — 미탐 데이터는 내렸을 때의 *이득만* 알려준다. 내려서 새로 올라올
> 오탐이 몇 건일지는 여전히 미관측이다. **거리가 아니라 방향의 근거로만** 쓴다.

**회귀 안전장치: 미탐이 0건이면 두 곡선은 완전히 동일하다.**

## 6. 압축 탭 라벨 — 측정부터 했다 (v37)

| 언어 | 기본 | 압축 |
|---|---:|---:|
| 한국어 | **1,096px** | 728px |
| English | 1,072px | 720px |
| 日本語 | 1,048px | 760px |
| 中文 | 944px | 680px |

1366px 노트북에서 사이드바(≈336px)를 빼면 본문은 **≈1,030px**. 한·영·일은
기본 라벨로 **실제로 넘친다.** 관제실 모니터가 넓으면 켤 이유가 없어 **기본 꺼짐**,
`🩺 진단`의 토글 또는 `FDS_OPS_TAB_COMPACT=1`.

### 여기서 나온 숨은 버그

`st.tabs(key=…)`는 선택된 **라벨 문자열**을 세션에 저장한다. 언어나 압축 모드를
바꾸면 그 값은 **존재하지 않는 문자열**이 된다 → `st.tabs` 직전에 정리 가드를 넣었다.

## 7. 자리를 옮긴 것

- **🖊 프롬프트 · 📚 RAG 편집기** : AI 분석 탭 맨 위 → **사이드바**
  설정 도구가 작업대 첫 화면을 차지해, 탭을 여는 이유(탐지·분석)가 스크롤 아래로 밀려 있었다.
- **경보 켜기/끄기** : 실시간 감시 탭 → **사이드바** (세부 설정은 그대로)
  "알람 어떻게 꺼요?"의 답이 탭 안쪽 접힌 패널이면 아무도 못 찾고 결국 스피커를 끈다.

## 8. 이번에 밟은 함정 — 재발 방지용 기록

| 함정 | 증상 | 교훈 |
|---|---|---|
| **컴파일 검증에 잘못된 파이썬** | f-string 안 같은 따옴표 중첩은 3.12+ 전용. 시스템 3.12로는 통과했는데 앱(conda 3.11.15)은 `ImportError`로 죽었다 | 검증은 반드시 `envs/qaqc_st/python.exe` |
| `st.tabs` 위치 언패킹 | 탭 순서를 바꾸면 **조용히 다른 탭에** 그린다 | 키 딕셔너리 + 레이아웃 표 |
| 번역된 라벨로 비교 (`if tri_sort == "대기순"`) | 한국어에서만 정렬이 동작 | 코드값 + `format_func` |
| `rs.VERDICT_LABEL_KO` 직접 사용 3곳 | 영어 화면에 한국어 판정 | `_verdict_label()` 한 벌 |
| 위젯 key 중복 (`alarm_on` 2곳) | Streamlit 즉시 크래시 | 사이드바에 한 벌, 나머지는 상태 표시만 |
| 커스텀 헬퍼가 AST 스캐너를 피함 (`_kpi_row` · plotly `name=`/`title=`) | 스캔은 통과인데 화면엔 한국어 | 호출부 수동 감사 + 경고 주석 |
| `AppTest`가 `st.rerun()`을 자동으로 안 따라감 | 정상 동작이 테스트 실패로 보였다 | 액션 후 `at.run()` 한 번 더 |

## v28~v37 검증

```
selftest_all               12/12 통과 (79.0초)
전체 컴파일 (3.11.15)      60파일 · 실패 0
i18n                       571키 × 4개국어 · 누락 0 · 키 노출 0
영어 화면 한국어 잔존      94 → 5 (전부 모델 피처명 · 의도적)
AI 분석 탭 (확정 첫 화면)  번역 전후 한국어 렌더 561행 스냅샷 — 문구 차이 0
미탐 곡선                  τ별 손계산 대조 일치 · 미탐 0건이면 기존 곡선과 완전 동일
                           최소점 이동 τ 0.18 → 0.10 (표본 200 + 미탐 25)
압축 탭                    4개 국어 × 압축 on/off × 배치안 — 예외 0
확정 요구사항              첫 탭 = 🧠 AI (전 조합) · th_review = 0.005 불변
```

## 파일 변경 규모

```
ops_dashboard.py       2,613 → 3,022 (+409)
detect_workbench.py      830 →   875  (+45)
ops_ui.py                      1,848        571키 × 4개국어
ops_queries.py                   782        threshold_whatif_fn 신설
```

## 버전

`ops_dashboard v27→v37` · `ops_ui v20→v29` · `ops_queries v21→v22` ·
`ops_sidebar v21→v23` · `ops_guide v2→v3` · `ops_shift v1→v2` ·
`ops_dispatch v3→v4` · `watcher_panel v15→v16`

## v37 남은 과제

| 항목 | 내용 |
|---|---|
| **피처 사전 다국어화** | 계좌 이력 피처명은 `model_meta.json`·임계값 리포트·설명서가 **같은 이름을 쓴다.** 화면만 번역하면 리포트와 대조가 불가능해진다 → 넷을 함께 옮기는 별도 과제. **사용자 판단으로 보류(2026-08-10).** |

---

# v38 — 두 대시보드 합치기 (발송물 · 프롬프트 · 경보) + 보고서 저장

**요청 배경**
> "dashboard.py 하고 ops_dashboard.py 가 각각 5번/1번 세션에서 AI 분석을 하고
>  메시지를 발송하는 과정과 결과물이 다른 것 같아. 기존 dashboard.py 의 발송
>  방식과 프롬프트가 좋은데 지금 연동이 안되고 개별로 들어가 있는 상태인 거야?"

맞았다. 부품(`llm_analyzer`·`detect_workbench`·`rag_searcher`)은 이미 공유하고 있었지만
**결과물을 만드는 계층**이 두 벌이었다. 같은 탐지 건이라도 어느 화면에서 보내느냐에 따라
전혀 다른 통보가 나갔다.

| | dashboard 세션5 | ops 세션1 (수정 전) |
|---|---|---|
| Slack | 위험도 게이지·확률 분포 헤더 + LLM 텍스트 | 머리말 + LLM 텍스트 **끝** |
| Email | KPI 카드 HTML + **강제 마스킹된 HTML 리포트 첨부** | 평문 한 덩어리 |
| 프롬프트 | `prompt_ov_*` (세션 전용) | 같은 키지만 **다른 프로세스** → 공유 안 됨 |
| 감사 로그 | `session_state` (휘발) | `audit_store` DB (영속) |
| 경보 | 삐- 소리 하나 | 등급·데스크톱·카드·중복억제 |

`dashboard.py` 는 `ops_dispatch` 를 import 하지 않았고, `ops_dashboard.py` 는
`notify_visuals` 를 import 하지 않았다 — **두 파일이 서로의 발송 코드를 몰랐다.**

## 1. 리치 컴포저 → `pipeline/notify_compose.py` (신설)

발송물 서식의 단일 출처. dashboard 세션5 에만 있던 컴포저 4종을 옮기고 양쪽이 호출한다.

```
labels(t) · fraud_short(code, lang) · batch_type_counts(bres)
slack_single / email_single / slack_batch / email_batch
report_md_single / report_md_batch          <- 3장
```

**앱마다 다른 것은 전부 인자로 받는다** — 이 모듈은 `st.session_state` 를 읽지 않는다.

| 인자 | dashboard | ops |
|---|---|---|
| `t` / `lang` | `tt` | `ui.make_ops_t` (둘 다 i18n_data 폴백) |
| `head` | `_tier_head` | `ops_dispatch.tier_head` |
| `rich` | `rich_notify` | `ai_rich_notify` (신설·기본 ON) |
| `masker` | `_build_masker_forced` | 〃 (신설) |
| `body` | (없음 — LLM 원문) | **화면에서 편집한 본문** |

`body` 인자가 핵심이다. ops 의 이메일 미리보기는 "여기 보이는 그대로 나간다"가 계약이라,
편집본을 그대로 감싸야 한다.

**dashboard.py 는 위임만 남았다 (-80줄).** 출력물은 완전히 동일하다.

### 통로 확장 (하위 호환)

- `ops_dispatch.send_manual(html=…, attachments=…)` — 안 넘기면 예전처럼 평문 한 파트
- `auto_send` 의 `compose_email` 이 **문자열/3-튜플 둘 다** 수용

### ops 발송 UX 는 그대로 두되, 리치 구성 시점을 옮겼다

예약(`_send_ask`) 이 아니라 **확인(`_send_confirm`) 시점**에 만든다 — 확인 카드에
보이는 본문이 곧 나가는 본문이어야 하기 때문이다. 예약 때 미리 만들어두면 그 사이
마스킹·등급 설정을 바꿔도 낡은 본문이 나간다. 첨부 파일명도 승인 전에 보인다.

## 2. 프롬프트 저장소 → `prompts/overrides.json`

`prompt_ov_*` 가 `session_state` 에만 살았다. 두 앱은 별개 프로세스라
**세션5 에서 고친 프롬프트가 ops 분석에 반영되지 않았고**, 새로고침 한 번에 사라졌다.

```
detect_workbench:  prompt_store_path() · load_prompt_store() · save_prompt_override()
경로 변경:         FDS_PROMPT_STORE
```

**저장 성공 시 세션 사본을 지운다.** 이것이 이 변경의 핵심이다 —
사본을 남기면 상대 앱이 나중에 저장한 프롬프트를 이 세션이 영원히 무시해서,
파일로 옮긴 의미가 사라진다. 파일이 유일한 진실이고, 세션 사본은 **파일 쓰기가
실패했을 때만** 남는 비상 경로다.

| | |
|---|---|
| 동시 저장 | 쓰기 직전 read-modify-write + `os.replace` 원자 교체 → 다른 슬롯끼리는 안 덮음 |
| 깨진 파일 | 경고 로그 한 줄 + 기본 프롬프트로 진행 (앱은 안 멈춤) |
| 기본값 복원 | 파일에서도 삭제 → 두 앱 모두 기본값 복귀 |
| 화면 표시 | 편집기에 저장 경로 + "두 대시보드가 이 파일 한 벌을 함께 씁니다" |

별도 프로세스 2개로 교차 검증했다 — A 가 저장 → B 가 읽음 → B 가 다른 슬롯 추가 →
두 슬롯 모두 생존.

## 3. 보고서 `.md` 저장 — ops 에 신설

Slack/Email 은 '지금 알린다'이고 `.md` 는 '나중에 남긴다'다. 관제 화면에는 후자가
아예 없어서, 분석 결과를 보관하려면 화면을 복사하거나 **자기 앞으로 메일을 보내야 했다.**
저장(안전)이 없다는 이유로 발송(되돌릴 수 없음)을 누르게 되는 구조였다.

- 탐지 결과 · 단건 분석 · 배치 3곳에 `보고서 저장 (.md)`
- 서식은 `notify_compose.report_md_*` 단일 출처 — 두 화면이 낸 보고서 항목이 갈리면 비교가 안 된다
- **dashboard 배치 저장도 개선**: `_bres.analysis` 본문만 던지던 것 → KPI·유형분포 머리말 + 3단계 산출물

## 4. 경보 시스템 — dashboard 에 적용 · 설정 공유

dashboard 에는 `_play_alarm()` 삐- 소리 하나뿐이었다. 다른 세션을 보고 있거나 창을
내려놨으면 **탐지 사실 자체를 놓쳤고**, 등급·중복억제 같은 정책이 하나도 없었다.

- `pipeline/ops_alert.py` 를 그대로 쓴다 — 단건 탐지 · 배치 두 경로
- 결과를 그린 **뒤에** 쏜다 (카드가 우상단 고정이라 먼저 쏘면 같은 rerun 에서 묻힌다)
- 배치는 **대표 1건만** — 한 번에 수십 건이 울리면 아무것도 안 울린 것과 같다
- 등급 경계는 `watcher_config.json` — ops 와 같은 출처

### 설정 공유 — `alarm_prefs.json`

```
ops_alert:  prefs_path() · load_prefs() · save_prefs(ss) · init_state(ss, shared=True)
경로 변경:  FDS_ALARM_PREFS
```

공유하는 것은 **사용자가 정한 값만**(`SHARED_KEYS` 12개). 런타임 상태는 공유하지 않는다 —
워터마크(`_alarm_seen_id`)를 공유하면 한쪽이 본 경보를 다른 쪽이 영영 못 보고,
오디오 활성화(`alarm_audio_armed`)는 **브라우저 탭마다** 따로 받아야 하는 권한이다.

AppTest 로 양방향 확인: dashboard 에서 끄면 ops 가 이어받고, ops 에서 등급을 바꾸면
dashboard 가 이어받는다.

### '조용한 시간'·'중복 억제'는 dashboard 에 넣지 않았다

둘 다 워처가 **무인**으로 올리는 경보용 정책(`poll_new`)인데, dashboard 의 경보는
담당자가 [탐지 실행]을 누른 결과라 적용될 일이 없다. 있으나 마나 한 스위치를 놓으면
"껐는데 왜 울려요"가 된다. 어디서 설정하는지만 캡션으로 안내한다.

## 5. 버그 — "윈도우 알람이 안 온다" — 원인 2개

사용자 보고로 발견. **둘 다 조용히 실패해서 화면에 아무 흔적이 없었다.**

**① 브라우저 알림 권한** — `desktop()` 은 `Notification.permission !== 'granted'` 면
그냥 return 한다. 권한은 사용자가 버튼을 눌러야 요청되는데, 그 활성화 버튼을
**접힌 expander 안에** 넣어 뒀다. 안 보이니 아무도 안 누르고 → 알림이 영영 안 온다.

→ 버튼을 접힌 패널 **밖**, 마스터 토글 바로 아래로. ops 에만 있던 **진단 버튼**도 추가
(파이썬은 권한 상태를 못 읽는다 — 브라우저가 직접 읽어 화면에 써 준다).

**② 등급 필터** — `alarm_tier` 기본값 `confirm` + 이 프로젝트의 확정 경계 **0.9**.
위험도 0.85 짜리 이상거래를 탐지해도 **아무 흔적 없이** 사라졌다.

→ 걸러낼 때마다 이유를 캡션으로 남긴다:

```
[알림없음] 위험도 0.6000 — 현재 '확정만 (0.9 이상)' 설정이라 알리지 않았습니다
           (확정 경계 0.9). 사이드바 '경보 세부 설정 → 울릴 등급'에서 낮출 수 있습니다.
```

경보가 안 울리는 이유는 셋뿐인데(꺼짐·등급미달·권한) 셋 다 무증상이면
사용자로서는 "고장났다"고밖에 볼 수 없다.

## 6. AI 자동실행 토글 위치 (ops)

`if _dlast['is_anomaly']:` 안에 있어서 **탐지 실행 전에는 보이지 않고, 정상 판정이면
아예 안 나타났다.** 이미 LLM 이 도는 걸 본 뒤에야 끌 수 있었으니, 로컬 모델 수십 초
상황에서 "급하니 건너뛰자"를 선택할 방법이 사실상 없었다.

→ 탐지 입력 바로 위, 실행 버튼과 같은 화면으로. 결과 블록에서는 **값만 읽는다**
(같은 key 로 위젯을 두 번 만들면 `DuplicateWidgetID` 로 죽는다).

## 7. 버그 — 테스트가 사용자 설정 파일을 덮어썼다

**설정을 파일로 옮기면 앱을 실행하는 테스트가 그 파일을 건드릴 수 있다.** 두 번 겪었다.

| | 증상 | 조치 |
|---|---|---|
| `prompts/overrides.json` | selftest_ui 가 편집기 [저장]/[복원]을 **실제로 클릭**한다 — 리다이렉트 안 하면 실행할 때마다 사용자 프롬프트가 지워진다 | `FDS_PROMPT_STORE` 를 임시 경로로 |
| `alarm_prefs.json` | AppTest 가 위젯 값을 바꾸면 `on_change` 가 **실제로 발화**해 전부 꺼짐·0 으로 덮였다. 그 파일 때문에 다음 실행에서 `selftest_alert` 의 중복억제 검증이 깨져 발견 | `FDS_ALARM_PREFS` 를 임시 경로로 + `selftest_alert` 는 `shared=False` |

기존에 운영 DB 를 사본으로 쓰던 것과 같은 원칙이다. 설정 파일도 같은 대접이 필요했다.

`selftest_ui` 14절의 어서션 2개는 새 계약에 맞게 갱신했다 — 세션 사본이 아니라
`prompt_overrides()` 가 무엇을 돌려주는지를 본다. 진짜 목표를 검증하는 항목도 추가했다:
"한쪽이 저장하면 다른 쪽이 읽는다" · "저장 후 세션 사본을 남기지 않는다".

## 8. 합치지 **않은** 것 — 설계상 달라야 하는 것

| 항목 | 왜 분리 유지 |
|---|---|
| API 키·수신처 (`ov_*` vs `ai_*`) | 프롬프트는 **분석 결과를 결정하는 내용물**이라 같아야 하고, 키·수신처는 **접속 자격**이라 운영/검증이 갈려야 한다. 같은 축으로 합치면 한쪽을 합치는 순간 다른 쪽까지 샌다 |
| 발송 UX | ops = 확인 카드 + DB 감사 로그 / dashboard = 자동 발송 + 즉시 발송. 관제와 분석은 책임이 다르다 |
| 워터마크·오디오 활성화 | 4장 참조 — 공유하면 경보를 놓치거나 권한이 안 먹는다 |

## 9. 이번에 밟은 함정 — 재발 방지용 기록

| 함정 | 증상 | 교훈 |
|---|---|---|
| **세션 사본이 파일을 이긴다** | 프롬프트를 파일로 옮겼는데도 상대 앱 저장이 반영 안 됨 | 공유가 목적이면 **저장 성공 시 세션 사본을 지운다** |
| **테스트가 사용자 설정을 덮어씀** | `selftest_alert` 중복억제 검증이 갑자기 깨짐 | 설정 파일도 DB 처럼 임시 경로로 리다이렉트 |
| **권한이 필요한 버튼을 접어 둠** | 설정은 다 켜져 있는데 윈도우 알림만 안 옴 | 브라우저 제스처가 필요한 버튼은 **절대 접지 않는다** |
| **필터가 흔적 없이 삼킴** | 위험도 0.85 탐지에 아무 반응 없음 | 걸러낼 때마다 **이유를 화면에 남긴다** |
| **리치 OFF 에서 머리말까지 사라짐** | 등급 머리말은 시각화가 아니라 지시문인데 함께 꺼졌다 | `rich` 는 시각화만 끈다 — 리팩터링 중 자체 발견 |
| 위젯 토글을 결과 블록 안에 배치 | 실행 전에 못 고르는 스위치 | 결정 시점과 위젯 위치를 맞춘다 |

## v38 검증

```
selftest_all               12/12 통과 (85.7초)
전체 컴파일 (3.11.15)      실패 0
i18n (ops_ui)              586키 x 4개국어 · 누락 0
컴포저 교차 검증            강제 마스킹 적용 · '_' 내부필드 제외 · 편집본 반영 · 마스커 없으면 표 비움
프롬프트 공유              별도 프로세스 2개 — A저장→B읽기→B추가→두 슬롯 생존 · 깨진 파일 복원력
경보 설정 공유             AppTest 양방향 — dashboard OFF→ops 이어받음 / ops tier→dashboard 이어받음
설정 파일 오염             전체 스위트 실행 후 alarm_prefs.json · prompts/overrides.json 생성 안 됨
```

## 파일 변경 규모

```
신설  pipeline/notify_compose.py              221    발송물·보고서 서식 단일 출처
수정  dashboard.py              5,744 -> 5,843 (+99)   컴포저 -80 / 경보 +179
      ops_dashboard.py          3,033 -> 3,197 (+164)
      pipeline/ops_ui.py        1,848 -> 1,925 (+77)   586키 x 4개국어
      pipeline/ops_alert.py       834 ->   919 (+85)   설정 공유
      pipeline/detect_workbench.py 875 -> 988 (+113)   프롬프트 저장소
      pipeline/ops_dispatch.py    718 ->   730 (+12)   html/첨부 통로
      pipeline/ops_sidebar.py     493 ->   507 (+14)
      pipeline/selftest_ui.py     573 ->   599 (+26)   새 계약 검증 + 오염 방지
문서  prompts/README_prompts.md · .gitignore (overrides.json · alarm_prefs.json)
```

## 버전

`ops_dashboard v37→v38` · `ops_ui v29→v30` · `ops_sidebar v23→v24` ·
`ops_alert v24→v25` · `ops_dispatch v4→v5` · `detect_workbench v2→v3` ·
`notify_compose v1` (신설)

## v38 남은 과제

| 항목 | 내용 |
|---|---|
| **피처 사전 다국어화** | v37 에서 이월. 사용자 판단으로 보류(2026-08-10) |
| **API 키 공유 여부** | 현재 의도적 분리(8장). 운영/검증을 한 벌로 쓰기로 결정하면 그때 별도 과제 — 키는 프롬프트와 달리 **유출 반경**이 다르므로 같은 방식으로 옮기면 안 된다 |
| **경보 카드 → 세션 이동** | ops 는 카드 클릭 시 `?goto=` 로 탐지 로그가 열린다. dashboard 는 그 수신부가 없어 클릭해도 이동하지 않는다(소리·알림·카드는 정상) |

---

# v39 — 관제 콘솔 키보드 단축키 · AI 액션 확장 (9→25종)

`dashboard.py` 에는 있는데 `ops_dashboard.py` 에만 없던 두 축을 채웠다.
v38이 '결과물을 만드는 계층'을 합친 작업이었다면, 이번은 **조작 계층**이다.

| | 이전 | v39 |
|---|---|---|
| 키보드 단축키 | **0** (`keydown` 검색 결과 0건) | **12종** + `?` 전체 목록 모달 |
| 챗 에이전트 액션 | 9종 | **25종** (dashboard 21종을 넘어섬) |
| 퀵프롬프트 | 없음 | 4개 |
| 에이전트 자가진단 | 없음 | 등록 수 · 파서 왕복 · 화이트리스트 · 액션 직접 실행 |

## 1. 키보드 단축키 — 신설

`1`~`8` 탭 · `←→` 이전/다음 · `C` 챗 포커스 · `H` 안내 · `?` 목록 ·
`R` 새로고침 · `A` 자동새로고침 · `V` 압축 · `B` 사이드바 · `T` 테마 ·
`L` 언어 · `Ctrl+/` 힌트.

키 배치는 **dashboard 와 의도적으로 동일**하다(두 앱을 오가는 담당자의
근육기억). `R`·`A` 만 관제 전용 추가 — 저쪽엔 없는 개념이다.

### 왜 파일 **맨 끝**인가

히든 버튼을 누르면 `st.rerun()` 이 걸리고, Streamlit 은 **그 런에서 그려지지
않은 위젯의 상태를 폐기**한다. 단축키 블록이 앞쪽에 있으면 키 한 번에 뒤쪽
탭의 위젯(트리아지 필터·로그 검색어)이 초기화된다. dashboard 는 v12 에서
이 문제를 위젯 key 를 상태값과 조합하는 우회로 막았는데, ops 는 **모든 위젯이
그려진 뒤**에 두는 쪽을 택했다 — 우회가 필요 없다.

### 두 갈래

| 갈래 | 대상 | 방식 |
|---|---|---|
| 순수 클라이언트 | 탭 이동 · 사이드바 · 챗 포커스 | JS 가 DOM 직접 클릭. **rerun 없음** |
| 파이썬 상태 | 테마 · 언어 · 압축 · 자동새로고침 | 히든 버튼 → 상태 전환 → rerun |

ops 는 `st.tabs(key=, default=)` 라 탭 이동을 DOM 클릭으로 처리할 수 있다.
문서 순서상 **첫 번째** `[role="tablist"]` 로 범위를 좁힌다 — AI 탭 서브탭과
로그 상세탭도 `[role="tab"]` 이라 그냥 잡으면 엉뚱한 걸 누른다.

가드는 dashboard 에서 그대로 가져왔다: IME 조합(`isComposing`) 무시 ·
`INPUT/TEXTAREA/SELECT`·`contentEditable` 회피 · baseweb 셀렉트/슬라이더/탭
포커스 시 차단 · **항상 제거 후 재등록**(테마 변경 시 iframe 재마운트로
리스너가 죽는 문제. dashboard v8.4 와 동일 원인).

## 2. 챗 에이전트 액션 9 → 25종 (`pipeline/ops_agent.py` v1→v2)

추가 16종 — 전부 **되돌릴 수 있는 표시 설정**이거나 **밖으로 내보내지 않는 실행**:

```
표시  set_window · set_min_score · set_queue_limit · set_only_new · set_sort_dir
      set_log_limit · set_log_anomaly_only · set_fp_dim · set_compact_tabs
      set_auto_refresh · set_refresh_sec
조회  search_log · open_keymap
실행  run_ai_analysis · run_batch · set_batch_window
```

`run_*` 는 결과를 화면에 만들 뿐이고, 발송은 그 뒤 사람이 누르는 별도
버튼(`det_send_slack` 등)이다. 버튼은 위젯 **반환값**이라 세션 상태로 누를 수
없으므로 예약 플래그(`_pending_ai_run`)를 쓴다.

### ★ 새로 막은 축 — 경보 등급 임계값

`th_review`/`th_confirm` 저장은 표면상 화면 설정이라 넣을 뻔했다. 그런데 이
값은 `watcher_config.json` 에 저장되고 그 파일은 **핫 리로드**다 — 저장하는
순간 재시작 없이 무인 워처의 경보 기준이 바뀐다(`_tier_th` 주석). 실질적으로
워처 제어라 레지스트리에서 제외하고, 사람이 비용곡선(§v37 12.1)을 보고
직접 누르는 쪽으로 남겼다. 발송·판정·워처 제어 차단은 이전과 동일.

## 3. 🐛 `sort_queue` 가 죽어 있었다 (기존 버그)

*"위험점수 순으로 정렬해줘"* 가 **동작하지 않았다.** 챗봇은 "바꿨습니다"라고
답하는데 화면은 그대로.

```
apply()  ss["tri_sort"] = "점수순"          ← 화면 표시 문구
화면     _SORT_OPTS = ["age", "score"]
         if ss.get("tri_sort") not in _SORT_OPTS: ss.pop("tri_sort")   ← 매번 버려짐
```

구버전 값 정리 코드에 걸려 **조용히 폐기**됐다. 실패 표시조차 없었던 것이
문제의 핵심이다. 위젯 옵션값으로 교정하고, 같은 방식으로 죽지 않도록
25종 전수에 대해 "상태가 실제로 바뀌고 메모가 나오는가"를 검사한다.

## 4. 챗 UX — 퀵프롬프트 · 자가진단

액션이 25종인데 앱 안에서 확인할 방법이 없으면 반쪽이다. 자가진단 패널은
**LLM 없이** 파서를 왕복 검증한다 — 여기서 초록불인데 액션이 안 먹으면
원인은 액션 파이프라인이 아니라 **LLM 연결**이라고 담당자가 혼자 가릴 수 있다.

## 5. 이번에 밟은 함정 — 재발 방지용 기록

| 함정 | 증상 | 처리 |
|---|---|---|
| **위젯 key 를 위젯 생성 후 수정** | 단축키 `V`/`A` 가 안 먹고 빨간 박스. 히든 버튼이 파일 끝이라 진단탭·실시간탭 토글보다 뒤였다 | 예약값(`_pending_compact`/`_pending_autorf`) → 위젯 앞에서 소비 |
| 같은 함정 (2번째) | 자가진단 '이 액션 실행' 이 AI 탭 안이라 `apply()` 인라인 호출이 터졌다 | 챗 입력과 같은 **적재 → 드레인** |
| **값만 보는 테스트** | 위 두 건을 테스트가 통과시켰다 — 예외가 나도 값 검사만 하면 모른다 | 모든 검사에 **예외 0 단언 병행** |
| 실행 플래그를 탭 **안**에서 pop | 조건이 안 맞은 런에서 안 지워져, 다음 자동 새로고침에 시키지도 않은 분석이 돈다 | `JUMP_TXN` 과 같이 탭 밖에서 pop |
| f-string 중첩 따옴표 | 배포 환경이 **Python 3.11** — 3.12+ 문법이라 기동부터 SyntaxError 였을 것 | 색상을 미리 변수로 꺼내 보간 |
| `components.v1.html` 폐기 | 지원 종료 예고일(2026-06-01) 경과 · 경고 출력 | dashboard 의 `_html()` 호환 쉼 이식 (st.iframe 우선, 실패 시 폴백) |

## v39 검증

```
selftest_all               12/12 통과 (167.2초 · UI 회귀가 156초)
selftest_agent             액션 25종 · example 파서 왕복 전수 · 위험 액션 차단 · 조용한 실패 0
selftest_ui (AppTest)      히든 버튼 8개 실제 클릭 · 예외 0 · 액션 반영 회귀
생성 JS                    node --check 통과 (키 리스너 · 챗 포커스)
전체 컴파일 (3.11.15)      실패 0
```

새 테스트는 값 변화와 **예외 0 을 항상 함께** 본다(위 5장 3행).

## 파일 변경 규모

```
수정  ops_dashboard.py          3,197 -> 3,554 (+357)   단축키 +234 / 챗UX · 배선
      pipeline/ops_agent.py       305 ->   598 (+293)   9 -> 25종 · sort_queue 수정
      pipeline/selftest_agent.py  179 ->   287 (+108)   신규 4절
      pipeline/selftest_ui.py     599 ->   721 (+122)   ⌨ 절 신설
문서  ops_dashboard_사용설명서.md §3 단축키 · §4 액션 · §13 신설
      OPS_BACKLOG.md  B2 신설
```

## 버전

`ops_dashboard v38→v39` · `ops_agent v1→v2`

## v39 남은 과제

| 항목 | 내용 |
|---|---|
| **비한국어 연속 렌더 자동검증** | `OPS_BACKLOG.md` **B2** 신설. AppTest 가 언어 전환 후 2회차 run 에서 죽는다(`batch_src` 라디오). **v39 와 무관한 기존 현상** — 단축키를 들어낸 사본에서도 재현. 실제 브라우저는 영향 없으나 i18n 회귀를 자동으로 못 잡는다 |
| **피처 사전 다국어화** | v37 에서 이월. 보류(2026-08-10) |

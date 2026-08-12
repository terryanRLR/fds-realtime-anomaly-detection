# 배포 번들 — LightGBM 13-class

추론에 필요한 모델 + 메타 파일 한 벌입니다. **메타 4종은 모델과 세트로 움직입니다** —
하나라도 빠지거나 세대가 어긋나면 추론이 조용히 틀어집니다.

> ⚠️ **저장소에는 `.pkl` 이 포함되지 않습니다** (합계 136MB, `rf_fds.pkl` 단독 83MB).
> 커밋되는 것은 **메타 JSON 4종**(`feature_cols` · `feature_defaults` · `model_meta` · `eval_result`)과
> 이 문서·`로드예제.py`·`*.sql` 뿐입니다.
> 모델 파일은 `notebooks/team_final/` 01~06 을 실행해 재생성하거나 팀에서 받으세요.
> 모델 카드와 성능 근거: [`docs/07_model_and_thresholds.md`](../docs/07_model_and_thresholds.md)

## 현행 번들 (`model_meta.json` 기준)

| 항목 | 값 |
|---|---|
| 모델 파일 | `lgbm_13class(최종).pkl` |
| 피처 수 | **58** |
| 클래스 | 13 — 사기 `a`~`l` + 정상 `m` (normal_index = 12) |
| 검증 Macro-F1 | **0.6138** |
| 트리 수 | 300 |
| 인코딩된 범주형 컬럼 | 45 |

> ⚠️ `is_fraud`(정답 라벨) 누수 컬럼은 제외하고 학습했습니다.
> 전처리 결과에 이 컬럼이 남아 있으면 반드시 drop 하세요.

### 세대 주의 — `model_meta(요약).json` 은 구 번들입니다

| | `model_meta.json` (현행) | `model_meta(요약).json` (구) |
|---|---|---|
| 피처 수 | 58 | 60 |
| Macro-F1 | 0.6138 | 0.5994 |

`feature_cols.json` · `feature_defaults.json` 은 **둘 다 58개**로, 현행 모델과 일치합니다.
구 요약본은 이력 참고용으로만 두세요 — 추론 코드는 `model_meta.json` 만 읽습니다.

## 파일

| 파일 | 형식 | 내용 |
| --- | --- | --- |
| `lgbm_13class(최종).pkl` | joblib/pickle | **운영 모델** |
| `lgbm_13class(모델).pkl` | joblib/pickle | 동일 계열 이전 산출물 |
| `feature_cols.json` | JSON list(58) | **모델 입력 컬럼 순서**. 추론 시 이 순서로 정렬 |
| `feature_defaults.json` | JSON dict(58) | 결측 대치 기본값 (실수=중앙값, 정수/코드=최빈값) |
| `le_target.pkl` | sklearn LabelEncoder | 클래스 인덱스 ↔ 라벨. `inverse_transform(pred)` → `'a'`~`'m'` |
| `label_encoders.pkl` | dict{col: LabelEncoder} | 범주형 컬럼별 인코더 (관측된 정수 코드 기준) |
| `model_meta.json` | JSON | 요약 — 피처수·클래스맵·정상인덱스·성능 |
| `eval_result.json` | JSON | 학습 시점 리포트 (QA 대시보드 세션 2 '정적' 모드가 읽음) |
| `로드예제.py` | py | 로드 + 정렬(`prepare`) + 예측(`predict`) 예제 |
| `rf_fds.pkl` · `lgbm_fds.pkl` 등 | pickle | 비교용 추가 모델 — 세션 2 셀렉터에 노출됨 |
| `*.onnx` / `*.pmml` / `*.sql` | — | 추가 형식. 넣기만 하면 셀렉터에 뜸 |

## 사용

```python
from 로드예제 import predict
idx, label = predict(df)      # df: 전처리 형식 DataFrame
```

앱 안에서는 `pipeline/model_loader.py` 가 형식을 가리지 않고 통합 `predict_proba` 로 감쌉니다.

## 탐색 순서

`FDS_MODEL_DIR` → `CWD/models` → `프로젝트루트/models` → `pipeline/models` → `pipeline/` → 프로젝트 루트 → `CWD`

## 배포 전 검증

```bash
python -m tools.verify_bundle
python -m tools.verify_bundle --raw data/train.csv --x data/X_tr.parquet   # 변환 규칙 자가검증까지
```

## ⚠️ `label_encoders.pkl` 주의

전달받은 parquet 이 **이미 숫자로 인코딩된 상태**라 원본 문자열 ↔ 코드 매핑은 복원할 수 없습니다.
따라서 이 파일은 **관측된 정수 코드**로 복원한 식별용 인코더입니다 (코드 유효성 검증·역참조용).
원본 문자열을 코드로 변환해야 한다면 전처리 단계의 **원본 인코더**를 쓰세요.
나머지 3종(`feature_cols` / `feature_defaults` / `le_target`)은 모델과 정확히 일치합니다.

> 📌 `le_target.pkl` 은 parquet 정수 라벨(0~12) 디코딩에도 재사용됩니다 — 지우지 마세요.

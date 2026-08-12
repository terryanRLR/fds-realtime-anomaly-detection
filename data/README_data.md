# data/ — 데이터셋 배치 위치 (앱 관점)

> 📌 **스키마 · 세대 · 재생성 절차는 [`README.md`](README.md) 를 보세요.**
> 이 문서는 **대시보드가 데이터셋을 어떻게 인식하는지**만 다룹니다.

여기에 `*.csv` / `*.parquet` 를 두면 **사이드바 '데이터셋' 선택기가 자동으로 찾습니다.**

## 인식 규칙

- `X_*` / `y_*` 페어는 **자동 결합**됩니다 (`X_tr.parquet` + `y_tr.parquet` → 한 데이터셋).
- 결합은 **위치 기준**입니다 — 인덱스로 붙이면 어긋납니다. 파일만 페어로 두면 로더가 처리합니다.
- **접두어가 붙어도 인식됩니다**: `구 X_tr.parquet`, `구구 X_va.parquet`, `old_y_va.parquet` …
  ([dataset_loader.py:45](../pipeline/dataset_loader.py#L45)) — 세대별 데이터셋을 나란히 두고 고를 수 있습니다.
- 라벨(`Fraud_Type`) 유무에 따라 🏷️(평가 가능) / ❔(예측 전용)로 표시됩니다.
- 정수 라벨(0~12)은 `models/le_target.pkl` 로 `'a'`~`'m'` 자동 디코딩됩니다.

## 현재 들어 있는 것

| 파일 | 용도 |
|---|---|
| `train.csv` | 원본 학습 데이터 (`Fraud_Type` 라벨 포함) |
| `test.csv` | 라벨 없는 평가용 |
| `X_tr.parquet` / `y_tr.parquet` | 전처리 완료 학습 세트 |
| `X_va.parquet` / `y_va.parquet` | 검증 세트 |
| `구 *.parquet` / `구구 *.parquet` | 이전 세대 — 선택기에 함께 노출됩니다 |

## 주의

- **parquet X 에는 NaN 이 있습니다** (`amount_to_month_max_ratio` 등 파생 컬럼).
  LightGBM 은 그대로 처리하고, LogReg/ONNX 비교 시 자동으로 `fillna(0)` 됩니다.
- 데이터셋과 모델의 **피처 수가 맞아야** 합니다. 어긋나면 해당 모델만 사유와 함께
  스킵되고 앱은 죽지 않습니다.
- 🔴 이 폴더의 데이터 파일은 `.gitignore` 로 제외돼 있습니다 (141MB). 저장소에 커밋하지 마세요.

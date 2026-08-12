# models/ — 모델 배치 위치

상세는 같은 폴더의 [README.md](README.md) 를 보세요. 여기서는 요약만 둡니다.

**필수 메타 4종** (모델과 세트로 움직입니다 — 하나라도 빠지면 추론이 어긋납니다):

```
label_encoders.pkl · le_target.pkl · feature_cols.json · feature_defaults.json
```

부가 파일: `model_meta.json`(현행 요약) · `eval_result.json`(학습 시점 리포트)

`*.pkl` / `*.onnx` / `*.pmml` / `*.sql` 을 추가로 두면 QA 대시보드 세션 2 의
모델 셀렉터에 자동으로 나타납니다.

> 📌 `le_target.pkl` 은 parquet 정수 라벨 디코딩에도 재사용됩니다 — 반드시 유지하세요.

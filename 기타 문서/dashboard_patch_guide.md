# FDS v5 업데이트 — 타당성 검토 결과 & 대시보드 통합 패치 가이드

검증 환경: Python 3.12 / 실스키마(48피처) 합성 데이터 3,000행 / LightGBM·LogReg 학습 모델
모든 신규 모듈은 실제 실행 테스트를 통과했습니다 (하단 테스트 로그 요약 참조).

---

## 0. 타당성 결론 요약

| 항목 | 판정 | 비고 |
|---|---|---|
| 1. 세션5 배치(묶음) 분석 | ✅ 가능 | `batch_analyzer.py` 신규 — 테스트 통과 |
| 1-1. 배치 스크립트 | ✅ 완료 | LLM 1회 호출 구조 (건별 호출 대비 n배 절약) |
| 1-2. 배치 프롬프트 | ✅ 완료 | "정상 n건, A형 2건…" 집계 인용 강제 양식 |
| 2. 세션2·3 동적 그래프 | ✅ 가능 | `evaluator.py` 신규 — 3모델 교차비교·13×13 CM·실측 비용곡선 검증 |
| 2-1. Parquet X/y 분할셋 | ✅ 가능 | `dataset_loader.py` — ID merge / 위치 concat 양쪽 검증 |
| 2-2. 모델 ONNX | ✅ 가능 | onnxruntime — sklearn 원본과 오차 1.27e-07 |
| 2-2. 모델 PMML | 🟡 조건부 | sklearn-pmml-model(순수 파이썬) — 트리·선형 계열만. 미지원 구조는 pypmml(JVM 필요) 폴백 |
| 2-2. 모델 SQL | 🟡 규약 필요 | DuckDB 실행 — `proba_<class>` 컬럼 규약 준수 시 동작 (m2cgen 출력 호환) |

**PMML/SQL 솔직한 한계**: PMML은 "파일이면 다 열림"이 아니라 *모델 계열 의존*이야.
LightGBM→PMML(sklearn2pmml 경유)은 GBM 구조라 대체로 읽히지만, 커스텀 전처리가
파이프라인에 박힌 PMML은 실패할 수 있어 → 로더가 예외를 잡고 사유를 표시하도록 설계함.
SQL은 "임의 SQL 모델"이 아니라 **스코어링 쿼리 규약**(아래 §4)을 정의해서 지원하는 방식이
현실적인 최선이고, 그 규약으로 구현·테스트 완료했어.

---

## 1. 신규 파일 배치

```
pipeline/dataset_loader.py   # 데이터셋 검색·로딩 (CSV/Parquet/X+y 결합)
pipeline/model_loader.py     # pkl/ONNX/PMML/SQL 통합 어댑터 (UnifiedModel)
pipeline/evaluator.py        # 동적 평가 (모델비교·CM·실측 비용곡선·세션3 집계)
pipeline/batch_analyzer.py   # 묶음 분석 (집계→프롬프트→LLM 1회→보고서)
```

requirements.txt 추가:
```
pyarrow            # Parquet
duckdb             # SQL 모델 스코어링
onnxruntime        # ONNX 모델
sklearn-pmml-model # PMML (선택 — 미설치 시 pmml 로더만 비활성)
```

i18n_data.py 맨 아래에 `i18n_additions.py` 내용 붙여넣기 (신규 키 40여 개).
누락 키는 make_t가 키 문자열을 그대로 반환하므로 붙여넣기 전에도 앱은 죽지 않음.

---

## 2. dashboard.py 패치 ① — 사이드바에 데이터셋 선택기 신설

`train_path = st.text_input(...)` / `test_path = ...` 블록 **아래**에 추가:

```python
    # ── 📂 평가 데이터셋 선택 (세션 2·3 공용) — v5 신설 ──
    st.markdown(f'<p style="color:{T["text_muted"]};font-size:10px;letter-spacing:0.08em;text-transform:uppercase">{t("ds.section")}</p>', unsafe_allow_html=True)
    ds_folder = st.text_input(t("ds.folder_label"), st.session_state.get('ds_folder', 'data/'), key="ds_folder")

    @st.cache_data(ttl=60, show_spinner=False)
    def _discover_ds(folder):
        from pipeline.dataset_loader import discover_datasets
        return discover_datasets(folder)

    _ds_found = _discover_ds(ds_folder)
    if _ds_found:
        _ds_names = list(_ds_found.keys())
        _cur_ds = st.session_state.get('selected_dataset', _ds_names[0])
        _di = _ds_names.index(_cur_ds) if _cur_ds in _ds_names else 0
        _ds_sel = st.selectbox(t("ds.select_label"), _ds_names, index=_di, key="ds_sel_global",
                               format_func=lambda x: f"{'🏷️' if _ds_found[x].has_label else '❔'} {x}")
        st.session_state['selected_dataset'] = _ds_sel
        st.caption(_ds_found[_ds_sel].note)
    else:
        st.caption(t("ds.none_found"))
```

캐시 로딩 헬퍼(기존 `load_train_df` 근처, 전역 함수 영역):

```python
@st.cache_data(show_spinner=t("common.csv_loading_spinner"))
def load_selected_dataset(ds_folder, ds_name, _mt=None):
    """선택 데이터셋 로드 — X/y parquet은 자동 결합, 라벨은 Fraud_Type으로 통일"""
    from pipeline.dataset_loader import discover_datasets, load_dataset
    found = discover_datasets(ds_folder)
    if ds_name not in found:
        return None, None
    info = found[ds_name]
    return load_dataset(info), info
```

세션 3 첫 줄 `df = load_train_df()` 을 다음으로 교체하면 **세션 3 전체 그래프가
선택 데이터셋을 따라 자동 변동**됨 (기존 렌더 코드는 그대로 재사용):

```python
    df, _dsinfo = load_selected_dataset(st.session_state.get('ds_folder','data/'),
                                        st.session_state.get('selected_dataset',''))
    if df is None:
        df = load_train_df()          # 폴백: 기존 동작
    elif 'Fraud_Type' not in df.columns:
        alert_box(t("ds.no_label_warn"), "warn"); df = None
```

---

## 3. dashboard.py 패치 ② — 세션 2 동적 재평가 모드

세션 02 블록 상단(`eval_data=load_eval_result()` 직전)에 모드 스위치 추가:

```python
    _eval_mode = st.radio(t("s2.mode_label"), ["static", "dynamic"], horizontal=True, key="s2_mode",
                          format_func=lambda x: t("s2.mode_static") if x=="static" else t("s2.mode_dynamic"))
```

`dynamic` 선택 시 아래 블록 실행 → **eval_result.json과 동일 스키마 dict**를 만들어
기존 렌더 코드(`comp=eval_data["model_comparison"]` 이하)를 그대로 태움:

```python
    if _eval_mode == "dynamic":
        from pipeline.model_loader import discover_models, load_model
        from pipeline.evaluator import evaluate, threshold_cost_curve, make_batch_preprocess

        _mdl_found = discover_models("models/")            # 🥒pkl 🔷onnx 📄pmml 🗄️sql 전부
        _mdl_sel = st.multiselect(t("s2.model_multi_label"), list(_mdl_found.keys()),
                                  default=list(_mdl_found.keys())[:3], max_selections=3, key="s2_models")
        if st.button(t("s2.run_eval_button"), type="primary", key="s2_run"):
            df_eval, _info = load_selected_dataset(st.session_state.get('ds_folder','data/'),
                                                   st.session_state.get('selected_dataset',''))
            if df_eval is None or 'Fraud_Type' not in df_eval.columns:
                alert_box(t("ds.no_label_warn"), "warn")
            else:
                with st.spinner(t("s2.eval_spinner", n=len(_mdl_sel))):
                    try:
                        clf = _get_ml_classifier("models/lgbm_fds.pkl")   # 전처리기 재사용
                        prep = make_batch_preprocess(clf)
                        models = {}
                        for name in _mdl_sel:
                            try: models[name] = load_model(_mdl_found[name])
                            except Exception as _me: alert_box(t("s2.eval_fail", e=f"{name}: {_me}"), "error")
                        _MAX = 5000
                        ev = evaluate(models, df_eval, prep, max_rows=_MAX)
                        st.session_state['s2_dyn_eval'] = ev
                        st.session_state['s2_dyn_ytrue'] = df_eval['Fraud_Type'].astype(str).head(_MAX).tolist()
                    except Exception as e:
                        alert_box(t("s2.eval_fail", e=e), "error")
        if st.session_state.get('s2_dyn_eval'):
            eval_data = st.session_state['s2_dyn_eval']     # ← 이하 기존 렌더 코드가 그대로 소비
            st.caption(t("s2.eval_size_note", n=eval_data["eval_size"], max=5000))
```

**임계값 기대비용 곡선 교체** — 기존 하드코딩(`dfn=[200*(1-_th)**2 ...]`) 블록을:

```python
        _dyn = st.session_state.get('s2_dyn_eval')
        if _eval_mode == "dynamic" and _dyn and _dyn.get("best_model"):
            cc1, cc2 = st.columns(2)
            with cc1: _fn_c = st.number_input(t("s2.cost_fn_unit"), 1_000, 100_000_000, 1_000_000, step=100_000, key="fn_c")
            with cc2: _fp_c = st.number_input(t("s2.cost_fp_unit"), 100, 10_000_000, 30_000, step=10_000, key="fp_c")
            from pipeline.evaluator import threshold_cost_curve
            import numpy as _np
            _pm = _dyn["per_model"][_dyn["best_model"]]
            curve = threshold_cost_curve(_np.array(_pm["risk"]),
                                         _np.array(st.session_state['s2_dyn_ytrue'][:len(_pm["risk"])]),
                                         fn_cost=_fn_c, fp_cost=_fp_c)
            thresholds, dfn, dfp, dtot = curve["thresholds"], curve["fn"], curve["fp"], curve["total"]
            st.caption(t("s2.cost_optimal", th=curve["optimal_threshold"]))
        else:
            thresholds=np.arange(0.05,1.0,0.02)
            dfn=[200*(1-_th)**2 for _th in thresholds];dfp=[80*_th**1.8 for _th in thresholds];dtot=[a+b for a,b in zip(dfn,dfp)]
            st.caption("※ 시연용 더미 곡선 — 실측은 '실시간 재평가' 모드에서")   # 🐛 지난 리뷰 반영
        # (이하 fig_th 그리는 기존 코드 그대로)
```

⚠️ 주의: `evaluate()`의 `per_model` 안 배열은 `st.cache_data`에 넣지 말 것
(numpy 직렬화 비용). 위처럼 session_state에 직접 보관 권장.

---

## 4. SQL 모델 규약 (models/*.sql)

```sql
-- 대상 테이블명은 반드시 data, 행 순서 유지(ORDER BY 금지)
-- 클래스별 확률 컬럼: proba_<class>  (score_<class>도 허용 — 행별 정규화됨)
SELECT
  CASE WHEN Customer_VPN_Indicator=1 THEN 0.6 ELSE 0.02 END AS proba_a,
  ...
  CASE WHEN ... THEN 0.9 ELSE 0.2 END AS proba_m
FROM data
```
m2cgen(`m2cgen --language sql`) 출력물이 이 규약과 호환됨.

---

## 5. dashboard.py 패치 ③ — 세션 5 배치(묶음) 분석

### 5-1. 각 탭에 일괄 분석 버튼 (tab2/tab3/tab4 공통 패턴)

tab3 예시 — `if st.button(t("s5.run_detect_arrow"),key="run_train2",...)` 줄 **아래**에:

```python
            if len(rl) >= 2:
                if st.button(t("s5.batch_button", n=len(rl)), key="batch_train", width='stretch'):
                    st.session_state['batch_rows'] = rl
                    st.session_state['batch_go'] = True
```
(tab2는 `rp`/key="batch_test", tab4는 `rs`/key="batch_syn" 으로 동일 3줄.
 1건뿐이면 버튼 대신 `st.caption(t("s5.batch_min_warn"))`.)

### 5-2. 배치 실행 + 렌더링 (단건 `if row_to_predict is not None:` 블록 **뒤**에 추가)

```python
    # ── 📦 배치 일괄 분석 — v5 신설 ─────────────────────
    if st.session_state.pop('batch_go', False):
        from pipeline.batch_analyzer import run_batch
        _rows = st.session_state.get('batch_rows', [])
        _pbar = st.progress(0.0, text=t("s5.batch_spinner", i=0, n=len(_rows)))
        def _cb(i, n): _pbar.progress(i/n, text=t("s5.batch_spinner", i=i, n=n))
        _mpath = avail_models.get(st.session_state['selected_model'], {}).get("path", "models/lgbm_fds.pkl")
        _anlz = _build_llm_analyzer() if st.session_state.get('run_with_llm', True) else None
        _rag  = _build_rag(rag_k) if _anlz else None
        st.session_state['batch_res'] = run_batch(
            _rows, _get_ml_classifier(_mpath), threshold=threshold,
            analyzer=_anlz, masker=_build_masker(), rag=_rag,
            lang_suffix=_llm_lang_suffix(), progress_cb=_cb,
        )
        _pbar.empty(); st.rerun()

    _bres = st.session_state.get('batch_res')
    if _bres:
        st.divider(); section_header(t("s5.batch_result_title"), "BATCH")
        b1,b2,b3,b4 = st.columns(4)
        with b1: kpi_card(t("s5.batch_kpi_total"),   f"{_bres.total:,}", None, "📦", T['accent'])
        with b2: kpi_card(t("s5.batch_kpi_anomaly"), f"{_bres.anomaly_count:,}", None, "🚨", T['red'])
        with b3: kpi_card(t("s5.batch_kpi_avg"),     f"{_bres.avg_risk:.4f}", None, "📈", T['amber'])
        with b4: kpi_card(t("s5.batch_kpi_max"),     f"{_bres.max_risk:.4f}", None, "🔥", T['purple'])
        alert_box(f"<b>{t('s5.batch_summary_label')}</b> — {_bres.summary_line}", "info")
        if not _bres.llm_used:
            alert_box(t("s5.batch_llm_fallback_note"), "warn")

        # 정답 보유 표본 정확도 (train_csv 배치일 때)
        _lab = [r for r in _bres.rows_out if r['true_label']]
        if _lab:
            _hit = sum(1 for r in _lab if r['fraud_type'] == r['true_label'])
            st.caption(t("s5.batch_accuracy_note", n=len(_lab), hit=_hit, pct=_hit/len(_lab)*100))

        import html as _html
        st.markdown(f'**{t("s5.batch_report_title")}**')
        st.markdown(  # ⚠ LLM 출력은 반드시 escape (지난 리뷰 XSS 수정과 동일 원칙)
            f'<div style="max-height:420px;overflow-y:auto;background:var(--bg-surface);'
            f'border:1px solid var(--border);border-radius:var(--radius);padding:14px 16px;'
            f'font-family:var(--font-mono);font-size:12px;white-space:pre-wrap;line-height:1.6;'
            f'color:var(--text-secondary)">{_html.escape(_bres.analysis)}</div>',
            unsafe_allow_html=True)

        with st.expander(t("s5.batch_table_title")):
            st.dataframe(pd.DataFrame(_bres.rows_out).drop(columns=['idx']), width='stretch', hide_index=True)

        bb1, bb2, bb3, _ = st.columns([1.2,1.2,1.4,3])
        with bb1:
            if st.button(t("s5.batch_send_slack"), key="batch_slack"):
                ok = _build_notifier().send_slack(_bres.slack)              # 반환값 확인 (지난 리뷰 반영)
                st.toast(t("s5.slack_sent_toast") if ok else t("s5.slack_fail_toast"))
        with bb2:
            if st.button(t("s5.batch_send_email"), key="batch_email"):
                _to = st.session_state.get('notify_email','')
                ok = bool(_to) and _build_notifier().send_email(_to, f"[FDS 배치] 이상 {_bres.anomaly_count}건", _bres.email)
                st.toast(t("s5.email_sent_toast") if ok else t("s5.email_fail_toast"))
        with bb3:
            if st.button(t("s5.batch_clear"), key="batch_clear"):
                st.session_state.pop('batch_res', None); st.rerun()
```

---

## 6. 지난 리뷰 크리티컬 4건 — 이번 패치에 함께 반영 권장

1. **ml_classifier `_dummy_predict` 'm' 분기**: `proba[ft] = round(1-score if ft!='m' else score,4)`
   → `'m'`일 때 `proba['m'] = round(1-score, 4)` 로 (risk=score 유지). 더미 모드 100% 오탐 해소.
2. **`_do_llm_analysis` 자동발송 성공 플래그**: `ok = _build_notifier().send_slack(...)` 반환값으로
   `det['auto_slack_sent'] = ok` (email 동일 + `_to` 비어있으면 시도 없이 False).
3. **main.py `run_pipeline`에 PII 마스킹 삽입**: ⑤ LLM 분석 직전
   `masked = PIIMasker(level="standard").mask_row({k:v for k,v in row.items() if not k.startswith('_')})`
   후 `analyzer.analyze(masked, ...)`.
4. **이메일 미리보기 XSS**: `_email_text` → `html.escape(_email_text)` (위 배치 렌더에도 이미 적용).
5. (보너스) 사이드바 llama URL placeholder `.../completion` → `.../v1/chat/completions`.

---

## 7. 실행 테스트 로그 요약 (이 환경에서 실측)

```
[dataset_loader] CSV·단일 parquet·X_tr+y_tr(ID merge)·X_va+y_va(위치 concat) 로드 OK
                 라벨 컬럼 'label'→Fraud_Type 자동 정규화 / 행수 불일치 ValueError 방어 OK
[model_loader]   pkl(LightGBM 13클래스) OK / ONNX vs sklearn 최대오차 1.27e-07
                 ONNX ZipMap 출력형도 OK / SQL(DuckDB) proba 정규화 OK / pmml 라이브러리 가용
[evaluator]      3모델(pkl+onnx+sql) 교차 비교 · 13×13 CM · classification_report
                 실측 임계값-비용곡선(48pt, 최적 임계값 산출) OK
[batch_analyzer] 60건 배치 0.19초 / "정상 50건, B형 1건, …으로 측정되었습니다" 요약 생성
                 PII 마스킹(이름·IP·거래ID) 확인 / LLM 경로·폴백 경로 모두 OK
```

주의: 합성 데이터라 LightGBM F1=1.0으로 나온 건 과적합이 아니라 픽스처 특성.
실데이터에서는 eval_result.json 수준(macro-F1 ~0.52)이 재현될 것으로 예상.


---

## 8. 【v5.1】 실제 parquet 세트(X_tr/y_tr/X_va/y_va) 검증 결과 및 대응

실파일 4개(96,140행 / 23,860행)로 재검증하면서 발견·반영한 사항:

### 실파일 특성 (검증됨)
| 항목 | 실제 상태 | 대응 |
|---|---|---|
| X 피처 | **82열 전처리 완료형** (인코딩·`*_freq` 파생·`Location_sigungu`) — 원본 48피처 아님 | `passthrough_preprocess()` 신설 — MLClassifier._preprocess 대신 사용 |
| y 라벨 | 컬럼명 `y`, **정수 인코딩 0~12** ('a'~'m' 문자 아님) | 로더가 자동 디코딩: models/le_target.pkl 우선 → 없으면 알파벳 매핑(12=m, 95,198건 다수 클래스로 검증) |
| 인덱스 | X=[2,3,4…](행 드롭 흔적) vs y=[0,1,2…] — **불일치** | 인덱스 결합 금지, 위치(concat) 결합 — 96,140행 전행 원본 y와 일치 검증 |
| `__index_level_0__` | pyarrow 잔재 컬럼 | 로더가 자동 제거 |
| NaN | `amount_to_month_max_ratio`(2,195) 등 4개 파생 컬럼에 존재 | LightGBM/XGBoost는 그대로(NaN native), LogReg/ONNX 비교 시 `passthrough_preprocess(feat, fillna=0)` |

### 세션 2 동적 평가 — 전처리 완료형 데이터셋일 때 (§3 코드에서 교체)
```python
# 라벨 외 전열이 수치형(전처리 완료형)이면 passthrough, 아니면 기존 MLClassifier 전처리
_feat = [c for c in df_eval.columns if c != 'Fraud_Type']
_is_encoded = all(pd.api.types.is_numeric_dtype(df_eval[c]) for c in _feat)
if _is_encoded:
    from pipeline.evaluator import passthrough_preprocess
    prep = passthrough_preprocess(_feat, fillna=0)      # NaN 비허용 모델 포함 비교 시
else:
    prep = make_batch_preprocess(_get_ml_classifier("models/lgbm_fds.pkl"))
```
⚠️ 82피처 데이터셋은 **그 피처로 학습된 모델**과 짝지어야 함. 48피처 lgbm_fds.pkl에
82피처 X를 넣으면 shape 오류 — evaluate()가 모델별로 에러를 격리해 사유를 표시함.

### 세션 5 배치 — 전처리 완료형 행 입력 시
```python
from pipeline.model_loader import make_row_classifier
clf = make_row_classifier("models/lgbm_82feat.pkl", _feat)   # MLClassifier 대신 어댑터
res = run_batch(rows, clf, threshold=threshold, ...)
```

### 실측 검증 로그 (실파일)
```
로더    : tr(96,140×82)·va(23,860×82) 결합, 정수→문자 디코딩 후 원본 y 전행 일치
평가    : LightGBM 실학습(17.7s) → va 23,860행 전량 평가 0.4s, 13×13 CM 생성
비용곡선: 실측 FN/FP 기반 산출 (FN 100만/FP 3만 가정)
배치    : 실 va 100건(사기30+정상70) 0.17s, "정상 99건, E형 1건…" 요약 생성
ONNX   : 실데이터(fillna 후) proba 정상
```
※ 위 macro-F1 수치는 검증용 급조 학습 결과 — 성능 지표가 아닌 배관 검증임.
